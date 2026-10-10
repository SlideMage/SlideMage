"""Persisted, user-editable system prompts for the two Ollama-backed
features that rewrite/generate text but aren't translation:
alt_draft.py's image-description drafting, and ai_draft.py's whole-slide
AI rewrite (2026-09-23, review finding -- both used to be hardcoded
SYSTEM_PROMPT constants with no way to tune them without editing source,
unlike translation_prompts.py's own already-customizable prompts).

One prompt per kind, not translation_prompts.py's per-(model, source
language, target language) grid -- neither drafting nor slide-rewrite has
a language-pair dimension, and there was no request for per-model
tuning here, so this stays the simpler shape rather than inventing
unrequested granularity. Same two-level fallback as
translation_prompts.get_effective_prompt(), though: a user-set prompt if
one exists, else the calling module's own hardcoded default.

On-disk shape (media/alt-text.json-style: plain, human-readable, hand-
editable in a pinch):

    {"image_draft": "...", "slide_rewrite": "..."}

Tracked in git, like translation_prompts.json (not gitignored like
app_settings.json's own per-machine UI preferences) -- which model
prompts describe this project's images is project content worth
sharing/versioning, not one machine's own throwaway local state.
"""
from __future__ import annotations

import json

from .deck_scan import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / ".slidemage" / "draft_prompts.json"

KIND_IMAGE_DRAFT = "image_draft"
KIND_SLIDE_REWRITE = "slide_rewrite"


def _load_raw() -> dict[str, str]:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_custom_prompt(kind: str) -> str | None:
    """The user's own saved prompt for `kind`, or None if they've never
    edited it (or cleared it back to blank) -- callers fall back to their
    own hardcoded default in that case (alt_draft.SYSTEM_PROMPT /
    ai_draft.SYSTEM_PROMPT)."""
    return _load_raw().get(kind) or None


def set_custom_prompt(kind: str, prompt: str, default: str = "") -> None:
    """Empty/whitespace-only clears the override, reverting to the
    hardcoded default. So does a prompt equal to `default` (the caller's
    hardcoded one): saving the stock text verbatim is the same as never
    having customized it, and a stored copy would silently diverge once the
    default is revised in a code update."""
    raw = _load_raw()
    prompt = prompt.strip()
    if prompt and prompt != default.strip():
        raw[kind] = prompt
    else:
        raw.pop(kind, None)
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
