# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter's update notice, without Qt (docs/plans/presenter-app.md, step 4): when to look for a newer
release, which release counts, and how to install it.

A release carries the Presenter's zip only when it changes the Presenter (release.yml), and plan_update() with
`need_asset=True` skips a release without this platform's zip, so the Presenter is told only about releases that
concern it. The update mode is the one SlideMage shares ("off" never checks). It looks at every start, in the
background: one small request. Once a day was too rare, a release was not offered for up to 24 hours after the
last look (up to v0.13.11). The updater is imported when needed: it pulls in urllib, which the start window does
not need."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from ..version import VERSION_NUMBER

def check_allowed() -> bool:
    """False when the shared update mode says never to look."""
    from .. import updater

    return updater.get_update_mode() != updater.UPDATE_MODE_OFF


def find_update(current: str = VERSION_NUMBER):
    """The newest release newer than `current` that carries the Presenter's zip for this system, or None.
    Raises updater.UpdateError when GitHub cannot be reached."""
    from .. import updater

    releases = updater.fetch_releases(flavour=updater.PRESENTER)
    return updater.plan_update(releases, current, need_asset=True).latest


def can_install() -> bool:
    """True for a frozen Windows or Linux build; the macOS app and a source checkout only open the release page."""
    from .. import updater

    return updater.can_self_update()


def install(release, relaunch: bool = True, progress: Optional[Callable[[int, int], bool]] = None) -> None:
    """Download `release`'s zip, unpack it next to the running folder and start the helper that swaps the folders
    once this process has ended (and starts the new Presenter, if `relaunch`). The caller then quits. Raises
    updater.UpdateError."""
    from .. import updater

    binary = updater.asset_names(updater.PRESENTER)[1]
    folder = Path(sys.executable).parent
    with tempfile.TemporaryDirectory(prefix="slidemage-update-") as tmp:
        zip_path = Path(tmp) / "update.zip"
        updater.download(release, zip_path, progress or (lambda _done, _total: True))
        staging = updater.stage_folder_update(zip_path, folder, binary)
    updater.spawn_folder_swap(folder, staging, binary, [] if relaunch else None)


def remove_leftover() -> None:
    """At the start of a frozen Windows or Linux build: delete the folder an earlier update left as "<folder>.old"."""
    from .. import updater

    if updater.can_self_update():
        updater.remove_leftover_folder(Path(sys.executable).parent)
