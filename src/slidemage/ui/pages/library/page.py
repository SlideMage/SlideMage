# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library rail and views, loaded on first opening."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget

from ....slide_similarity import find_clusters, usage_index
from ...background import run_in_background
from ...kit.tokens import SPACE
from ...kit.widgets import Card, IconButton, RowButton, Surface, text_label
from .similar import SimilarView, prepare_clusters


class LibraryPage(Surface):
    closed = Signal()

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._scan = None

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
        rail.addWidget(text_label("Checks", "heading"))
        self.similar_row = RowButton("compare", "Similar slides", chip=("…", "neutral"), selectable=True)
        self.similar_row.sub.hide()
        self.similar_row.set_selected(True)
        rail.addWidget(self.similar_row)
        rail.addStretch(1)
        outer.addWidget(self.rail)

        self.views = QStackedWidget()
        self.similar_view = SimilarView(app)
        self.status = self.similar_view.status
        self.similar_view.count_changed.connect(lambda count: self.similar_row.chip.set_text(str(count)))
        self.views.addWidget(self.similar_view)
        self.similar_row.clicked.connect(lambda: self.views.setCurrentWidget(self.similar_view))
        outer.addWidget(self.views, 1)

    def ensure_loaded(self) -> None:
        """Rescan on every opening: workspace state has no project/slide-changed signal."""
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
        ctx = self.app.project
        self._scan_project = ctx
        self.status.setText("Finding similar slides…")
        self.status.show()
        language = self.app.state.language

        def scan():
            usage = usage_index(ctx)
            clusters = find_clusters(ctx, usage=usage)
            try:
                resolver = self.app.background.renderer.resolver
            except Exception:  # Rendering may be disabled or its store unavailable.
                resolver = None
            return prepare_clusters(ctx, clusters, usage, resolver, language)

        self._scan = run_in_background(scan, self._on_loaded, parent=self)

    def _on_loaded(self, clusters, error) -> None:
        self._scan = None
        if self._scan_project != self.app.project:
            self.ensure_loaded()
            return
        try:
            if error is not None:
                raise error
            self.similar_view.set_clusters(clusters)
        except Exception as exc:
            self.status.setText(f"Could not find similar slides: {exc}")
            self.status.show()

    def shutdown(self) -> None:
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
