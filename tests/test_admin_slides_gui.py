"""The Admin slides tab of the Deck settings sheet: fetch results, which slides are planned, and
where they go. (The slides themselves are tested in test_admin_slides.py.)"""
from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from slidemage import admin_slides
from slidemage.course_schedule import CourseGroup, CourseSchedule, CourseSession
from slidemage.ui.dialogs.admin_slides import AdminSlidesTab
from test_admin_slides import DETAIL, GROUP, make_deck


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_tab(tmp_path, monkeypatch, language="de", **deck_fields):
    started = []
    monkeypatch.setattr(admin_slides, "fetch", lambda url, lang: started.append((url, lang)) or ("", ""))
    deck = replace(make_deck(tmp_path, language=language), **deck_fields)
    tab = AdminSlidesTab(deck)
    tab.started = started
    return tab


def two_groups():
    return CourseSchedule((
        CourseGroup("Standardgruppe", (CourseSession("05.10.2026", "09:00", "10:00", "SR 1", "Abhaltung", ""),)),
        CourseGroup("Gruppe Wirtschaftsinformatik", (CourseSession("06.10.2026", "08:30", "10:00", "HS 1", "Abhaltung", ""),)),
    ))


def test_a_deck_without_a_course_page_says_so_and_fetches_nothing(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch, course_url="")
    tab.start()
    assert "links no course page" in tab.status.text()
    assert tab.title_section.isHidden() and tab.preview.isHidden()          # only the hint
    assert not tab._started and tab.slide_specs == []


def test_the_course_is_fetched_once_on_a_thread_and_shown(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    assert tab.status.text() == "Loading the linked course…"
    tab.start()
    tab.start()
    from slidemage.ui import background
    for thread in tuple(background._running):
        thread.wait()
    qapp.processEvents()
    assert tab.started == [("https://example.invalid/course", "de")]       # once, with the deck's language


def test_multiple_groups_and_lecturers_build_combined_preview(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    changes = []
    tab.changed.connect(lambda: changes.append(1))
    groups = two_groups()
    tab._on_loaded(groups, DETAIL)

    assert not tab.group_combo.isHidden()
    assert [tab.group_combo.itemText(i) for i in range(tab.group_combo.count())] == [g.name for g in groups.groups]
    assert "05.10.2026" in tab.preview.toPlainText()
    assert "Bachelorkurs (Management Science)" in tab.preview.toPlainText()
    assert "Andreas Darmann, Jürgen Fleiß" in tab.preview.toPlainText()
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide", "Course-Sessions"]
    assert changes

    tab.group_combo.setCurrentIndex(1)
    assert "06.10.2026" in tab.preview.toPlainText()
    assert "05.10.2026" not in tab.preview.toPlainText()

    checkbox, _ = tab._lecturer_checks[0]
    checkbox.setChecked(False)
    assert "Andreas Darmann" not in tab.preview.toPlainText()
    assert "Jürgen Fleiß" in tab.preview.toPlainText()


def test_empty_groups_are_labelled_in_the_picker_only(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    groups = (CourseGroup("Standardgruppe", GROUP.sessions[:1]), CourseGroup("Gruppe Operations Management", ()))
    tab._on_loaded(CourseSchedule(groups), DETAIL)
    assert [tab.group_combo.itemText(i) for i in range(tab.group_combo.count())] == [
        "Standardgruppe", "Gruppe Operations Management (empty)"]
    tab.group_combo.setCurrentIndex(1)
    assert r"\textbf{Gruppe Operations Management}\par Keine Termine" in tab.preview.toPlainText()


def test_unchecking_a_section_drops_it_from_the_plan(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    tab._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    tab.sessions_check.setChecked(False)
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide"]
    tab.title_check.setChecked(False)
    assert tab.slide_specs == []


def test_failed_fetch_disables_its_own_section_only(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    tab._on_loaded("network unreachable", DETAIL)
    assert not tab.sessions_check.isChecked() and not tab.sessions_section.isEnabled()
    assert "network unreachable" in tab.sessions_status.text()
    assert tab.title_section.isEnabled()
    assert [suffix for suffix, _ in tab.slide_specs] == ["Title-Slide"]


def test_a_closed_tab_ignores_a_late_fetch_result(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    tab.cancel()
    tab._on_loaded(CourseSchedule((CourseGroup("First", ()),)), DETAIL)
    assert tab.slide_specs == []


def test_the_english_deck_gets_its_own_language_and_slides(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch, language="en")
    assert tab.language == "en"
    tab._on_loaded(CourseSchedule((GROUP,)), "not needed")
    assert r"\textbf{Date} & \textbf{Time}" in tab.slide_specs[0][1]


@pytest.mark.parametrize(("deck_language", "taught", "warned"), [("en", ("de",), True), ("de", ("de",), False)])
def test_language_mismatch_warns_without_blocking(tmp_path, monkeypatch, qapp, deck_language, taught, warned):
    tab = make_tab(tmp_path, monkeypatch, language=deck_language)
    tab._on_loaded("no sessions", replace(DETAIL, languages=taught))
    assert tab.language_warning.isHidden() is not warned
    assert tab.slide_specs


def test_the_position_defaults_to_the_end_of_the_deck(tmp_path, monkeypatch, qapp):
    tab = make_tab(tmp_path, monkeypatch)
    assert tab.position is tab._positions[-1]
