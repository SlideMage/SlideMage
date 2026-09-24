"""Tabs -> Blocks: the list of curated slide blocks (blocks.py), plus the
dialog a deck editor's "Insert block…" button opens. A block itself is
edited in the ordinary deck editor tab (qt_deck_editor_tab.py), through a
synthetic Deck.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import blocks
from .deck_scan import Deck


class BlocksTab(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        intro = QLabel(
            "A block is a curated, ordered set of slides (e.g. \"About me\", "
            "\"Sampling methods\") you can copy into any deck with a deck "
            "editor's \"Insert block…\" button. Each deck gets its own "
            "editable copy; \"Update block from here\" in a deck pushes that "
            "copy back to the block."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        toolbar = QHBoxLayout()
        for text, handler in (
            ("New block…", self._on_new),
            ("Open", self._on_open),
            ("Rename…", self._on_rename),
            ("Delete…", self._on_delete),
            ("Refresh", self.reload),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.block_list = QListWidget()
        self.block_list.itemDoubleClicked.connect(lambda _item: self._on_open())
        layout.addWidget(self.block_list, stretch=1)

        self.reload()

    def reload(self) -> None:
        selected = self._selected_name()
        self.block_list.clear()
        found = blocks.scan_blocks()
        for block in found:
            item = QListWidgetItem(f"{block.name}   —   {block.call_count} slide(s)")
            item.setData(Qt.ItemDataRole.UserRole, block.name)
            self.block_list.addItem(item)
            if block.name == selected:
                self.block_list.setCurrentItem(item)
        if not found:
            placeholder = QListWidgetItem("(no blocks yet -- click \"New block…\")")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.block_list.addItem(placeholder)

    def _selected_name(self) -> str | None:
        item = self.block_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _ask_name(self, title: str, current: str = "") -> str | None:
        while True:
            name, ok = QInputDialog.getText(self, title, "Block name:", text=current)
            if not ok:
                return None
            name = name.strip()
            problem = blocks.name_problem(name)
            if problem is None:
                return name
            QMessageBox.warning(self, title, problem)
            current = name

    def _on_new(self) -> None:
        name = self._ask_name("New block")
        if name is None:
            return
        blocks.create_block(name)
        self.reload()
        self.app.log(f"Created block {name}")
        self.app.open_block_editor(name)

    def _on_open(self) -> None:
        name = self._selected_name()
        if name is not None:
            self.app.open_block_editor(name)

    def _on_rename(self) -> None:
        old = self._selected_name()
        if old is None:
            return
        new = self._ask_name("Rename block", old)
        if new is None or new == old:
            return
        # Its editor tab is keyed by the old path -- close it first (nothing
        # in that tab is ever unsaved; every row action writes immediately).
        self.app.close_block_editor(blocks.block_path(old))
        try:
            changed = blocks.rename_block(old, new)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Rename block failed", str(exc))
            return
        self.reload()
        self.app.refresh_open_deck_editors()
        self.app.log(
            f"Renamed block {old} -> {new}"
            + (f" (updated its copies in {changed} deck(s))" if changed else "")
        )

    def _on_delete(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        reply = QMessageBox.question(
            self, "Delete block",
            f"Delete the block '{name}'?\n\nDecks that already contain a copy "
            f"of it keep their copy unchanged.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.app.close_block_editor(blocks.block_path(name))
        blocks.delete_block(name)
        self.reload()
        self.app.log(f"Deleted block {name}")


class InsertBlockDialog(QDialog):
    """Pick a block and where in `deck` to stamp it (blocks.insert_positions())."""

    def __init__(self, parent: QWidget, deck: Deck) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert block")
        self._blocks = [b for b in blocks.scan_blocks() if b.call_count]
        self._positions = blocks.insert_positions(deck)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.block_combo = QComboBox()
        for block in self._blocks:
            self.block_combo.addItem(f"{block.name} ({block.call_count} slide(s))")
        form.addRow("Block:", self.block_combo)
        self.position_combo = QComboBox()
        for position in self._positions:
            self.position_combo.addItem(position.label)
        # Default to appending after everything else -- the usual case.
        self.position_combo.setCurrentIndex(len(self._positions) - 1)
        form.addRow("Insert:", self.position_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Insert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not self._blocks:
            layout.insertWidget(0, QLabel(
                "No block with any slides yet -- create one under Tabs → Blocks."
            ))
            self.block_combo.setEnabled(False)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def selected(self) -> tuple[blocks.Block, blocks.InsertPosition]:
        return (
            self._blocks[self.block_combo.currentIndex()],
            self._positions[self.position_combo.currentIndex()],
        )
