"""The sheet for a deck's group tag (UI_REDESIGN_PLAN.md, step 9): ⋮ "Tags…" asks for the group
alone, "Duplicate deck…" also for the copy's name. The group is stored in the deck's own file as
\\decktags{...} (deck_editor.set_deck_tags), where it decides the section of the deck switcher
the deck appears in.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QButtonGroup, QLabel, QLineEdit, QRadioButton, QVBoxLayout

from ...deck_scan import SELECTABLE_GROUP_TAGS, TAG_COURSE, TAG_RESEARCH, TAG_TEST, TAG_WORK
from ..kit import kit_qss as q
from ..kit.widgets import Field, ModalSheet, Surface, set_property

GROUP_LABELS = {
    TAG_WORK: "Workdeck (pinned to the top of the deck switcher)",
    TAG_COURSE: "Course deck",
    TAG_RESEARCH: "Research presentation",
    TAG_TEST: "Test deck",
}


class DeckGroupSheet(ModalSheet):
    def __init__(self, parent, title: str, current_group: str, *, ok_text: str = "Save",
                 name_prompt: Optional[str] = None, default_name: str = "",
                 validate_name: Optional[Callable[[str], Optional[str]]] = None) -> None:
        """After exec(), `name` ("" without `name_prompt`) and `group` hold the choice.
        `validate_name` returns the reason a name is unusable, shown in the sheet, or None."""
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

        group_box = Surface()
        group_layout = QVBoxLayout(group_box)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(6)
        buttons = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        # The manual's own group is never offered (deck_scan.TAG_MANUAL): a copy of the manual
        # starts out as a course deck.
        if current_group not in SELECTABLE_GROUP_TAGS:
            current_group = TAG_COURSE
        for tag in SELECTABLE_GROUP_TAGS:
            radio = QRadioButton(GROUP_LABELS[tag])
            radio.setChecked(tag == current_group)
            buttons.addButton(radio)
            self._radios[tag] = radio
            group_layout.addWidget(radio)
        layout.addWidget(Field("Group (decides the section of the deck switcher)", group_box))

        note = QLabel("Stored in the deck's own file as \\decktags{...}, so it stays with the deck.")
        note.setObjectName(q.PANEL_CAPTION)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.problem = QLabel()
        self.problem.setObjectName(q.PANEL_CAPTION)
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)

        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        ok = self.add_button(ok_text, kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        (self.name_edit or next(iter(self._radios.values()))).setFocus()
        self.name = ""
        self.group = current_group

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
        self.group = next(tag for tag, radio in self._radios.items() if radio.isChecked())
        self.accept()
