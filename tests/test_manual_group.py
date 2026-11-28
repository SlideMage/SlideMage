# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shipped manual's group, ordering and protected settings."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QPushButton

from slidemage.compiler import CompileJob, order_jobs
from slidemage import deck_scan
from conftest import EXAMPLE_PROJECT, command_context, filled_menu, menu_actions
from slidemage.ui.dialogs.deck_group import GROUP_LABELS, DeckGroupSheet
from slidemage.ui.workspace.menus import build_deck_menu

def make_deck(name, tags):
    return deck_scan.deck_from_text(Path(f"{name}.tex"), f"\\decktags{{{tags}}}\n")


def test_manual_compiles_before_the_test_decks():
    manual, course, test = (make_deck("manual", "test,manual"), make_deck("course", "course"), make_deck("test", "test"))
    assert manual.group == "manual" and not manual.is_test_deck
    jobs = [CompileJob(d, "instructor", None) for d in (manual, test, course)]
    assert [j.deck.name for j in order_jobs(jobs)] == ["course", "manual", "test"]


def test_manual_has_a_disabled_deck_settings_entry_and_its_own_switcher_section(qapp):
    course = make_deck("course-deck", "course")
    manual = deck_scan.read_deck(EXAMPLE_PROJECT.decks_dir / "slidemage-manual.tex")
    assert manual.group == "manual"
    settings = {deck.name: menu_actions(filled_menu(command_context(deck), "Deck"))["deck_settings"].isEnabled()
                for deck in (course, manual)}
    assert settings == {"course-deck": True, "slidemage-manual": False}
    menu = build_deck_menu(None, [course, manual], course)
    menu._build()
    headings = [entry[1] for entry in menu._entries if entry[0] == "header"]
    assert headings == ["Course decks", "SlideMage manual"]


def test_sheet_asks_for_a_group_and_a_valid_name(qapp):
    sheet = DeckGroupSheet(None, "Duplicate deck", ["manual"], ok_text="Duplicate", name_prompt="Name",
                           default_name="talk-copy",
                           validate_name=lambda name: None if name == "talk-2" else f"{name} is taken")
    ok = next(b for b in sheet.findChildren(QPushButton) if b.text() == "Duplicate")
    ok.click()
    assert sheet.result() == 0 and not sheet.problem.isHidden() and "talk-copy is taken" in sheet.problem.text()
    sheet.name_edit.setText("talk-2")
    assert sheet.problem.isHidden()                       # the reason goes away when the name changes
    checks = {c.text(): c for c in sheet.findChildren(QCheckBox)}
    assert not any("manual" in label.lower() for label in checks)
    assert [label for label, box in checks.items() if box.isChecked()] == [GROUP_LABELS["course"]]
    checks[GROUP_LABELS["course"]].setChecked(False)
    checks[GROUP_LABELS["test"]].setChecked(True)
    ok.click()
    assert sheet.result() == 1 and (sheet.name, sheet.chosen_groups) == ("talk-2", ("test",))


def test_tags_sheet_has_no_name_field_and_keeps_the_current_group(qapp):
    sheet = DeckGroupSheet(None, "Tags — course", ["research"])
    assert sheet.name_edit is None
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Save").click()
    assert (sheet.name, sheet.chosen_groups) == ("", ("research",))


def test_the_sheet_asks_for_a_template_when_given_some(qapp):
    sheet = DeckGroupSheet(None, "New deck", ["course"], ok_text="Create", name_prompt="Name", default_name="x",
                           templates=[("acme", "Acme University"), ("other", "Other")], current_template="other")
    assert sheet.template_box.currentData() == "other"
    sheet.template_box.setCurrentIndex(0)
    sheet._on_ok()
    assert sheet.template == "acme" and sheet.name == "x"
