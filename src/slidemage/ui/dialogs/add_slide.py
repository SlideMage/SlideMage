"""The Add slide sheet (UI_REDESIGN_PLAN.md, step 9): one place to put a slide into the open deck.

The slide comes from one of four sources:

* New: a blank slide of a frame from the gallery, with a title, a slug and a language.
* Existing: a slide of the project, loaded live, as one of its frozen versions, or as one
  reveal step (\\slidestep).
* Duplicate: a copy of a slide in its own language, independent of the original.
* Translate: a copy in another language, linked to the original; EN to DE can be machine-
  translated first (the model picker and the cloud consent are those of Settings -> AI models).

"Appears in" says in which deck versions the slide shows. The new slide goes in at the position
the caller names (after a slide, at the end of a section, ...). The files and the deck call are
slide_add's and deck_editor's; this sheet asks for the choices, shows what the Add button will do
and reports what went wrong. A new or copied slide opens in the Source view afterwards.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, QThread, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ... import alt_draft, deck_editor, slide_add, slide_import, slide_language, slide_snapshot, slide_versioning
from ...ai.providers import ChatProvider, OllamaProvider
from ...deck_scan import Deck
from ..ai_models import fill_model_combo, provider_from_combo
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Field, ModalSheet, SegmentedControl, Surface, ThumbnailGrid, ToggleChip, caption, set_property
from ..workspace.menus import VIEW_LABELS
from ..workspace.topbar import VIEW_TONES

SOURCES = (("new", "New"), ("existing", "Existing"), ("duplicate", "Duplicate"), ("translate", "Translate"))
LOAD_LABELS = (("live", "Live slide"), ("frozen", "Frozen version"), ("step", "One reveal step"))
LOAD_TIPS = {"live": "Follows every edit of the slide.", "frozen": "Stays as it was when it was frozen.",
             "step": "One reveal step of the slide, as a slide of its own."}
LANGUAGE_LABELS = {"EN": "EN", "DE": "DE", "mult": "Multilingual"}
SLUG_HINT = "The slug is letters and digits with single hyphens between words, e.g. MM-Theorem."
PICKER_LABELS = {"existing": "Slide", "duplicate": "Slide to duplicate", "translate": "Slide to translate"}
TRANSLATION_WARNING = ("Sends the whole slide text to the model as one block. LaTeX commands are not "
                       "guaranteed to survive untouched: review the result before you rely on it.")
WIDTH = 720
THUMB = (56, 32)   # the preview of a slide in the Existing list
MARGINS = 48     # of the sheet


class _TranslateWorker(QThread):
    """One slide_add.translate_body() off the GUI thread, so that Cancel can end it."""

    translated = Signal(object, str, object)     # this worker, the text, the error (None if none)

    def __init__(self, provider: ChatProvider, body: str) -> None:
        super().__init__()
        self.provider = provider
        self.body = body

    def run(self) -> None:
        text, error = slide_add.translate_body(self.provider, self.body)
        self.translated.emit(self, text, error)


class AddSlideSheet(ModalSheet):
    def __init__(self, app, deck: Deck, insert_at: int, indent: str, *, where: str = "", source: str = "new",
                 slide: Optional[str] = None, target: Optional[str] = None) -> None:
        """`app` is the window; the slide goes into `deck` at the offset `insert_at` (indented by
        `indent`), described by `where` ("after 1y8"). `source` is the one to start on, `slide` the
        id-slug Duplicate and Translate start from, `target` the language a translation starts on."""
        super().__init__("Add slide", app, width=WIDTH)
        self.app = app
        self.deck = deck
        self.insert_at = insert_at
        self.indent = indent
        self._context = slide
        self._slug_edited = False
        self._models_filled = False
        self._worker: Optional[_TranslateWorker] = None
        self._provider: Optional[ChatProvider] = None
        self._slides = slide_add.project_slides()
        self._template = slide_snapshot.detect_template(deck.preamble_text)

        body = Surface()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._build_source(where, source)
        self._build_picker()
        self._build_existing()
        self._build_new()
        self._build_copy()
        self._build_views()
        self._build_status()
        self.add_tab("", body)
        self._build_footer()

        self._preset_target = target
        self._on_source(source)

    # -- building --------------------------------------------------------------------------

    def _add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def _build_source(self, where: str, source: str) -> None:
        if where:
            caption = QLabel(where)
            caption.setObjectName(q.PANEL_CAPTION)
            self._add(caption)
        self.source = SegmentedControl(SOURCES, current=source)
        self.source.changed.connect(self._on_source)
        self._add(self.source)

    def _build_picker(self) -> None:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a slide in the project by id or title")
        self.search.textChanged.connect(self._fill_list)
        self.listbox = QListWidget()
        self.listbox.setFixedHeight(204)
        self.listbox.setIconSize(QSize(*THUMB))
        self.listbox.currentItemChanged.connect(lambda *_: self._on_picked())
        layout.addWidget(self.search)
        layout.addWidget(self.listbox)
        self.picker = Field(PICKER_LABELS["existing"], box)
        self._add(self.picker)

    def _build_existing(self) -> None:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.load = SegmentedControl(LOAD_LABELS, current="live")
        self.load.changed.connect(lambda _key: self._sync())
        layout.addWidget(Field("Load as", self.load))
        self.load_note = QLabel()
        self.load_note.setObjectName(q.PANEL_CAPTION)
        layout.addWidget(self.load_note)
        self.version = QComboBox()
        self.version.currentIndexChanged.connect(lambda _i: self._sync())
        self.version_field = Field("Version", self.version)
        layout.addWidget(self.version_field)
        self.steps = QLineEdit(deck_editor.DEFAULT_STEPS)
        self.steps.setToolTip("Reveal steps as a beamer overlay list: 2, or 1-2,4, or 2-")
        self.steps.textChanged.connect(lambda _text: self._sync())
        self.steps_field = Field("Step", self.steps)
        layout.addWidget(self.steps_field)
        self.existing = self._add(box)

    def _build_new(self) -> None:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        names = QHBoxLayout()
        names.setSpacing(12)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Slide title")
        self.title_edit.textEdited.connect(self._on_title)
        self.slug_edit = QLineEdit()
        self.slug_edit.setPlaceholderText("Short-name")
        self.slug_edit.textEdited.connect(self._on_slug_edited)
        self.slug_edit.textChanged.connect(lambda _text: self._sync())
        names.addWidget(Field("Title", self.title_edit), 14)
        names.addWidget(Field("Slug", self.slug_edit), 10)
        layout.addLayout(names)
        self.frames = ThumbnailGrid(
            [(frame, frame, slide_add.frame_thumbnail(frame)) for frame in slide_add.FRAMES],
            current=slide_add.STANDARD_FRAME)
        self.frames.chosen.connect(lambda _key: self._sync())
        layout.addWidget(Field("Frame", self.frames))
        self.frame_note = QLabel()
        self.frame_note.setObjectName(q.PANEL_CAPTION)
        layout.addWidget(self.frame_note)
        self.language = SegmentedControl([(code, label) for code, label in LANGUAGE_LABELS.items()], current="EN")
        self.language.changed.connect(lambda _key: self._sync())
        self.language.setToolTip("Multilingual: the same slide in every language, in one file.")
        layout.addWidget(Field("Language", self.language))
        self.new = self._add(box)

    def _build_copy(self) -> None:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.copy_slug = QLineEdit()
        self.copy_slug.textEdited.connect(self._on_slug_edited)
        self.copy_slug.textChanged.connect(lambda _text: self._sync())
        layout.addWidget(Field("New slug", self.copy_slug))

        self.translation = Surface()
        translation = QVBoxLayout(self.translation)
        translation.setContentsMargins(0, 0, 0, 0)
        translation.setSpacing(12)
        self.target = QComboBox()
        self.target.currentIndexChanged.connect(lambda _i: self._sync())
        translation.addWidget(Field("Translate into", self.target))
        self.machine = QCheckBox("Translate the text with a model")
        self.machine.setEnabled(False)      # until a slide and a language allow it (_sync)
        self.machine.toggled.connect(lambda _on: self._sync())
        translation.addWidget(self.machine)
        self.machine_box = Surface()
        machine = QVBoxLayout(self.machine_box)
        machine.setContentsMargins(0, 0, 0, 0)
        machine.setSpacing(8)
        warning = caption(TRANSLATION_WARNING)
        self._reserve_lines(warning)
        machine.addWidget(warning)
        self.model = QComboBox()
        machine.addWidget(Field("Translation model", self.model))
        translation.addWidget(self.machine_box)
        layout.addWidget(self.translation)
        self.copy = self._add(box)

    def _build_views(self) -> None:
        row = Surface()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.views: dict[str, ToggleChip] = {}
        for view in deck_editor.DEFAULT_CONDITIONS:
            chip = ToggleChip(VIEW_LABELS[view], VIEW_TONES[view])
            chip.setChecked(True)
            chip.toggled.connect(lambda _on: self._sync())
            layout.addWidget(chip)
            self.views[view] = chip
        layout.addStretch(1)
        self.views_field = Field("Appears in", row)
        self._add(self.views_field)

    def _build_status(self) -> None:
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        self._add(self.progress)
        self.status = caption()
        self._add(self.status)

    def _build_footer(self) -> None:
        self.call_preview = QLabel()
        self.call_preview.setObjectName(q.PANEL_MONO)
        self.add_footer_note(self.call_preview)
        self.cancel_button = self.add_button("Cancel", role="reject")
        self.ok = self.add_button("Add slide", kind="primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._on_add)

    # -- what the choices are ---------------------------------------------------------------------

    def current_source(self) -> str:
        return self.source.current() or "new"

    def picked(self) -> Optional[str]:
        """The id-slug chosen in the list."""
        item = self.listbox.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def chosen_views(self) -> list[str]:
        return [view for view, box in self.views.items() if box.isChecked()]

    def chosen_load(self) -> str:
        return (self.load.current() or "live") if self.current_source() == "existing" else "live"

    def chosen_target(self) -> Optional[str]:
        return self.target.currentData()

    def wants_translation(self) -> bool:
        return self.current_source() == "translate" and self.machine.isEnabled() and self.machine.isChecked()

    def slug(self) -> str:
        edit = self.slug_edit if self.current_source() == "new" else self.copy_slug
        return edit.text().strip()

    def problem(self) -> Optional[str]:
        """Why Add cannot go ahead yet, or None."""
        source = self.current_source()
        if source == "new":
            if not self.slug():
                return "Give the slide a title or a slug."
            if not slide_add.SLUG_RE.match(self.slug()):
                return SLUG_HINT
        elif self.picked() is None:
            return "Pick a slide from the list."
        elif source == "existing":
            if self.chosen_load() == "frozen" and self.version.currentData() is None:
                return "This slide has no frozen version."
        else:
            if self.app.centre.is_dirty(slide_add.slide_path(self.picked())):
                return "Save this slide's unsaved changes first: the copy is made from the saved file."
            if not slide_add.SLUG_RE.match(self.slug()):
                return SLUG_HINT
        try:
            self.call_spec()
        except ValueError as exc:
            return str(exc)
        return None

    def call_spec(self) -> slide_add.CallSpec:
        return slide_add.call_spec(self.chosen_load(), self.chosen_views(), self.version.currentData(),
                                   self.steps.text())

    # -- reacting ---------------------------------------------------------------------------------

    def _on_source(self, source: str) -> None:
        self.source.set_current(source)
        self._slug_edited = False
        picks = source != "new"
        self.picker.setVisible(picks)
        self.picker.label.setText(PICKER_LABELS.get(source, ""))
        self.existing.setVisible(source == "existing")
        self.new.setVisible(source == "new")
        self.copy.setVisible(source in ("duplicate", "translate"))
        self.translation.setVisible(source == "translate")
        if picks:
            self._fill_list()
            if source != "existing" and self.picked() is None and self._context:
                self._select(self._context)
        if source == "translate":
            self._fill_models()
        self._on_picked()

    def _fill_list(self) -> None:
        query = self.search.text().strip().lower()
        keep = self.picked()
        self.listbox.clear()
        for slide in self._slides:
            if query and query not in slide.id_slug.lower() and query not in slide.title.lower():
                continue
            item = QListWidgetItem(f"{slide_language.bare_id(slide.id_slug)}   {slide.title}   {slide.badge}".rstrip())
            item.setData(Qt.ItemDataRole.UserRole, slide.id_slug)
            item.setToolTip(slide.id_slug)
            png = slide_snapshot.snapshot_path(self.app.project, slide_language.bare_id(slide.id_slug), self._template,
                                               slide_snapshot.THUMB_SIZE, slide.id_slug)
            if png.is_file():   # the cached preview, loaded by the icon when the row is painted
                item.setIcon(QIcon(str(png)))
            self.listbox.addItem(item)
        if keep:
            self._select(keep)

    def _select(self, id_slug: str) -> None:
        for row in range(self.listbox.count()):
            if self.listbox.item(row).data(Qt.ItemDataRole.UserRole) == id_slug:
                self.listbox.setCurrentRow(row)
                self.listbox.scrollToItem(self.listbox.item(row))
                return

    def _on_picked(self) -> None:
        """The slide in the list changed: what depends on it follows (frozen versions, the
        languages to translate into, the suggested slug)."""
        slide = self.picked()
        self.version.blockSignals(True)
        self.version.clear()
        if slide:
            for version in deck_editor.available_versions(slide):
                self.version.addItem(slide_versioning.version_label(version), version)
        self.version.blockSignals(False)
        self.target.blockSignals(True)
        self.target.clear()
        if slide:
            for code in slide_add.other_languages(slide):
                self.target.addItem(LANGUAGE_LABELS[code], code)
            preset = self.target.findData(self._preset_target)
            if preset >= 0:
                self.target.setCurrentIndex(preset)
        self.target.blockSignals(False)
        if not self._slug_edited and slide:
            suffix = "-Copy" if self.current_source() == "duplicate" else ""
            self.copy_slug.setText(slide_add.slug_of(slide) + suffix)
        self._sync()

    def _on_title(self, title: str) -> None:
        if not self._slug_edited:
            self.slug_edit.setText(slide_import.slug_from_title(title, ""))

    def _on_slug_edited(self, _text: str) -> None:
        self._slug_edited = True

    def _fill_models(self) -> None:
        if not self._models_filled:
            self._models_filled = True
            fill_model_combo(self.app.project, self.model, "translation", OllamaProvider().list_models(),
                             "(no AI models available)", fallback_local=alt_draft.DEFAULT_TRANSLATION_MODEL)

    def _sync(self) -> None:
        """Show what the choices allow, and what Add will do."""
        source = self.current_source()
        load = self.load.current()
        self.load_note.setText(LOAD_TIPS[load])
        self.version_field.setVisible(load == "frozen")
        self.steps_field.setVisible(load == "step")
        frozen = source == "existing" and load == "frozen"
        self.views_field.label.setText("Appears in" if not frozen else "Appears in (a frozen version has no choice)")
        for chip in self.views.values():
            chip.setEnabled(not frozen)
        slide = self.picked()
        can_translate = slide is not None and self.chosen_target() is not None \
            and slide_add.can_machine_translate(slide, self.chosen_target())
        if can_translate != self.machine.isEnabled():
            self.machine.setEnabled(can_translate)
            self.machine.setChecked(can_translate)    # on whenever it is possible, as asked for
        self.machine.setToolTip("" if can_translate else
                                "Only English to German can be translated by a model; the copy is linked all the same.")
        self.machine_box.setVisible(self.wants_translation())
        frame = self.frames.current()
        self.frame_note.setText("Replace the picture in the new slide before you compile it."
                                if frame in slide_add.NEEDS_IMAGE else "")
        self.frame_note.setVisible(bool(self.frame_note.text()))
        problem = self.problem()
        self._set_status(problem or "", error=False)
        self.ok.setEnabled(problem is None and self._worker is None)
        self.call_preview.setText(self._call_text() if problem is None else "")

    def _call_text(self) -> str:
        spec = self.call_spec()
        shown = self.picked() if self.current_source() == "existing" else "the new slide"
        return deck_editor.format_call(spec.macro, shown, spec.version, spec.conditions, spec.steps)

    def _set_status(self, text: str, *, error: bool) -> None:
        self.status.setText(text)
        set_property(self.status, "tone", "error" if error else "")
        self._reserve_lines(self.status)

    @staticmethod
    def _reserve_lines(label: QLabel) -> None:
        """Room for all the lines of a wrapped label: the sheet's pages sit in a stacked widget,
        which does not pass the height a label needs for its width on to the layout."""
        label.setMinimumHeight(label.heightForWidth(WIDTH - MARGINS) if label.text() else 0)

    # -- adding -----------------------------------------------------------------------------------

    def _on_add(self) -> None:
        if self.problem() is not None or self._worker is not None:
            return
        source = self.current_source()
        try:
            if source == "existing":
                self._finish(self.picked(), None)
            elif source == "new":
                created = slide_add.create_new(self.slug(), self.language.current() or "EN",
                                               self.frames.current() or slide_add.STANDARD_FRAME,
                                               self.title_edit.text())
                self._finish(created.id_slug, created.path)
            elif source == "duplicate":
                created = slide_add.create_copy(self.picked(), self.slug())
                self._finish(created.id_slug, created.path)
            elif self.wants_translation():
                self._start_translation()
            else:
                created = slide_add.create_copy(self.picked(), self.slug(), self.chosen_target())
                self._finish(created.id_slug, created.path)
        except (OSError, ValueError) as exc:     # FileExistsError is an OSError
            self._set_status(str(exc), error=True)

    def _finish(self, id_slug: str, new_path) -> None:
        """Put the slide's call into the deck; a new file opens in the Source view."""
        spec = self.call_spec()
        previous_text = self.deck.text
        try:
            deck_editor.insert_slide_call(
                self.deck.path, self.deck.text, self.insert_at, self.indent,
                spec.macro, id_slug, spec.version, spec.conditions, spec.steps)
        except (deck_editor.StaleFileError, ValueError) as exc:
            note = "" if new_path is None else f" The new slide file {new_path.name} was created; it is not in the deck."
            QMessageBox.critical(self, "Add slide failed", f"{exc}{note}")
            return
        self.accept()
        self.app.after_deck_edit(
            self.deck.path, f"Added \\{spec.macro}{{{id_slug}}} to {self.deck.name}", previous_text=previous_text)
        if new_path is not None:
            self.app.open_slide_editor(new_path)

    # -- translating ------------------------------------------------------------------------------

    def _start_translation(self) -> None:
        provider = provider_from_combo(self, self.model, "the slide's LaTeX body")
        if provider is None or not self.app.try_start_ollama_task("translating a slide", provider):
            return
        self._provider = provider
        self._worker = _TranslateWorker(provider, slide_add.source_body(self.picked()))
        self._worker.translated.connect(self._on_translated)
        self._busy(f"Translating with {provider.label}…")
        self._worker.start()

    def _busy(self, text: str) -> None:
        running = self._worker is not None
        self.progress.setVisible(running)
        self.picker.setEnabled(not running)
        self.copy.setEnabled(not running)
        self.views_field.setEnabled(not running)
        self.source.setEnabled(not running)
        self.ok.setEnabled(not running)
        if running:
            self._set_status(text, error=False)

    def _on_translated(self, worker: _TranslateWorker, text: str, error: Optional[str]) -> None:
        if worker is not self._worker:      # the sheet was closed meanwhile: nobody waits for this
            return
        self._worker = None
        worker.wait()
        worker.deleteLater()
        self.app.end_ollama_task(self._provider)
        self._busy("")
        if error:
            self._sync()
            self._set_status(f"Translation failed: {error} Untick the model translation to make the copy as it is.",
                             error=True)
            return
        try:
            created = slide_add.create_copy(self.picked(), self.slug(), self.chosen_target(), body=text)
        except (OSError, ValueError) as exc:
            self._sync()
            self._set_status(str(exc), error=True)
            return
        self._finish(created.id_slug, created.path)

    def event(self, event: QEvent) -> bool:
        """The sources differ in height: once the layout has settled after a change, the sheet takes the
        height of what it shows now (it also shrinks)."""
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            self.adjustSize()
        return handled

    def done(self, result: int) -> None:
        """Closing the sheet ends a running translation: its thread must not outlive the sheet."""
        worker, self._worker = self._worker, None
        if worker is not None:
            provider = self._provider
            background.stop_worker(worker, worker.provider.abort, on_done=lambda: self.app.end_ollama_task(provider))
        super().done(result)
