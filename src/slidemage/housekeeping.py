"""What "Empty pdf folder" and "Remove temp files" (Housekeeping) would delete, and the deleting.

Free of Qt: the Housekeeping sheet (ui/dialogs/housekeeping.py) shows the counts, the window
(ui/workspace/maintenance.py) asks and calls the removal.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import compiler, deck_snapshot, preview_build, project
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


def delete_files(files: list[Path]) -> None:
    for path in files:
        path.unlink(missing_ok=True)


def find_temp_files(ctx: ProjectContext) -> TempFiles:
    wrappers = list(ctx.decks_dir.rglob("_slidemage_*.tex"))
    if not project.is_snapshot(ctx.root):
        # left behind by an interrupted snapshot; in a snapshot they're its own
        wrappers += ctx.decks_dir.rglob(f"{deck_snapshot.WRAPPER_PREFIX}*.tex")
    scratch = list(ctx.temp_dir.iterdir()) if ctx.temp_dir.exists() else []
    return TempFiles(compiler.removable_build_entries(ctx), [p for p in wrappers if not preview_build.is_active(p)], scratch)


def remove_temp_files(ctx: ProjectContext, found: TempFiles) -> None:
    paths = found.build + found.scratch + found.wrappers
    # A preview can start after the sheet counts files. Both the reservation
    # check and deletion use the same guard, including a live CLI's OS lock.
    with preview_build.cleanup_guard(paths, ctx.root) as permitted:
        if not permitted:
            return
        for path in found.build + found.scratch:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        delete_files(found.wrappers)
