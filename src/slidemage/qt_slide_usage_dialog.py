"""Save-time dialog for a slide that is used in several decks (v5.23.0,
direct instruction): per deck, move on to the new version or stay on the
previous one -- see slide_usage.py for what each choice does to the deck.
Also names the slide's translations, which this save leaves unchanged."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import slide_usage

CURRENT = "current"
KEEP = "keep"


class SlideUsageDialog(QDialog):
    """exec() == Accepted: choices() maps deck name -> "current" | "keep"
    (decks without a choice are left out), open_translation() says whether
    to open the first translation afterwards."""

    def __init__(
        self,
        parent: Optional[QWidget],
        slide_name: str,
        new_version: str,
        old_version: Optional[str],
        usages: list,
        translations: list,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Where this slide is used")
        self.setMinimumWidth(640)
        self._combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        old = f"v{old_version}" if old_version else None
        intro = QLabel(
            f"<b>{slide_name}</b> is saved as v{new_version}"
            + (f"; the outgoing content is kept as {old}." if old else ".")
            + "<br>For each deck, choose which version it uses from now on.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Deck</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Uses now</b>"), 0, 1)
        grid.addWidget(QLabel("<b>From now on</b>"), 0, 2)
        for row, usage in enumerate(usages, start=1):
            name = usage.deck.name + (" (archived)" if usage.deck.archived else "")
            grid.addWidget(QLabel(name), row, 0)
            state = QLabel(usage.state_text())
            state.setWordWrap(True)
            grid.addWidget(state, row, 1)
            combo = QComboBox()
            if usage.only_unpinnable:
                combo.addItem("Current (nothing to choose)", None)
                combo.setEnabled(False)
            else:
                combo.addItem(f"Move to current (v{new_version})", CURRENT)
                if usage.following and old:
                    combo.addItem(f"Keep {old}", KEEP)
                if usage.pinned_versions:
                    combo.addItem("Stay on " + ", ".join(
                        "v" + v.replace("-", ".") for v in usage.pinned_versions), KEEP)
            self._combos[usage.deck.name] = combo
            grid.addWidget(combo, row, 2)
        layout.addLayout(grid)

        self._open_translation: Optional[QCheckBox] = None
        if translations:
            lines = []
            for t in translations:
                where = ", ".join(t.decks) if t.decks else "no deck"
                lines.append(f"<li><b>{t.id_slug}</b> ({t.language or 'translation'}), used in {where}</li>")
            note = QLabel(
                "<br>This slide has a translation. It is not changed by this save -- "
                "update it to match, and choose its version in its decks the same way:"
                f"<ul>{''.join(lines)}</ul>")
            note.setWordWrap(True)
            layout.addWidget(note)
            self._open_translation = QCheckBox("Open the translation in the editor after saving")
            layout.addWidget(self._open_translation)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choices(self) -> dict[str, str]:
        out = {}
        for name, combo in self._combos.items():
            value = combo.currentData()
            if value is not None:
                out[name] = value
        return out

    def open_translation(self) -> bool:
        return self._open_translation is not None and self._open_translation.isChecked()
