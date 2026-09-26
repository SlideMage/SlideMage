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

    new_heading = next(
        label for label in tab._chapter_headers.values()
        if label.text() == "Section: New"
    )
    row = next(
        tab.grid.getItemPosition(i)[0] for i in range(tab.grid.count())
        if tab.grid.itemAt(i).widget() is new_heading
    )
    number_cell = tab.grid.itemAtPosition(row, 0).widget()
    up = next(
        button for button in number_cell.findChildren(QPushButton)
        if button.text() == "↑"
    )
    assert up.isEnabled()
    up.click()
    updated = _read(path)
    assert updated.index("\\section{Two}") < updated.index("\\section{New}")
    assert updated.index("\\section{New}") < updated.index("\\slide{ccc-Two}")

    new_heading = next(
        label for label in tab._chapter_headers.values()
        if label.text() == "Section: New"
    )
    row = next(
        tab.grid.getItemPosition(i)[0] for i in range(tab.grid.count())
        if tab.grid.itemAt(i).widget() is new_heading
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
    assert updated.index("\\slide{ccc-Two}") < updated.index("\\section{New}")
    assert updated.index("\\section{New}") < updated.index("\\section{Two}")


def test_section_up_crosses_legacy_block_comments(tmp_path, qapp):
    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "%% Block: legacy\n%%\n"
        "\\slide{aaa-First}\n\\slide{bbb-Second}\n"
        "%% End block: legacy\n%%\n"
        "\\section{After}\n\\end{document}\n"
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
    heading = next(label for label in tab._chapter_headers.values()
                   if label.text() == "Section: After")
    row = next(tab.grid.getItemPosition(i)[0] for i in range(tab.grid.count())
               if tab.grid.itemAt(i).widget() is heading)
    controls = tab.grid.itemAtPosition(row, 0).widget()
    up = next(button for button in controls.findChildren(QPushButton)
              if button.text() == "↑")
    assert up.isEnabled()
    up.click()
    updated = _read(path)
    assert updated.index("\\slide{aaa-First}") < updated.index("\\section{After}")
    assert updated.index("\\section{After}") < updated.index("\\slide{bbb-Second}")


def test_typing_a_slide_number_moves_the_slide(tmp_path, qapp):
    from PySide6.QtWidgets import QLineEdit

    slides = "".join(f"\\slide{{{c * 3}-{c.upper()}}}\n" for c in "abcdef")
    text = "\\documentclass{beamer}\n\\begin{document}\n" + slides + "\\end{document}\n"
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
        updated = _read(path)
        tab.reload(replace(tab.deck, text=updated, chapters=_parse_chapters(updated)))

    tab = DeckEditorTab(SimpleNamespace(after_deck_edit=after_deck_edit), deck)
    sixth = [edit for edit in tab.findChildren(QLineEdit) if edit.text() == "6"][0]
    sixth.setText("2")
    sixth.editingFinished.emit()
    assert [line[7:10] for line in _read(path).splitlines() if line.startswith("\\slide")] == [
        "aaa", "fff", "bbb", "ccc", "ddd", "eee",
    ]


def test_select_all_toggles_every_slide_checkbox(tmp_path, qapp):
    from PySide6.QtCore import Qt

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{aaa-One}\n\\slide{bbb-Two}\n\\slide{ccc-Three}\n"
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
    tab = DeckEditorTab(SimpleNamespace(), deck)
    boxes = [box for box, _call in tab._row_checkboxes]
    assert len(boxes) == 3
    assert not tab.select_all_box.isHidden()
    assert tab.select_all_box.checkState() == Qt.CheckState.Unchecked

    boxes[0].setChecked(True)
    assert tab.select_all_box.checkState() == Qt.CheckState.PartiallyChecked

    tab.select_all_box.click()
    assert all(box.isChecked() for box in boxes)
    assert tab.select_all_box.checkState() == Qt.CheckState.Checked
    assert tab.bulk_remove_button.text() == "Remove selected (3)"

    tab.select_all_box.click()
    assert not any(box.isChecked() for box in boxes)
    assert tab.select_all_box.checkState() == Qt.CheckState.Unchecked

    tab.grid_view_radio.setChecked(True)
    assert tab.select_all_box.isHidden()
