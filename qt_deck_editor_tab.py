"""Phase 5 of the PySide6 migration (see PYSIDE6_MIGRATION.md): the deck
slide-list editor tab -- ports deck_editor_tab.py's DeckEditorTab onto Qt
widgets. deck_editor.py (parse_slide_calls/change_slide_call_variant/
remove_slide_call/restore_deck_text/available_versions/BASE_MACROS/
SlideCall) is reused completely unchanged -- confirmed Tkinter-independent
during planning.

Source-editing (the "Source" button), +before/+after (which open the
add-slide dialog), and Render need slide_source_tab.py's and
add_slide_dialog.py's own Qt ports (Phases 6-7) -- wired here as stubs that
log rather than act, same pattern as qt_gui.py's own deck-open stub from
Phase 4.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import deck_editor, slide_language, slide_snapshot
from .deck_editor import SlideCall
from .deck_scan import Deck
from .qt_slide_preview_popup import SlidePreviewPopup
from .qt_theme import CLOSE_BUTTON, LINK_LABEL, WARNING_LABEL
from .slide_ids import SLIDES_DIR

VERSIONS = ["instructor", "during-course", "after-course"]
VERSION_LABELS = {
    "instructor": "Instructor",
    "during-course": "During-course",
    "after-course": "After-course",
}


class NoScrollComboBox(QComboBox):
    """A QComboBox that never reacts to the mouse wheel (2026-09-23, direct
    instruction: "I want the scroll wheel to only scroll through the deck,
    everything else is error prone") -- both dropdowns in this tab (the
    toolbar's chapter-navigation combo and each row's own variant combo)
    sit directly in the path of a scroll gesture aimed at the deck's own
    QScrollArea, and Qt's default QComboBox wheel handling quietly changes
    the current selection instead of scrolling past it. Ignoring the event
    here (rather than accepting it as a no-op) lets it propagate to the
    enclosing scroll area, so the wheel keeps scrolling the deck exactly as
    if the cursor weren't over a combo box at all."""

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.ignore()


def _language_badge_html(id_slug: str) -> str:
    """Rich-text suffix for a slide row/card's own id label (2026-08-24) --
    appended directly onto the existing label rather than added as its own
    grid column, since none of this grid's fixed columns (0-8, see
    _build_row) are free. Empty for a legacy, not-yet-migrated slide (no
    noise added to the other ~665). Both this slide's own language *and* a
    cross-referenced translation in another language show together,
    highlighted, when both exist -- direct instruction, so a linked
    translation is obvious at a glance rather than only discoverable by
    opening the header comment."""
    own = slide_language.own_language(id_slug)
    if own is None:
        return ""
    path = SLIDES_DIR / f"{id_slug}-current.tex"
    cross_lang = slide_language.cross_referenced_language(id_slug, path)
    if cross_lang is not None and cross_lang != own:
        return f' <span style="font-weight:bold;">[{own} + {cross_lang}]</span>'
    return f' <span style="color:gray;">[{own}]</span>'


