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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .fonts import load_fonts
from .theme import ThemeManager
from .tokens import VIEWS
from .widgets import (
    Button,
    Card,
    Chip,
    IconButton,
    IconLabel,
    ModalSheet,
    PopoverMenu,
    SegmentedControl,
    SplitButton,
    Toast,
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
        heading.setObjectName("mutedLabel")
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
