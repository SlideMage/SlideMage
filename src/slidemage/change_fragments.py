# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Changelog fragments (issue #247): what a PR changes, written down without a version number.

A PR that changes the app adds one file to ``changes/`` at the repository root (see ``changes/README.md``) and
leaves ``VERSION_NUMBER`` and CHANGELOG.md alone, so two open PRs never conflict over the version.
``packaging/make_release.py`` collects the fragments, works out the version (:func:`next_version`), writes one
CHANGELOG entry for the release, sets ``VERSION_NUMBER`` and deletes the fragments.

A fragment::

    kind: fixed              (fixed | new | breaking)
    reason: direct request: "Render now" did nothing
    compat: some-change-id   (breaking only: the compat.CHANGES ids, comma-separated)

    The technical description, one or more paragraphs.

    NEW: An optional one-sentence summary.
    - What users notice, in plain words.

    BREAKING: What breaks and what to do about it (breaking only).

A version a PR cannot know yet is written :data:`NEXT` (``compat.CHANGES`` ``since``); the release script puts the
new number in its place.

    python -m slidemage.change_fragments --check [FILE ...]     # all of changes/ without FILEs
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import version

FOLDER = Path(__file__).resolve().parents[2] / "changes"   # the checkout's; a frozen build has none
README = "README.md"
NEXT = "NEXT"

KINDS = ("breaking", "new", "fixed")          # biggest first: the release's order
KEYS = ("kind", "reason", "compat")
BREAKING_PREFIX = "BREAKING:"

# A paragraph that would start a history entry of its own when written into CHANGELOG.md.
_ENTRY_START_RE = re.compile(r"^(v\d+(?:\.\d+){2,3} \(|The displayed string)", re.MULTILINE)
_HEADER_RE = re.compile(r"^([A-Za-z_]+):\s*(.*)$")


@dataclass
class Fragment:
    path: Path
    kind: str = ""
    reason: str = ""
    compat: list[str] = field(default_factory=list)
    technical: list[str] = field(default_factory=list)   # the paragraphs for CHANGELOG.md, line wraps kept
    summary: str = ""
    news: list[str] = field(default_factory=list)
    breaking: list[str] = field(default_factory=list)     # BREAKING: paragraphs, prefix kept
    header_problems: list[str] = field(default_factory=list)
    new_paragraphs: int = 0


def parse(path: Path, text: Optional[str] = None) -> Fragment:
    """The fragment in `path` (or in `text`, read from `path` when None)."""
    if text is None:
        text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").strip("\n")
    fragment = Fragment(path)
    header, _, body = text.partition("\n\n")
    for line in header.split("\n"):
        match = _HEADER_RE.match(line.strip())
        if not match or match.group(1).lower() not in KEYS:
            fragment.header_problems.append(f"header line {line.strip()!r} is not one of {', '.join(KEYS)}")
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        if key == "kind":
            fragment.kind = value.lower()
        elif key == "reason":
            fragment.reason = value
        else:
            fragment.compat = [part.strip() for part in value.split(",") if part.strip()]
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", body)):
        if not paragraph:
            continue
        if paragraph.startswith(version.NEW_PREFIX):
            fragment.new_paragraphs += 1
            fragment.summary, fragment.news = version.parse_news(paragraph)
        elif paragraph.startswith(BREAKING_PREFIX):
            fragment.breaking.append(paragraph)
        else:
            fragment.technical.append(paragraph)
    return fragment


def paths(folder: Path = FOLDER) -> list[Path]:
    """The fragment files in `folder`, by name (README.md is not one)."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.name != README)


def read_all(folder: Path = FOLDER) -> list[Fragment]:
    return [parse(p) for p in paths(folder)]


def problems(fragment: Fragment, changes: Optional[Iterable] = None) -> list[str]:
    """What is wrong with `fragment` (empty = fine). `changes`: compat.CHANGES unless given."""
    found = list(fragment.header_problems)
    if fragment.kind not in KINDS:
        found.append(f"kind is {fragment.kind!r}, not one of {', '.join(KINDS)}")
    if not fragment.reason:
        found.append("no 'reason:' line (why the change was made: direct request, issue #N, ...)")
    if not fragment.technical:
        found.append("no technical description (a paragraph before NEW:)")
    if fragment.new_paragraphs != 1 or not fragment.news:
        found.append("needs exactly one NEW: paragraph with '- ' bullets (what users get, in plain words)")
    body = "\n\n".join(fragment.technical + fragment.breaking)
    if _ENTRY_START_RE.search(body):
        found.append("a line starts like a CHANGELOG entry ('vX.Y.Z (...'); reword it")
    if fragment.kind == "breaking":
        if not fragment.breaking:
            found.append(f"a breaking change needs a paragraph starting {BREAKING_PREFIX!r}")
        if not fragment.compat:
            found.append("a breaking change needs a 'compat:' line naming its slidemage.compat.CHANGES ids")
    elif fragment.breaking:
        found.append(f"a {BREAKING_PREFIX} paragraph needs 'kind: breaking'")
    if fragment.compat:
        if changes is None:
            from . import compat
            changes = compat.CHANGES
        since = {c.id: c.since for c in changes}
        for change_id in fragment.compat:
            if change_id not in since:
                found.append(f"compat id {change_id!r} is not in slidemage.compat.CHANGES")
            elif since[change_id] != NEXT:
                found.append(f"compat id {change_id!r} has since={since[change_id]!r}; a new change has since={NEXT!r}")
    return found


# -- versions -------------------------------------------------------------------

def _parts(number: str) -> tuple[int, ...]:
    parts = number.strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"{number!r} is not a vX.Y.Z version")
    return tuple(int(p) for p in parts)


def bump(last: str, kind: str) -> str:
    """The version after `last` for a change of `kind`: in 0.x breaking raises the minor and anything else the
    patch; from 1.0 on breaking raises the major, new the minor, fixed the patch."""
    major, minor, patch = _parts(last)
    if major == 0:
        major, minor, patch = (0, minor + 1, 0) if kind == "breaking" else (0, minor, patch + 1)
    elif kind == "breaking":
        major, minor, patch = major + 1, 0, 0
    elif kind == "new":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"v{major}.{minor}.{patch}"


def biggest(kinds: Iterable[str]) -> str:
    present = set(kinds)
    return next((kind for kind in KINDS if kind in present), "fixed")


def next_version(last: str, kinds: Iterable[str]) -> str:
    """The release after `last` that carries changes of `kinds`: one bump, by the biggest of them."""
    return bump(last, biggest(kinds))


def resolve(since: str, current: str = "") -> str:
    """`since` itself, or for NEXT `current` (default VERSION_NUMBER): between releases the running build is the
    last release plus the unreleased changes, so a NEXT change counts as part of it. For comparisons only."""
    return (current or version.VERSION_NUMBER) if since == NEXT else since


# -- command line -----------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check the changelog fragments in changes/.")
    parser.add_argument("--check", action="store_true", help="report problems, exit 1 if there are any")
    parser.add_argument("files", nargs="*", type=Path, help="fragment files (default: all of changes/)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    files = [f for f in args.files if f.name != README] if args.files else paths()
    bad = 0
    for path in files:
        if not path.is_file():
            continue                       # deleted by the PR (a release)
        for problem in problems(parse(path)):
            print(f"{path}: {problem}")
            bad += 1
    if not bad:
        print(f"{len(files)} fragment(s) fine")
    return 1 if bad and args.check else 0


if __name__ == "__main__":
    sys.exit(main())
