# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library rail and views, loaded on first opening."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget

from ....slide_similarity import find_clusters
from ...background import run_in_background
from ...kit.tokens import SPACE
from ...kit.widgets import Card, IconButton, RowButton, Surface, caption, text_label


class LibraryPage(Surface):
    closed = Signal()

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._loaded = False
        self._scan = None
        self.clusters = []

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
        self.similar_view = Card()
        self.similar_view.layout().addWidget(text_label("Similar slides", "title"))
        self.status = caption("Finding similar slides…")
        self.similar_view.layout().addWidget(self.status)
        self.similar_view.layout().addStretch(1)
        self.views.addWidget(self.similar_view)
        self.similar_row.clicked.connect(lambda: self.views.setCurrentWidget(self.similar_view))
        outer.addWidget(self.views, 1)

    def ensure_loaded(self) -> None:
        """Scan once, off the GUI thread, when the page is first shown."""
        if not self._loaded:
            self._loaded = True
            self._scan = run_in_background(lambda: find_clusters(self.app.project), self._on_loaded, parent=self)

    def _on_loaded(self, clusters, error) -> None:
        self._scan = None
        if error is not None:
            self._loaded = False
            self.status.setText(f"Could not find similar slides: {error}")
            return
        self.clusters = clusters
        count = sum(cluster.sequence_deck is None for cluster in clusters)
        self.similar_row.chip.set_text(str(count))
        self.status.setText(f"{count} similar slide groups")

    def shutdown(self) -> None:
        if self._scan is not None:
            self._scan.stop(wait_ms=0)
