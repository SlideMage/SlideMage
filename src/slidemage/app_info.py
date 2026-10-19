# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the About sheet (ui/dialogs/about.py) shows besides the release history of version.py:
SlideMage's licences, and the one-line form of a history entry.

Free of Qt.
"""
from __future__ import annotations

from pathlib import Path

# The legal files: bundled with the package (packaging/slidemage.spec puts them in slidemage/legal/), else the
# repo root's, when running from a source checkout.
_LEGAL_DIRS = (Path(__file__).resolve().parent / "legal", Path(__file__).resolve().parents[2])
SEPARATOR = "\n\n" + "=" * 72 + "\n\n"


def _legal(name: str) -> str | None:
    for folder in _LEGAL_DIRS:
        try:
            return (folder / name).read_text(encoding="utf-8")
        except OSError:
            continue
    return None


# Below this many characters, an already-short description is shown in full with no toggle:
# there is nothing meaningful left to collapse.
SUMMARY_MAX_CHARS = 200


def license_text() -> str:
    """SlideMage's licences for the About sheet: the LICENSE overview, the third-party notices, then the full text of
    every licence in LICENSES/."""
    overview = _legal("LICENSE")
    if overview is None:
        return "License text not found (not installed, and not in a source checkout)."
    parts = [overview, _legal("THIRD_PARTY_NOTICES.md") or ""]
    for folder in _LEGAL_DIRS:
        texts = sorted((folder / "LICENSES").glob("*.txt")) if (folder / "LICENSES").is_dir() else []
        if texts:
            parts += [f"{file.stem}\n\n{file.read_text(encoding='utf-8', errors='replace')}" for file in texts]
            break
    return SEPARATOR.join(part.strip() for part in parts if part.strip())


def summary(text: str) -> str:
    """The one-line collapsed form of a history entry's description.

    Prefers the first sentence (through the first ". "), since these descriptions are written as
    flowing prose and the first sentence is usually already a fair summary of the whole entry.
    Falls back to a word-boundary truncation when the first sentence alone runs past a line.
    """
    period = text.find(". ")
    if period != -1 and period + 1 <= SUMMARY_MAX_CHARS:
        return text[: period + 1]
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    cut = text.rfind(" ", 0, SUMMARY_MAX_CHARS)
    if cut <= 0:
        cut = SUMMARY_MAX_CHARS
    return text[:cut].rstrip() + "…"
