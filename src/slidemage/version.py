# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage's version string and release-history parser.

See CHANGELOG.md for the release history, bump rules and BREAKING convention.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .processes import command_output

VERSION_NUMBER = "v0.13.4"

# Versions before v0.11.0 were numbered vX.Y.Z with X from 2 to 10; the history, the tags and the files projects
# and plugins hold under that scheme are read as 0.X.Y.Z (v10.19.0 is v0.10.19.0). A first part of 2 or more can only
# be the old scheme: the new one stays in 0.x until a stable v1.0.0.
LEGACY_FIRST_MAJOR = 2


def to_zero_x(parts: tuple[int, ...]) -> tuple[int, ...]:
    """`parts` of an old-scheme version with the leading 0 (10, 19, 0 -> 0, 10, 19, 0); any other unchanged."""
    return (0, *parts) if parts and parts[0] >= LEGACY_FIRST_MAJOR else parts


# Matches each "vX.Y.Z (...): description..." entry in CHANGELOG.md (four parts up to v0.10.19.0),
# skipping the introduction.
_HISTORY_ENTRY_RE = re.compile(
    r"^(v\d+(?:\.\d+){2,3}) \(([^)]*)\):\s*(.*?)"
    r"(?=\n\nv\d+(?:\.\d+){2,3} \(|\n\nThe displayed string|\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass
class HistoryEntry:
    version: str
    meta: str          # whatever's in parens -- usually a date + reason
    description: str
    # The same text split at blank lines, each paragraph's own line wraps
    # joined -- keeps a "BREAKING:" paragraph recognizable
    # (packaging/release_notes.py, updater.breaking_notes()).
    paragraphs: list[str] = field(default_factory=list)
    # The entry's "NEW:" paragraph (since v5.35.4): what users get, for the
    # GitHub release notes (packaging/release_notes.py) -- an optional
    # one-sentence summary on the NEW: line, then "- " bullets
    summary: str = ""
    news: list[str] = field(default_factory=list)


NEW_PREFIX = "NEW:"


def _parse_news(paragraph: str) -> tuple[str, list[str]]:
    """(summary, bullets) of a "NEW:" paragraph: the text after NEW: on its
    first line is the summary, every line starting with "- " a bullet, and
    other lines continue the line before them."""
    summary_lines: list[str] = []
    bullets: list[str] = []
    for line in paragraph.strip()[len(NEW_PREFIX):].split("\n"):
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line:
            if bullets:
                bullets[-1] += " " + line
            else:
                summary_lines.append(line)
    return " ".join(summary_lines), bullets


def parse_history() -> list[HistoryEntry]:
    """Every per-bump entry in CHANGELOG.md, oldest first."""
    text = Path(__file__).with_name("CHANGELOG.md").read_text(encoding="utf-8")
    entries = []
    for match in _HISTORY_ENTRY_RE.finditer(text):
        version, meta, body = match.group(1), match.group(2), match.group(3)
        meta = re.sub(r"\s+", " ", meta).strip()
        description = re.sub(r"\s+", " ", body).strip()
        raw = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
        paragraphs = [re.sub(r"\s+", " ", paragraph).strip() for paragraph in raw]
        summary, news = "", []
        for paragraph in raw:
            if paragraph.strip().startswith(NEW_PREFIX):
                summary, news = _parse_news(paragraph)
        entries.append(HistoryEntry(
            version=version, meta=meta, description=description, paragraphs=paragraphs,
            summary=summary, news=news))
    return entries


def run_git(*args: str) -> str | None:
    # The app's own checkout, not the project: since v4.0.0 the two
    # are separate repositories, and the version string is about
    # the app. (A frozen build has no checkout -> plain number.)
    out = command_output(["git", *args], cwd=Path(__file__).resolve().parent, timeout=5)
    return None if out is None else out.strip()


def _compute_version_string() -> str:
    commit_dt = run_git(
        "show", "-s", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", "HEAD"
    )
    if commit_dt is None:
        return VERSION_NUMBER
    return f"{VERSION_NUMBER} ({commit_dt})"


def __getattr__(name: str) -> str:
    if name == "VERSION":
        value = _compute_version_string()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
