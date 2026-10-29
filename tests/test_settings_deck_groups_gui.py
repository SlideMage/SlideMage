# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Project → Deck groups (docs/plans/editable-deck-tags.md §5–6): add, edit, reorder, remove with its
three answers, restore the defaults, tags found in decks, and the window following a saved list. Every project
here is a throwaway one under tmp_path."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from slidemage import deck_groups, deck_scan
from slidemage.deck_groups import DEFAULT_GROUPS, ROLE_PINNED, DeckGroup
from slidemage.project import ProjectContext
from slidemage.ui.dialogs import settings_deck_groups as sdg
from slidemage.ui.dialogs.deck_group import DeckGroupSheet
from slidemage.ui.dialogs.settings import DECK_GROUPS, PROJECT, SettingsSheet
from slidemage.ui.dialogs.settings_deck_groups import LEAVE, MOVE, TAKE_OFF, GroupSheet, RemoveGroupSheet
from slidemage.ui.workspace import menus
from conftest import build_window, make_project

PREAMBLE = "\\documentclass{beamer}\n\\input{SlideMage_template}\n"


def deck_text(tags: str | None) -> str:
    line = f"\\decktags{{{tags}}}\n" if tags is not None else ""
    return f"{PREAMBLE}{line}\\begin{{document}}\n\\end{{document}}\n"


class FakeApp(QWidget):
    """The window as far as the section uses it: its project, decks, rescan, log and the slide list's undo."""

    def __init__(self, ctx):
        super().__init__()
        self.project = ctx
        self.logged, self.undo = [], []
        self.log = self.logged.append
        self.slide_list = SimpleNamespace(deck_edited=lambda path, summary, previous: self.undo.append(
            (path.name, summary, previous)))
        self.centre = SimpleNamespace(unsaved=lambda _path: False)
        self.reload_decks()

    def reload_decks(self):
        self.deck_groups = deck_groups.load(self.project)
        self.decks = deck_scan.scan_decks(self.project)


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "project"
    (root / "decks").mkdir(parents=True)
    (root / ".slidemage").mkdir()
    for name, tags in (("alpha", "course"), ("beta", "course,intro"), ("gamma", "research,intro"),
                       ("delta", None), ("work", "work")):
        (root / "decks" / f"{name}.tex").write_text(deck_text(tags), encoding="utf-8", newline="\n")
    return ProjectContext.at(root)


@pytest.fixture
def app(ctx, qapp):
    return FakeApp(ctx)


@pytest.fixture
def section(app):
    return sdg.DeckGroupsSection(app)


def stored(ctx):
    return json.loads((ctx.root / ".slidemage" / "project.json").read_text(encoding="utf-8"))["deck_groups"]


def tags_in(ctx, name):
    return deck_scan.parse_tags((ctx.root / "decks" / f"{name}.tex").read_text(encoding="utf-8"))


def fill_group_sheet(monkeypatch, *, heading=None, label=None, tag=None, roles=None, fallback=None, seen=None):
    """The next GroupSheet is filled in so and its Save/Add pressed; a refused entry leaves it open (Cancel)."""
    def exec_(self):
        if heading is not None:
            self.heading_edit.setText(heading)
        if label is not None:
            self.label_edit.setText(label)
            self.label_edit.textEdited.emit(label)
        if tag is not None:
            self.tag_edit.setText(tag)
            self.tag_edit.textEdited.emit(tag)
        for role, on in (roles or {}).items():
            self.role_checks[role].setChecked(on)
        if fallback is not None:
            self.fallback_check.setChecked(fallback)
        self._on_ok()
        if seen is not None:
            seen.append(self)
        return self.result()
    monkeypatch.setattr(GroupSheet, "exec", exec_)


def answer_questions(monkeypatch, answer=QMessageBox.StandardButton.Yes):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda _parent, _title, text, *a, **k: (asked.append(text), answer)[1])
    return asked


def texts(section):
    return [section.list.item(i).text() for i in range(section.list.count())]


# -- the list -------------------------------------------------------------------------------------------------------

def test_the_list_shows_each_group_with_its_label_tag_roles_and_decks(section):
    rows = texts(section)
    assert [r.splitlines()[0] for r in rows] == ["(no heading)", "Course decks", "Research presentations",
                                                 "Test decks"]
    assert "tag work" in rows[0] and "pinned on top" in rows[0] and "1 deck" in rows[0]
    # alpha and beta name it, delta has no group and goes to the fallback
    assert "decks without a group go here" in rows[1] and "3 decks" in rows[1]
    assert "label “Research presentation”" in rows[2] and "1 deck" in rows[2]
    assert "no slide list" in rows[3] and "0 decks" in rows[3]


def test_a_deck_counts_in_every_group_it_names(ctx, qapp):
    (ctx.root / "decks" / "both.tex").write_text(deck_text("course,research"), encoding="utf-8")
    rows = texts(sdg.DeckGroupsSection(FakeApp(ctx)))
    assert "4 decks" in rows[1] and "2 decks" in rows[2]


