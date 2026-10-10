"""What the About sheet (ui/dialogs/about.py) shows besides the release history of version.py:
SlideMage's own license, and the one-line form of a history entry.

Free of Qt.
"""
from __future__ import annotations

import importlib.metadata
from pathlib import Path

# Running from a source checkout without `pip install`: the repo root's copy.
_CHECKOUT_LICENSE = Path(__file__).resolve().parents[2] / "LICENSE"

# Below this many characters, an already-short description is shown in full with no toggle:
# there is nothing meaningful left to collapse.
SUMMARY_MAX_CHARS = 200


def license_text() -> str:
    """SlideMage's own LICENSE, as shipped in the installed package's metadata."""
    try:
        text = importlib.metadata.distribution("slidemage").read_text("licenses/LICENSE")
    except importlib.metadata.PackageNotFoundError:
        text = None
    if text is not None:
        return text
    try:
        return _CHECKOUT_LICENSE.read_text(encoding="utf-8")
    except OSError as exc:
        return f"License text not found (not installed, and {_CHECKOUT_LICENSE}: {exc})"


def summary(text: str) -> str:
    """The one-line collapsed form of a history entry's description.

    Prefers the first sentence (through the first ". "), since these descriptions are written as
    flowing prose and the first sentence is usually already a fair summary of the whole entry.
    Falls back to a word-boundary truncation when the first sentence alone runs past a line.
    """
    period = text.find(". ")
    if period != -1 and period + 1 <= SUMMARY_MAX_CHARS:
        return text[: period + 1]
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    cut = text.rfind(" ", 0, SUMMARY_MAX_CHARS)
    if cut <= 0:
        cut = SUMMARY_MAX_CHARS
    return text[:cut].rstrip() + "…"