class DeckEditorTab(QWidget):
    # Whole-file text snapshots kept per undo step -- see deck_editor_tab.py's
    # own module docstring for the full undo-design rationale (ported
    # verbatim, only the widget layer differs).
    _UNDO_LIMIT = 20

    def __init__(self, app, deck: Deck) -> None:
        super().__init__()
        self.app = app
        self.deck = deck
        # Which institution this deck's own preamble selects (Graz,
        # Innsbruck, MCI) -- computed once, not per row, since it can't
        # change without the whole deck's own preamble changing. Every
        # preview/hover for this deck's slides is captured/looked up under
        # this template, never some other one, so it always shows how a
        # slide *actually* renders inside this specific deck.
        self._template = slide_snapshot.detect_template(deck.preamble_text)
        self._undo_stack: list[str] = []
        self._trailing_stretch_row: Optional[int] = None
        # id_slug -> its row's link label, so a Preview popup's "Render
        # now" can refresh that row's hover tooltip afterward without
        # re-scanning the grid.
        self._id_labels: dict[str, QLabel] = {}
        # One (checkbox, call) per row of the List/Thumbnail view, rebuilt
        # with the rows -- what the toolbar's bulk "Remove selected" button
        # reads. Selection deliberately doesn't survive a rebuild: after any
        # edit the calls' offsets and positions have all moved.
        self._row_checkboxes: list[tuple[QCheckBox, SlideCall]] = []
        # Chapter-header widgets, keyed by that header's occurrence index
        # (0, 1, 2, ... in encounter order) rather than its title text --
        # two chapters that happen to share an exact title would otherwise
        # collide on the same dict key. The chapter combo's own item index
        # is exactly this same occurrence index, by construction (see
        # _populate_chapter_combo), so no separate title<->index mapping
        # is needed. Two separate dicts since List/Thumbnail and Grid are
        # two separate widget trees (see the toolbar radios below), each
        # with their own header row for the same chapter.
        self._chapter_headers: dict[int, QLabel] = {}
        self._grid_chapter_headers: dict[int, QLabel] = {}
        # Thumbnail view isn't a separate widget tree from List -- it's the
        # same row grid with one extra image row per slide, so toggling it
        # just flips this flag and rebuilds. Grid view (below) *is* a
        # separate tree, switched via self.view_stack instead.
        self._show_thumbnails = False

        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._on_refresh)
        toolbar.addWidget(refresh_button)

        source_button = QPushButton("Source")
        source_button.clicked.connect(self._on_source)
        toolbar.addWidget(source_button)

        transcript_button = QPushButton("Transcript")
        transcript_button.clicked.connect(self._on_transcript)
        toolbar.addWidget(transcript_button)

        self.undo_button = QPushButton("Undo")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._on_undo)
        toolbar.addWidget(self.undo_button)

        # Only shown while two or more rows are ticked (see
        # _update_bulk_remove_button).
        self.bulk_remove_button = QPushButton("Remove selected")
        self.bulk_remove_button.setVisible(False)
        self.bulk_remove_button.clicked.connect(self._on_remove_selected)
        toolbar.addWidget(self.bulk_remove_button)

        # Shown and hidden together with "Remove selected".
        self.clear_selection_button = QPushButton("Clear selection")
        self.clear_selection_button.setVisible(False)
        self.clear_selection_button.clicked.connect(self._on_clear_selection)
        toolbar.addWidget(self.clear_selection_button)

        toolbar.addWidget(QLabel("Quick navigation:"))
        self.chapter_combo = NoScrollComboBox()
        self.chapter_combo.setToolTip("Jump the view to a chapter.")
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        toolbar.addWidget(self.chapter_combo)

        close_button = QPushButton("Close")
        close_button.setObjectName(CLOSE_BUTTON)
        close_button.clicked.connect(self._on_close)
        toolbar.addWidget(close_button)

        toolbar.addStretch()

        toolbar.addWidget(QLabel("View:"))

        self.list_view_radio = QRadioButton("List")
        self.thumbnail_view_radio = QRadioButton("Thumbnail")
        self.grid_view_radio = QRadioButton("Grid")
        self.list_view_radio.setChecked(True)
        self.thumbnail_view_radio.setToolTip(
            "Show a rendered thumbnail below each slide's id, in addition "
            "to the usual row controls."
        )
        self.grid_view_radio.setToolTip(
            "Browse this deck as a grid of rendered thumbnail cards, "
            "grouped by chapter. Click a card to open that slide -- no "
            "row controls here, this is for a quick visual overview."
        )
        # QButtonGroup (exclusive by default): only one of List/Thumbnail/
        # Grid can ever be selected. Unlike a 2-way toggle, a 3-way group
        # can't tell which option became active just from "the one that
        # turned True" -- request.sender()/isChecked() on all three inside
        # one shared handler is simpler than three separate slots, so every
        # radio connects to the same _on_view_toggled. Parented to self
        # (not left anonymous) so it isn't garbage-collected once __init__
        # returns.
        self._view_button_group = QButtonGroup(self)
        self._view_button_group.addButton(self.list_view_radio)
        self._view_button_group.addButton(self.thumbnail_view_radio)
        self._view_button_group.addButton(self.grid_view_radio)
        self.list_view_radio.toggled.connect(self._on_view_toggled)
        self.thumbnail_view_radio.toggled.connect(self._on_view_toggled)
        self.grid_view_radio.toggled.connect(self._on_view_toggled)
        toolbar.addWidget(self.list_view_radio)
        toolbar.addWidget(self.thumbnail_view_radio)
        toolbar.addWidget(self.grid_view_radio)

        outer.addLayout(toolbar)

        # List and Thumbnail share one widget tree (see _show_thumbnails
        # above); Grid is a genuinely separate one (a fixed-column card
        # grid, no row controls) reinstated by request after being folded
        # into Thumbnail and found to not cover the same use case -- so
        # List/Thumbnail is index 0 here and Grid is index 1.
        self.view_stack = QStackedWidget()
        outer.addWidget(self.view_stack, stretch=1)

        # Both scrollbar directions: vertical since a deck's slide list can
        # run well past 100 rows, horizontal since one row's own content
        # needs ~1200px by default (see gui.py's own note) and would
        # otherwise get clipped with no way to reach it.
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view_stack.addWidget(self.list_scroll)  # index 0

        self.inner = QWidget()
        self.inner.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.list_scroll.setWidget(self.inner)
        self.grid = QGridLayout(self.inner)
        self.grid.setVerticalSpacing(2)

        # Grid view: a fixed-column card grid, only vertical scrolling
        # (cards reflow within whatever width the tab has, rather than
        # spilling sideways the way the list view's row grid does).
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view_stack.addWidget(self.card_scroll)  # index 1

        self.card_inner = QWidget()
        self.card_scroll.setWidget(self.card_inner)
        self.card_grid = QGridLayout(self.card_inner)
        self.card_grid.setSpacing(8)

        self._build_rows()

    # -- public API used by qt_gui.py ------------------------------------------

    def reload(self, deck: Deck) -> None:
        self.deck = deck
        self._template = slide_snapshot.detect_template(deck.preamble_text)
        self._build_rows()

    # -- toolbar actions --------------------------------------------------------

    def _on_refresh(self) -> None:
        """Re-reads this deck from disk -- every row action here already
        rebuilds the tab on its own (see after_deck_edit), so this is only
        for picking up a change made outside the app (e.g. hand-editing the
        deck's own .tex file in TeXstudio) without closing and reopening
        the tab."""
        fresh_deck = self.app.resync_deck(self.deck.path)
        if fresh_deck is None:
            QMessageBox.critical(
                self,
                "Refresh failed",
                f"{self.deck.name} could not be found -- it may have been "
                "archived or removed since this tab was opened.",
            )
            return
        self.reload(fresh_deck)
        self._undo_stack.clear()
        self._update_undo_button_state()
        self.app.log(f"Refreshed {self.deck.name} (slides)")

    def _on_source(self) -> None:
        self.app.open_deck_source_editor(self.deck, return_to=self)

    def _on_transcript(self) -> None:
        self.app.prompt_deck_transcript_version(self.deck)

    def record_undo_snapshot(self, previous_text: str) -> None:
        self._undo_stack.append(previous_text)
        del self._undo_stack[: -self._UNDO_LIMIT]
        self._update_undo_button_state()

    def _update_undo_button_state(self) -> None:
        self.undo_button.setEnabled(bool(self._undo_stack))

    def _on_undo(self) -> None:
        if not self._undo_stack:
            return
        previous_text = self._undo_stack.pop()
        try:
            deck_editor.restore_deck_text(self.deck.path, self.deck.text, previous_text)
        except deck_editor.StaleFileError as exc:
            self._undo_stack.append(previous_text)
            QMessageBox.critical(self, "Undo failed", str(exc))
            return
        self._update_undo_button_state()
        self.app.after_deck_edit(self.deck.path, f"Undid last change to {self.deck.name}")

    def _on_close(self) -> None:
        self.app.close_deck_editor_tab(self)

    def _on_view_toggled(self, checked: bool) -> None:
        if not checked:
            return  # ignore the "turned off" side of the exclusive group
        self._show_thumbnails = self.thumbnail_view_radio.isChecked()
        self.view_stack.setCurrentIndex(1 if self.grid_view_radio.isChecked() else 0)
        self._build_rows()

    def _on_chapter_selected(self, index: int) -> None:
        # Scrolls both views (not just the currently visible one), so
        # whichever one the user switches to afterward is already lined up.
        # QScrollArea.ensureWidgetVisible only guarantees a widget ends up
        # *somewhere* in the viewport -- depending on which direction the
        # scroll has to move, that can leave the heading sitting at the
        # bottom edge rather than the top (2026-08-15, direct instruction:
        # a chapter jump should always land the heading at the top).
        # Computing the header's own y position relative to the scrolled
        # widget and setting the vertical scrollbar to exactly that value
        # pins its top edge to the top of the viewport instead.
        for headers, scroll, inner in (
            (self._chapter_headers, self.list_scroll, self.inner),
            (self._grid_chapter_headers, self.card_scroll, self.card_inner),
        ):
            header = headers.get(index)
            if header is not None:
                scroll.verticalScrollBar().setValue(header.mapTo(inner, QPoint(0, 0)).y())

    # -- row construction -----------------------------------------------------

    @staticmethod
    def _chapter_occurrence_labels(calls: list[SlideCall]) -> list[str]:
        """One label per chapter-header row _build_rows/_build_card_grid
        would insert, in encounter order -- the same de-duplication
        (consecutive identical titles collapse into one header) both of
        those loops use, kept in sync with them since all three walk the
        identical `calls` sequence the same way."""
        labels: list[str] = []
        last_chapter_title = object()
        for call in calls:
            title = call.chapter.title if call.chapter is not None else None
            if title != last_chapter_title:
                last_chapter_title = title
                labels.append(title if title is not None else "(before first chapter)")
        return labels

    def _populate_chapter_combo(self, calls: list[SlideCall]) -> None:
        # Blocked rather than left to fire: repopulating always resets to
        # index 0, and letting that trigger _on_chapter_selected would
        # force-scroll back to the top on every single edit (every row
        # action rebuilds via after_deck_edit -> reload -> _build_rows),
        # discarding wherever the user was actually looking.
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        self.chapter_combo.addItems(self._chapter_occurrence_labels(calls))
        self.chapter_combo.blockSignals(False)

    def _build_rows(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._id_labels = {}
        self._chapter_headers = {}
        self._row_checkboxes = []
        self._update_bulk_remove_button()

        # QGridLayout's row-stretch factors are layout state, not tied to
        # the widgets just cleared above -- a stale stretch=1 left on a
        # previous build's trailing row (see the bottom of this method)
        # doesn't get reset just because that row's own widgets are gone.
        # After adding/removing slides shifts row indices, that stale row
        # can land on a real header/content row instead of past the end of
        # the deck, making *that* row balloon to absorb leftover space
        # (confirmed directly: "+ before" twice in a row left two rows
        # both stretched, one of them mid-deck). Clear it before rebuilding.
        if self._trailing_stretch_row is not None:
            self.grid.setRowStretch(self._trailing_stretch_row, 0)
            self._trailing_stretch_row = None

        calls = deck_editor.parse_slide_calls(self.deck)
        self._build_card_grid(calls)
        self._populate_chapter_combo(calls)
        if not calls:
            label = QLabel(
                "This deck has no \\slide{}-family calls of its own "
                "(e.g. a wrapper deck that \\input{}s a shared slide list)."
            )
            label.setObjectName("mutedLabel")
            self.grid.addWidget(label, 0, 0)
            return

        row_index = 0
        last_chapter_title = object()  # sentinel, never equal to a real title or None
        chapter_occurrence = 0
        for position, call in enumerate(calls, start=1):
            title = call.chapter.title if call.chapter is not None else None
            if title != last_chapter_title:
                last_chapter_title = title
                header_text = title if title is not None else "(before first chapter)"
                header_label = QLabel(header_text)
                header_label.setStyleSheet("font-weight: bold;")
                self.grid.addWidget(header_label, row_index, 0, 1, 10)
                self._chapter_headers[chapter_occurrence] = header_label
                chapter_occurrence += 1
                row_index += 1
            self._build_row(row_index, position, call)
            row_index += 1
            if self._show_thumbnails:
                self._build_thumbnail_row(row_index, call)
                row_index += 1

        # Without this, QGridLayout hands leftover vertical space (the
        # scroll area's viewport is usually taller than the row content)
        # to whichever rows have no maximum-size cap -- a bare QLabel's
        # maximumSize is unbounded, unlike the button/combo rows' fixed
        # vertical size policy, so *only* the chapter-header rows would
        # stretch to fill the gap, one per header, producing wildly uneven
        # spacing (confirmed via screenshot: tight between two consecutive
        # slide rows, ballooned around every header). An empty trailing row
        # with all the stretch absorbs that leftover space instead, so
        # every real content row just keeps its natural size.
        self.grid.setRowStretch(row_index, 1)
        self._trailing_stretch_row = row_index

    def _build_row(self, row_index: int, position: int, call: SlideCall) -> None:
        # Checkbox + slide number share column 0's cell (rather than adding
        # a column and shifting every other one) -- ticking two or more
        # rows reveals the toolbar's bulk "Remove selected" button.
        number_cell = QWidget()
        number_layout = QHBoxLayout(number_cell)
        number_layout.setContentsMargins(0, 0, 0, 0)
        select_box = QCheckBox()
        if call.editable:
            select_box.setToolTip("Select for bulk removal")
            select_box.toggled.connect(self._update_bulk_remove_button)
            self._row_checkboxes.append((select_box, call))
        else:
            select_box.setEnabled(False)
            select_box.setToolTip(f"Can't be removed here -- {call.readonly_reason}")
        number_layout.addWidget(select_box)
        number_layout.addWidget(QLabel(str(position)))
        self.grid.addWidget(number_cell, row_index, 0)

        link = QLabel(call.id_slug + _language_badge_html(call.id_slug))
        link.setObjectName(LINK_LABEL)
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.mousePressEvent = (  # noqa: E731
            lambda event, c=call: self.app.open_slide_editor(
                SLIDES_DIR / c.source_filename, return_to=self
            )
        )
        self._set_preview_tooltip(link, call.id_slug)
        self._id_labels[call.id_slug] = link
        self.grid.addWidget(link, row_index, 1)

        before_button = QPushButton("+ before")
        before_button.clicked.connect(lambda: self._on_insert(call, before=True))
        self.grid.addWidget(before_button, row_index, 5)

        after_button = QPushButton("+ after")
        after_button.clicked.connect(lambda: self._on_insert(call, before=False))
        self.grid.addWidget(after_button, row_index, 6)

        preview_button = QPushButton("Preview")
        preview_button.clicked.connect(lambda: self._on_preview(call, position))
        self.grid.addWidget(preview_button, row_index, 8)

        # Opens the Images tab on this slide (2026-09-19, direct
        # instruction) -- before the read-only early return below, since
        # jumping to a slide's images has nothing to do with whether its
        # \slide{} call itself can be edited here.
        images_button = QPushButton("Images")
        images_button.clicked.connect(
            lambda: self.app.open_images_for_slide(call.id_slug))
        self.grid.addWidget(images_button, row_index, 9)

        if not call.editable:
            label = QLabel(f"read-only: {call.readonly_reason}")
            label.setObjectName(WARNING_LABEL)
            self.grid.addWidget(label, row_index, 2, 1, 3)
            return

        versions = deck_editor.available_versions(call.id_slug)
        options, current_index = self._variant_options(call, versions)
        initial_label = options[current_index]
        combo = NoScrollComboBox()
        combo.addItems(options)
        combo.setCurrentIndex(current_index)
        self.grid.addWidget(combo, row_index, 2)

        cond_frame = QWidget()
        cond_layout = QHBoxLayout(cond_frame)
        cond_layout.setContentsMargins(0, 0, 0, 0)
        cond_vars: dict[str, QCheckBox] = {}
        initial_cond_values: dict[str, bool] = {}
        for v in VERSIONS:
            checked = call.conditions is not None and v in call.conditions
            cb = QCheckBox(VERSION_LABELS[v][:1])
            cb.setChecked(checked)
            cond_layout.addWidget(cb)
            cond_vars[v] = cb
            initial_cond_values[v] = checked
        self.grid.addWidget(cond_frame, row_index, 3)

        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(lambda: self._on_apply(call, combo, cond_vars))
        self.grid.addWidget(apply_button, row_index, 4)

        def sync_row_state() -> None:
            # The I/D/A condition checkboxes only mean anything for
            # \conditionalslide -- shown only once the dropdown actually
            # selects it. Apply only matters once something's pending.
            macro, _ = self._parse_option(combo.currentText())
            conditional = macro == "conditionalslide"
            cond_frame.setVisible(conditional)

            dirty = combo.currentText() != initial_label
            if conditional:
                dirty = dirty or any(
                    cond_vars[v].isChecked() != initial_cond_values[v] for v in VERSIONS
                )
            apply_button.setVisible(dirty)

        combo.currentTextChanged.connect(lambda _: sync_row_state())
        for cb in cond_vars.values():
            cb.toggled.connect(sync_row_state)
        sync_row_state()

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(lambda: self._on_remove(call))
        self.grid.addWidget(remove_button, row_index, 7)

    # -- thumbnail view ---------------------------------------------------------

    def _build_thumbnail_row(self, row_index: int, call: SlideCall) -> None:
        """Thumbnail view isn't a separate layout -- it's the same row grid
        with this one extra row inserted right under a slide's normal
        control row (see _build_rows), holding just the cached thumbnail in
        the id link's own column (1). Every other control (variant, remove,
        +before/+after, Preview) stays exactly where list view puts it, on
        the row above; this row only ever holds the image."""
        thumb_w, thumb_h = slide_snapshot.THUMB_SIZE
        image_label = QLabel()
        image_label.setFixedSize(thumb_w, thumb_h)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        png_path = slide_snapshot.snapshot_path(
            slide_snapshot.bare_id(call.id_slug), self._template, slide_snapshot.THUMB_SIZE)
        pixmap = QPixmap(str(png_path)) if png_path.is_file() else QPixmap()
        if not pixmap.isNull():
            image_label.setPixmap(pixmap)
            # Fixed white, not theme-following -- a slide's own background
            # is white regardless of the app's dark/light mode.
            image_label.setStyleSheet("background-color: #ffffff;")
        else:
            image_label.setText("<i>no preview yet</i>")
            image_label.setObjectName("mutedLabel")
            image_label.setStyleSheet("border: 1px solid palette(mid);")
        image_label.mousePressEvent = (  # noqa: E731
            lambda event, c=call: self.app.open_slide_editor(
                SLIDES_DIR / c.source_filename, return_to=self
            )
        )
        self.grid.addWidget(image_label, row_index, 1)

    # -- grid view ---------------------------------------------------------

    # Fixed column count rather than a reflow-on-resize layout (Qt has no
    # built-in flow layout, and writing a custom QLayout subclass felt like
    # more than this needed) -- cards wrap to a new row automatically as
    # more are added, just not as the window itself is resized.
    _GRID_COLUMNS = 4

    def _build_card_grid(self, calls: list[SlideCall]) -> None:
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._grid_chapter_headers = {}

        if not calls:
            label = QLabel(
                "This deck has no \\slide{}-family calls of its own.")
            label.setObjectName("mutedLabel")
            self.card_grid.addWidget(label, 0, 0)
            return

        row_index = 0
        col_index = 0
        last_chapter_title = object()
        chapter_occurrence = 0
        for position, call in enumerate(calls, start=1):
            title = call.chapter.title if call.chapter is not None else None
            if title != last_chapter_title:
                last_chapter_title = title
                if col_index != 0:
                    row_index += 1
                    col_index = 0
                header_text = title if title is not None else "(before first chapter)"
                header_label = QLabel(header_text)
                header_label.setStyleSheet("font-weight: bold;")
                self.card_grid.addWidget(
                    header_label, row_index, 0, 1, self._GRID_COLUMNS)
                self._grid_chapter_headers[chapter_occurrence] = header_label
                chapter_occurrence += 1
                row_index += 1
            self.card_grid.addWidget(
                self._build_card(position, call), row_index, col_index)
            col_index += 1
            if col_index >= self._GRID_COLUMNS:
                col_index = 0
                row_index += 1

    def _build_card(self, position: int, call: SlideCall) -> QWidget:
        """One clickable card: this slide's cached thumbnail (this deck's
        own template, slide_snapshot.THUMB_SIZE) plus an id/title caption.
        Click opens the source editor -- same action as the list view's own
        id link. No editing controls here on purpose (see the Grid radio's
        own tooltip): this view is for browsing, not editing."""
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(4, 4, 4, 4)

        thumb_w, thumb_h = slide_snapshot.THUMB_SIZE
        image_label = QLabel()
        image_label.setFixedSize(thumb_w, thumb_h)
        image_label.setAlignment(Qt.AlignCenter)
        png_path = slide_snapshot.snapshot_path(
            slide_snapshot.bare_id(call.id_slug), self._template, slide_snapshot.THUMB_SIZE)
        pixmap = QPixmap(str(png_path)) if png_path.is_file() else QPixmap()
        if not pixmap.isNull():
            image_label.setPixmap(pixmap)
            # Fixed white, not theme-following -- same reasoning as every
            # other slide image preview in this app: a slide's own
            # background is white regardless of the app's dark/light mode.
            image_label.setStyleSheet("background-color: #ffffff;")
        else:
            image_label.setText("<i>no preview yet</i>")
            image_label.setObjectName("mutedLabel")
            image_label.setStyleSheet(
                "border: 1px solid palette(mid);")
        layout.addWidget(image_label)

        caption = QLabel(f"{position}. {call.id_slug}" + _language_badge_html(call.id_slug))
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignCenter)
        caption.setFixedWidth(thumb_w)
        layout.addWidget(caption)

        card.mousePressEvent = (  # noqa: E731
            lambda event, c=call: self.app.open_slide_editor(
                SLIDES_DIR / c.source_filename, return_to=self
            )
        )
        return card

    # -- variant option formatting --------------------------------------------

    def _variant_options(self, call: SlideCall, versions: list[str]) -> tuple[list[str], int]:
        options = [self._format_option(m, None) for m in deck_editor.BASE_MACROS]
        for v in versions:
            options.append(self._format_option("slideversion", v))
            options.append(self._format_option("omitslideversion", v))
        current_label = self._format_option(call.macro, call.version)
        try:
            idx = options.index(current_label)
        except ValueError:
            options.insert(0, current_label)
            idx = 0
        return options, idx

    @staticmethod
    def _format_option(macro: str, version: Optional[str]) -> str:
        return f"\\{macro} (v{version})" if version is not None else f"\\{macro} (current)"

    @staticmethod
    def _parse_option(label: str) -> tuple[str, Optional[str]]:
        macro = label.split(" ", 1)[0][1:]
        if "(v" in label:
            return macro, label.split("(v", 1)[1].rstrip(")")
        return macro, None

    # -- actions --------------------------------------------------------------

    def _on_apply(self, call: SlideCall, combo: QComboBox, cond_vars: dict) -> None:
        macro, version = self._parse_option(combo.currentText())
        conditions = None
        if macro == "conditionalslide":
            conditions = [v for v in VERSIONS if cond_vars[v].isChecked()]
            if not conditions:
                QMessageBox.critical(
                    self, "Change variant", "Pick at least one deck version for \\conditionalslide."
                )
                return
        previous_text = self.deck.text
        try:
            deck_editor.change_slide_call_variant(
                self.deck.path, self.deck.text, call, macro, version, conditions
            )
        except (deck_editor.StaleFileError, ValueError) as exc:
            QMessageBox.critical(self, "Change variant failed", str(exc))
            return
        self.app.after_deck_edit(
            self.deck.path,
            f"Changed {call.id_slug} in {self.deck.name}: \\{call.macro} -> \\{macro}",
            previous_text=previous_text,
        )

    def _on_remove(self, call: SlideCall) -> None:
        # No confirmation dialog -- the toolbar's Undo button covers this
        # instead (see the module docstring).
        previous_text = self.deck.text
        try:
            deck_editor.remove_slide_call(self.deck.path, self.deck.text, call)
        except (deck_editor.StaleFileError, ValueError) as exc:
            QMessageBox.critical(self, "Remove failed", str(exc))
            return
        self.app.after_deck_edit(
            self.deck.path,
            f"Removed \\{call.macro}{{{call.id_slug}}} from {self.deck.name}",
            previous_text=previous_text,
        )

    def _selected_calls(self) -> list[SlideCall]:
        return [call for box, call in self._row_checkboxes if box.isChecked()]

    def _update_bulk_remove_button(self, *_args) -> None:
        count = len(self._selected_calls())
        self.bulk_remove_button.setVisible(count >= 2)
        self.bulk_remove_button.setText(f"Remove selected ({count})")
        self.clear_selection_button.setVisible(count >= 2)

    def _on_clear_selection(self) -> None:
        for box, _call in self._row_checkboxes:
            box.setChecked(False)

    def _on_remove_selected(self) -> None:
        # No confirmation, same as the per-row Remove: the whole batch is
        # one write, so one click of Undo restores all of it.
        calls = self._selected_calls()
        if not calls:
            return
        previous_text = self.deck.text
        try:
            deck_editor.remove_slide_calls(self.deck.path, self.deck.text, calls)
        except (deck_editor.StaleFileError, ValueError) as exc:
            QMessageBox.critical(self, "Remove failed", str(exc))
            return
        self.app.after_deck_edit(
            self.deck.path,
            f"Removed {len(calls)} slides from {self.deck.name}: "
            + ", ".join(c.id_slug for c in calls),
            previous_text=previous_text,
        )

    def _on_insert(self, call: SlideCall, before: bool) -> None:
        insert_at = call.line_start if before else call.line_end
        self.app.open_add_slide_dialog(self.deck, insert_at, call.indent, return_to=self)

    def _set_preview_tooltip(self, label: QLabel, id_slug: str) -> None:
        """Hover preview: Qt's tooltips render a real (if limited) HTML
        subset, including local <img> tags, so this needs no custom popup
        or event filter -- just a rich-text string pointing at the cached
        PNG (slide_snapshot.py). Falls back to a plain-text hint when
        nothing has been captured for this slide yet.

        `id_slug` is the full slug (e.g. "22s-More-Exotic-Bonds", what
        SlideCall.id_slug actually holds) -- snapshots are keyed by the
        short id a compiled page's own footer carries instead
        (slide_snapshot.bare_id() derives it the same way
        \\setSlideID does).

        Points at the dedicated THUMB_SIZE thumbnail, not the 1920x1080 full
        size shrunk to width=480 in HTML -- confirmed directly that Qt's
        rich-text tooltip renderer doesn't apply the same smooth-scaling
        quality QPixmap.scaled() does, so a 4x runtime shrink looked soft.
        Rendering the thumbnail at its own target size from the PDF page
        (slide_snapshot.py) and displaying it near enough to native size
        avoids that entirely.
        """
        png_path = slide_snapshot.snapshot_path(
            slide_snapshot.bare_id(id_slug), self._template, slide_snapshot.THUMB_SIZE)
        if png_path.is_file():
            width, _height = slide_snapshot.THUMB_SIZE
            label.setToolTip(f'<img src="{png_path.as_uri()}" width="{width}">')
        else:
            label.setToolTip(
                "No preview captured yet -- use Preview to generate one.")

    def _render_to_pdf(self, call: SlideCall, position: int) -> None:
        """The real compile a Preview popup's "Render now" falls back to --
        same deck preamble/frame-number context the old Render button used,
        so the PDF matches how the slide actually looks and where it falls
        in this deck. Does *not* open the compiled PDF itself (2026-09-22,
        direct report: the popup's own image already refreshes from the
        fresh snapshot this compile leaves behind -- see SlidePreviewPopup's
        own _on_render_done() -- so opening the standalone PDF too was a
        redundant second auto-open). Raises RuntimeError on failure, same
        contract SlidePreviewPopup expects from render_fn.
        """
        from . import slide_preview

        # Read live, same as qt_slide_source_tab.py's own preview/render
        # paths -- this popup's "Render now" ignored the checkbox entirely
        # otherwise (direct report, 2026-08-30).
        slide_preview.render_slide_to_pdf(
            call.macro, call.id_slug, call.version, call.conditions,
            footer_timestamp=self.app.footer_timestamp_checkbox.isChecked(),
            preamble_text=self.deck.preamble_text, frame_number=position,
            log=self.app.signals.log.emit, steps=call.steps,
        )

    def _on_preview(self, call: SlideCall, position: int) -> None:
        popup = SlidePreviewPopup(
            self, slide_snapshot.bare_id(call.id_slug),
            SLIDES_DIR / call.source_filename,
            render_fn=lambda: self._render_to_pdf(call, position),
            template=self._template,
        )
        popup.exec()
        # A "Render now" inside the popup may have just captured this
        # slide's first-ever snapshot -- refresh the hover tooltip so it
        # doesn't keep advertising "no preview yet".
        label = self._id_labels.get(call.id_slug)
        if label is not None:
            self._set_preview_tooltip(label, call.id_slug)
