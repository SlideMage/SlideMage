# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The About sheet: the release history of version.py, and the license."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QPlainTextEdit

from slidemage import app_info
from slidemage import version as version_mod
from slidemage.ui.dialogs import about
from slidemage.ui.dialogs.about import AboutSheet


def test_sheet_shows_history_license_and_expands_an_entry(qapp):
    sheet = AboutSheet()
    html = sheet.browser.toHtml()
    newest = version_mod.parse_history()[-1].version
    assert version_mod.VERSION in html and newest in html
    # Regression: the license used to be looked up in the project folder.
    assert "LaTeX framework" in sheet.findChild(QPlainTextEdit).toPlainText()
    entries = about._unreleased() + list(reversed(version_mod.parse_history()))
    index = next(i for i, e in enumerate(entries) if app_info.summary(e.description) != e.description)
    description = entries[index].description
    assert f"toggle:{index}" in html and description not in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl(f"toggle:{index}"))
    assert description in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl(f"toggle:{index}"))
    assert description not in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl("https://example.org"))


def test_unreleased_fragments_are_listed_on_top(qapp, monkeypatch, tmp_path):
    from slidemage import change_fragments
    (tmp_path / "fix.md").write_text("kind: fixed\nreason: issue #1\n\nThe queue starts. More text here.\n\n"
                                     "NEW:\n- Fixed.\n", encoding="utf-8")
    monkeypatch.setattr(change_fragments, "read_all", lambda: [change_fragments.parse(tmp_path / "fix.md")])
    sheet = AboutSheet()
    text = sheet.browser.toPlainText()
    assert text.index("Unreleased (fixed, issue #1)") < text.index("\n" + version_mod.parse_history()[-1].version + " (")
    assert "The queue starts." in text
