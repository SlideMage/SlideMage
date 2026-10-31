# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The PDFs SlideMage Presenter showed last (docs/plans/presenter-app.md, step 2): absolute paths, newest first, kept
in the layout store (ui/layout_settings.py) next to the presentation settings. No Qt, so it is unit-testable."""
from __future__ import annotations

import os
from pathlib import Path

from ..ui import layout_settings

STORE_KEY = "presenter_recent"
LIMIT = 10


def _same(path: str) -> str:
    """The key two spellings of one file share (case and slashes on Windows)."""
    return os.path.normcase(os.path.normpath(path))


def _stored() -> list[str]:
    value = layout_settings.get(STORE_KEY, [])
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, list) else []


def add(path: Path | str) -> None:
    """Put `path` first; a second entry for the same file goes, and only the newest LIMIT stay. The store is
    re-read here, so another running program's entries are not lost."""
    new = os.path.abspath(path)
    kept = [item for item in _stored() if _same(item) != _same(new)]
    layout_settings.set(STORE_KEY, [new, *kept][:LIMIT])


def load() -> list[Path]:
    """The recent PDFs, newest first, without the ones that are gone (they stay stored: a drive may come back)."""
    seen: set[str] = set()
    found: list[Path] = []
    for item in _stored():
        if _same(item) in seen:
            continue
        seen.add(_same(item))
        if os.path.isfile(item):
            found.append(Path(item))
    return found[:LIMIT]
