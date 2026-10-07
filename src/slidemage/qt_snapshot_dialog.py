"""Decks -> "Create deck snapshot..." (v5.33.0, docs/DECK_SNAPSHOT_PLAN.md):
pick one or more decks, folder or .zip, and whether the LaTeX package files
and the SlideMage app go in. The snapshots themselves are made one after the
other by deck_snapshot.snapshot_decks() on a worker thread (qt_gui.py); this
module also has the two questions around a run -- whether older snapshots
should be deleted, and the summary at the end."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from . import app_settings, deck_snapshot, open_path
from .deck_scan import Deck
from .deck_snapshot import ExistingSnapshot, SnapshotOptions, SnapshotResult
from .qt_theme import MUTED_LABEL

# Remembered between runs (app_settings), and used as they are by the
# snapshot the archive question offers.
OUTPUT_SETTING_KEY = "snapshot_output"        # "folder" / "zip"
TEXMF_SETTING_KEY = "snapshot_texmf"
APP_SETTING_KEY = "snapshot_app"

TEXMF_TOOLTIP = (
    "Copy the TeX distribution's package files the deck uses (class, style, "
    "Lua and font files) into the snapshot's texmf/ folder, as an exact record "
    "of the LaTeX version it was made with. Adds tens of MB per snapshot. "
    "Without it, the snapshot still records every package's version and file "
    "hash in snapshot.json."
)
APP_TOOLTIP = (
    "Put the SlideMage that made the snapshot into its app/ folder (the .exe, "
    "or a source archive when SlideMage runs from source). Rendering a "
    "snapshot never needs it; its version is recorded either way."
)


def saved_options() -> SnapshotOptions:
    """The settings last used in the dialog."""
    return SnapshotOptions(
        zip=app_settings.get(OUTPUT_SETTING_KEY, "folder") == "zip",
        texmf=bool(app_settings.get(TEXMF_SETTING_KEY, False)),
        include_app=bool(app_settings.get(APP_SETTING_KEY, False)),
    )


def save_options(options: SnapshotOptions) -> None:
    app_settings.set(OUTPUT_SETTING_KEY, "zip" if options.zip else "folder")
    app_settings.set(TEXMF_SETTING_KEY, options.texmf)
    app_settings.set(APP_SETTING_KEY, options.include_app)


def describe_options(options: SnapshotOptions) -> str:
    """"folder, without LaTeX package files" -- for the archive question."""
    parts = [".zip file" if options.zip else "folder",
             "with LaTeX package files" if options.texmf else "without LaTeX package files"]
    if options.include_app:
        parts.append("with the SlideMage app")
    return ", ".join(parts)


class SnapshotDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], decks: list[Deck],
                 preselected: set[str], busy: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create deck snapshot")
        self.resize(560, 560)
        self._decks = decks
        options = saved_options()

        layout = QVBoxLayout(self)
        intro = QLabel(
            "A snapshot is a self-contained copy of a deck -- slides, media, "
            "bibliography, template and LaTeX framework -- that compiles exactly "
            "as the deck does today, whatever changes later. Each selected deck "
            "gets its own snapshot; they are made one after the other.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        deck_header = QHBoxLayout()
        deck_header.addWidget(QLabel("<b>Decks</b>"))
        deck_header.addStretch(1)
        select_all = QPushButton("Select all")
        select_all.setAutoDefault(False)
        select_all.clicked.connect(lambda: self._set_all(True))
        deck_header.addWidget(select_all)
        select_none = QPushButton("Select none")
        select_none.setAutoDefault(False)
        select_none.clicked.connect(lambda: self._set_all(False))
        deck_header.addWidget(select_none)
        layout.addLayout(deck_header)

        self.deck_list = QListWidget()
        for deck in decks:
            label = f"{deck.name}   (archived)" if deck.archived else deck.name
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if deck.name in preselected
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, deck.name)
            self.deck_list.addItem(item)
        self.deck_list.itemChanged.connect(lambda _item: self._update_buttons())
        layout.addWidget(self.deck_list, stretch=1)

        self.show_archived = QCheckBox("Show archived decks")
        self.show_archived.setChecked(any(d.archived and d.name in preselected for d in decks))
        self.show_archived.toggled.connect(self._apply_archived_filter)
        layout.addWidget(self.show_archived)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("<b>Output</b>"))
        self.folder_radio = QRadioButton("Folder")
        self.zip_radio = QRadioButton(".zip file")
        group = QButtonGroup(self)
        group.addButton(self.folder_radio)
        group.addButton(self.zip_radio)
        (self.zip_radio if options.zip else self.folder_radio).setChecked(True)
        output_row.addWidget(self.folder_radio)
        output_row.addWidget(self.zip_radio)
        output_row.addStretch(1)
        layout.addLayout(output_row)

        self.texmf_checkbox = QCheckBox("Include LaTeX package files")
        self.texmf_checkbox.setToolTip(TEXMF_TOOLTIP)
        self.texmf_checkbox.setChecked(options.texmf)
        layout.addWidget(self.texmf_checkbox)
        self.app_checkbox = QCheckBox("Include SlideMage app")
        self.app_checkbox.setToolTip(APP_TOOLTIP)
        self.app_checkbox.setChecked(options.include_app)
        layout.addWidget(self.app_checkbox)

        note = QLabel(
            "Each deck is compiled in all its versions, then rendered once more "
            "from the snapshot to check that it is complete -- this takes a while "
            "for a large deck and occupies the compile slot.")
        note.setObjectName(MUTED_LABEL)
        note.setWordWrap(True)
        layout.addWidget(note)

        where_row = QHBoxLayout()
        where = QLabel(f"Saved to: {deck_snapshot.snapshots_dir()}")
        where.setObjectName(MUTED_LABEL)
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        where_row.addWidget(where, stretch=1)
        open_button = QPushButton("Open folder")
        open_button.setAutoDefault(False)
        open_button.setEnabled(deck_snapshot.snapshots_dir().is_dir())
        open_button.clicked.connect(
            lambda: open_path.open_in_default_app(deck_snapshot.snapshots_dir()))
        where_row.addWidget(open_button)
        layout.addLayout(where_row)

        self.busy_label = QLabel(
            "A compile run is in progress -- snapshots can be created once it has finished.")
        self.busy_label.setObjectName(MUTED_LABEL)
        self.busy_label.setWordWrap(True)
        self.busy_label.setVisible(busy)
        layout.addWidget(self.busy_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.create_button = QPushButton("Create snapshots")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._accept)
        button_row.addWidget(self.create_button)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)
        layout.addLayout(button_row)

        self._busy = busy
        self._apply_archived_filter(self.show_archived.isChecked())
        self._update_buttons()

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
        return SnapshotOptions(zip=self.zip_radio.isChecked(),
                               texmf=self.texmf_checkbox.isChecked(),
                               include_app=self.app_checkbox.isChecked())

    def _accept(self) -> None:
        if not self.selected_decks():
            return
        save_options(self.options())
        self.accept()


# -- the questions around a run --------------------------------------------------

DELETE_OLD, KEEP_OLD, CANCEL_RUN = "delete", "keep", "cancel"


def ask_about_old_snapshots(parent: Optional[QWidget],
                            existing: list[ExistingSnapshot]) -> str:
    """"Older snapshots exist" -- asked once per run, before it starts:
    DELETE_OLD, KEEP_OLD or CANCEL_RUN. Deleting happens per deck, only after
    that deck's new snapshot succeeded, and goes to the trash."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Older snapshots exist")
    lines = [snap.label for snap in existing]
    box.setText(
        "These decks already have snapshots:\n\n" + "\n".join(lines)
        + "\n\nDelete these older snapshots once the new ones have been created?")
    box.setInformativeText(
        "A deck's older snapshots are only deleted after its new snapshot has "
        "been created and checked, and they go to the Recycle Bin.")
    delete = box.addButton("Delete old snapshots", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep them", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(keep)
    box.exec()
    clicked = box.clickedButton()
    if clicked is delete:
        return DELETE_OLD
    if clicked is keep:
        return KEEP_OLD
    return CANCEL_RUN


def summary_text(results: list[SnapshotResult]) -> str:
    lines = []
    for r in results:
        if r.ok:
            line = f"✓  {r.deck_name}: {r.path.name}  ({deck_snapshot.format_size(r.size)})"
            if r.deleted:
                line += f" -- {len(r.deleted)} older snapshot(s) moved to the trash"
        elif r.skipped:
            line = f"–  {r.deck_name}: skipped (stopped)"
        else:
            line = f"✗  {r.deck_name}: {r.error}"
        lines.append(line)
        lines.extend(f"      warning: {w}" for w in r.warnings)
    return "\n".join(lines)


def show_summary(parent: Optional[QWidget], results: list[SnapshotResult]) -> None:
    ok = sum(1 for r in results if r.ok)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information if ok == len(results) else QMessageBox.Icon.Warning)
    box.setWindowTitle("Deck snapshots")
    box.setText(f"{ok} of {len(results)} snapshot(s) created.")
    box.setInformativeText(summary_text(results))
    open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    open_button.setEnabled(deck_snapshot.snapshots_dir().is_dir())
    box.exec()
    if box.clickedButton() is open_button:
        open_path.open_in_default_app(deck_snapshot.snapshots_dir())
