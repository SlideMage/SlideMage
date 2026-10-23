# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A deck in several groups (docs/plans/editable-deck-tags.md, step 3): listed the same way under each of its
groups in the deck switcher, Deck → Switch deck and Several decks…, compiled once, with the roles of all its
groups; "Other decks" for decks in no group; the Tags…, Duplicate deck… and New deck… sheets as checkboxes."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QPushButton

from conftest import EXAMPLE, build_window, command_context, filled_menu, qapp as qapp  # noqa: F401 -- a fixture
from slidemage import deck_editor, deck_scan
from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_groups import DEFAULT_GROUPS, ROLE_PINNED, ROLE_TEST, DeckGroup, groups_of, roles_of
from slidemage.fileio import read_text_exact
from slidemage.project import ProjectContext
from slidemage.ui.dialogs.deck_group import DeckGroupSheet
from slidemage.ui.workspace import deck_actions, menus
from slidemage.ui.workspace.deck_actions import tags_with_groups
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
    """The deck switcher's (heading, [deck names]) sections, as shown."""
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


def test_a_deck_in_two_groups_is_in_both_sections_of_the_switcher(qapp):
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    assert both.groups == ("course", "research")
    assert switcher([both, course]) == [("Course decks", ["both", "lecture"]), ("Research presentations", ["both"])]


def test_the_current_deck_is_ticked_under_each_group_and_the_keys_step_through_both(qapp):
    both, other = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    menu = menus.build_deck_menu(None, [both, other], both)
    ticked = [e[1] for e in menu._entries if e[0] == "item" and e[4] == "check"]
    assert ticked == [menus.deck_key(both)] * 2                 # the same way under each group
    menu._prepare()
    keys = [row.key for row in menu._rows]
    assert keys == [menus.deck_key(d) for d in (both, other, both)]
    assert menu._current == 0                                     # the menu opens on its first entry
    menu._step(1)
    menu._step(1)
    assert menu._current == 2                                     # Down reaches the second entry too
    menu._step(1)
    assert menu._current == 0                                     # and wraps round
    menu.deleteLater()


def test_a_deck_in_two_groups_is_in_both_sections_of_switch_deck(qapp):
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    menu = filled_menu(command_context(course, decks=[both, course]), "Deck")
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None and a.menu().objectName() == "submenu:switch deck")
    shown = [a for a in sub.actions() if a.objectName()]
    assert [a.objectName() for a in shown] == [menus.deck_key(d) for d in (both, course, both)]
    assert [a.isChecked() for a in shown] == [False, True, False]


def test_a_pinned_deck_is_also_listed_under_its_other_groups(qapp):
    deck = make_deck("both", ["course", "work"])
    assert deck.is_pinned and deck.groups == ("work", "course")
    assert switcher([deck]) == [(None, ["both"]), ("Course decks", ["both"])]


def test_a_deck_has_the_roles_of_all_its_groups():
    deck = make_deck("d", ["lab", "workshops"], OWN_GROUPS)
    assert deck.groups == ("workshops", "lab") and deck.is_pinned and deck.is_test_deck
    assert not make_deck("d", ["lectures"], OWN_GROUPS).is_pinned


def test_a_deck_in_two_groups_is_compiled_once():
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    jobs = order_jobs([CompileJob(d, "instructor", None) for d in (both, course)])
    assert [j.deck.name for j in jobs] == ["both", "lecture"]     # by its first group, once


def test_several_decks_ticks_a_deck_once_whichever_of_its_rows(qapp):
    both, course = make_deck("both", ["research", "course"]), make_deck("lecture", ["course"])
    sheet = MultiCompileSheet(None, [both, course])
    boxes = sheet.boxes_of(both, "instructor")
    assert len(boxes) == 2 and len(sheet.boxes_of(course, "instructor")) == 1
    boxes[1].setChecked(True)
    assert boxes[0].isChecked()                                   # its other row follows
    assert [(d.name, kind) for d, kind in sheet.chosen()] == [("both", "instructor")]
    boxes[0].setChecked(False)
    assert not boxes[1].isChecked() and sheet.chosen() == []
    sheet._set_all(True)
    chosen = [(d.name, kind) for d, kind in sheet.chosen()]
    assert len(chosen) == len(set(chosen)) and ("both", "instructor") in chosen
    sheet.deleteLater()


def test_other_decks_is_a_section_only_when_a_deck_has_no_group(qapp):
    grouped, manual = make_deck("talk", ["lectures"], OWN_GROUPS), make_deck("manual", ["manual"], OWN_GROUPS)
    lab = make_deck("lab", ["lab"], OWN_GROUPS)
    assert "Other decks" not in [h for h, _ in menus.deck_sections([grouped, manual, lab], OWN_GROUPS)]
    loose = make_deck("loose", ["intro"], OWN_GROUPS)
    assert loose.groups == ()
    assert switcher([grouped, manual, lab, loose], groups=OWN_GROUPS) == [
        ("Lectures", ["talk"]), ("Other decks", ["loose"]), ("SlideMage manual", ["manual"]), ("Lab decks", ["lab"])]
    # with the default list the fallback group takes such a deck
    assert "Other decks" not in [h for h, _ in menus.deck_sections([make_deck("loose", ["intro"])])]


