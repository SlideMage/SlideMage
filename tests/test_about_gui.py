"""The About sheet: the release history of version.py, and the license."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from slidemage import app_info
from slidemage import version as version_mod
from slidemage.ui.dialogs.about import AboutSheet


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_summary_is_the_first_sentence_or_a_cut_at_a_word():
    assert app_info.summary("One. Two.") == "One."
    assert app_info.summary("short") == "short"
    long = "word " * 100
    cut = app_info.summary(long)
    assert cut.endswith("…") and len(cut) <= app_info.SUMMARY_MAX_CHARS + 1 and " …" not in cut


def test_sheet_has_the_history_newest_first_and_the_license(qapp):
    sheet = AboutSheet()
    html = sheet.browser.toHtml()
    newest = version_mod.parse_history()[-1].version
    assert version_mod.VERSION in html and newest in html
    assert "Slidemaster" in sheet.findChild(QPlainTextEdit).toPlainText()


def test_a_toggle_link_expands_one_entry_in_place(qapp):
    # The newest entry with something to collapse (a short entry gets no toggle).
    index = next(i for i, e in enumerate(reversed(version_mod.parse_history()))
                 if app_info.summary(e.description) != e.description)
    sheet = AboutSheet()
    assert sheet._expanded == set() and f"toggle:{index}" in sheet._build_html()
    sheet._on_anchor_clicked(QUrl(f"toggle:{index}"))
    assert sheet._expanded == {index} and "[show less]" in sheet._build_html()
    sheet._on_anchor_clicked(QUrl(f"toggle:{index}"))
    assert sheet._expanded == set()
    sheet._on_anchor_clicked(QUrl("https://example.org"))      # other links do nothing
