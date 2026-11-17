# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A project's own words, per language (decision S2 a). No Qt.

`spelling-words-<lang>.txt` in the project folder, one word per line, so co-authors share the list through the
project. Lines are kept sorted (case ignored) and unique, so two people adding words merge cleanly. A word on the
list is never underlined, in any case ("SlideMage" also covers "slidemage"), and is never sent to a checker.
Blank lines and lines starting with # are ignored, so the file may carry a comment.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..fileio import atomic_write
from .checker import normalized

_cache: dict[Path, tuple[tuple[int, int], frozenset[str]]] = {}
_lock = threading.Lock()


def path(root: Path, language: str) -> Path:
    return Path(root) / f"spelling-words-{language.lower()}.txt"


def _key(word: str) -> str:
    return normalized(word).casefold()


def _lines(file: Path) -> list[str]:
    try:
        return file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def words(root: Path, language: str) -> frozenset[str]:
    """The list's words, case-folded (compare with `contains()`). Read again only when the file changed."""
    file = path(root, language)
    try:
        stat = file.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return frozenset()
    with _lock:
        cached = _cache.get(file)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    found = frozenset(_key(line.strip()) for line in _lines(file)
                      if line.strip() and not line.lstrip().startswith("#"))
    with _lock:
        _cache[file] = (stamp, found)
    return found


def contains(root: Path, language: str, word: str) -> bool:
    return _key(word) in words(root, language)


def add(root: Path, language: str, word: str) -> bool:
    """Put `word` on the list (False if it is there already, in any case). Comments stay at the top."""
    word = normalized(word).strip()
    if not word or any(c.isspace() for c in word):
        raise ValueError(f"not one word: {word!r}")
    file = path(root, language)
    lines = _lines(file)
    comments = [line for line in lines if line.lstrip().startswith("#")]
    entries = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if _key(word) in {_key(e) for e in entries}:
        return False
    entries = sorted({*entries, word}, key=lambda e: (_key(e), e))
    atomic_write(file, "".join(f"{line}\n" for line in [*comments, *entries]))
    with _lock:
        _cache.pop(file, None)
    return True
