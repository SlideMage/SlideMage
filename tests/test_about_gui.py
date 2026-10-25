# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The About sheet: the release history of version.py, and the license."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QPlainTextEdit

from slidemage import app_info
from slidemage import version as version_mod
from slidemage.ui.dialogs.about import AboutSheet


def test_summary_is_the_first_sentence_or_a_cut_at_a_word():
    assert app_info.summary("One. Two.") == "One."
    assert app_info.summary("short") == "short"
    long = "word " * 100
    cut = app_info.summary(long)
    assert cut.endswith("…") and len(cut) <= app_info.SUMMARY_MAX_CHARS + 1 and " …" not in cut


def test_sheet_shows_history_license_and_expands_an_entry(qapp):
    sheet = AboutSheet()
    html = sheet.browser.toHtml()
    newest = version_mod.parse_history()[-1].version
    assert version_mod.VERSION in html and newest in html
    # Regression: the license used to be looked up in the project folder.
    assert "LaTeX framework" in app_info.license_text()
    assert "LaTeX framework" in sheet.findChild(QPlainTextEdit).toPlainText()
    entries = list(reversed(version_mod.parse_history()))
    index = next(i for i, e in enumerate(entries) if app_info.summary(e.description) != e.description)
    description = entries[index].description
    assert f"toggle:{index}" in html and description not in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl(f"toggle:{index}"))
    assert description in sheet.browser.toPlainText() and "[show less]" in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl(f"toggle:{index}"))
    assert description not in sheet.browser.toPlainText()
    sheet.browser.anchorClicked.emit(QUrl("https://example.org"))
