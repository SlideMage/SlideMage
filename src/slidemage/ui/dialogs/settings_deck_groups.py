# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Project → Deck groups (docs/plans/editable-deck-tags.md, §5 and §6): the project's list of deck
groups in switcher order, and what can be done to it.

* Add group…: heading and label; the tag is proposed from the label and can be edited until saved.
* Edit…: heading, label, roles and fallback of any group, built-in ones too. Taking a role or the fallback from
  another group asks first. The tag never changes: decks name it in their files.
* Move up / Move down: the switcher's section order, and the compile order.
* Remove…: any group. Decks that carry its tag are moved to another group, lose the tag, or keep it in the file.
  Rewriting a deck's \\decktags is deck_editor.set_deck_tags (stale-checked), one undo step per deck.
* Restore the default groups: the built-in groups come back as shipped; the user's own groups stay.
* Found in decks: tags in decks that name no group, each with Add as group.

Like the rest of Settings, every change is saved at once (deck_groups.save, into .slidemage/project.json), and
the window rescans its decks (`reload_decks`), so the switcher and the menus follow.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QRadioButton, QVBoxLayout)

from ... import deck_editor, deck_groups
from ...deck_groups import DEFAULT_GROUPS, ROLE_PINNED, ROLE_TEST, DeckGroup
from ..kit.widgets import Button, Field, ModalSheet, Surface, caption, row, set_property

ROLE_NOTES = {ROLE_PINNED: "pinned on top", ROLE_TEST: "no slide list"}
FALLBACK_NOTE = "decks without a group go here"
ROLE_CHOICES = {ROLE_PINNED: "Pinned on top of the deck switcher, without a heading",
                ROLE_TEST: "Test decks: no slide list, no background previews"}
FALLBACK_CHOICE = "Decks without a group go here"

MOVE, TAKE_OFF, LEAVE = "move", "take_off", "leave"


def _decks(n: int) -> str:
    return f"{n} deck" if n == 1 else f"{n} decks"


def group_name(group: DeckGroup) -> str:
    return group.heading or group.label


def notes(group: DeckGroup) -> list[str]:
    found = [ROLE_NOTES[role] for role in deck_groups.ROLES if role in group.roles]
    return found + [FALLBACK_NOTE] if group.fallback else found


def retag(tags: Sequence[str], old: str, new: str | None) -> list[str]:
    """`tags` with `old` replaced by `new` where it stood (dropped if `new` is None or already there)."""
    result: list[str] = []
    for tag in tags:
        tag = new if tag == old else tag
        if tag is not None and tag not in result:
            result.append(tag)
    return result


