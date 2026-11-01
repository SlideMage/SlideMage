# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The debug log in the window (step 4 of docs/plans/debug-log.md): the commands that switch it, open its folder and
save a debug report (Help menu, Settings -> About, Ctrl+K), and the "Debug log" chip after the AutoSave switch that
shows while it is on, so it is not left on unnoticed (decision D1: it stays on until turned off). Clicking the chip
opens the log folder. The log itself is diagnostics.py."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog, QWidget

from ... import diagnostics, open_path
from ..kit.widgets import Chip

CHIP_TOOLTIP = "The detailed debug log is on. Click to open its folder; Help turns it off."


class DebugChip(Chip):
    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__("Debug log", "warning", icon="bug_report", parent=parent, pressable=True)
        self.setToolTip(CHIP_TOOLTIP)
        self.setAccessibleName("Debug log on")
        self.clicked.connect(lambda: open_folder(window))
        self.refresh()

    def refresh(self) -> None:
        self.setVisible(diagnostics.debug_enabled())


def toggle_title(_window) -> str:
    return "Turn debug log off" if diagnostics.debug_enabled() else "Turn debug log on"


def set_debug(window, on: bool) -> None:
    """Settings -> About and the Help menu: on or off now, and for every SlideMage started later."""
    diagnostics.set_debug(on)
    chip = getattr(window, "debug_chip", None)
    if chip is not None:
        chip.refresh()
        switch = getattr(window, "autosave_switch", None)
        if switch is not None:
            switch.relayout()
    where = diagnostics.debug_log_path()
    window.log(f"Debug log on: {where}" if on and where else "Debug log off")


def toggle(window) -> None:
    set_debug(window, not diagnostics.debug_enabled())


def open_folder(window) -> None:
    folder = diagnostics.debug_log_path().parent if diagnostics.debug_enabled() else diagnostics.log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        open_path.open_in_default_app(folder)
    except OSError as exc:
        window.toast.show_message(f"Could not open {folder}: {exc}", error=True, timeout_ms=6000)


def report_folder() -> Path:
    found = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    return Path(found) if found else Path.home()


def save_report(window) -> None:
    """Ask where, then write the zip there (diagnostics.write_report). Nothing is sent anywhere."""
    start = str(report_folder() / diagnostics.report_name())
    chosen, _ = QFileDialog.getSaveFileName(window, "Save debug report", start, "Zip archive (*.zip)")
    if not chosen:
        return
    target = Path(chosen)
    if target.suffix.lower() != ".zip":
        target = target.with_name(target.name + ".zip")
    try:
        names = diagnostics.write_report(target, window.project.root)
    except OSError as exc:
        window.toast.show_message(f"Could not save the debug report: {exc}", error=True, timeout_ms=6000)
        return
    window.log(f"Debug report saved: {target} ({len(names)} files)")
    window.toast.show_message(f"Debug report saved to {target.name}, in {target.parent}.")
