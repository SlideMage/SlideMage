# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library rail and views, loaded on first opening."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLineEdit,
                               QListWidgetItem, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout)

from .... import deck_editor, library_data, topic_blocks
from ....fileio import read_text_exact, write_text_exact
from ....slide_similarity import find_clusters, usage_index
from ...background import run_in_background
from ...kit.tokens import SPACE
from ...kit.widgets import (Button, Card, Field, IconButton, ModalSheet, PlainList, RowButton,
                            Surface, clear_layout, text_label)
from .blocks import BlockView
from .similar import SimilarView, prepare_clusters
from .slides import SlidesView, prepare_groups
from .suggestions import SuggestionsView, prepare_suggestions


class LibraryPage(Surface):
    closed = Signal()

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._scan = None
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
        topics = QScrollArea()
        topics.setWidgetResizable(True)
        topics.setFrameShape(QScrollArea.Shape.NoFrame)
        content = Surface()
        self.topics = QVBoxLayout(content)
        self.topics.setContentsMargins(0, 0, 0, 0)
        self.topics.setSpacing(SPACE.xs)
        topics.setWidget(content)
        rail.addWidget(topics, 1)
        rail.addWidget(text_label("Topic blocks", "heading"))
        block_scroll = QScrollArea()
        block_scroll.setWidgetResizable(True)
        block_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        block_content = Surface()
        self.block_list = QVBoxLayout(block_content)
        self.block_list.setContentsMargins(0, 0, 0, 0)
        self.block_list.setSpacing(SPACE.xs)
        block_scroll.setWidget(block_content)
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
        self.slides_view = SlidesView(app)
        self.suggestions_view = SuggestionsView(app)
        self.block_view = BlockView(app)
        self.block_view.changed.connect(self._block_changed)
        self.slides_view.block_requested.connect(self.show_block)
        self.slides_view.new_block_requested.connect(self._new_block)
        self.slides_view.add_to_block_requested.connect(self._add_to_block)
        self.suggestions_view.changed.connect(self.ensure_loaded)
        self.slides_view.library_changed.connect(self._update_rail)
        self.slides_view.library_changed.connect(lambda _data: self.ensure_loaded(suggestions_only=True))
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
        self.similar_row.set_selected(scope == "similar")
        for key, row in self.block_rows.items():
            row.set_selected(scope == "block" and key == self._block_key)
        for key, row in self.rows.items():
            row.set_selected(not topic and key == scope)
        for key, row in self.topic_rows.items():
            row.set_selected(scope != "similar" and key == topic)

    def _update_rail(self, library):
        groups = self.slides_view.model.groups
        for scope, count in (("pool", sum(r.id in library.pool or bool(r.blocks) for r in groups)),
                             ("all", len(groups)), ("unused", sum(r.unused for r in groups))):
            self.rows[scope].chip.set_text(str(count))
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
            self.block_rows[key] = row
        self.block_list.addStretch(1)
        scope = ("block" if self.views.currentWidget() is self.block_view else
                 "similar" if self.views.currentWidget() is self.similar_view else
                 "suggestions" if self.views.currentWidget() is self.suggestions_view else self.slides_view._scope)
        self._select_row(scope, self.slides_view._topic if self.views.currentWidget() is self.slides_view else "")

    def ensure_loaded(self, *, suggestions_only=False) -> None:
        """Rescan on every opening: workspace state has no project/slide-changed signal."""
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
        ctx = self.app.project
        self._scan_project = ctx
        if not suggestions_only:
            self.status.setText("Finding similar slides…")
            self.status.show()
            self.slides_view.status.setText("Loading slides…")
            self.slides_view.status.show()
        self.suggestions_view.status.setText("Finding suggestions…")
        self.suggestions_view.status.show()
        language = self.app.state.language
        current_groups = self.slides_view.model.groups

        def scan():
            usage = None if suggestions_only else usage_index(ctx)
            clusters = None if suggestions_only else find_clusters(ctx, usage=usage)
            try:
                resolver = self.app.background.renderer.resolver
            except Exception:  # Rendering may be disabled or its store unavailable.
                resolver = None
            groups = current_groups if suggestions_only else prepare_groups(ctx, usage, language)
            blocks = topic_blocks.read_blocks(ctx)
            for group in groups if not suggestions_only else ():
                group.block_topics = {t for key in group.blocks if key in blocks for t in blocks[key].topics}
            return (groups, library_data.read(ctx),
                    None if suggestions_only else prepare_clusters(ctx, clusters, usage, resolver, language),
                    prepare_suggestions(ctx, library_data.suggestions(ctx), groups, resolver, language),
                    blocks)

        self._scan = run_in_background(scan, self._on_loaded, parent=self)

    def _on_loaded(self, result, error) -> None:
        self._scan = None
        if self._scan_project != self.app.project:
            self.ensure_loaded()
            return
        try:
            if error is not None:
                raise error
            groups, library, clusters, suggestions, self.blocks = result
            if clusters is not None:
                self.similar_view.set_clusters(clusters)
                self.slides_view.set_groups(groups, library, [c.cluster for c in clusters])
            pool_empty = not any(row.id in library.pool or row.blocks for row in groups)
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
        if not sheet.exec():
            return
        slugs = [slides.item(n).data(Qt.ItemDataRole.UserRole) for n in range(slides.count())
                 if slides.item(n).isSelected()]
        try:
            target, text = topic_blocks.prepare_calls_block(
                self.app.project, [deck_editor.format_call("slide", slug) for slug in slugs], title.text())
            if not target.exists():
                write_text_exact(target, text)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Create block failed", str(exc))
            return
        self.show_block(target.stem)
        self.ensure_loaded()

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
        self.block_view.shutdown()
        self.slides_view.shutdown()
        self.suggestions_view.shutdown()
