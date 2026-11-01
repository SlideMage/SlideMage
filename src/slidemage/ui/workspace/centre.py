# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The workspace's centre column: a strip of tabs over Preview, Source, Split (both side by side) and
Details (docs/UI_REDESIGN_PLAN.md, step 5; docs/plans/centre-tabs.md).

The first tab is the slide tab, always there: it follows the focused slide. A file opened on purpose -- a deck's own
source, SlideMage.bib, test-slides.tex -- has a tab of its own until it is closed (centre_tabs.py); opening a file
that has a tab shows that tab. Every tab remembers the mode it was last shown in, and a file tab has the Source view
alone. The top bar's mode switch (WorkspaceState.mode) says which of the views are shown for the tab on show; the
focused slide, view and language come from the same state. This class decides *what* each view shows and keeps
them in step:

* the Source view shows the file of the tab on show: for the slide tab the file of the focused slide (the one the
  deck calls, so a pinned version opens as the frozen snapshot it is), or a slide's file opened on purpose -- a
  frozen version -- until another slide is focused; for a file tab its file, which the Source view keeps open
  while another tab is shown;
* the Preview shows the slide tab's slide as the deck typesets it, or a frozen version alone; saving re-renders it
  while it is visible. Its language chip shows the slide's file in the other language instead (the top bar's
  language stays), typeset in that language as the deck calls it;
* Details shows the slide the same way.

Focusing a slide shows the slide tab; the file tabs stay open. Views that are not visible are not updated, only
brought up to date when they are shown. Unsaved edits are kept per file by the Source view, whichever tab is
shown, and counted in WorkspaceState.dirty.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QMessageBox, QSplitter, QSplitterHandle, QStackedWidget, QVBoxLayout,
    QWidget)

from ... import app_settings, deck_editor, deck_outline, slide_branch, slide_language, slide_source, slide_usage, slide_versioning
from ...ai.tools.slidemage import slide_target
from ...preview_target import PreviewTarget, for_call, for_path
from ...slide_language import TRANSLATION_LANGUAGES, bare_id, current_path_for_bare_id, own_language
from ..dialogs.new_slide_version import NewSlideVersionSheet
from ..dialogs.slide_usage_dialog import DeckVersions, apply_deck_versions, ask_deck_versions
from .. import layout_settings
from ..kit import kit_qss as q
from .centre_tabs import FILE, CentreTab, CentreTabs, TabStrip
from .details_view import DetailsPane
from .preview_view import PreviewPane
from .source_file import NEW_SLIDE, OVERWRITE, RELOADED, autosave_on, prompt_version_level
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


def ask_update_on_leave(parent, slide_id: str, version: slide_versioning.Version) -> tuple[bool, bool]:
    """The question when leaving a changed slide: (Update Version chosen, "Don't ask again" ticked)."""
    box = QMessageBox(parent)
    box.setWindowTitle("Update version")
    box.setText(f"{slide_id} has changed since v{slide_versioning.format_dot(version)}.\n\n"
                "Make the changes a version of their own now?")
    update = box.addButton("Update version…", QMessageBox.ButtonRole.AcceptRole)
    later = box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(later)
    stop = QCheckBox("Don't ask again (Settings → General)")
    box.setCheckBox(stop)
    box.exec()
    return box.clickedButton() is update, stop.isChecked()


def _is_slide_file(path: Path) -> bool:
    try:
        slide_language.call_for_slide_path(path)
    except ValueError:
        return False
    return True


class _CtrlWatch(QObject):
    """While a Ctrl+Tab series runs: says when it is over, the Ctrl key released (or another key pressed)."""

    released = Signal()

    def eventFilter(self, _obj, event) -> bool:  # noqa: N802 -- Qt's name
        kind = event.type()
        if kind == QEvent.Type.KeyRelease and event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Meta):
            self.released.emit()
        elif kind == QEvent.Type.KeyPress and not event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.released.emit()
        return False


