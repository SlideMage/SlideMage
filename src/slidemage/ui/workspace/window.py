"""The main window of the redesigned UI (docs/UI_REDESIGN_PLAN.md, step 3).

A top bar (topbar.py) over three columns -- slide list, centre, side panels --
with the compile log underneath. The shared WorkspaceState (state.py) holds
the current deck, view and language; the top bar and the columns read and
write it instead of each other.

The left column is the slide
list (slide_list.py), the centre the Preview / Source / Split / Details views
of the focused slide (centre.py), or the Images page (pages/images.py), which
takes the width of all three columns while it is shown. The window's other
duties are plain functions next to it: compile flows (compile_actions.py), deck
actions (deck_actions.py) and project maintenance (maintenance.py). Builds belong to
the compile controller (compile_controller.py); the window shows them (compile_display.py).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import app_settings, bibliography, deck_headers, deck_outline, latex_edit, project, updater
from ... import version as version_mod
from ...ai.providers import ChatProvider
from ...deck_scan import Deck, scan_decks
from .. import layout_settings
from ..dialogs.add_slide import AddSlideSheet
from ..dialogs.import_presentation import ImportPresentationSheet
from ..dialogs.open_project import OpenProjectSheet
from ..dialogs.settings import SettingsSheet
from ..kit.kit_qss import WARNING_LABEL
from ..kit.theme import ThemeManager
from ..kit.widgets import Toast
from ..pages.images import ImagesPage
from ..pages.no_decks import NoDecksPage
from ..text import plural
from . import side_panels, slide_list
from .actions import build_registry
from .centre import CentreColumn
from . import maintenance
from .build_options import BuildOptionsDialog
from .compile_controller import CompileController
from .compile_display import CompileDisplay
from .palette import CommandPalette
from .panels.base import PanelActions
from .side_panels import SidePanels
from .slide_list import SlideList
from .state import WorkspaceState
from .topbar import TopBar

# Settings key of the deck that was open when the app was last closed.
LAST_DECK_KEY = "last_deck"


class _ColumnHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            splitter = self.splitter()
            splitter.reset_column.emit(splitter.indexOf(self))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class _ColumnSplitter(QSplitter):
    reset_column = Signal(int)

    def createHandle(self) -> QSplitterHandle:
        return _ColumnHandle(self.orientation(), self)


class _CurrentPageStack(QStackedWidget):
    """Let the shown page, rather than the widest hidden page, size the centre."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(self.updateGeometry)

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()


