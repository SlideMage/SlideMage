# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferences of this user and machine, outside the project: the window layout, and the model and effort the
Claude Code tab runs its tasks with."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .. import diagnostics, project
from ..fileio import JsonStore

_log = logging.getLogger("slidemage.settings")

def store_path() -> Path:
    return project.config_dir() / "layout.json"


def get(key: str, default: Any = None) -> Any:
    return JsonStore(store_path()).read().get(key, default)


def set(key: str, value: Any) -> None:
    diagnostics.event(_log, "setting changed", key=key)
    JsonStore(store_path()).update(lambda data: data.update({key: value}), strict=False)
