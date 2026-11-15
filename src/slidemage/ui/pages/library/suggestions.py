# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared runs and single slides that can join the reusable collection."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QInputDialog, QMessageBox, QScrollArea, QVBoxLayout

from .... import alt_blocks, library_data, topic_blocks
from ...background import run_in_background
from ...kit.flow import FlowLayout
from ...kit.tokens import SPACE
from ...kit.widgets import Button, Card, Chip, Surface, caption, clear_layout, text_label
from .slides import load_picture


@dataclass
class PreparedSuggestion:
    suggestion: library_data.Suggestion
    slides: list  # (SlideGroup, QImage), decoded on the scan worker
    existing: str = ""
    reason: str = ""


def prepare_suggestions(ctx, suggestions, groups, resolver, language):
    """Validate block actions and prepare thumbnails on the page's scan worker."""
    rows = {row.id: row for row in groups}
    prepared = []
    for suggestion in suggestions:
        slides = [(rows[i], load_picture(ctx, rows[i], resolver, language)) for i in suggestion.ids[:5] if i in rows]
        item = PreparedSuggestion(suggestion, slides)
        if suggestion.kind == "run":
            try:
                path, _text, _edits = topic_blocks.prepare_run_block(ctx, suggestion.occurrences, suggestion.title)
                item.existing = path.stem if path.exists() else ""
            except ValueError as exc:
                item.reason = str(exc)
        prepared.append(item)
    return prepared