class GroupSheet(ModalSheet):
    """Add group… (`group` None, or a tag found in decks as `tag`) and Edit… of one group. `check(group)`
    returns why a group cannot be added, or None. After exec(), `group` is the group as entered."""

    def __init__(self, parent, group: DeckGroup | None = None, *, tag: str = "",
                 check: Callable[[DeckGroup], str | None] = lambda _g: None) -> None:
        self._editing = group
        super().__init__("Edit group" if group else "Add group", parent, width=480)
        self._check = check
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        proposed = tag.replace("-", " ").capitalize()
        self.heading_edit = QLineEdit(group.heading if group else proposed)
        self.label_edit = QLineEdit(group.label if group else proposed)
        self.tag_edit = QLineEdit(group.tag if group else tag)
        self.tag_edit.setReadOnly(group is not None or bool(tag))
        self._tag_typed = bool(tag)
        self.tag_edit.textEdited.connect(self._on_tag_typed)
        self.label_edit.textEdited.connect(self._on_label)
        layout.addWidget(Field("Heading in the deck switcher (empty: no heading)", self.heading_edit))
        layout.addWidget(Field("Label in the Tags sheet", self.label_edit))
        layout.addWidget(Field("Tag (what \\decktags carries in the deck's file)", self.tag_edit))
        layout.addWidget(caption(
            "The tag cannot change once the group is saved: decks name it in their files." if group is None else
            "The tag cannot change: decks name it in their files."))
        self.role_checks: dict[str, QCheckBox] = {}
        self.fallback_check: QCheckBox | None = None
        if group is not None:
            roles = Surface()
            roles_layout = QVBoxLayout(roles)
            roles_layout.setContentsMargins(0, 0, 0, 0)
            roles_layout.setSpacing(6)
            for role, text in ROLE_CHOICES.items():
                check_box = QCheckBox(text)
                check_box.setChecked(role in group.roles)
                self.role_checks[role] = check_box
                roles_layout.addWidget(check_box)
            self.fallback_check = QCheckBox(FALLBACK_CHOICE)
            self.fallback_check.setChecked(group.fallback)
            roles_layout.addWidget(self.fallback_check)
            layout.addWidget(Field("Roles (each is on one group at most)", roles))
        self.problem = caption()
        self.problem.hide()
        layout.addWidget(self.problem)
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button("Save" if group else "Add", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        (self.label_edit if tag else self.heading_edit).setFocus()
        self.group = group

    def _on_tag_typed(self, _text: str) -> None:
        self._tag_typed = True
        self._show_problem("")

    def _on_label(self, label: str) -> None:
        self._show_problem("")
        if self._editing is None and not self._tag_typed:
            self.tag_edit.setText(deck_groups.tag_from_label(label))

    def _show_problem(self, text: str) -> None:
        self.problem.setText(text)
        set_property(self.problem, "tone", "error")
        self.problem.setVisible(bool(text))

    def entered(self) -> DeckGroup:
        roles = frozenset(role for role, box in self.role_checks.items() if box.isChecked())
        if self._editing is not None:
            roles |= self._editing.roles - set(deck_groups.ROLES)      # a role this SlideMage does not know stays
        return DeckGroup(self.tag_edit.text().strip(), self.label_edit.text().strip(),
                         self.heading_edit.text().strip(), roles,
                         self.fallback_check.isChecked() if self.fallback_check is not None else False)

    def _on_ok(self) -> None:
        group = self.entered()
        reason = self._check(group)
        if reason is not None:
            self._show_problem(reason)
            return
        self.group = group
        self.accept()


class RemoveGroupSheet(ModalSheet):
    """Remove… of a group that decks carry: move them to another group, take the tag off them, or leave it in
    the files. After exec(), `choice` is MOVE, TAKE_OFF or LEAVE, and `target` the other group's tag for MOVE."""

    def __init__(self, parent, group: DeckGroup, count: int, others: Sequence[DeckGroup]) -> None:
        super().__init__(f"Remove “{group_name(group)}”", parent, width=480)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(caption(f"{_decks(count)} {'carries' if count == 1 else 'carry'} the tag "
                                 f"“{group.tag}” in {'its' if count == 1 else 'their'} file."))
        buttons = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        self.target_box = QComboBox()
        for other in others:
            self.target_box.addItem(group_name(other), other.tag)
        for key, text in ((MOVE, "Move them to another group:"),
                          (TAKE_OFF, "Take the tag off them"),
                          (LEAVE, "Leave the tag in the files – it then names no group")):
            radio = QRadioButton(text)
            buttons.addButton(radio)
            self._radios[key] = radio
            layout.addWidget(radio)
            if key == MOVE:
                layout.addWidget(self.target_box)
        self._radios[MOVE].setEnabled(bool(others))
        self._radios[MOVE if others else TAKE_OFF].setChecked(True)
        self._radios[MOVE].toggled.connect(self.target_box.setEnabled)
        self.target_box.setEnabled(bool(others))
        layout.addWidget(caption("A deck left without a group goes to the group for decks without a group, or to "
                                 "Other decks. Undo in the slide list takes a deck's change back."))
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button("Remove", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        self.choice = MOVE if others else TAKE_OFF
        self.target: str | None = None

    def choose(self, choice: str, target: str | None = None) -> None:
        """Select an answer (and the group to move to), as clicking would."""
        self._radios[choice].setChecked(True)
        if target is not None:
            self.target_box.setCurrentIndex(self.target_box.findData(target))

    def _on_ok(self) -> None:
        self.choice = next(key for key, radio in self._radios.items() if radio.isChecked())
        self.target = self.target_box.currentData() if self.choice == MOVE else None
        self.accept()


class DeckGroupsSection(Surface):
    """The Deck groups part of Settings' Project tab. `app` is the window: its project, its decks and
    `reload_decks` (a window without them shows no counts and has nothing to rescan)."""

    changed = Signal()        # a list was saved

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.groups: list[DeckGroup] = list(deck_groups.load(app.project))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.list = QListWidget()
        self.list.setAccessibleName("Deck groups")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(170)
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self.edit_group())
        layout.addWidget(Field("Deck groups (the deck switcher's sections, top to bottom)", self.list))
        self.add_button = Button("Add group…", compact=True)
        self.edit_button = Button("Edit…", compact=True)
        self.up_button = Button("Move up", compact=True)
        self.down_button = Button("Move down", compact=True)
        self.remove_button = Button("Remove…", compact=True)
        self.restore_button = Button("Restore the default groups", compact=True)
        for button, slot in ((self.add_button, self.add_group), (self.edit_button, self.edit_group),
                             (self.up_button, lambda: self.move(-1)), (self.down_button, lambda: self.move(1)),
                             (self.remove_button, self.remove_group), (self.restore_button, self.restore_defaults)):
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
        layout.addWidget(row(self.add_button, self.edit_button, self.up_button, self.down_button,
                             self.remove_button, self.restore_button, stretch=6))
        layout.addWidget(caption(
            "A deck names its groups in its own file, \\decktags{course,workshops}, and is listed under each. "
            "The list is stored with the project (.slidemage/project.json), so everyone who opens it sees the "
            "same groups."))

        self.found_list = QListWidget()
        self.found_list.setAccessibleName("Tags found in decks")
        self.found_list.setMaximumHeight(96)
        self.found_list.itemSelectionChanged.connect(self._sync_buttons)
        self.add_found_button = Button("Add as group…", compact=True)
        self.add_found_button.clicked.connect(lambda: self.add_found())
        self.found = Surface()
        found_layout = QVBoxLayout(self.found)
        found_layout.setContentsMargins(0, 0, 0, 0)
        found_layout.setSpacing(6)
        found_layout.addWidget(Field("Found in decks (tags that name no group)", self.found_list))
        found_layout.addWidget(row(caption("Nothing changes in the files until you add one as a group."),
                                   self.add_found_button))
        layout.addWidget(self.found)
        self.fill()

    # -- what the list shows ------------------------------------------------------------------------------------------

    def decks(self) -> list:
        return list(getattr(self.app, "decks", None) or [])

    def count(self, tag: str) -> int:
        """The decks in the group `tag`: each deck counts in every group it is in."""
        return sum(1 for d in self.decks() if tag in deck_groups.groups_of(d.tags, self.groups))

    def carriers(self, tag: str) -> list:
        """The decks whose own file names `tag`."""
        return [d for d in self.decks() if tag in d.tags]

    def found_tags(self) -> Counter:
        known = set(deck_groups.group_tags(self.groups))
        return Counter(tag for d in self.decks() for tag in dict.fromkeys(d.tags) if tag not in known)

    def fill(self, select: str | None = None) -> None:
        select = select if select is not None else self.selected_tag()
        self.list.clear()
        for group in self.groups:
            details = [f"label “{group.label}”", f"tag {group.tag}", *notes(group), _decks(self.count(group.tag))]
            item = QListWidgetItem(f"{group.heading or '(no heading)'}\n    " + "  ·  ".join(details))
            item.setData(Qt.ItemDataRole.UserRole, group.tag)
            self.list.addItem(item)
            if group.tag == select:
                self.list.setCurrentItem(item)
        self.found_list.clear()
        for tag, n in sorted(self.found_tags().items()):
            item = QListWidgetItem(f"{tag}  ·  {_decks(n)}")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            self.found_list.addItem(item)
        self.found.setVisible(self.found_list.count() > 0)
        self._sync_buttons()

    def selected_tag(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None and item.isSelected() else None

    def select(self, tag: str) -> None:
        self.fill(select=tag)

    def _index(self, tag: str | None) -> int:
        return next((i for i, g in enumerate(self.groups) if g.tag == tag), -1)

    def _sync_buttons(self) -> None:
        index = self._index(self.selected_tag())
        for button in (self.edit_button, self.remove_button):
            button.setEnabled(index >= 0)
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < len(self.groups) - 1)
        self.add_found_button.setEnabled(self.found_list.currentItem() is not None)

    # -- saving ------------------------------------------------------------------------------------------------------

    def commit(self, groups: Sequence[DeckGroup], summary: str, select: str | None = None) -> bool:
        """Save `groups` as the project's list, rescan the decks and show the list again."""
        try:
            deck_groups.save(self.app.project, groups)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Deck groups", f"Couldn't save the deck groups: {exc}")
            return False
        self.groups = list(groups)
        self._reload()
        self.fill(select)
        log = getattr(self.app, "log", None)
        if log is not None:
            log(summary)
        self.changed.emit()
        return True

    def _reload(self) -> None:
        reload = getattr(self.app, "reload_decks", None)
        if reload is not None:
            reload()

    def _check_new(self, group: DeckGroup) -> str | None:
        if not group.tag:
            return "The group needs a tag."
        taken = next((g for g in self.groups if g.tag == group.tag), None)
        if taken is not None:
            return f"The tag “{group.tag}” is taken by the group “{group_name(taken)}”."
        return deck_groups.validate([*self.groups, group])

    # -- the buttons -------------------------------------------------------------------------------------------------

    def add_group(self, tag: str = "") -> None:
        sheet = GroupSheet(self, tag=tag, check=self._check_new)
        if not sheet.exec() or sheet.group is None:
            return
        group = sheet.group
        self.commit([*self.groups, group], f"Added the deck group {group.tag}", group.tag)

    def add_found(self) -> None:
        item = self.found_list.currentItem()
        if item is not None:
            self.add_group(item.data(Qt.ItemDataRole.UserRole))

    def edit_group(self) -> None:
        index = self._index(self.selected_tag())
        if index < 0:
            return
        old = self.groups[index]

        def giving_up(other: DeckGroup, new: DeckGroup) -> DeckGroup:
            """`other` without the roles and the fallback that `new` takes."""
            return DeckGroup(other.tag, other.label, other.heading, other.roles - new.roles,
                             other.fallback and not new.fallback)

        others = [g for g in self.groups if g.tag != old.tag]
        sheet = GroupSheet(self, old, check=lambda g: deck_groups.validate([*(giving_up(o, g) for o in others), g]))
        if not sheet.exec() or sheet.group is None or sheet.group == old:
            return
        new = sheet.group
        taken = [ROLE_NOTES[role] for role in deck_groups.ROLES if role in new.roles - old.roles]
        if new.fallback and not old.fallback:
            taken.append(FALLBACK_NOTE)
        holders = [(note, g) for note in taken for g in others if giving_up(g, new) != g and note in notes(g)]
        for note, holder in holders:
            if QMessageBox.question(
                    self, "Deck groups", f"“{note}” is on the group “{group_name(holder)}”. Move it to "
                    f"“{group_name(new)}”?") != QMessageBox.StandardButton.Yes:
                return
        groups = [new if g.tag == old.tag else giving_up(g, new) for g in self.groups]
        self.commit(groups, f"Changed the deck group {new.tag}", new.tag)

    def move(self, delta: int) -> None:
        index = self._index(self.selected_tag())
        other = index + delta
        if index < 0 or not 0 <= other < len(self.groups):
            return
        groups = list(self.groups)
        groups[index], groups[other] = groups[other], groups[index]
        self.commit(groups, f"Moved the deck group {groups[other].tag} {'up' if delta < 0 else 'down'}",
                    groups[other].tag)

    def remove_group(self) -> None:
        index = self._index(self.selected_tag())
        if index < 0:
            return
        group = self.groups[index]
        remaining = [g for g in self.groups if g.tag != group.tag]
        carriers = self.carriers(group.tag)
        if not carriers:
            if QMessageBox.question(self, "Remove group", f"Remove the group “{group_name(group)}”? No deck "
                                    "carries its tag.") != QMessageBox.StandardButton.Yes:
                return
            self.commit(remaining, f"Removed the deck group {group.tag}")
            return
        sheet = RemoveGroupSheet(self, group, len(carriers), remaining)
        if not sheet.exec():
            return
        if not self.commit(remaining, f"Removed the deck group {group.tag}"):
            return
        if sheet.choice == LEAVE:
            return
        target = sheet.target if sheet.choice == MOVE else None
        self.retag_decks(carriers, group.tag, target)

    def retag_decks(self, decks: Sequence, old: str, new: str | None) -> None:
        """Rewrite each deck's \\decktags with `old` replaced by `new` (or dropped), one undo step per deck."""
        centre = getattr(self.app, "centre", None)
        done: list[tuple[Path, str, str]] = []
        failed: list[str] = []
        for deck in decks:
            if centre is not None and centre.unsaved(deck.path):
                failed.append(f"{deck.name}: it has edits in the Source view that could not be saved")
                continue
            try:
                deck_editor.set_deck_tags(deck.path, deck.text, retag(deck.tags, old, new))
            except (deck_editor.StaleFileError, ValueError, OSError) as exc:
                failed.append(f"{deck.name}: {exc}")
                continue
            done.append((deck.path, deck.name, deck.text))
        if done:
            self._reload()
            self.fill()
        slide_list = getattr(self.app, "slide_list", None)
        for path, name, previous in done:
            summary = f"Moved {name} from {old} to {new}" if new else f"Took the tag {old} off {name}"
            if slide_list is not None:
                slide_list.deck_edited(path, summary, previous)
            log = getattr(self.app, "log", None)
            if log is not None:
                log(summary)
        if failed:
            QMessageBox.warning(self, "Deck groups", "These decks still carry the tag “" + old + "”:\n\n"
                                + "\n".join(failed))

    def restore_defaults(self) -> None:
        if QMessageBox.question(
                self, "Restore the default groups",
                "Bring back the built-in groups (work, course, research and test) with their headings, labels and "
                "roles as shipped? Groups of your own stay; a role a built-in group takes back is taken off "
                "them.") != QMessageBox.StandardButton.Yes:
            return
        default_tags = {g.tag for g in DEFAULT_GROUPS}
        taken = {role for g in DEFAULT_GROUPS for role in g.roles}
        fallback_taken = any(g.fallback for g in DEFAULT_GROUPS)
        own = [DeckGroup(g.tag, g.label, g.heading, g.roles - taken, g.fallback and not fallback_taken)
               for g in self.groups if g.tag not in default_tags]
        self.commit([*DEFAULT_GROUPS, *own], "Restored the default deck groups", self.selected_tag())
