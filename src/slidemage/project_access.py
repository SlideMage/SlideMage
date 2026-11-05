# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Can SlideMage write where it keeps the project's state and builds?

A project in a cloud-synced folder can stop accepting new files while the folder itself still lists: with
Nextcloud's virtual files (and OneDrive's Files On-Demand) the folders are placeholders that only the running
sync client can serve, so without it creating a file in .slidemage/ or .build/ fails ("[Errno 22] Invalid
argument", "access denied") and listing them is refused. Every preference, project.json and render then
failed on its own, with nothing on screen to say why (2026-11-05). problems() tries each folder the way
SlideMage writes to it -- a new temporary file, removed again -- and says which ones refuse; the window
checks on start and every ACCESS_CHECK_INTERVAL_MS (maintenance.py) and tells the user once per outage.
Plain functions, no Qt: called off the GUI thread, as a stalled sync client can make the probe slow.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .project import ProjectContext

PROBE_PREFIX = ".slidemage-probe-"


def folders(ctx: ProjectContext) -> tuple[Path, ...]:
    """The folders SlideMage writes to on its own, without the user asking: its state, the builds and the slides
    (autosave)."""
    return ctx.settings_dir, ctx.build_dir, ctx.slides_dir


def problems(ctx: ProjectContext) -> list[tuple[Path, str]]:
    """(folder, reason) for each folder of folders() that exists and refuses a new file; [] when all accept one.
    A folder that does not exist yet is no problem (it is made when first needed), but a project root that has
    gone is."""
    if not ctx.root.is_dir():
        return [(ctx.root, "the project folder is not there")]
    found = []
    for folder in folders(ctx):
        reason = _probe(folder)
        if reason is not None:
            found.append((folder, reason))
    return found


def _probe(folder: Path) -> str | None:
    try:
        if not folder.exists():
            return None
        fd, name = tempfile.mkstemp(prefix=PROBE_PREFIX, suffix=".tmp", dir=folder)
    except OSError as exc:
        return exc.strerror or str(exc)
    os.close(fd)
    try:
        os.unlink(name)
    except OSError:
        pass        # the folder took the file, which is what is asked
    return None


def message(ctx: ProjectContext, found: list[tuple[Path, str]]) -> str:
    """One sentence for the window: which folders, and the likely cause."""
    names = ", ".join(_name(ctx, folder) for folder, _reason in found)
    return (f"SlideMage can't write to {names} in {ctx.root} ({found[0][1]}). If the project is in a synced "
            "folder (Nextcloud, OneDrive, ...), check that its sync client is running. Settings and previews "
            "won't be saved until then.")


def _name(ctx: ProjectContext, folder: Path) -> str:
    try:
        return folder.relative_to(ctx.root).as_posix() + "/" if folder != ctx.root else "the project folder"
    except ValueError:
        return str(folder)
