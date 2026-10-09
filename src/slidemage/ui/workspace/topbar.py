"""The workspace's top bar (prototype v3): logo, deck switcher, "View as",
EN/DE, save status, Preview/Split/Source/Details, Compile, Images and ⋮.

The bar changes the shared WorkspaceState for the things that are state (deck,
view, language, mode) and reports every other click as a command key through
`command` (menus.py lists the keys); the window decides what a command does.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...deck_scan import Deck
from ..kit import kit_qss as q
from ..kit.fonts import FONT_DIR
from ..kit.widgets import Button, DropdownButton, IconButton, SegmentedControl, SplitButton
from .menus import VIEW_LABELS, build_compile_menu, build_deck_menu, build_more_menu, deck_key
from .state import MODES, UI_LANGUAGES, VIEWS, WorkspaceState

LOGO_PATH = FONT_DIR.parent / "icon.svg"
LOGO_SIZE = 32
# The kit names the view colors "instructor", "during" and "after".
VIEW_TONES = {"instructor": "instructor", "during-course": "during", "after-course": "after"}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class TopBar(QWidget):
    command = Signal(str)

    def __init__(self, state: WorkspaceState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._decks: list[Deck] = []
        self._compiling = False
        self._compile_menu = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        row = QFrame()
        row.setObjectName(q.TOPBAR)
        row.setFixedHeight(60)
        outer.addWidget(row)
        self._strip = QFrame()
        self._strip.setObjectName(q.TOPBAR_STRIP)
        self._strip.setFixedHeight(3)
        outer.addWidget(self._strip)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)

        def add(widget: QWidget) -> None:
            # centred in the bar, not stretched to its full height
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

        logo = QLabel()
        logo.setPixmap(QIcon(str(LOGO_PATH)).pixmap(LOGO_SIZE, LOGO_SIZE))
        add(logo)

        self._deck_button = DropdownButton(q.TOPBAR_DECK)
        self._deck_button.clicked.connect(self._open_deck_menu)
        add(self._deck_button)

        view_as = QLabel("View as")
        view_as.setObjectName(q.TOPBAR_LABEL)
        add(view_as)
        self._views = SegmentedControl(
            [(view, VIEW_LABELS[view]) for view in VIEWS], current=state.view, tones=VIEW_TONES)
        self._views.changed.connect(state.set_view)
        add(self._views)
        self._languages = SegmentedControl(
            [(lang, lang) for lang in UI_LANGUAGES], current=state.language, mono=True)
        self._languages.changed.connect(state.set_language)
        add(self._languages)

        layout.addStretch()
        self._save = QLabel("Saved")
        self._save.setObjectName(q.TOPBAR_SAVE)
        add(self._save)

        self._modes = SegmentedControl([(mode, mode.capitalize()) for mode in MODES], current=state.mode)
        self._modes.changed.connect(state.set_mode)
        add(self._modes)

        self._compile = SplitButton("")
        self._compile.clicked.connect(lambda: self.command.emit(f"compile:{state.view}"))
        add(self._compile)
        self._images = Button("Images", "secondary")
        self._images.clicked.connect(lambda: self.command.emit("images"))
        add(self._images)
        self._more = IconButton("more_vert", "More")
        self._more.clicked.connect(self._open_more_menu)
        add(self._more)

        state.deck_changed.connect(self._on_deck_changed)
        state.view_changed.connect(self._on_view_changed)
        state.language_changed.connect(self._languages.set_current)
        state.mode_changed.connect(self._modes.set_current)
        state.lint_errors_changed.connect(lambda count: self._modes.set_badge("source", count))
        state.dirty_changed.connect(lambda dirty: self._save.setText("Unsaved changes" if dirty else "Saved"))
        self._on_deck_changed(state.deck)
        self._on_view_changed(state.view)

    # -- what the window tells the bar -------------------------------------

    def set_decks(self, decks: list[Deck]) -> None:
        self._decks = decks

    def set_images_open(self, is_open: bool) -> None:
        self._images.setText("Close images" if is_open else "Images")
        self._images.setProperty("kind", "primary" if is_open else "secondary")
        _repolish(self._images)

    def set_compiling(self, compiling: bool) -> None:
        self._compiling = compiling
        self._rebuild_compile_menu()

    # -- reacting to the state ---------------------------------------------

    def _on_deck_changed(self, deck: Deck | None) -> None:
        self._deck_button.set_text(deck.name if deck is not None else "No deck")
        self._rebuild_compile_menu()
        self._update_compile_label()

    def _on_view_changed(self, view: str) -> None:
        self._views.set_current(view)
        self._strip.setProperty("tone", VIEW_TONES[view])
        _repolish(self._strip)
        self._update_compile_label()

    def _update_compile_label(self) -> None:
        deck = self._state.deck
        label = "Compile PDF"
        if deck is not None and deck.supports_version:
            label += " · " + VIEW_LABELS[self._state.view].replace(" course", "")
        self._compile.set_text(label)
        self._compile.setEnabled(deck is not None)

    def _rebuild_compile_menu(self) -> None:
        if self._compile_menu is not None:
            self._compile_menu.deleteLater()
        self._compile_menu = build_compile_menu(self, self._state.deck, self._compiling)
        self._compile_menu.triggered.connect(self.command)
        self._compile.set_menu(self._compile_menu)

    # -- menus -------------------------------------------------------------

    def _open_deck_menu(self) -> None:
        menu = build_deck_menu(self, self._decks, self._state.deck)
        menu.triggered.connect(self._on_deck_picked)
        menu.closed.connect(lambda: self._deck_button.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self._deck_button.set_active(True)
        menu.popup_below(self._deck_button)

    def _on_deck_picked(self, key: str) -> None:
        for deck in self._decks:
            if deck_key(deck) == key:
                self._state.set_deck(deck)
                return

    def _open_more_menu(self) -> None:
        menu = build_more_menu(self, self._state.deck)
        menu.triggered.connect(self.command)
        menu.closed.connect(lambda: self._more.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self._more.set_active(True)
        menu.popup_below(self._more, align_right=True)
