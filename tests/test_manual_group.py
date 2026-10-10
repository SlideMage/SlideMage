"""The SlideMage manual's own deck group: tag `manual`, its own section in
the deck switcher, above the test decks, never offered as a choice, and the manual's Tags
entry is disabled -- so the manual always stays in its section."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QRadioButton

from slidemage import qt_deck_group_dialog
from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_scan import GROUP_ORDER, SELECTABLE_GROUP_TAGS, TAG_MANUAL, Deck
from conftest import command_context
from slidemage.ui.workspace.menus import GROUP_HEADINGS, build_deck_menu, build_more_menu

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
    assert list(GROUP_HEADINGS)[-2:] == [TAG_MANUAL, "test"]
    assert GROUP_HEADINGS[TAG_MANUAL] == "SlideMage manual"


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


def menu_rows(menu):
    menu._build()
    return {row.key: row for row in menu._rows}


def test_manual_has_a_disabled_tags_entry_and_its_own_switcher_section(qapp):
    course, manual = make_deck("course-deck", ["course"]), make_deck("slidemage-manual", ["manual"])
    tags = {deck.name: menu_rows(build_more_menu(None, command_context(deck)))["deck_tags"].isEnabled()
            for deck in (course, manual)}
    assert tags == {"course-deck": True, "slidemage-manual": False}
    menu = build_deck_menu(None, [course, manual], course)
    menu._build()
    headings = [entry[1] for entry in menu._entries if entry[0] == "header"]
    assert headings == ["Course decks", "SlideMage manual"]
