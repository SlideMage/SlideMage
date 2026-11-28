# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which text files of the project changed on disk (UI redesign step 10c: Claude Code edits
files, SlideMage keeps its views in step). A cheap poll instead of OS file watching: `scan()` stats the
project's text files, `diff()` compares two scans. No Qt.

The same files are visible here as to the agent tools (tools/files.py `is_hidden`): dot-folders
(`.build/`, `.slidemage/`, `.git/` ...) and `pdf/` do not exist, and only text files count. The review store is the one explicit exception: a hook
can mark a slide after the poll already saw its source write.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..deck_scan import is_generated_wrapper
from ..project import ProjectContext
from .tools.edits import EDITABLE_SUFFIXES
from .tools.files import HIDDEN_FOLDERS

Scan = dict[Path, tuple[int, int]]       # path -> (modification time in ns, size)


@dataclass(frozen=True)
class Changes:
    added: tuple[Path, ...] = ()
    removed: tuple[Path, ...] = ()
    modified: tuple[Path, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.modified)


def scan(root: Path) -> Scan:
    found: Scan = {}
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    hidden = entry.name.startswith(".") or (folder == root and entry.name in HIDDEN_FOLDERS)
                    if not hidden:
                        pending.append(Path(entry.path))
                elif (entry.name.lower().endswith(EDITABLE_SUFFIXES) and not entry.name.startswith(".")
                      and not is_generated_wrapper(entry.name)):
                    info = entry.stat()
                    found[Path(entry.path)] = (info.st_mtime_ns, info.st_size)
            except OSError:
                continue            # gone while scanning
    review = ProjectContext.at(root).ai_review_path
    try:
        info = review.stat()
        found[review] = (info.st_mtime_ns, info.st_size)
    except OSError:
        pass
    return found


def diff(old: Scan, new: Scan) -> Changes:
    return Changes(
        added=tuple(sorted(new.keys() - old.keys())),
        removed=tuple(sorted(old.keys() - new.keys())),
        modified=tuple(sorted(p for p in new.keys() & old.keys() if new[p] != old[p])))
