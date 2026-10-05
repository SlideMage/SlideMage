"""The "Settings" dialog of a deck row: the deck-wide settings that live in the
deck's own file -- template, language, footer text, course link, where its PDFs
go, and the appendix TOC (deck_settings.py reads and writes them). It replaces
the former "Course link..." button and dialog.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import deck_editor, deck_settings
from .deck_settings import DeckSettings
from .qt_theme import MUTED_LABEL

LANGUAGE_LABELS = {"en": "English", "de": "Deutsch"}
OUTPUT_LABELS = {
    None: "All outputs",
    "instructor": "Instructor",
    "presenter": "Presenter",
    "during-course": "During-course",
    "after-course": "After-course",
    "transcript": "Transcript",
}


class DeckSettingsDialog(QDialog):
    """Edits a copy of `settings`; `result_settings()` is the edited one after
    exec() returned Accepted. `templates` is [(key, label)] of the templates
    the project can find; the deck's current one is added if it is not there."""

    def __init__(
        self,
        parent: QWidget | None,
        deck_name: str,
        settings: DeckSettings,
        templates: list[tuple[str, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Deck settings — {deck_name}")
        self._original = settings
        self.result_value = settings
        self.open_link_requested = False

        self.setMinimumWidth(760)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "These settings are written into the deck's own file, so they stay with the deck.")
        intro.setWordWrap(True)
        intro.setObjectName(MUTED_LABEL)
        layout.addWidget(intro)

        form = QFormLayout()
        layout.addLayout(form)

        self.template_combo = QComboBox()
        entries = list(templates)
        if settings.template and settings.template not in {key for key, _ in entries}:
            entries.append((settings.template, f"{settings.template} (not found in this project)"))
        for key, label in entries:
            self.template_combo.addItem(label, key)
        index = self.template_combo.findData(settings.template)
        self.template_combo.setCurrentIndex(max(index, 0))
        self.template_combo.setToolTip(
            "The institution template: colors, logo, title bar and footer. "
            "Slidemaster_preamble_<name>.tex, loaded by the deck's \\input line.")
        form.addRow("Template:", self.template_combo)

        self.language_combo = QComboBox()
        codes = list(LANGUAGE_LABELS)
        if settings.language not in codes:
            codes.append(settings.language)
        for code in codes:
            self.language_combo.addItem(LANGUAGE_LABELS.get(code, code), code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(settings.language))
        self.language_combo.setToolTip(
            "The deck's language (\\decklanguage): hyphenation, automatic texts, "
            "the language of its transcript and of \\multilingualtext.")
        form.addRow("Language:", self.language_combo)

        self.footer_edit = QLineEdit(settings.footer_text)
        self.footer_edit.setPlaceholderText("Shown at the left of the footer, e.g. course | name | term")
        self.footer_edit.setToolTip("The deck's \\FooterText.")
        form.addRow("Footer text:", self.footer_edit)

        link_row = QHBoxLayout()
        self.url_edit = QLineEdit(settings.course_url)
        self.url_edit.setPlaceholderText("https://online.uni-graz.at/...")
        self.url_edit.setMinimumWidth(420)
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(bool(settings.course_url.strip()))
        self.url_edit.textChanged.connect(
            lambda text: self.open_button.setEnabled(bool(text.strip())))
        self.open_button.clicked.connect(self._on_open_link)
        link_row.addWidget(self.url_edit, 1)
        link_row.addWidget(self.open_button)
        form.addRow("Course link:", link_row)

        outputs = QGroupBox("Where the PDFs go")
        out_form = QFormLayout(outputs)
        self.output_edits: dict[str | None, QLineEdit] = {}
        for key in deck_settings.OUTPUT_KEYS:
            edit = QLineEdit(settings.output_folders.get(key, ""))
            edit.setCursorPosition(0)  # long paths show from their start
            edit.setPlaceholderText(
                "(the project's pdf folder)" if key is None else "(as for all outputs)")
            browse = QPushButton("Browse…")
            browse.clicked.connect(lambda _checked=False, k=key: self._browse(k))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(browse)
            out_form.addRow(f"{OUTPUT_LABELS[key]}:", row)
            self.output_edits[key] = edit
        note = QLabel(
            "A folder, or a file name ending in .pdf. An output with no entry of its own "
            "goes where \"All outputs\" says.")
        note.setWordWrap(True)
        note.setObjectName(MUTED_LABEL)
        out_form.addRow(note)
        layout.addWidget(outputs)

        self.appendix_check = QCheckBox("Always add the slide-preview appendix (\\deckappendixtoc)")
        self.appendix_check.setChecked(settings.appendix_toc)
        layout.addWidget(self.appendix_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, key: str | None) -> None:
        edit = self.output_edits[key]
        start = edit.text().strip()
        if start.lower().endswith(".pdf"):
            start = str(Path(start).parent)
        chosen = QFileDialog.getExistingDirectory(
            self, f"Folder for: {OUTPUT_LABELS[key]}", start)
        if chosen:
            edit.setText(chosen.replace("\\", "/"))

    def _on_open_link(self) -> None:
        self.open_link_requested = True
        self._on_accept()

    def _on_accept(self) -> None:
        try:
            self.result_value = self._read_fields()
        except ValueError as exc:
            self.open_link_requested = False
            QMessageBox.warning(self, "Deck settings", str(exc))
            return
        self.accept()

    def _read_fields(self) -> DeckSettings:
        url = self.url_edit.text().strip()
        if url:
            url = deck_editor.normalize_course_url(url)
        folders = {}
        for key, edit in self.output_edits.items():
            typed = edit.text().strip()
            # an entry left as it was stays byte for byte, whatever its slashes
            path = (typed if typed == self._original.output_folders.get(key, "")
                    else deck_settings._clean_path(typed))
            if path:
                folders[key] = path
        return DeckSettings(
            template=self.template_combo.currentData() or "",
            language=self.language_combo.currentData() or "en",
            footer_text=self.footer_edit.text(),
            course_url=url,
            output_folders=folders,
            appendix_toc=self.appendix_check.isChecked(),
        )

    def result_settings(self) -> DeckSettings:
        return self.result_value
