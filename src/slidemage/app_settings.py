"""Local SlideMage UI preferences -- dark mode, plus (2026-08-25,
direct instruction) the preferred translation and other AI models.
Older per-feature model choices remain readable as a migration fallback.
A plain JSON file lives inside SlideMage/ itself, not the Windows registry (2026-08-25,
direct instruction, replacing an earlier QSettings-based design used for
one day: "I want everything pertaining to SlideMage to be saved in its
proper folder, and for the app to work as long as that folder is
synched"). This project's entire folder already lives in a synced
location (D:\\uniCLOUD\\...); a registry entry is tied to one specific
PC's own registry and would NOT travel with the folder to another machine
the way a plain file inside it does.

Gitignored (see .gitignore) -- unlike translation_prompts.py's own store,
this is a personal UI preference, not project content worth version-
controlling or diffing on every toggle, but it still needs to physically
sit inside the synced folder tree for the cloud-sync client itself (not
git) to carry it across machines.

STORE_PATH is resolved from deck_scan.PROJECT_ROOT, i.e. it lives in the
project's .slidemage/ folder, next to translation_prompts.json.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .deck_scan import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / ".slidemage" / "app_settings.json"

OLLAMA_HOST_SETTING_KEY = "ollama_host"
OTHER_MODEL_SETTING_KEY = "other_model"
# Duplicated from ai_draft.py/alt_draft.py's own DEFAULT_OLLAMA_HOST
# rather than imported from either -- this module sits below both of them
# in the import graph (they import get_ollama_host() from here), so it
# has no business depending back on either just for one shared constant.
_FALLBACK_OLLAMA_HOST = "http://localhost:11434"


def load() -> dict[str, Any]:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save(settings: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set(key: str, value: Any) -> None:
    settings = load()
    settings[key] = value
    save(settings)


def get_other_model() -> str | None:
    """The shared non-translation model, with a legacy preference fallback."""
    settings = load()
    for key in (OTHER_MODEL_SETTING_KEY, "drafting_model", "ai_draft_model",
                "syntax_check_model"):
        if settings.get(key):
            return settings[key]
    return None


def get_ollama_host() -> str:
    """The Ollama server every drafting/translation/AI-rewrite call should
    use (2026-09-23, review finding: this used to be a hardcoded
    "http://localhost:11434" in two separate modules, with no way to
    point this app at Ollama running elsewhere -- a different machine, a
    non-default port, WSL, ...).

    Resolution order: the Preferences dialog's own saved value if the
    user has set one, else $OLLAMA_HOST (Ollama's own conventional
    environment variable, so a script/CI run can point this app at a
    different server without touching its settings file), else the plain
    localhost default."""
    saved = get(OLLAMA_HOST_SETTING_KEY)
    if saved:
        return saved
    return os.environ.get("OLLAMA_HOST") or _FALLBACK_OLLAMA_HOST


def set_ollama_host(host: str) -> None:
    """Empty/whitespace-only clears the saved override, falling back to
    $OLLAMA_HOST/the plain default again -- same "empty means unset"
    convention draft_prompts.set_custom_prompt() uses."""
    settings = load()
    host = host.strip()
    if host:
        settings[OLLAMA_HOST_SETTING_KEY] = host
    else:
        settings.pop(OLLAMA_HOST_SETTING_KEY, None)
    save(settings)


# Default Ollama model per AI task (2026-09-26, direct instruction), set in
# Settings -> "AI models" and read by every place that offers a model
# picker -- which now only *preselects* this default; picking another
# model there applies to that dialog/tab only and is no longer remembered
# as "whatever was used last". The setting keys are the same ones the old
# remember-last-choice code used, so an existing app_settings.json keeps
# working as the initial default.
MODEL_SETTINGS: dict[str, str] = {
    "syntax_check": "syntax_check_model",
    "ai_draft": "ai_draft_model",
    "image_description": "drafting_model",
    "translation": "translation_model",
}


def default_model(task: str) -> str:
    """The configured default model name for `task` (a MODEL_SETTINGS
    key), or "" when none has been chosen yet."""
    return str(get(MODEL_SETTINGS[task]) or "")
