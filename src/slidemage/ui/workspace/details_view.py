"""The Details view: facts about the focused slide and the slide-level actions.

What the slide is (file, frame, version, language, slug), Set language /
Rename / Duplicate / Delete, and the transcript summary. Its frozen versions,
where it is used and its visibility in the open deck are side panels
(panels/). The summary is a note that lives in media/alt-text.json, not in the
.tex file; until the Transcript entry panel (step 6b) takes it over it has its
own Save, and leaving the slide saves a pending edit so that it is never lost.

All of these act on the slide's `-current.tex` and its frozen versions, not on
the version the open deck happens to pin. The work is in slide_rename and
alt_images; this view asks, confirms and reports.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import alt_blocks, alt_images, slide_language, slide_rename, slide_source, slide_versioning
from ...deck_editor import SLIDES_DIR
from ...deck_outline import SlideRow
from ...qt_duplicate_slide_dialog import DuplicateSlideDialog
from ..kit import kit_qss as q
from ..kit.widgets import Button, PopoverMenu, Surface
from .state import WorkspaceState

# The language menu: label -> the code slide_rename.set_slide_language() takes.
LANGUAGE_CHOICES = (("EN", "EN"), ("DE", "DE"), ("Multilingual", "mult"))
SAVE_FIRST = ("Save or revert this slide's unsaved changes first: the file is moved on disk, "
              "and an unsaved buffer would be saved under (or lost relative to) the wrong name.")


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class DetailsPane(Surface):
    summary_dirty_changed = Signal(bool)   # the transcript summary has (no) unsaved edits

    def __init__(self, app, state: WorkspaceState, is_dirty: Callable[[Path], bool]) -> None:
        """`is_dirty(path)`: whether the Source view holds unsaved edits of that file."""
        super().__init__()
        self.app = app
        self.state = state
        self._is_dirty = is_dirty
        self._id_slug = ""
        self._row: Optional[SlideRow] = None
        self._summary: Optional[QPlainTextEdit] = None
        self.summary_dirty = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setObjectName(q.SURFACE)
        self._scroll.viewport().setObjectName(q.SURFACE)
        outer.addWidget(self._scroll)
        self._scroll.setWidget(Surface())

    # -- the slide -----------------------------------------------------------------

    @property
    def current_path(self) -> Path:
        return SLIDES_DIR / f"{self._id_slug}-current.tex"

    def show_slide(self, id_slug: str, row: Optional[SlideRow], message: str = "") -> None:
        """Show the slide `id_slug` ("" with a `message`: no slide), in the open deck as `row`."""
        self.flush_summary()
        self._id_slug, self._row = id_slug, row
        page = Surface()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        self._summary = None
        if not id_slug:
            layout.addWidget(_label(message or "Select a slide in the list.", q.DETAILS_LABEL))
            layout.addStretch(1)
        else:
            layout.addWidget(self._build_header())
            layout.addWidget(self._build_facts())
            layout.addLayout(self._build_actions())
            layout.addWidget(self._build_summary())
            layout.addStretch(1)
        self._scroll.setWidget(page)

    def _panel(self, title: str) -> tuple[Surface, QVBoxLayout]:
        panel = Surface()
        panel.setObjectName(q.DETAILS_PANEL)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(_label(title, q.DETAILS_HEAD))
        return panel, layout

    def _build_header(self) -> QWidget:
        row = QHBoxLayout()
        title = self._row.title if self._row else self._id_slug
        row.addWidget(_label(title, q.DETAILS_TITLE), 1)
        row.addWidget(_label(slide_language.bare_id(self._id_slug), q.PREVIEW_ID))
        holder = Surface()
        holder.setLayout(row)
        return holder

    def _build_facts(self) -> QWidget:
        path = self.current_path
        text = slide_source.read_slide_source(path)[0] if path.is_file() else ""
        version = slide_versioning.parse_version(text)
        badge = slide_language.badge_for(self._id_slug, path)
        _language, _, slug = slide_rename.parse_id_slug(self._id_slug)
        panel, layout = self._panel("Slide")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        rows = [("File", path.name), ("Frame", alt_blocks.frame_type(text) or "none found"),
                ("Version", f"v{slide_versioning.format_dot(version)}" if version else "untracked"),
                ("Language", badge.text().strip("[]") or "untagged"), ("Slug", slug)]
        for i, (name, value) in enumerate(rows):
            grid.addWidget(_label(name, q.DETAILS_LABEL), i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_label(value, q.DETAILS_VALUE), i, 1)
        language = Button("Set language ▾", "secondary", compact=True)
        language.setToolTip("Rename the slide to the language and rewrite every deck reference to match.")
        language.clicked.connect(lambda: self._open_language_menu(language))
        rename = Button("Rename…", "secondary", compact=True)
        rename.setToolTip("Change the slide's descriptive slug (the id and the language stay). "
                          "Rewrites every deck reference to match.")
        rename.clicked.connect(self._rename)
        grid.addWidget(language, 3, 2)
        grid.addWidget(rename, 4, 2)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return panel

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        duplicate = Button("Duplicate slide…", "secondary")
        duplicate.setToolTip("A new slide seeded from this one's saved content: a plain copy, or a "
                             "cross-referenced translation (with an optional machine-translation pass).")
        duplicate.clicked.connect(self._duplicate)
        delete = Button("Delete slide…", "secondary")
        delete.setToolTip("Permanently delete the slide's file and its frozen versions, after checking "
                          "which decks still reference it.")
        delete.clicked.connect(self._delete)
        row.addWidget(duplicate)
        row.addWidget(delete)
        row.addStretch(1)
        return row

    def _build_summary(self) -> QWidget:
        panel, layout = self._panel("Transcript summary")
        self._summary = QPlainTextEdit()
        self._summary.setFixedHeight(64)
        self._summary.setPlaceholderText(
            "Optional: shown at the top of this slide's transcript entry, before its body text.")
        bare = slide_language.bare_id(self._id_slug)
        self._summary.setPlainText(alt_images.load_slide_notes().get(bare, alt_images.SlideNotes()).summary)
        self._set_summary_dirty(False)
        self._summary_save = Button("Save summary", "secondary", compact=True)
        self._summary_save.setEnabled(False)
        # Connected after the initial text: loading the slide must not mark it changed.
        self._summary.textChanged.connect(self._on_summary_edited)
        self._summary_save.clicked.connect(self._save_summary)
        layout.addWidget(self._summary)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._summary_save)
        layout.addLayout(row)
        return panel

    def _set_summary_dirty(self, dirty: bool) -> None:
        if dirty != self.summary_dirty:
            self.summary_dirty = dirty
            self.summary_dirty_changed.emit(dirty)

    def _on_summary_edited(self) -> None:
        self._set_summary_dirty(True)
        self._summary_save.setEnabled(True)

    def _save_summary(self) -> None:
        self.flush_summary()
        self._summary_save.setEnabled(False)

    def flush_summary(self) -> None:
        """Save a pending summary edit (it has no Discard: leaving the slide or the deck saves it)."""
        if self._summary is None or not self.summary_dirty:
            return
        bare, text = slide_language.bare_id(self._id_slug), self._summary.toPlainText().strip()

        def mutate(notes: dict[str, alt_images.SlideNotes]) -> bool:
            notes.setdefault(bare, alt_images.SlideNotes()).summary = text
            return True

        alt_images.update_slide_notes(mutate)
        self._set_summary_dirty(False)
        self.app.log(f"Saved transcript summary for {bare}" if text else f"Cleared transcript summary for {bare}")

    # -- actions on the slide's file -----------------------------------------------------

    def _guard(self, title: str) -> bool:
        """Whether the slide's file may be moved or copied: not while the Source view
        holds unsaved edits of it."""
        if self._is_dirty(self.current_path):
            QMessageBox.warning(self, title, SAVE_FIRST)
            return False
        return True

    def _open_language_menu(self, anchor: QWidget) -> None:
        own = slide_language.own_language(self._id_slug)
        menu = PopoverMenu(self, min_width=180)
        for label, code in LANGUAGE_CHOICES:
            menu.add_item(code, label, icon="check" if code == own else "")
        menu.triggered.connect(self._set_language)
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(anchor)

    def _set_language(self, language: str) -> None:
        old = self._id_slug
        if slide_language.own_language(old) == language or not self._guard("Set language"):
            return
        n_refs = slide_rename.count_references(old)
        confirm = QMessageBox.question(
            self, "Set language",
            f"This will rename {old}-current.tex (and any frozen versions of it) to language "
            f"{language}, and rewrite {n_refs} deck reference(s) to match. Continue?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            new = slide_rename.set_slide_language(old, language)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Set language failed", str(exc))
            return
        self.app.log(f"Set language of {old} -> {new} ({n_refs} deck reference(s) updated)")
        self.app.refresh_open_deck_editors()

    def _rename(self) -> None:
        old = self._id_slug
        _, _, current_slug = slide_rename.parse_id_slug(old)
        if not self._guard("Rename slide"):
            return
        slug, ok = QInputDialog.getText(
            self, "Rename slide",
            "New slug (letters, digits, and single hyphens between words only; the slide's "
            "3-character id and language segment, if any, stay the same):",
            QLineEdit.EchoMode.Normal, current_slug)
        if not ok or not slug or slug == current_slug:
            return
        try:
            new = slide_rename.compute_new_slug(old, slug)
        except ValueError as exc:
            QMessageBox.critical(self, "Rename slide", str(exc))
            return
        n_refs = slide_rename.count_references(old)
        confirm = QMessageBox.question(
            self, "Rename slide",
            f"This will rename {old}-current.tex (and any frozen versions of it) to {new}-current.tex, "
            f"and rewrite {n_refs} deck reference(s) to match. Continue?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            new = slide_rename.rename_slide_slug(old, slug)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Rename slide failed", str(exc))
            return
        self.app.log(f"Renamed slide {old} -> {new} ({n_refs} deck reference(s) updated)")
        self.app.refresh_open_deck_editors()

    def _duplicate(self) -> None:
        if not self._guard("Duplicate slide"):
            return
        dialog = DuplicateSlideDialog(self.app, self._id_slug, self.current_path)
        if dialog.exec() != DuplicateSlideDialog.DialogCode.Accepted:
            return
        self.app.log(f"Duplicated {self._id_slug} -> {dialog.new_id_slug}")
        self.app.open_slide_editor(dialog.new_path)

    def _delete(self) -> None:
        id_slug = self._id_slug
        if not self._guard("Delete slide"):
            return
        decks = slide_rename.deck_names_referencing(id_slug)
        n_refs = slide_rename.count_references(id_slug)
        usage = (f"This slide is referenced {n_refs} time(s) across {len(decks)} deck(s): {', '.join(decks)}. "
                 "Deleting it will also remove those references, so none of those decks is left "
                 "pointing at a file that no longer exists." if decks
                 else "This slide is not currently referenced by any deck.")
        confirm = QMessageBox.question(
            self, "Delete slide",
            f"Permanently delete {id_slug}-current.tex (and any frozen versions of it)?\n\n{usage}\n\n"
            "This cannot be undone from within SlideMage.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            result = slide_rename.delete_slide_id(id_slug)
        except (FileNotFoundError, OSError) as exc:
            QMessageBox.critical(self, "Delete slide failed", str(exc))
            return
        self.app.log(f"Deleted slide {id_slug} ({result['files_removed']} file(s), "
                     f"{result['deck_references_removed']} deck reference(s) removed)")
        self.state.set_focused_slide(None)
        self.app.refresh_open_deck_editors()
