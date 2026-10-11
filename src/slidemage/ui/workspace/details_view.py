"""The Details view: facts about the focused slide and the slide-level actions.

What the slide is (file, frame, version, language, slug) and Rename / Duplicate /
Delete (Duplicate opens the Add slide sheet). Everything else about the focused slide is a side panel (panels/): its
versions, where it is used, its visibility, citations, language (also Set
language), images, transcript entry and speaker notes.

All of these act on the slide's `-current.tex` and its frozen versions, not on
the version the open deck happens to pin. The work is in slide_rename; this
view asks, confirms and reports.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import alt_blocks, slide_language, slide_rename, slide_source, slide_versioning
from ...deck_editor import SLIDES_DIR
from ...deck_outline import SlideRow
from ..kit import kit_qss as q
from ..kit.widgets import Button, Surface
from .state import WorkspaceState

SAVE_FIRST = ("Save or revert this slide's unsaved changes first: the file is moved on disk, "
              "and an unsaved buffer would be saved under (or lost relative to) the wrong name.")


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class DetailsPane(Surface):
    def __init__(self, app, state: WorkspaceState, is_dirty: Callable[[Path], bool]) -> None:
        """`is_dirty(path)`: whether the Source view holds unsaved edits of that file."""
        super().__init__()
        self.app = app
        self.state = state
        self._is_dirty = is_dirty
        self._id_slug = ""
        self._row: Optional[SlideRow] = None

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
        return SLIDES_DIR / slide_language.current_name(self._id_slug)

    def show_slide(self, id_slug: str, row: Optional[SlideRow], message: str = "") -> None:
        """Show the slide `id_slug` ("" with a `message`: no slide), in the open deck as `row`."""
        self._id_slug, self._row = id_slug, row
        page = Surface()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        if not id_slug:
            layout.addWidget(_label(message or "Select a slide in the list.", q.DETAILS_LABEL))
            layout.addStretch(1)
        else:
            layout.addWidget(self._build_header())
            layout.addWidget(self._build_facts())
            layout.addLayout(self._build_actions())
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
        rename = Button("Rename…", "secondary", compact=True)
        rename.setToolTip("Change the slide's descriptive slug (the id and the language stay). "
                          "Rewrites every deck reference to match.")
        rename.clicked.connect(self._rename)
        grid.addWidget(rename, 4, 2)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return panel

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        duplicate = Button("Duplicate slide…", "secondary")
        duplicate.setToolTip("Add a copy of this slide, seeded from its saved content, to the deck.")
        duplicate.clicked.connect(self._duplicate)
        delete = Button("Delete slide…", "secondary")
        delete.setToolTip("Permanently delete the slide's file and its frozen versions, after checking "
                          "which decks still reference it.")
        delete.clicked.connect(self._delete)
        row.addWidget(duplicate)
        row.addWidget(delete)
        row.addStretch(1)
        return row

    # -- actions on the slide's file -----------------------------------------------------

    def _guard(self, title: str) -> bool:
        """Whether the slide's file may be moved: not while the Source view
        holds unsaved edits of it."""
        if self._is_dirty(self.current_path):
            QMessageBox.warning(self, title, SAVE_FIRST)
            return False
        return True

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
            f"This will rename {slide_language.current_name(old)} (and any frozen versions of it) to {slide_language.current_name(new)}, "
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
        self.app.slide_list.add_slide("duplicate", self._id_slug)

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
            f"Permanently delete {slide_language.current_name(id_slug)} (and any frozen versions of it)?\n\n{usage}\n\n"
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
