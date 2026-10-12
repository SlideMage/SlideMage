"""Persisted, user-editable system prompt for alt_draft.py's image-description
drafting (2026-09-23, review finding -- it used to be a hardcoded
SYSTEM_PROMPT constant with no way to tune it without editing source,
unlike translation_prompts.py's own already-customizable prompts). The
whole-slide rewrite prompt that shared this store went with the rewrite
dialog (2026-10-10); a stored "slide_rewrite" entry is simply ignored.

One prompt per kind, not translation_prompts.py's per-(model, source
language, target language) grid -- drafting has no language-pair
dimension, and there was no request for per-model tuning here. Same two-level fallback as
translation_prompts.get_effective_prompt(), though: a user-set prompt if
one exists, else the calling module's own hardcoded default.

On-disk shape (media/alt-text.json-style: plain, human-readable, hand-
editable in a pinch):

    {"image_draft": "..."}

Tracked in git, like translation_prompts.json (not gitignored like
app_settings.json's own per-machine UI preferences) -- which model
prompts describe this project's images is project content worth
sharing/versioning, not one machine's own throwaway local state.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import project
from .alt_images import atomic_write_text

KIND_IMAGE_DRAFT = "image_draft"


def _store_path() -> Path:
    return project.transitional_context().settings_dir / "draft_prompts.json"


def _load_raw() -> dict[str, str]:
    """The stored prompts; a file that cannot be read or is not the documented shape counts as empty,
    and entries that are not text are dropped."""
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):    # a missing file, no permission, not UTF-8 (UnicodeDecodeError), bad JSON
        return {}
    if not isinstance(data, dict):
        return {}
    return {kind: prompt for kind, prompt in data.items() if isinstance(prompt, str)}


def get_custom_prompt(kind: str) -> str | None:
    """The user's own saved prompt for `kind`, or None if they've never
    edited it (or cleared it back to blank) -- callers fall back to their
    own hardcoded default in that case (alt_draft.SYSTEM_PROMPT)."""
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
    atomic_write_text(_store_path(), json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
