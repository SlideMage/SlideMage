# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The SlideMage manual's own deck group: tag `manual`, its own section in
the deck switcher, above the test decks, never offered as a choice, and the manual's Tags
entry is disabled -- so the manual always stays in its section."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton, QRadioButton

from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_scan import SELECTABLE_GROUP_TAGS, TAG_MANUAL, Deck
from conftest import command_context, filled_menu, menu_actions
from slidemage.ui.dialogs.deck_group import GROUP_LABELS, DeckGroupSheet
from slidemage.ui.workspace.menus import build_deck_menu

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


def make_deck(name, tags):
    return Deck(
        name=name, path=Path(f"{name}.tex"), archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0, chapters=[], output_folders={}, tags=tags)


def test_manual_tag_wins_and_is_its_own_group():
    assert make_deck("m", ["manual"]).group == TAG_MANUAL
    assert make_deck("m", ["test", "manual"]).group == TAG_MANUAL
    assert make_deck("m", ["manual"]).is_test_deck is False   # clickable, has a slide list
    assert TAG_MANUAL not in SELECTABLE_GROUP_TAGS


def test_shipped_manual_carries_the_tag():
    text = (EXAMPLE / "decks" / "slidemage-manual.tex").read_text(encoding="utf-8")
    assert "\\decktags{manual}" in text


def test_manual_compiles_before_the_test_decks():
    manual, course, test = (make_deck("manual", ["manual"]), make_deck("course", ["course"]),
                            make_deck("test", ["test"]))
    jobs = [CompileJob(d, "instructor", None) for d in (manual, test, course)]
    assert [j.deck.name for j in order_jobs(jobs)] == ["course", "manual", "test"]


def test_sheet_never_offers_the_manual_group(qapp):
    sheet = DeckGroupSheet(None, "Duplicate deck", TAG_MANUAL)
    radios = sheet.findChildren(QRadioButton)
    assert len(radios) == len(SELECTABLE_GROUP_TAGS)
    assert not any("manual" in radio.text().lower() for radio in radios)
    # a copy of the manual starts out as a course deck
    assert [r.text() for r in radios if r.isChecked()] == [GROUP_LABELS["course"]]


def test_manual_has_a_disabled_deck_settings_entry_and_its_own_switcher_section(qapp):
    course, manual = make_deck("course-deck", ["course"]), make_deck("slidemage-manual", ["manual"])
    settings = {deck.name: menu_actions(filled_menu(command_context(deck), "Deck"))["deck_settings"].isEnabled()
                for deck in (course, manual)}
    assert settings == {"course-deck": True, "slidemage-manual": False}
    menu = build_deck_menu(None, [course, manual], course)
    menu._build()
    headings = [entry[1] for entry in menu._entries if entry[0] == "header"]
    assert headings == ["Course decks", "SlideMage manual"]


def test_sheet_asks_for_a_group_and_a_valid_name(qapp):
    sheet = DeckGroupSheet(None, "Duplicate deck", "research", ok_text="Duplicate", name_prompt="Name",
                           default_name="talk-copy",
                           validate_name=lambda name: None if name == "talk-2" else f"{name} is taken")
    ok = next(b for b in sheet.findChildren(QPushButton) if b.text() == "Duplicate")
    ok.click()
    assert sheet.result() == 0 and not sheet.problem.isHidden() and "talk-copy is taken" in sheet.problem.text()
    sheet.name_edit.setText("talk-2")
    assert sheet.problem.isHidden()                       # the reason goes away when the name changes
    next(r for r in sheet.findChildren(QRadioButton) if r.text() == GROUP_LABELS["test"]).setChecked(True)
    ok.click()
    assert sheet.result() == 1 and (sheet.name, sheet.group) == ("talk-2", "test")


def test_tags_sheet_has_no_name_field_and_keeps_the_current_group(qapp):
    sheet = DeckGroupSheet(None, "Tags — course", "research")
    assert sheet.name_edit is None
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Save").click()
    assert (sheet.name, sheet.group) == ("", "research")


def test_the_sheet_asks_for_a_template_when_given_some(qapp):
    sheet = DeckGroupSheet(None, "New deck", "course", ok_text="Create", name_prompt="Name", default_name="x",
                           templates=[("uni-graz", "University of Graz"), ("mci", "MCI")], current_template="mci")
    assert sheet.template_box.currentData() == "mci"
    sheet.template_box.setCurrentIndex(0)
    sheet._on_ok()
    assert sheet.template == "uni-graz" and sheet.name == "x"
