# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter's update notice, without Qt (docs/plans/presenter-app.md, step 4): when to look for a newer
release, which release counts, and how to install it.

A release carries the Presenter's zip only when it changes the Presenter (release.yml), and plan_update() with
`need_asset=True` skips a release without this platform's zip, so the Presenter is told only about releases that
concern it. The update mode is the one SlideMage shares ("off" never checks). The time of the last successful check
is kept in the layout store, so the program looks at most once a day. The updater is imported when needed: it pulls
in urllib, which the start window does not need."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from ..ui import layout_settings
from ..version import VERSION_NUMBER

STORE_KEY = "presenter_update_checked"      # time.time() of the last successful check
CHECK_INTERVAL = 24 * 3600                  # seconds between two checks


def check_due(now: Optional[float] = None) -> bool:
    """True when the update mode allows a check and the last one is a day old (or none is known, or the clock went
    back)."""
    from .. import updater

    if updater.get_update_mode() == updater.UPDATE_MODE_OFF:
        return False
    now = time.time() if now is None else now
    last = layout_settings.get(STORE_KEY)
    if isinstance(last, bool) or not isinstance(last, (int, float)):
        return True
    return not 0 <= now - last < CHECK_INTERVAL


def mark_checked(now: Optional[float] = None) -> None:
    layout_settings.set(STORE_KEY, time.time() if now is None else now)


def find_update(current: str = VERSION_NUMBER):
    """The newest release newer than `current` that carries the Presenter's zip for this system, or None.
    Raises updater.UpdateError when GitHub cannot be reached. Remembers the time of a successful check."""
    from .. import updater

    releases = updater.fetch_releases(flavour=updater.PRESENTER)
    mark_checked()
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
