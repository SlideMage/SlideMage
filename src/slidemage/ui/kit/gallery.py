# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Debug-only gallery of every kit widget, in light or dark mode:

    python -m slidemage.ui.kit.gallery [--light]

Not reachable from the application; it exists to eyeball the kit while
building later steps and is rendered by tests/test_ui_kit_gui.py.
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .fonts import FONT_DIR, load_fonts
from .kit_qss import FIELD_LABEL
from .theme import ThemeManager
from .tokens import VIEWS
from .widgets import (
    Button,
    Card,
    Chip,
    IconButton,
    IconLabel,
    Field,
    ModalSheet,
    PopoverMenu,
    SegmentedControl,
    SplitButton,
    ThumbnailGrid,
    Toast,
    ToggleChip,
)

VIEW_TONES = {"instructor": "instructor", "during": "during", "after": "after"}


class KitGallery(QWidget):
    def __init__(self, theme: ThemeManager) -> None:
        super().__init__()
        self.theme = theme
        self.setWindowTitle("SlideMage UI kit")
        self.resize(900, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self._root = QVBoxLayout(body)
        self._root.setSpacing(16)

        dark = QCheckBox("Dark mode")
        dark.setChecked(theme.dark)
        dark.toggled.connect(self._set_dark)
        self._root.addWidget(dark)

        self._section("Segmented control", self._segmented())
        self._section("Chips", self._chips())
        self._section("Buttons, split button, icon buttons", self._buttons())
        self._section("Form controls", self._controls())
        self._section("Field, thumbnail grid", self._thumbnails())
        self._section("Card", self._card())
        self._section("Palette", self._swatches())
        self._root.addStretch(1)

        self.toast = Toast(self)
        self.toast.action_triggered.connect(lambda key: print("toast action:", key))

    def _set_dark(self, dark: bool) -> None:
        # Deliberately not ThemeManager.set_dark(): that persists the choice
        # in the app's settings file.
        self.theme.dark = dark
        self.theme.apply()

    def _section(self, title: str, content: QWidget) -> None:
        heading = QLabel(title)
        heading.setObjectName(FIELD_LABEL)
        self._root.addWidget(heading)
        self._root.addWidget(content)

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            layout.addWidget(w)
        layout.addStretch(1)
        return row

    def _segmented(self) -> QWidget:
        view = SegmentedControl(
            [("instructor", "Instructor"), ("during", "During course"), ("after", "After course")],
            tones=VIEW_TONES, current="during")
        lang = SegmentedControl([("en", "EN"), ("de", "DE")], mono=True)
        mode = SegmentedControl([("p", "Preview"), ("s", "Split"), ("c", "Source"), ("d", "Details")])
        mode.set_badge("c", 3)   # lint errors in the Source view
        return self._row(view, lang, mode)

    def _chips(self) -> QWidget:
        chips = [Chip("pinned 1-0-0", "neutral", "push_pin"), Chip("course note", "info"),
                 Chip("EN", "muted"), Chip("outdated translation", "warning", "warning"),
                 Chip("2 lint errors", "error", "error"), Chip("reviewed", "ok", "check")]
        return self._row(*chips)

    def _controls(self) -> QWidget:
        line = QLineEdit()
        line.setPlaceholderText("Placeholder")
        filled = QLineEdit("Some text")
        off = QLineEdit("Disabled")
        off.setEnabled(False)
        combo = QComboBox()
        combo.addItems(["SlideMage", "Beamer", "Plain"])
        combo_off = QComboBox()
        combo_off.addItem("Disabled")
        combo_off.setEnabled(False)
        spin = QSpinBox()
        spin.setValue(2)
        checks = [QCheckBox("Checked"), QCheckBox("Unchecked"), QCheckBox("Checked, disabled"),
                  QCheckBox("Disabled")]
        checks[0].setChecked(True)
        checks[2].setChecked(True)
        checks[2].setEnabled(False)
        checks[3].setEnabled(False)
        radios = [QRadioButton("Selected"), QRadioButton("Other"), QRadioButton("Disabled")]
        radios[0].setChecked(True)
        radios[2].setEnabled(False)
        chips = [ToggleChip("Instructor", "instructor"), ToggleChip("During course", "during"),
                 ToggleChip("After course", "after"), ToggleChip("Frozen", "after")]
        for chip in chips[:3]:
            chip.setChecked(True)
        chips[3].setChecked(True)
        chips[3].setEnabled(False)
        text = QPlainTextEdit("A multi-line field,\nwith a second line.")
        text.setFixedHeight(64)
        items = QListWidget()
        items.addItems([f"List item {n}" for n in range(1, 12)])
        items.setFixedHeight(90)
        items.setCurrentRow(1)
        return self._rows(self._row(line, filled, off), self._row(combo, combo_off, spin), self._row(*checks),
                          self._row(*radios), self._row(*chips), text, items)

    @staticmethod
    def _rows(*rows: QWidget) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        for r in rows:
            layout.addWidget(r)
        return column

    def _buttons(self) -> QWidget:
        split = SplitButton("Compile PDF · During")
        menu = PopoverMenu()
        menu.add_header("Compile")
        menu.add_item("i", "Instructor", meta="Ctrl+1", icon="school")
        menu.add_item("d", "During course", meta="Ctrl+2", icon="co_present")
        menu.add_item("a", "After course", meta="Ctrl+3", icon="history_edu")
        menu.add_separator()
        menu.add_item("all", "All except archive", meta="3 decks")
        menu.add_item("x", "Delete build folder", tone="danger")
        menu.add_item("off", "Unavailable", enabled=False)
        split.set_menu(menu)
        menu.triggered.connect(lambda key: self.toast.show_message(f"Menu: {key}", [("undo", "Undo")]))
        more = IconButton("more_vert", "More")
        toast_error = Button("Show error toast", "ghost")
        toast_error.clicked.connect(lambda: self.toast.show_message(
            "Compile failed in 1y8", [("open", "Open in Source")], error=True))
        sheet_button = Button("Open sheet", "secondary")
        sheet_button.clicked.connect(self._open_sheet)
        return self._row(split, more, IconLabel("lock"), Button("Primary", "primary"),
                         Button("Secondary", "secondary"), toast_error, sheet_button)

    def _thumbnails(self) -> QWidget:
        pictures = sorted((FONT_DIR.parent / "frames").glob("*.png"))   # the frame gallery of Add slide
        return Field("Frame", ThumbnailGrid([(p.stem, p.stem, p) for p in pictures]))

    def _card(self) -> QWidget:
        card = Card(raised=True)
        card.layout().addWidget(QLabel("Card content on the surface color."))
        return card

    def _swatches(self) -> QWidget:
        t = self.theme.tokens
        colors = [t.bg, t.surface, t.text, t.line, *(t.view_color(v) for v in VIEWS), *t.steps,
                  t.error, t.warning, t.ok, t.info]
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for color in colors:
            swatch = QLabel()
            swatch.setFixedSize(28, 28)
            swatch.setStyleSheet(f"background-color: {color}; border: 1px solid {t.line}; border-radius: 4px;")
            swatch.setToolTip(color)
            layout.addWidget(swatch)
        layout.addStretch(1)
        return row

    def _open_sheet(self) -> None:
        sheet = ModalSheet("Settings", self)
        general = QWidget()
        QVBoxLayout(general).addWidget(QLineEdit("General settings"))
        models = QWidget()
        QVBoxLayout(models).addWidget(QPlainTextEdit("AI models"))
        sheet.add_tab("General", general)
        sheet.add_tab("AI models", models)
        sheet.add_button("Cancel", role="reject")
        sheet.add_button("Save", kind="primary", role="accept")
        sheet.exec()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    load_fonts()
    theme = ThemeManager()
    theme.dark = "--light" not in sys.argv
    theme.apply()
    gallery = KitGallery(theme)
    gallery.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
