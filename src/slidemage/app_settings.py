"""Local SlideMage UI preferences -- dark mode, the Ollama host, and the saved
settings of the AI routes (ai/ai_profile.py reads and writes those keys).
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

The file is the project's .slidemage/app_settings.json (ProjectContext.settings_dir),
next to translation_prompts.json; every function takes the ProjectContext it belongs to.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .fileio import read_json, write_json
from .project import ProjectContext

OLLAMA_HOST_SETTING_KEY = "ollama_host"
# Duplicated from ai_draft.py/alt_draft.py's own DEFAULT_OLLAMA_HOST
# rather than imported from either -- this module sits below both of them
# in the import graph (they import get_ollama_host() from here), so it
# has no business depending back on either just for one shared constant.
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def _store_path(ctx: ProjectContext) -> Path:
    return ctx.settings_dir / "app_settings.json"


def load(ctx: ProjectContext) -> dict[str, Any]:
    return read_json(_store_path(ctx))


def save(ctx: ProjectContext, settings: dict[str, Any]) -> None:
    write_json(_store_path(ctx), settings)


def get(ctx: ProjectContext, key: str, default: Any = None) -> Any:
    return load(ctx).get(key, default)


def set(ctx: ProjectContext, key: str, value: Any) -> None:
    settings = load(ctx)
    settings[key] = value
    save(ctx, settings)


def get_ollama_host(ctx: ProjectContext) -> str:
    """The Ollama server every drafting/translation/AI-rewrite call should
    use (2026-09-23, review finding: this used to be a hardcoded
    "http://localhost:11434" in two separate modules, with no way to
    point this app at Ollama running elsewhere -- a different machine, a
    non-default port, WSL, ...).

    Resolution order: the Settings sheet's own saved value if the
    user has set one, else $OLLAMA_HOST (Ollama's own conventional
    environment variable, so a script/CI run can point this app at a
    different server without touching its settings file), else the plain
    localhost default."""
    saved = get(ctx, OLLAMA_HOST_SETTING_KEY)
    if saved:
        return saved
    return os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST


def set_ollama_host(ctx: ProjectContext, host: str) -> None:
    """Empty/whitespace-only clears the saved override, falling back to
    $OLLAMA_HOST/the plain default again -- same "empty means unset"
    convention draft_prompts.set_custom_prompt() uses."""
    settings = load(ctx)
    host = host.strip()
    if host:
        settings[OLLAMA_HOST_SETTING_KEY] = host
    else:
        settings.pop(OLLAMA_HOST_SETTING_KEY, None)
    save(ctx, settings)
