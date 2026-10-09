"""The Source view's own "Add reference to .bib…" entry (2026-09-23, direct
instruction; renamed from "Add citation" 2026-09-25, direct instruction,
once the "Cite" popover (insert_popovers.py) gave the word "citation" a
second, different meaning in the same toolbar -- this one
only ever *creates* a new .bib entry, never inserts a citation call for
one) -- a small form for adding a new entry to Slidemaster.bib
without leaving the app or hand-writing BibTeX. Picking a source type
(Article/Book/Online/Report) swaps in that type's own fields below the
three shared ones (author/title/year, present for every type this file
uses -- confirmed by a direct field-frequency survey of the existing 126
entries). Every field carries a tooltip and a placeholder example
explaining what belongs in it, since not everyone filling this in knows
BibTeX field conventions by heart.

The citation key (this file's own "lowercase first author's surname +
year" convention, per its header comment) is suggested live from the
author/year fields and re-suggested as they change, but only until the
user edits the key field directly -- editing it by hand opts out of the
auto-suggestion for the rest of this dialog's life, same as a filename
field would. Either way it's checked against every existing key
(case-insensitively) before the entry can be added, so a duplicate ID
is never silently created.

All the actual parsing/writing/sorting logic lives in bibliography.py
(TYPE_FIELDS, suggest_key, format_entry, add_entry) -- this module is
purely the Qt form around it.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import bibliography
from .ui.kit.theme import MUTED_LABEL

# label shown in the "Type:" combo -> bibliography.TYPE_FIELDS key
_TYPE_LABELS: dict[str, str] = {
    "Article (journal)": "article",
    "Book": "book",
    "Online source": "online",
    "Report / working paper": "report",
}

# Per-field (tooltip, placeholder) help text -- covers every field any of
# the four types uses (bibliography.TYPE_FIELDS' own union).
_FIELD_HELP: dict[str, tuple[str, str]] = {
    "author": (
        "One or more authors as \"Surname, First\" -- separate multiple "
        "authors with \" and \" (used to derive the suggested citation key "
        "below, from the *first* author's surname).",
        "Smith, John and Doe, Jane",
    ),
    "title": ("The work's title, exactly as it should appear in the citation.", "Title of the work"),
    "year": ("4-digit publication year.", "2024"),
    "journaltitle": ("Full journal name -- not abbreviated.", "Journal of Finance"),
    "volume": ("Journal volume number.", "12"),
    "number": ("Issue number within the volume.", "3"),
    "pages": (
        "Page range, using two hyphens for the dash -- rendered as a real "
        "en dash (e.g. \"100--120\"); leave blank for a single page.",
        "100--120",
    ),
    "doi": ("DOI, without the \"https://doi.org/\" prefix.", "10.1016/j.jfineco.2005.10.005"),
    "publisher": ("Publisher name.", "Macmillan"),
    "edition": ("Edition, if not the first (leave blank otherwise).", "2nd ed."),
    "location": ("City of publication.", "London"),
    "isbn": ("ISBN, if known.", "978-0-000-00000-0"),
    "url": ("Full URL of the online source.", "https://..."),
    "organization": ("The organization that published or hosts this source, if any.", "London School of Economics"),
    "note": (
        "Free-form note -- for a web source this is usually an access date.",
        "accessed: 23.09.2026",
    ),
    "institution": (
        "The institution that issued this report, if any (optional -- e.g. "
        "an SSRN working paper has none).",
        "Federal Reserve Bank of Boston",
    ),
    "type": ("Report series/number, if any.", "Working Paper No. 07-3"),
}

_FIELD_LABELS: dict[str, str] = {
    "author": "Author(s)*", "title": "Title*", "year": "Year*",
    "journaltitle": "Journal*", "volume": "Volume", "number": "Issue number",
    "pages": "Pages", "doi": "DOI",
    "publisher": "Publisher*", "edition": "Edition", "location": "Location", "isbn": "ISBN",
    "url": "URL*", "organization": "Organization", "note": "Note",
    "institution": "Institution", "type": "Report type/number",
}


def _make_field(name: str) -> QLineEdit:
    tooltip, placeholder = _FIELD_HELP[name]
    entry = QLineEdit()
    entry.setToolTip(tooltip)
    entry.setPlaceholderText(placeholder)
    return entry


class CitationDialog(QDialog):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self._key_manually_edited = False
        self.new_key: Optional[str] = None

        self.setWindowTitle("Add reference to .bib")
        self.setModal(True)
        self._build()
        self._on_type_change()

    # -- widgets ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Add a new entry to Slidemaster.bib. Fields marked * are required."))

        type_form = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(list(_TYPE_LABELS))
        self.type_combo.currentTextChanged.connect(self._on_type_change)
        type_form.addRow("Type:", self.type_combo)
        layout.addLayout(type_form)

        shared_form = QFormLayout()
        self.author_entry = _make_field("author")
        self.title_entry = _make_field("title")
        self.year_entry = _make_field("year")
        for entry in (self.author_entry, self.title_entry, self.year_entry):
            entry.textChanged.connect(self._update_suggested_key)
        shared_form.addRow(_FIELD_LABELS["author"], self.author_entry)
        shared_form.addRow(_FIELD_LABELS["title"], self.title_entry)
        shared_form.addRow(_FIELD_LABELS["year"], self.year_entry)
        layout.addLayout(shared_form)

        # One QFormLayout page per type, holding only that type's own
        # additional fields (author/title/year above are shared, so never
        # repeated here) -- self._field_entries is keyed by (kind, field
        # name) so _on_submit() below can read back exactly the fields
        # that belong to whichever type is currently selected.
        self._field_entries: dict[tuple[str, str], QLineEdit] = {}
        self.type_stack = QStackedWidget()
        for kind, field_specs in bibliography.TYPE_FIELDS.items():
            page = QWidget()
            page_form = QFormLayout(page)
            for field_name, _required in field_specs:
                if field_name in ("author", "title", "year"):
                    continue
                entry = _make_field(field_name)
                self._field_entries[(kind, field_name)] = entry
                page_form.addRow(_FIELD_LABELS[field_name], entry)
            self.type_stack.addWidget(page)
        layout.addWidget(self.type_stack)

        key_form = QFormLayout()
        self.key_entry = QLineEdit()
        self.key_entry.setToolTip(
            "Citation key used in \\fullcite{}/\\textcite{}/\\cite{} calls -- "
            "suggested automatically from the first author's surname and the "
            "year (this file's own convention), editable if you'd rather pick "
            "your own."
        )
        self.key_entry.textEdited.connect(self._on_key_edited)
        key_form.addRow("Citation key:", self.key_entry)
        layout.addLayout(key_form)

        self.key_status_label = QLabel("")
        self.key_status_label.setObjectName(MUTED_LABEL)
        layout.addWidget(self.key_status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        self.add_button = QPushButton("Add reference to .bib")
        self.add_button.clicked.connect(self._on_submit)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.add_button)
        layout.addLayout(button_row)

    # -- live behavior --------------------------------------------------------------

    def _current_kind(self) -> str:
        return _TYPE_LABELS[self.type_combo.currentText()]

    def _on_type_change(self) -> None:
        kind = self._current_kind()
        index = list(bibliography.TYPE_FIELDS).index(kind)
        self.type_stack.setCurrentIndex(index)

    def _on_key_edited(self, _text: str) -> None:
        self._key_manually_edited = True
        self._update_key_status()

    def _update_suggested_key(self) -> None:
        if self._key_manually_edited:
            return
        suggestion = bibliography.suggest_key(self.author_entry.text(), self.year_entry.text())
        # setText (not textEdited-triggering user input) -- doesn't re-mark
        # _key_manually_edited, so this stays live as author/year change.
        self.key_entry.blockSignals(True)
        self.key_entry.setText(suggestion)
        self.key_entry.blockSignals(False)
        self._update_key_status()

    def _update_key_status(self) -> None:
        key = self.key_entry.text().strip()
        if not key:
            self.key_status_label.setText("")
            return
        if not bibliography.KEY_RE.match(key):
            self.key_status_label.setText(
                "Doesn't match this file's own key convention (lowercase "
                "surname + 4-digit year, e.g. \"smith2024\") -- still usable, "
                "just unconventional."
            )
            return
        existing = bibliography.load()
        if key.lower() in {k.lower() for k in existing}:
            self.key_status_label.setText(f"⚠ \"{key}\" already exists in Slidemaster.bib -- pick another.")
        else:
            self.key_status_label.setText(f"✓ \"{key}\" is available.")

    # -- submit -----------------------------------------------------------------

    def _on_submit(self) -> None:
        kind = self._current_kind()
        key = self.key_entry.text().strip()
        if not key:
            QMessageBox.critical(self, "Add reference", "Enter a citation key.")
            return

        existing = bibliography.load()
        if key.lower() in {k.lower() for k in existing}:
            QMessageBox.critical(
                self, "Add reference",
                f"Citation key \"{key}\" already exists in Slidemaster.bib -- "
                "pick a different key.",
            )
            return

        fields: dict[str, str] = {}
        missing: list[str] = []
        for field_name, required in bibliography.TYPE_FIELDS[kind]:
            if field_name == "author":
                value = self.author_entry.text().strip()
            elif field_name == "title":
                value = self.title_entry.text().strip()
            elif field_name == "year":
                value = self.year_entry.text().strip()
            else:
                value = self._field_entries[(kind, field_name)].text().strip()
            fields[field_name] = value
            if required and not value:
                missing.append(_FIELD_LABELS[field_name].rstrip("*"))

        if missing:
            QMessageBox.critical(
                self, "Add reference",
                "Please fill in: " + ", ".join(missing),
            )
            return

        try:
            bibliography.add_entry(kind, key, fields)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Add reference failed", str(exc))
            return

        self.new_key = key
        self.app.log(f"Added reference \"{key}\" ({kind}) to Slidemaster.bib")
        self.accept()
