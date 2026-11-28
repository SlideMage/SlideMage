# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The About sheet (UI_REDESIGN_PLAN.md, step 9): SlideMage's release history and license.

The history is version.parse_history(), read from CHANGELOG.md, so a new history
entry appended there (one per release, by packaging/make_release.py) shows up here with nothing else to
keep in sync; a checkout's unreleased changes/ fragments are listed on top, as "Unreleased". Each entry collapses to a one-line summary (some run to a dozen sentences);
"show more" expands that one entry in place. The toggles are links of a made-up `toggle:N` scheme
that the browser must not navigate to (setOpenLinks(False)), so anchorClicked() is all that
reacts. The license is the LICENSE file, read on each open.
"""
from __future__ import annotations

import html as _html
import re

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser

from ... import app_info, change_fragments
from ... import version as version_mod
from ..kit.theme import ThemeManager
from ..kit.widgets import ModalSheet


def _unreleased() -> list[version_mod.HistoryEntry]:
    """The changes/ fragments of a checkout (issue #247) as entries headed "Unreleased"; none in a frozen build."""
    entries = []
    for fragment in change_fragments.read_all():
        description = re.sub(r"\s+", " ", " ".join(fragment.technical)).strip()
        entries.append(version_mod.HistoryEntry(
            version="Unreleased", meta=f"{fragment.kind}, {fragment.reason}", description=description,
            summary=fragment.summary, news=fragment.news))
    return entries


class AboutSheet(ModalSheet):
    def __init__(self, parent=None) -> None:
        super().__init__("About SlideMage", parent, width=640)
        self.setMinimumHeight(620)
        # Indices (into the newest-first list _build_html() builds) of the entries shown in full.
        self._expanded: set[int] = set()
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        theme = parent.theme if parent is not None else ThemeManager()
        self.browser.document().setDefaultStyleSheet(f"a {{ color: {theme.tokens.link}; }}")
        self.browser.anchorClicked.connect(self._on_anchor_clicked)
        self.browser.setHtml(self._build_html())
        self.add_tab("Version history", self.browser)
        license_view = QPlainTextEdit()
        license_view.setReadOnly(True)
        license_view.setPlainText(app_info.license_text())
        self.add_tab("License", license_view)
        self.add_button("Close", kind="primary", role="accept")

    def _on_anchor_clicked(self, url: QUrl) -> None:
        href = url.toString()
        if not href.startswith("toggle:"):
            return
        index = int(href[len("toggle:"):])
        self._expanded ^= {index}
        # setHtml() resets the scrollbar: put it back, so the entry just toggled stays where it was.
        scrollbar = self.browser.verticalScrollBar()
        position = scrollbar.value()
        self.browser.setHtml(self._build_html())
        scrollbar.setValue(position)

    def _build_html(self) -> str:
        # Newest first -- parse_history() returns oldest first; a checkout's unreleased fragments on top.
        entries = _unreleased() + list(reversed(version_mod.parse_history()))
        parts = [f"<h2>SlideMage &mdash; {_html.escape(version_mod.VERSION)}</h2>"]
        for index, entry in enumerate(entries):
            summary = app_info.summary(entry.description)
            expanded = index in self._expanded
            body = _html.escape(entry.description if expanded else summary)
            # No toggle when there is nothing to collapse.
            toggle = (f' <a href="toggle:{index}" style="text-decoration:none;">'
                      f"[{'show less' if expanded else 'show more'}]</a>"
                      if summary != entry.description else "")
            parts.append(
                f"<p><b>{_html.escape(entry.version)}</b> "
                f"<span style='color: gray;'>({_html.escape(entry.meta)})</span><br>"
                f"{body}{toggle}</p><hr>")
        return "".join(parts)
