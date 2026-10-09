"""The small dialog for choosing a deck's group tag (2026-09-19): shown from
a deck row's "Tags" button, and from the Duplicate dialog (which also asks
for the copy's name). The choice is stored in the deck's own file as
\\decktags{...} -- see deck_editor.set_deck_tags().
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .deck_scan import SELECTABLE_GROUP_TAGS, TAG_COURSE, TAG_RESEARCH, TAG_TEST, TAG_WORK
from .ui.kit.theme import MUTED_LABEL

GROUP_LABELS = {
    TAG_WORK: "Workdeck (pinned to the top of the table)",
    TAG_COURSE: "Course deck",
    TAG_RESEARCH: "Research presentation",
    TAG_TEST: "Test deck",
}


def ask_deck_details(
    parent: QWidget,
    title: str,
    current_group: str,
    name_prompt: Optional[str] = None,
    default_name: str = "",
    validate_name: Optional[Callable[[str], Optional[str]]] = None,
) -> Optional[tuple[str, str]]:
    """Returns (name, group tag), or None if cancelled. `name_prompt=None`
    means no name field at all (tags-only edit; the returned name is "").
    `validate_name` returns a reason string for an unusable name (shown in
    a warning, then the dialog reopens with the text kept) or None."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)

    name_edit: Optional[QLineEdit] = None
    if name_prompt is not None:
        layout.addWidget(QLabel(name_prompt))
        name_edit = QLineEdit(default_name)
        name_edit.selectAll()
        layout.addWidget(name_edit)

    layout.addWidget(QLabel("Group (the tag decides which section of the deck table it appears in):"))
    group_buttons = QButtonGroup(dialog)
    radios: dict[str, QRadioButton] = {}
    # The manual's own group is never offered (deck_scan.TAG_MANUAL): a copy
    # of the manual starts out as a course deck.
    if current_group not in SELECTABLE_GROUP_TAGS:
        current_group = TAG_COURSE
    for tag in SELECTABLE_GROUP_TAGS:
        radio = QRadioButton(GROUP_LABELS[tag])
        radio.setChecked(tag == current_group)
        group_buttons.addButton(radio)
        radios[tag] = radio
        layout.addWidget(radio)

    note = QLabel("Stored in the deck's own file as \\decktags{...}, so it stays with the deck.")
    note.setWordWrap(True)
    note.setObjectName(MUTED_LABEL)
    layout.addWidget(note)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    (name_edit or next(iter(radios.values()))).setFocus()

    while True:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        name = name_edit.text().strip() if name_edit is not None else ""
        if name_edit is not None and validate_name is not None:
            reason = validate_name(name)
            if reason is not None:
                QMessageBox.critical(parent, title, reason)
                continue
        group = next(tag for tag, radio in radios.items() if radio.isChecked())
        return name, group
