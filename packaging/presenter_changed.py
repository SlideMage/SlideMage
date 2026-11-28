# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print "true" when a file SlideMage Presenter is built from changed since the previous release tag, else "false"
(release.yml attaches the Presenter's assets only on "true"; docs/plans/presenter-app.md, step 4).

    python packaging/presenter_changed.py          # HEAD against `git describe --tags --abbrev=0 HEAD^`

The files are the pathspecs of packaging/presenter_paths.txt. Without a previous tag, or when git cannot tell,
the answer is "true": a Presenter that is attached once too often does no harm, one that is missing does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PATHS_FILE = Path(__file__).resolve().parent / "presenter_paths.txt"


def pathspecs(text: str) -> list[str]:
    """The pathspecs in `text`: one per line, blank lines and #-comments skipped."""
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def previous_tag(rev: str = "HEAD") -> str | None:
    try:
        done = subprocess.run(["git", "describe", "--tags", "--abbrev=0", f"{rev}^"],
                              capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip() or None


def changed_since(tag: str | None, specs: list[str], rev: str = "HEAD") -> bool:
    if not tag or not specs:
        return True
    try:
        done = subprocess.run(["git", "diff", "--quiet", tag, rev, "--", *specs], capture_output=True)
    except OSError:
        return True
    return done.returncode != 0      # 0: nothing changed, 1: something did, anything else: an error


def main() -> int:
    specs = pathspecs(PATHS_FILE.read_text(encoding="utf-8"))
    print("true" if changed_since(previous_tag(), specs) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