class SuggestionsView(Surface):
    changed = Signal()

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._write = None
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE.lg)
        body.addWidget(text_label("Suggestions", "title"))
        intro = caption("Runs of slides that two decks share become topic blocks. Single slides that two decks "
                        "call can join the pool. Title and section slides are never suggested.")
        intro.setWordWrap(True)
        body.addWidget(intro)
        self.pool_hint = caption("The pool is your collection of reusable slides; add the ones you want to use again.")
        self.pool_hint.setWordWrap(True)
        body.addWidget(self.pool_hint)
        self.status = caption("Finding suggestions…")
        body.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = Surface()
        self.cards = QVBoxLayout(content)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(SPACE.lg)
        self.cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        body.addWidget(scroll, 1)

    def set_suggestions(self, prepared, *, pool_empty):
        clear_layout(self.cards)
        self.pool_hint.setVisible(pool_empty)
        self.status.setText("No suggestions right now." if not prepared else "")
        self.status.setVisible(not prepared)
        for kind, heading in (("run", "Shared runs"), ("single", "Single slides")):
            items = [item for item in prepared if item.suggestion.kind == kind]
            self.cards.addWidget(text_label(f"{heading} · {len(items)}", "heading"))
            for item in items:
                suggestion = item.suggestion
                card = Card()
                card.setProperty("suggestion_kind", kind)
                head = FlowLayout()
                title = text_label(alt_blocks.plain_title(suggestion.title) if kind == "run"
                                   else item.slides[0][0].title, "heading")
                title.setTextFormat(Qt.TextFormat.PlainText)
                head.addWidget(title)
                if kind == "run":
                    head.addWidget(Chip(f"{len(suggestion.ids)} slides"))
                    button = Button(f"Link to block {item.existing}" if item.existing else "Make topic block", "primary")
                    button.setEnabled(not item.reason)
                    button.clicked.connect(lambda _checked=False, item=item: self._make_block(item))
                    head.addWidget(button)
                else:
                    for label, reusable in (("Not reusable", False), ("Add to pool", True)):
                        button = Button(label, "primary" if reusable else "secondary")
                        button.clicked.connect(lambda _checked=False, i=suggestion.ids[0], reusable=reusable:
                                               self._mark(i, reusable))
                        head.addWidget(button)
                card.layout().addLayout(head)
                decks = dict.fromkeys(
                    deck.name + (f" / {calls[0].chapter.title}" if kind == "run" and calls[0].chapter else "")
                    for deck, calls in suggestion.occurrences)
                prefix = (f"{suggestion.ids[0]} {item.slides[0][0].badge} · in {len(decks)} decks: "
                          if kind == "single" else "In ")
                usage = caption(prefix + " · ".join(decks))
                usage.setTextFormat(Qt.TextFormat.PlainText)
                usage.setWordWrap(True)
                card.layout().addWidget(usage)
                previews = FlowLayout()
                for row, image in item.slides:
                    member = Surface()
                    column = QVBoxLayout(member)
                    column.setContentsMargins(0, 0, 0, 0)
                    picture = text_label("No render yet", "secondary")
                    picture.setFixedSize(132, 75)
                    picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    if not image.isNull():
                        picture.setPixmap(QPixmap.fromImage(image).scaled(
                            picture.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    column.addWidget(picture)
                    label = caption(row.title)
                    label.setTextFormat(Qt.TextFormat.PlainText)
                    label.setFixedWidth(132)
                    label.setWordWrap(True)
                    column.addWidget(label)
                    member.setToolTip(f"{row.title}\n{row.id} · {row.badge}")
                    previews.addWidget(member)
                if len(suggestion.ids) > len(item.slides):
                    previews.addWidget(caption(f"and {len(suggestion.ids) - len(item.slides)} more"))
                card.layout().addLayout(previews)
                if item.reason:
                    reason = caption(item.reason, "warning")
                    reason.setWordWrap(True)
                    card.layout().addWidget(reason)
                self.cards.addWidget(card)

    def _mark(self, slide_id, reusable):
        if self._write is not None:
            return
        ctx = self.app.project

        def write():
            data = library_data.read(ctx)
            if reusable:
                data.pool.add(slide_id)
                data.not_reusable.discard(slide_id)
            else:
                data.not_reusable.add(slide_id)
                data.pool.discard(slide_id)
            library_data.write(ctx, data)

        def done(_result, error):
            self._write = None
            if error is not None:
                self.status.setText(f"Could not save library: {error}")
                self.status.show()
            else:
                self.changed.emit()

        self._write = run_in_background(write, done, parent=self)

    def _make_block(self, prepared):
        if self._write is not None:
            return
        suggestion, ctx = prepared.suggestion, self.app.project
        title = suggestion.title
        if not prepared.existing:
            title, accepted = QInputDialog.getText(self, "Make topic block", "Block title:", text=title)
            if not accepted:
                return

        def prepare():
            proposal = topic_blocks.prepare_run_block(ctx, suggestion.occurrences, title)
            return proposal, proposal[0].exists()

        def done(target, error):
            self._write = None
            if error is not None:
                QMessageBox.critical(self, "Make block failed", str(error))
                return
            paths = {deck.path for deck, _calls in suggestion.occurrences}
            # Old one-file snapshots must not undo part of this multi-file conversion.
            slide_list = self.app.slide_list
            for path in paths:
                slide_list._undo.pop(path, None)
            slide_list._undo_order = [(owner, path) for owner, path in slide_list._undo_order if path not in paths]
            self.app.after_deck_edit(next(iter(paths)), f"Linked shared run to block {target.stem}")
            self.changed.emit()

        def approve(result, error):
            self._write = None
            if error is not None:
                QMessageBox.critical(self, "Make block failed", str(error))
                return
            proposal, existing = result
            target, _text, edits = proposal
            files = sorted(edits)
            if not existing:
                files.append(target)
            message = (f"Link this run in every listed deck to block {target.stem}?\n\nWrites:\n"
                       + "\n".join(str(path) for path in files) + "\n\nThis action cannot be undone.")
            if QMessageBox.question(self, "Link to topic block", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
                self._write = run_in_background(
                    lambda: topic_blocks.make_run_block(ctx, suggestion.occurrences, title, proposal), done, parent=self)

        self._write = run_in_background(prepare, approve, parent=self)

    def shutdown(self):
        if self._write is not None:
            self._write.stop(wait_ms=0)
