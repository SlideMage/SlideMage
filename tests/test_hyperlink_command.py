"""The source editor's hyperlink command creates clickable LaTeX links."""
from __future__ import annotations

from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from slidemage import qt_slide_source_tab, transcript
from slidemage.qt_slide_source_tab import SlideSourceTab, format_hyperlink
from slidemage.qt_theme import ThemeManager


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_editor(tmp_path, qapp):
    path = tmp_path / "deck.tex"
    path.write_text("Word appears here", encoding="utf-8")
    app = SimpleNamespace(theme=ThemeManager(), log=lambda _line: None)
    return SlideSourceTab(app, path), path


def test_hyperlink_formatter_escapes_text_and_preserves_url():
    url = "https://example.org/a_b?x=1&y=2#part%20x"
    assert format_hyperlink(" R&D ", url) == (
        r"\href{https://example.org/a\_b?x=1\&y=2\#part\%20x}{R\&D}"
    )


@pytest.mark.parametrize("word,url", [
    ("", "https://example.org"),
    ("Word", "javascript:alert(1)"),
    ("Word", "https://example.org/a b"),
    ("Word", "https://example.org:bad"),
])
def test_hyperlink_formatter_rejects_invalid_input(word, url):
    with pytest.raises(ValueError):
        format_hyperlink(word, url)


def test_dropdown_prompts_for_label_and_url_and_replaces_selection(tmp_path, qapp, monkeypatch):
    tab, path = make_editor(tmp_path, qapp)
    cursor = tab.widget.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
    tab.widget.setTextCursor(cursor)
    answers = iter([("R&D", True), ("https://example.org/page?x=1&y=2", True)])
    prompts = []

    def prompt(*_args, **kwargs):
        prompts.append(kwargs)
        return next(answers)

    monkeypatch.setattr(qt_slide_source_tab.QInputDialog, "getText", prompt)
    index = tab.command_combo.findText(r"\href{LINK}{WORD} (hyperlink…)")
    assert index > 0
    tab.command_combo.setCurrentIndex(index)
    tab.command_combo.activated.emit(index)

    assert prompts[0]["text"] == "Word"
    assert tab.widget.toPlainText() == (
        r"\href{https://example.org/page?x=1\&y=2}{R\&D} appears here"
    )
    assert path.read_text(encoding="utf-8") == "Word appears here"
    assert tab.command_combo.currentIndex() == 0


def test_canceling_url_prompt_keeps_source_unchanged(tmp_path, qapp, monkeypatch):
    tab, _ = make_editor(tmp_path, qapp)
    answers = iter([("Word", True), ("", False)])
    monkeypatch.setattr(qt_slide_source_tab.QInputDialog, "getText",
                        lambda *_args, **_kwargs: next(answers))
    index = tab.command_combo.findText(r"\href{LINK}{WORD} (hyperlink…)")
    tab.command_combo.setCurrentIndex(index)
    tab.command_combo.activated.emit(index)
    assert tab.widget.toPlainText() == "Word appears here"


def test_hyperlink_url_survives_transcript_html():
    url = "https://example.org/a_b?x=1&y=2#part%20x"
    source = format_hyperlink("R&D", url)
    html = transcript._inline_html(transcript._inline_markdown(source))

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.targets = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.targets.append(dict(attrs)["href"])

    parsed = Links()
    parsed.feed(html)
    assert parsed.targets == [url]
    assert "R&amp;D" in html
