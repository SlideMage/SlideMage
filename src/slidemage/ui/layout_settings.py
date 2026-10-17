"""Preferences of this user and machine, outside the project: the window layout, and the model and effort the
Claude Code tab runs its tasks with."""
from __future__ import annotations

from typing import Any

from ..fileio import read_json, write_json
from ..project import config_dir

STORE_PATH = config_dir() / "layout.json"


def get(key: str, default: Any = None) -> Any:
    return read_json(STORE_PATH).get(key, default)


def set(key: str, value: Any) -> None:
    write_json(STORE_PATH, {**read_json(STORE_PATH), key: value})