# -- add ------------------------------------------------------------------------------------------------------------

def test_add_proposes_the_tag_from_the_label_and_saves_the_group_last(ctx, app, section, monkeypatch):
    seen = []
    fill_group_sheet(monkeypatch, heading="Guest lectures", label="Guest lecture", seen=seen)
    section.add_button.click()
    assert seen[0].tag_edit.text() == "guest-lecture"
    assert stored(ctx)[-1] == {"tag": "guest-lecture", "label": "Guest lecture", "heading": "Guest lectures"}
    assert app.deck_groups[-1].tag == "guest-lecture"            # the window rescanned with the new list
    assert section.selected_tag() == "guest-lecture"


def test_a_tag_typed_by_hand_is_kept_when_the_label_changes(ctx, section, monkeypatch):
    def exec_(self):
        self.tag_edit.setText("ws")
        self.tag_edit.textEdited.emit("ws")
        self.label_edit.setText("Workshop")
        self.label_edit.textEdited.emit("Workshop")
        self._on_ok()
        return self.result()
    monkeypatch.setattr(GroupSheet, "exec", exec_)
    section.add_group()
    assert stored(ctx)[-1]["tag"] == "ws"


@pytest.mark.parametrize("tag, reason", [("course", "taken by the group “Course decks”"),
                                         ("manual", "reserved"), ("Bad Tag", "lowercase")])
def test_add_refuses_a_taken_reserved_or_invalid_tag_in_the_sheet(ctx, section, monkeypatch, tag, reason):
    seen = []
    fill_group_sheet(monkeypatch, heading="X", label="X", tag=tag, seen=seen)
    section.add_group()
    assert reason in seen[0].problem.text() and not seen[0].problem.isHidden()
    assert not (ctx.root / ".slidemage" / "project.json").exists()


# -- edit -----------------------------------------------------------------------------------------------------------

def test_edit_changes_heading_and_label_of_a_built_in_group_not_its_tag(ctx, section, monkeypatch):
    section.select("research")
    seen = []
    fill_group_sheet(monkeypatch, heading="Talks", label="Talk", seen=seen)
    section.edit_button.click()
    assert seen[0].tag_edit.isReadOnly()
    assert stored(ctx)[2] == {"tag": "research", "label": "Talk", "heading": "Talks"}


def test_moving_a_role_asks_first_and_takes_it_off_the_group_that_had_it(ctx, section, monkeypatch):
    section.select("research")
    asked = answer_questions(monkeypatch)
    fill_group_sheet(monkeypatch, roles={ROLE_PINNED: True}, fallback=True)
    section.edit_group()
    assert len(asked) == 2 and "pinned on top" in asked[0] and "decks without a group go here" in asked[1]
    by_tag = {g["tag"]: g for g in stored(ctx)}
    assert by_tag["research"]["roles"] == ["pinned"] and by_tag["research"]["fallback"]
    assert "roles" not in by_tag["work"] and "fallback" not in by_tag["course"]


def test_declining_the_question_changes_nothing(ctx, section, monkeypatch):
    section.select("research")
    answer_questions(monkeypatch, QMessageBox.StandardButton.No)
    fill_group_sheet(monkeypatch, roles={ROLE_PINNED: True})
    section.edit_group()
    assert not (ctx.root / ".slidemage" / "project.json").exists()


# -- reorder --------------------------------------------------------------------------------------------------------

def test_move_up_and_down_reorder_the_list_and_keep_the_group_selected(ctx, section):
    section.select("research")
    section.up_button.click()
    assert [g["tag"] for g in stored(ctx)] == ["work", "research", "course", "test"]
    assert section.selected_tag() == "research"
    section.down_button.click()
    section.down_button.click()
    assert [g["tag"] for g in stored(ctx)] == ["work", "course", "test", "research"]
    assert not section.down_button.isEnabled() and section.up_button.isEnabled()


# -- remove ---------------------------------------------------------------------------------------------------------

def remove_answering(monkeypatch, choice, target=None, seen=None):
    def exec_(self):
        if seen is not None:
            seen.append(self)
        self.choose(choice, target)
        self._on_ok()
        return self.result()
    monkeypatch.setattr(RemoveGroupSheet, "exec", exec_)


def test_remove_moves_the_decks_to_another_group_one_undo_step_each(ctx, app, section, monkeypatch):
    section.select("course")
    remove_answering(monkeypatch, MOVE, "research")
    before = (ctx.root / "decks" / "beta.tex").read_text(encoding="utf-8")
    section.remove_button.click()
    assert [g["tag"] for g in stored(ctx)] == ["work", "research", "test"]
    assert tags_in(ctx, "alpha") == ["research"] and tags_in(ctx, "beta") == ["research", "intro"]
    assert [(name, previous == before) for name, _s, previous in app.undo] == [
        ("alpha.tex", False), ("beta.tex", True)]
    assert [d.groups for d in app.decks if d.name == "alpha"] == [("research",)]


