# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""TeX and Perl folders that are missing from this process's PATH, added once at start-up (cli.main).

A program inherits PATH from whatever started it. Right after an installer put MiKTeX or Perl on the computer, that
is often the old PATH: the setup program itself (SlideMage-Setup.exe, which runs `--self-test --compile` and may
start SlideMage when it ends) and an Explorer that has not picked the change up yet. SlideMage would then not find
lualatex, latexmk or perl although they are installed. So, on Windows, extend_path() adds

* the folders of the user's and the computer's PATH in the registry that this process's PATH lacks, and
* the usual installation folders of MiKTeX, TeX Live and Strawberry Perl, where they exist and are not on PATH yet
  (the installers put portable Strawberry Perl in PERL_PORTABLE_DIR);

on Linux, the newest upstream TeX Live in /usr/local/texlive when no lualatex is on PATH. Folders are only ever
appended, so whatever the user put on PATH first still wins.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# Where SlideMage-Setup.exe unpacks portable Strawberry Perl (packaging/slidemage.iss): per user, no administrator.
PERL_PORTABLE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / "StrawberryPerl"


def _windows_registry_path() -> list[str]:
    """The user's PATH, then the computer's, as the registry holds them now, with %VARIABLES% expanded."""
    try:
        import winreg
    except ImportError:
        return []
    parts: list[str] = []
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _kind = winreg.QueryValueEx(handle, "Path")
        except OSError:
            continue
        parts += [os.path.expandvars(p) for p in str(value).split(os.pathsep) if p.strip()]
    return parts


def _windows_known_dirs() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    program_files = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    dirs = [local / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64",
            program_files / "MiKTeX" / "miktex" / "bin" / "x64"]
    dirs += [texlive / "bin" / platform for texlive in _newest_first(Path(r"C:\texlive"))
             for platform in ("windows", "win64", "win32")]
    # perl\bin only: Strawberry's c\bin (gcc, make, ...) would shadow other programs, and latexmk needs none of it.
    dirs += [PERL_PORTABLE_DIR / "perl" / "bin", Path(r"C:\Strawberry\perl\bin")]
    return dirs


def _newest_first(base: Path) -> list[Path]:
    """The year folders of a TeX Live installation (base/2026, base/2025, ...), newest first."""
    try:
        years = [p for p in base.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name)]
    except OSError:
        return []
    return sorted(years, key=lambda p: p.name, reverse=True)


def _linux_known_dirs() -> list[Path]:
    if shutil.which("lualatex"):
        return []
    for texlive in _newest_first(Path("/usr/local/texlive")):
        found = sorted((texlive / "bin").glob("*-linux"))
        if found:
            return found[:1]
    return []


def missing_dirs(path: str) -> list[str]:
    """The folders extend_path() would append to `path`, in order."""
    have = {os.path.normcase(os.path.normpath(p)) for p in path.split(os.pathsep) if p}
    if sys.platform == "win32":
        candidates = [*_windows_registry_path(), *map(str, _windows_known_dirs())]
    elif sys.platform.startswith("linux"):
        candidates = list(map(str, _linux_known_dirs()))
    else:
        candidates = []
    added: list[str] = []
    for folder in candidates:
        key = os.path.normcase(os.path.normpath(folder))
        if key in have or not os.path.isdir(folder):
            continue
        have.add(key)
        added.append(folder)
    return added


def extend_path() -> list[str]:
    """Append missing_dirs() to os.environ["PATH"]; the folders added."""
    path = os.environ.get("PATH", "")
    added = missing_dirs(path)
    if added:
        os.environ["PATH"] = os.pathsep.join([p for p in [path, *added] if p])
    return added
