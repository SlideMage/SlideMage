"""The ticked rows of a deck tab survive a reload (saving a slide's source,
any deck edit, switching views)."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from slidemage.deck_scan import Deck, _parse_chapters
from slidemage.qt_deck_editor_tab import DeckEditorTab

TEXT = (
    "\\documentclass{beamer}\n\\begin{document}\n"
    "\\slide{aaa-First}\n\\slide{bbb-Second}\n"
    "\\slidestep{ccc-Step}[instructor]{1}\n\\slidestep{ccc-Step}[instructor]{1}\n"
    "\\slide{ddd-Last}\n"
    "\\end{document}\n"
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_tab(tmp_path):
    path = tmp_path / "course.tex"
    path.write_text(TEXT, encoding="utf-8", newline="")
    deck = Deck(
        name="course", path=path, archived=False, text=TEXT,
        supports_version=False, uses_biblatex=False,
        preamble_end=TEXT.index("\\begin{document}") + len("\\begin{document}"),
        chapters=_parse_chapters(TEXT), output_folders={},
    )
    return DeckEditorTab(SimpleNamespace(), deck), deck


def ticked(tab):
    return [(call.id_slug, i) for i, (box, call) in enumerate(tab._row_checkboxes) if box.isChecked()]


def test_ticked_rows_stay_ticked_after_a_reload(tmp_path, qapp):
    tab, deck = make_tab(tmp_path)
    boxes = tab._row_checkboxes
    boxes[1][0].setChecked(True)      # bbb
    boxes[3][0].setChecked(True)      # the second of the two identical ccc steps
    assert ticked(tab) == [("bbb-Second", 1), ("ccc-Step", 3)]

    tab.reload(replace(deck))          # what saving a slide's source triggers
    assert ticked(tab) == [("bbb-Second", 1), ("ccc-Step", 3)]
    assert tab.bulk_remove_button.text() == "Remove selected (2)"
    assert not tab.bulk_remove_button.isHidden()


def test_selection_follows_the_slides_when_the_deck_changes(tmp_path, qapp):
    tab, deck = make_tab(tmp_path)
    tab._row_checkboxes[3][0].setChecked(True)     # ddd? no: ccc #2 -- index 3
    tab._row_checkboxes[1][0].setChecked(True)     # bbb
    # a slide is inserted at the top: every offset and position moves
    text = TEXT.replace("\\slide{aaa-First}\n", "\\slide{new-Top}\n\\slide{aaa-First}\n")
    tab.reload(replace(deck, text=text, chapters=_parse_chapters(text)))
    assert [slug for slug, _ in ticked(tab)] == ["bbb-Second", "ccc-Step"]


def test_an_unticked_row_stays_unticked_and_removed_slides_drop_out(tmp_path, qapp):
    tab, deck = make_tab(tmp_path)
    tab._row_checkboxes[0][0].setChecked(True)
    tab._row_checkboxes[0][0].setChecked(False)
    tab._row_checkboxes[4][0].setChecked(True)     # ddd
    text = TEXT.replace("\\slide{ddd-Last}\n", "")
    tab.reload(replace(deck, text=text, chapters=_parse_chapters(text)))
    assert ticked(tab) == []


def test_selection_survives_a_trip_through_the_grid_view(tmp_path, qapp):
    tab, _deck = make_tab(tmp_path)
    tab._row_checkboxes[1][0].setChecked(True)
    tab.grid_view_radio.setChecked(True)           # no checkboxes in this view
    tab.list_view_radio.setChecked(True)
    assert ticked(tab) == [("bbb-Second", 1)]
