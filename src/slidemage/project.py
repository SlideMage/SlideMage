"""Locate the Slidemaster project (the folder holding slide_ids.csv) to operate on.

Deliberately free of side effects and of imports from the rest of the package:
cli.py must settle the project before deck_scan computes PROJECT_ROOT at import.
"""
from __future__ import annotations

import os
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
    """$SLIDEMASTER_PROJECT, else upward from the cwd, else upward from a frozen
    exe's own folder (PyInstaller's __file__ is a throwaway temp dir), else the
    last project opened."""
    env = os.environ.get(ENV_VAR)
    if env and is_project(Path(env)):
        return Path(env).resolve()
    found = find_upward(Path.cwd())
    if found is None and getattr(sys, "frozen", False):
        found = find_upward(Path(sys.executable).parent)
    return found or load_last_project()