class CentreColumn(QFrame):
    versions_changed = Signal()   # a slide was restored or frozen as a version
    duplicate_requested = Signal(str)   # the details pane's Duplicate: the id-slug of the slide
    source_only_changed = Signal(bool)  # the tab shown has a file that is no slide: the Source view alone

    def __init__(self, app, state: WorkspaceState) -> None:
        super().__init__()
        self.app = app
        self.state = state
        self._slide_path: Optional[Path] = None   # the slide tab's file: the focused slide's, or one opened on purpose
        self._opening = False               # open_file() is changing the focus itself
        self._edited: set[Path] = set()     # files written from the Source view since they were last left
        self._switching = False             # a tab is being shown: its mode is set, then the views refresh once
        self._holding = 0                   # > 0: showing another tab does not refresh, the caller does
        self.tabs = CentreTabs(state.mode, self)
        self._shown = self.tabs.active      # the tab the views show (to write its file when it is left)
        self._ctrl = _CtrlWatch(self)       # watches for the end of a Ctrl+Tab series
        self._ctrl.released.connect(self.end_tab_cycle)
        self.tab_strip = TabStrip()

        self.source = SourcePane(app)
        self.preview = PreviewPane(app, state, self._preview_buffer)
        self.preview.neighbours = self._neighbour_targets
        self.preview.deck_targets = self._deck_targets
        self.preview.slide_requested.connect(self._go_adjacent)
        self.details = DetailsPane(app, state, self.unsaved)
        self.details.duplicate_requested.connect(self.duplicate_requested)
        self.details.open_requested.connect(lambda path: self.open_file(path))
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
        # A row of its own under the views for the background renders' dial and status (background_previews):
        # floating over the views it covered the Preview's slide id and the editor's last lines.
        self.status_row = QWidget()
        row = QHBoxLayout(self.status_row)
        row.setContentsMargins(12, 0, 12, 8)
        row.setSpacing(8)
        row.addStretch(1)
        self.status_row.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tab_strip)
        layout.addWidget(self._pages, 1)
        layout.addWidget(self.status_row)
        self.setObjectName(q.CARD)   # the white card on the grey page

        self.source.dirty_changed.connect(self._update_dirty)
        self.source.written.connect(self._edited.add)
        self.source.buffer_changed.connect(self.preview.buffer_changed)
        self.source.lint_errors_changed.connect(state.set_lint_errors)
        self.source.written.connect(lambda _path: state.drop_outline())   # before anything below reads a row
        self.source.saved.connect(self._on_saved)
        self.source.render_requested.connect(self.render_buffer)
        self.source.restore_requested.connect(self.restore_version)
        self.source.version_requested.connect(self.update_version)
        self.source.file_requested.connect(self.open_file)
        self.preview.partner_requested.connect(lambda path: self.open_file(path, keep_mode=True))
        self.tab_strip.activate_requested.connect(self.tabs.activate)
        self.tab_strip.close_requested.connect(self.close_tab)
        self.tabs.tabs_changed.connect(self._update_strip)
        self.tabs.active_changed.connect(self._on_tab_active)
        self._update_strip()
        state.deck_changed.connect(self._on_deck_changed)
        state.focused_slide_changed.connect(self._on_focus)
        state.view_changed.connect(lambda _view: self.refresh())
        state.language_changed.connect(self._on_language)
        state.mode_changed.connect(self._on_mode)
        self.refresh()

    # -- what the window asks ----------------------------------------------------------

    def open_file(self, path: Path, on_saved: Optional[Callable[[str], None]] = None,
                  line: Optional[int] = None, *, keep_mode: bool = False, tab: bool = False) -> None:
        """Show `path` in the Source view. A file that is no slide (a deck's source, SlideMage.bib, test-slides.tex)
        has a tab of its own, which is shown (opened first unless it has one) in the Source view alone; `keep_mode`
        does not apply to it. A slide's file is the slide tab's: the slide tab is shown, the slide of the project is
        focused, and the Source view is switched to unless it is on show or `keep_mode`. (`tab` asks for a tab of its
        own, which a slide's file does not get yet.) `on_saved(previous_text)` runs after each save of it; `line`
        puts the cursor there. With the Preview alone on show (`keep_mode`) the file only becomes the centre's path:
        its editor is built when the Source view is shown (refresh()), unless `on_saved` or `line` need it now, as
        they live on the editor. The views are refreshed unless the focus click had already put them there."""
        if not _is_slide_file(path):
            self._open_file_tab(path, on_saved, line)
            return
        flipped = self._show_slide_tab()
        changed = path != self._path or flipped
        mode = self.state.mode
        self._opening = True
        try:
            if path.parent == self.state.project.slides_dir and bare_id(path.name) != self.state.focused_slide:
                self.state.set_focused_slide(bare_id(path.name))     # the focused slide keeps its occurrence
                changed = True
            self._set_path(path)
            if self.state.mode not in ("source", "split") and not keep_mode:
                self.state.set_mode("source")
        finally:
            self._opening = False
        if self.state.mode in ("source", "split") or on_saved is not None or line is not None:
            self.source.show_path(path, on_saved)
        if changed or self.state.mode != mode:
            self.refresh()
        if line is not None and self.source.current is not None:
            self.source.current.editor.go_to_line(line)

    def _open_file_tab(self, path: Path, on_saved: Optional[Callable[[str], None]], line: Optional[int]) -> None:
        """Show the file tab of `path`, opening it (at the end of the strip) unless it has one."""
        tab = self.tabs.tab_for(path)
        if tab is None:
            tab = self.tabs.add_file(path, on_saved)
            self.source.hold(path)
        elif on_saved is not None:
            tab.on_saved = on_saved
        if tab is self.tabs.active:
            self.refresh()                   # the hook or the line are for the file on show already
        else:
            self.tabs.activate(tab)          # refreshes
        if line is not None and self.source.current is not None:
            self.source.current.editor.go_to_line(line)

    @property
    def path(self) -> Optional[Path]:
        """The file of the tab on show, which the Source view shows (in Preview it is not loaded): the slide tab's
        slide, the focused one or one opened on purpose, or a file tab's file."""
        return self._path

    @property
    def _path(self) -> Optional[Path]:
        tab = self.tabs.active
        return tab.path if tab.kind == FILE else self._slide_path

    @property
    def source_only(self) -> bool:
        """The tab on show has a file that is no slide: it has the Source view alone."""
        return self.tabs.active.source_only

    def is_dirty(self, path: Path) -> bool:
        """The Source view's buffer of `path` differs from the file: briefly between a keystroke and its
        autosave, for good when it cannot be saved. For a display; `unsaved` is the question before a change."""
        file = self.source.file_for(path)
        return file is not None and file.dirty

    def is_blocked(self, path: Path) -> bool:
        """The Source view holds edits of `path` that cannot be saved (a conflict, read-only, an AI fix
        running), not just the ones an autosave is about to write."""
        file = self.source.file_for(path)
        return file is not None and file.blocked

    def unsaved(self, path: Path) -> bool:
        """Whether the Source view holds edits of `path` that could not be saved (a conflict with a change
        on disk, a read-only buffer, an AI fix running). The edits that can be are written first."""
        file = self.source.file_for(path)
        return file is not None and not file.write_now(force=True) and file.dirty

    def sync_source(self, path: Path) -> None:
        """Show the file again if it changed on disk elsewhere in the app, unless it has unsaved edits."""
        file = self.source.file_for(path)
        if file is not None:
            file.sync()

    def file_written(self, path: Path) -> None:
        """A file was written on disk outside the Source view (by the chat): an open buffer takes it in
        (disk_changed), and the Preview renders the slide if it is the one shown and not open."""
        if self.disk_changed(path) is None and path in (self._path, self._slide_path):
            self._on_saved(path)

    def disk_changed(self, path: Path) -> Optional[str]:
        """A file may have changed on disk behind the app's back (Claude Code in the terminal). What the
        Source view did with its buffer of `path`: SAME / RELOADED / CONFLICT (source_file.py), None if the
        file is not open."""
        file = self.source.file_for(path)
        if file is None:
            return None
        outcome = file.disk_changed()
        if outcome == RELOADED and path in (self._path, self._slide_path):
            self._on_saved(path)
        return outcome

    def _preview_buffer(self) -> Optional[tuple[str, str]]:
        """The Source view's buffer of the previewed slide, never that of another slide."""
        path = self.preview.target_path
        return self.source.buffer(path) if path is not None else None

    def slide_text(self, path: Path) -> str:
        """The text of a slide file as the Source view has it, edits not yet written included, else the saved file."""
        file = self.source.file_for(path)
        return file.editor.text() if file is not None else slide_source.read_slide_source(path)[0]

    def edit_slide_text(self, path: Path, change: Callable[[str], str], *, show: bool = False) -> bool:
        """Apply `change(text) -> text` to the Source view's buffer of `path`, as one undo step, and
        leave it to the Source view's autosave, so that an edit made from a panel is never written by
        another route. False when the file is not editable (a frozen version, until it is unlocked).
        The file becomes the Source view's own if `show` or it is shown already; else (a slide the focus
        has left) it is changed off-stage and written at once (SourcePane.edit_off_stage), so the Source
        view does not go back to it."""
        current = self.source.current
        if not show and (current is None or current.path != path):
            return self.source.edit_off_stage(path, change)
        if show:
            self.show_slide_tab()      # the slide is the Source view's, so it is the tab on show
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
        if not self._written(open_current):
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
        self.state.drop_outline()   # the slide's title may differ now
        self.app.log(
            f"Restored {frozen.name} as the current version of {id_slug}: now "
            f"v{slide_versioning.format_dot(version)}"
            + (f"; the previous content is archived as {archived.name}" if archived else ""))
        if open_current is not None:
            open_current.reload()
        self.open_file(current)
        self.versions_changed.emit()

    def _written(self, file) -> bool:
        """Write an open file's edits first; False (and say why) when they cannot be."""
        if file is None or file.write_now(force=True):
            return True
        QMessageBox.warning(self.app, "Edits not saved",
                            f"{file.path.name} has edits that could not be saved"
                            + (" (it changed on disk)." if file.conflicted else ".") + " Resolve that first.")
        return False

    def update_version(self, id_slug: str) -> None:
        """The Source view's Update Version: ask how significant the change is, unless the slide is
        made the version it already names (not frozen yet), then freeze_version()."""
        current = self.state.project.slides_dir / slide_language.current_name(id_slug)
        if not current.is_file() or not self._written(self.source.file_for(current)):
            return
        text = slide_source.read_slide_source(current)[0]
        try:
            new, base = slide_versioning.plan_update(current, id_slug, text, "patch")
        except ValueError as exc:
            QMessageBox.information(self.app, "Update version", str(exc))
            return
        level = prompt_version_level(self.app, base) if new != base else "patch"
        if level == NEW_SLIDE:
            self.save_as_new_slide(id_slug)
        elif level == OVERWRITE:
            self.overwrite_version(id_slug)
        elif level is not None:
            self.freeze_version(id_slug, level)

    def overwrite_version(self, id_slug: str) -> None:
        """Update version -> Overwrite: the changes go into the version they were made to, which keeps its number
        (slide_versioning.overwrite_version); decks pinned to it get them too."""
        current = self.state.project.slides_dir / slide_language.current_name(id_slug)
        open_current = self.source.file_for(current)
        if not self._written(open_current):
            return
        try:
            version = slide_versioning.overwrite_version(self.state.project, current, id_slug)
        except (ValueError, OSError, slide_source.StaleFileError) as exc:
            QMessageBox.warning(self.app, "Cannot overwrite the version", str(exc))
            return
        self.app.log(f"Overwrote v{slide_versioning.format_dot(version)} of {id_slug} with its current content")
        if open_current is not None:
            open_current.adopt_disk()
        self.refresh()
        self.versions_changed.emit()

    def save_as_new_slide(self, id_slug: str) -> None:
        """Update version → New slide…: the changes become a slide of their own (slide_branch.py), which the decks
        ticked load instead; the slide itself goes back to its version. The new slide opens in the editor."""
        project = self.state.project
        reason = slide_branch.can_branch(project, id_slug)
        if reason:
            QMessageBox.information(self.app, "Save as a new slide", reason)
            return
        current = project.slides_dir / slide_language.current_name(id_slug)
        version = slide_versioning.parse_marker(slide_source.read_slide_source(current)[0])
        usages = [(u.deck.name, len(slide_branch.following_calls(u))) for u in slide_usage.find_usage(project, id_slug)]
        usages = [(name, count) for name, count in usages if count]
        edited = self.state.deck.name if self.state.deck is not None else None
        usages.sort(key=lambda item: item[0] != edited)          # the deck it is edited in first
        sheet = NewSlideVersionSheet(self.app, id_slug, version[0] if version else slide_versioning.DEFAULT_BASELINE,
                                     id_slug.split("-", 2)[2], usages, edited)
        if not sheet.exec():
            return
        open_current = self.source.file_for(current)
        try:
            result = slide_branch.save_as_new_slide(project, id_slug, sheet.slug, sheet.decks)
        except (ValueError, OSError, slide_source.StaleFileError, deck_editor.StaleFileError) as exc:
            QMessageBox.warning(self.app, "Save as a new slide", str(exc))
            return
        new = result.created.id_slug
        self.app.log(f"{id_slug}'s changes are now the new slide {new}; {id_slug} is back at "
                     f"v{slide_versioning.format_dot(result.reverted_to)}")
        for name, count in result.decks.items():
            self.app.log(f"    {name}: {count} call(s) now load {new}")
        if open_current is not None:
            open_current.adopt_disk()
        self.app.after_version_updates([current, result.created.path])
        if edited in result.decks:
            self.app.after_deck_edit(self.state.deck.path, f"{id_slug} → {new} in {edited}", result.previous_texts[edited])
        if set(result.decks) - {edited}:
            self.app.refresh_open_deck_editors()
        self.open_file(result.created.path)

    def update_deck_versions(self) -> None:
        """⋮ → This deck → Update Version of all changed slides: every slide the open deck calls from its
        current file that carries a "+" becomes a version, all at the one level asked here. Decks are not
        rewritten (one that follows current.tex moves on, one that pins a version stays pinned); the
        slide's own Update Version asks per deck."""
        deck = self.state.deck
        if deck is None:
            return
        self.source.flush_all()
        changed = slide_versioning.changed_slides(self.state.project, deck, self.state.language)
        if not changed:
            QMessageBox.information(self.app, "Update version", f"No slide of {deck.name} has changes since its last version.")
            return
        self._update_versions(changed, "Update version of all changed slides", f"in {deck.name}")

    def update_selected_versions(self) -> None:
        """Make a version of each selected slide, using one shared bump level."""
        slugs = list(dict.fromkeys(row.call.id_slug for row in self.app.slide_list.targets()))
        if not slugs:
            return
        self.source.flush_all()
        self._update_versions(slugs, "Update versions", "selected")

    def _update_versions(self, changed: list[str], title: str, label: str) -> None:
        """Batch versioning keeps deck calls as they are, including pinned versions."""
        blocked = [slug for slug in changed
                   if self.is_blocked(self.state.project.slides_dir / slide_language.current_name(slug))]
        if blocked:
            QMessageBox.warning(self.app, "Edits not saved",
                                "These slides have edits that could not be saved (see the notice in the Source view); "
                                "resolve that first: " + ", ".join(slide_language.bare_id(slug) for slug in blocked))
            return
        shown = ", ".join(slide_language.bare_id(slug) for slug in changed[:12]) + (", …" if len(changed) > 12 else "")
        box = QMessageBox(self.app)
        box.setWindowTitle(title)
        box.setText(f"Update versions of {len(changed)} slide(s) {label}:\n{shown}\n\n"
                    "How significant are the changes? Each slide is frozen as the next version of that size.")
        levels: dict[str, object] = {}
        for level in ("major", "minor", "patch"):
            levels[level] = box.addButton(level.capitalize(), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(levels["patch"])
        box.exec()
        level = next((name for name, button in levels.items() if box.clickedButton() is button), None)
        if level is None:
            return
        done, failed, updated = 0, [], []
        for slug in changed:
            current = self.state.project.slides_dir / slide_language.current_name(slug)
            open_current = self.source.file_for(current)
            try:
                _frozen, version, _base = slide_versioning.update_version(self.state.project, current, slug, level)
            except (OSError, ValueError, slide_source.StaleFileError) as exc:
                failed.append(f"{slide_language.bare_id(slug)}: {exc}")
                continue
            updated.append(current)
            done += 1
            self.app.log(f"{slug} is now v{slide_versioning.format_dot(version)}")
            if open_current is not None:
                open_current.adopt_disk()
        self.app.after_version_updates(updated)
        if failed:
            QMessageBox.warning(self.app, "Update version",
                                f"{done} slide(s) updated; not these:\n" + "\n".join(failed))

    def freeze_version(self, id_slug: str, level: slide_versioning.BumpLevel) -> None:
        """Update Version (also the Versions panel's): the slide's current content becomes a frozen
        version (slide_versioning.update_version()), after asking what each deck does; decks that
        keep the old content are pinned to the version it moves on from."""
        current = self.state.project.slides_dir / slide_language.current_name(id_slug)
        if not current.is_file():
            QMessageBox.warning(self.app, "Cannot update the version", "The slide's current file was not found.")
            return
        open_current = self.source.file_for(current)
        if not self._written(open_current):
            return
        text, _eol = slide_source.read_slide_source(current)
        try:
            new, base = slide_versioning.plan_update(current, id_slug, text, level)
        except ValueError as exc:
            QMessageBox.warning(self.app, "Cannot update the version", str(exc))
            return
        asked = ask_deck_versions(self.app, self.state.project, id_slug, text, new, base) if new != base \
            else DeckVersions({}, None)
        if asked is None:
            return
        try:
            frozen, version, base = slide_versioning.update_version(self.state.project, current, id_slug, level)
        except (ValueError, slide_source.StaleFileError) as exc:
            QMessageBox.warning(self.app, "Cannot update the version", str(exc))
            return
        self.app.log(f"{id_slug} is now v{slide_versioning.format_dot(version)}, frozen as {frozen.name}")
        if version != base:
            apply_deck_versions(self.app, id_slug, asked.choices, base)
        if open_current is not None:
            open_current.adopt_disk()
        self.refresh()
        self.versions_changed.emit()
        if asked.open_translation is not None:
            self.open_file(asked.open_translation)

    # -- leaving a changed slide -------------------------------------------------------

    def _set_path(self, path: Optional[Path]) -> None:
        """Make `path` the slide tab's file; leaving another slide that was edited may offer Update Version for it
        (once the switch is done). Showing a file tab and coming back is not leaving the slide."""
        left = self._slide_path
        self._slide_path = path
        if left is not None and left != path:
            # Its edits still waiting for their autosave are written now: the Source view does not do it
            # when it is hidden (Preview), as it shows the new file only when it is on show.
            file = self.source.file_for(left)
            if file is not None:
                file.write_now()
            # after the switch
            QTimer.singleShot(0, lambda: self._offer_version(left))

    def offer_versions_on_close(self) -> None:
        """Closing the window (or switching projects, or restarting for an update) leaves every slide edited on
        this visit, the one on show included: each is offered Update Version as if it were left."""
        for path in sorted(self._edited):
            self._offer_version(path, closing=True)

    def _offer_version(self, path: Path, *, closing: bool = False) -> None:
        """Settings -> General, "Ask about Update Version when leaving a changed slide": the slide's current
        file `path` was edited in the Source view and now carries a "+" -- ask whether to make it a version
        (Update Version, as its button does). Asked once per visit with edits; "Not now" leaves the "+".
        Edits that were discarded instead of saved (AutoSave off) are not asked about: they cannot be written."""
        if path not in self._edited or (path == self._slide_path and not closing):
            return                         # not edited on this visit, or the slide tab shows it again already
        self._edited.discard(path)
        if not app_settings.get(self.state.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY, False):
            return
        if not path.is_file() or not path.name.endswith(slide_language.CURRENT_SUFFIX)                 or not slide_versioning.is_current_slide(path):
            return
        file = self.source.file_for(path)
        if file is not None and not file.write_now():
            return                         # edits that cannot be saved: the notice in the Source view says so
        marker = slide_versioning.parse_marker(slide_source.read_slide_source(path)[0])
        if marker is None or not marker[1]:
            return                         # no "+": nothing changed since the last version
        id_slug = path.name[:-len(slide_language.CURRENT_SUFFIX)]
        update, stop = ask_update_on_leave(self.app, bare_id(id_slug), marker[0])
        if stop:
            app_settings.set(self.state.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY, False)
        if update:
            self.update_version(id_slug)

    # -- keeping the views in step -----------------------------------------------------

    def _update_dirty(self, _dirty: bool = False) -> None:
        self.state.set_dirty(bool(self.source.blocked_files()))   # saved as you type: only edits that cannot be saved

    def _on_deck_changed(self, _deck) -> None:
        # The new deck's remembered mode is the state's already; the slide tab follows the deck, the file tabs stay.
        self.tabs.slide_tab.mode = self.state.mode
        self._show_slide_tab()
        self._set_path(None)
        self.refresh()

    # -- tabs ----------------------------------------------------------------------------

    def _show_slide_tab(self) -> bool:
        """Show the slide tab, without refreshing the views (the caller does). Whether another tab was shown."""
        slide = self.tabs.slide_tab
        if self.tabs.active is slide:
            return False
        self._holding += 1
        try:
            self.tabs.activate(slide)
        finally:
            self._holding -= 1
        return True

    def show_slide_tab(self) -> None:
        """Show the slide tab, in the mode it was last shown in (what focusing a slide does)."""
        if self._show_slide_tab():
            self.refresh()

    def _on_tab_active(self, tab: CentreTab) -> None:
        """Another tab is on show: its file is the Source view's, its mode the state's (a file that is no slide has
        the Source view alone). The file tab left is written, as a file out of view is, as the Source view does not
        show it when the new tab is in Preview."""
        left, self._shown = self._shown, tab
        if left is not tab and left.kind == FILE:
            file = self.source.file_for(left.path)
            if file is not None:
                file.write_now()
        self.tab_strip.set_active(tab)
        self._switching = True
        try:
            self.state.set_mode("source" if tab.source_only else tab.mode)
        finally:
            self._switching = False
        if tab.kind != FILE and self.state.mode not in ("source", "split"):
            self.source.show_path(None)         # as for the slide tab in Preview before: no file is "shown"
        self.source_only_changed.emit(tab.source_only)
        if not self._holding:
            self.refresh()

    def _update_strip(self) -> None:
        self.tab_strip.set_tabs(self.tabs.tabs, self._tab_label)
        self.tab_strip.set_active(self.tabs.active)

    def _tab_label(self, tab: CentreTab) -> tuple[str, str]:
        """(text, tooltip) of a tab: a file tab names its file; the slide tab names the slide on show."""
        if tab.kind == FILE:
            return tab.path.name, str(tab.path)
        return self._slide_label(), ""

    def _slide_label(self) -> str:
        """"1y8 · Market efficiency": the slide tab's slide."""
        path = self._slide_path
        if path is None:
            return "Slide"
        id_slug, _version = self._file_slide()
        row = self._focused_row()
        title = row.title if row is not None and id_slug == row.call.id_slug else deck_outline.slide_file_title(path, id_slug)
        return f"{bare_id(id_slug)} · {title}" if title else bare_id(id_slug)

    def close_tab(self, tab: CentreTab) -> bool:
        """Close a file tab (its "x", the middle button, Ctrl+W). Edits that would be lost are asked about: Save,
        Discard or Cancel (False: it stays open). Then the tab used before comes back, in the mode it was last
        shown in."""
        if not tab.closable or tab not in self.tabs.tabs:
            return False
        file = self.source.file_for(tab.path)
        if file is not None and file.dirty and not (autosave_on() and file.write_now(force=True)):
            answer = self._ask_save(file.path.name)
            if answer == "save":
                if not file.write_now(force=True):
                    return False               # a conflict with a change on disk: its notice says so
            elif answer == "discard":
                file.reload()
            else:
                return False
        self._remove_tab(tab)
        return True

    def close_active_tab(self) -> bool:
        """Ctrl+W: close the tab on show unless it is the slide tab."""
        return self.close_tab(self.tabs.active)

    def _remove_tab(self, tab: CentreTab) -> None:
        self.tabs.close(tab)                   # shows the tab used before when this was on show
        self.source.release(tab.path)          # the file goes (and `file_closed` tells the window), edits kept aside

    def _forget_missing_tabs(self) -> None:
        """A file tab whose file was renamed or deleted meanwhile is closed without asking: there is nothing to save to."""
        gone = [tab for tab in self.tabs.tabs if tab.kind == FILE and not tab.path.is_file()]
        if not gone:
            return
        self._holding += 1                      # the refresh that found them goes on
        try:
            for tab in gone:
                self._remove_tab(tab)
        finally:
            self._holding -= 1

    def cycle_tabs(self, step: int) -> None:
        """Ctrl+Tab (`step` 1) and Ctrl+Shift+Tab (-1): the next (previous) tab in most-recently-used order. The
        series goes on until Ctrl is released."""
        if len(self.tabs.tabs) < 2:
            return
        if not self.tabs.cycling:
            QApplication.instance().installEventFilter(self._ctrl)
        self.tabs.cycle(step)

    def end_tab_cycle(self) -> None:
        """The Ctrl+Tab series is over: the tab it stopped at is the most recently used."""
        QApplication.instance().removeEventFilter(self._ctrl)
        self.tabs.end_cycle()

    def _ask_save(self, name: str) -> Optional[str]:
        """"save", "discard" or None (Cancel) for the unsaved changes of the file `name`."""
        box = QMessageBox(QMessageBox.Icon.Question, "Unsaved changes", f"Save the changes to {name}?",
                          parent=self.app)
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        return "save" if box.clickedButton() is save else "discard" if box.clickedButton() is discard else None

    def _on_mode(self, mode: str) -> None:
        """The mode of the tab on show changed. A file that is no slide has the Source view alone (D3 of the plan):
        another mode, asked for by whatever route, is put back."""
        tab = self.tabs.active
        if tab.source_only and mode != "source":
            self.state.set_mode("source")
            return
        if self._switching:
            return
        if tab.kind != FILE:
            tab.mode = mode                    # the slide tab comes back in this mode
        self.refresh()

    def _on_focus(self, _slide_id: Optional[str]) -> None:
        if not self._opening:
            self._show_slide_tab()
            self._set_path(self._focused_path())
            self.refresh()

    def _on_language(self, _language: str) -> None:
        # SourcePane retains each file's buffer, including pending edits. The file tabs stay as they are.
        if self._focused_row() is not None:
            self._set_path(self._focused_path())
        self.refresh()

    def _on_saved(self, _path: Path) -> None:
        self.state.drop_outline()
        if self.state.mode in ("preview", "split"):
            self.preview.render_after_save()
        self.refresh()

    def render_buffer(self) -> None:
        """Render the editor's buffer, saved or not (Ctrl+Enter, Ctrl+R in the Source view). A file that is no slide
        has nothing to render."""
        if self.source_only:
            return
        if self.state.mode == "source":
            self.state.set_mode("split")   # the page is where the render shows
        self.preview.render_buffer()

    def _focused_row(self) -> Optional[deck_outline.SlideRow]:
        state = self.state
        deck = state.deck
        if deck is None or deck.is_test_deck or state.focused_slide is None:
            return None
        return deck_outline.slide_row(state.project, deck, state.focused_slide, state.view, state.language,
                                      occurrence_key=state.focused_occurrence, outline=state.outline)

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
                    "or edit its source with Deck → Source.")
        return "Select a slide in the list. Click it to open its source."

    def refresh(self) -> None:
        """Bring the visible views up to date with the state."""
        self._forget_missing_tabs()
        mode = self.state.mode
        if self._slide_path is not None and not self._slide_path.is_file():
            self._slide_path = self._focused_path()   # renamed or deleted meanwhile
        was_split = self.source.isVisibleTo(self) and self.preview.isVisibleTo(self)
        self.source.setVisible(mode in ("source", "split"))
        self.preview.setVisible(mode in ("preview", "split"))
        self._pages.setCurrentWidget(self.details if mode == "details" else self._split)
        if mode == "split" and not was_split:
            self._apply_split()   # the remembered share on entering; not again while the handle is dragged
        message = self._empty_message()
        if mode in ("source", "split"):
            self.source.set_message(message)
            self.source.show_path(self._path, self.tabs.active.on_saved)
        if mode in ("preview", "split"):
            target, row, title, language = self._preview_context()
            self.preview.show_slide(target, row, title, message, language)
        if mode == "details":
            row = self._focused_row()
            id_slug = row.call.id_slug if row else self._file_slide()[0]
            self.details.show_slide(id_slug, row, message)
        self.tab_strip.set_label(self.tabs.slide_tab, self._slide_label())

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
        """(id-slug, version) of the slide tab's file, or ("", None) if it has none."""
        if self._slide_path is None:
            return "", None
        try:
            _macro, id_slug, version = slide_language.call_for_slide_path(self._slide_path)
        except ValueError:
            return "", None
        return id_slug, version

    def _preview_context(self) -> tuple[Optional[PreviewTarget], Optional[deck_outline.SlideRow], str, Optional[str]]:
        """(target, row, title, language) of what the Preview shows: the focused slide as the deck calls it; the
        file of the other language that the language chip opened, as the deck calls it in that language (`row`
        stays the slot's, `language` is the file's); a frozen version, or a slide the deck doesn't use, alone."""
        row = self._focused_row()
        id_slug, version = self._file_slide()
        state = self.state
        path = self._slide_path
        if row is not None and (path is None or (id_slug == row.call.id_slug and version == row.call.version)):
            return for_call(state.project, state.deck, row.call, row.position, language=state.language, frame_number=row.frame_number,
                            occurrence_key=row.key, hidden=row.hidden, outline=state.outline), row, row.title, None
        if path is None:
            return None, None, "", None
        own = own_language(id_slug)
        partner = (row is not None and version is None and own in TRANSLATION_LANGUAGES and id_slug != row.call.id_slug
                   and row.matches(bare_id(id_slug)))
        target = (slide_target(state.project, state.deck, path, state.view, own) if partner
                  else for_path(state.project, path))
        title = deck_outline.slide_file_title(path, id_slug) if target else ""
        return target, row if partner else None, title, own if partner else None

    def _go_adjacent(self, direction: int) -> None:
        """The Preview's wheel ran past the last (first) reveal step: focus the slide after (before) the focused one,
        opening at its first step going forward, at its last going back -- as in a presentation."""
        state, row = self.state, self._focused_row()
        if state.deck is None or row is None:
            return
        rows = deck_outline.outline_rows(state.project, state.deck, state.view, state.language, outline=state.outline)
        index = next((i for i, r in enumerate(rows) if r.position == row.position), None)
        if index is None:
            return
        index += direction
        while 0 <= index < len(rows) and rows[index].hidden:
            index += direction
        if not 0 <= index < len(rows):
            return
        other = rows[index]
        target = for_call(state.project, state.deck, other.call, other.position, frame_number=other.frame_number,
                          occurrence_key=other.key, hidden=other.hidden, outline=state.outline)
        if target is not None:
            self.preview.set_step_choice(target.source_path, 1 if direction > 0 else None)
        state.set_focused_slide(other.call.id, occurrence_key=other.key)

    def _english_frames(self, state) -> Optional[deck_outline.Outline]:
        """An outline for for_call without a language, which takes the Instructor frame numbers of the English
        resolution: the state's own when it is English, else one resolution kept for the deck text. Without it each
        neighbour resolved every slot of the deck again (in German, six times after every Preview refresh)."""
        outline = state.outline
        if outline is not None and outline.matches(state.project, state.deck, "EN"):
            return outline
        cached = getattr(self, "_english_frames_cache", None)
        if cached is not None and cached.matches(state.project, state.deck, "EN"):
            return cached
        links = slide_language.TranslationLinks(state.project.slides_dir)
        slots = deck_outline.resolve_slots(state.project, state.deck, deck_editor.VIEW_INSTRUCTOR, "EN", links=links)
        cached = deck_outline.Outline(state.project, state.deck.path, state.deck.text, deck_editor.VIEW_INSTRUCTOR, "EN",
                                      [], links, {r.key: r.frame_number for r in slots})
        self._english_frames_cache = cached
        return cached

    def _neighbour_targets(self) -> list:
        """[(target, row)] of the slides nearest to the focused one in the deck (one before, one after, two before,
        two after, ...) that the view typesets: the Preview counts their reveal steps while it is idle."""
        state, row = self.state, self._focused_row()
        if state.deck is None or row is None:
            return []
        # Kept while the slide, the view and the resolved outline stay: building them reads every slide's language
        # header of the deck six times, on this thread, and the Preview asks after every refresh (v8.52.2).
        key = (id(state.outline), state.outline is not None, state.deck.path, row.position, state.view, state.language)
        cached = getattr(self, "_neighbours_cache", None)
        if cached is not None and cached[0] == key and cached[1] is state.outline:
            return cached[2]
        rows = deck_outline.outline_rows(state.project, state.deck, state.view, state.language, outline=state.outline)
        index = next((i for i, r in enumerate(rows) if r.position == row.position), None)
        if index is None:
            return []
        picks = []
        for distance in range(1, 4):
            picks += [rows[i] for i in (index - distance, index + distance) if 0 <= i < len(rows)]
        # Built as the focused slide's target is (preview_target.resolve_views), so a neighbour's step count is found
        # under the same key once that slide is focused.
        frames = self._english_frames(state)
        targets = [(for_call(state.project, state.deck, r.call, r.position, frame_number=r.frame_number,
                             occurrence_key=r.key, hidden=r.hidden, outline=frames), r) for r in picks if not r.hidden]
        if state.outline is not None:           # without a resolved outline there is nothing that says it is still right
            self._neighbours_cache = (key, state.outline, targets)
        return targets

    def _deck_targets(self) -> list:
        """[(target, row)] of every slide of the open deck that the view typesets, in deck order: the Preview reads
        their stored pages ahead. Built once per deck text, view, language and outline (about 50 ms for 400 slides)."""
        state = self.state
        if state.deck is None or state.outline is None:
            return []
        key = (id(state.outline), state.deck.path, state.view, state.language)
        cached = getattr(self, "_deck_targets_cache", None)
        if cached is not None and cached[0] == key and cached[1] is state.outline:
            return cached[2]
        rows = deck_outline.outline_rows(state.project, state.deck, state.view, state.language, outline=state.outline)
        frames = self._english_frames(state)
        targets = [(for_call(state.project, state.deck, r.call, r.position, frame_number=r.frame_number,
                             occurrence_key=r.key, hidden=r.hidden, outline=frames), r) for r in rows if not r.hidden]
        self._deck_targets_cache = (key, state.outline, targets)
        return targets

    # -- settings and housekeeping the window forwards ---------------------------------

    def refresh_colors(self) -> None:
        self.source.refresh_colors()

    def set_tab_width(self, chars: int) -> None:
        self.source.set_tab_width(chars)

    def refresh_model_preferences(self, models: list[str]) -> None:
        self.source.refresh_model_preferences(models)
