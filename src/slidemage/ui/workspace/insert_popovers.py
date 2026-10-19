# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The small forms of the Source view's Insert menu and its "Insert citation"
button, as popovers under their button (docs/UI_REDESIGN_PLAN.md, step 5):

* `LinkPopover`: the visible text and the URL of a hyperlink;
* `CodeFilePopover`: a file from the project's snippets/ folder, or a new one,
  and listings options, for \\SMCodeFile;
* `CitationPopover`: a search over Slidemaster.bib and the citation style;
* `InstructionPopover`: what "Rewrite selection · Custom…" should do (not an insert: its `chosen` is the instruction).

Each reports the LaTeX to insert through `chosen(text)`; what the text looks
like and what is valid is in latex_edit.py, snippets.py and bibliography.py.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem

from ... import bibliography, latex_edit, snippets
from ...project import ProjectContext
from ..kit import kit_qss as q
from ..kit.widgets import Button, Popover, SegmentedControl

RESULT_LIMIT = 50
# Citation styles in the order the project uses them (285 \fullcite, 40 \textcite, 6 \parencite
# in its slides); "bib id" is the bare key, for a hand-typed \fullcite{a,b} or an alt-text source.
CITATION_STYLES = (("fullcite", "\\fullcite"), ("textcite", "\\textcite"), ("parencite", "\\parencite"), ("", "bib id"))


def _note() -> QLabel:
    label = QLabel()
    label.setObjectName(q.SOURCE_NOTE)
    label.setWordWrap(True)
    return label


class _FormPopover(Popover):
    """A titled form that ends in Cancel and Insert; `chosen(text)` once `build()` says it is valid."""

    chosen = Signal(str)

    def __init__(self, title: str, *, min_width: int = 340) -> None:
        super().__init__(min_width=min_width)
        self.body.setContentsMargins(12, 10, 12, 12)
        self.body.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName(q.DETAILS_HEAD)
        self.body.addWidget(heading)
        self.note = _note()

    def _add_buttons(self, label: str = "Insert") -> None:
        """Call after the fields: the note, then Cancel and the primary button."""
        self.body.addWidget(self.note)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = Button("Cancel", "ghost", compact=True)
        cancel.clicked.connect(self.close)
        insert = Button(label, "primary", compact=True)
        insert.clicked.connect(self._on_insert)
        row.addWidget(cancel)
        row.addWidget(insert)
        self.body.addLayout(row)

    def _field(self, placeholder: str, text: str = "") -> QLineEdit:
        entry = QLineEdit(text)
        entry.setPlaceholderText(placeholder)
        entry.returnPressed.connect(self._on_insert)
        self.body.addWidget(entry)
        return entry

    def _on_insert(self) -> None:
        try:
            text = self.build()
        except ValueError as exc:
            self.note.setText(str(exc))
            return
        self.chosen.emit(text)
        self.close()

    def build(self) -> str:
        raise NotImplementedError


class LinkPopover(_FormPopover):
    def __init__(self, selected: str = "") -> None:
        super().__init__("Insert hyperlink")
        self.word = self._field("Visible word or phrase", selected)
        self.url = self._field("https://…")
        self._add_buttons()
        self.focus_target = self.url if selected else self.word

    def build(self) -> str:
        return latex_edit.format_hyperlink(self.word.text(), self.url.text())


class InstructionPopover(_FormPopover):
    def __init__(self) -> None:
        super().__init__("Rewrite selection")
        self.entry = self._field("What should change? e.g. more formal, as a question")
        self._add_buttons("Rewrite")
        self.focus_target = self.entry

    def build(self) -> str:
        if not (text := self.entry.text().strip()):
            raise ValueError("Say what the rewrite should do.")
        return text


