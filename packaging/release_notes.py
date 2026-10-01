"""Print a release's notes -- its history entry in src/slidemage/version.py
-- for the GitHub release (release.yml), and refuse a major version bump
whose entry has no "BREAKING:" paragraph.

    python packaging/release_notes.py v4.1.0 > release_notes.md

The previous release is the newest tag before TAG (`git describe --tags
--abbrev=0 TAG^`), or --previous. Exit codes: 0 fine, 1 no history entry
for TAG, 2 major bump without a BREAKING: paragraph.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidemage import updater, version  # noqa: E402

BREAKING_PREFIX = updater.BREAKING_PREFIX


def previous_tag(tag: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", f"{tag}^"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def notes_for(tag: str) -> list[str] | None:
    for entry in version.parse_history():
        if entry.version == tag:
            return entry.paragraphs
    return None


def entries_since(tag: str, previous: str | None) -> list[tuple[str, list[str]]]:
    """(version, paragraphs) of every history entry after the previous release
    up to and including TAG, newest first -- a release that bundles several
    unreleased versions (v5.4.0 after v4.1.0) lists them all, and the BREAKING:
    check sees all of them. Without a previous release: TAG's entry only."""
    new, old = updater.parse_version(tag), updater.parse_version(previous or "")
    picked = []
    for entry in version.parse_history():
        v = updater.parse_version(entry.version)
        if entry.version == tag or (
                old is not None and v is not None and new is not None and old < v <= new):
            picked.append((entry.version, entry.paragraphs))
    picked.sort(key=lambda e: updater.parse_version(e[0]) or (0, 0, 0), reverse=True)
    return picked


def check(tag: str, previous: str | None, paragraphs: list[str]) -> list[str]:
    """Problems that must stop the release (empty = fine)."""
    new, old = updater.parse_version(tag), updater.parse_version(previous or "")
    marked = any(p.startswith(BREAKING_PREFIX) for p in paragraphs)
    if new is not None and old is not None and new[0] > old[0] and not marked:
        return [
            f"{tag} raises the major version (previous release {previous}) but its "
            f"history entry in version.py has no paragraph starting {BREAKING_PREFIX!r}. "
            "Say what breaks with the past and what users need to do."
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag")
    parser.add_argument("--previous", help="previous release tag (default: from git)")
    args = parser.parse_args(argv)
    # A redirected stdout on Windows defaults to the ANSI code page, which
    # can't hold "→" or "ü"; the notes file is read back as UTF-8.
    sys.stdout.reconfigure(encoding="utf-8")

    if notes_for(args.tag) is None:
        print(f"error: version.py has no history entry for {args.tag}", file=sys.stderr)
        return 1
    previous = args.previous or previous_tag(args.tag)
    entries = entries_since(args.tag, previous)
    paragraphs = [p for _, paras in entries for p in paras]
    problems = check(args.tag, previous, paragraphs)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 2
    marked = any(p.startswith(BREAKING_PREFIX) for p in paragraphs)
    new, old = updater.parse_version(args.tag), updater.parse_version(previous or "")
    if marked and new is not None and old is not None and new[0] == old[0]:
        print(f"warning: {args.tag} has a {BREAKING_PREFIX} paragraph but keeps the "
              f"major version of {previous}", file=sys.stderr)
    if len(entries) == 1:
        sys.stdout.write("\n\n".join(paragraphs) + "\n")
    else:
        sys.stdout.write("\n\n".join(f"## {v}\n\n" + "\n\n".join(paras) for v, paras in entries) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
