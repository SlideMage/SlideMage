"""Info menu's version-history/license window (2026-08-25, direct
instruction; License tab added 2026-09-22, direct instruction) -- reads
version.parse_history() directly rather than maintaining a separate
changelog, so a new history paragraph appended to version.py's own
docstring (this project's standing per-bump convention -- see
VERSION_NUMBER's own comment there) shows up here automatically, with
nothing else to keep in sync. QTextBrowser (already part of QtWidgets, no
new dependency) renders a small hand-built HTML string -- see
qt_transcript_preview_tab.py for the same "why not QtWebEngine" reasoning.

Each entry collapses to a one-line summary by default (2026-09-09, direct
instruction) -- some of these descriptions run to a dozen sentences, and a
window full of them at full length meant scrolling past nine paragraphs to
find the one you actually wanted. Clicking "show more"/"show less" expands
just that one entry in place, via a custom `toggle:N` link scheme
intercepted through anchorClicked() rather than let through -- QTextBrowser
would otherwise try to navigate to it as a real document via setSource()
and blank itself, the same failure mode setOpenExternalLinks(False) alone
doesn't cover (that property only governs http(s) links); setOpenLinks(False)
is what actually stops the browser's own navigation while leaving
anchorClicked() to fire regardless.

The window is a QTabWidget with two tabs -- "Version history" (the
original content, unchanged) and "License" (plain-text LICENSE file from
the project root, read fresh on each open so it reflects whatever's
actually on disk, never embedded/duplicated here) -- rather than a
separate menu action, direct instruction: "as a separate tab in the
window that opens when one clicks Info."
"""
from __future__ import annotations

import html as _html
import importlib.metadata
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import version as version_mod
# Running from a source checkout without `pip install`: the repo root's copy.
_CHECKOUT_LICENSE = Path(__file__).resolve().parents[2] / "LICENSE"


def _license_text() -> str:
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

# Below this many characters, an already-short description just gets
# shown in full with no toggle at all -- there is nothing meaningful left
# to collapse, and a "show more" link that expands to the same text it
# replaced would just be a confusing no-op click.
_SUMMARY_MAX_CHARS = 200


def _summary(text: str) -> str:
    """The one-line collapsed form of a history entry's description.

    Prefers the first sentence (through the first ". "), since these
    descriptions are written as flowing prose and its own first sentence
    is usually already a fair one-line summary of the whole entry. Falls
    back to a plain word-boundary truncation for the (common) case where
    the first sentence alone still runs well past a single line.
    """
    period = text.find(". ")
    if period != -1 and period + 1 <= _SUMMARY_MAX_CHARS:
        return text[: period + 1]
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    cut = text.rfind(" ", 0, _SUMMARY_MAX_CHARS)
    if cut <= 0:
        cut = _SUMMARY_MAX_CHARS
    return text[:cut].rstrip() + "…"


class VersionHistoryDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Info")
        self.setModal(True)
        self.resize(560, 640)

        # Indices (into the newest-first list _build_html() itself builds)
        # of entries currently shown in full -- collapsed is the default,
        # nothing pre-expanded on open.
        self._expanded: set[int] = set()

        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        # Stops QTextBrowser's own setSource()-based navigation on a
        # clicked link (which would try to load "toggle:3" as a document
        # and blank the view) -- anchorClicked() below still fires
        # regardless of this setting, so nothing about the actual toggle
        # handling depends on it being True.
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.browser.setHtml(self._build_html())
        tabs.addTab(self.browser, "Version history")
        tabs.addTab(self._build_license_tab(), "License")
        layout.addWidget(tabs, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _build_license_tab(self) -> QWidget:
        """Plain read-only view of the project root's own LICENSE file,
        read fresh on each dialog open -- no embedded copy here to drift
        out of sync with it. A monospaced QPlainTextEdit (not QTextBrowser)
        since LICENSE is plain text, not HTML."""
        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(_license_text())
        return text_edit

    def _on_anchor_clicked(self, url: QUrl) -> None:
        href = url.toString()
        if not href.startswith("toggle:"):
            return
        index = int(href[len("toggle:"):])
        if index in self._expanded:
            self._expanded.discard(index)
        else:
            self._expanded.add(index)
        # setHtml() resets the scrollbar to the top -- restoring its prior
        # position keeps the entry just toggled roughly where the click
        # happened, rather than jumping the whole window back to the very
        # first entry on every click.
        scrollbar = self.browser.verticalScrollBar()
        position = scrollbar.value()
        self.browser.setHtml(self._build_html())
        scrollbar.setValue(position)

    def _build_html(self) -> str:
        # Newest first -- parse_history() itself returns oldest-first
        # (matching the docstring's own top-to-bottom chronological order).
        entries = list(reversed(version_mod.parse_history()))
        parts = [f"<h2>SlideMage &mdash; {_html.escape(version_mod.VERSION)}</h2>"]
        for index, entry in enumerate(entries):
            summary = _summary(entry.description)
            if index in self._expanded:
                body = _html.escape(entry.description)
                toggle_label = "show less"
            else:
                body = _html.escape(summary)
                toggle_label = "show more"
            # No toggle at all when there is nothing to collapse -- an
            # already-one-line description summarizes to itself.
            toggle_html = (
                f' <a href="toggle:{index}" style="text-decoration:none;">'
                f"[{toggle_label}]</a>"
                if summary != entry.description else ""
            )
            parts.append(
                f"<p><b>{_html.escape(entry.version)}</b> "
                f"<span style='color: gray;'>({_html.escape(entry.meta)})</span><br>"
                f"{body}{toggle_html}</p><hr>"
            )
        return "".join(parts)
