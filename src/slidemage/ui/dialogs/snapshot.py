"""The Snapshots sheet (UI_REDESIGN_PLAN.md, step 9; docs/DECK_SNAPSHOT_PLAN.md): pick one or more
decks, folder or .zip, and whether the LaTeX package files and the SlideMage app go in.

The snapshots themselves are made one after the other by deck_snapshot.snapshot_decks() on a
worker thread (ui/workspace/compile_jobs.py). This module also has the two questions around a run
-- whether older snapshots should be deleted, and the summary at the end. What is remembered
between runs, and the text of the summary, are deck_snapshot's.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ... import deck_snapshot, open_path
from ...deck_scan import Deck
from ...deck_snapshot import ExistingSnapshot, SnapshotOptions, SnapshotResult
from ..kit import kit_qss as q
from ..kit.widgets import Button, Field, ModalSheet, SegmentedControl, Surface, caption

TEXMF_TIP = (
    "Copy the TeX distribution's package files the deck uses (class, style, Lua and font files) "
    "into the snapshot's texmf/ folder, as an exact record of the LaTeX version it was made with. "
    "Adds tens of MB per snapshot. Without it, the snapshot still records every package's version "
    "and file hash in snapshot.json.")
APP_TIP = (
    "Put the SlideMage that made the snapshot into its app/ folder (the .exe, or a source archive "
    "when SlideMage runs from source). Rendering a snapshot never needs it; its version is "
    "recorded either way.")
OUTPUTS = (("folder", "Folder"), ("zip", ".zip file"))

DELETE_OLD, KEEP_OLD, CANCEL_RUN = "delete", "keep", "cancel"


class SnapshotSheet(ModalSheet):
    def __init__(self, parent: Optional[QWidget], decks: list[Deck], preselected: set[str],
                 busy: bool = False) -> None:
        super().__init__("Create deck snapshot", parent, width=600)
        self._decks = decks
        self._busy = busy
        options = deck_snapshot.saved_options()
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(caption(
            "A snapshot is a self-contained copy of a deck -- slides, media, bibliography, "
            "template and LaTeX framework -- that compiles exactly as the deck does today, "
            "whatever changes later. Each selected deck gets its own snapshot; they are made "
            "one after the other."))

        self.deck_list = QListWidget()
        self.deck_list.setFixedHeight(150)
        for deck in decks:
            item = QListWidgetItem(f"{deck.name}   (archived)" if deck.archived else deck.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if deck.name in preselected else Qt.CheckState.Unchecked)
            self.deck_list.addItem(item)
        self.deck_list.itemChanged.connect(lambda _item: self._update_buttons())
        bulk = Surface()
        bulk_row = QHBoxLayout(bulk)
        bulk_row.setContentsMargins(0, 0, 0, 0)
        self.show_archived = QCheckBox("Show archived decks")
        self.show_archived.setChecked(any(d.archived and d.name in preselected for d in decks))
        self.show_archived.toggled.connect(self._apply_archived_filter)
        select_all = Button("Select all", "ghost", compact=True)
        select_all.clicked.connect(lambda: self._set_all(True))
        select_none = Button("Select none", "ghost", compact=True)
        select_none.clicked.connect(lambda: self._set_all(False))
        bulk_row.addWidget(self.show_archived)
        bulk_row.addStretch(1)
        bulk_row.addWidget(select_all)
        bulk_row.addWidget(select_none)
        decks_box = Surface()
        decks_layout = QVBoxLayout(decks_box)
        decks_layout.setContentsMargins(0, 0, 0, 0)
        decks_layout.setSpacing(6)
        decks_layout.addWidget(self.deck_list)
        decks_layout.addWidget(bulk)
        layout.addWidget(Field("Decks", decks_box))

        self.output = SegmentedControl(OUTPUTS, current="zip" if options.zip else "folder")
        layout.addWidget(Field("Output", self.output))
        self.texmf_checkbox = QCheckBox("Include LaTeX package files")
        self.texmf_checkbox.setToolTip(TEXMF_TIP)
        self.texmf_checkbox.setChecked(options.texmf)
        self.app_checkbox = QCheckBox("Include SlideMage app")
        self.app_checkbox.setToolTip(APP_TIP)
        self.app_checkbox.setChecked(options.include_app)
        layout.addWidget(self.texmf_checkbox)
        layout.addWidget(self.app_checkbox)
        layout.addWidget(caption(
            "Each deck is compiled in all its versions, then rendered once more from the snapshot "
            "to check that it is complete -- this takes a while for a large deck and occupies the "
            "compile slot."))

        folder = deck_snapshot.snapshots_dir()
        where = Surface()
        where_row = QHBoxLayout(where)
        where_row.setContentsMargins(0, 0, 0, 0)
        path = QLabel(str(folder))
        path.setObjectName(q.PANEL_MONO)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_folder = Button("Open folder", "secondary", compact=True)
        open_folder.setEnabled(folder.is_dir())
        open_folder.clicked.connect(lambda: open_path.open_in_default_app(folder))
        where_row.addWidget(path, 1)
        where_row.addWidget(open_folder)
        layout.addWidget(Field("Saved to", where))

        self.busy_label = caption("A compile run is in progress -- snapshots can be created once it has finished.")
        self.busy_label.setVisible(busy)
        layout.addWidget(self.busy_label)

        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        self.create_button = self.add_button("Create snapshots", kind="primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._accept)
        self._apply_archived_filter(self.show_archived.isChecked())

    # -- state -----------------------------------------------------------------

    def _items(self) -> list[QListWidgetItem]:
        return [self.deck_list.item(i) for i in range(self.deck_list.count())]

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(state)

    def _apply_archived_filter(self, show: bool) -> None:
        for item, deck in zip(self._items(), self._decks):
            if deck.archived:
                item.setHidden(not show)
                if not show:
                    item.setCheckState(Qt.CheckState.Unchecked)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.create_button.setEnabled(not self._busy and bool(self.selected_decks()))

    def selected_decks(self) -> list[Deck]:
        """The checked decks, in list order."""
        return [deck for item, deck in zip(self._items(), self._decks)
                if not item.isHidden() and item.checkState() == Qt.CheckState.Checked]

    def options(self) -> SnapshotOptions:
        return SnapshotOptions(zip=self.output.current() == "zip",
                               texmf=self.texmf_checkbox.isChecked(),
                               include_app=self.app_checkbox.isChecked())

    def _accept(self) -> None:
        if self.selected_decks():
            deck_snapshot.save_options(self.options())
            self.accept()


# -- the questions around a run --------------------------------------------------

class _OldSnapshotsSheet(ModalSheet):
    def __init__(self, parent: Optional[QWidget], existing: list[ExistingSnapshot]) -> None:
        super().__init__("Older snapshots exist", parent, width=560)
        self.choice = CANCEL_RUN
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(caption("These decks already have snapshots. Delete these older snapshots "
                                  "once the new ones have been created?"))
        listing = QLabel("\n".join(snap.label for snap in existing))
        listing.setObjectName(q.PANEL_MONO)
        layout.addWidget(listing)
        layout.addWidget(caption(
            "A deck's older snapshots are only deleted after its new snapshot has been created "
            "and checked, and they go to the Recycle Bin."))
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        delete = self.add_button("Delete old snapshots")
        delete.clicked.connect(lambda: self._finish(DELETE_OLD))
        keep = self.add_button("Keep them", kind="primary")
        keep.clicked.connect(lambda: self._finish(KEEP_OLD))

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()


def ask_about_old_snapshots(parent: Optional[QWidget], existing: list[ExistingSnapshot]) -> str:
    """"Older snapshots exist" -- asked once per run, before it starts: DELETE_OLD, KEEP_OLD or
    CANCEL_RUN. Deleting happens per deck, only after that deck's new snapshot succeeded, and goes
    to the trash."""
    sheet = _OldSnapshotsSheet(parent, existing)
    sheet.exec()
    return sheet.choice


def show_summary(parent: Optional[QWidget], results: list[SnapshotResult]) -> None:
    ok = sum(1 for r in results if r.ok)
    sheet = ModalSheet("Deck snapshots", parent, width=560)
    body = Surface()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(QLabel(f"{ok} of {len(results)} snapshot(s) created."))
    details = QLabel(deck_snapshot.summary_text(results))
    details.setObjectName(q.PANEL_MONO)
    details.setWordWrap(True)
    details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(details)
    sheet.add_tab("", body)
    folder = deck_snapshot.snapshots_dir()
    open_folder = sheet.add_button("Open folder")
    open_folder.setEnabled(folder.is_dir())
    open_folder.clicked.connect(lambda: open_path.open_in_default_app(folder))
    sheet.add_button("Close", kind="primary", role="accept")
    sheet.exec()
