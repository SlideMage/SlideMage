"""The Deck settings sheet (UI_REDESIGN_PLAN.md, step 9): the deck-wide settings that live in the
deck's own file -- template, language, footer text, course link, the PDF shown by "Open pdf", where
the PDFs go, the appendix TOC (deck_settings.py reads and writes them) -- and, as a third tab, the
admin slides generated from the linked course (ui/dialogs/admin_slides.py).

Save closes the sheet with `action == "save"`; `result_settings()` is then the edited, checked
settings (a bad value shows under the form instead). On the Admin slides tab the button is Insert
slides (`action == "insert"`; `admin` has the slides and the position). Both edit the deck file, so
Insert waits until the form has no unsaved changes. The caller writes whichever it was.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QLabel, QLineEdit

from ... import deck_editor, deck_settings, open_path
from ...deck_scan import OPEN_PDF_CHOICES, Deck
from ...deck_settings import DeckSettings
from ..ai_models import add_route_badge
from ..kit.widgets import Button, Field, ModalSheet, Page, Surface, caption, columns, row, set_property
from .admin_slides import AdminSlidesTab

GENERAL, OUTPUT, ADMIN = range(3)
SAVE, INSERT = "save", "insert"
LANGUAGE_LABELS = {"en": "English", "de": "Deutsch"}
OUTPUT_LABELS = {
    None: "All outputs",
    "instructor": "Instructor",
    "presenter": "Presenter",
    "during-course": "During-course",
    "after-course": "After-course",
    "transcript": "Transcript",
}


class DeckSettingsSheet(ModalSheet):
    def __init__(self, parent, deck: Deck, templates: list[tuple[str, str]], *, tab: int = GENERAL) -> None:
        """Edits a copy of the deck's settings. `templates` is [(key, label)] of the templates the
        project can find; the deck's current one is added if it is not there. `tab` is the one to
        open on."""
        super().__init__(f"Deck settings — {deck.name}", parent, width=700)
        add_route_badge(self, parent)
        self.deck = deck
        self.original = deck_settings.read_settings(deck.text)
        self.settings = self.original
        self.action = ""
        self.add_tab("General", self._build_general(templates))
        self.add_tab("PDF output", self._build_output())
        self.admin = AdminSlidesTab(deck)
        self.add_tab("Admin slides", self.admin)

        self.note = caption("")
        self.add_footer_note(self.note)
        self.add_button("Cancel", role="reject")
        self.save_button = self.add_button("Save", kind="primary")
        self.save_button.clicked.connect(self._on_save)
        self.insert_button = self.add_button("Insert slides", kind="primary")
        self.insert_button.clicked.connect(self._on_insert)

        self._initial = self._values()
        for widget in (self.template_combo, self.language_combo, self.open_pdf_combo):
            widget.currentIndexChanged.connect(self._sync_footer)
        for widget in (self.footer_edit, self.url_edit, *self.output_edits.values()):
            widget.textChanged.connect(self._sync_footer)
        self.appendix_check.toggled.connect(self._sync_footer)
        self.admin.changed.connect(self._sync_footer)
        self.tab_changed.connect(self._on_tab)
        self.set_current_tab(tab)
        self._on_tab(tab)

    # -- building --------------------------------------------------------------------------

    def _build_general(self, templates: list[tuple[str, str]]) -> Page:
        page = Page()
        layout = page.body
        layout.addWidget(caption("These settings are written into the deck's own file, so they stay with the deck."))
        settings = self.original

        self.template_combo = QComboBox()
        entries = list(templates)
        if settings.template and settings.template not in {key for key, _ in entries}:
            entries.append((settings.template, f"{settings.template} (not found in this project)"))
        for key, label in entries:
            self.template_combo.addItem(label, key)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(settings.template), 0))
        self.template_combo.setToolTip(
            "The institution template: colors, logo, title bar and footer. "
            "Slidemaster_preamble_<name>.tex, loaded by the deck's \\input line.")
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
        layout.addWidget(columns(Field("Template", self.template_combo), Field("Language", self.language_combo)))

        self.footer_edit = QLineEdit(settings.footer_text)
        self.footer_edit.setPlaceholderText("Shown at the left of the footer, e.g. course | name | term")
        self.footer_edit.setToolTip("The deck's \\FooterText.")
        layout.addWidget(Field("Footer text", self.footer_edit))

        self.url_edit = QLineEdit(settings.course_url)
        self.url_edit.setPlaceholderText("https://online.uni-graz.at/...")
        self.open_button = Button("Open", compact=True)
        self.open_button.setEnabled(bool(settings.course_url.strip()))
        self.url_edit.textChanged.connect(lambda text: self.open_button.setEnabled(bool(text.strip())))
        self.open_button.clicked.connect(self._on_open_link)
        layout.addWidget(Field("Course link", row(self.url_edit, self.open_button)))
        layout.addWidget(caption("The course page the Admin slides tab reads the sessions and lecturers from."))

        self.appendix_check = QCheckBox("Always add the slide-preview appendix (\\deckappendixtoc)")
        self.appendix_check.setChecked(settings.appendix_toc)
        layout.addWidget(self.appendix_check)
        layout.addStretch(1)
        return page

    def _build_output(self) -> Page:
        page = Page()
        layout = page.body
        settings = self.original
        self.open_pdf_combo = QComboBox()
        for key in OPEN_PDF_CHOICES:
            self.open_pdf_combo.addItem(OUTPUT_LABELS[key], key)
        self.open_pdf_combo.setCurrentIndex(max(0, self.open_pdf_combo.findData(settings.open_pdf)))
        layout.addWidget(Field("Open pdf opens", self.open_pdf_combo))
        layout.addWidget(caption(
            "The PDF \"Open latest PDF\" opens -- unless a newer PDF of the deck comes from a later "
            "compile run; then it asks."))

        grid_box = Surface()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        self.output_edits: dict[str | None, QLineEdit] = {}
        for index, key in enumerate(deck_settings.OUTPUT_KEYS):
            edit = QLineEdit(settings.output_folders.get(key, ""))
            edit.setCursorPosition(0)       # long paths show from their start
            edit.setPlaceholderText("(the project's pdf folder)" if key is None else "(as for all outputs)")
            browse = Button("Browse…", compact=True)
            browse.clicked.connect(lambda _checked=False, k=key: self._browse(k))
            grid.addWidget(QLabel(f"{OUTPUT_LABELS[key]}"), index, 0)
            grid.addWidget(edit, index, 1)
            grid.addWidget(browse, index, 2)
            self.output_edits[key] = edit
        layout.addWidget(Field("Where the PDFs go", grid_box))
        layout.addWidget(caption(
            "A folder, or a file name ending in .pdf. An output with no entry of its own goes where "
            "\"All outputs\" says."))
        layout.addStretch(1)
        return page

    # -- the form --------------------------------------------------------------------------

    def _values(self) -> tuple:
        return (self.template_combo.currentData(), self.language_combo.currentData(), self.footer_edit.text(),
                self.url_edit.text(), tuple(edit.text() for edit in self.output_edits.values()),
                self.appendix_check.isChecked(), self.open_pdf_combo.currentData())

    def dirty(self) -> bool:
        return self._values() != self._initial

    def _read(self) -> DeckSettings:
        return deck_settings.from_form(
            self.original,
            template=self.template_combo.currentData() or "",
            language=self.language_combo.currentData() or "en",
            footer_text=self.footer_edit.text(),
            course_url=self.url_edit.text(),
            output_folders={key: edit.text() for key, edit in self.output_edits.items()},
            appendix_toc=self.appendix_check.isChecked(),
            open_pdf=self.open_pdf_combo.currentData() or "instructor")

    def result_settings(self) -> DeckSettings:
        return self.settings

    def _say(self, text: str, tone: str = "") -> None:
        self.note.setText(text)
        set_property(self.note, "tone", tone)

    def _on_tab(self, index: int) -> None:
        if index == ADMIN:
            self.admin.start()
        self._sync_footer()

    def _sync_footer(self) -> None:
        admin, dirty = self.current_tab() == ADMIN, self.dirty()
        self.save_button.setVisible(not admin or dirty)
        self.insert_button.setVisible(admin)
        self.insert_button.setEnabled(bool(self.admin.slide_specs) and not dirty)
        self._say("Save the deck settings first: Insert slides edits the same file." if admin and dirty else "")

    def _browse(self, key: str | None) -> None:
        edit = self.output_edits[key]
        start = edit.text().strip()
        if start.lower().endswith(".pdf"):
            start = str(Path(start).parent)
        chosen = QFileDialog.getExistingDirectory(self, f"Folder for: {OUTPUT_LABELS[key]}", start)
        if chosen:
            edit.setText(chosen.replace("\\", "/"))

    def _on_open_link(self) -> None:
        try:
            open_path.open_in_default_app(deck_editor.normalize_course_url(self.url_edit.text()))
        except (ValueError, OSError) as exc:
            self._say(str(exc), "error")

    def _on_save(self) -> None:
        try:
            self.settings = self._read()
        except ValueError as exc:
            self._say(str(exc), "error")
            return
        self.action = SAVE
        self.accept()

    def _on_insert(self) -> None:
        self.action = INSERT
        self.accept()

    def done(self, result: int) -> None:
        self.admin.cancel()
        super().done(result)
