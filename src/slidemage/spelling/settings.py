# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The spelling preferences of this user, outside the project (<config>/spelling.json). No Qt.

Which variant checks a language that has several (catalogue.VARIANTS), stored as `<language>_variant`:
- `de_variant` (stored as `german_variant` before v0.17.20, still read): "AT" (default, decision S5 a), "DE" or
  "CH". The variants differ in spellings such as Jänner/Januar and, for CH, ß/ss.
- `en_variant`: "US" (default) or "GB": color/colour, analyze/analyse.
"""
from __future__ import annotations

from pathlib import Path

from .. import project
from ..fileio import read_json, write_json
from .catalogue import DEFAULT_VARIANTS, VARIANTS

DEFAULT_GERMAN_VARIANT = DEFAULT_VARIANTS["de"]
DEFAULT_ENGLISH_VARIANT = DEFAULT_VARIANTS["en"]
_OLD_KEYS = {"de": "german_variant"}


def store_path() -> Path:
    return project.config_dir() / "spelling.json"


def variant(language: str) -> str:
    """The variant this user checks `language` in; "" for a language without variants."""
    language = language.lower()
    if language not in VARIANTS:
        return ""
    stored = read_json(store_path())
    value = stored.get(f"{language}_variant", stored.get(_OLD_KEYS.get(language, "")))
    return value if value in VARIANTS[language] else DEFAULT_VARIANTS[language]


def set_variant(language: str, value: str) -> None:
    language = language.lower()
    if value not in VARIANTS.get(language, {}):
        raise ValueError(f"{language} variant must be one of {', '.join(VARIANTS.get(language, {}))}, not {value!r}")
    stored = read_json(store_path())
    stored.pop(_OLD_KEYS.get(language, ""), None)
    write_json(store_path(), {**stored, f"{language}_variant": value})


def german_variant() -> str:
    return variant("de")


def set_german_variant(value: str) -> None:
    set_variant("de", value)


def english_variant() -> str:
    return variant("en")


def set_english_variant(value: str) -> None:
    set_variant("en", value)
