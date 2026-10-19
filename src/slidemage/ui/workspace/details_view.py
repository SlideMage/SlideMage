# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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

from PySide6.QtCore import Qt, Signal
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

from ... import ai_review, alt_blocks, slide_language, slide_rename, slide_source, slide_versioning
from ...deck_outline import SlideRow
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, Surface
from . import compare_rendered
from .state import WorkspaceState

SAVE_FIRST = ("This slide's edits in the Source view could not be saved (see the notice there). Resolve that first: "
              "the file is moved on disk, and the buffer would be saved under (or lost relative to) the wrong name.")


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class DetailsPane(Surface):
    duplicate_requested = Signal(str)   # the id-slug of the slide to duplicate into a deck
    open_requested = Signal(object)     # the Path of a slide file (a translation, a frozen version) to open in the Source view

    def __init__(self, app, state: WorkspaceState, is_dirty: Callable[[Path], bool]) -> None:
        """`is_dirty(path)`: whether the Source view holds edits of that file that could not be saved (writing the others first)."""
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
        return self.app.project.slides_dir / slide_language.current_name(self._id_slug)

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
            layout.addWidget(self._build_related())
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
        path = self.app.project.slides_dir / self._row.call.source_filename if self._row else self.current_path
        if ai_review.is_unreviewed(self.app.project, path):
            row.addWidget(Chip("Not reviewed", "warning"))
            reviewed = Button("Mark reviewed", "secondary", compact=True)
            reviewed.clicked.connect(lambda: self.app.slide_list.mark_reviewed([path]))
            row.addWidget(reviewed)
            if ai_review.last_before(self.app.project, path) is not None:
                compare = Button("Compare rendered", "secondary", compact=True)
                compare.clicked.connect(lambda: compare_rendered.compare_with_last_edit(self.app, path))
                row.addWidget(compare)
        holder = Surface()
        holder.setLayout(row)
        return holder

    def _build_facts(self) -> QWidget:
        path = self.current_path
        text = slide_source.read_slide_source(path)[0] if path.is_file() else ""
        version = slide_versioning.version_text(text)
        badge = slide_language.badge_for(self.app.project, self._id_slug)
        _language, _, slug = slide_rename.parse_id_slug(self._id_slug)
        panel, layout = self._panel("Slide")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        rows = [("File", path.name), ("Frame", alt_blocks.frame_type(text) or "none found"),
                ("Version", f"v{version}" if version else "untracked"),
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

    def _related_row(self, grid: QGridLayout, index: int, name: str, value: str, path: Path, chip: str = "") -> None:
        grid.addWidget(_label(name, q.DETAILS_LABEL), index, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(_label(value, q.DETAILS_VALUE), index, 1)
        if chip:
            grid.addWidget(Chip(chip, "warning"), index, 2)
        open_button = Button("Open", "secondary", compact=True)
        open_button.setToolTip(f"Open {path.name} in the Source view")
        open_button.clicked.connect(lambda _checked=False, p=path: self.open_requested.emit(p))
        grid.addWidget(open_button, index, 3)

    def _build_related(self) -> QWidget:
        """The other language of the slide and its frozen earlier versions, each with a way to open the file."""
        project = self.app.project
        panel, layout = self._panel("Other languages and earlier versions")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        index = 0
        try:
            link = slide_language.translation_link(project, self._id_slug)
        except OSError:
            link = None
        if link is not None:
            role = "Original" if not link.is_translation else "Translation of"
            self._related_row(grid, index, f"{link.language or 'Other language'}", f"{role}: {link.path.name}", link.path,
                              "may be out of date" if link.outdated else "")
            index += 1
        frozen = []
        for path in project.slides_dir.glob(f"{self._id_slug}-v*.tex"):
            match = slide_language.FROZEN_RE.search(path.name)
            if match and path.name[:match.start()] == self._id_slug:
                frozen.append((tuple(int(part) for part in match.group(1).split("-")), match.group(1), path))
        for _key, version, path in sorted(frozen, reverse=True):
            self._related_row(grid, index, slide_versioning.version_label(version), path.name, path)
            index += 1
        if index == 0:
            grid.addWidget(_label("No translation and no frozen earlier version.", q.DETAILS_LABEL), 0, 0, 1, 4)
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
        holds edits of it that could not be saved."""
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
        n_refs = slide_rename.count_references(self.app.project, old)
        confirm = QMessageBox.question(
            self, "Rename slide",
            f"This will rename {slide_language.current_name(old)} (and any frozen versions of it) to {slide_language.current_name(new)}, "
            f"and rewrite {n_refs} deck reference(s) to match. Continue?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            new = slide_rename.rename_slide_slug(self.app.project, old, slug)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Rename slide failed", str(exc))
            return
        self.app.log(f"Renamed slide {old} -> {new} ({n_refs} deck reference(s) updated)")
        self.app.refresh_open_deck_editors()

    def _duplicate(self) -> None:
        self.duplicate_requested.emit(self._id_slug)

    def _delete(self) -> None:
        id_slug = self._id_slug
        if not self._guard("Delete slide"):
            return
        decks = slide_rename.deck_names_referencing(self.app.project, id_slug)
        n_refs = slide_rename.count_references(self.app.project, id_slug)
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
            result = slide_rename.delete_slide_id(self.app.project, id_slug)
        except (FileNotFoundError, OSError) as exc:
            QMessageBox.critical(self, "Delete slide failed", str(exc))
            return
        self.app.log(f"Deleted slide {id_slug} ({result['files_removed']} file(s), "
                     f"{result['deck_references_removed']} deck reference(s) removed)")
        self.state.set_focused_slide(None)
        self.app.refresh_open_deck_editors()
