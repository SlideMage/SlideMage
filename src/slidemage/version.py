"""SlideMage's version string and release-history parser.

See CHANGELOG.md for the release history, bump rules and BREAKING convention.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .processes import no_console_kwargs

VERSION_NUMBER = "v8.0.21"

# Matches each "vX.Y.Z (...): description..." entry in CHANGELOG.md,
# skipping the introduction.
_HISTORY_ENTRY_RE = re.compile(
    r"^(v\d+\.\d+\.\d+) \(([^)]*)\):\s*(.*?)"
    r"(?=\n\nv\d+\.\d+\.\d+ \(|\n\nThe displayed string|\Z)",
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


def parse_history() -> list[HistoryEntry]:
    """Every per-bump entry in CHANGELOG.md, oldest first."""
    text = Path(__file__).with_name("CHANGELOG.md").read_text(encoding="utf-8")
    entries = []
    for match in _HISTORY_ENTRY_RE.finditer(text):
        version, meta, body = match.group(1), match.group(2), match.group(3)
        meta = re.sub(r"\s+", " ", meta).strip()
        description = re.sub(r"\s+", " ", body).strip()
        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()
        ]
        entries.append(HistoryEntry(
            version=version, meta=meta, description=description, paragraphs=paragraphs))
    return entries


def run_git(*args: str) -> str | None:
    popen_kwargs: dict = no_console_kwargs()
    try:
        result = subprocess.run(
            # The app's own checkout, not the project: since v4.0.0 the two
            # are separate repositories, and the version string is about
            # the app. (A frozen build has no checkout -> plain number.)
            ["git", *args], cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
            timeout=5, **popen_kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


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
