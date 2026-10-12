"""Preferences of this user and machine, outside the project: the window layout, and the model and effort the
Claude Code tab runs its tasks with."""
from __future__ import annotations

import json
from typing import Any

from ..project import config_dir

STORE_PATH = config_dir() / "layout.json"


def _load() -> dict[str, Any]:
    try:
        settings = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return settings if isinstance(settings, dict) else {}


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


def set(key: str, value: Any) -> None:
    settings = _load()
    settings[key] = value
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
