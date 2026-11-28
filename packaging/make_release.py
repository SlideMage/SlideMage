# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make a release from the changelog fragments in changes/ (issue #247).

    python packaging/make_release.py --dry-run          # print the version, the CHANGELOG entry and the notes
    python packaging/make_release.py                    # write them into the working tree, nothing else
    python packaging/make_release.py --publish          # and branch, commit, PR, merge, tag, push
    ... --summary "One sentence for the whole release."
    ... --beta                                          # a beta of the coming version: vX.Y.Z-beta.N
    ... --version v1.0.0                                # this version instead of the computed one (must be higher)

The version is the last release (VERSION_NUMBER) raised by the biggest change among the fragments
(change_fragments.next_version), or the one --version names. Betas (version.BETA_SUFFIX, user 2026-11-28):
--beta makes vX.Y.Z-beta.1 of the version a release would get, or the next beta (-beta.2, ...) when VERSION_NUMBER
is a beta already; the Release workflow publishes a beta as a GitHub pre-release, which only installations with
"Offer beta versions" are offered. A release after betas keeps their number (v1.1.0-beta.2 -> v1.1.0). Each beta
uses up the fragments it was made from, like a release; so a release after betas may have no fragments left: its
entry then gathers the betas' NEW: bullets, and its notes cover every entry since the previous release.

The script then

1. appends one entry to src/slidemage/CHANGELOG.md: a single fragment gives an entry just like the per-PR entries
   before it (``vX.Y.Z (date, reason): text``); several give ``vX.Y.Z (date, release of N changes): summary``, then
   a paragraph per fragment (``Fixed (reason): text``; breaking first, then new, then fixed, each in the order the
   fragments were added), then one NEW: paragraph with every bullet, then the BREAKING: paragraphs;
2. sets VERSION_NUMBER in src/slidemage/version.py;
3. writes the version over ``since="NEXT"`` in src/slidemage/compat*.py;
4. deletes the fragments (not changes/README.md);
5. builds the release notes (packaging/release_notes.py) as the last check.

--publish then runs on a clean, up-to-date default branch (origin/HEAD: develop in SlideMage_pre_v1, main in the
repository of 1.0 on; ``git remote set-head origin --auto`` refreshes it): branch release/vX.Y.Z, commit "Release vX.Y.Z", push, open the
PR, merge it with --admin, tag the merge commit and push the tag, which starts the Release workflow.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from slidemage import change_fragments as cf  # noqa: E402
from slidemage import version  # noqa: E402

_VERSION_RE = re.compile(r'^VERSION_NUMBER = "(v[^"]*)"', re.MULTILINE)
_NEXT_RE = re.compile(r"""(since\s*=\s*)(["'])NEXT\2""")
LABELS = {"breaking": "Breaking", "new": "New", "fixed": "Fixed"}


class ReleaseError(Exception):
    pass


