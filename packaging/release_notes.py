"""Print a release's notes for the GitHub release (release.yml), built from
the history entries in src/slidemage/CHANGELOG.md of every version since the
previous release, and refuse a release whose notes would be incomplete.

    python packaging/release_notes.py v4.1.0 > release_notes.md

What GitHub users see (v5.35.4, direct instruction: "describe the releases
in a more helpful manner, so GitHub users see in few sentences or bullet
points what is new since the previous release"): each history entry has a
"NEW:" paragraph -- an optional one-sentence summary, then "- " bullets in
plain user terms -- and the notes are

    <summary of the tagged version's entry: the release as a whole>
    *This release covers vA to vB.*        (when it bundles several)
    - <every entry's bullets, newest version first>
    ## Breaking changes                     (when an entry has BREAKING:)
    - **vX:** <the BREAKING: paragraph>
    ## Full changelog
    https://github.com/<repo>/compare/<previous>...<tag>

The long technical text of an entry stays in CHANGELOG.md (Info -> Version
history). Entries up to NEWS_REQUIRED_AFTER predate the NEW: paragraph; a
release made only of those prints their full text as before.

The previous release is the newest tag before TAG (`git describe --tags
--abbrev=0 TAG^`), or --previous. Exit codes: 0 fine, 1 no history entry
for TAG, 2 major bump without a BREAKING: paragraph, 3 an entry after
NEWS_REQUIRED_AFTER without a NEW: paragraph.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidemage import updater, version  # noqa: E402

BREAKING_PREFIX = updater.BREAKING_PREFIX
# v8.3.0 (direct decision): versions up to and including v8.2.1 are exempt;
# the 6.x-8.x entries were written without a NEW: paragraph.
NEWS_REQUIRED_AFTER = "v8.2.1"


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


def history_since(tag: str, previous: str | None) -> list[version.HistoryEntry]:
    """Every history entry after the previous release up to and including
    TAG, newest first -- a release that bundles several unreleased versions
    (v5.4.0 after v4.1.0) covers them all, and the checks see all of them.
    Without a previous release: TAG's entry only."""
    new, old = updater.parse_version(tag), updater.parse_version(previous or "")
    picked = []
    for entry in version.parse_history():
        v = updater.parse_version(entry.version)
        if entry.version == tag or (
                old is not None and v is not None and new is not None and old < v <= new):
            picked.append(entry)
    picked.sort(key=lambda e: updater.parse_version(e.version) or (0, 0, 0), reverse=True)
    return picked


def entries_since(tag: str, previous: str | None) -> list[tuple[str, list[str]]]:
    """(version, paragraphs) of history_since()'s entries."""
    return [(e.version, e.paragraphs) for e in history_since(tag, previous)]


def check(tag: str, previous: str | None, paragraphs: list[str]) -> list[str]:
    """Problems that must stop the release (empty = fine)."""
    new, old = updater.parse_version(tag), updater.parse_version(previous or "")
    marked = any(p.startswith(BREAKING_PREFIX) for p in paragraphs)
    if new is not None and old is not None and new[0] > old[0] and not marked:
        return [
            f"{tag} raises the major version (previous release {previous}) but its "
            f"history entry in CHANGELOG.md has no paragraph starting {BREAKING_PREFIX!r}. "
            "Say what breaks with the past and what users need to do."
        ]
    return []


def missing_news(entries: list[version.HistoryEntry]) -> list[str]:
    """Versions after NEWS_REQUIRED_AFTER whose entry has no NEW: bullets."""
    limit = updater.parse_version(NEWS_REQUIRED_AFTER)
    return [e.version for e in entries
            if not e.news and (updater.parse_version(e.version) or (0, 0, 0)) > limit]


def _covers(entries: list[version.HistoryEntry]) -> str:
    if len(entries) == 2:
        return f"{entries[1].version} and {entries[0].version}"
    return f"{entries[-1].version} to {entries[0].version}"


def render(tag: str, previous: str | None, entries: list[version.HistoryEntry]) -> str:
    """The release notes (see the module docstring). The changelog link sits
    under a heading of its own, so the updater (updater.breaking_notes(),
    which reads a "## Breaking changes" section up to the next heading)
    never takes it for part of the breaking changes."""
    parts: list[str] = []
    if any(e.news for e in entries):
        if entries[0].summary:
            parts.append(entries[0].summary)
        if len(entries) > 1:
            parts.append(f"*This release covers {_covers(entries)}.*")
        parts.append("\n".join(f"- {b}" for e in entries for b in e.news))
        breaking = [(e.version, p[len(BREAKING_PREFIX):].strip())
                    for e in entries for p in e.paragraphs if p.startswith(BREAKING_PREFIX)]
        if breaking:
            lines = [f"- **{v}:** {text}" if len(entries) > 1 else f"- {text}"
                     for v, text in breaking]
            parts.append("## Breaking changes\n\n" + "\n".join(lines))
    elif len(entries) == 1:
        # entries from before the NEW: paragraph: their full text
        parts.append("\n\n".join(entries[0].paragraphs))
    else:
        parts.extend(f"## {e.version}\n\n" + "\n\n".join(e.paragraphs) for e in entries)
    if previous:
        parts.append(f"## Full changelog\n\n"
                     f"https://github.com/{updater.REPO}/compare/{previous}...{tag}")
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag")
    parser.add_argument("--previous", help="previous release tag (default: from git)")
    args = parser.parse_args(argv)
    # A redirected stdout on Windows defaults to the ANSI code page, which
    # can't hold "→" or "ü"; the notes file is read back as UTF-8.
    sys.stdout.reconfigure(encoding="utf-8")

    if notes_for(args.tag) is None:
        print(f"error: CHANGELOG.md has no history entry for {args.tag}", file=sys.stderr)
        return 1
    previous = args.previous or previous_tag(args.tag)
    entries = history_since(args.tag, previous)
    paragraphs = [p for e in entries for p in e.paragraphs]
    problems = check(args.tag, previous, paragraphs)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 2
    missing = missing_news(entries)
    if missing:
        print(f"error: no NEW: paragraph (what users get, as '- ' bullets) in the history "
              f"entry of {', '.join(missing)}", file=sys.stderr)
        return 3
    marked = any(p.startswith(BREAKING_PREFIX) for p in paragraphs)
    new, old = updater.parse_version(args.tag), updater.parse_version(previous or "")
    if marked and new is not None and old is not None and new[0] == old[0]:
        print(f"warning: {args.tag} has a {BREAKING_PREFIX} paragraph but keeps the "
              f"major version of {previous}", file=sys.stderr)
    sys.stdout.write(render(args.tag, previous, entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
