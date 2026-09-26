"""qt_slide_source_tab.py's own "Insert citation" button (2026-09-25,
direct instruction) -- search Slidemaster.bib for an existing entry and
insert a citation call for it at the editor's own cursor, without leaving
the app or remembering the exact key by heart. Companion to
qt_citation_dialog.py's "Add reference" (renamed from "Add citation" the
same day, to read as adding a *reference* rather than inserting one):
that one only ever *creates* a new .bib entry; this one only ever
*inserts* a call for an *existing* one -- neither touches the other's job.

Two steps, both in the same dialog: type to filter the whole bib (key,
authors, title, year, container all searched at once, live, no debounce
needed -- filtering a few hundred already-parsed BibEntry objects in
memory is instant, nothing like the full slide-text search's own file
scan), then pick one entry and click whichever citation style button
matches what the slide needs. All three styles this project's slides
actually use (grep across slides/*.tex, 2026-09-25: 285 \\fullcite, 40
\\textcite, 6 \\parencite, zero bare \\cite) get their own button rather
than a style dropdown, per direct instruction ("different buttons for
the different citation options") -- picking a style is then one click
instead of two.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from . import bibliography
from .qt_theme import MUTED_LABEL

# (button label, literal LaTeX macro name) -- in the same left-to-right
# order as this module's own docstring frequency survey, most-used first.
_STYLE_BUTTONS: list[tuple[str, Optional[str]]] = [
    ("\\fullcite{}", "fullcite"),
    ("\\textcite{}", "textcite"),
    ("\\parencite{}", "parencite"),
    # 2026-09-27, direct instruction: just the bare key, no citation macro
    # around it (for a hand-typed \fullcite{a,b}, an alt-text source, ...).
    ("bib id", None),
]


class InsertCitationDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.app = parent.app
        self.editor = parent  # the SlideSourceTab -- for _replace_selection_or_insert
        self._entries = bibliography.load()
        self._selected_key: str | None = None

        self.setWindowTitle("Insert citation")
        self.resize(620, 480)
        self._build()
        self._run_filter()

    # -- widgets ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Search Slidemaster.bib, pick an entry, then pick a citation style "
            "to insert at the cursor."
        ))

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search by author, title, year, key…")
        self.search_entry.textChanged.connect(self._run_filter)
        layout.addWidget(self.search_entry)

        self.results_list = QListWidget()
        self.results_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.results_list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.results_list, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName(MUTED_LABEL)
        layout.addWidget(self.status_label)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Insert as:"))
        self.style_buttons: list[QPushButton] = []
        for label, macro in _STYLE_BUTTONS:
            button = QPushButton(label)
            button.setEnabled(False)
            button.setToolTip(
                f"Insert \\{macro}{{key}} for the selected entry." if macro
                else "Insert only the bib id (the key), without any citation macro.")
            button.clicked.connect(lambda checked=False, m=macro: self._on_insert(m))  # m None = bare key
            style_row.addWidget(button)
            self.style_buttons.append(button)
        style_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        style_row.addWidget(cancel_button)
        layout.addLayout(style_row)

        self.search_entry.setFocus()

    # -- filtering --------------------------------------------------------------

    def _searchable_text(self, key: str, entry: bibliography.BibEntry) -> str:
        return " ".join((
            key,
            entry.fields.get("author", ""),
            entry.title,
            entry.year,
            entry.container,
        )).lower()

    def _run_filter(self) -> None:
        query = self.search_entry.text().strip().lower()
        self.results_list.clear()
        keys = sorted(self._entries)
        if query:
            keys = [k for k in keys if query in self._searchable_text(k, self._entries[k])]
        for key in keys:
            entry = self._entries[key]
            summary = bibliography.format_citation(key, self._entries, "full")
            item = QListWidgetItem(f"{key} — {summary}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.results_list.addItem(item)
        self.status_label.setText(
            "1 match" if len(keys) == 1 else f"{len(keys)} matches"
        )
        self._on_selection_changed()

    # -- selection / insert -------------------------------------------------------

    def _on_selection_changed(self) -> None:
        items = self.results_list.selectedItems()
        self._selected_key = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        for button in self.style_buttons:
            button.setEnabled(self._selected_key is not None)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        # Double-click / Enter on a result with no style chosen yet --
        # \fullcite (the dominant style, per this module's own docstring
        # survey) is the reasonable one-click default.
        self._selected_key = item.data(Qt.ItemDataRole.UserRole)
        self._on_insert("fullcite")

    def _on_insert(self, macro: Optional[str]) -> None:
        if self._selected_key is None:
            return
        text = f"\\{macro}{{{self._selected_key}}}" if macro else self._selected_key
        self.editor._replace_selection_or_insert(text)
        self.accept()
