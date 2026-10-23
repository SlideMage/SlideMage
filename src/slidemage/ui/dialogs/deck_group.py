# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet for a deck's group tags (UI_REDESIGN_PLAN.md, step 9): ⋮ "Tags…" asks for the groups
alone, "Duplicate deck…" and "New deck…" also for the deck's name. The groups are stored in the deck's
own file as \\decktags{...} (deck_editor.set_deck_tags), where they decide the sections of the deck
switcher the deck is listed in: one checkbox per group of the project's list, any number of them
checked, none included (docs/plans/editable-deck-tags.md, step 3). "Tags…" also links to the list of
groups in Settings (step 5).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Callable, Optional

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout

from ...deck_groups import DEFAULT_GROUPS, DeckGroup, fallback_tag, headings, labels, selectable_tags
from ..kit.widgets import Button, Field, ModalSheet, Surface, caption, set_property

# The default groups' labels; a project's own list has deck_groups.labels(groups).
GROUP_LABELS = labels()


class DeckGroupSheet(ModalSheet):
    def __init__(self, parent, title: str, current_groups: Sequence[str], *, ok_text: str = "Save",
                 name_prompt: Optional[str] = None, default_name: str = "",
                 validate_name: Optional[Callable[[str], Optional[str]]] = None,
                 templates: Optional[Sequence[tuple[str, str]]] = None, current_template: str = "",
                 groups: Sequence[DeckGroup] = DEFAULT_GROUPS, edit_groups: bool = False) -> None:
        """After exec(), `name` ("" without `name_prompt`), `chosen_groups` (the checked groups' tags, in the
        list's order; none is allowed) and `template` ("" without `templates`) hold the choice. `current_groups`
        are checked to start with; without one of the list, the fallback group is. `validate_name` returns the
        reason a name is unusable, shown in the sheet, or None. `templates` is (key, label) pairs: a deck's institution template is asked for too. `groups` is the
        project's list of deck groups, the choices offered. With `edit_groups`, an "Edit groups…" button closes the
        sheet with `edit_groups_requested` set, for the caller to open Settings at the deck groups."""
        super().__init__(title, parent, width=480)
        self._validate_name = validate_name
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.name_edit: Optional[QLineEdit] = None
        if name_prompt is not None:
            self.name_edit = QLineEdit(default_name)
            self.name_edit.selectAll()
            self.name_edit.textChanged.connect(lambda _text: self._show_problem(""))
            layout.addWidget(Field(name_prompt, self.name_edit))
        self.template_box: Optional[QComboBox] = None
        if templates:
            self.template_box = QComboBox()
            for key, label in templates:
                self.template_box.addItem(label, key)
            self.template_box.setCurrentIndex(max(0, self.template_box.findData(current_template)))
            layout.addWidget(Field("Template (institution layout of the deck)", self.template_box))

        group_box = Surface()
        group_layout = QVBoxLayout(group_box)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(6)
        self._checks: dict[str, QCheckBox] = {}
        # The manual's own group is never offered (deck_groups.TAG_MANUAL): a copy of the manual
        # starts out in the fallback group (by default a course deck).
        selectable, group_labels = selectable_tags(groups), labels(groups)
        fallback = fallback_tag(groups)
        current = [tag for tag in selectable if tag in current_groups] or ([fallback] if fallback else [])
        for tag in selectable:
            check = QCheckBox(group_labels[tag])
            check.setChecked(tag in current)
            self._checks[tag] = check
            group_layout.addWidget(check)
        layout.addWidget(Field("Groups (the sections of the deck switcher the deck is listed in)", group_box))
        home = (headings(groups)[fallback] or group_labels[fallback]) if fallback else "Other decks"
        layout.addWidget(caption(f"With none checked, the deck is listed under {home}."))
        self.edit_groups_requested = False
        if edit_groups:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            edit = Button("Edit groups…", kind="ghost", compact=True)
            edit.setToolTip("Add, rename, reorder or remove the project's groups (Settings → Project)")
            edit.clicked.connect(self._on_edit_groups)
            row.addWidget(edit)
            row.addStretch(1)
            layout.addLayout(row)

        note = caption("Stored in the deck's own file as \\decktags{...}, so they stay with the deck.")
        layout.addWidget(note)
        self.problem = caption()
        self.problem.hide()
        layout.addWidget(self.problem)

        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button(ok_text, kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        focus = self.name_edit or next(iter(self._checks.values()), None)
        if focus is not None:
            focus.setFocus()
        self.name = ""
        self.chosen_groups: tuple[str, ...] = tuple(current)
        self.template = ""

    def _on_edit_groups(self) -> None:
        self.edit_groups_requested = True
        self.reject()

    def _show_problem(self, text: str) -> None:
        self.problem.setText(text)
        set_property(self.problem, "tone", "error")
        self.problem.setVisible(bool(text))

    def _on_ok(self) -> None:
        name = self.name_edit.text().strip() if self.name_edit is not None else ""
        reason = self._validate_name(name) if self.name_edit is not None and self._validate_name else None
        if reason is not None:
            self._show_problem(reason)
            return
        self.name = name
        self.chosen_groups = tuple(tag for tag, check in self._checks.items() if check.isChecked())
        if self.template_box is not None:
            self.template = self.template_box.currentData()
        self.accept()