class WorkspaceWindow(QMainWindow):
    update_check_done = Signal(object)   # the startup update check's result (updater.UpdatePlan or UpdateError)

    def __init__(self, theme: ThemeManager, project_context: project.ProjectContext) -> None:
        super().__init__()
        self.theme = theme
        self.project = project_context
        self.compile = CompileController(project_context, self)
        self.setWindowTitle(f"SlideMage — {version_mod.VERSION}")
        self.setMinimumSize(1024, 640)
        if updater.can_self_update():
            updater.remove_leftover_binary(Path(sys.executable))

        # Open Project... relaunches the process only after the same dirty
        # editor resolution used by closeEvent. That path has already
        # recorded the user's Save/Discard choice, so the subsequent close
        # must not ask a second time.
        self._dirty_edits_resolved_for_close = False
        self.decks: list[Deck] = []
        # Global mutual-exclusion for anything that calls Ollama (image
        # drafting, image translation, and the "Duplicate slide" dialog's
        # auto-translate option) -- None when idle, else a short label of
        # whatever currently holds it. Direct report, 2026-08-25: running a
        # drafting batch and a translation at the same time crashed, most
        # likely two different models loaded into VRAM simultaneously (a
        # local Ollama server's own resource limit, not a bug this app can
        # fix). See try_start_ollama_task()/end_ollama_task() below.
        self._ollama_task_label: Optional[str] = None

        self.state = WorkspaceState(self.project, self)
        self.commands = build_registry()
        self.left_column_hidden = layout_settings.get("left_column_hidden", False) is True
        self.right_column_hidden = layout_settings.get("right_column_hidden", False) is True
        self.build_options = BuildOptionsDialog(self, self.state)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.topbar = TopBar(self)
        outer.addWidget(self.topbar)
        snapshot_banner = self._build_snapshot_banner()
        if snapshot_banner is not None:
            outer.addWidget(snapshot_banner)

        # Left: the slide list, right: side panels with the assistant (chat) area below them.
        self.splitter = _ColumnSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.slide_list = SlideList(self, self.state, theme, Toast(central))
        self.side_panels = SidePanels(self, self.state, PanelActions(
            slide_text=lambda path: self.centre.slide_text(path), is_dirty=lambda path: self.centre.is_dirty(path),
            edit_slide_text=lambda path, change: self.centre.edit_slide_text(path, change),
            save_source=lambda: self.centre.source.save(),
            restore_version=lambda path: self.centre.restore_version(path),
            freeze_version=lambda id_slug, level: self.centre.freeze_version(id_slug, level),
            edit_deck=self.slide_list.edit, add_slide=self.slide_list.add_slide,
            add_reference=lambda key: self.centre.source.add_reference(key)))
        self.assistant = self.side_panels.assistant
        # Centre: the views of the focused slide, or the Images page. Its first scan reads every
        # slide that includes an image, hashes those images' bytes (~1s) and syncs the store --
        # deferred to the first time the page is shown (_on_page_changed) rather than paid on every
        # launch, and deliberately not a launch-time *write* to media/alt-text.json.
        self.stack = _CurrentPageStack()
        self.centre = CentreColumn(self, self.state)
        self.stack.addWidget(self.centre)
        self.images_page = ImagesPage(self, self.state)
        self.images_page.closed.connect(self._toggle_images)
        self.stack.addWidget(self.images_page)
        self.stack.currentChanged.connect(self._on_page_changed)
        for column in (self.slide_list, self.stack, self.side_panels):
            self.splitter.addWidget(column)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(1, False)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self.splitter.reset_column.connect(self._reset_column_width)
        self._columns_sized = False
        self._apply_column_visibility()
        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 12, 12, 12)
        workspace_layout.addWidget(self.splitter)
        self.no_decks = NoDecksPage(self)
        self.body = QStackedWidget()      # the workspace, or the page for a project without decks
        self.body.addWidget(workspace)
        self.body.addWidget(self.no_decks)
        outer.addWidget(self.body, 1)
        self.setCentralWidget(central)
        self.compile_display = CompileDisplay(self, central)
        self.update_check_done.connect(
            lambda result: maintenance.on_startup_update_check_done(self, result))

        self.palette = CommandPalette(self)
        self.commands.bind_shortcuts(self)
        self.topbar.command.connect(self._on_command)
        self.topbar.mode_clicked.connect(lambda: self.stack.setCurrentWidget(self.centre))   # leaves the Images page
        self.state.deck_changed.connect(self._remember_deck)
        self.state.dirty_changed.connect(self._on_dirty_changed)
        self.centre.preview.rendered.connect(self.slide_list.rebuild)   # a render may have captured a thumbnail
        self.centre.source.file_closed.connect(self._on_source_closed)
        self.centre.versions_changed.connect(self.side_panels.refresh)
        self.centre.source.reference_added.connect(self.side_panels.refresh)
        # Ctrl+S saves the file open in the Source view whichever view has the focus.
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.centre.source.save)
        # Ctrl+Enter renders the editor's buffer, saved or not, and shows the page (Ctrl+R in the Source view too).
        for sequence in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(sequence), self).activated.connect(self.centre.render_buffer)
        # Ctrl+Shift+F, the old project-wide text search, opens the palette, where that search is now.
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(self.palette.toggle)

        self.reload_decks()
        self._restore_window_geometry()

    def _restore_window_geometry(self) -> None:
        saved = layout_settings.get("window_geometry")
        if isinstance(saved, str) and self.restoreGeometry(QByteArray.fromBase64(saved.encode("utf-8"))):
            if any(self.frameGeometry().intersects(screen.availableGeometry()) for screen in QApplication.screens()):
                return
        self.setWindowState(Qt.WindowState.WindowNoState)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(available.size() * 0.9)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    # -- column widths and visibility ------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._columns_sized:
            self._columns_sized = True
            self.set_column_widths(left=slide_list.remembered_width(), right=side_panels.remembered_width(self.project))

    def set_column_widths(self, *, left: Optional[int] = None, right: Optional[int] = None) -> None:
        """Size either column within its limits, taking the difference from the centre."""
        sizes = self.splitter.sizes()
        left = min(max(sizes[0] if left is None else left, slide_list.MIN_WIDTH), slide_list.MAX_WIDTH)
        right = min(max(sizes[2] if right is None else right, side_panels.WIDTH), side_panels.MAX_WIDTH)
        if self.slide_list.isHidden():
            left = 0
        if self.side_panels.isHidden():
            right = 0
        self.splitter.setSizes([left, max(sum(sizes) - left - right, 1), right])

    def _toggle_column(self, side: str) -> None:
        self._set_column_hidden(side, not getattr(self, side + "_column_hidden"))

    def _set_column_hidden(self, side: str, hidden: bool) -> None:
        column, index, settings = (self.slide_list, 0, slide_list) if side == "left" else (
            self.side_panels, 2, side_panels)
        width = self.splitter.sizes()[index]
        if hidden and not column.isHidden() and width > 0:
            layout_settings.set(settings.WIDTH_SETTING, width)
        key = side + "_column_hidden"
        setattr(self, key, hidden)
        layout_settings.set(key, hidden)
        self._apply_column_visibility()

    def _apply_column_visibility(self) -> None:
        # Images temporarily uses both columns' room without changing the user's preferences.
        is_images = self.stack.currentWidget() is self.images_page
        self.slide_list.setVisible(not is_images and not self.left_column_hidden)
        self.side_panels.setVisible(not is_images and not self.right_column_hidden)
        if self._columns_sized:
            self.set_column_widths(left=slide_list.remembered_width(), right=side_panels.remembered_width(self.project))
        self.topbar.refresh_column_toggles()

    def _reset_column_width(self, index: int) -> None:
        self.set_column_widths(left=slide_list.WIDTH if index == 1 else None,
                               right=side_panels.WIDTH if index == 2 else None)
        self._on_splitter_moved(0, index)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        # The Images page hides the columns: not the user's choice.
        sizes = self.splitter.sizes()
        collapsed = []
        for side, index, column, settings in (("left", 0, self.slide_list, slide_list),
                                              ("right", 2, self.side_panels, side_panels)):
            if column.isVisible():
                if sizes[index] == 0:
                    collapsed.append(side)
                else:
                    layout_settings.set(settings.WIDTH_SETTING, sizes[index])
        for side in collapsed:
            self._set_column_hidden(side, True)

    # -- commands --------------------------------------------------------------

    def _on_command(self, command_id: str) -> None:
        self.commands.run(command_id, self)

    # -- decks -----------------------------------------------------------------

    def reload_decks(self) -> None:
        """Rescans the decks. The current deck stays (a fresh object for the
        same file), follows its file when archived, or falls back to the one
        that was open last time, else the first active deck."""
        self.decks = scan_decks(self.project)
        self.topbar.set_decks(self.decks)
        self.body.setCurrentWidget(self.no_decks if not self.decks else self.body.widget(0))
        if not self.decks:
            self.no_decks.refresh()
        current = self.state.deck
        remembered = app_settings.get(self.project, LAST_DECK_KEY)
        by_path = next((d for d in self.decks if current and d.path == current.path), None)
        by_name = next((d for d in self.decks if current and d.name == current.name), None)
        last = next((d for d in self.decks if d.name == remembered), None)
        first_active = next((d for d in self.decks if not d.archived), None)
        switched = self.state.set_deck(by_path or by_name or last or first_active or next(iter(self.decks), None))
        if not switched:   # a fresh scan of the open deck is no switch (state.set_deck): nothing told the views
            self.slide_list.rebuild()
            self.centre.refresh()
            self.side_panels.refresh()

    def _remember_deck(self, deck: Optional[Deck]) -> None:
        if deck is not None:
            app_settings.set(self.project, LAST_DECK_KEY, deck.name)

    def _on_refresh_decks_clicked(self) -> None:
        """⋮ -> "Refresh decks": a wait cursor for the duration of the rescan,
        so a scan slow enough to notice (every deck file re-read and
        re-parsed) has some visible sign it's working rather than looking
        like the click did nothing. A thin wrapper around reload_decks()
        itself, so its many *other* callers (after_deck_edit() and friends,
        already fast/frequent enough that a cursor flash on each one would
        just be noise) are unaffected."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            deck_outline.forget_lint()   # the bibliography or an image may have changed on disk
            self.reload_decks()
        finally:
            QApplication.restoreOverrideCursor()

    # -- the centre column's pages ---------------------------------------------

    def _on_page_changed(self, index: int) -> None:
        """Tell the top bar whether Images is open; the page takes the room of the slide list and the
        side panels, and scans the slides when it is first shown. Leaving it saves a pending edit."""
        is_images = self.stack.widget(index) is self.images_page
        self.topbar.set_images_open(is_images)
        self._apply_column_visibility()
        if is_images:
            self.images_page.ensure_loaded()
        else:
            try:
                self.images_page.flush()
            except Exception as exc:  # noqa: BLE001 -- the edits stay in the page (and in the close prompt)
                QMessageBox.critical(self, "Save failed", f"Could not save image edits: {exc}")

    def _toggle_images(self) -> None:
        self.stack.setCurrentWidget(self.centre if self.stack.currentWidget() is self.images_page else self.images_page)

    def open_images_for_slide(self, id_slug: str) -> None:
        """The slide list's "Images" entry: opens the Images page and lands on that slide's images."""
        self.stack.setCurrentWidget(self.images_page)
        self.images_page.show_slide(id_slug)

    def _show_chat(self) -> None:
        self.stack.setCurrentWidget(self.centre)   # the Images page hides the right column
        self.assistant.show_view("chat")

    def ask_chat(self, text: str) -> None:
        """Put `text` to the chat as a question about the focused slide (the command palette)."""
        self._show_chat()
        self.assistant.chat.ask(text, "slide")

    def focus_chat(self) -> None:
        """Open the chat on the focused slide with the cursor in the message box (the Source view's Tools menu)."""
        self._show_chat()
        self.assistant.chat.focus_composer("slide")

    def open_slide_editor(
        self, path: Path, on_saved: Optional[Callable[[str], None]] = None, line: Optional[int] = None,
    ) -> None:
        """Show a file in the Source view: a slide, a deck's own source or Slidemaster.bib.
        `on_saved(previous_text)` runs after each save; `line` puts the cursor there."""
        self.stack.setCurrentWidget(self.centre)
        self.centre.open_file(path, on_saved, line)

    def _on_source_closed(self, path: Path) -> None:
        """Close-side half of the open-side sort in _on_edit_bib(): the file on disk
        already holds whatever the user meant to keep, so sorting it now catches
        any entry added or reordered during the session without a manual
        sort_bib.py run."""
        if path == self.project.bibliography_path:
            bibliography.sort_entries(path)

    def _on_dirty_changed(self, dirty: bool) -> None:
        if not dirty:
            self.slide_list.rebuild()   # a save changes lint errors and stale previews
            self.side_panels.refresh()  # and the slide's versions

    # -- deck resync after edits -----------------------------------------------

    def resync_deck(self, deck_path: Path) -> Optional[Deck]:
        """Re-scans every deck (like Refresh decks) and returns this one's
        fresh Deck snapshot -- called after any edit made through the slide
        list, so the current deck never goes stale."""
        self.reload_decks()
        return next((deck for deck in self.decks if deck.path == deck_path), None)

    @property
    def compiling(self) -> bool:
        return self.compile.running

    def log(self, line: str) -> None:
        """Append to the Log drawer, from any thread."""
        self.compile.log.emit(line)

    def closeEvent(self, event) -> None:
        """Resolve unsaved source and image edits before application exit; a compile run is stopped."""
        if self.compiling and QMessageBox.question(
                self, "Compile running", "A compile run is in progress. Stop it and quit?"
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        if not self._dirty_edits_resolved_for_close and not self._resolve_dirty_edits():
            event.ignore()
            return
        self.centre.source.stop_ai_checks()   # no worker thread outlives the window
        self.assistant.shutdown()
        self.images_page.shutdown()
        self.palette.stop_search(5000)
        self.compile.shutdown()
        layout_settings.set("window_geometry", self.saveGeometry().toBase64().data().decode("ascii"))
        super().closeEvent(event)

    def _resolve_dirty_edits(self) -> bool:
        """Return False when the user cancels or any requested save fails."""
        dirty_files = self.centre.source.dirty_files()
        panels = self.side_panels.dirty_panels() + ([self.images_page] if self.images_page.dirty else [])
        if dirty_files or panels:
            unsaved = [plural(len(dirty_files), "unsaved file")] if dirty_files else []
            if panels:
                unsaved.append("edits in the " + " and ".join(p.title for p in panels) + " panel"
                               + ("s" if len(panels) > 1 else ""))
            choice = QMessageBox.question(
                self,
                "Unsaved source edits",
                f"Save changes in {' and '.join(unsaved)} before closing?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return False
            if choice == QMessageBox.StandardButton.Yes:
                self.side_panels.flush()   # speaker notes go into their file's buffer, saved below
                try:
                    self.images_page.flush()
                except Exception as exc:  # noqa: BLE001 -- keep app open on save failure
                    QMessageBox.critical(self, "Save failed", f"Could not save image edits: {exc}")
                    return False
                for file in self.centre.source.dirty_files():
                    try:
                        saved = file.save()
                    except Exception as exc:  # noqa: BLE001 -- keep app open on save failure
                        QMessageBox.critical(
                            self, "Save failed",
                            f"Could not save {file.path.name}: {exc}",
                        )
                        return False
                    # save() returns False on a cancelled version dialog,
                    # stale disk content, or any other handled save failure.
                    if not saved or file.dirty:
                        return False
        return True

    def _on_open_project(self) -> None:
        """⋮ → "Open project…": the project picker (recent projects, any folder, a new project).

        Restarts the whole application rather than switching in place (see
        project.relaunch_with_project): the window, its caches and its jobs
        all hold the ProjectContext they were built with."""
        if self.compiling:
            QMessageBox.information(
                self, "Busy",
                "Can't switch projects while a compile run is in progress -- "
                "wait for it to finish first.",
            )
            return
        sheet = OpenProjectSheet(self, current=self.project.root, needs_check=maintenance.project_needs_check)
        sheet.exec()
        chosen_path = sheet.chosen
        if chosen_path is None or chosen_path == self.project.root:
            return  # cancelled, or already open -- nothing to restart for
        if not self._resolve_dirty_edits():
            return
        project.relaunch_with_project(chosen_path)
        self._dirty_edits_resolved_for_close = True
        self.close()

    def _on_import_presentation(self) -> None:
        ImportPresentationSheet(self, self.state.deck).exec()

    def _on_open_settings(self) -> None:
        sheet = SettingsSheet(self)
        sheet.exec()
        if sheet.loaded:        # the model pickers that are open follow a changed default
            self.images_page.refresh_model_preferences(sheet.available_models, sheet.vision_models)
            self.centre.refresh_model_preferences(sheet.available_models)
            self.assistant.chat.refresh_route()

    def set_dark_mode(self, checked: bool) -> None:
        """Called from the Settings sheet's Dark mode checkbox; theme.set_dark() also
        persists the choice (QSettings, per-machine -- see ui/kit/theme.py)."""
        self.theme.set_dark(checked)
        self.assistant.refresh_colors()
        # QSS covers every ordinary widget automatically, but a
        # QSyntaxHighlighter's own tag colors live on the text document,
        # outside the stylesheet mechanism entirely -- each open editor's
        # highlighter needs an explicit nudge to pick up the new palette and re-run.
        self.centre.refresh_colors()

    def set_tab_width_chars(self, chars: int) -> None:
        """Called from the Settings sheet's tab-width spinbox, like set_dark_mode() above: persist
        the choice (app_settings.py), then nudge every already-open slide/deck-source editor to pick
        it up immediately rather than only on next open."""
        app_settings.set(self.project, latex_edit.TAB_WIDTH_SETTING_KEY, chars)
        self.centre.set_tab_width(chars)

    def after_deck_edit(
        self, deck_path: Path, summary: str, previous_text: Optional[str] = None
    ) -> None:
        """Shared post-edit sequence for every deck edit through the slide list
        or a dialog -- header-sync in the background, rescan (which redraws the
        list), then log a summary line and tell the list, which keeps
        `previous_text` for its Undo."""
        threading.Thread(target=self._regenerate_headers_bg, daemon=True).start()
        self.resync_deck(deck_path)
        self.slide_list.deck_edited(deck_path, summary, previous_text)
        self.log(summary)

    def refresh_open_deck_editors(self) -> None:
        """Re-scans the decks and redraws the slide list from current disk state
        (2026-08-25) -- for an edit that can touch more than one deck at once and
        has no single deck_path to hand after_deck_edit()
        (slide_rename.set_slide_language() rewrites every deck reference
        to a renamed slide, across however many decks reference it).
        Without this, the list kept showing a slide under its old id-slug
        after a rename. Doesn't re-run deck_headers.regenerate_headers(self.project) itself
        -- a caller that needs that has already run it (set_slide_language()
        always does, as its own last step)."""
        self.reload_decks()

    def try_start_ollama_task(self, label: str, provider: Optional[ChatProvider] = None) -> bool:
        """Reserves the single app-wide Ollama slot for `label` (a short
        present-participle phrase, e.g. "drafting descriptions" --
        appears in the busy message below). Returns False, and shows why,
        if another Ollama-dependent task already holds it -- every call
        site (the Images page's drafting, translating and prompt tuning; the
        Add slide sheet's and the Ask AI to fix panel's requests) must call this before issuing its own first
        Ollama request and end_ollama_task() when that request (or batch of
        them) is fully done, whether it ran on a background thread or
        blocked the GUI thread synchronously. This is deliberately a single
        global slot, not a smarter per-model or per-resource scheduler --
        running two Ollama-dependent tasks at once has been observed to
        crash (2026-08-25, direct report), almost certainly from two
        different models being loaded into VRAM simultaneously, which is a
        limit of the local Ollama server itself, not something this app can
        negotiate around.

        A task on a cloud `provider` needs no slot (and takes none, so it
        neither waits for a local task nor makes one wait); every call
        passes the provider to both calls. No provider means Ollama."""
        if provider is not None and not provider.is_local:
            return True
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

    def end_ollama_task(self, provider: Optional[ChatProvider] = None) -> None:
        if provider is None or provider.is_local:
            self._ollama_task_label = None

    def _regenerate_headers_bg(self) -> None:
        changed, n_decks = deck_headers.regenerate_headers(self.project)
        self.log(
            f"==== Header sync: {changed} slide file(s) updated across {n_decks} deck(s) ===="
        )

    def open_deck_source_editor(self, deck: Deck) -> None:
        """⋮ -> "Edit deck source" -- opens the deck's raw .tex file in the same
        editor used for a slide's own source. A save is routed through the same
        after_deck_edit() pipeline every list action already uses, so a hand-edit
        gets header-sync, the slide list redrawn, and an Undo entry exactly like
        any other deck edit."""
        self.open_slide_editor(
            deck.path,
            on_saved=lambda previous_text: self.after_deck_edit(
                deck.path, f"Edited {deck.name}'s source directly", previous_text=previous_text
            ),
        )

    def _on_edit_bib(self) -> None:
        """"⋮ -> "Edit .bib" (a plain toolbar button until
        2026-08-25) -- opens Slidemaster.bib in the same editor used
        for a slide's/deck's own .tex source. That editor
        already degrades gracefully for a non-slide path, so no separate
        editor was needed just for this.

        Sorted on disk *before* opening (2026-08-18, direct instruction:
        keep Slidemaster.bib sorted automatically on open/close of this tab
        rather than needing a manual sort_bib.py run) -- only when actually
        creating a new tab, not when this just re-focuses an already-open
        one, so a mid-edit buffer is never silently reloaded out from under
        the user. The matching close-side sort lives in
        _on_source_closed()."""
        if self.centre.source.file_for(self.project.bibliography_path) is None:
            bibliography.sort_entries(self.project.bibliography_path)
        self.open_slide_editor(self.project.bibliography_path)

    def _on_edit_test_slides(self) -> None:
        """"Tabs -> Edit test-slides.tex" -- opens decks/test-slides.tex in
        source mode, like "Edit .bib" does for Slidemaster.bib."""
        path = self.project.decks_dir / "test-slides.tex"
        if not path.is_file():
            QMessageBox.warning(self, "Edit test-slides.tex", f"{path} does not exist.")
            return
        self.open_slide_editor(path)

    def open_add_slide_dialog(self, deck: Deck, insert_at: int, indent: str, **start) -> None:
        """The Add slide sheet for a place in `deck`; `start`: where, source, slide, target
        (AddSlideSheet)."""
        AddSlideSheet(self, deck, insert_at, indent, **start).exec()

    def _build_snapshot_banner(self) -> Optional[QLabel]:
        """A line above the tabs when the open project is a deck snapshot:
        what it is, and that SlideMage leaves it as it was (no compatibility
        migrations, no framework updates; compiles use the snapshot's own
        framework, PDF dates and footer timestamps)."""
        info = project.snapshot_info(self.project.root)
        if info is None:
            return None
        manifest = project.snapshot_manifest(self.project.root)
        made_with = manifest.get("slidemage", {}).get("version", "?")
        when = str(info.get("created", ""))[:16].replace("T", " ")
        label = QLabel(
            f"Deck snapshot of {info.get('deck_name', '?')}, taken {when} with SlideMage "
            f"{made_with}. SlideMage doesn't update it, and compiles reproduce it as it "
            "was -- but anything you edit here changes the snapshot.")
        label.setObjectName(WARNING_LABEL)
        label.setWordWrap(True)
        return label

