"""PySide6 rewrite of SlideMage's GUI -- see PYSIDE6_MIGRATION.md for the
full migration plan. Started via cli.main() (`slidemage`).

Phase 4: the deck table (qt_deck_table.py) wired into the shell built in
Phase 3, plus compile-job threading/signal wiring and the remaining main-
toolbar actions (Empty pdf/folder, Remove temp files, Archive unused
content, footer-timestamp/auto-open/dark-mode checkboxes, version label).
Opening a deck's slide-list editor or a slide's own editor tab (DeckRow's
name-label click) is still a stub -- those need slide_source_tab.py's and
deck_editor_tab.py's own Qt ports (Phases 5-6).
"""
from __future__ import annotations

import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QCompleter,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import app_settings
from . import archive as archive_mod
from . import bibliography
from . import deck_duplicate
from . import deck_editor
from . import deck_headers
from . import open_path
from . import pptx_export
from . import qt_slide_source_tab
from . import slide_ids
from . import slide_rename
from . import slide_snapshot
from . import transcript
from . import update_all_previews
from . import version as version_mod
from .compiler import (
    BUILD_DIR,
    PDF_DIR,
    PDF_MOVE_RETRY_TOTAL_SECONDS,
    CancelToken,
    CompileJob,
    latest_pdf_for_deck,
    resolve_output_location,
    run_job,
    run_jobs,
)
from .deck_scan import DECKS_DIR, GROUP_TAGS, PROJECT_ROOT, Deck, scan_decks
from .qt_add_slide_dialog import AddSlideDialog
from .qt_closable_tab_bar import ClosableTabBar
from .qt_deck_editor_tab import DeckEditorTab
from .qt_deck_group_dialog import ask_deck_details
from .qt_settings_dialog import SettingsDialog
from .qt_slide_search_dialog import SlideSearchDialog
from .qt_slide_source_tab import SlideSourceTab
from .qt_transcript_preview_tab import TranscriptPreviewTab
from .qt_transcript_tab import TranscriptTab
from .qt_version_history_dialog import VersionHistoryDialog
from .slide_ids import SLIDES_DIR
from .qt_deck_table import DeckRow, DeckTable, build_progress_texts, job_column_key
from .qt_theme import WARNING_LABEL, ThemeManager
from .unused_content import archive_unused_content

RUNNING_LOG_RE = re.compile(r"^==== Compiling \S+ -> (\S+) ====")
MOVING_LOG_RE = re.compile(r"^==== MOVING: (\S+) ->")
PASS_LOG_RE = re.compile(r"^==== PASS: (\S+) ->")
FAIL_LOG_RE = re.compile(r"^\*\*\* FAIL: (\S+) --")
DONE_LOG_RE = re.compile(r"^==== Done: (.+) ====$")
RENDER_START_RE = re.compile(r"^==== Rendering (\S+) -> \S+ ====")
RENDER_PASS_RE = re.compile(r"^==== PASS: render of (\S+) ->")
RENDER_FAIL_RE = re.compile(r"^\*\*\* FAIL: render of (\S+) --")
RUN_NUMBER_RE = re.compile(r"^Run number (\d+) of rule '([^']+)'")

# The project root's own workflow scratch folder (CONVERSION_NOTES.md) --
# where a PPTX mid-conversion, a higher-resolution source image waiting to
# be cropped, or similar working input gets placed by hand. Unlike .build/
# and decks/_slidemage_*.tex, this isn't SlideMage's own build output, but
# "Remove temp files" (2026-09-18, direct instruction) empties it too.
TEMP_DIR = PROJECT_ROOT / ".temp"

SPINNER_INTERVAL_MS = 400
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"


class CompileSignals(QObject):
    """Cross-thread bridge: run_jobs()/archive_unused_content() (on plain
    threading.Thread workers, same as the Tk version) call
    log.emit(line) from the worker thread. Qt automatically queues a
    cross-thread signal emission onto the receiving QObject's own thread
    (the GUI thread, since this object is created there) -- this replaces
    gui.py's manual queue.Queue + root.after(100, poll) with real
    event-driven delivery, no polling loop needed."""

    log = Signal(str)
    batch_done = Signal()
    # For a background thread (e.g. DeckEditorTab's own per-row Render)
    # that needs to re-enable a button once it's done -- setEnabled() is a
    # widget mutation, so it has to run on the GUI thread same as
    # everything else here. Signal(object) rather than Signal(QPushButton)
    # so this can carry any widget type, not just buttons.
    enable_button = Signal(object)


