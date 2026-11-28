# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deck groups in switchers, compile selection and editing dialogs."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QPushButton

from conftest import EXAMPLE, build_window, command_context, filled_menu, qapp as qapp  # noqa: F401 -- a fixture
from slidemage import deck_editor, deck_scan
from slidemage.deck_groups import DEFAULT_GROUPS, ROLE_PINNED, ROLE_TEST, DeckGroup, groups_of, roles_of
from slidemage.fileio import read_text_exact
from slidemage.project import ProjectContext
from slidemage.ui.dialogs.deck_group import DeckGroupSheet
from slidemage.ui.workspace import deck_actions, menus
from slidemage.ui.workspace.multi_compile import MultiCompileSheet

# A list without a fallback group: a deck naming none of these is in no group.
OWN_GROUPS = (
    DeckGroup("workshops", "Workshop", "Workshops", frozenset({ROLE_PINNED})),
    DeckGroup("lectures", "Lecture", "Lectures"),
    DeckGroup("lab", "Lab deck", "Lab decks", frozenset({ROLE_TEST})),
)


def make_deck(name, tags, groups=DEFAULT_GROUPS):
    group_tags = groups_of(tags, groups)
    return deck_scan.Deck(
        name=name, path=Path(f"{name}.tex"), archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0, chapters=[], output_folders={}, tags=list(tags),
        groups=group_tags, roles=roles_of(group_tags, groups))


def switcher(decks, current=None, groups=DEFAULT_GROUPS):
    menu = menus.build_deck_menu(None, decks, current, groups)
    names = {menus.deck_key(d): d.name for d in decks}
    sections, heading = [], None
    for entry in menu._entries:
        if entry[0] == "header":
            heading = entry[1]
            sections.append((heading, []))
        elif entry[0] == "item":
            if not sections or sections[-1][0] != heading:
                sections.append((heading, []))
            sections[-1][1].append(names[entry[1]])
    return sections


def test_the_current_deck_is_ticked_under_each_group_and_the_keys_step_through_both(qapp):
    both, other = make_deck("both", ["work", "course"]), make_deck("lecture", ["course"])
    menu = menus.build_deck_menu(None, [both, other], both)
    ticked = [e[1] for e in menu._entries if e[0] == "item" and e[4] == "check"]
    assert ticked == [menus.deck_key(both)] * 2
    assert [e[1] for e in menu._entries if e[0] == "header"] == ["Pinned", "Course decks"]
    menu._prepare()
    keys = [row.key for row in menu._rows]
    assert keys == [menus.deck_key(d) for d in (both, both, other)]
    for index in (0, 1, 2, 0):
        assert menu._current == index
        menu._step(1)
    menu.deleteLater()


def test_a_deck_in_two_groups_is_in_both_sections_of_switch_deck(qapp):
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    menu = filled_menu(command_context(course, decks=[both, course]), "Deck")
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None and a.menu().objectName() == "submenu:switch deck")
    shown = [a for a in sub.actions() if a.objectName()]
    assert [a.objectName() for a in shown] == [menus.deck_key(d) for d in (both, course, both)]
    assert [a.isChecked() for a in shown] == [False, True, False]


def test_several_decks_includes_ungrouped_decks_and_ticks_each_deck_once(qapp):
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    sheet = MultiCompileSheet(None, [both, course])
    boxes = sheet._twins[(both.name, "instructor")]
    assert len(boxes) == 2 and len(sheet._twins[(course.name, "instructor")]) == 1
    boxes[1].setChecked(True)
    assert boxes[0].isChecked()                                   # its other row follows
    assert [(d.name, kind) for d, kind in sheet.chosen()] == [("both", "instructor")]
    boxes[0].setChecked(False)
    assert not boxes[1].isChecked() and sheet.chosen() == []
    sheet._set_all(True)
    chosen = [(d.name, kind) for d, kind in sheet.chosen()]
    assert len(chosen) == len(set(chosen)) and ("both", "instructor") in chosen
    sheet.deleteLater()

    loose = make_deck("loose", [], OWN_GROUPS)
    sheet = MultiCompileSheet(None, [loose], OWN_GROUPS)
    assert len(sheet._twins[(loose.name, "instructor")]) == 1
    sheet.deleteLater()