class CodeFilePopover(_FormPopover):
    """\\SMCodeFile: LaTeX source a slide shows from a file, so the slide needs no [fragile] frame.
    The file lies in snippets/ (a path relative to the project folder); an existing one is
    picked from the list, a new name is created on Insert."""

    def __init__(self, project: ProjectContext, slide_id: str) -> None:
        super().__init__("Insert code file", min_width=380)
        self.project = project
        hint = _note()
        hint.setText("Shows LaTeX source from a file in the project's snippets/ folder, so the slide "
                     "needs no [fragile] frame.")
        self.body.addWidget(hint)
        self.path = QComboBox()
        self.path.setEditable(True)
        self.path.addItems(snippets.list_snippets(project))
        self.path.setEditText(snippets.next_snippet(project, slide_id) if slide_id else "snippets/")
        self.path.lineEdit().returnPressed.connect(self._on_insert)
        self.path.currentTextChanged.connect(self._update_note)
        self.body.addWidget(self.path)
        self.keys = self._field("listings options, optional (e.g. firstline=3)")
        self.create = QCheckBox("Create the file if it doesn't exist")
        self.body.addWidget(self.create)
        self._add_buttons()
        self.focus_target = self.path.lineEdit()
        self._update_note()

    def _update_note(self, _text: str = "") -> None:
        text = self.path.currentText().strip()
        try:
            exists = snippets.resolve(self.project, text).is_file()
        except ValueError:
            exists = False
        self.create.setChecked(not exists)
        self.create.setEnabled(not exists)
        self.note.setText("" if exists else "This file does not exist yet.")

    def build(self) -> str:
        path = self.path.currentText().strip()
        snippets.resolve(self.project, path)       # a ValueError if it lies outside snippets/
        if self.create.isChecked():
            snippets.create(self.project, path)
        return latex_edit.code_file_call(path, self.keys.text())


class CitationPopover(Popover):
    """Search Slidemaster.bib and insert a citation of the entry chosen: Up/Down move, Enter
    inserts, Esc closes. The footer opens "Add reference to .bib…" for a new entry."""

    chosen = Signal(str)
    add_reference_requested = Signal()

    def __init__(self, project: ProjectContext) -> None:
        super().__init__(min_width=460)
        self.body.setContentsMargins(10, 10, 10, 8)
        self.body.setSpacing(8)
        self._entries = bibliography.load(project.bibliography_path)
        top = QHBoxLayout()
        top.addWidget(QLabel("Insert as"))
        self.styles = SegmentedControl([(key or "key", label) for key, label in CITATION_STYLES],
                                       current="fullcite", mono=True)
        top.addWidget(self.styles)
        top.addStretch(1)
        self.body.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by author, title, year, key…")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._insert_current)
        self.search.installEventFilter(self)
        self.body.addWidget(self.search)
        self.results = QListWidget()
        self.results.setMinimumHeight(220)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.itemActivated.connect(lambda _item: self._insert_current())
        self.body.addWidget(self.results)
        footer = QHBoxLayout()
        self.count = _note()
        footer.addWidget(self.count, 1)
        add = Button("Add reference to .bib…", "ghost", compact=True)
        add.clicked.connect(self._add_reference)
        footer.addWidget(add)
        self.body.addLayout(footer)
        self.focus_target = self.search
        self._filter()

    def _filter(self) -> None:
        keys = bibliography.search(self._entries, self.search.text())
        self.results.clear()
        for key in keys[:RESULT_LIMIT]:
            summary = bibliography.format_citation(key, self._entries, "full")
            item = QListWidgetItem(f"{key}  {summary}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.results.addItem(item)
        if keys:
            self.results.setCurrentRow(0)
        shown = min(len(keys), RESULT_LIMIT)
        self.count.setText(f"{len(keys)} match{'es' if len(keys) != 1 else ''}"
                           + (f", the first {shown} shown" if len(keys) > shown else ""))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # The search field keeps the keyboard; the arrows move the list under it.
        if obj is self.search and event.type() == QEvent.Type.KeyPress \
                and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.results.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            if 0 <= row < self.results.count():
                self.results.setCurrentRow(row)
            return True
        return super().eventFilter(obj, event)

    def _insert_current(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        macro = {"key": ""}.get(self.styles.current(), self.styles.current())
        self.chosen.emit(f"\\{macro}{{{key}}}" if macro else key)
        self.close()

    def _add_reference(self) -> None:
        self.close()
        self.add_reference_requested.emit()
