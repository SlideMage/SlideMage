"""Admin slides dialog: fetch results, checkbox/group/lecturer selection,
placement, and slide creation."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage import deck_editor, slide_ids
from slidemage.course_schedule import (
    CourseDetail,
    CourseGroup,
    CourseSchedule,
    CourseSession,
    Lecturer,
)
from slidemage.deck_scan import Deck
from slidemage.qt_admin_slides_dialog import (
    AdminSlidesDialog,
    build_sessions_slide_source,
    build_title_slide_source,
    insert_admin_slides,
)
from slidemage.qt_deck_editor_tab import DeckEditorTab


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"

DETAIL = CourseDetail(
    number="355.001", title="Bachelorkurs (Management Science)",
    semester="Wintersemester 2026/27",
    lecturers=(
        Lecturer("Andreas", "Darmann", "Vortragende*r"),
        Lecturer("Jürgen", "Fleiß", "Vortragende*r"),
    ),
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(tmp_path, course_url=COURSE_URL, language="de"):
    path = tmp_path / "course.tex"
    text = (
        "\\documentclass{beamer}\n\\decklanguage[" + language + "]\n"
        "\\begin{document}\n\\end{document}\n"
    )
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=[], course_url=course_url,
    )


def make_dialog(tmp_path, monkeypatch, language="de"):
    monkeypatch.setattr(AdminSlidesDialog, "_start_fetch", lambda self: None)
    return AdminSlidesDialog(None, make_deck(tmp_path, language=language))


def test_editor_admin_slides_button_requires_link_and_course_deck(tmp_path, qapp):
    tab = DeckEditorTab(SimpleNamespace(), make_deck(tmp_path))
    toolbar = tab.layout().itemAt(0).layout()
    labels = [toolbar.itemAt(i).widget().text()
              for i in range(toolbar.count())
              if isinstance(toolbar.itemAt(i).widget(), QPushButton)]
    assert "Admin slides…" in labels
    assert "Insert block…" not in labels
    assert tab.admin_slides_button.isEnabled()

    tab.reload(replace(tab.deck, course_url=None))
    assert not tab.admin_slides_button.isEnabled()

    tab.reload(replace(tab.deck, tags=["research"], course_url=COURSE_URL))
    assert tab.admin_slides_button.isHidden()

    tab.reload(replace(tab.deck, tags=[]))
    assert not tab.admin_slides_button.isHidden()
    assert tab.admin_slides_button.isEnabled()


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


def test_multiple_groups_and_lecturers_build_combined_preview(tmp_path, monkeypatch, qapp):
    dialog = make_dialog(tmp_path, monkeypatch)
    groups = (
        CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),
        CourseGroup("Gruppe Wirtschaftsinformatik", (CourseSession("06.10.2026", "08:30", "10:00", "HS 1", "Abhaltung", ""),)),
    )
    dialog._on_loaded(CourseSchedule(groups), DETAIL)

    assert not dialog.group_combo.isHidden()
    assert [dialog.group_combo.itemText(i) for i in range(dialog.group_combo.count())] == [
        group.name for group in groups
    ]
    assert "05.10.2026" in dialog.preview.toPlainText()
    assert "Bachelorkurs (Management Science)" in dialog.preview.toPlainText()
    assert "Andreas Darmann, Jürgen Fleiß" in dialog.preview.toPlainText()
    assert dialog.insert_button.isEnabled()

    dialog.group_combo.setCurrentIndex(1)
    assert "06.10.2026" in dialog.preview.toPlainText()
    assert "05.10.2026" not in dialog.preview.toPlainText()

    lecturer_checkbox, _ = dialog._lecturer_checks[0]
    lecturer_checkbox.setChecked(False)
    assert "Andreas Darmann" not in dialog.preview.toPlainText()
    assert "Jürgen Fleiß" in dialog.preview.toPlainText()


def test_empty_groups_are_labelled_in_the_picker_only(tmp_path, monkeypatch, qapp):
    dialog = make_dialog(tmp_path, monkeypatch)
    groups = (
        CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),
        CourseGroup("Gruppe Operations Management", ()),
    )
    dialog._on_loaded(CourseSchedule(groups), DETAIL)

    assert [dialog.group_combo.itemText(i) for i in range(dialog.group_combo.count())] == [
        "Standardgruppe", "Gruppe Operations Management (empty)",
    ]
    dialog.group_combo.setCurrentIndex(1)
    assert r"\textbf{Gruppe Operations Management}\par Keine Termine" in dialog.preview.toPlainText()


def test_unchecking_a_section_drops_it_from_the_plan(tmp_path, monkeypatch, qapp):
    dialog = make_dialog(tmp_path, monkeypatch)
    groups = (CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),)
    dialog._on_loaded(CourseSchedule(groups), DETAIL)

    dialog.sessions_group.setChecked(False)
    assert [suffix for suffix, _ in dialog.slide_specs] == ["Title-Slide"]

    dialog.title_group.setChecked(False)
    assert dialog.slide_specs == []
    assert not dialog.insert_button.isEnabled()


def test_failed_fetch_disables_its_own_section_only(tmp_path, monkeypatch, qapp):
    dialog = make_dialog(tmp_path, monkeypatch)
    dialog._on_loaded("network unreachable", DETAIL)

    assert not dialog.sessions_group.isChecked()
    assert not dialog.sessions_group.isEnabled()
    assert dialog.title_group.isEnabled()
    assert [suffix for suffix, _ in dialog.slide_specs] == ["Title-Slide"]


def test_canceled_dialog_ignores_a_late_fetch_result(tmp_path, monkeypatch, qapp):
    dialog = make_dialog(tmp_path, monkeypatch)
    dialog.reject()
    dialog._on_loaded(CourseSchedule((CourseGroup("First", ()),)), DETAIL)
    assert dialog.slide_specs == []


def test_insertion_creates_editable_slides_and_deck_calls_in_order(tmp_path, monkeypatch):
    deck = make_deck(tmp_path)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    ids = iter(["abc", "def"])
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: next(ids))
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [
        ("Title-Slide", build_title_slide_source(r"\titleframe{Financial Markets}{Stefan Palan\\Summer term 2026}")),
        ("Course-Sessions", build_sessions_slide_source(r"\begin{tabular}{ll}Datum & Zeit \\ \end{tabular}")),
    ]

    slide_paths = insert_admin_slides(deck, position, specs)

    assert [path.name for path in slide_paths] == [
        "abc-DE-Title-Slide-current.tex", "def-DE-Course-Sessions-current.tex",
    ]
    deck_text = deck.path.read_text(encoding="utf-8")
    assert deck_text.index(r"\slide{abc-DE-Title-Slide}") < deck_text.index(r"\slide{def-DE-Course-Sessions}")
    assert '"abc"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")
    assert '"def"' in (tmp_path / "slide_ids.csv").read_text(encoding="utf-8")


def test_failure_on_a_later_slide_leaves_deck_untouched(tmp_path, monkeypatch):
    deck = make_deck(tmp_path)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    # Same ID twice: the second slide file already exists, so its open("x") fails.
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    specs = [("Title-Slide", build_title_slide_source("A")), ("Title-Slide", build_title_slide_source("B"))]

    with pytest.raises(FileExistsError):
        insert_admin_slides(deck, position, specs)

    assert deck.path.read_text(encoding="utf-8") == deck.text
    assert not list((tmp_path / "slides").glob("*.tex"))


def test_insert_slide_calls_at_end_of_file_without_newline(tmp_path):
    path = tmp_path / "deck.tex"
    text = "\\begin{document}\n\\slide{aaa-EN-First}"
    path.write_text(text, encoding="utf-8", newline="")

    deck_editor.insert_slide_calls(path, text, len(text), "", ["bbb-DE-A", "ccc-DE-B"])

    assert path.read_text(encoding="utf-8") == (
        "\\begin{document}\n\\slide{aaa-EN-First}\n\\slide{bbb-DE-A}\n\\slide{ccc-DE-B}\n"
    )


def test_stale_deck_keeps_external_change_and_removes_new_slide(tmp_path, monkeypatch):
    deck = make_deck(tmp_path)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: "abc")
    position = deck_editor.slide_insert_positions(deck)[0]
    deck.path.write_text(deck.text + "% external edit\n", encoding="utf-8", newline="")

    with pytest.raises(deck_editor.StaleFileError):
        insert_admin_slides(deck, position, [("Course-Sessions", build_sessions_slide_source("Table"))])

    assert "% external edit" in deck.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "slides").glob("*.tex"))


def test_english_deck_gets_a_translated_sessions_table(tmp_path, monkeypatch, qapp):
    group = CourseGroup("Standardgruppe", (
        CourseSession("05.10.2026", "09:00", "10:00", "SR 15.25", "Abhaltung", "Vorbesprechung"),
        CourseSession("12.10.2026", "09:00", "10:00", "HS 01", "Prüfung", "Bitte Ausweis mitbringen"),
    ))
    dialog = make_dialog(tmp_path, monkeypatch, language="en")
    assert dialog.language == "en"
    dialog._on_loaded(CourseSchedule((group,)), "not needed")
    source = dialog.slide_specs[0][1]

    assert r"\begin{standardframe}{Course sessions}" in source
    assert r"\textbf{Date} & \textbf{Time} & \textbf{Location} & \textbf{Session}" in source
    assert r"\textbf{Standard group}" in source
    assert "SR 15.25 & Class — Preliminary meeting" in source
    # A remark with unknown words stays German rather than half-translated.
    assert "HS 01 & Exam — Bitte Ausweis mitbringen" in source
    assert "Zeit" not in source and "Abhaltungstermine" not in source

    german = make_dialog(tmp_path, monkeypatch, language="de")
    german._on_loaded(CourseSchedule((group,)), "not needed")
    assert r"\textbf{Datum} & \textbf{Zeit}" in german.slide_specs[0][1]
    assert "Abhaltung — Vorbesprechung" in german.slide_specs[0][1]


def test_english_deck_slides_are_named_en(tmp_path, monkeypatch):
    deck = make_deck(tmp_path, language="en")
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", tmp_path / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
    ids = iter(["abc", "def"])
    monkeypatch.setattr(slide_ids, "mint_slide_id", lambda: next(ids))
    position = deck_editor.slide_insert_positions(deck)[0]
    slide_paths = insert_admin_slides(deck, position, [
        ("Title-Slide", build_title_slide_source("A")),
        ("Course-Sessions", build_sessions_slide_source("Table", "en")),
    ], "en")
    assert [path.name for path in slide_paths] == [
        "abc-EN-Title-Slide-current.tex", "def-EN-Course-Sessions-current.tex",
    ]
    assert r"\slide{def-EN-Course-Sessions}" in deck.path.read_text(encoding="utf-8")
