# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The files of the public repository's initial commit (v1.0 plan, user 2026-11-28).

    python packaging/public_tree.py --list               # what is left out, and the counts
    python packaging/public_tree.py --check              # fails on private paths or links to left-out files
    python packaging/public_tree.py --export DIR         # writes the kept files of HEAD into DIR (new or empty)

At v1.0.0 the repository is renamed SlideMage/SlideMage_pre_v1 and a fresh SlideMage/SlideMage gets one commit.
It keeps every tracked file except the internal working documents: docs/ keeps the user and developer
documentation in DOCS_KEPT only (plans, code reviews, findings, *_PLAN.md, benchmarks and issue/PR notes stay in
SlideMage_pre_v1), and .claude/ (the maintainer's own skills and agents) is left out.

--check reads the kept text files for private paths (PRIVATE_DEFAULT and PATTERNS_FILE) and the kept
Markdown files for relative links to files that are left out; either makes it fail.
"""
from __future__ import annotations

import argparse
import io
import posixpath
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DROPPED_PREFIXES = (".claude/", "docs/")
DOCS_KEPT = (
    "docs/SlideMage.md",
    "docs/PROJECT_OVERVIEW.md",
    "docs/PLUGIN_GUIDE.md",
    "docs/THEME_PACKAGE.md",
    "docs/CITATION_PACKAGE.md",
    "docs/CODE_SIGNING.md",
    "docs/SlideMageCommands.md",
    "docs/AI_TOOLS.md",
    "docs/PREVIEW_THUMBNAILS.md",
    "docs/PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md",
    "docs/preview-render-optimization-benchmark.json",   # PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md links it
    "docs/handover_archive.py",          # tests/test_handover_archive.py reads it
    "docs/design-handbook/",
)
# Generic signs of a maintainer's own folders; the personal ones (user name, machine, address) are read from
# PATTERNS_FILE, one regular expression per line, which is in .git/ and so never part of any commit.
PRIVATE_DEFAULT = (r"uniCLOUD", r"Dropbox[\\/]+repos")
PATTERNS_FILE = ".git/public_tree_patterns.txt"
SELF = {"packaging/public_tree.py", "tests/test_public_tree.py"}     # they name the patterns
_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")


def tracked(root: Path = ROOT, ref: str = "HEAD") -> list[str]:
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "-z", ref], cwd=root, capture_output=True,
                         check=True).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def kept(path: str) -> bool:
    if any(path == keep or (keep.endswith("/") and path.startswith(keep)) for keep in DOCS_KEPT):
        return True
    return not path.startswith(DROPPED_PREFIXES)


def split(paths: list[str]) -> tuple[list[str], list[str]]:
    return [p for p in paths if kept(p)], [p for p in paths if not kept(p)]


def private_pattern(root: Path = ROOT) -> re.Pattern[str]:
    patterns = list(PRIVATE_DEFAULT)
    extra = Path(subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True,
                                check=True).stdout.strip())
    extra = (extra if extra.is_absolute() else root / extra) / Path(PATTERNS_FILE).name
    if extra.is_file():
        patterns += [line.strip() for line in extra.read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.startswith("#")]
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


def private_hits(name: str, text: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    pattern = pattern or re.compile("|".join(PRIVATE_DEFAULT), re.IGNORECASE)
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            hits.append(f"{name}:{number}: {line.strip()[:120]}")
    return hits


def broken_links(name: str, text: str, dropped: set[str], kept_paths: set[str]) -> list[str]:
    """Relative Markdown links from `name` to a file that is left out, or a folder with nothing kept in it."""
    problems = []
    for target in _LINK.findall(text):
        if "://" in target or target.startswith("mailto:"):
            continue
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
        folder = resolved.rstrip("/") + "/"
        if resolved in dropped or (resolved not in kept_paths and any(p.startswith(folder) for p in dropped)
                                   and not any(p.startswith(folder) for p in kept_paths)):
            problems.append(f"{name}: links to left-out {resolved}")
    return problems


def check(root: Path = ROOT, ref: str = "HEAD") -> list[str]:
    keep, drop = split(tracked(root, ref))
    dropped, kept_paths = set(drop), set(keep)
    pattern = private_pattern(root)
    problems: list[str] = []
    archive = _archive(root, ref)
    for member in archive.getmembers():
        if not member.isfile() or member.name not in kept_paths:
            continue
        data = archive.extractfile(member).read()
        if b"\0" in data[:8000]:
            continue
        text = data.decode("utf-8", errors="replace")
        if member.name not in SELF:
            problems += private_hits(member.name, text, pattern)
        if member.name.endswith(".md"):
            problems += broken_links(member.name, text, dropped, kept_paths)
    return problems


def _archive(root: Path, ref: str) -> tarfile.TarFile:
    data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=root, capture_output=True, check=True).stdout
    return tarfile.open(fileobj=io.BytesIO(data))


def export(target: Path, root: Path = ROOT, ref: str = "HEAD") -> int:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    keep = set(split(tracked(root, ref))[0])
    archive = _archive(root, ref)
    members = [m for m in archive.getmembers() if m.isfile() and m.name in keep]
    target.mkdir(parents=True, exist_ok=True)
    archive.extractall(target, members=members, filter="data")
    return len(members)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="the files left out, and the counts")
    mode.add_argument("--check", action="store_true", help="fail on private paths or links to left-out files")
    mode.add_argument("--export", type=Path, metavar="DIR", help="write the kept files into DIR")
    parser.add_argument("--ref", default="HEAD", help="the commit to read (default HEAD)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.list:
        keep, drop = split(tracked(ROOT, args.ref))
        print("\n".join(drop))
        print(f"\n{len(keep)} files kept, {len(drop)} left out")
        return 0
    if args.check:
        problems = check(ROOT, args.ref)
        print("\n".join(problems) if problems else "no private paths, no links to left-out files")
        return 1 if problems else 0
    print(f"{export(args.export, ROOT, args.ref)} files written to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
