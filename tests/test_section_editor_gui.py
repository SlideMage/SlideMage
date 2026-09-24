"""Section rows are editable in the deck slide view."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage.archive import _read
from slidemage.deck_scan import Deck, _parse_chapters
from slidemage.qt_deck_editor_tab import DeckEditorTab, QInputDialog


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_sections_are_rows_and_can_be_added_and_reordered(tmp_path, monkeypatch, qapp):
    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{aaa-Front}\n"
        "\\section{One}\n\\slide{bbb-One}\n"
        "\\section{Empty}\n"
        "\\section{Two}\n\\slide{ccc-Two}\n"
        "\\end{document}\n"
    )
    path = tmp_path / "course.tex"
    path.write_text(text, encoding="utf-8", newline="")
    deck = Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False,
        preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
        chapters=_parse_chapters(text), output_folders={},
    )
    tab = None

    def after_deck_edit(_path, _summary, previous_text):
        assert previous_text == tab.deck.text
        updated = _read(path)
        tab.reload(replace(tab.deck, text=updated, chapters=_parse_chapters(updated)))

    tab = DeckEditorTab(SimpleNamespace(after_deck_edit=after_deck_edit), deck)
    assert [tab.chapter_combo.itemText(i) for i in range(tab.chapter_combo.count())] == [
        "(before first chapter)", "One", "Empty", "Two",
    ]
    assert len(tab._chapter_headers) == 4
    assert any(
        label.text() == "Section: Empty" for label in tab._chapter_headers.values()
    )

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("New", True))
    add = next(
        button for button in tab.findChildren(QPushButton)
        if button.text() == "Add section…"
    )
    add.click()
    assert [chapter.title for chapter in tab.deck.chapters] == [
        "One", "Empty", "Two", "New",
    ]
    assert tab.chapter_combo.itemText(4) == "New"

    two_heading = tab._chapter_headers[3]
    row = next(
        tab.grid.getItemPosition(i)[0] for i in range(tab.grid.count())
        if tab.grid.itemAt(i).widget() is two_heading
    )
    number_cell = tab.grid.itemAtPosition(row, 0).widget()
    down = next(
        button for button in number_cell.findChildren(QPushButton)
        if button.text() == "↓"
    )
    down.click()
    updated = _read(path)
    assert updated.index("\\section{New}") < updated.index("\\section{Two}")
    assert updated.index("\\section{Two}") < updated.index("\\slide{ccc-Two}")

    slide_label = next(
        label for label in tab._id_labels.values() if label.text() == "ccc-Two"
    )
    row = next(
        tab.grid.getItemPosition(i)[0] for i in range(tab.grid.count())
        if tab.grid.itemAt(i).widget() is slide_label
    )
    number_cell = tab.grid.itemAtPosition(row, 0).widget()
    up = next(
        button for button in number_cell.findChildren(QPushButton)
        if button.text() == "↑"
    )
    up.click()
    updated = _read(path)
    assert updated.index("\\section{New}") < updated.index("\\slide{ccc-Two}")
    assert updated.index("\\slide{ccc-Two}") < updated.index("\\section{Two}")
