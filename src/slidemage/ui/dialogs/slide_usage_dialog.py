# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choose call edits for a shared slide and preview the captured revision's outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import slide_usage, slide_versioning

CURRENT = "current"
KEEP = "keep"


def revision_summary(proposal: slide_versioning.Proposal, current: Path, root: Path, *,
                     pin: str | None = None) -> str:
    outcomes = slide_usage.revision_outcomes(proposal, current, pin=pin)
    lines = []
    if pin is not None or len({deck for deck, _ in outcomes}) > 1:
        lines = [f"{deck.relative_to(root).as_posix()} — {outcome}" for deck, outcome in outcomes]
        if not lines:
            lines.append("No decks are pinned to this version.")
    hints = []
    if proposal.has_translation:
        hints.append("Another language may load a matching translation instead.")
    marker = slide_versioning.parse_marker(proposal.inputs[current])
    if marker and marker[1]:
        hints.append("A compile may use the last frozen version; Compile with edits uses the current text.")
    return "\n\n".join(section for section in ("\n".join(lines), "\n".join(hints)) if section)


class SlideUsageDialog(QDialog):
    """Choose edits for a version bump, or confirm an Overwrite with a read-only summary."""

    def __init__(
        self,
        parent: Optional[QWidget],
        root: Path,
        cap: slide_versioning.Proposal,
        current: Path,
        level: slide_versioning.BumpLevel | None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(640)
        self._combos: dict[Path, QComboBox] = {}
        self._open_translation: Optional[QCheckBox] = None
        layout = QVBoxLayout(self)
        body = QWidget()
        content = QVBoxLayout(body)
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        if level is None:
            self.setWindowTitle("Overwrite version")
            slide_name = current.name.removesuffix("-current.tex")
            base = slide_versioning.parse_version(cap.inputs[current]) or slide_versioning.DEFAULT_BASELINE
            pin = slide_versioning.format_hyphen(base)
            text = (f"Replace {slide_versioning.version_label(pin)} of {slide_name} with the current content?\n\n"
                    + revision_summary(cap, current, root, pin=pin))
            summary = QLabel(text)
            summary.setTextFormat(Qt.TextFormat.PlainText)
            summary.setAlignment(Qt.AlignmentFlag.AlignTop)
            summary.setWordWrap(True)
            content.addWidget(summary)
        else:
            self.setWindowTitle("Where this slide is used")
            self._add_choices(content, root, cap, current, level)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Overwrite" if level is None else "Save")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if level is None:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)

    def _add_choices(self, content, root, cap, current, level):
        slide_name = current.name.removesuffix("-current.tex")
        new_version, base = cap.update(current, level)
        new = slide_versioning.format_dot(new_version)
        old = f"v{slide_versioning.format_dot(base)}" if cap.base_file(current) in cap.frozen else None
        intro = QLabel(
            f"<b>{slide_name}</b> is saved as v{new}"
            + (f"; the outgoing content is kept as {old}." if old else ".")
            + "<br>Choose which version each deck, block or fragment uses from now on.")
        intro.setWordWrap(True)
        content.addWidget(intro)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Source file</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Uses now</b>"), 0, 1)
        grid.addWidget(QLabel("<b>From now on</b>"), 0, 2)
        for row, usage in enumerate(cap.usages, start=1):
            name = usage.deck.name + (f" (used by {len(usage.decks)} decks)" if usage.block else
                                      " (archived)" if usage.deck.archived else "")
            source = QLabel(name)
            source.setTextFormat(Qt.TextFormat.PlainText)
            source.setWordWrap(True)
            grid.addWidget(source, row, 0)
            if usage.block:
                decks = ", ".join(d.path.relative_to(root).as_posix() for d in usage.decks)
                source.setText(f"{name}\nUsed by {decks}")
            state = QLabel(usage.state_text())
            state.setWordWrap(True)
            grid.addWidget(state, row, 1)
            combo = QComboBox()
            combo.addItem("Leave calls as written", None)
            if usage.only_unpinnable:
                combo.setEnabled(False)
            else:
                combo.addItem(f"Move to current (v{new})", CURRENT)
                if usage.following and old:
                    combo.addItem(f"Keep {old}", KEEP)
            self._combos[usage.deck.path] = combo
            grid.addWidget(combo, row, 2)
        content.addLayout(grid)
        if any(call.block and call.id_slug == slide_name for _, call in cap.occurrences):
            note = QLabel("A block's choice applies to every deck that uses it. "
                          "Keep pins the call in the block file. For a per-deck choice, Unlink the block first.")
            note.setWordWrap(True)
            content.addWidget(note)

        summary = QLabel()
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        content.addWidget(summary)

        def refresh():
            proposal = cap.with_edits(slide_versioning.patch_edits(cap, current, level, self.choices()))
            text = revision_summary(proposal, current, root)
            summary.setText(text)
            summary.setVisible(bool(text))

        for combo in self._combos.values():
            combo.currentIndexChanged.connect(refresh)
        refresh()

        if cap.translations:
            lines = []
            for t in cap.translations:
                where = ", ".join(t.decks) if t.decks else "no deck"
                lines.append(f"<li><b>{t.id_slug}</b> ({t.language or 'translation'}), used in {where}</li>")
            note = QLabel(
                "<br>This slide has a translation. It is not changed by this save -- "
                "update it to match, and choose its version in its decks the same way:"
                f"<ul>{''.join(lines)}</ul>")
            note.setWordWrap(True)
            content.addWidget(note)
            self._open_translation = QCheckBox("Open the translation in the editor after saving")
            content.addWidget(self._open_translation)

    def choices(self) -> dict[Path, str]:
        out = {}
        for name, combo in self._combos.items():
            value = combo.currentData()
            if value is not None:
                out[name] = value
        return out

    def open_translation(self) -> bool:
        return self._open_translation is not None and self._open_translation.isChecked()


@dataclass
class DeckVersions:
    choices: dict[Path, str]                 # file path -> CURRENT | KEEP (empty: nothing to choose)
    open_translation: Optional[Path]        # the translation to open after the save, if asked for


def ask_deck_versions(
    parent: QWidget | None, root: Path, cap: slide_versioning.Proposal,
    current: Path, level: slide_versioning.BumpLevel,
) -> Optional[DeckVersions]:
    """Ask about shared calls when making a new version. Return None on Cancel."""
    if not slide_usage.needs_dialog(cap.usages, cap.translations):
        return DeckVersions({}, None)
    new, base = cap.update(current, level)
    if new == base:
        return DeckVersions({}, None)
    dialog = SlideUsageDialog(parent, root, cap, current, level)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return DeckVersions(dialog.choices(), cap.translations[0].path if dialog.open_translation() else None)


def ask_overwrite(parent: QWidget, root: Path, proposal: slide_versioning.Proposal, current: Path) -> bool:
    return SlideUsageDialog(parent, root, proposal, current, None).exec() == QDialog.DialogCode.Accepted
