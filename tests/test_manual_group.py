"""The SlideMage manual's own deck group: tag `manual`, its own section in
the deck table, above the test decks, never offered as a choice, and the manual's Tags
button is disabled -- so the manual always stays in its section."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QRadioButton

from slidemage import qt_deck_group_dialog
from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_scan import GROUP_ORDER, SELECTABLE_GROUP_TAGS, TAG_MANUAL, Deck
from slidemage.qt_deck_table import GROUPS, DeckTable
from slidemage.ui.kit.theme import ThemeManager

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(name, tags):
    return Deck(
        name=name, path=Path(f"{name}.tex"), archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0, chapters=[], output_folders={}, tags=tags)


def test_manual_tag_wins_and_is_its_own_group():
    assert make_deck("m", ["manual"]).group == TAG_MANUAL
    assert make_deck("m", ["test", "manual"]).group == TAG_MANUAL
    assert make_deck("m", ["manual"]).is_test_deck is False   # clickable, has a slide list
    assert TAG_MANUAL not in SELECTABLE_GROUP_TAGS
    assert GROUP_ORDER[-2:] == (TAG_MANUAL, "test")      # test decks sort below the manual
    assert [g[0] for g in GROUPS][-2:] == [TAG_MANUAL, "test"]
    assert GROUPS[-2][1] == "SlideMage manual"


def test_shipped_manual_carries_the_tag():
    text = (EXAMPLE / "decks" / "slidemage-manual.tex").read_text(encoding="utf-8")
    assert "\\decktags{manual}" in text


def test_manual_compiles_before_the_test_decks():
    manual, course, test = (make_deck("manual", ["manual"]), make_deck("course", ["course"]),
                            make_deck("test", ["test"]))
    jobs = [CompileJob(d, "instructor", None) for d in (manual, test, course)]
    assert [j.deck.name for j in order_jobs(jobs)] == ["course", "manual", "test"]


def test_dialog_never_offers_the_manual_group(qapp, monkeypatch):
    seen = {}

    def grab(dialog):
        radios = dialog.findChildren(QRadioButton)
        seen["labels"] = [r.text() for r in radios]
        seen["checked"] = [r.text() for r in radios if r.isChecked()]
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(qt_deck_group_dialog.QDialog, "exec", grab)
    assert qt_deck_group_dialog.ask_deck_details(None, "Duplicate deck", TAG_MANUAL) is None
    assert len(seen["labels"]) == len(SELECTABLE_GROUP_TAGS)
    assert not any("manual" in label.lower() for label in seen["labels"])
    # a copy of the manual starts out as a course deck
    assert seen["checked"] == [qt_deck_group_dialog.GROUP_LABELS["course"]]


def test_manual_row_has_a_disabled_tags_button(qapp):
    nothing = lambda *a, **k: None  # noqa: E731
    table = DeckTable(
        ThemeManager(), archivable=True, on_open=nothing, on_archive=nothing, on_edit=nothing,
        on_duplicate=nothing, on_tags=nothing, on_export_pptx=nothing,
        on_compile_selected=nothing, on_stop_compilation=nothing,
        on_create_transcript=nothing, on_refresh=nothing)
    table.rebuild([make_deck("course-deck", ["course"]), make_deck("slidemage-manual", ["manual"])])
    tags_buttons = [b for b in table.findChildren(QPushButton) if b.text() == "Tags"]
    assert [b.isEnabled() for b in tags_buttons] == [True, False]
    headings = [b.text() for b in table.findChildren(QPushButton) if "(" in b.text()]
    assert any("SlideMage manual" in h for h in headings)
