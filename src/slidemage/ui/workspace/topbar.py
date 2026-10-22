# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workspace's top bar (prototype v6): logo, deck switcher, the AI switch (ai_switch.py), "View as",
EN/DE, save status, Preview/Split/Source/Details and Compile, under the window's menu bar (menus.py), which has
every other command. While the Images page is open, a "Close images" button follows Compile (Images itself is in
View and ⌘K).

The bar changes the shared WorkspaceState for the things that are state (deck,
view, language, mode) and reports every other click as a command id through
`command`; the commands (actions.py) and their menus (menus.py) come from the
registry of the window it is given.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout, QWidget

from ...deck_scan import Deck
from ..kit import kit_qss as q
from ..kit.fonts import FONT_DIR
from ..kit.widgets import Button, DropdownButton, IconButton, SegmentedControl, SplitButton
from .ai_switch import AiSwitch
from .menus import VIEW_LABELS, build_compile_menu, build_deck_menu, deck_key
from .state import MODES, UI_LANGUAGES, VIEWS

LOGO_PATH = FONT_DIR.parent / "icon.svg"
# Its dark front card would vanish on the dark theme's bar; this variant has a light front card.
DARK_LOGO_PATH = FONT_DIR.parent / "logo" / "slidemage-mark-dark.svg"
LOGO_SIZE = 32
# The widest the deck switcher gets in each density, its name elided beyond (the full name is its tooltip):
# wide enough in the full bar for names like "t-Uni-Masterdeck-Publishing" (1920 x 1080 shows the full bar;
# at 125 % scaling, 1536 px, the narrow one), and for "slidemage-manual" down to the tight bar; the tiny one
# (1024 px) keeps the room for the other controls.
DECK_MAX_WIDTHS = {"full": 280, "narrow": 220, "tight": 200, "tiny": 170}
DECK_MAX_WIDTH = max(DECK_MAX_WIDTHS.values())
# The narrowest bar each density is for, when its content fits: below 1500 px the labels shorten, below 1320 px
# the AI switch gives up the name of its connection too, and in the narrowest window (1024 px) it is only icons:
# it is the last to shrink.
DENSITIES = (("full", 1500), ("narrow", 1320), ("tight", 0), ("tiny", 0))
# The kit names the view colors "instructor", "during" and "after".
VIEW_TONES = {"instructor": "instructor", "during-course": "during", "after-course": "after"}
SHORT_VIEWS = {"instructor": "Instr.", "during-course": "During", "after-course": "After"}
MODE_LABELS = {mode: mode.capitalize() for mode in MODES}
SHORT_MODES = {"preview": "Prev.", "split": "Split", "source": "Src.", "details": "Info"}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class TopBar(QWidget):
    command = Signal(str)
    mode_clicked = Signal()   # the user clicked Preview / Split / Source / Details (whatever it changed)

    def __init__(self, window, parent: QWidget | None = None) -> None:
        """`window` is the command context: its `state`, `commands` and `compiling`."""
        super().__init__(parent)
        self._window = window
        self._state = state = window.state
        self._decks: list[Deck] = []
        self._compile_menu = None
        self._density = DENSITIES[0][0]
        self._available_width: int | None = None
        self._updating_density = False
        # Let the parent shrink before resizeEvent chooses a smaller density.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
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

        self._row_layout = layout = QHBoxLayout(row)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)

        def add(widget: QWidget) -> None:
            # centred in the bar, not stretched to its full height
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

        self._left_column = IconButton("first_page")
        self._left_column.setCheckable(True)
        self._left_column.clicked.connect(lambda: self.command.emit("column:left"))
        add(self._left_column)

        self._logo = QLabel()
        self.set_dark(False)
        add(self._logo)

        self._deck_button = DropdownButton(q.TOPBAR_DECK)
        self._deck_button.clicked.connect(self.open_deck_menu)
        add(self._deck_button)

        self.ai_switch = AiSwitch(state)
        add(self.ai_switch)

        self._view_as = QLabel("View as")
        self._view_as.setObjectName(q.TOPBAR_LABEL)
        add(self._view_as)
        self._views = SegmentedControl(
            [(view, VIEW_LABELS[view]) for view in VIEWS], current=state.view, tones=VIEW_TONES, roving=True)
        self._views.changed.connect(state.set_view)
        add(self._views)
        self._languages = SegmentedControl(
            [(lang, lang) for lang in UI_LANGUAGES], current=state.language, mono=True, roving=True)
        self._languages.changed.connect(state.set_language)
        add(self._languages)

        layout.addStretch()
        self._save = QLabel("Saved")
        self._save.setObjectName(q.TOPBAR_SAVE)
        add(self._save)

        self._modes = SegmentedControl([(mode, mode.capitalize()) for mode in MODES], current=state.mode, roving=True)
        self._modes.changed.connect(state.set_mode)
        self._modes.changed.connect(lambda _mode: self.mode_clicked.emit())
        add(self._modes)

        self._compile = SplitButton("")
        self._compile.clicked.connect(lambda: self.command.emit(f"compile:{state.view}"))
        add(self._compile)
        self._images = Button("Close images", "primary")
        self._images.clicked.connect(lambda: self.command.emit("images"))
        self._images.hide()
        add(self._images)
        self._right_column = IconButton("last_page")
        self._right_column.setCheckable(True)
        self._right_column.clicked.connect(lambda: self.command.emit("column:right"))
        add(self._right_column)
        self.refresh_column_toggles()
        self._set_tab_order()

        state.deck_changed.connect(self._on_deck_changed)
        state.view_changed.connect(self._on_view_changed)
        state.selection_changed.connect(lambda _ids: self.refresh_compile_menu())
        state.focused_slide_changed.connect(lambda _id: self.refresh_compile_menu())
        state.language_changed.connect(self._languages.set_current)
        state.mode_changed.connect(self._modes.set_current)
        state.lint_errors_changed.connect(self._on_lint_errors_changed)
        state.dirty_changed.connect(self._on_dirty_changed)
        self._on_deck_changed(state.deck)
        self._on_view_changed(state.view)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._available_width = event.size().width()
        self._update_density()

    def _set_tab_order(self) -> None:
        """Tab and Shift+Tab follow the bar left to right, then go on into the slide list, the centre and the side
        panels (the window adds them to its splitter in that order). The widgets are chained once, all of them: a
        hidden one ("Close images") and a segment that is not selected (roving) are skipped by visibility and focus
        policy, whatever the density."""
        switch = self.ai_switch
        stops = [self._left_column, self._deck_button, *switch.segments.buttons(), switch.caret,
                 *self._views.buttons(), *self._languages.buttons(), *self._modes.buttons(), *self._compile.buttons(),
                 self._images, self._right_column]
        for before, after in zip(stops, stops[1:]):
            QWidget.setTabOrder(before, after)

    def _update_density(self) -> None:
        if self._available_width is None or self._updating_density:
            return
        self._updating_density = True
        try:
            # Start at the preferred density, then measure the actual content (including badges).
            for density, preferred_width in DENSITIES:
                if self._available_width < preferred_width:
                    continue
                self._apply_density(density)
                if self.minimumSizeHint().width() <= self._available_width:
                    break
        finally:
            self._updating_density = False

    def _apply_density(self, density: str) -> None:
        self._density = density
        full = density == "full"
        tight = density in ("tight", "tiny")
        tiny = density == "tiny"
        margin = 8 if tiny else 12 if tight else 24
        self._row_layout.setContentsMargins(margin, 0, margin, 0)
        self._row_layout.setSpacing(5 if tiny else 8 if tight else 14)
        self._view_as.setVisible(full)
        self._views.setToolTip("View as")
        self._views.set_labels(VIEW_LABELS if full else SHORT_VIEWS, tooltips=VIEW_LABELS, compact=not full)
        self._languages.set_labels({lang: lang for lang in UI_LANGUAGES}, compact=not full)
        self._modes.set_labels(MODE_LABELS if full else SHORT_MODES, tooltips=MODE_LABELS, compact=not full)
        self.ai_switch.set_shrink({"tight": 1, "tiny": 2}.get(density, 0))
        self._update_deck_label()
        self._update_save_label()
        self._update_compile_label()
        # Flush nested layout minimums before measuring; Qt otherwise updates them next event loop.
        for widget in (self._deck_button, self.ai_switch.segments, self.ai_switch, self._views, self._languages,
                       self._modes, self._compile):
            widget.layout().invalidate()
            widget.layout().activate()
        self._row_layout.invalidate()
        self._row_layout.activate()
        self.layout().invalidate()

    # -- what the window tells the bar -------------------------------------

    def refresh_column_toggles(self) -> None:
        for side, button, hide_icon, show_icon in (
                ("left", self._left_column, "first_page", "last_page"),
                ("right", self._right_column, "last_page", "first_page")):
            hidden = getattr(self._window, side + "_column_hidden")
            command = self._window.commands[f"column:{side}"]
            button.setChecked(not hidden)
            button.set_active(not hidden)
            button.set_icon(show_icon if hidden else hide_icon)
            button.setToolTip(f"{command.title(self._window)} ({command.info(self._window)})")

    def set_decks(self, decks: list[Deck]) -> None:
        self._decks = decks

    def set_dark(self, dark: bool) -> None:
        self._logo.setPixmap(QIcon(str(DARK_LOGO_PATH if dark else LOGO_PATH)).pixmap(LOGO_SIZE, LOGO_SIZE))

    def set_images_open(self, is_open: bool) -> None:
        self._images.setVisible(is_open)
        self._update_density()

    # -- reacting to the state ---------------------------------------------

    def _on_deck_changed(self, deck: Deck | None) -> None:
        self._update_deck_label()
        self.refresh_compile_menu()
        self._update_compile_label()
        self._update_density()

    def _update_deck_label(self) -> None:
        deck = self._state.deck
        name = deck.name if deck is not None else "No deck"
        self._deck_button.set_text(name, max_width=DECK_MAX_WIDTHS[self._density])
        self._deck_button.setToolTip(name)

    def _on_dirty_changed(self, dirty: bool) -> None:
        self._update_save_label()
        self._update_density()

    def _update_save_label(self) -> None:
        text = "Unsaved changes" if self._state.dirty else "Saved"
        self._save.setText(text if self._density == "full" else "●" if self._density == "tiny" else text.split()[0])
        self._save.setToolTip(text)

    def _on_lint_errors_changed(self, count: int) -> None:
        self._modes.set_badge("source", count)
        self._update_density()

    def _on_view_changed(self, view: str) -> None:
        self._views.set_current(view)
        self._strip.setProperty("tone", VIEW_TONES[view])
        _repolish(self._strip)
        self._update_compile_label()
        self._update_density()

    def _update_compile_label(self) -> None:
        deck = self._state.deck
        label = "Compile PDF"
        if deck is not None and deck.supports_version:
            label += " · " + VIEW_LABELS[self._state.view].replace(" course", "")
        self._compile.set_text(label if self._density == "full" else "Compile")
        versioned = deck is not None and deck.supports_version
        self._compile.setToolTip("Compile PDF" + (" · " + VIEW_LABELS[self._state.view] if versioned else ""))
        self._compile.setEnabled(deck is not None)

    def refresh_compile_menu(self) -> None:
        """Build the caret menu again (a compile run began or ended, or the deck or selection changed)."""
        if self._compile_menu is not None:
            self._compile_menu.deleteLater()
        self._compile_menu = build_compile_menu(self, self._window)
        self._compile_menu.triggered.connect(self.command)
        self._compile.set_menu(self._compile_menu)

    # -- menus -------------------------------------------------------------

    def open_deck_menu(self) -> None:
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
