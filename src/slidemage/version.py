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

VERSION_NUMBER = "v1.0.0"

# Versions before v0.11.0 were numbered vX.Y.Z with X from 2 to 10; the history, the tags and the files projects
# and plugins hold under that scheme are read as 0.X.Y.Z (v10.19.0 is v0.10.19.0). A first part of 2 or more can only
# be the old scheme: the new one stays in 0.x until a stable v1.0.0.
LEGACY_FIRST_MAJOR = 2


def to_zero_x(parts: tuple[int, ...]) -> tuple[int, ...]:
    """`parts` of an old-scheme version with the leading 0 (10, 19, 0 -> 0, 10, 19, 0); any other unchanged."""
    return (0, *parts) if parts and parts[0] >= LEGACY_FIRST_MAJOR else parts


def zero_x_string(text: str) -> str:
    """A stored old-scheme version string in its 0.x form ("v10.19.0" -> "v0.10.19.0"); anything else unchanged.
    record_project_open rewrites project.json with it, so to_zero_x can retire before 2.0 (v1.0 plan, step 3)."""
    if not isinstance(text, str):
        return text
    base, beta = split_beta(text)
    digits = base[1:] if base[:1] in ("v", "V") else base
    parts = digits.split(".")
    if not all(part.isdigit() for part in parts) or int(parts[0]) < LEGACY_FIRST_MAJOR:
        return text
    suffix = f"{BETA_SUFFIX}{beta}" if beta is not None else ""
    return f"{base[:len(base) - len(digits)]}0.{digits}{suffix}"


# Betas (user, 2026-11-28): "vX.Y.Z-beta.N", a test version of the coming vX.Y.Z, published on GitHub as a
# pre-release; only installations with "Offer beta versions" on (updater.get_beta_updates) are offered one.
# vX.Y.Z-beta.1 < vX.Y.Z-beta.2 < vX.Y.Z. Everything that only asks "which features does this build have"
# (plugin requirements, project files, compat) reads a beta as its vX.Y.Z (base_version).
BETA_SUFFIX = "-beta."
_BETA_RE = re.compile(r"^(v?\d+(?:\.\d+)*)-beta\.(\d+)$")


def split_beta(tag: str) -> tuple[str, int | None]:
    """("v1.1.0", 2) for "v1.1.0-beta.2"; (tag, None) for anything without a beta suffix."""
    match = _BETA_RE.match(tag.strip())
    return (match.group(1), int(match.group(2))) if match else (tag.strip(), None)


def base_version(tag: str) -> str:
    """The release a version belongs to: "v1.1.0" for "v1.1.0-beta.2", any other version unchanged."""
    return split_beta(tag)[0]


def is_beta(tag: str) -> bool:
    return split_beta(tag)[1] is not None


def release_key(tag: str) -> tuple[int, ...] | None:
    """A sort key that orders releases including betas: the numbers (old scheme read as 0.x, padded to four parts),
    then (0, N) for beta N and (1, 0) for the release itself. None for anything that is not a version."""
    base, beta = split_beta(tag)
    parts = base.lstrip("vV").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    numbers = to_zero_x(tuple(int(part) for part in parts))
    numbers = numbers + (0,) * (4 - len(numbers))
    return numbers + ((0, beta) if beta is not None else (1, 0))


# Matches each "vX.Y.Z (...): description..." entry in CHANGELOG.md (four parts up to v0.10.19.0),
# skipping the introduction.
_HISTORY_ENTRY_RE = re.compile(
    r"^(v\d+(?:\.\d+){2,3}(?:-beta\.\d+)?) \(([^)]*)\):\s*(.*?)"
    r"(?=\n\nv\d+(?:\.\d+){2,3}(?:-beta\.\d+)? \(|\n\nThe displayed string|\Z)",
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


def parse_news(paragraph: str) -> tuple[str, list[str]]:
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


def parse_history(text: str | None = None) -> list[HistoryEntry]:
    """Every entry in CHANGELOG.md (or in `text`), oldest first: one per release from issue #247 on, one per
    version bump before."""
    if text is None:
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
                summary, news = parse_news(paragraph)
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


def unreleased_fragments() -> list[Path]:
    """The checkout's changes/*.md fragments (issue #247; see change_fragments): changes merged since the release
    VERSION_NUMBER names. A frozen build has no checkout, so none."""
    folder = Path(__file__).resolve().parents[2] / "changes"
    try:
        return sorted(p for p in folder.glob("*.md") if p.name != "README.md")
    except OSError:
        return []


def _compute_version_string() -> str:
    """VERSION_NUMBER, from a checkout with the commit date; with unreleased fragments the number is that of the
    last release, so it gets "+dev" and the commit: "v0.17.38+dev (3e7142f9, 2026-11-18 14:02)"."""
    out = run_git("show", "-s", "--format=%h %cd", "--date=format:%Y-%m-%d %H:%M", "HEAD")
    if out is None:
        return VERSION_NUMBER
    commit, _, commit_dt = out.partition(" ")
    if unreleased_fragments():
        return f"{VERSION_NUMBER}+dev ({commit}, {commit_dt})"
    return f"{VERSION_NUMBER} ({commit_dt})"


def __getattr__(name: str) -> str:
    if name == "VERSION":
        value = _compute_version_string()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
