"""The main window of the redesigned UI (docs/UI_REDESIGN_PLAN.md, step 3).

A top bar (topbar.py) over three columns -- slide list, centre, side panels --
with the compile log underneath. The shared WorkspaceState (state.py) holds
the current deck, view and language; the top bar and the columns read and
write it instead of each other.

The window replaces qt_gui.py's tabbed window. The left column is the slide
list (slide_list.py), the centre the Preview / Source / Split / Details views
of the focused slide (centre.py). Steps 9 and 10 replace the old pages the
centre column's stack still hosts, each marked "replaced in step N" below:
the Images page and the transcript previews. The window's other duties live
in mixins next to it: compile orchestration (compile_jobs.py), deck actions
(deck_actions.py) and project maintenance (maintenance.py).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import app_settings, bibliography, deck_headers, deck_outline, latex_edit, project, updater
from ... import version as version_mod
from ...ai.providers import ChatProvider
from ...deck_scan import DECKS_DIR, PROJECT_ROOT, Deck, scan_decks
from ...qt_add_slide_dialog import AddSlideDialog
from ...qt_import_dialog import ImportPresentationDialog
from ...qt_settings_dialog import SettingsDialog
from ...qt_transcript_preview_tab import TranscriptPreviewTab
from ...qt_transcript_tab import TranscriptTab
from ..kit.theme import WARNING_LABEL, ThemeManager
from ..kit.widgets import Toast
from .actions import build_registry
from .centre import CentreColumn
from .compile_jobs import BuildOptionsDialog, CompileJobsMixin
from .deck_actions import DeckActionsMixin
from .maintenance import MaintenanceMixin
from .palette import CommandPalette
from .side_panels import SidePanels
from .slide_list import SlideList
from .state import WorkspaceState
from .topbar import TopBar

# Settings key of the deck that was open when the app was last closed.
LAST_DECK_KEY = "last_deck"


class WorkspaceWindow(MaintenanceMixin, DeckActionsMixin, CompileJobsMixin, QMainWindow):
    def __init__(self, theme: ThemeManager) -> None:
        super().__init__()
        self.theme = theme
        self.setWindowTitle(f"SlideMage — {version_mod.VERSION}")
        self.resize(1280, 860)
        if updater.can_self_update():
            updater.remove_leftover_binary(Path(sys.executable))

        # Open Project... relaunches the process only after the same dirty
        # editor resolution used by closeEvent. That path has already
        # recorded the user's Save/Discard choice, so the subsequent close
        # must not ask a second time.
        self._dirty_edits_resolved_for_close = False
        self.decks: list[Deck] = []
        # Keyed by slide bare id, not path -- a transcript preview has no
        # file of its own to dedupe on, and re-clicking "Render transcript"
        # for the same slide should refresh its existing page rather than
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

        self.state = WorkspaceState(self)
        self.commands = build_registry()
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

        # Left: the slide list, right: side panels (and the chat of step 10 below them).
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.slide_list = SlideList(self, self.state, theme, Toast(central))
        self.side_panels = SidePanels(self, self.state)
        # Centre: the views of the focused slide, or one of the pages below
        # (replaced in step 9: the Images page).
        self.stack = QStackedWidget()
        self.centre = CentreColumn(self, self.state)
        self.stack.addWidget(self.centre)
        # Its own first scan reads every slide that includes an image and
        # hashes those images' bytes (~1s) and syncs the store -- deferred to
        # the first time the page is shown (_on_page_changed) rather than
        # paid on every launch, and deliberately not a launch-time *write* to
        # media/alt-text.json.
        self.transcript_tab = TranscriptTab(self)
        self.stack.addWidget(self.transcript_tab)
        self.stack.currentChanged.connect(self._on_page_changed)
        for column in (self.slide_list, self.stack, self.side_panels):
            self.splitter.addWidget(column)
        self.splitter.setStretchFactor(1, 1)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.addWidget(self.splitter)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)
        self._init_compile(central)
        self.signals.update_check_done.connect(self._on_startup_update_check_done)

        self.palette = CommandPalette(self)
        self.commands.bind_shortcuts(self)
        self.topbar.command.connect(self._on_command)
        self.state.deck_changed.connect(self._remember_deck)
        self.state.dirty_changed.connect(self._on_dirty_changed)
        self.centre.preview.rendered.connect(self.slide_list.rebuild)   # a render may have captured a thumbnail
        self.centre.source.file_closed.connect(self._on_source_closed)
        self.centre.versions_changed.connect(self.side_panels.refresh)
        self.centre.source.reference_added.connect(self.side_panels.refresh)
        # Ctrl+Shift+F, the old project-wide text search, opens the palette, where that search is now.
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(self.palette.toggle)

        self.reload_decks()

    # -- commands --------------------------------------------------------------

    def _on_command(self, command_id: str) -> None:
        self.commands.run(command_id, self)

    # -- decks -----------------------------------------------------------------

    def reload_decks(self) -> None:
        """Rescans the decks. The current deck stays (a fresh object for the
        same file), follows its file when archived, or falls back to the one
        that was open last time, else the first active deck."""
        self.decks = scan_decks()
        self.topbar.set_decks(self.decks)
        current = self.state.deck
        remembered = app_settings.get(LAST_DECK_KEY)
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
            app_settings.set(LAST_DECK_KEY, deck.name)

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

    def _discard(self, page: QWidget) -> None:
        self.stack.removeWidget(page)
        page.deleteLater()

    def _on_page_changed(self, index: int) -> None:
        """Run the image-description page's first (expensive) scan only once
        it's actually shown, and tell the top bar whether Images is open."""
        is_images = self.stack.widget(index) is self.transcript_tab
        self.topbar.set_images_open(is_images)
        if is_images:
            self.transcript_tab.ensure_loaded()

    def _toggle_images(self) -> None:
        self.stack.setCurrentWidget(
            self.centre if self.stack.currentWidget() is self.transcript_tab else self.transcript_tab)

    def open_images_for_slide(self, id_slug: str) -> None:
        """The slide list's "Images" entry (2026-09-19, direct instruction):
        opens (or reveals) the Images page and lands on that slide's images. ensure_loaded() first because the page's first scan
        is deferred until it's shown -- _find_and_show_slide() only searches
        rows a scan has already produced."""
        self.stack.setCurrentWidget(self.transcript_tab)
        self.transcript_tab.ensure_loaded()
        self.transcript_tab._find_and_show_slide(id_slug)

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
        if path == bibliography.DEFAULT_BIB:
            bibliography.sort_entries()

    def open_transcript_preview(self, key: str, title: str) -> TranscriptPreviewTab:
        """The Preview's "Render transcript" (2026-08-25) --
        `key` is the slide's bare id, so re-rendering the same slide
        refreshes its existing page (via the caller's own set_html() call
        right after this returns) instead of piling up duplicates."""
        existing = self._transcript_preview_tabs.get(key)
        if existing is not None:
            self.stack.setCurrentWidget(existing)
            return existing
        tab = TranscriptPreviewTab(self, title)
        self._transcript_preview_tabs[key] = tab
        self.stack.addWidget(tab)
        self.stack.setCurrentWidget(tab)
        return tab

    def close_transcript_preview_tab(self, tab: TranscriptPreviewTab) -> None:
        for key, existing in list(self._transcript_preview_tabs.items()):
            if existing is tab:
                del self._transcript_preview_tabs[key]
        self.stack.setCurrentWidget(self.centre)
        self._discard(tab)

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
        self.palette.stop_search()
        self._stop_worker()
        super().closeEvent(event)

    def _resolve_dirty_edits(self) -> bool:
        """Return False when the user cancels or any requested save fails."""
        dirty_files = self.centre.source.dirty_files()
        panels = self.side_panels.dirty_panels()
        if dirty_files or panels:
            unsaved = [f"{len(dirty_files)} unsaved file{'s' if len(dirty_files) != 1 else ''}"] if dirty_files else []
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

        # Image descriptions have their own Save draft action and shared
        # alt-text store. Resolve those edits before the window disappears.
        image_tab = self.transcript_tab
        if image_tab._any_editor_dirty():
            choice = QMessageBox.question(
                self,
                "Unsaved image edits",
                "Save the current image description edits as a draft before closing?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return False
            if choice == QMessageBox.StandardButton.Yes:
                try:
                    image_tab._save(mark_reviewed=False)
                except Exception as exc:  # noqa: BLE001 -- keep app open on save failure
                    QMessageBox.critical(self, "Save failed", f"Could not save image edits: {exc}")
                    return False
                if image_tab._any_editor_dirty():
                    return False
        return True

    def _on_open_project(self) -> None:
        """⋮ → "Open project…" -- lets the user point SlideMage at
        any folder on disk via a native file picker (QFileDialog, so this
        is the same dialog whether it's Windows' or Linux's own), instead
        of only ever discovering a project automatically (cli.py's
        --project/$SLIDEMASTER_PROJECT/upward-search/last-opened chain) --
        added 2026-09-23 after that chain silently reused a stale
        "last project" on a fresh machine's first real run, with no
        visible way to override it once the app was already open.

        Restarts the whole application rather than switching in place:
        PROJECT_ROOT and every directory constant derived from it at
        import time across this package (see project.relaunch_with_project's
        own docstring) are fixed for a process's entire lifetime -- there
        is no single place left to mutate them all after the fact."""
        if self.compiling:
            QMessageBox.information(
                self, "Busy",
                "Can't switch projects while a compile run is in progress -- "
                "wait for it to finish first.",
            )
            return
        # Shared with cli.py's own first-run picker (project.py's own
        # pick_or_create_project()) -- also offers to create a new project
        # (seeded with the demo content, if bundled) when the chosen
        # folder isn't one yet, rather than only ever rejecting it.
        chosen_path = project.pick_or_create_project(self, PROJECT_ROOT.parent)
        if chosen_path is None:
            return
        if chosen_path == PROJECT_ROOT:
            return  # already open -- nothing to restart for
        reply = QMessageBox.question(
            self, "Open project",
            f"Switch to {chosen_path}?\n\nSlideMage restarts to open a "
            "different project.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._resolve_dirty_edits():
            return
        project.relaunch_with_project(chosen_path)
        self._dirty_edits_resolved_for_close = True
        self.close()

    def _on_import_presentation(self) -> None:
        dialog = ImportPresentationDialog(self)
        dialog.exec()

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()
        models = dialog.available_models
        self.transcript_tab.refresh_model_preferences(models, dialog.vision_models)
        self.centre.refresh_model_preferences(models)

    def set_dark_mode(self, checked: bool) -> None:
        """Public (2026-08-25): called from the Settings dialog's own
        checkbox (qt_settings_dialog.py), not just an internal toolbar
        handler any more -- theme.set_dark() itself now also persists the
        choice (QSettings, per-machine -- see ui/kit/theme.py)."""
        self.theme.set_dark(checked)
        # QSS covers every ordinary widget automatically, but a
        # QSyntaxHighlighter's own tag colors live on the text document,
        # outside the stylesheet mechanism entirely -- each open editor's
        # highlighter needs an explicit nudge to pick up the new palette and re-run.
        self.centre.refresh_colors()

    def set_tab_width_chars(self, chars: int) -> None:
        """Called from the Settings dialog's own tab-width spinbox
        (qt_settings_dialog.py), same shape as set_dark_mode() just above:
        persist the choice (app_settings.py), then nudge every already-open
        slide/deck-source editor to pick it up immediately rather than only
        on next open."""
        app_settings.set(latex_edit.TAB_WIDTH_SETTING_KEY, chars)
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
        self._log(summary)

    def refresh_open_deck_editors(self) -> None:
        """Re-scans the decks and redraws the slide list from current disk state
        (2026-08-25) -- for an edit that can touch more than one deck at once and
        has no single deck_path to hand after_deck_edit()
        (slide_rename.set_slide_language() rewrites every deck reference
        to a renamed slide, across however many decks reference it).
        Without this, the list kept showing a slide under its old id-slug
        after a rename. Doesn't re-run deck_headers.regenerate_headers() itself
        -- a caller that needs that has already run it (set_slide_language()
        always does, as its own last step)."""
        self.reload_decks()

    def try_start_ollama_task(self, label: str, provider: Optional[ChatProvider] = None) -> bool:
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
        changed, n_decks = deck_headers.regenerate_headers()
        self.signals.log.emit(
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
        if self.centre.source.file_for(bibliography.DEFAULT_BIB) is None:
            bibliography.sort_entries()
        self.open_slide_editor(bibliography.DEFAULT_BIB)

    def _on_edit_test_slides(self) -> None:
        """"Tabs -> Edit test-slides.tex" -- opens decks/test-slides.tex in
        source mode, like "Edit .bib" does for Slidemaster.bib."""
        path = DECKS_DIR / "test-slides.tex"
        if not path.is_file():
            QMessageBox.warning(self, "Edit test-slides.tex", f"{path} does not exist.")
            return
        self.open_slide_editor(path)

    def open_add_slide_dialog(self, deck: Deck, insert_at: int, indent: str) -> None:
        dialog = AddSlideDialog(self, deck, insert_at, indent)
        dialog.exec()

    def _build_snapshot_banner(self) -> Optional[QLabel]:
        """A line above the tabs when the open project is a deck snapshot:
        what it is, and that SlideMage leaves it as it was (no compatibility
        migrations, no framework updates; compiles use the snapshot's own
        framework, PDF dates and footer timestamps)."""
        info = project.snapshot_info(PROJECT_ROOT)
        if info is None:
            return None
        manifest = project.snapshot_manifest(PROJECT_ROOT)
        made_with = manifest.get("slidemage", {}).get("version", "?")
        when = str(info.get("created", ""))[:16].replace("T", " ")
        label = QLabel(
            f"Deck snapshot of {info.get('deck_name', '?')}, taken {when} with SlideMage "
            f"{made_with}. SlideMage doesn't update it, and compiles reproduce it as it "
            "was -- but anything you edit here changes the snapshot.")
        label.setObjectName(WARNING_LABEL)
        label.setWordWrap(True)
        return label

