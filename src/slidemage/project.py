"""Locate the Slidemaster project (the folder holding slide_ids.csv) to operate on.

Deliberately free of side effects and of imports from the rest of the package:
cli.py must settle the project before deck_scan computes PROJECT_ROOT at import.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MARKER = "slide_ids.csv"
ENV_VAR = "SLIDEMASTER_PROJECT"


def is_project(path: Path) -> bool:
    return (path / MARKER).is_file()


def find_upward(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if is_project(candidate):
            return candidate
    return None


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "SlideMage"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SlideMage"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "slidemage"


def _last_project_file() -> Path:
    return config_dir() / "last_project"


def load_last_project() -> Path | None:
    try:
        path = Path(_last_project_file().read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return path if is_project(path) else None


def save_last_project(path: Path) -> None:
    target = _last_project_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(path), encoding="utf-8")
    except OSError:
        pass


def discover() -> Path | None:
    """$SLIDEMASTER_PROJECT, else upward from the cwd, else the last project opened."""
    env = os.environ.get(ENV_VAR)
    if env and is_project(Path(env)):
        return Path(env).resolve()
    return find_upward(Path.cwd()) or load_last_project()


def relaunch_with_project(root: Path) -> None:
    """Start a fresh SlideMage process pointed at `root` and return --
    never quits the current one itself, since a GUI action needs to
    finish its own event handling first (Qt closes windows/quits the
    QApplication in its caller, after this returns).

    Switching projects can't just mutate the running process's own state:
    deck_scan.PROJECT_ROOT and every directory constant derived from it at
    import time across this whole package (compiler.BUILD_DIR/PDF_DIR,
    slide_source.SLIDES_DIR, alt_images.STORE_PATH, app_settings.STORE_PATH,
    ...) are fixed once, at the first `from . import deck_scan` anywhere
    in the process -- there is no single place left to change them all
    after the fact. A new process re-derives every one of them fresh from
    this one new root, the same as if the user had launched SlideMage
    pointed at `root` from the start.

    Frozen (PyInstaller): sys.executable *is* the SlideMage binary itself,
    so it's relaunched directly. Unfrozen: sys.executable is the Python
    interpreter that's currently running this file as an installed
    package, not as a standalone script, so it needs `-m slidemage` to
    find its way back to the same entry point cli.py's own console-script
    hook (`slidemage = slidemage.cli:main`) uses."""
    save_last_project(root)
    env = os.environ.copy()
    env[ENV_VAR] = str(root)
    argv = (
        [sys.executable, "--project", str(root)]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "slidemage", "--project", str(root)]
    )
    subprocess.Popen(argv, env=env)
