# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A topic block's metadata, ordered slides and linked decks."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit, QPlainTextEdit, QScrollArea, QVBoxLayout

from .... import deck_scan, topic_blocks
from ...background import run_in_background
from ...kit.flow import FlowLayout
from ...kit.tokens import SPACE
from ...kit.widgets import Button, Card, Chip, Field, RowButton, Surface, caption, clear_layout, text_label
from ...workspace.slide_tree import BLOCK
from .pictures import load_picture


class BlockView(QScrollArea):
    changed = Signal()

    def __init__(self, app):
        super().__init__()
        self.app, self.block, self._pictures = app, None, None
        self._write = None
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        content = Surface()
        self.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        body.setSpacing(SPACE.lg)
        head = QHBoxLayout()
        self.heading = text_label("Topic block", "title")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        head.addWidget(self.heading, 1)
        edit = Button("Edit in deck")
        edit.clicked.connect(lambda: self.open_deck())
        head.addWidget(edit)
        self.insert = Button("Insert into deck…", "primary")
        self.insert.clicked.connect(self._insert)
        head.addWidget(self.insert)
        body.addLayout(head)
        self.key = text_label("", "mono")
        self.key.setTextFormat(Qt.TextFormat.PlainText)
        self.key.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.key)
        metadata = Card()
        fields = QHBoxLayout()
        self.title = QLineEdit()
        self.title.editingFinished.connect(lambda: self.save_metadata("SlideMage block", self.title.text()))
        fields.addWidget(Field("Title", self.title), 1, Qt.AlignmentFlag.AlignTop)
        topics = Surface()
        self.topics = FlowLayout(topics)
        fields.addWidget(Field("Topics", topics), 1, Qt.AlignmentFlag.AlignTop)
        metadata.layout().addLayout(fields)
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(72)
        self.description.installEventFilter(self)
        metadata.layout().addWidget(Field("Description", self.description))
        body.addWidget(metadata)
        self.status = caption()
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.count = text_label("", "heading")
        body.addWidget(self.count)
        hint = caption("Reorder or remove slides in a deck that uses the block; the change reaches every deck.")
        hint.setWordWrap(True)
        body.addWidget(hint)
        self.slides = FlowLayout()
        body.addLayout(self.slides)
        body.addWidget(text_label("Used in decks", "heading"))
        self.used_in = QVBoxLayout()
        body.addLayout(self.used_in)
        body.addStretch(1)

    def set_block(self, block, groups):
        self.shutdown()
        self.block = block
        self.heading.setText(block.title)
        self.key.setText(f"blocks/{block.path.name} · \\slideblock{{{block.path.stem}}}")
        self.title.setText(block.title)
        self.description.setPlainText(block.description)
        self.status.clear()
        self.insert.setEnabled(self.app.state.deck is not None)
        self.count.setText(f"{len(block.calls)} slides, in order")
        self._show_topics()
        clear_layout(self.used_in)
        for deck in block.decks:
            row = RowButton("link", deck.name, "Linked · changes here reach this deck", elide_title=True)
            row.clicked.connect(lambda deck=deck: self.open_deck(deck))
            self.used_in.addWidget(row)
        if not block.decks:
            self.used_in.addWidget(caption("In no deck. Edit the calls in Source.", "warning"))
        clear_layout(self.slides)
        members = {slug: row for row in groups for slug in row.members}
        pictures = []
        for n, call in enumerate(block.calls, 1):
            row = members.get(call.id_slug)
            tile = Surface()
            column = QVBoxLayout(tile)
            column.setContentsMargins(0, 0, 0, 0)
            picture = text_label("No render yet", "secondary")
            picture.setFixedSize(156, 88)
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame = Card()
            frame.layout().setContentsMargins(0, 0, 0, 0)
            frame.layout().addWidget(picture)
            column.addWidget(frame)
            title = caption(f"{n}. {row.title if row else call.id_slug}")
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setFixedWidth(156)
            title.setWordWrap(True)
            column.addWidget(title)
            tile.setToolTip(call.id_slug)
            self.slides.addWidget(tile)
            if row:
                pictures.append((picture, row))
        ctx, language = self.app.project, self.app.state.language
        resolver = getattr(self.app.background.renderer, "resolver", None)

        def load(cancel):
            images = []
            for _label, row in pictures:
                if cancel.is_set():
                    break
                images.append(load_picture(ctx, row, resolver, language))
            return images

        def done(images, error):
            self._pictures = None
            if error is None:
                for (label, _row), image in zip(pictures, images):
                    if not image.isNull():
                        label.setPixmap(QPixmap.fromImage(image).scaled(
                            label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self._pictures = run_in_background(load, done, parent=self)

    def save_metadata(self, field, value):
        if self.block is None:
            return
        value = value.strip()
        previous = {"SlideMage block": self.block.title, "Topics": ", ".join(self.block.topics),
                    "Description": self.block.description}[field]
        if value == previous:
            return
        if self._write is not None:
            return
        block = self.block
        self._write = True
        self.widget().setEnabled(False)

        def done(_result, error):
            self._write = None
            self.widget().setEnabled(True)
            if self.block is not block:
                return
            if error is not None:
                self.status.setText(f"Could not save block: {error}")
                return
            if field == "SlideMage block":
                block.title = value or block.path.stem
                self.heading.setText(block.title)
                self.title.setText(block.title)
            elif field == "Topics":
                block.topics = [t.strip() for t in value.split(",") if t.strip()]
                self._show_topics()
            else:
                block.description = value
            self.status.clear()
            self.changed.emit()

        self._write = run_in_background(
            lambda: topic_blocks.update_metadata(block.path, field, value, expected=previous), done, parent=self)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "description", None) and event.type() == QEvent.Type.FocusOut:
            self.save_metadata("Description", " ".join(self.description.toPlainText().splitlines()))
        return super().eventFilter(watched, event)

    def _show_topics(self):
        clear_layout(self.topics)
        for topic in self.block.topics:
            chip = Chip(topic + " ×", pressable=True)
            chip.clicked.connect(lambda topic=topic: self.save_metadata(
                "Topics", ", ".join(t for t in self.block.topics if t != topic)))
            self.topics.addWidget(chip)
        add = Button("+ Topic", "ghost")
        add.clicked.connect(self._add_topic)
        self.topics.addWidget(add)

    def _add_topic(self):
        topic, accepted = QInputDialog.getText(self, "Add topic", "Topic:")
        if accepted and topic.strip():
            self.save_metadata("Topics", ", ".join(dict.fromkeys([*self.block.topics, topic.strip()])))

    def _insert(self):
        if self.app.state.deck is not None:
            self.app.slide_list.add_slide(source="block")

    def open_deck(self, deck=None):
        if deck is None:
            current = self.app.state.deck
            deck = next((d for d in self.block.decks if current and d.path == current.path),
                        self.block.decks[0] if self.block.decks else None)
        if deck is None:
            self.app.open_slide_editor(self.block.path, tab=True)
            return
        self.app.stack.setCurrentWidget(self.app.centre)
        if not self.app.state.set_deck(deck_scan.read_deck(deck.path)):
            self.app.slide_list.rebuild(preserve_focus=True)
        tree = self.app.slide_list.tree
        for head in tree.section_items():
            for item in [head, *(head.child(n) for n in range(head.childCount()))]:
                block = item.data(0, BLOCK)
                if block and block.block == self.block.path.stem:
                    first = block.rows[0]
                    self.app.state.set_focused_slide(first.call.id, occurrence_key=first.key)
                    tree.clearSelection()
                    keys = {row.key for row in block.rows}
                    for child in tree.slide_items():
                        child.setSelected(tree.data_of(child).key in keys)
                    tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
                    head.setExpanded(True)
                    tree.scrollToItem(item)
                    self.app.state.set_mode("preview")
                    return

    def shutdown(self):
        if self._pictures is not None:
            self._pictures.stop(wait_ms=0)
            self._pictures = None
