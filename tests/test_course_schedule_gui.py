"""Course schedule import placement, group choice, and slide creation."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage import deck_editor, qt_course_schedule_dialog, slide_ids
from slidemage.course_schedule import CourseGroup, CourseSchedule, CourseSession
from slidemage.deck_scan import Deck
from slidemage.qt_course_schedule_dialog import (
    CourseScheduleDialog,
    build_schedule_slide_source,
    insert_schedule_slide,
)
from slidemage.qt_deck_editor_tab import DeckEditorTab


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(tmp_path, course_url=COURSE_URL):
    path = tmp_path / "course.tex"
    text = "\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n"
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[], course_url=course_url,
    )


def test_editor_import_button_requires_link_and_course_deck(tmp_path, qapp):
    tab = DeckEditorTab(SimpleNamespace(), make_deck(tmp_path))
    toolbar = tab.layout().itemAt(0).layout()
    labels = [toolbar.itemAt(i).widget().text()
              for i in range(toolbar.count())
              if isinstance(toolbar.itemAt(i).widget(), QPushButton)]
    assert "Import sessions…" in labels
    assert "Insert block…" not in labels
    assert tab.import_sessions_button.isEnabled()

    tab.reload(replace(tab.deck, course_url=None))
    assert not tab.import_sessions_button.isEnabled()

    tab.reload(replace(tab.deck, tags=["research"], course_url=COURSE_URL))
    assert tab.import_sessions_button.isHidden()

    tab.reload(replace(tab.deck, tags=[]))
    assert not tab.import_sessions_button.isHidden()
    assert tab.import_sessions_button.isEnabled()


def test_schedule_positions_follow_regular_slide_calls(tmp_path):
    deck = make_deck(tmp_path)
    text = (
        "\\begin{document}\n\\section{Intro}\n"
        "\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n"
        "\\end{document}\n"
    )
    deck.path.write_text(text, encoding="utf-8", newline="")
    deck = replace(deck, text=text)
    positions = deck_editor.slide_insert_positions(deck)
    assert [position.label for position in positions] == [
        "At the beginning", "After 1. aaa-EN-First", "After 2. bbb-EN-Second",
    ]
    assert positions[-1].insert_at == text.index("\\end{document}")


def test_multiple_groups_trigger_choice_and_preview(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(CourseScheduleDialog, "_start_fetch", lambda self: None)
    groups = (
        CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),
        CourseGroup("Gruppe Wirtschaftsinformatik", (CourseSession("06.10.2026", "08:30", "10:00", "HS 1", "Abhaltung", ""),)),
    )
    offered = []

    def choose(_parent, _title, _label, names, _initial, _editable):
        offered.extend(names)
        return names[1], True

    monkeypatch.setattr(qt_course_schedule_dialog.QInputDialog, "getItem", choose)
    dialog = CourseScheduleDialog(None, make_deck(tmp_path))
    dialog._show_schedule(CourseSchedule("Bachelorkurs", groups))

    assert offered == [group.name for group in groups]
    assert "Gruppe Wirtschaftsinformatik" in dialog.preview.toPlainText()
    assert "06.10.2026" in dialog.preview.toPlainText()
    assert "05.10.2026" not in dialog.preview.toPlainText()
    assert dialog.insert_button.isEnabled()



def test_canceled_fetch_does_not_open_group_query(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(CourseScheduleDialog, "_start_fetch", lambda self: None)
    dialog = CourseScheduleDialog(None, make_deck(tmp_path))
    dialog.reject()
    groups = (CourseGroup("First", ()), CourseGroup("Second", ()))

    def unexpected_query(*_args):
        raise AssertionError("group query opened after cancel")

    monkeypatch.setattr(qt_course_schedule_dialog.QInputDialog, "getItem", unexpected_query)
    dialog._show_schedule(CourseSchedule("Course", groups))
    assert dialog.slide_source is None


def test_insertion_creates_editable_slide_and_deck_call(tmp_path, monkeypatch):
    deck = make_deck(tmp_path)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    source = build_schedule_slide_source(r"\begin{tabular}{ll}Datum & Zeit \\ \end{tabular}")

    slide_path = insert_schedule_slide(deck, position, source)

    assert slide_path.name == "abc-DE-Course-Sessions-current.tex"
    assert slide_path.read_text(encoding="utf-8") == source.replace("\r\n", "\n")
    assert r"\slide{abc-DE-Course-Sessions}" in deck.path.read_text(encoding="utf-8")
    assert '"abc"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")


def test_stale_deck_keeps_external_change_and_removes_new_slide(tmp_path, monkeypatch):
    deck = make_deck(tmp_path)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    deck.path.write_text(deck.text + "% external edit\n", encoding="utf-8", newline="")

    with pytest.raises(deck_editor.StaleFileError):
        insert_schedule_slide(deck, position, build_schedule_slide_source("Table"))

    assert "% external edit" in deck.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "slides").glob("*.tex"))
