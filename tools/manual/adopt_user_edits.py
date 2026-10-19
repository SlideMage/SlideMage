# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bring edits made to the SlideMage manual in a project's copy back into
SlideMage's own manual (example/), so future versions carry them.

The manual is shipped as example/ and copied into projects (bundled_copies.py);
a user who edits a slide in their copy -- or an assistant that edits it there --
changes only that copy. This tool compares, file by file, the project's copy
(S), the example (E) and the baseline recorded when the copy was last made (B,
.slidemage/bundled_copies.json):

  S differs from B, E equals B   the project's edit -> adopted into example/
  S differs from B, E differs    both changed -> a conflict, merged by hand
  S equals E                     nothing to do (SlideMage's own
                                 "%% Included in decks:" line is ignored)

Frozen versions (slides/<id>-...-vX-Y-Z.tex) the project has for a manual slide
and example/ lacks are adopted with the slide.

    python tools/manual/adopt_user_edits.py [--project DIR] [--apply]

Without --apply it only reports. --project defaults to $SLIDEMASTER_PROJECT.
Run it after a user edited manual slides, before the next SlideMage version.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "example"
sys.path.insert(0, str(REPO / "src"))

from slidemage import bundled_copies  # noqa: E402

HEADER = re.compile(rb"^%% Included in decks:[^\r\n]*", re.MULTILINE)
FROZEN = re.compile(r"^(?P<id>[A-Za-z0-9]{3})-.*-v\d+(?:-\d+)*\.tex$")


def with_header_of(data: bytes, other: bytes) -> bytes:
    """`data` with its "Included in decks" line replaced by the one in `other`."""
    header = HEADER.search(other)
    return HEADER.sub(lambda _m: header.group(0), data, count=1) if header else data


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", type=Path, default=os.environ.get("SLIDEMASTER_PROJECT"))
    parser.add_argument("--apply", action="store_true", help="copy the adoptable files into example/")
    args = parser.parse_args()
    if not args.project:
        parser.error("--project (or $SLIDEMASTER_PROJECT) is required")
    project = Path(args.project)
    manifest = bundled_copies.read_manifest(project).get(bundled_copies.MANUAL)
    if not manifest:
        print("The project has no recorded manual baseline; nothing to compare against.")
        return 1
    baseline = manifest["files"]

    adopt, conflicts = [], []
    for rel in bundled_copies.manual_files(EXAMPLE):
        mine, ours = project / rel, EXAMPLE / rel
        if not mine.is_file():
            continue
        s, e = mine.read_bytes(), ours.read_bytes()
        if rel.startswith("slides/") and rel.endswith(".tex"):
            s = with_header_of(s, e)
        if s == e:
            continue
        known = baseline.get(rel)
        if known is not None and sha(s) == known:
            continue                       # the project's copy is just the old bundle
        if known is not None and sha(e) != known:
            conflicts.append(rel)          # changed on both sides
        else:
            adopt.append((rel, s))

    ids = {line.strip().strip('"') for line in
           (EXAMPLE / "slide_ids.csv").read_text(encoding="utf-8").splitlines()[1:]}
    for path in sorted((project / "slides").glob("*.tex")):
        match = FROZEN.match(path.name)
        if match and match["id"] in ids and not (EXAMPLE / "slides" / path.name).exists():
            adopt.append((f"slides/{path.name}", path.read_bytes()))

    print(f"adoptable ({len(adopt)}):")
    for rel, _data in adopt:
        print("  ", rel)
    print(f"conflicts, changed in the project and in example/ ({len(conflicts)}):")
    for rel in conflicts:
        print("  ", rel)
    if args.apply:
        for rel, data in adopt:
            (EXAMPLE / rel).write_bytes(data)
        print(f"copied {len(adopt)} file(s) into {EXAMPLE}")
    elif adopt:
        print("(dry run; --apply copies them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