def test_remove_says_how_many_decks_carry_the_tag(section, monkeypatch):
    from PySide6.QtWidgets import QLabel
    section.select("course")
    seen = []
    remove_answering(monkeypatch, LEAVE, seen=seen)
    section.remove_group()
    assert any("2 decks carry the tag “course”" in label.text() for label in seen[0].findChildren(QLabel))


def test_remove_can_take_the_tag_off_the_decks(ctx, app, section, monkeypatch):
    section.select("research")
    remove_answering(monkeypatch, TAKE_OFF)
    section.remove_group()
    assert tags_in(ctx, "gamma") == ["intro"]
    assert [d.groups for d in app.decks if d.name == "gamma"] == [("course",)]      # the fallback takes it in
    assert [summary for _n, summary, _p in app.undo] == ["Took the tag research off gamma"]


def test_remove_can_leave_the_tag_in_the_files_and_it_shows_under_found_in_decks(ctx, section, monkeypatch):
    section.select("research")
    remove_answering(monkeypatch, LEAVE)
    section.remove_group()
    assert tags_in(ctx, "gamma") == ["research", "intro"]
    assert [g["tag"] for g in stored(ctx)] == ["work", "course", "test"]
    found = [section.found_list.item(i).text() for i in range(section.found_list.count())]
    assert found == ["intro  ·  2 decks", "research  ·  1 deck"]


def test_a_group_no_deck_carries_is_removed_after_a_question(ctx, section, monkeypatch):
    section.select("test")
    asked = answer_questions(monkeypatch)
    section.remove_group()
    assert asked and [g["tag"] for g in stored(ctx)] == ["work", "course", "research"]


def test_a_deck_with_unsaved_source_edits_keeps_its_tag_and_is_named(ctx, app, section, monkeypatch):
    app.centre.unsaved = lambda path: path.name == "alpha.tex"
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    section.select("course")
    remove_answering(monkeypatch, MOVE, "research")
    section.remove_group()
    assert tags_in(ctx, "alpha") == ["course"] and tags_in(ctx, "beta") == ["research", "intro"]
    assert "alpha" in warned[0]


# -- restore, found in decks ----------------------------------------------------------------------------------------

def test_restore_brings_back_the_defaults_and_keeps_the_users_own_groups(ctx, section, monkeypatch):
    own = DeckGroup("workshops", "Workshop", "Workshops", frozenset({ROLE_PINNED}))
    deck_groups.save(ctx, [DeckGroup("course", "Lecture", "Lectures"), own])
    section.groups = list(deck_groups.load(ctx))
    answer_questions(monkeypatch)
    section.restore_button.click()
    assert deck_groups.load(ctx) == (*DEFAULT_GROUPS, DeckGroup("workshops", "Workshop", "Workshops"))


def test_add_as_group_takes_a_tag_found_in_decks(ctx, app, section, monkeypatch):
    found = [section.found_list.item(i).text() for i in range(section.found_list.count())]
    assert found == ["intro  ·  2 decks"] and not section.found.isHidden()
    section.found_list.setCurrentRow(0)
    seen = []
    fill_group_sheet(monkeypatch, heading="Introductions", seen=seen)
    section.add_found_button.click()
    assert seen[0].tag_edit.isReadOnly() and seen[0].label_edit.text() == "Intro"
    assert stored(ctx)[-1] == {"tag": "intro", "label": "Intro", "heading": "Introductions"}
    assert section.found.isHidden()
    assert "2 decks" in texts(section)[-1]


# -- the window follows ---------------------------------------------------------------------------------------------

def test_settings_opens_at_the_deck_groups_and_the_deck_switcher_follows_a_saved_list(qapp, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    deck = root / "decks" / "test.tex"
    deck.write_bytes(deck.read_bytes().replace(b"\\begin{document}", b"\\decktags{workshops}\r\n\\begin{document}"))
    window = build_window(monkeypatch, ProjectContext.at(root))
    assert [h for h, decks in menus.deck_sections(window.decks, window.deck_groups) if decks] == ["Course decks"]
    sheet = SettingsSheet(window, focus=DECK_GROUPS)      # what window.open_deck_groups() opens
    assert sheet.current_tab() == PROJECT and sheet.focusWidget() is sheet.project_tab.deck_groups.list
    fill_group_sheet(monkeypatch, heading="Workshops", label="Workshop", tag="workshops")
    sheet.project_tab.deck_groups.add_group()
    assert [h for h, decks in menus.deck_sections(window.decks, window.deck_groups) if decks] == ["Workshops"]
    assert window.topbar._deck_groups == window.deck_groups
    assert "workshops" in DeckGroupSheet(window, "Tags", ("course",), groups=window.deck_groups)._checks
