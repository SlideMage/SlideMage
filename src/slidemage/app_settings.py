# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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

The AI settings of this machine are the exception (v8.58.0, direct instruction: "save all AI model-related settings
in the SlideMage folder structure, not the project folder structure"): MACHINE_KEYS -- the model per route and task,
what Cloud means, the Ollama server and the API key's file fallback -- live in SlideMage's own folder
(project.config_dir()/ai_settings.json, MACHINE_STORE_PATH), for every project on this computer, and never travel
with a synced project. load() and save() split and merge them, so callers see one dict as before; the first load
of a project moves any it still holds out of it (a value this machine already has wins). The project keeps what
is the project's: its Local/Cloud policy (project.json), the Cloud first-use flag, the German form of address and
the prompts.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import diagnostics
from .fileio import read_json, write_json
from .project import ProjectContext, config_dir

_log = logging.getLogger("slidemage.settings")
OLLAMA_HOST_SETTING_KEY = "ollama_host"
MACHINE_STORE_PATH = config_dir() / "ai_settings.json"
# The keys of ai/ai_profile.py (models per route and task, the Cloud connection, and the per-task model keys of
# before v8.0 that it still reads), the Ollama server and ai/credentials.py's API key fallback; ai_draft_model is
# a leftover of an older version.
MACHINE_KEYS = frozenset({
    "ai_models", "cloud_conn", OLLAMA_HOST_SETTING_KEY, "anthropic_api_key",
    "chat_model", "drafting_model", "translation_model", "syntax_check_model", "ai_draft_model",
})
# Duplicated from ai_draft.py/alt_draft.py's own DEFAULT_OLLAMA_HOST
# rather than imported from either -- this module sits below both of them
# in the import graph (they import get_ollama_host() from here), so it
# has no business depending back on either just for one shared constant.
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


def _store_path(ctx: ProjectContext) -> Path:
    return ctx.settings_dir / "app_settings.json"


def peek(ctx: ProjectContext, key: str, default: Any = None) -> Any:
    """Read a legacy setting with machine precedence, without migrating either file."""
    machine = read_json(MACHINE_STORE_PATH)
    if key in MACHINE_KEYS and key in machine:
        return machine[key]
    return read_json(_store_path(ctx)).get(key, default)


def peek_ollama_host(ctx: ProjectContext) -> str:
    return peek(ctx, OLLAMA_HOST_SETTING_KEY) or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST


def load(ctx: ProjectContext) -> dict[str, Any]:
    """The project's settings with this machine's AI settings (MACHINE_KEYS) over them."""
    project_settings = read_json(_store_path(ctx))
    machine = read_json(MACHINE_STORE_PATH)
    moved = {key: project_settings.pop(key) for key in MACHINE_KEYS if key in project_settings}
    if moved:
        machine = {**moved, **machine}
        write_json(MACHINE_STORE_PATH, machine)
        write_json(_store_path(ctx), project_settings)
    return {**project_settings, **{key: value for key, value in machine.items() if key in MACHINE_KEYS}}


def save(ctx: ProjectContext, settings: dict[str, Any]) -> None:
    """`settings` as load() gave it, changed: MACHINE_KEYS to this machine's file (one left out is removed), the
    rest to the project's."""
    machine = {key: value for key, value in read_json(MACHINE_STORE_PATH).items() if key not in MACHINE_KEYS}
    machine.update({key: value for key, value in settings.items() if key in MACHINE_KEYS})
    write_json(MACHINE_STORE_PATH, machine)
    write_json(_store_path(ctx), {key: value for key, value in settings.items() if key not in MACHINE_KEYS})


def get(ctx: ProjectContext, key: str, default: Any = None) -> Any:
    return load(ctx).get(key, default)


def set(ctx: ProjectContext, key: str, value: Any) -> None:
    diagnostics.event(_log, "setting changed", key=key)     # the key only: a value can be a key or a token
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
