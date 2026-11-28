# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What "Empty pdf folder" and "Remove temp files" (Housekeeping) would delete, and the deleting.

Free of Qt: the Housekeeping sheet (ui/dialogs/housekeeping.py) shows the counts, the window
(ui/workspace/maintenance.py) asks and calls the removal. Startup also prunes forgotten render stores.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from collections.abc import Callable

from . import compiler, deck_snapshot, preview_build, project
from .progress import Progress
from .project import ProjectContext

# The project root's own workflow scratch folder (CONVERSION_NOTES.md) -- where a PPTX
# mid-conversion, a higher-resolution source image waiting to be cropped, or similar working
# input gets placed by hand. Unlike .build/ and decks/_slidemage_*.tex, this isn't SlideMage's
# own build output, but "Remove temp files" (2026-09-18, direct instruction) empties it too.


@dataclass
class TempFiles:
    build: list[Path] = field(default_factory=list)       # items of .build/ (not the compile records)
    wrappers: list[Path] = field(default_factory=list)    # leftover _slidemage_*.tex wrappers in decks/
    scratch: list[Path] = field(default_factory=list)     # items of .temp/

    def __bool__(self) -> bool:
        return bool(self.build or self.wrappers or self.scratch)

    @property
    def count(self) -> int:
        return len(self.build) + len(self.wrappers) + len(self.scratch)


def pdf_files(ctx: ProjectContext) -> list[Path]:
    """The files directly in pdf/."""
    return [p for p in ctx.pdf_dir.iterdir() if p.is_file()] if ctx.pdf_dir.is_dir() else []


def delete_files(files: list[Path], on_progress: Callable[[Progress], None] | None = None) -> None:
    for n, path in enumerate(files, 1):
        path.unlink(missing_ok=True)
        if on_progress:
            on_progress(Progress.step(n, len(files), "Deleting"))


def find_temp_files(ctx: ProjectContext) -> TempFiles:
    wrappers = list(ctx.decks_dir.rglob("_slidemage_*.tex"))
    if not project.is_snapshot(ctx.root):
        # left behind by an interrupted snapshot; in a snapshot they're its own
        wrappers += ctx.decks_dir.rglob(f"{deck_snapshot.WRAPPER_PREFIX}*.tex")
    scratch = list(ctx.temp_dir.iterdir()) if ctx.temp_dir.exists() else []
    return TempFiles(compiler.removable_build_entries(ctx), [p for p in wrappers if not preview_build.is_active(p)], scratch)


def remove_temp_files(ctx: ProjectContext, found: TempFiles,
                      on_progress: Callable[[Progress], None] | None = None) -> None:
    paths = found.build + found.scratch + found.wrappers
    # A preview can start after the sheet counts files. Both the reservation
    # check and deletion use the same guard, including a live CLI's OS lock.
    with preview_build.cleanup_guard(paths, ctx.root) as permitted:
        if not permitted:
            return
        for n, path in enumerate(paths, 1):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            if on_progress:
                on_progress(Progress.step(n, len(paths), "Removing"))


def prune_render_stores(ctx: ProjectContext) -> None:
    """Remove the caches of projects unused for 30 days whose project folder no longer exists; keep the open
    project's. A project's whole cache root goes (one rmtree); render stores that earlier versions left in
    `render-store/<id>/` are judged the same way."""
    current = project.project_cache_dir(ctx.root)
    before = time.time() - 30 * 86400
    candidates = [(folder, folder / project.RENDER_STORE) for folder in (project.cache_dir() / "projects").glob("*")]
    candidates += [(store, store) for store in (project.cache_dir() / "render-store").glob("*")]
    for folder, store in candidates:
        if folder == current or folder == project.legacy_cache_roots(ctx.root)[2]:
            continue
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            if (store / "index.sqlite").stat().st_mtime >= before:
                continue
            marker = store / "project.txt"
            if marker.exists():
                project_folder = marker.read_text(encoding="utf-8")
                if project_folder and Path(project_folder).is_dir():
                    continue
        except (OSError, UnicodeError):
            continue
        shutil.rmtree(folder, ignore_errors=True)
