# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers for the words the UI shows."""
from __future__ import annotations


def plural(count: int, word: str) -> str:
    """"1 slide", "3 slides"."""
    return f"{count} {word}{'' if count == 1 else 's'}"
