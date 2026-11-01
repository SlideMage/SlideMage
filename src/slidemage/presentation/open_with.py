# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offer SlideMage Presenter under "Open with" for PDF files (docs/plans/presenter-app.md, step 5a), without Qt.

The Presenter is unpacked from a zip, not installed, so nothing registers it. This writes per-user entries, no
administrator rights needed, and never changes the default PDF program:
- Windows: HKCU\\Software\\Classes keys (a ProgID, an OpenWithProgids value for .pdf, an Applications entry).
- Linux: a .desktop file in $XDG_DATA_HOME/applications (default ~/.local/share/applications).
- macOS: nothing to do here, the .app's Info.plist declares PDFs.

Only a frozen build registers itself: a source checkout would register python.exe. The registry, the file system and
the "tell the system" calls are injectable, so tests never touch the real ones. `winreg` is imported when needed."""
from __future__ import annotations

import ntpath
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Protocol

PROG_ID = "SlideMage.Presenter.pdf"
APP_KEY = "SlideMagePresenter.exe"
APP_NAME = "SlideMage Presenter"
PROG_ID_DESCRIPTION = "PDF document (SlideMage Presenter)"
DESKTOP_FILE = "slidemage-presenter.desktop"
ICON_FILE = "presenter-icon-256.png"

# The desktop entry written on Linux; packaging/slidemage-presenter.desktop.template carries the same keys with
# placeholders for people who install by hand (tests/test_presenter_open_with.py keeps the two in step).
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=SlideMage Presenter
Comment=Present a PDF with the presenter view of SlideMage
Exec={exec}
Icon={icon}
Terminal=false
NoDisplay=false
Categories=Office;Presentation;
MimeType=application/pdf;
StartupWMClass=SlideMage Presenter
"""

OFF, ON, MOVED = "off", "on", "moved"
SHCNE_ASSOCCHANGED = 0x08000000


def _windows() -> bool:
    return sys.platform == "win32"


def supported() -> bool:
    """True for a frozen Windows or Linux build; a source checkout and macOS (Info.plist) have nothing to register."""
    return bool(getattr(sys, "frozen", False)) and sys.platform in ("win32", "linux")


# -- Windows -----------------------------------------------------------------------------------

class Registry(Protocol):
    """The few HKCU operations the Windows part needs; tests pass a fake."""

    def set_value(self, key: str, name: str, value: str) -> None: ...
    def set_empty_value(self, key: str, name: str) -> None: ...
    def get_value(self, key: str, name: str) -> Optional[str]: ...
    def delete_value(self, key: str, name: str) -> None: ...
    def delete_tree(self, key: str) -> None: ...


class HkcuRegistry:
    """The real registry, under HKEY_CURRENT_USER. Missing keys and values are fine for the deletes."""

    def __init__(self) -> None:
        import winreg
        self.winreg = winreg

    def set_value(self, key: str, name: str, value: str) -> None:
        w = self.winreg
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, key, 0, w.KEY_SET_VALUE) as handle:
            w.SetValueEx(handle, name, 0, w.REG_SZ, value)

    def set_empty_value(self, key: str, name: str) -> None:
        w = self.winreg
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, key, 0, w.KEY_SET_VALUE) as handle:
            w.SetValueEx(handle, name, 0, w.REG_NONE, b"")

    def get_value(self, key: str, name: str) -> Optional[str]:
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, key, 0, w.KEY_READ) as handle:
                value, _kind = w.QueryValueEx(handle, name)
        except FileNotFoundError:
            return None
        return value if isinstance(value, str) else None

    def delete_value(self, key: str, name: str) -> None:
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, key, 0, w.KEY_SET_VALUE) as handle:
                w.DeleteValue(handle, name)
        except FileNotFoundError:
            pass

    def delete_tree(self, key: str) -> None:
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, key, 0, w.KEY_READ | w.KEY_SET_VALUE) as handle:
                while True:
                    try:
                        child = w.EnumKey(handle, 0)
                    except OSError:
                        break
                    self.delete_tree(key + "\\" + child)
        except FileNotFoundError:
            return
        try:
            w.DeleteKey(w.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def notify_associations_changed() -> None:
    """Tell Explorer that file associations changed (SHChangeNotify), so "Open with" is rebuilt at once."""
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, 0, None, None)


PROG_ID_KEY = "Software\\Classes\\" + PROG_ID
OPEN_WITH_KEY = "Software\\Classes\\.pdf\\OpenWithProgids"
APP_ROOT_KEY = "Software\\Classes\\Applications\\" + APP_KEY