def test_other_decks_is_a_section_only_when_a_deck_has_no_group(qapp):
    grouped, manual = make_deck("talk", ["lectures"], OWN_GROUPS), make_deck("manual", ["manual"], OWN_GROUPS)
    lab = make_deck("lab", ["lab"], OWN_GROUPS)
    assert "Other decks" not in [h for h, _ in menus.deck_sections([grouped, manual, lab], OWN_GROUPS)]
    loose = make_deck("loose", ["intro"], OWN_GROUPS)
    assert switcher([grouped, manual, lab, loose], groups=OWN_GROUPS) == [
        ("Lectures", ["talk"]), ("Other decks", ["loose"]), ("SlideMage manual", ["manual"]), ("Lab decks", ["lab"])]


def checks(sheet):
    return {c.text(): c for c in sheet.findChildren(QCheckBox)}


def test_the_sheet_has_a_checkbox_per_group_and_starts_with_the_decks_groups(qapp):
    sheet = DeckGroupSheet(None, "Tags", ["course", "research"])
    boxes = checks(sheet)
    assert [label for label, c in boxes.items() if c.isChecked()] == ["Course deck", "Research presentation"]
    boxes["Course deck"].setChecked(False)
    boxes["Test deck"].setChecked(True)
    sheet._on_ok()
    assert sheet.chosen_groups == ("research", "test")
    sheet.deleteLater()


class _Sheet:
    def __init__(self, chosen, name="", template=""):
        self.chosen_groups, self.name, self.template = tuple(chosen), name, template

    def exec(self):
        return True


@pytest.fixture
def group_window(monkeypatch, tmp_path, qapp):
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    window = build_window(monkeypatch, ProjectContext.at(root))
    deck = next(d for d in window.decks if d.name == "slidemage-manual-copy")
    deck_editor.set_deck_tags(deck.path, deck.text, ["course", "intro"])    # a tag that is no group's
    window.reload_decks()
    return window, next(d for d in window.decks if d.name == "slidemage-manual-copy")


def _tags(path):
    return deck_scan.find_decktags(read_text_exact(path)).group(1)


def test_tags_writes_the_checked_groups_and_keeps_other_tags(group_window, monkeypatch):
    window, deck = group_window
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet(["research", "work"]))
    deck_actions.on_edit_deck_tags(window, deck)
    assert _tags(deck.path) == "work,research,intro"
    window.reload_decks()
    deck = next(d for d in window.decks if d.path == deck.path)
    assert deck.groups == ("work", "research") and ROLE_PINNED in deck.roles
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet([]))
    deck_actions.on_edit_deck_tags(window, deck)
    assert _tags(deck.path) == "intro"


def test_edit_groups_closes_the_tags_sheet_with_the_request(qapp):
    plain = DeckGroupSheet(None, "Duplicate", ["course"], groups=OWN_GROUPS)
    assert "Edit groups…" not in [b.text() for b in plain.findChildren(QPushButton)]
    plain.deleteLater()
    sheet = DeckGroupSheet(None, "Tags", ["course"], groups=OWN_GROUPS, edit_groups=True)
    next(b for b in sheet.findChildren(QPushButton) if b.text() == "Edit groups…").click()
    assert sheet.edit_groups_requested and sheet.result() == 0
    sheet.deleteLater()


def test_tags_opens_the_deck_groups_and_then_asks_again(group_window, monkeypatch):
    window, deck = group_window
    opened = []
    monkeypatch.setattr(window, "open_deck_groups", lambda: opened.append(True))

    class _EditFirst(_Sheet):
        def exec(self):
            return False

    sheets = iter([_EditFirst([]), _Sheet(["research"])])

    def make(*_a, **kw):
        assert kw.get("edit_groups") is True
        sheet = next(sheets)
        sheet.edit_groups_requested = isinstance(sheet, _EditFirst)
        return sheet

    monkeypatch.setattr(deck_actions, "DeckGroupSheet", make)
    deck_actions.on_edit_deck_tags(window, deck)
    assert opened == [True]
    assert _tags(deck.path) == "research,intro"


def test_new_deck_with_two_groups_and_with_none(group_window, monkeypatch):
    window, _ = group_window
    decks = window.project.decks_dir
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet(["research", "work"], "two"))
    deck_actions.on_new_deck(window)
    assert _tags(decks / "two.tex") == "work,research"
    assert next(d for d in window.decks if d.name == "two").groups == ("work", "research")
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet([], "none"))
    deck_actions.on_new_deck(window)
    assert deck_scan.find_decktags(read_text_exact(decks / "none.tex")) is None
    assert next(d for d in window.decks if d.name == "none").groups == ("course",)    # the fallback group
