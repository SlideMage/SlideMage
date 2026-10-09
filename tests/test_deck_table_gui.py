"""The deck table keeps everything left-aligned in a wide window."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage.deck_scan import Deck
from slidemage.qt_deck_table import DeckTable
from slidemage.ui.kit.theme import ThemeManager


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(name="demo", supports_version=True, chapters=()):
    return Deck(
        name=name, path=Path(f"{name}.tex"), archived=False, text="",
        supports_version=supports_version, uses_biblatex=False, preamble_end=0,
        chapters=list(chapters), output_folders={}, tags=[])


def make_table(decks):
    nothing = lambda *a, **k: None  # noqa: E731
    table = DeckTable(
        ThemeManager(), archivable=True, on_open=nothing, on_archive=nothing, on_edit=nothing,
        on_duplicate=nothing, on_export_pptx=nothing, on_compile_selected=nothing,
        on_stop_compilation=nothing, on_create_transcript=nothing, on_refresh=nothing)
    table.rebuild(decks)
    return table


def left_edges(table, width):
    table.resize(width, 400)
    table.show()
    QApplication.processEvents()
    row = table.rows[0]
    edges = [row.vars[v].mapTo(table, row.vars[v].rect().topLeft()).x()
             for v in ("instructor", "during-course", "after-course")]
    edges.append(row.presenter_var.mapTo(table, row.presenter_var.rect().topLeft()).x())
    buttons = {b.text(): b.mapTo(table, b.rect().topLeft()).x()
               for b in table.findChildren(QPushButton) if b.text() in ("Clear selection", "Refresh decks")}
    return edges, buttons


def test_wide_window_does_not_spread_columns_or_buttons(qapp):
    table = make_table([make_deck()])
    narrow = left_edges(table, 1100)
    wide = left_edges(table, 2400)
    assert wide == narrow           # the extra width goes to the right
    # and the buttons sit at the left, not at the far right edge
    assert max(wide[1].values()) < 900


def test_clear_selection_after_a_run_clears_checkboxes_and_pass_fail_marks(qapp):
    table = make_table([make_deck()])
    row = table.rows[0]
    row.vars["instructor"].setChecked(True)
    row.presenter_var.setChecked(True)
    row.set_status("instructor", "pass")
    row.set_status("during-course", "fail")
    row.set_status("presenter", "moving")
    assert row.status_labels["instructor"].text() == "✓"
    table._on_clear_selection()
    assert not row.vars["instructor"].isChecked() and not row.presenter_var.isChecked()
    assert all(label.text() == "" for label in row.status_labels.values())
    # a sticky fail is gone too, so the next compile starts clean
    row.set_status("during-course", "pass")
    assert row.status_labels["during-course"].text() == "✓"


def test_clear_selection_during_a_run_keeps_dots_and_results_until_clicked_again(qapp):
    table = make_table([make_deck()])
    row = table.rows[0]
    row.vars["instructor"].setChecked(True)
    row.vars["after-course"].setChecked(True)
    table.set_compiling(True)
    row.set_status("instructor", "running")
    row.set_status("after-course", "pass")
    row.set_status("during-course", "fail")
    table._on_clear_selection()
    # checkboxes are cleared, the indicators stay
    assert not row.vars["instructor"].isChecked() and not row.vars["after-course"].isChecked()
    assert row.status_labels["instructor"].text() == "."
    assert row.status_labels["after-course"].text() == "✓"
    assert row.status_labels["during-course"].text() == "✗"
    row.tick_spinner(1)
    assert row.status_labels["instructor"].text() == ".."      # still animated
    # the run ends; another click clears the indicators
    row.set_status("instructor", "pass")
    table.set_compiling(False)
    assert row.status_labels["instructor"].text() == "✓"
    table._on_clear_selection()
    assert all(label.text() == "" for label in row.status_labels.values())


def test_pages_field_makes_page_jobs_for_versions_and_presenter_only(qapp):
    from slidemage.deck_scan import Chapter
    from slidemage.partial_compile import PartialError

    chapter = Chapter(order=1, title="One", slug="One", start=0, end=0)
    table = make_table([make_deck(chapters=[chapter])])
    row = table.rows[0]
    row.vars["instructor"].setChecked(True)
    row.chapter_var.setChecked(True)
    row.presenter_var.setChecked(True)
    assert [job.pages for job in row.build_jobs()] == [None, None, None]
    row.pages_edit.setText("4, 7-9")
    jobs = row.build_jobs()
    assert [(job.chapter is not None, job.presenter, job.pages) for job in jobs] == [
        (False, False, [4, 7, 8, 9]), (True, False, None), (False, True, [4, 7, 8, 9])]
    row.pages_edit.setText("4, x")
    with pytest.raises(PartialError):
        row.build_jobs()
    table._on_clear_selection()
    assert row.pages_edit.text() == ""
