"""The deck table keeps everything left-aligned in a wide window."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from slidemage.deck_scan import Deck
from slidemage.qt_deck_table import DeckTable
from slidemage.qt_theme import ThemeManager


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