def _git(*args: str, root: Path = ROOT, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def current_version(root: Path = ROOT) -> str:
    match = _VERSION_RE.search(_read(root / "src" / "slidemage" / "version.py"))
    if not match:
        raise ReleaseError("no VERSION_NUMBER in src/slidemage/version.py")
    return match.group(1)


def added_at(path: Path, root: Path = ROOT) -> int:
    """When `path` was first committed (a Unix time); a file not committed yet sorts last."""
    try:
        out = _git("log", "--diff-filter=A", "--format=%ct", "--", str(path), root=root, check=False)
    except OSError:
        return sys.maxsize
    times = [int(t) for t in out.split() if t.isdigit()]
    return min(times) if times else sys.maxsize


def ordered(fragments: list[cf.Fragment], when=None) -> list[cf.Fragment]:
    """Breaking first, then new, then fixed; within a kind in the order the fragments were added."""
    when = when or (lambda f: added_at(f.path))
    return sorted(fragments, key=lambda f: (cf.KINDS.index(f.kind) if f.kind in cf.KINDS else len(cf.KINDS),
                                            when(f), f.path.name))


def entry_text(number: str, date: str, fragments: list[cf.Fragment], summary: str = "") -> str:
    """The CHANGELOG entry of the release (see the module docstring), "\\n"-separated, no trailing newline."""
    if not fragments:
        raise ReleaseError("no fragments")
    paragraphs: list[str] = []
    if len(fragments) == 1:
        only = fragments[0]
        technical = [p.strip() for p in only.technical]
        paragraphs.append(f"{number} ({date}, {only.reason}): {technical[0]}")
        paragraphs.extend(technical[1:])
        summary = summary or only.summary
    else:
        counts = ", ".join(f"{sum(f.kind == kind for f in fragments)} {LABELS[kind].lower()}"
                           for kind in cf.KINDS if any(f.kind == kind for f in fragments))
        paragraphs.append(f"{number} ({date}, release of {len(fragments)} changes): "
                          f"{summary or f'This release has {counts} changes.'}")
        for fragment in fragments:
            technical = [p.strip() for p in fragment.technical]
            paragraphs.append(f"{LABELS.get(fragment.kind, 'Changed')} ({fragment.reason}): {technical[0]}")
            paragraphs.extend(technical[1:])
        if not summary:
            summaries = [f.summary for f in fragments if f.summary]
            summary = summaries[0] if len(summaries) == 1 else ""
    news = "\n".join(f"- {bullet}" for f in fragments for bullet in f.news)
    paragraphs.append(f"{version.NEW_PREFIX} {summary}\n{news}" if summary else f"{version.NEW_PREFIX}\n{news}")
    paragraphs.extend(p.strip() for f in fragments for p in f.breaking)
    return "\n\n".join(paragraphs)


def history_entry(text: str) -> version.HistoryEntry:
    entries = version.parse_history(text)
    if len(entries) != 1:
        raise ReleaseError(f"the new entry reads as {len(entries)} entries; check the fragments' text")
    return entries[0]


def apply(root: Path, number: str, entry: str, fragments: list[cf.Fragment]) -> list[Path]:
    """Write the release into the tree at `root`; the files changed or deleted."""
    touched: list[Path] = []
    changelog = root / "src" / "slidemage" / "CHANGELOG.md"
    text = _read(changelog)
    nl = _newline(text)
    _write(changelog, text.rstrip("\r\n") + nl + nl + entry.replace("\n", nl) + nl)
    touched.append(changelog)

    version_py = root / "src" / "slidemage" / "version.py"
    text = _read(version_py)
    _write(version_py, _VERSION_RE.sub(f'VERSION_NUMBER = "{number}"', text, count=1))
    touched.append(version_py)

    for path in sorted((root / "src" / "slidemage").glob("compat*.py")):
        text = _read(path)
        new = _NEXT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{number}{m.group(2)}", text)
        if new != text:
            _write(path, new)
            touched.append(path)

    for fragment in fragments:
        fragment.path.unlink()
        touched.append(fragment.path)
    return touched


def choose_number(previous: str, kinds, *, beta: bool = False, explicit: str = "") -> str:
    """The new version: `explicit` (--version; with `beta` its first beta unless it names one), else the next one
    after `previous` for changes of `kinds`, as a beta with `beta`. After a beta of vX.Y.Z: its next beta, or vX.Y.Z
    itself. ReleaseError unless the result comes after `previous`."""
    if explicit:
        number = explicit.strip()
        if not number.startswith("v"):
            number = "v" + number
        if beta and not version.is_beta(number):
            number += f"{version.BETA_SUFFIX}1"
        try:
            cf._parts(version.base_version(number))
        except ValueError as error:
            raise ReleaseError(f"--version: {error}") from None
    else:
        base, beta_number = version.split_beta(previous)
        if beta_number is not None:
            number = f"{base}{version.BETA_SUFFIX}{beta_number + 1}" if beta else base
        else:
            number = cf.next_version(previous, kinds)
            if beta:
                number += f"{version.BETA_SUFFIX}1"
    new, old = version.release_key(number), version.release_key(previous)
    if new is None or old is None or new <= old:
        raise ReleaseError(f"{number} does not come after the current version {previous}")
    return number


def betas_entry(number: str, date: str, summary: str, history: str) -> str:
    """The CHANGELOG entry of a release made of its betas only (no fragments left): the summary and every NEW:
    bullet of the betas of `number`, oldest first."""
    history = history.replace("\r\n", "\n")       # _read keeps the file's line ends; the parser wants LF
    betas = [e for e in version.parse_history(history)
             if version.is_beta(e.version) and version.base_version(e.version) == number]
    if not betas:
        raise ReleaseError("changes/ has no fragments: nothing to release")
    betas.sort(key=lambda e: version.release_key(e.version))
    names = ", ".join(e.version for e in betas)
    news = "\n".join(f"- {bullet}" for e in betas for bullet in e.news)
    summary = summary or f"SlideMage {number}: the changes tested in {names}."
    return (f"{number} ({date}, release of the betas {names}): {summary}\n\n"
            f"{version.NEW_PREFIX} {summary}\n{news}")


def prepare(root: Path = ROOT, summary: str = "", date: str = "", when=None, *, beta: bool = False,
            explicit: str = "") -> tuple[str, str, str, list[cf.Fragment]]:
    """(previous release, new version, CHANGELOG entry, fragments), after checking every fragment."""
    fragments = cf.read_all(root / "changes")
    previous = current_version(root)
    date = date or _dt.date.today().isoformat()
    if not fragments:
        if beta or not version.is_beta(previous):
            raise ReleaseError("changes/ has no fragments: nothing to release")
        number = choose_number(previous, [], explicit=explicit)
        entry = betas_entry(number, date, summary, _read(root / "src" / "slidemage" / "CHANGELOG.md"))
        history_entry(entry)
        return previous, number, entry, []
    bad = [f"{f.path.name}: {p}" for f in fragments for p in cf.problems(f)]
    if bad:
        raise ReleaseError("fragments with problems:\n  " + "\n  ".join(bad))
    number = choose_number(previous, [f.kind for f in fragments], beta=beta, explicit=explicit)
    fragments = ordered(fragments, when)
    entry = entry_text(number, date, fragments, summary)
    history_entry(entry)
    return previous, number, entry, fragments


def notes(number: str, previous: str, entry: str) -> str:
    """The GitHub release notes of `entry`; raises ReleaseError where release_notes.py would refuse the tag."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "packaging" / "release_notes.py")
    release_notes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_notes)
    parsed = history_entry(entry)
    problems = release_notes.check(number, previous, parsed.paragraphs)
    if release_notes.missing_news([parsed]):
        problems.append("the entry has no NEW: bullets")
    if problems:
        raise ReleaseError("\n".join(problems))
    return release_notes.render(number, previous, [parsed])


DEFAULT_BRANCH = "develop"


def default_branch(root: Path = ROOT) -> str:
    """The branch releases start from and merge into: origin's default branch, DEFAULT_BRANCH if git cannot say."""
    ref = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", root=root, check=False)
    return ref.split("/", 1)[1] if ref.startswith("origin/") else DEFAULT_BRANCH


def _publish(number: str, previous: str, entry: str, fragments: list[cf.Fragment], body: str) -> None:
    if _git("status", "--porcelain"):
        raise ReleaseError("the working tree has uncommitted changes")
    base = default_branch()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != base:
        raise ReleaseError(f"on {branch}, not {base}")
    _git("fetch", "origin", base, "--tags")
    if _git("rev-parse", "HEAD") != _git("rev-parse", f"origin/{base}"):
        raise ReleaseError(f"{base} is not origin/{base}: pull first")
    if _git("tag", "-l", number):
        raise ReleaseError(f"the tag {number} exists already")
    release_branch = f"release/{number}"
    _git("switch", "-c", release_branch)
    apply(ROOT, number, entry, fragments)
    check = subprocess.run([sys.executable, str(ROOT / "packaging" / "release_notes.py"), number,
                            "--previous", previous], cwd=ROOT, capture_output=True, text=True)
    if check.returncode != 0:
        raise ReleaseError(f"release_notes.py refused {number}: {check.stderr.strip()}")
    _git("add", "-A")
    _git("commit", "-m", f"Release {number}")
    _git("push", "-u", "origin", release_branch)
    title = f"Release {number}"
    pr_body = f"{body}\n\nMade by `packaging/make_release.py` from {len(fragments)} fragment(s) in `changes/`."
    url = subprocess.run(["gh", "pr", "create", "--base", base, "--head", release_branch, "--title", title,
                          "--body", pr_body], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    number_of_pr = url.rstrip("/").rsplit("/", 1)[-1]
    subprocess.run(["gh", "pr", "merge", number_of_pr, "--admin", "--merge"], cwd=ROOT, check=True)
    merged = json.loads(subprocess.run(["gh", "pr", "view", number_of_pr, "--json", "mergeCommit"], cwd=ROOT,
                                       capture_output=True, text=True, check=True).stdout)
    sha = merged["mergeCommit"]["oid"]
    _git("fetch", "origin", base)
    _git("switch", base)
    _git("merge", "--ff-only", f"origin/{base}")
    _git("tag", number, sha)
    _git("push", "origin", number)
    _git("branch", "-d", release_branch, check=False)
    _git("push", "origin", "--delete", release_branch, check=False)
    print(f"released {number}: {url}, tag {number} on {sha[:8]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print, write nothing")
    mode.add_argument("--publish", action="store_true", help="branch, commit, PR, merge, tag and push")
    parser.add_argument("--summary", default="", help="one sentence for the whole release (the NEW: summary)")
    parser.add_argument("--date", default="", help="the entry's date (default: today)")
    parser.add_argument("--beta", action="store_true", help="a beta of the coming version (vX.Y.Z-beta.N)")
    parser.add_argument("--version", default="", help="this version instead of the computed one, e.g. v1.0.0")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        previous, number, entry, fragments = prepare(ROOT, args.summary, args.date, beta=args.beta,
                                                     explicit=args.version)
        body = notes(number, previous, entry)
        if args.dry_run:
            print(f"{previous} -> {number} ({len(fragments)} fragment(s))\n\n--- CHANGELOG.md entry\n\n{entry}\n\n"
                  f"--- release notes\n\n{body}")
        elif args.publish:
            _publish(number, previous, entry, fragments, body)
        else:
            for path in apply(ROOT, number, entry, fragments):
                print(path.relative_to(ROOT))
            print(f"{previous} -> {number}: written; commit, merge and tag {number} on the merge commit")
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
