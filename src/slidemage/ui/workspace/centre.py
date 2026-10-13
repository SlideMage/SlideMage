"""The workspace's centre column: Preview, Source, Split (both side by side) and
Details of the focused slide (docs/UI_REDESIGN_PLAN.md, step 5).

The top bar's mode switch (WorkspaceState.mode) says which of the views are
shown; the focused slide, view and language come from the same state. This
class decides *what* each view shows and keeps them in step:

* the Source view shows the file of the focused slide (the one the deck calls,
  so a pinned version opens as the frozen snapshot it is), or a file opened on
  purpose -- a deck's own source, Slidemaster.bib, a frozen version -- until
  another slide is focused;
* the Preview shows the focused slide as the deck typesets it, or a frozen
  version alone; saving re-renders it while it is visible;
* Details shows the slide the same way.

Views that are not visible are not updated, only brought up to date when they
are shown. Unsaved edits are kept per file by the Source view, whichever slide
is shown, and counted in WorkspaceState.dirty.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QMessageBox, QSplitter, QSplitterHandle, QStackedWidget)

from ... import deck_outline, slide_language, slide_source, slide_versioning
from ...preview_target import PreviewTarget, for_call, for_path
from ...slide_language import bare_id, current_path_for_bare_id
from ..dialogs.slide_usage_dialog import apply_deck_versions, ask_deck_versions
from .. import layout_settings
from ..kit import kit_qss as q
from .details_view import DetailsPane
from .preview_view import PreviewPane
from .source_file import RELOADED
from .source_view import SourcePane
from .state import WorkspaceState


# Settings key of the share of the width the Source view gets in the Split view.
SPLIT_SETTING = "source_preview_split"
DEFAULT_SPLIT = 0.5


class _ResetHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.splitter().reset_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class _SourcePreviewSplitter(QSplitter):
    """Source | Preview; a double-click on the divider gives each half the width again."""
    reset_requested = Signal()

    def createHandle(self) -> QSplitterHandle:
        return _ResetHandle(self.orientation(), self)


class CentreColumn(QFrame):
    versions_changed = Signal()   # a slide was restored or frozen as a version
    duplicate_requested = Signal(str)   # the details pane's Duplicate: the id-slug of the slide

    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.app = app
        self.state = state
        self._path: Optional[Path] = None   # the file the Source view shows
        self._opening = False               # open_file() is changing the focus itself

        self.source = SourcePane(app)
        self.preview = PreviewPane(app, state, self._preview_buffer)
        self.details = DetailsPane(app, state, self.is_dirty)
        self.details.duplicate_requested.connect(self.duplicate_requested)
        ratio = layout_settings.get(SPLIT_SETTING)
        self._split_ratio = (ratio if isinstance(ratio, (int, float)) and not isinstance(ratio, bool)
                             and 0.1 <= ratio <= 0.9 else DEFAULT_SPLIT)
        self._split = _SourcePreviewSplitter(Qt.Orientation.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(9)   # a thin line (kit_qss) with room to grab
        self._split.splitterMoved.connect(self._remember_split)
        self._split.reset_requested.connect(self._reset_split)
        self._split.setObjectName(q.SURFACE)
        self._split.addWidget(self.source)
        self._split.addWidget(self.preview)
        self._pages = QStackedWidget()
        self._pages.setObjectName(q.SURFACE)
        self._pages.addWidget(self._split)
        self._pages.addWidget(self.details)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._pages)
        self.setObjectName(q.CARD)   # the white card on the grey page

        self.source.dirty_changed.connect(self._update_dirty)
        self.source.buffer_changed.connect(self.preview.buffer_changed)
        self.source.lint_errors_changed.connect(state.set_lint_errors)
        self.source.saved.connect(self._on_saved)
        self.source.render_requested.connect(self.render_buffer)
        self.source.restore_requested.connect(self.restore_version)
        self.source.file_requested.connect(self.open_file)
        state.deck_changed.connect(self._on_deck_changed)
        state.focused_slide_changed.connect(self._on_focus)
        state.view_changed.connect(lambda _view: self.refresh())
        state.language_changed.connect(self._on_language)
        state.mode_changed.connect(lambda _mode: self.refresh())
        self.refresh()

    # -- what the window asks ----------------------------------------------------------

    def open_file(self, path: Path, on_saved: Optional[Callable[[str], None]] = None,
                  line: Optional[int] = None) -> None:
        """Show `path` in the Source view (a slide of the project focuses the slide too).
        `on_saved(previous_text)` runs after each save of it; `line` puts the cursor there."""
        self._opening = True
        try:
            if path.parent == self.state.project.slides_dir:
                self.state.set_focused_slide(bare_id(path.name))
            self._path = path
            if self.state.mode not in ("source", "split"):
                self.state.set_mode("source")
        finally:
            self._opening = False
        self.source.show_path(path, on_saved)
        self.refresh()
        if line is not None and self.source.current is not None:
            self.source.current.editor.go_to_line(line)

    @property
    def path(self) -> Optional[Path]:
        """The file of the focused slide, or the one opened on purpose: what the Source view shows (in
        Preview it is not loaded)."""
        return self._path

    def is_dirty(self, path: Path) -> bool:
        file = self.source.file_for(path)
        return file is not None and file.dirty

    def sync_source(self, path: Path) -> None:
        """Show the file again if it changed on disk elsewhere in the app, unless it has unsaved edits."""
        file = self.source.file_for(path)
        if file is not None:
            file.sync()

    def file_written(self, path: Path) -> None:
        """A file was written on disk outside the Source view (by the chat): an open buffer takes it in
        (disk_changed), and the Preview renders the slide if it is the one shown and not open."""
        if self.disk_changed(path) is None and path == self._path:
            self._on_saved(path)

    def disk_changed(self, path: Path) -> Optional[str]:
        """A file may have changed on disk behind the app's back (Claude Code in the terminal). What the
        Source view did with its buffer of `path`: SAME / RELOADED / CONFLICT (source_file.py), None if the
        file is not open."""
        file = self.source.file_for(path)
        if file is None:
            return None
        outcome = file.disk_changed()
        if outcome == RELOADED and path == self._path:
            self._on_saved(path)
        return outcome

    def _preview_buffer(self) -> Optional[tuple[str, str]]:
        """The Source view's buffer of the previewed slide, never that of another slide."""
        path = self.preview.target_path
        return self.source.buffer(path) if path is not None else None

    def slide_text(self, path: Path) -> str:
        """The text of a slide file as the Source view has it, unsaved edits included, else the saved file."""
        file = self.source.file_for(path)
        return file.editor.text() if file is not None else slide_source.read_slide_source(path)[0]

    def edit_slide_text(self, path: Path, change: Callable[[str], str]) -> bool:
        """Apply `change(text) -> text` to the Source view's buffer of `path`, as one undo step, and
        leave it there unsaved: a save is the Source view's, with its version prompt, backup and
        deck questions, so that an edit made from a panel is never saved by another route. False
        when the file is not editable (a frozen version, until it is unlocked)."""
        self.source.show_path(path)
        file = self.source.current
        if file is None or file.editor.is_read_only():
            return False
        file.editor.replace_all_text(change(file.editor.text()))
        return True

    def restore_version(self, frozen: Path) -> None:
        """"Make this the current version": slide_versioning.restore_version()."""
        match = slide_language.FROZEN_RE.search(frozen.name)
        id_slug = frozen.name[:match.start()] if match else ""
        current = frozen.parent / slide_language.current_name(id_slug)
        if not match or not current.is_file():
            QMessageBox.warning(self.app, "Cannot restore", "The slide's current file was not found.")
            return
        open_current = self.source.file_for(current)
        if open_current is not None and open_current.dirty:
            QMessageBox.warning(self.app, "Unsaved changes",
                                f"{current.name} has unsaved changes. Save or revert them first.")
            return
        reply = QMessageBox.question(
            self.app, "Make this the current version",
            f"Replace the content of {current.name} with this version?\n\n"
            "What is current now is archived first as a version of its own, "
            "and the restored content gets a new, higher version number.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            archived, version = slide_versioning.restore_version(self.state.project, current, id_slug, frozen)
        except slide_versioning.RestoreError as exc:
            QMessageBox.warning(self.app, "Cannot restore", str(exc))
            return
        self.app.log(
            f"Restored {frozen.name} as the current version of {id_slug}: now "
            f"v{slide_versioning.format_dot(version)}"
            + (f"; the previous content is archived as {archived.name}" if archived else ""))
        if open_current is not None:
            open_current.reload()
        self.open_file(current)
        self.versions_changed.emit()

    def freeze_version(self, id_slug: str, level: slide_versioning.BumpLevel) -> None:
        """"Freeze as": the slide's current content becomes a frozen version and the slide moves on
        to the next one (slide_versioning.freeze_current()), after asking what each deck does."""
        current = self.state.project.slides_dir / slide_language.current_name(id_slug)
        if not current.is_file():
            QMessageBox.warning(self.app, "Cannot freeze", "The slide's current file was not found.")
            return
        open_current = self.source.file_for(current)
        if open_current is not None and open_current.dirty:
            QMessageBox.warning(self.app, "Unsaved changes",
                                f"{current.name} has unsaved changes. Save or revert them first.")
            return
        text, _eol = slide_source.read_slide_source(current)
        final, frozen_as = slide_versioning.plan_save(slide_versioning.parse_version(text), level)
        asked = ask_deck_versions(self.app, self.state.project, id_slug, text, final, frozen_as)
        if asked is None:
            return
        try:
            frozen, version = slide_versioning.freeze_current(self.state.project, current, id_slug, level)
        except (ValueError, slide_source.StaleFileError) as exc:
            QMessageBox.warning(self.app, "Cannot freeze", str(exc))
            return
        self.app.log(f"Froze {id_slug} as {frozen.name}: now v{slide_versioning.format_dot(version)}")
        apply_deck_versions(self.app, id_slug, asked.choices, frozen_as)
        if open_current is not None:
            open_current.reload()
        self.refresh()
        self.versions_changed.emit()
        if asked.open_translation is not None:
            self.open_file(asked.open_translation)

    # -- keeping the views in step -----------------------------------------------------

    def _update_dirty(self, _dirty: bool = False) -> None:
        self.state.set_dirty(bool(self.source.dirty_files()))

    def _on_deck_changed(self, _deck) -> None:
        self._path = None
        self.refresh()

    def _on_focus(self, _slide_id: Optional[str]) -> None:
        if not self._opening:
            self._path = self._focused_path()
            self.refresh()

    def _on_language(self, _language: str) -> None:
        # SourcePane retains each file's buffer, including pending edits.
        # A non-slide opened explicitly (deck source, bibliography) stays open.
        if self._focused_row() is not None and (self._path is None or self._file_slide()[0]):
            self._path = self._focused_path()
        self.refresh()

    def _on_saved(self, _path: Path) -> None:
        if self.state.mode in ("preview", "split"):
            self.preview.render_after_save()
        self.refresh()

    def render_buffer(self) -> None:
        """Render the editor's buffer, saved or not (Ctrl+Enter, Ctrl+R in the Source view)."""
        if self.state.mode == "source":
            self.state.set_mode("split")   # the page is where the render shows
        self.preview.render_buffer()

    def _focused_row(self) -> Optional[deck_outline.SlideRow]:
        state = self.state
        deck = state.deck
        if deck is None or deck.is_test_deck or state.focused_slide is None:
            return None
        return deck_outline.slide_row(state.project, deck, state.focused_slide, state.view, state.language)

    def _focused_path(self) -> Optional[Path]:
        """The file of the focused slide, if it has one: what the deck's call loads, else the
        slide's current file."""
        row = self._focused_row()
        slide_id = self.state.focused_slide
        path = self.state.project.slides_dir / row.call.source_filename if row is not None \
            else current_path_for_bare_id(self.state.project, slide_id) if slide_id else None
        return path if path is not None and path.is_file() else None

    def _empty_message(self) -> str:
        deck = self.state.deck
        if deck is None:
            return "This project has no decks yet."
        if deck.is_test_deck:
            return (f"{deck.name} is a test deck: it has no slide list. Compile it from the top bar, "
                    "or edit its source from the ⋮ menu.")
        return "Select a slide in the list. Double-click it to open its source."

    def refresh(self) -> None:
        """Bring the visible views up to date with the state."""
        mode = self.state.mode
        if self._path is not None and not self._path.is_file():
            self._path = self._focused_path()   # renamed or deleted meanwhile
        was_split = self.source.isVisibleTo(self) and self.preview.isVisibleTo(self)
        self.source.setVisible(mode in ("source", "split"))
        self.preview.setVisible(mode in ("preview", "split"))
        self._pages.setCurrentWidget(self.details if mode == "details" else self._split)
        if mode == "split" and not was_split:
            self._apply_split()   # the remembered share on entering; not again while the handle is dragged
        message = self._empty_message()
        if mode in ("source", "split"):
            self.source.set_message(message)
            self.source.show_path(self._path)
        if mode in ("preview", "split"):
            target, row, title = self._preview_context()
            self.preview.show_slide(target, row, title, self._no_preview_message(message))
        if mode == "details":
            row = self._focused_row()
            id_slug = row.call.id_slug if row else self._file_slide()[0]
            self.details.show_slide(id_slug, row, self._details_message(message))

    def _apply_split(self) -> None:
        # Weights, so the share holds when the window is resized.
        self._split.setSizes([round(10_000 * self._split_ratio), round(10_000 * (1 - self._split_ratio))])

    def _remember_split(self, _position: int = 0, _index: int = 0) -> None:
        source, preview = self._split.sizes()
        if source and preview:
            self._split_ratio = source / (source + preview)
            layout_settings.set(SPLIT_SETTING, self._split_ratio)

    def _reset_split(self) -> None:
        self._split_ratio = DEFAULT_SPLIT
        layout_settings.set(SPLIT_SETTING, DEFAULT_SPLIT)
        self._apply_split()

    def _file_slide(self) -> tuple[str, Optional[str]]:
        """(id-slug, version) of the slide file shown, or ("", None) if it is no slide's."""
        if self._path is None:
            return "", None
        try:
            _macro, id_slug, version = slide_language.call_for_slide_path(self._path)
        except ValueError:
            return "", None
        return id_slug, version

    def _preview_context(self) -> tuple[Optional[PreviewTarget], Optional[deck_outline.SlideRow], str]:
        """What the Preview shows: the focused slide as the deck calls it; a frozen version, or a
        slide the deck doesn't use, alone."""
        row = self._focused_row()
        id_slug, version = self._file_slide()
        deck = self.state.deck
        if row is not None and (self._path is None or (id_slug == row.call.id_slug and version == row.call.version)):
            return for_call(self.state.project, deck, row.call, row.position), row, row.title
        if self._path is None:
            return None, None, ""
        target = for_path(self.state.project, self._path)
        return target, None, deck_outline.slide_file_title(self._path, id_slug) if target else ""

    def _no_preview_message(self, fallback: str) -> str:
        if self._path is not None and self._file_slide()[0] == "":
            return f"{self._path.name} is not a slide: there is nothing to preview."
        return fallback

    def _details_message(self, fallback: str) -> str:
        if self._path is not None and self._file_slide()[0] == "":
            return f"{self._path.name} is not a slide: these are the details of slides."
        return fallback

    # -- settings and housekeeping the window forwards ---------------------------------

    def refresh_colors(self) -> None:
        self.source.refresh_colors()

    def set_tab_width(self, chars: int) -> None:
        self.source.set_tab_width(chars)

    def refresh_model_preferences(self, models: list[str]) -> None:
        self.source.refresh_model_preferences(models)
