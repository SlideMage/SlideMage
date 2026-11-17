# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The spelling preferences of this user, outside the project (<config>/spelling.json). No Qt.

- `german_variant`: which German dictionary checks German text, "AT" (default, decision S5 a), "DE" or "CH". The
  variants differ in spellings such as Jänner/Januar and, for CH, ß/ss.
"""
from __future__ import annotations

from pathlib import Path

from .. import project
from ..fileio import read_json, write_json
from .catalogue import GERMAN_VARIANTS

DEFAULT_GERMAN_VARIANT = "AT"


def store_path() -> Path:
    return project.config_dir() / "spelling.json"


def german_variant() -> str:
    value = read_json(store_path()).get("german_variant")
    return value if value in GERMAN_VARIANTS else DEFAULT_GERMAN_VARIANT


def set_german_variant(variant: str) -> None:
    if variant not in GERMAN_VARIANTS:
        raise ValueError(f"German variant must be one of {', '.join(GERMAN_VARIANTS)}, not {variant!r}")
    write_json(store_path(), {**read_json(store_path()), "german_variant": variant})