def test_several_decks_lists_the_other_decks_too(qapp):
    loose = make_deck("loose", [], OWN_GROUPS)
    sheet = MultiCompileSheet(None, [loose], OWN_GROUPS)
    assert len(sheet.boxes_of(loose, "instructor")) == 1
    sheet.deleteLater()


def test_tags_with_groups_sets_exactly_the_chosen_groups_and_keeps_other_tags():
    assert tags_with_groups(["intro", "course", "x"], ["research", "work"]) == ["work", "research", "intro", "x"]
    assert tags_with_groups(["intro", "course"], []) == ["intro"]
    assert tags_with_groups(["manual", "intro"], ["course"]) == ["course", "intro"]
    assert tags_with_groups(["course", "lab"], ["lab", "workshops"], OWN_GROUPS) == ["workshops", "lab", "course"]


def checks(sheet):
    return {c.text(): c for c in sheet.findChildren(QCheckBox)}


def test_the_sheet_has_a_checkbox_per_group_and_starts_with_the_decks_groups(qapp):
    sheet = DeckGroupSheet(None, "Tags", ["course", "research"])
    assert [label for label, c in checks(sheet).items() if c.isChecked()] == ["Course deck", "Research presentation"]
    checks(sheet)["Course deck"].setChecked(False)
    checks(sheet)["Test deck"].setChecked(True)
    sheet._on_ok()
    assert sheet.chosen_groups == ("research", "test")
    sheet.deleteLater()


def test_the_sheet_allows_no_group(qapp):
    sheet = DeckGroupSheet(None, "Tags", [], groups=OWN_GROUPS)
    assert not any(c.isChecked() for c in checks(sheet).values())    # no fallback to start with
    assert "Other decks" in " ".join(lbl.text() for lbl in sheet.findChildren(type(sheet.problem)))
    sheet._on_ok()
    assert sheet.result() == 1 and sheet.chosen_groups == ()
    sheet.deleteLater()


# -- the sheets' callers, on a copy of the example project --------------------------------------------------------------

class _Sheet:
    def __init__(self, chosen, name="", template=""):
        self.chosen_groups, self.name, self.template = tuple(chosen), name, template

    def exec(self):
        return True


def _window(monkeypatch, tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(EXAMPLE, root)
    window = build_window(monkeypatch, ProjectContext.at(root))
    deck = next(d for d in window.decks if d.name == "slidemage-manual-copy")
    deck_editor.set_deck_tags(deck.path, deck.text, ["course", "intro"])    # a tag that is no group's
    window.reload_decks()
    return window, root, next(d for d in window.decks if d.name == "slidemage-manual-copy")


def _tags(path):
    return deck_scan.find_decktags(read_text_exact(path)).group(1)


def test_tags_writes_the_checked_groups_and_keeps_other_tags(qapp, monkeypatch, tmp_path):
    window, root, deck = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet(["research", "work"]))
    deck_actions.on_edit_deck_tags(window, deck)
    assert _tags(deck.path) == "work,research,intro"
    window.reload_decks()
    deck = next(d for d in window.decks if d.path == deck.path)
    assert deck.groups == ("work", "research") and deck.is_pinned
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


def test_tags_opens_the_deck_groups_and_then_asks_again(qapp, monkeypatch, tmp_path):
    window, root, deck = _window(monkeypatch, tmp_path)
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


def test_duplicate_deck_with_two_groups_and_with_none(qapp, monkeypatch, tmp_path):
    window, root, deck = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet(["test", "course"], "two"))
    deck_actions.on_duplicate_deck(window, deck)
    assert _tags(root / "decks" / "two.tex") == "course,test,intro"
    copy = next(d for d in window.decks if d.name == "two")
    assert copy.groups == ("course", "test") and copy.is_test_deck
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet([], "none"))
    deck_actions.on_duplicate_deck(window, deck)
    assert _tags(root / "decks" / "none.tex") == "intro"


def test_new_deck_with_two_groups_and_with_none(qapp, monkeypatch, tmp_path):
    window, root, _deck = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet(["research", "work"], "two"))
    deck_actions.on_new_deck(window)
    assert _tags(root / "decks" / "two.tex") == "work,research"
    assert next(d for d in window.decks if d.name == "two").groups == ("work", "research")
    monkeypatch.setattr(deck_actions, "DeckGroupSheet", lambda *a, **k: _Sheet([], "none"))
    deck_actions.on_new_deck(window)
    assert deck_scan.find_decktags(read_text_exact(root / "decks" / "none.tex")) is None
    assert next(d for d in window.decks if d.name == "none").groups == ("course",)    # the fallback group
