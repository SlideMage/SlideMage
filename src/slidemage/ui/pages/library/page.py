# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library rail and views, loaded on first opening."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout

from .... import library_data
from ....slide_similarity import find_clusters, usage_index
from ...background import run_in_background
from ...kit.tokens import SPACE
from ...kit.widgets import Card, IconButton, RowButton, Surface, clear_layout, text_label
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
        rail.addWidget(text_label("Checks", "heading"))
        self.similar_row = RowButton("compare", "Similar slides", chip=("…", "neutral"), selectable=True)
        self.similar_row.sub.hide()
        rail.addWidget(self.similar_row)
        outer.addWidget(self.rail)

        self.views = QStackedWidget()
        self.similar_view = SimilarView(app)
        self.slides_view = SlidesView(app)
        self.suggestions_view = SuggestionsView(app)
        self.suggestions_view.changed.connect(self.ensure_loaded)
        self.slides_view.library_changed.connect(self._update_rail)
        self.slides_view.library_changed.connect(lambda _data: self.ensure_loaded(suggestions_only=True))
        self.slides_view.scope_changed.connect(self._select_row)
        self.status = self.similar_view.status
        self.similar_view.count_changed.connect(lambda count: self.similar_row.chip.set_text(str(count)))
        self.views.addWidget(self.similar_view)
        self.views.addWidget(self.slides_view)
        self.views.addWidget(self.suggestions_view)
        self.views.setCurrentWidget(self.suggestions_view)
        self._select_row("suggestions")
        self.similar_row.clicked.connect(lambda: self._show_view("similar"))
        outer.addWidget(self.views, 1)

    def _show_view(self, scope, topic=""):
        self._choose_initial = False
        self.views.setCurrentWidget({"similar": self.similar_view, "suggestions": self.suggestions_view}.get(
            scope, self.slides_view))
        if scope in ("pool", "all", "unused"):
            self.slides_view.set_scope(scope, topic)
        else:
            self._select_row(scope)

    def _select_row(self, scope, topic=""):
        self.similar_row.set_selected(scope == "similar")
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
            for topic in library.topics.get(group.id, set()):
                counts[topic] = counts.get(topic, 0) + 1
        for topic, count in sorted(counts.items(), key=lambda item: item[0].casefold()):
            row = RowButton(None, topic, chip=(str(count), "neutral"), selectable=True, elide_title=True)
            row.sub.hide()
            row.clicked.connect(lambda topic=topic: self._show_view("all", topic))
            self.topics.addWidget(row)
            self.topic_rows[topic] = row
        self.topics.addStretch(1)
        scope = ("similar" if self.views.currentWidget() is self.similar_view else
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
            return (groups, library_data.read(ctx),
                    None if suggestions_only else prepare_clusters(ctx, clusters, usage, resolver, language),
                    prepare_suggestions(ctx, library_data.suggestions(ctx), groups, resolver, language))

        self._scan = run_in_background(scan, self._on_loaded, parent=self)

    def _on_loaded(self, result, error) -> None:
        self._scan = None
        if self._scan_project != self.app.project:
            self.ensure_loaded()
            return
        try:
            if error is not None:
                raise error
            groups, library, clusters, suggestions = result
            if clusters is not None:
                self.similar_view.set_clusters(clusters)
                self.slides_view.set_groups(groups, library, [c.cluster for c in clusters])
            pool_empty = not any(row.id in library.pool or row.blocks for row in groups)
            self.suggestions_view.set_suggestions(suggestions, pool_empty=pool_empty)
            self.rows["suggestions"].chip.set_text(str(len(suggestions)))
            self._update_rail(library)
            if self._choose_initial:
                self._show_view("suggestions" if pool_empty else "pool")
        except Exception as exc:
            self.status.setText(f"Could not find similar slides: {exc}")
            self.status.show()
            self.slides_view.status.setText(f"Could not load slides: {exc}")
            self.slides_view.status.show()
            self.suggestions_view.status.setText(f"Could not load suggestions: {exc}")
            self.suggestions_view.status.show()

    def shutdown(self) -> None:
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
        self.slides_view.shutdown()
        self.suggestions_view.shutdown()
