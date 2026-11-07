# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared template edits for compat migrations; format-specific matching stays with each change."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path


def template_paths(root: Path) -> Iterator[Path]:
    yield from sorted(root.glob("SlideMage_template_*.tex"))


def read_template_lines(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n").split("\n"), ("\r\n" if "\r\n" in raw else "\n")


def drop_template_lines(root: Path, hits: Callable[[list[str]], list[int]],
                        intro: Callable[[list[str], int], bool]) -> dict[Path, bytes]:
    """Plan removals without writing: old templates keep their line endings and final newline, if any."""
    plan: dict[Path, bytes] = {}
    for path in template_paths(root):
        try:
            lines, eol = read_template_lines(path)
        except (OSError, UnicodeDecodeError):
            continue
        found = hits(lines)
        if not found:
            continue
        drop: set[int] = set()
        for at in found:
            drop.add(at)
            if intro(lines, at):
                drop.add(at - 1)
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        plan[path.relative_to(root)] = eol.join(kept).encode("utf-8")
    return plan
