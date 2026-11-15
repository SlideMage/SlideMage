# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library rail and views, loaded on first opening."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLineEdit,
                               QListWidgetItem, QMessageBox, QStackedWidget, QVBoxLayout)

from .... import deck_editor, library_data, slide_usage, topic_blocks
from ....fileio import read_text_exact
from ....slide_similarity import find_clusters
from ...background import run_in_background
from ...kit.tokens import SPACE
from ...kit.widgets import (Button, Card, Field, IconButton, ModalSheet, PlainList, RowButton,
                            Surface, clear_layout, text_label)
from .blocks import BlockView
from .shared import resolver_of, scroll_column
from .similar import SimilarView, prepare_clusters
from .slides import SlidesView, prepare_groups
from .suggestions import SuggestionsView, prepare_suggestions


class LibraryPage(Surface):
    closed = Signal()

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._scan = None
        self._rescan = False
        self._write = None
        self._choose_initial = True
        self._block_key = ""
        self.blocks = {}
        self.block_rows = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(SPACE.xl)
        self.rail = Card()
        self.rail.setFixedWidth(260)
        rail = self.rail.layout()
        head = QHBoxLayout()
        head.addWidget(text_label("Library", "title"), 1)
        close = IconButton("close", "Close library (Esc)")
        close.clicked.connect(self.closed)
        head.addWidget(close)
        rail.addLayout(head)
        self.rows = {}
        self.topic_rows = {}
        for scope, title in (("pool", "Pool"), ("suggestions", "Suggestions"),
                             ("all", "All slides"), ("unused", "Not in any deck")):
            row = RowButton(None, title, chip=("…", "neutral"), selectable=True)
            row.sub.hide()
            row.clicked.connect(lambda scope=scope: self._show_view(scope))
            rail.addWidget(row)
            self.rows[scope] = row
        rail.addWidget(text_label("Topics", "heading"))
        topics, self.topics = scroll_column(SPACE.xs)
        rail.addWidget(topics, 1)
        rail.addWidget(text_label("Topic blocks", "heading"))
        block_scroll, self.block_list = scroll_column(SPACE.xs)
        rail.addWidget(block_scroll, 1)
        new_block = Button("+ New block", "ghost")
        new_block.clicked.connect(lambda: self._new_block())
        rail.addWidget(new_block)
        rail.addWidget(text_label("Checks", "heading"))
        self.similar_row = RowButton("compare", "Similar slides", chip=("…", "neutral"), selectable=True)
        self.similar_row.sub.hide()
        rail.addWidget(self.similar_row)
        outer.addWidget(self.rail)

        self.views = QStackedWidget()
        self.similar_view = SimilarView(app)
        self.similar_view.changed.connect(self.ensure_loaded)
        self.slides_view = SlidesView(app)
        self.suggestions_view = SuggestionsView(app)
        self.block_view = BlockView(app)
        self.block_view.changed.connect(self._block_changed)
        self.slides_view.block_requested.connect(self.show_block)
        self.slides_view.new_block_requested.connect(self._new_block)
        self.slides_view.add_to_block_requested.connect(self._add_to_block)
        self.suggestions_view.changed.connect(self.ensure_loaded)
        self.slides_view.library_changed.connect(self._update_rail)
        self.slides_view.library_changed.connect(lambda _data: self.ensure_loaded())
        self.slides_view.scope_changed.connect(self._select_row)
        self.status = self.similar_view.status
        self.similar_view.count_changed.connect(lambda count: self.similar_row.chip.set_text(str(count)))
        self.views.addWidget(self.similar_view)
        self.views.addWidget(self.slides_view)
        self.views.addWidget(self.suggestions_view)
        self.views.addWidget(self.block_view)
        self.views.setCurrentWidget(self.suggestions_view)
        self._select_row("suggestions")
        self.similar_row.clicked.connect(lambda: self._show_view("similar"))
        outer.addWidget(self.views, 1)

    def _show_view(self, scope, topic=""):
        self._choose_initial = False
        self._block_key = ""
        self.views.setCurrentWidget({"similar": self.similar_view, "suggestions": self.suggestions_view}.get(
            scope, self.slides_view))
        if scope in ("pool", "all", "unused"):
            self.slides_view.set_scope(scope, topic)
        else:
            self._select_row(scope)

    def _select_row(self, scope, topic=""):
        self._scope, self._topic = scope, topic
        self.similar_row.set_selected(scope == "similar")
        for key, row in self.block_rows.items():
            row.set_selected(scope == "block" and key == self._block_key)
        for key, row in self.rows.items():
            row.set_selected(not topic and key == scope)
        for key, row in self.topic_rows.items():
            row.set_selected(scope != "similar" and key == topic)

    def _update_rail(self, library):
        groups = self.slides_view.model.groups
        for scope in ("pool", "all", "unused"):
            self.rows[scope].chip.set_text(str(sum(self.slides_view.model.in_scope(r, scope) for r in groups)))
        clear_layout(self.topics)
        self.topic_rows.clear()
        counts = {}
        for group in groups:
            for topic in library.topics.get(group.id, set()) | group.block_topics:
                counts[topic] = counts.get(topic, 0) + 1
        for topic, count in sorted(counts.items(), key=lambda item: item[0].casefold()):
            row = RowButton(None, topic, chip=(str(count), "neutral"), selectable=True, elide_title=True)
            row.sub.hide()
            row.clicked.connect(lambda topic=topic: self._show_view("all", topic))
            self.topics.addWidget(row)
            row.show()
            self.topic_rows[topic] = row
        self.topics.addStretch(1)
        clear_layout(self.block_list)
        self.block_rows.clear()
        for key, block in sorted(self.blocks.items(), key=lambda item: item[1].title.casefold()):
            n = len(block.decks)
            row = RowButton("link", block.title, f"used by {n} deck{'s' if n != 1 else ''}",
                            chip=(str(len(block.calls)), "neutral"), selectable=True, elide_title=True)
            row.clicked.connect(lambda key=key: self.show_block(key))
            self.block_list.addWidget(row)
            row.show()
            self.block_rows[key] = row
        self.block_list.addStretch(1)
        self._select_row(self._scope, self._topic)

    def ensure_loaded(self) -> None:
        """Rescan on every opening: workspace state has no project/slide-changed signal."""
        if self._scan is not None:
            self._rescan = True
            return
        ctx = self.app.project
        self._scan_project = ctx
        self.status.setText("Finding similar slides…")
        self.status.show()
        self.slides_view.status.setText("Loading slides…")
        self.slides_view.status.show()
        self.suggestions_view.status.setText("Finding suggestions…")
        self.suggestions_view.status.show()
        language = self.app.state.language

        def scan():
            scanned = slide_usage.deck_calls(ctx)
            usage = slide_usage.decks_by(scanned, "id")
            clusters = find_clusters(ctx, usage=usage)
            resolver = resolver_of(self.app)
            blocks = topic_blocks.read_blocks(ctx, scanned)
            groups = prepare_groups(ctx, usage, blocks, language)
            return (groups, library_data.read(ctx),
                    prepare_clusters(ctx, clusters, usage, blocks, resolver, language),
                    prepare_suggestions(ctx, library_data.suggestions(ctx, scanned), groups, resolver, language),
                    blocks)

        self._scan = run_in_background(scan, self._on_loaded, parent=self)

    def _on_loaded(self, result, error) -> None:
        self._scan = None
        if self._rescan:
            self._rescan = False
            self.ensure_loaded()
            return
        if self._scan_project != self.app.project:
            self.ensure_loaded()
            return
        try:
            if error is not None:
                raise error
            groups, library, clusters, suggestions, self.blocks = result
            self.similar_view.set_clusters(clusters)
            self.slides_view.set_groups(groups, library, [c.cluster for c in clusters])
            pool_empty = not any(self.slides_view.model.in_scope(row, "pool") for row in groups)
            self.suggestions_view.set_suggestions(suggestions, pool_empty=pool_empty)
            self.rows["suggestions"].chip.set_text(str(len(suggestions)))
            self._update_rail(library)
            if self._block_key:
                self.show_block(self._block_key)
            if self._choose_initial:
                self._show_view("suggestions" if pool_empty else "pool")
        except Exception as exc:
            self.status.setText(f"Could not find similar slides: {exc}")
            self.status.show()
            self.slides_view.status.setText(f"Could not load slides: {exc}")
            self.slides_view.status.show()
            self.suggestions_view.status.setText(f"Could not load suggestions: {exc}")
            self.suggestions_view.status.show()

    def _block_changed(self):
        for group in self.slides_view.model.groups:
            group.block_topics = {t for key in group.blocks if key in self.blocks for t in self.blocks[key].topics}
        self.slides_view._rebuild_topics()
        self.slides_view._filter()
        self._update_rail(self.slides_view.model.library)

    def show_block(self, key):
        self._choose_initial = False
        self._block_key = key
        self.views.setCurrentWidget(self.block_view)
        self.block_view.widget().setEnabled(key in self.blocks)
        if key in self.blocks:
            self.block_view.set_block(self.blocks[key], self.slides_view.model.groups)
        else:
            self.block_view.status.setText(f"Loading block {key}…")
        self._select_row("block")

    def _new_block(self, selected=None):
        if self._write is not None:
            return
        sheet = ModalSheet("New topic block", self, width=560)
        body = Surface()
        column = QVBoxLayout(body)
        title = QLineEdit()
        column.addWidget(Field("Block title", title))
        slides = PlainList()
        slides.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for row in self.slides_view.model.groups:
            item = QListWidgetItem(f"{row.title} · {row.id} {row.badge}")
            item.setData(Qt.ItemDataRole.UserRole, row.slug)
            slides.addItem(item)
            item.setSelected(row.slug in (selected or []))
        column.addWidget(Field("Slides, in the order shown", slides))
        sheet.add_tab("", body)
        sheet.add_button("Cancel", role="reject")
        create = sheet.add_button("Create block", kind="primary", role="accept")
        title.textChanged.connect(lambda: create.setEnabled(bool(title.text().strip() and slides.selectedItems())))
        slides.itemSelectionChanged.connect(lambda: create.setEnabled(bool(title.text().strip() and slides.selectedItems())))
        create.setEnabled(False)
        try:
            if not sheet.exec():
                return
            slugs = [slides.item(n).data(Qt.ItemDataRole.UserRole) for n in range(slides.count())
                     if slides.item(n).isSelected()]
            name = title.text()
        finally:
            sheet.deleteLater()
        ctx = self.app.project

        def work():
            target, text = topic_blocks.prepare_calls_block(
                ctx, [deck_editor.format_call("slide", slug) for slug in slugs], name)
            return topic_blocks.commit_block(ctx, target, text)

        def done(target, error):
            self._write = None
            if error is not None:
                QMessageBox.critical(self, "Create block failed", str(error))
                return
            self.show_block(target.stem)
            self.ensure_loaded()

        self._write = run_in_background(work, done, parent=self)

    def _add_to_block(self, slugs):
        if not self.blocks:
            self._new_block(slugs)
            return
        blocks = list(self.blocks.values())
        choices = [f"{b.title} ({b.path.stem})" for b in blocks]
        chosen, accepted = QInputDialog.getItem(self, "Add to block", "Topic block:", choices, editable=False)
        if not accepted:
            return
        block = blocks[choices.index(chosen)]
        try:
            summary = f"Added {len(slugs)} slides to block {block.path.stem} (changes {len(block.decks)} decks)"
            if self.app.state.deck is not None:
                if not self.app.slide_list.edit(
                        "Add to block failed", summary,
                        lambda path, before: deck_editor.insert_slide_calls(path, before, len(before), "", slugs),
                        source=block.path):
                    return
            else:
                text = read_text_exact(block.path)
                deck_editor.insert_slide_calls(block.path, text, len(text), "", slugs)
                self.app.after_deck_edit(block.path, summary)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Add to block failed", str(exc))
            return
        self.show_block(block.path.stem)
        self.ensure_loaded()

    def shutdown(self) -> None:
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
        if self._write is not None:
            self._write.stop(wait_ms=0)
        self.similar_view.shutdown()
        self.block_view.shutdown()
        self.slides_view.shutdown()
        self.suggestions_view.shutdown()