class SlideMageWindow(QMainWindow):
    def __init__(self, theme: ThemeManager) -> None:
        super().__init__()
        self.theme = theme
        self.setWindowTitle(f"SlideMage — {version_mod.VERSION}")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1008, 975)

        self._build_menu_bar()

        self.compiling = False
        self.cancel_token: Optional[CancelToken] = None
        self._job_status_map: dict[str, tuple[DeckRow, str]] = {}
        # Resolved once per job in _compile_rows() (compiler.resolve_output_location()
        # -- a deck's own \deckoutputfolder, or PDF_DIR/jobname) so
        # _open_pdf() knows exactly where a job's PDF actually landed
        # without re-deriving it, which is only ever correct for a deck
        # with no override and no full-filename override either.
        self._job_output_paths: dict[str, Path] = {}
        self._job_progress_texts: dict[str, str] = {}
        self._current_progress_base = ""
        self._spinner_frame = 0
        self.active_rows: list[DeckRow] = []
        self.archived_rows: list[DeckRow] = []
        # Keyed by path, deduping already-open tabs -- reselecting an
        # already-open deck/slide editor instead of reopening it.
        self._deck_editor_tabs: dict[Path, DeckEditorTab] = {}
        self._slide_source_tabs: dict[Path, SlideSourceTab] = {}
        # Keyed by slide bare id, not path -- a transcript preview has no
        # file of its own to dedupe on, and re-clicking "Render transcript"
        # for the same slide should refresh its existing tab rather than
        # piling up duplicates.
        self._transcript_preview_tabs: dict[str, TranscriptPreviewTab] = {}
        # Global mutual-exclusion for anything that calls Ollama (image
        # drafting, image translation, and the "Duplicate slide" dialog's
        # auto-translate option) -- None when idle, else a short label of
        # whatever currently holds it. Direct report, 2026-08-25: running a
        # drafting batch and a translation at the same time crashed, most
        # likely two different models loaded into VRAM simultaneously (a
        # local Ollama server's own resource limit, not a bug this app can
        # fix). See try_start_ollama_task()/end_ollama_task() below.
        self._ollama_task_label: Optional[str] = None

        self.signals = CompileSignals()
        self.signals.log.connect(self._log)
        self.signals.enable_button.connect(lambda w: w.setEnabled(True))
        self.signals.batch_done.connect(self._on_batch_done)

        central = QWidget()
        outer = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        # Only the dynamically-opened deck-editor/slide-editor tabs are
        # closable this way -- "Active decks"/"Archived decks" are the two
        # permanent tabs and have nothing to close to.
        self.tabs.setTabBar(
            ClosableTabBar(self._tab_is_closable, self._close_tab_at_index)
        )
        # ElideRight (not the default ElideMiddle) so a long deck/slide tab
        # name is truncated at the end -- keeps the identifying start of
        # the name (e.g. the slide id-slug) visible rather than its middle.
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)

        self.active_table = DeckTable(
            theme, archivable=True,
            on_open=self.open_deck_editor,
            on_archive=self._archive_deck,
            on_edit=self._on_edit_deck,
            on_duplicate=self._on_duplicate_deck,
            on_export_pptx=self._on_export_pptx,
            on_compile_selected=self._compile_rows,
            on_stop_compilation=self._stop_compilation,
            on_create_transcript=self._on_create_transcript_toplevel,
            on_refresh=self._on_refresh_decks_clicked,
            on_tags=self._on_edit_deck_tags,
            on_open_pdf=self._on_open_latest_pdf,
        )
        self.archived_table = DeckTable(
            theme, archivable=False,
            on_open=self.open_deck_editor,
            on_archive=None,
            on_edit=None,
            on_duplicate=None,
            on_export_pptx=None,
            on_compile_selected=self._compile_rows,
            on_stop_compilation=self._stop_compilation,
            on_create_transcript=self._on_create_transcript_toplevel,
            on_refresh=self._on_refresh_decks_clicked,
        )
        self.tabs.addTab(self.active_table, "Active decks")
        # Archived decks / Images start CLOSED (2026-08-25, direct
        # instruction) -- opened on demand via the new "Tabs" menu instead
        # of always being present, and closable once open (see
        # _tab_is_closable/_close_tab_at_index below). Both widgets are
        # still constructed up front here (cheap) and, once opened, kept
        # alive across a close rather than deleted -- so reopening never
        # repays Images' own first-load scan (see TranscriptTab below) or
        # loses Archived decks' own scroll position.
        #
        # Third widget alongside Active/Archived decks. Its own first scan
        # reads every slide that includes an image and hashes those images'
        # bytes (~1s) and syncs the store -- deferred to the first time the
        # tab is actually opened rather than paid on every launch, and
        # deliberately not a launch-time *write* to media/alt-text.json.
        self.transcript_tab = TranscriptTab(self)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setCornerWidget(self._build_search_box())
        outer.addWidget(self.tabs)
        self._apply_tab_colors()

        self._toolbar_layout = self._build_toolbar()
        outer.addLayout(self._toolbar_layout)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Log:"))
        self.status_label = QLabel("")
        self.status_label.setObjectName(WARNING_LABEL)
        log_header.addWidget(self.status_label)
        log_header.addStretch()
        outer.addLayout(log_header)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(200)
        outer.addWidget(self.log_text)

        self.setCentralWidget(central)

        self.reload_decks()
        self._width_fitted = False

        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(SPINNER_INTERVAL_MS)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Not in __init__: before the first show() the widgets are not
        # polished yet (fonts/stylesheet), and the deck table's size hint
        # then comes out at less than half of what it really needs.
        if not self._width_fitted:
            self._width_fitted = True
            self._fit_initial_width()

    def _fit_initial_width(self) -> None:
        """Opening width: wide enough for the whole main screen (2026-09-21,
        direct instruction: "the entire width of the main screen (all
        buttons) [should be] visible") -- the widest deck table row (its
        buttons, checkboxes and columns, which otherwise sit behind a
        horizontal scroll bar) and the footer checkbox row, plus the
        window's own margins, limited to the screen the window opens on.
        Only ever grows the default width; a saved/dragged size afterwards
        is the user's own."""
        needed = max(
            self.active_table.content.sizeHint().width(),
            self.archived_table.content.sizeHint().width(),
            self._toolbar_layout.sizeHint().width(),
        )
        margins = 48  # central widget + tab frame + scroll area frame
        screen = QGuiApplication.primaryScreen()
        limit = screen.availableGeometry().width() if screen is not None else needed + margins
        self.resize(max(self.width(), min(needed + margins, limit)), self.height())
        if screen is not None:
            # a wider window must not hang over the screen's right edge
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            if frame.right() > available.right():
                self.move(max(available.left(), available.right() - frame.width() + 1), frame.top())

    # -- toolbar / search (Phase 3's corner widget unchanged) -----------------

    def _build_search_box(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel("Find slide:"))

        self.slide_search_entry = QLineEdit()
        self.slide_search_entry.setFixedWidth(220)
        layout.addWidget(self.slide_search_entry)

        completer = QCompleter(slide_ids.list_id_slugs(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._on_slide_search_activated)
        self.slide_search_entry.setCompleter(completer)

        # Searches every slide's own *body text* (slide_search.py), unlike
        # "Find slide:" above, which only autocompletes on a slide's own
        # id/slug (2026-08-26, direct instruction). Ctrl+Shift+F is the
        # same shortcut regardless of which tab/widget has focus, since
        # this is a project-wide search, not scoped to whatever's open.
        search_text_button = QPushButton("Search all slide texts…")
        search_text_button.setToolTip("Search every slide's text (Ctrl+Shift+F)")
        search_text_button.clicked.connect(self._on_open_slide_search)
        layout.addWidget(search_text_button)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._on_open_slide_search)

        return container

    def _on_slide_search_activated(self, id_slug: str) -> None:
        return_to = self.tabs.currentWidget()
        self.open_slide_editor(SLIDES_DIR / f"{id_slug}-current.tex", return_to=return_to)
        self.slide_search_entry.clear()

    def _on_open_slide_search(self) -> None:
        SlideSearchDialog(self).exec()

    def _build_menu_bar(self) -> None:
        """First menu bar this app has ever had (2026-08-25, direct
        instruction), grown the same day, then rearranged once more the
        same day (direct instruction) into what's now four top-level
        entries:

        - **System** -- was "Settings" until the rename; "Preferences…"
          (dark mode, per-model translation prompt configuration --
          qt_settings_dialog.py) plus "Exit SlideMage" at the bottom,
          the one place an app-lifecycle action belongs, separate from
          Preferences above it.
        - **Tabs** -- opens "Archived decks"/"Images"/the Slidemaster.bib
          editor, none of which are open by default any more (previously
          Archived decks/Images were two of the three permanent tabs,
          always present; .bib had its own always-visible toolbar
          button). All three are closable once opened, unlike "Active
          decks" which stays the one truly permanent tab.
        - **Housekeeping** -- the five maintenance actions that used to be
          the bottom toolbar's own row of buttons, moved here so that row
          could go away entirely (direct instruction: "This will allow you
          to get rid of the bottom button row entirely"), grouped under
          two labelled sections (addSection() -- a real Qt menu feature,
          not just a plain separator): "Cleanup" (the three that remove/
          relocate files) and "Updating" (the two that refresh derived
          state from current disk content).
        - **Info** -- a single top-level action (not a dropdown with
          items inside -- there's only ever the one thing to show),
          opening the version-history window (qt_version_history_dialog.py).
          Last position (2026-08-25, direct instruction; originally sat
          second, right after System).
        """
        system_menu = self.menuBar().addMenu("System")
        preferences_action = system_menu.addAction("Preferences…")
        preferences_action.triggered.connect(self._on_open_settings)
        system_menu.addSeparator()
        exit_action = system_menu.addAction("Exit SlideMage")
        exit_action.triggered.connect(self.close)

        tabs_menu = self.menuBar().addMenu("Tabs")
        archived_action = tabs_menu.addAction("Archived decks")
        archived_action.triggered.connect(self._on_open_archived_tab)
        images_action = tabs_menu.addAction("Images")
        images_action.triggered.connect(self._on_open_images_tab)
        bib_action = tabs_menu.addAction("Edit .bib")
        bib_action.triggered.connect(self._on_edit_bib)

        housekeeping_menu = self.menuBar().addMenu("Housekeeping")
        housekeeping_menu.addSection("Cleanup")
        empty_pdf_action = housekeeping_menu.addAction("Empty pdf folder")
        empty_pdf_action.triggered.connect(self._empty_pdf_folder)
        remove_temp_action = housekeeping_menu.addAction("Remove temp files")
        remove_temp_action.triggered.connect(self._remove_temp_files)
        archive_unused_action = housekeeping_menu.addAction(
            "Archive unused slides and media files")
        archive_unused_action.triggered.connect(self._on_archive_unused_content)
        housekeeping_menu.addSection("Updating")
        update_previews_action = housekeeping_menu.addAction("Update slide previews")
        update_previews_action.setToolTip(
            "Scan every deck (active and archived) for which slides it "
            "uses under which institution template, then compile "
            "(instructor version) exactly those slide-template "
            "combinations and delete any cached preview no deck uses any "
            "more. Runs in the background, but occupies the compile slot "
            "the same as any other job."
        )
        update_previews_action.triggered.connect(self._on_update_previews)
        sync_translation_links_action = housekeeping_menu.addAction(
            "Reestablish broken translation links")
        sync_translation_links_action.setToolTip(
            "Refresh every slide's own \"Translation of: ...\"/\"<LANG> "
            "translation: ...\" header comment to match current disk state "
            "(mirrors deck_headers.py's own \"Included in decks\" "
            "regeneration) -- run after renaming a slide by hand, or just "
            "to normalize comments written before this tool existed. "
            "Only refreshes links that already exist; never invents a new "
            "one. Runs instantly, no compile involved."
        )
        sync_translation_links_action.triggered.connect(self._on_sync_translation_links)

        info_action = self.menuBar().addAction("Info")
        info_action.triggered.connect(self._on_open_version_history)

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def _on_open_version_history(self) -> None:
        dialog = VersionHistoryDialog(self)
        dialog.exec()

    def _on_open_archived_tab(self) -> None:
        if self.tabs.indexOf(self.archived_table) == -1:
            self.tabs.addTab(self.archived_table, "Archived decks")
            self._set_tab_color(self.archived_table, self.theme.tab_colors()["archived"])
        self.tabs.setCurrentWidget(self.archived_table)

    def _on_open_images_tab(self) -> None:
        if self.tabs.indexOf(self.transcript_tab) == -1:
            self.tabs.addTab(self.transcript_tab, "Images")
            self._set_tab_color(self.transcript_tab, self.theme.tab_colors()["transcript"])
        self.tabs.setCurrentWidget(self.transcript_tab)

    def open_images_for_slide(self, id_slug: str) -> None:
        """A deck editor row's "Images" button (2026-09-19, direct
        instruction): opens (or reveals) the Images tab and lands on that
        slide's images. ensure_loaded() first because the tab's first scan
        is deferred until it's shown -- _find_and_show_slide() only searches
        rows a scan has already produced."""
        self._on_open_images_tab()
        self.transcript_tab.ensure_loaded()
        self.transcript_tab._find_and_show_slide(id_slug)

    def _build_toolbar(self) -> QHBoxLayout:
        """Just the two footer-related checkboxes now (2026-08-25) -- the
        five maintenance buttons that used to fill this row moved into the
        "Housekeeping" menu, and "Edit .bib" into the "Tabs" menu (both
        _build_menu_bar(), direct instruction: get rid of the bottom
        button row entirely)."""
        toolbar = QHBoxLayout()
        toolbar.addStretch()

        self.footer_timestamp_checkbox = QCheckBox("Include footer timestamp")
        # Default off (2026-08-20, direct instruction) -- was on by default.
        self.footer_timestamp_checkbox.setChecked(False)
        toolbar.addWidget(self.footer_timestamp_checkbox)

        self.appendix_toc_checkbox = QCheckBox("Generate appendix TOC")
        self.appendix_toc_checkbox.setToolTip(
            "Adds a clickable appendix (agenda + one thumbnail grid per "
            "chapter) to the Instructor/version-less and Presenter compiles "
            "-- a no-op on During-course/After-course and per-chapter jobs."
        )
        # Persisted (app_settings.py, same local per-machine store dark
        # mode/tab-width/model-picker settings already use) -- unlike
        # footer_timestamp/auto_open just below, which stay hardcoded
        # per-launch defaults; direct instruction, 2026-09-16.
        self.appendix_toc_checkbox.setChecked(bool(app_settings.get("appendix_toc", False)))
        self.appendix_toc_checkbox.toggled.connect(
            lambda checked: app_settings.set("appendix_toc", checked)
        )
        toolbar.addWidget(self.appendix_toc_checkbox)

        self.auto_open_checkbox = QCheckBox("Auto-open generated PDFs")
        self.auto_open_checkbox.setChecked(True)
        toolbar.addWidget(self.auto_open_checkbox)

        return toolbar

    def set_dark_mode(self, checked: bool) -> None:
        """Public (2026-08-25): called from the Settings dialog's own
        checkbox (qt_settings_dialog.py), not just an internal toolbar
        handler any more -- theme.set_dark() itself now also persists the
        choice (QSettings, per-machine -- see qt_theme.py)."""
        self.theme.set_dark(checked)
        # QSS covers every ordinary widget automatically, but a
        # QSyntaxHighlighter's own tag colors live on the text document,
        # outside the stylesheet mechanism entirely -- each open slide
        # editor's highlighter needs an explicit nudge to pick up the new
        # palette and re-run.
        for tab in self._slide_source_tabs.values():
            tab.highlighter.refresh_colors()
        # Same reasoning applies to per-tab text colors -- set via
        # QTabBar.setTabTextColor(), not QSS, so they don't repaint
        # themselves when the stylesheet is reapplied above.
        self._apply_tab_colors()

    def set_tab_width_chars(self, chars: int) -> None:
        """Called from the Settings dialog's own tab-width spinbox
        (qt_settings_dialog.py), same shape as set_dark_mode() just above:
        persist the choice (app_settings.py), then nudge every already-open
        slide/deck-source editor to pick it up immediately rather than only
        on next open."""
        app_settings.set(qt_slide_source_tab.TAB_WIDTH_SETTING_KEY, chars)
        for tab in self._slide_source_tabs.values():
            tab.refresh_tab_width()

    def _set_tab_color(self, widget: QWidget, hex_color: str) -> None:
        index = self.tabs.indexOf(widget)
        if index != -1:
            self.tabs.tabBar().setTabTextColor(index, QColor(hex_color))

    @staticmethod
    def _slide_editor_tab_color_role(path: Path) -> str:
        """Slidemaster.bib opens through the exact same SlideSourceTab/
        _slide_source_tabs machinery as any slide or deck .tex source (see
        _on_edit_bib) -- singled out here only for its tab color, on direct
        instruction that it read as its own thing rather than blending in
        with ordinary slide/deck editor tabs."""
        return "bib_editor" if path == bibliography.DEFAULT_BIB else "slide_editor"

    def _apply_tab_colors(self) -> None:
        """Distinct text colors per tab role -- Active/Archived decks,
        open deck-editor tabs, open slide-editor tabs -- the feature that
        motivated this whole migration (ttk.Notebook has no per-tab color
        API at all). Re-run on every dark/light toggle since the color
        values themselves come from the palette."""
        colors = self.theme.tab_colors()
        self._set_tab_color(self.active_table, colors["active"])
        self._set_tab_color(self.archived_table, colors["archived"])
        self._set_tab_color(self.transcript_tab, colors["transcript"])
        for tab in self._deck_editor_tabs.values():
            self._set_tab_color(tab, colors["deck_editor"])
        for path, tab in self._slide_source_tabs.items():
            self._set_tab_color(tab, colors[self._slide_editor_tab_color_role(path)])
        for tab in self._transcript_preview_tabs.values():
            self._set_tab_color(tab, colors["transcript"])

    def _on_tab_changed(self, index: int) -> None:
        """Run the image-description tab's first (expensive) scan only once
        it's actually opened -- see where it's constructed for why."""
        if self.tabs.widget(index) is self.transcript_tab:
            self.transcript_tab.ensure_loaded()

    def _tab_is_closable(self, index: int) -> bool:
        """ClosableTabBar's own predicate -- "Active decks" is the one
        truly permanent tab now (2026-08-25: Archived decks/Images used to
        be permanent too, but now open on demand from the "Tabs" menu, so
        they need a close "x" like anything else opened that way) --
        everything else opened at runtime (deck-editor/slide-editor tabs,
        Archived decks, Images, a transcript preview) is closable."""
        widget = self.tabs.widget(index)
        return isinstance(
            widget, (DeckEditorTab, SlideSourceTab, DeckTable, TranscriptTab, TranscriptPreviewTab)
        ) and widget is not self.active_table

    def _close_tab_at_index(self, index: int) -> None:
        """ClosableTabBar's own close callback -- a deck-editor/slide-
        editor tab routes through its own `_on_close()` (already wired to
        its toolbar "Close" button) so the hover "x" goes through the same
        unsaved-changes prompt as that button; Archived decks/Images/a
        transcript preview have no such prompt (nothing in them is ever
        "unsaved" the way a source buffer is) and just leave the tab bar,
        their own widget kept alive (not deleted) so reopening them later
        doesn't lose scroll position or (for Images) repay its first-load
        scan -- a transcript preview tab is the one exception, since it's
        cheap to regenerate and has no reason to be kept around once
        closed."""
        widget = self.tabs.widget(index)
        if isinstance(widget, (DeckEditorTab, SlideSourceTab)):
            widget._on_close()
        elif isinstance(widget, TranscriptPreviewTab):
            widget._on_close()
        elif widget in (self.archived_table, self.transcript_tab):
            self.tabs.removeTab(index)
            self.tabs.setCurrentWidget(self.active_table)

    # -- deck slide-list editor tabs -----------------------------------------

    def open_deck_editor(self, deck: Deck) -> None:
        existing = self._deck_editor_tabs.get(deck.path)
        if existing is not None:
            existing.reload(deck)
            self.tabs.setCurrentWidget(existing)
            return
        tab = DeckEditorTab(self, deck)
        self._deck_editor_tabs[deck.path] = tab
        self.tabs.addTab(tab, f"{deck.name} (slides)")
        self.tabs.setCurrentWidget(tab)
        self._set_tab_color(tab, self.theme.tab_colors()["deck_editor"])

    def close_deck_editor_tab(self, tab: DeckEditorTab) -> None:
        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.removeTab(index)
        # ttk.Notebook's own post-forget() default (whatever tab now sits
        # at this index) could land on "Archived decks" -- explicitly
        # return to "Active decks" instead, same fix gui.py's own
        # DeckEditorTab._on_close already applies.
        self.tabs.setCurrentWidget(self.active_table)
        self._deck_editor_tabs.pop(tab.deck.path, None)
        tab.deleteLater()

    def resync_deck(self, deck_path: Path) -> Optional[Deck]:
        """Re-scans every deck (like Refresh decks) and returns this one's
        fresh Deck snapshot -- called after any edit made through the deck
        slide-list editor, so the main table's own DeckRow never goes
        stale."""
        self.reload_decks()
        for row in self.active_rows + self.archived_rows:
            if row.deck.path == deck_path:
                return row.deck
        return None

    def after_deck_edit(
        self, deck_path: Path, summary: str, previous_text: Optional[str] = None
    ) -> None:
        """Shared post-edit sequence for every deck slide-list editor
        action -- header-sync in the background, resync + rebuild the open
        tab, then log a summary line. See gui.py's own after_deck_edit for
        the full rationale (ported unchanged)."""
        threading.Thread(target=self._regenerate_headers_bg, daemon=True).start()
        fresh_deck = self.resync_deck(deck_path)
        tab = self._deck_editor_tabs.get(deck_path)
        if tab is not None:
            if previous_text is not None:
                tab.record_undo_snapshot(previous_text)
            if fresh_deck is not None:
                tab.reload(fresh_deck)
        self._log(summary)

    def refresh_open_deck_editors(self) -> None:
        """Refreshes the main Active/Archived tables and every currently
        open deck-editor tab from current disk state (2026-08-25) -- for
        an edit that can touch more than one deck at once and has no
        single deck_path to hand after_deck_edit()
        (slide_rename.set_slide_language() rewrites every deck reference
        to a renamed slide, across however many decks reference it).
        Without this, an open deck-editor tab kept showing a slide under
        its old id-slug after a rename -- clicking it tried to open a
        file that no longer existed. Doesn't re-run
        deck_headers.regenerate_headers() itself -- a caller that needs
        that has already run it (set_slide_language() always does, as its
        own last step)."""
        self.reload_decks()
        fresh_by_path = {row.deck.path: row.deck for row in self.active_rows + self.archived_rows}
        for deck_path, tab in self._deck_editor_tabs.items():
            fresh_deck = fresh_by_path.get(deck_path)
            if fresh_deck is not None:
                tab.reload(fresh_deck)

    def try_start_ollama_task(self, label: str) -> bool:
        """Reserves the single app-wide Ollama slot for `label` (a short
        present-participle phrase, e.g. "drafting descriptions" --
        appears in the busy message below). Returns False, and shows why,
        if another Ollama-dependent task already holds it -- every call
        site (qt_transcript_tab.py's single/batch drafting, single/batch
        translation, and its "Tune prompt…" dialog; qt_duplicate_slide_dialog.py's
        auto-translate option) must call this before issuing its own first
        Ollama request and end_ollama_task() when that request (or batch of
        them) is fully done, whether it ran on a background thread or
        blocked the GUI thread synchronously. This is deliberately a single
        global slot, not a smarter per-model or per-resource scheduler --
        running two Ollama-dependent tasks at once has been observed to
        crash (2026-08-25, direct report), almost certainly from two
        different models being loaded into VRAM simultaneously, which is a
        limit of the local Ollama server itself, not something this app can
        negotiate around."""
        if self._ollama_task_label is not None:
            QMessageBox.warning(
                self, "Ollama busy",
                f"{self._ollama_task_label.capitalize()} is already running -- "
                f"only one Ollama-dependent task can run at a time in this "
                f"app (running two at once has crashed before). Wait for it "
                f"to finish, or stop it, before starting {label}.",
            )
            return False
        self._ollama_task_label = label
        return True

    def end_ollama_task(self) -> None:
        self._ollama_task_label = None

    def _regenerate_headers_bg(self) -> None:
        changed, n_decks = deck_headers.regenerate_headers()
        self.signals.log.emit(
            f"==== Header sync: {changed} slide file(s) updated across {n_decks} deck(s) ===="
        )

    def log(self, line: str) -> None:
        """Public entry point for the deck editor/slide source tab modules
        to append to the log pane -- always called from the main thread (a
        button/dialog action)."""
        self._log(line)

    def open_deck_source_editor(self, deck: Deck, return_to: Optional[QWidget] = None) -> None:
        """The deck slide-list editor's own "Source" button -- opens the
        deck's raw .tex file in the same editor used for a slide's own
        source. A save is routed through the same after_deck_edit()
        pipeline every row action already uses, so a hand-edit gets
        header-sync, the open deck-editor tab refreshed, and an Undo-stack
        entry exactly like any other deck edit."""
        self.open_slide_editor(
            deck.path,
            on_saved=lambda previous_text: self.after_deck_edit(
                deck.path, f"Edited {deck.name}'s source directly", previous_text=previous_text
            ),
            return_to=return_to,
        )

    def _on_edit_bib(self) -> None:
        """"Tabs -> Edit .bib" menu action (a plain toolbar button until
        2026-08-25) -- opens Slidemaster.bib in the same editor tab used
        for a slide's/deck's own .tex source. That editor
        already degrades gracefully for a non-slide path (no Preview/
        Render/transcript-summary controls, see SlideSourceTab's own
        _is_slide check), so no separate editor was needed just for this.

        Sorted on disk *before* opening (2026-08-18, direct instruction:
        keep Slidemaster.bib sorted automatically on open/close of this tab
        rather than needing a manual sort_bib.py run) -- only when actually
        creating a new tab, not when this just re-focuses an already-open
        one, so a mid-edit buffer is never silently reloaded out from under
        the user. The matching close-side sort lives in
        close_slide_editor_tab()."""
        if bibliography.DEFAULT_BIB not in self._slide_source_tabs:
            bibliography.sort_entries()
        self.open_slide_editor(bibliography.DEFAULT_BIB, return_to=self.tabs.currentWidget())

    def open_slide_editor(
        self,
        path: Path,
        on_saved: Optional[Callable[[str], None]] = None,
        return_to: Optional[QWidget] = None,
    ) -> None:
        existing = self._slide_source_tabs.get(path)
        if existing is not None:
            if return_to is not None:
                existing.return_to = return_to
            self.tabs.setCurrentWidget(existing)
            return
        tab = SlideSourceTab(self, path, on_saved=on_saved, return_to=return_to)
        self._slide_source_tabs[path] = tab
        self.tabs.addTab(tab, path.name)
        self.tabs.setCurrentWidget(tab)
        self._set_tab_color(tab, self.theme.tab_colors()[self._slide_editor_tab_color_role(path)])

    def rename_slide_editor_tab(self, tab: SlideSourceTab, new_path: Path) -> None:
        """Re-key _slide_source_tabs after slide_rename.set_slide_language()
        moves a slide's own file out from under an already-open editor tab
        (2026-08-24) -- SlideSourceTab._on_set_language calls this right
        after a successful rename, so open_slide_editor()'s own
        already-open-tab dedup (keyed by path) keeps working against the
        file's *new* name instead of pointing at a path that no longer
        exists on disk."""
        old_path = tab.path
        self._slide_source_tabs.pop(old_path, None)
        self._slide_source_tabs[new_path] = tab
        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.setTabText(index, new_path.name)

    def close_slide_editor_tab(self, tab: SlideSourceTab) -> None:
        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.removeTab(index)
        # Return to whichever tab this slide was (most recently) opened
        # from, if it's still open -- guarded the same way gui.py's own
        # _close_tab is (the originating tab may have been closed while
        # this one was open).
        if tab.return_to is not None and self.tabs.indexOf(tab.return_to) != -1:
            self.tabs.setCurrentWidget(tab.return_to)
        self._slide_source_tabs.pop(tab.path, None)
        tab.deleteLater()
        # Close-side half of the open-side sort in _on_edit_bib(): both
        # SlideSourceTab's own "Close" (discards any unsaved edit) and
        # "Close and save" paths funnel through here already, so by this
        # point the file on disk already reflects whatever the user meant
        # to keep -- sorting it now catches any entry added/reordered
        # during this session without needing a manual sort_bib.py run.
        if tab.path == bibliography.DEFAULT_BIB:
            bibliography.sort_entries()

    def open_transcript_preview(self, key: str, title: str) -> TranscriptPreviewTab:
        """SlideSourceTab's own "Render transcript" button (2026-08-25) --
        `key` is the slide's bare id, so re-rendering the same slide
        refreshes its existing tab (via the caller's own set_html() call
        right after this returns) instead of piling up duplicates."""
        existing = self._transcript_preview_tabs.get(key)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return existing
        tab = TranscriptPreviewTab(self, title)
        self._transcript_preview_tabs[key] = tab
        self.tabs.addTab(tab, title)
        self.tabs.setCurrentWidget(tab)
        self._set_tab_color(tab, self.theme.tab_colors()["transcript"])
        return tab

    def close_transcript_preview_tab(self, tab: TranscriptPreviewTab) -> None:
        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.removeTab(index)
        for key, existing in list(self._transcript_preview_tabs.items()):
            if existing is tab:
                del self._transcript_preview_tabs[key]
        tab.deleteLater()

    def generate_deck_transcript(self, deck: Deck, version: str, *, quiet: bool = False) -> bool:
        """Whole-deck transcript generation (write_transcript(), written to
        transcripts/ or the deck's own \\deckoutputfolder[transcript]{}/
        bare \\deckoutputfolder{} override) -- shared by the deck-editor
        tab's own "Transcript" button and the main deck table's own
        "Create Transcript" button, so the success/error/log handling
        lives in exactly one place. Same synchronous-with-a-wait-cursor
        pattern the Images tab's own (now single-slide-only) generate
        button uses: this is a fast regex-based render, not a LaTeX
        compile, so no thread is needed. Returns whether it succeeded.

        quiet=True suppresses the completion dialog on success (not on
        failure) -- used by the main table's own batch "Create Transcript"
        button (2026-09-17, direct instruction: "work similarly" to
        "Create PDF", which shows no per-job completion dialog either), so
        checking During-course/After-course across several decks at once
        doesn't mean clicking through that many modal dialogs in a row.
        The deck-editor tab's own single-shot "Transcript" button keeps
        the dialog, matching every other one-off action in this app."""
        target_dir, stem = transcript.resolve_transcript_location(deck, deck.path, version)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            md_path, html_path, result = transcript.write_transcript(
                deck.path, version, directory=target_dir, filename_stem=stem)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Transcript failed", f"{deck.name} ({version}):\n{exc}")
            self._log(f"*** Transcript generation failed for {deck.path.stem} ({version}): {exc} ***")
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self._log(
            f"Transcript for {deck.path.stem} ({version}): "
            f"{len(result.slides)} of {result.total_in_deck} slides -> "
            f"{md_path.name}, {html_path.name}"
        )
        if result.undescribed:
            self._log(
                f"    {result.undescribed} slide(s) contain an image with no "
                f"description yet; those points are marked in the transcript."
            )
        if not quiet:
            QMessageBox.information(
                self, "Transcript generated",
                f"{len(result.slides)} of {result.total_in_deck} slides written to:\n\n"
                f"{md_path}\n{html_path}"
                + (f"\n\n{result.undescribed} slide(s) still have an undescribed "
                   f"image; those are flagged in place." if result.undescribed else ""),
            )
        return True

    def prompt_deck_transcript_version(self, deck: Deck) -> None:
        """Asks only for version -- used where the deck is already known
        (the deck-editor tab's own "Transcript" button, called cross-tab
        as self.app.prompt_deck_transcript_version(self.deck), same
        no-leading-underscore convention as open_deck_editor/
        open_slide_editor for anything another tab needs to call)."""
        version, ok = QInputDialog.getItem(
            self, "Generate transcript", "Version:",
            list(transcript.STUDENT_VERSIONS), 0, False,
        )
        if not ok:
            return
        self.generate_deck_transcript(deck, version)

    def _on_create_transcript_toplevel(self, rows: list[DeckRow]) -> None:
        """Main deck table's own "Create Transcript" button -- mirrors
        "Create PDF"'s own per-row During-course/After-course checkboxes
        (2026-09-17, direct instruction: "I select During-course or
        After-course for one or more decks and when I click the button,
        it should create these transcripts"): for every row with either
        checked, generate that deck's transcript for each checked student
        version, quietly (no completion dialog on success, same as
        "Create PDF" itself shows none) so a multi-deck/version batch
        doesn't mean clicking through one dialog per transcript. Only
        when nothing valid is checked anywhere -- no deck selected at
        all, or only non-transcript versions like Instructor/Presenter --
        does it fall back to asking directly, which is "a dialog box
        asking for further instructions" for exactly that case."""
        pairs: list[tuple[Deck, str]] = [
            (row.deck, version)
            for row in rows
            for version in row.selected_versions()
            if version in transcript.STUDENT_VERSIONS
        ]
        if not pairs:
            self._prompt_create_transcript_fallback()
            return
        failures = sum(
            0 if self.generate_deck_transcript(deck, version, quiet=True) else 1
            for deck, version in pairs
        )
        self._log(
            f"==== Create Transcript: {len(pairs) - failures} of {len(pairs)} "
            f"transcript(s) generated ===="
        )

    def _prompt_create_transcript_fallback(self) -> None:
        """"Create Transcript"'s own fallback dialog, for when nothing
        valid is checked on any deck row -- asks for deck, then version,
        the same two-step picker the button used before it grew per-row
        checkbox awareness."""
        deck_names = [d.name for d in scan_decks() if not d.archived]
        if not deck_names:
            QMessageBox.information(self, "No decks", "No active decks found.")
            return
        deck_name, ok = QInputDialog.getItem(
            self, "Generate transcript",
            "No deck has During-course/After-course checked -- pick one:",
            deck_names, 0, False,
        )
        if not ok:
            return
        deck = next(d for d in scan_decks() if d.name == deck_name)
        self.prompt_deck_transcript_version(deck)

    def open_add_slide_dialog(
        self, deck: Deck, insert_at: int, indent: str, return_to: Optional[QWidget] = None,
    ) -> None:
        dialog = AddSlideDialog(self, deck, insert_at, indent, return_to=return_to)
        dialog.exec()

    # -- table (re)construction ------------------------------------------------

    def reload_decks(self) -> None:
        decks = scan_decks()
        active_decks = [d for d in decks if not d.archived]
        archived_decks = [d for d in decks if d.archived]
        self.active_table.rebuild(active_decks)
        self.archived_table.rebuild(archived_decks)
        self.active_rows = self.active_table.rows
        self.archived_rows = self.archived_table.rows
        self._remap_job_status_rows()

    def _remap_job_status_rows(self) -> None:
        """Re-point _job_status_map at the fresh DeckRow objects reload_decks()
        just built, by the one thing that survives a rebuild -- the deck's
        own name. reload_decks() runs any time a deck is edited/archived/
        duplicated/tagged, none of which check self.compiling first (editing
        one deck while a *different* one compiles in the background is
        completely normal), and DeckTable.rebuild() deletes every DeckRow's
        widgets and builds new ones -- so without this, the next RUNNING/
        MOVING/PASS/FAIL log line for a job started before the rebuild calls
        set_status() on a QLabel Qt has already destroyed, raising
        RuntimeError inside _log() and silently killing the rest of that
        batch's log/status/auto-open handling (2026-09-23 review finding).
        A job whose deck no longer exists in the fresh scan (renamed/
        archived/deleted mid-compile) is dropped instead -- its row's
        _job_status_map lookup already tolerates a missing entry (a plain
        `.get()`), so this only ever narrows what future log lines can
        find, never breaks the lookup itself. A rebuilt row's own status
        labels start blank regardless -- the job's own compile keeps
        running either way, this only restores where its *next* status
        update lands."""
        if not self._job_status_map:
            return
        rows_by_deck_name = {
            row.deck.name: row for row in (*self.active_rows, *self.archived_rows)
        }
        self._job_status_map = {
            jobname: (rows_by_deck_name[row.deck.name], key)
            for jobname, (row, key) in self._job_status_map.items()
            if row.deck.name in rows_by_deck_name
        }

    def _on_refresh_decks_clicked(self) -> None:
        """DeckTable's own "Refresh decks" button (direct instruction) --
        a wait cursor for the duration of the rescan, so a scan slow enough
        to notice (every deck file re-read and re-parsed, on top of a
        rebuild of both tables' full row widget trees) has some visible
        sign it's working rather than looking like the click did nothing.
        A thin wrapper around reload_decks() itself, not reload_decks()
        directly, so its many *other* callers (after_deck_edit() and
        friends, already fast/frequent enough that a cursor flash on each
        one would just be noise) are unaffected."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.reload_decks()
        finally:
            QApplication.restoreOverrideCursor()

    # -- actions -----------------------------------------------------------

    def _archive_deck(self, deck: Deck) -> None:
        reply = QMessageBox.question(
            self, "Archive deck", f"Move {deck.name}.tex to decks/archive/?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            archive_mod.archive_deck(deck)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Archive failed", str(exc))
            return
        self._log(f"Archived {deck.name}.tex -> decks/archive/{deck.name}.tex")
        self.reload_decks()

    def _compile_rows(self, rows: list[DeckRow]) -> None:
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return
        jobs: list[CompileJob] = []
        job_status_map: dict[str, tuple[DeckRow, str]] = {}
        footer_timestamp = self.footer_timestamp_checkbox.isChecked()
        appendix_toc = self.appendix_toc_checkbox.isChecked()
        for row in rows:
            row.reset_status()
            for job in row.build_jobs():
                job.footer_timestamp = footer_timestamp
                job.appendix_toc = appendix_toc
                job_status_map[job.jobname] = (row, job_column_key(job))
                output_dir, output_stem = resolve_output_location(job)
                self._job_output_paths[job.jobname] = output_dir / f"{output_stem}.pdf"
                jobs.append(job)
        if not jobs:
            QMessageBox.information(
                self, "Nothing selected", "Check at least one version per deck to compile."
            )
            return
        self._start_jobs(jobs, job_status_map)

    def _on_edit_deck(self, deck: Deck) -> None:
        """Active decks table's own "Source" button -- straight to this
        deck's raw .tex source, without going through its slide-list
        editor tab first (open_deck_source_editor's own "Source" button
        needs a DeckEditorTab already open; this is the same underlying
        SlideSourceTab, just reached directly from the table). return_to
        is the table itself (a real page of self.tabs, same as any other
        return_to), so closing the source tab lands back on Active decks.
        """
        self.open_deck_source_editor(deck, return_to=self.active_table)

    @staticmethod
    def _tags_with_group(deck_tags: list[str], group: str) -> list[str]:
        """`group` as the deck's group tag, keeping any other tags it has."""
        return [group] + [t for t in deck_tags if t not in GROUP_TAGS]

    def _on_open_latest_pdf(self, deck: Deck) -> None:
        """Active decks table's own "Open pdf" button (2026-09-21) -- opens
        the most recently created PDF of this deck, whichever version or
        output folder it landed in (compiler.latest_pdf_for_deck())."""
        pdf_path = latest_pdf_for_deck(deck)
        if pdf_path is None:
            QMessageBox.information(
                self, "No PDF yet", f"No PDF has been created for {deck.name} yet.")
            return
        try:
            open_path.open_in_default_app(pdf_path)
        except OSError as exc:
            self._log(f"*** couldn't open {pdf_path.name}: {exc} ***")

    def _on_edit_deck_tags(self, deck: Deck) -> None:
        """A deck row's "Tags" button: choose the group the deck appears
        in. Written into the deck's own file as \\decktags{...}."""
        if deck.path in self._slide_source_tabs:
            QMessageBox.information(
                self, "Tags",
                f"{deck.name}.tex is open in a source editor tab -- close it "
                "first, so this change and that editor can't overwrite each "
                "other.",
            )
            return
        result = ask_deck_details(self, f"Tags — {deck.name}", deck.group)
        if result is None:
            return
        _name, group = result
        if group == deck.group and group in deck.tags:
            return  # already exactly that
        try:
            deck_editor.set_deck_tags(
                deck.path, deck.text, self._tags_with_group(deck.tags, group))
        except (deck_editor.StaleFileError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Tags failed", str(exc))
            return
        self._log(f"Tagged {deck.name} as {group}")
        self.refresh_open_deck_editors()

    def _on_duplicate_deck(self, deck: Deck) -> None:
        # Creation is where a deck's tag is first chosen (2026-09-19): the
        # dialog takes the copy's name and its group together, defaulting
        # to the original's group.
        result = ask_deck_details(
            self, "Duplicate deck", deck.group,
            name_prompt=f"Name for the copy of {deck.name}.tex:",
            default_name=f"{deck.name}-copy",
            validate_name=lambda n: deck_duplicate.is_valid_deck_name(n, deck.path.parent),
        )
        if result is None:
            return
        new_name, group = result
        try:
            dest = deck_duplicate.duplicate_deck(deck, new_name)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Duplicate failed", str(exc))
            return
        self._log(f"Duplicated {deck.name}.tex -> {dest.name}")
        if group != deck.group or group not in deck.tags:
            try:
                deck_editor.set_deck_tags(
                    dest, deck_editor._read(dest), self._tags_with_group(deck.tags, group))
                self._log(f"Tagged {dest.stem} as {group}")
            except (deck_editor.StaleFileError, ValueError, OSError) as exc:
                QMessageBox.warning(
                    self, "Tags",
                    f"{dest.name} was created, but tagging it as {group} failed: {exc}")
        self.reload_decks()

    def _on_export_pptx(self, deck: Deck) -> None:
        """Compiles `deck` (instructor version, direct instruction -- the
        fullest-content version, matching what update_all_previews.py's
        own snapshot refresh already treats as this project's "real"
        default) and exports the result as a .pptx with one full-page
        image per PDF page -- see pptx_export.py's own docstring for why
        one PDF page per pptx slide (every beamer overlay/reveal as its
        own slide) rather than one pptx slide per \\slide{} call, and why
        python-pptx rather than a hand-rolled OOXML package.

        Reuses self.compiling as the same single-flight guard a real
        "Create PDF" batch already checks (same message pattern as
        _on_archive_unused_content's own busy check) -- this runs a real
        latexmk invocation of its own, which can't safely run alongside
        another one."""
        if self.compiling:
            QMessageBox.information(
                self, "Busy",
                "Can't export to PowerPoint while a compile run is in "
                "progress -- wait for it to finish first.",
            )
            return
        self.compiling = True
        threading.Thread(target=self._export_pptx_bg, args=(deck,), daemon=True).start()

    def _export_pptx_bg(self, deck: Deck) -> None:
        log = self.signals.log.emit
        job = CompileJob(deck, version="instructor", chapter=None)
        log(f"==== Exporting {deck.name} to PowerPoint (instructor version) ====")
        try:
            # run_job() itself already logs its own "==== PASS/FAIL:
            # ... ====" lines (picked up by the same PASS_LOG_RE/
            # FAIL_LOG_RE-driven log handler every other compile goes
            # through, auto-opening the compiled PDF too if that
            # checkbox is on) -- nothing extra needed here for the
            # compile step itself, only for what happens after it.
            #
            # run_job() doesn't wait for the PDF's move into pdf/ (it
            # backgrounds that so one job's stuck sync client can't block
            # the rest of a batch's queue -- see its own docstring), so
            # reading .build/<jobname>.pdf right after it returns races
            # that same background thread, which copies the PDF out and
            # then deletes every .build/<jobname>.* file, this PDF
            # included -- there's nothing else queued behind a one-off
            # export, so waiting here for on_relocated costs nothing and
            # avoids reading a file that thread may have already removed.
            relocated = threading.Event()
            outcome: dict[str, object] = {"ok": False, "dest_pdf": None}

            def _on_relocated(ok: bool, dest_pdf: Path) -> None:
                outcome["ok"] = ok
                outcome["dest_pdf"] = dest_pdf
                relocated.set()

            if not run_job(job, log, on_relocated=_on_relocated):
                log(f"*** FAIL: PowerPoint export of {deck.name} -- "
                   f"compile failed, see above ***")
                return
            # Generous margin over the retry loop's own total budget --
            # this thread has nothing else to do but wait for it anyway.
            relocated.wait(PDF_MOVE_RETRY_TOTAL_SECONDS + 30)
            if not outcome["ok"]:
                log(f"*** FAIL: PowerPoint export of {deck.name} -- "
                   f"couldn't move the compiled PDF into place, see above ***")
                return
            pdf_path = outcome["dest_pdf"]
            out_path = PDF_DIR / f"{job.jobname}.pptx"
            try:
                pptx_export.export_deck_to_pptx(pdf_path, out_path, log=log)
            except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
                log(f"*** FAIL: PowerPoint export of {deck.name} -- {exc!r} ***")
                return
            log(f"==== PASS: {out_path.relative_to(PROJECT_ROOT)} ====")
            # Always opened, unlike the auto-open-PDF checkbox above --
            # this is a single, deliberate export the user just asked
            # for, not a batch that could pop open many windows
            # unattended, so there's no "maybe don't" case worth a
            # preference for.
            try:
                open_path.open_in_default_app(out_path)
            except OSError as exc:
                log(f"*** couldn't auto-open {out_path.name}: {exc} ***")
        finally:
            self.compiling = False

    def _start_jobs(
        self, jobs: list[CompileJob], job_status_map: dict[str, tuple[DeckRow, str]]
    ) -> None:
        self._job_status_map = job_status_map
        self._job_progress_texts = build_progress_texts(jobs)
        self.compiling = True
        self.cancel_token = CancelToken()
        self.active_table.set_compiling(True)
        self.archived_table.set_compiling(True)
        threading.Thread(target=self._run_jobs_thread, args=(jobs,), daemon=True).start()

    def _stop_compilation(self) -> None:
        if self.cancel_token is None or not self.compiling:
            return
        reply = QMessageBox.question(
            self,
            "Stop creation",
            "Stop the compile run? The job currently compiling will be "
            "killed immediately (including latexmk's own lualatex/biber "
            "children); anything still queued after it will be skipped.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._log("==== Stop requested -- killing current job and skipping the rest ====")
        self.cancel_token.request_stop()
        self.active_table.disable_stop_button()
        self.archived_table.disable_stop_button()

    def _run_jobs_thread(self, jobs: list[CompileJob]) -> None:
        cancel = self.cancel_token
        results = run_jobs(jobs, self.signals.log.emit, cancel=cancel)
        passed = sum(1 for ok in results.values() if ok)
        failed = len(results) - passed
        self.signals.log.emit(f"==== Done: {passed} passed, {failed} failed ====")
        self.compiling = False
        self.cancel_token = None
        # set_compiling() touches widgets -- runs via this signal (queued
        # onto the GUI thread automatically, same as the log signal above)
        # rather than being called directly from this worker thread.
        self.signals.batch_done.emit()

    def _on_batch_done(self) -> None:
        self.active_table.set_compiling(False)
        self.archived_table.set_compiling(False)

    def _empty_pdf_folder(self) -> None:
        self._empty_folder(PDF_DIR, "pdf/")

    def _remove_temp_files(self) -> None:
        if self.compiling:
            QMessageBox.information(
                self, "Busy", "Can't remove temp files while a compile run is in progress."
            )
            return
        build_files = [p for p in BUILD_DIR.iterdir() if p.is_file()] if BUILD_DIR.exists() else []
        wrapper_files = list(DECKS_DIR.rglob("_slidemage_*.tex"))
        temp_entries = list(TEMP_DIR.iterdir()) if TEMP_DIR.exists() else []
        all_files = build_files + wrapper_files
        if not all_files and not temp_entries:
            QMessageBox.information(self, "Nothing to do", "No temp files to remove.")
            return
        reply = QMessageBox.question(
            self,
            "Remove temp files",
            f"Delete {len(build_files)} file(s) in .build/, "
            f"{len(wrapper_files)} leftover wrapper file(s) in decks/, and "
            f"{len(temp_entries)} item(s) in .temp/ (the workflow scratch "
            "folder -- e.g. a PPTX mid-conversion or an image waiting to "
            "be cropped -- not just build output)?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for p in all_files:
            p.unlink(missing_ok=True)
        for p in temp_entries:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        self._log(
            f"Removed {len(all_files)} temp file(s) "
            f"({len(build_files)} in .build/, {len(wrapper_files)} wrapper file(s) in decks/) "
            f"and {len(temp_entries)} item(s) in .temp/"
        )

    def _on_archive_unused_content(self) -> None:
        if self.compiling:
            QMessageBox.information(
                self,
                "Busy",
                "Can't archive unused content while a compile run is in "
                "progress -- a running compile could still need a file this "
                "would move.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Archive unused content",
            "Scan media/ and slides/ for files no longer referenced by any "
            "slide or deck (including archived decks) and move them into "
            "media/archive/ and slides/archive/? Files can be moved back by "
            "hand afterwards if needed.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        threading.Thread(target=self._run_archive_unused_content, daemon=True).start()

    def _run_archive_unused_content(self) -> None:
        archive_unused_content(self.signals.log.emit)

    def _on_sync_translation_links(self) -> None:
        """Refreshes translation cross-reference comments from current
        disk state -- pure text scanning over slides/, no compile
        involved, so (unlike Archive unused content/Update previews) this
        runs synchronously rather than on a background thread."""
        changed, missing = slide_rename.regenerate_translation_links()
        self._log(f"Sync translation links: {changed} file(s) updated")
        for line in missing:
            self._log(f"    (unresolved: {line})")
        if missing:
            QMessageBox.warning(
                self, "Sync translation links",
                f"{changed} file(s) updated. {len(missing)} link(s) could "
                "not be resolved -- see the log pane for details.",
            )

    def _on_update_previews(self) -> None:
        """No template picker any more (2026-08-16, direct instruction:
        "I forgot that each deck has a specific template linked to it" --
        there's nothing to pick, every deck already carries its own).
        Scans every deck for which (template, slide) combinations it
        actually needs (update_all_previews.needed_slides_by_template())
        and shows that in the confirmation dialog, so the count reflects
        exactly what's about to be compiled -- not "every slide file in
        the project" the way the old single-template design counted.
        """
        if self.compiling:
            QMessageBox.information(self, "Busy", "A compile run is already in progress.")
            return

        needed = update_all_previews.needed_slides_by_template()
        if not needed:
            QMessageBox.information(
                self, "Nothing to do", "No deck references any slides right now."
            )
            return
        total_slides = sum(len(ids) for ids in needed.values())
        template_names = [
            slide_snapshot.TEMPLATES.get(t, t) for t in sorted(needed)
        ]
        reply = QMessageBox.question(
            self, "Update previews",
            f"Scan every deck (active and archived) and refresh preview "
            f"snapshots for {total_slides} slide-template combination(s) "
            f"across {', '.join(template_names)}? Cached previews no "
            f"longer used by any deck are deleted afterward.\n\nThis is "
            f"one very long compile (well over an hour is plausible for "
            f"this many slides) -- it runs in the background, but "
            f"occupies the compile slot, so no other compile can start "
            f"until it's done.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.compiling = True
        self.cancel_token = CancelToken()
        self.active_table.set_compiling(True)
        self.archived_table.set_compiling(True)
        # _log()'s RUNNING_LOG_RE handling looks up a human-readable status
        # line in self._job_progress_texts by jobname -- normally populated
        # by _start_jobs() from the real compile queue, but this operation
        # builds its own temp deck/CompileJob entirely inside
        # update_all_previews.run(), with no channel back to this class
        # except the log stream. Without registering an entry here first,
        # each template's own "==== Compiling ... ====" line still matches
        # RUNNING_LOG_RE fine, but the lookup finds nothing and the status
        # line by "Log:" just stays blank for the whole run. One jobname
        # per template (there can be several, run one after another), all
        # generated here rather than left to run() so both sides agree on
        # the exact strings ahead of time. "-instructor" matches
        # CompileJob.jobname's own "-{version}" suffix (compiler.py) --
        # update_all_previews.run() always compiles the instructor version.
        base_jobnames = {
            template: f"{update_all_previews.JOBNAME_PREFIX}{uuid.uuid4().hex[:8]}"
            for template in needed
        }
        self._job_progress_texts = {
            f"{base_jobname}-instructor":
                f"Update previews ({slide_snapshot.TEMPLATES.get(template, template)})"
            for template, base_jobname in base_jobnames.items()
        }
        threading.Thread(
            target=self._run_update_previews_thread, args=(needed, base_jobnames), daemon=True
        ).start()

    def _run_update_previews_thread(
        self, needed: dict[str, set[str]], base_jobnames: dict[str, str]
    ) -> None:
        cancel = self.cancel_token
        try:
            ok = update_all_previews.run(
                self.signals.log.emit, cancel=cancel,
                base_jobnames=base_jobnames, needed=needed,
            )
        except Exception as exc:  # noqa: BLE001 -- reported, batch must still clean up state
            self.signals.log.emit(f"*** Update previews failed: {exc} ***")
            ok = False
        self.signals.log.emit(
            "==== Update previews: compile finished ====" if ok
            else "==== Update previews: FAILED ===="
        )
        self.compiling = False
        self.cancel_token = None
        # set_compiling() touches widgets -- runs via this signal (queued
        # onto the GUI thread automatically), same as _run_jobs_thread's
        # own use of it.
        self.signals.batch_done.emit()

    def _empty_folder(self, folder: Path, label: str) -> None:
        if not folder.exists():
            QMessageBox.information(self, "Nothing to do", f"{label} doesn't exist yet.")
            return
        files = [p for p in folder.iterdir() if p.is_file()]
        if not files:
            QMessageBox.information(self, "Nothing to do", f"{label} is already empty.")
            return
        reply = QMessageBox.question(self, "Empty folder", f"Delete all {len(files)} file(s) in {label}?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        for p in files:
            p.unlink(missing_ok=True)
        self._log(f"Emptied {label} ({len(files)} file(s) deleted)")

    def _open_pdf(self, jobname: str) -> None:
        pdf_path = self._job_output_paths.get(jobname, PDF_DIR / f"{jobname}.pdf")
        if not pdf_path.exists():
            return
        try:
            open_path.open_in_default_app(pdf_path)
        except OSError as exc:
            self._log(f"*** couldn't auto-open {pdf_path.name}: {exc} ***")

    def _tick_spinner(self) -> None:
        self._spinner_frame += 1
        for row in self.active_rows + self.archived_rows:
            row.tick_spinner(self._spinner_frame)

    # -- log pane (main-thread only, via the signals.log connection) --------

    def _log(self, line: str) -> None:
        self.log_text.appendPlainText(line)

        render_start = RENDER_START_RE.match(line)
        if render_start:
            self._current_progress_base = f"Rendering {render_start.group(1)}"
            self.status_label.setText(f"{self._current_progress_base}: starting...")
            return
        render_pass = RENDER_PASS_RE.match(line)
        if render_pass:
            self.status_label.setText(f"Done: rendered {render_pass.group(1)}")
            self._current_progress_base = ""
            return
        render_fail = RENDER_FAIL_RE.match(line)
        if render_fail:
            self.status_label.setText(f"Render failed: {render_fail.group(1)}")
            self._current_progress_base = ""
            return

        for pattern, status in (
            (RUNNING_LOG_RE, "running"),
            (MOVING_LOG_RE, "moving"),
            (PASS_LOG_RE, "pass"),
            (FAIL_LOG_RE, "fail"),
        ):
            match = pattern.match(line)
            if match:
                jobname = match.group(1)
                entry = self._job_status_map.get(jobname)
                if entry is not None:
                    row, key = entry
                    row.set_status(key, status)
                # "Update previews"' own temp megadeck (update_all_previews.py)
                # shares this same PASS log line with no other channel back to
                # the GUI -- excluded here unconditionally, not gated on the
                # checkbox, since nobody wants a 639-slide throwaway PDF
                # popping open regardless of their normal auto-open preference.
                is_preview_all = jobname.startswith(update_all_previews.JOBNAME_PREFIX)
                if status == "pass" and self.auto_open_checkbox.isChecked() and not is_preview_all:
                    self._open_pdf(jobname)
                if status in ("running", "moving"):
                    base = self._job_progress_texts.get(jobname, "")
                    if status == "running":
                        self._current_progress_base = base
                        if base:
                            self.status_label.setText(f"{base}: starting...")
                    elif base:
                        self.status_label.setText(f"{base}: compiled, relocating PDF...")
                break
        else:
            done_match = DONE_LOG_RE.match(line)
            if done_match:
                self.status_label.setText(f"Done: {done_match.group(1)}")
                return
            run_match = RUN_NUMBER_RE.match(line)
            if run_match and self._current_progress_base:
                run_number = run_match.group(1)
                self.status_label.setText(f"{self._current_progress_base}: Compile {run_number}...")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    theme = ThemeManager()
    theme.apply()
    window = SlideMageWindow(theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
