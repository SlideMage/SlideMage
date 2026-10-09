"""Full-text slide search dialog (2026-08-26, direct instruction) --
searches every slide's raw .tex source via slide_search.search_slides(),
unlike the toolbar's existing "Find slide:" box (qt_gui.py's own
_build_search_box), which only autocompletes on a slide's own id/slug,
never its body text.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from . import slide_search
from .ui.kit.theme import MUTED_LABEL

# Debounced, not searched on every single keystroke directly -- typing a
# whole word fires several keystrokes in quick succession, and re-scanning
# every slide file on each of them is wasted work a short pause after the
# last one avoids. 665 slide files, once the OS has any of them in its own
# file cache from a prior search this session, scan in ~30ms either way
# (confirmed directly) -- this is about not doing that repeatedly while
# someone is still typing, not about it being slow on its own.
_DEBOUNCE_MS = 200
_MIN_QUERY_LENGTH = 2


class SlideSearchDialog(QDialog):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Search slides")
        self.resize(680, 520)

        layout = QVBoxLayout(self)

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Search every slide's text…")
        layout.addWidget(self.query_edit)

        self.status_label = QLabel("")
        self.status_label.setObjectName(MUTED_LABEL)
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.setWordWrap(True)
        self.results_list.itemActivated.connect(self._on_result_activated)
        layout.addWidget(self.results_list, stretch=1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._run_search)
        self.query_edit.textChanged.connect(lambda _: self._timer.start())

        self.query_edit.setFocus()

    def _run_search(self) -> None:
        query = self.query_edit.text().strip()
        self.results_list.clear()
        if len(query) < _MIN_QUERY_LENGTH:
            self.status_label.setText("")
            return
        results = slide_search.search_slides(query)
        self.status_label.setText(
            "1 match" if len(results) == 1 else f"{len(results)} matches"
        )
        for result in results:
            item = QListWidgetItem(
                f"{result.slide_id} — {result.title}\n{result.snippet}"
            )
            item.setData(Qt.ItemDataRole.UserRole, result.path)
            self.results_list.addItem(item)

    def _on_result_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        self.app.open_slide_editor(path, return_to=self.app.tabs.currentWidget())
        self.accept()