def _command(executable: str) -> str:
    return f'"{executable}" "%1"'


def _executable_in(command: Optional[str]) -> Optional[str]:
    """The program of a registered command line: the first quoted part (or the text up to the first space)."""
    if not command:
        return None
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 0 else None
    return command.split(" ", 1)[0] or None


def _same_path(a: str, b: str) -> bool:
    return ntpath.normcase(ntpath.normpath(a)) == ntpath.normcase(ntpath.normpath(b))


def _register_windows(executable: str, registry: Registry, notify: Callable[[], None]) -> None:
    command = _command(executable)
    registry.set_value(PROG_ID_KEY, "", PROG_ID_DESCRIPTION)
    registry.set_value(PROG_ID_KEY + "\\DefaultIcon", "", f'"{executable}",0')
    registry.set_value(PROG_ID_KEY + "\\shell\\open", "FriendlyAppName", APP_NAME)
    registry.set_value(PROG_ID_KEY + "\\shell\\open\\command", "", command)
    # REG_NONE with no data: what Windows itself writes for the programs it lists here.
    registry.set_empty_value(OPEN_WITH_KEY, PROG_ID)
    registry.set_value(APP_ROOT_KEY, "FriendlyAppName", APP_NAME)
    registry.set_value(APP_ROOT_KEY + "\\shell\\open\\command", "", command)
    registry.set_value(APP_ROOT_KEY + "\\SupportedTypes", ".pdf", "")
    notify()


def _unregister_windows(registry: Registry, notify: Callable[[], None]) -> None:
    registry.delete_tree(PROG_ID_KEY)
    registry.delete_value(OPEN_WITH_KEY, PROG_ID)
    registry.delete_tree(APP_ROOT_KEY)
    notify()


def _registered_windows(registry: Registry) -> Optional[str]:
    return _executable_in(registry.get_value(PROG_ID_KEY + "\\shell\\open\\command", ""))


# -- Linux -------------------------------------------------------------------------------------

def applications_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "applications"


def desktop_file() -> Path:
    return applications_dir() / DESKTOP_FILE


def desktop_text(executable: str) -> str:
    """The desktop entry for the program at `executable`; Exec quotes the path, the icon sits beside the program."""
    icon = str(Path(executable).parent / ICON_FILE)
    return DESKTOP_ENTRY.format(exec=f'"{executable}" %f', icon=icon)


def run_update_desktop_database(directory: Path) -> None:
    """Refresh the MIME cache when the tool exists; a failure only means "Open with" shows up at the next login."""
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, str(directory)], check=False, timeout=30, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass


def _register_linux(executable: str, runner: Callable[[Path], None]) -> None:
    path = desktop_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_text(executable), encoding="utf-8")
    runner(path.parent)


def _unregister_linux(runner: Callable[[Path], None]) -> None:
    path = desktop_file()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    runner(path.parent)


def _registered_linux() -> Optional[str]:
    try:
        text = desktop_file().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if line.startswith("Exec="):
            return _executable_in(line[len("Exec="):])
    return None


# -- the public calls --------------------------------------------------------------------------

def status(executable: str, registry: Optional[Registry] = None) -> str:
    """OFF (not registered), ON (registered for `executable`) or MOVED (registered for another path)."""
    if _windows():
        registered = _registered_windows(registry or HkcuRegistry())
        same = registered is not None and _same_path(registered, executable)
    else:
        registered = _registered_linux()
        same = registered is not None and os.path.normpath(registered) == os.path.normpath(executable)
    if registered is None:
        return OFF
    return ON if same else MOVED


def register(executable: str, registry: Optional[Registry] = None, notify: Optional[Callable[[], None]] = None,
             runner: Optional[Callable[[Path], None]] = None) -> None:
    """Add the Presenter at `executable` to "Open with" for PDFs. Raises OSError when the system refuses."""
    if _windows():
        _register_windows(executable, registry or HkcuRegistry(), notify or notify_associations_changed)
    else:
        _register_linux(executable, runner or run_update_desktop_database)


def unregister(registry: Optional[Registry] = None, notify: Optional[Callable[[], None]] = None,
               runner: Optional[Callable[[Path], None]] = None) -> None:
    """Remove exactly what register() added; nothing to remove is fine."""
    if _windows():
        _unregister_windows(registry or HkcuRegistry(), notify or notify_associations_changed)
    else:
        _unregister_linux(runner or run_update_desktop_database)
