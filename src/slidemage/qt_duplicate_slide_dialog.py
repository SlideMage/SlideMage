"""qt_slide_source_tab.py's own "Duplicate slide" button (2026-08-25) --
either a same-language copy (a fresh, independent slide seeded from this
one's content, no translation link) or a cross-referenced translation into
another language, with an optional machine-translation pass over the
slide's raw LaTeX body.

Reuses exactly the same slide_ids.create_slide_file(base_on=...,
cross_ref_id_slug=...) + slide_ids.add_translation_backreference() pairing
AddSlideDialog's own "base on existing slide" flow already uses (see that
module) -- this is a shortcut into the same mechanism, scoped to one
specific source slide and callable directly from the slide-source editor
rather than needing a deck's own "+ before"/"+ after" button. Unlike
AddSlideDialog, this never inserts the result into any deck: this tab has
no fixed deck of its own to insert into. The new file is created "loose"
(its own fresh "Included in decks: (none)" header) and the caller
(qt_slide_source_tab.py's _on_duplicate_slide) opens it directly in a new
editor tab for review -- the usual deck-editor "+ before"/"+ after" flow is
how it gets attached to a deck once it's ready.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from . import alt_draft, app_settings, slide_ids, slide_language, slide_rename
from .qt_add_slide_dialog import SLUG_RE
from .qt_theme import MUTED_LABEL

_LANGUAGE_LABELS = {"EN": "EN", "DE": "DE", "mult": "Multilingual"}
_LABEL_TO_LANGUAGE = {v: k for k, v in _LANGUAGE_LABELS.items()}


def _slug_of(id_slug: str) -> str:
    """Slug portion of an id-slug, minus its bare ID and (if present) its
    language segment -- the same split slide_rename.compute_new_id_slug()
    does internally, needed here as its own value rather than folded into
    a freshly-composed id-slug: a duplicate needs a brand-new bare ID
    (minted fresh), not the source's own."""
    parts = id_slug.split("-", 2)
    if len(parts) >= 3 and parts[1] in slide_language.LANGUAGES:
        return parts[2]
    return "-".join(parts[1:])


class DuplicateSlideDialog(QDialog):
    def __init__(self, parent, source_id_slug: str, source_path: Path) -> None:
        super().__init__(parent)
        # `parent` is always the SlideSourceTab that opened this dialog
        # (qt_slide_source_tab.py's _on_duplicate_slide), which already
        # carries this same reference -- needed here for the app-wide
        # Ollama mutex (try_start_ollama_task()/end_ollama_task()) around
        # the auto-translate option below.
        self.app = parent.app
        self.source_id_slug = source_id_slug
        self.source_path = source_path
        self._own_language = slide_language.own_language(source_id_slug)
        # Set on accept(); the caller (qt_slide_source_tab.py's
        # _on_duplicate_slide) reads these back after exec() returns.
        self.new_id_slug: Optional[str] = None
        self.new_path: Optional[Path] = None

        self.setWindowTitle("Duplicate slide")
        self.setModal(True)
        self._build()

    # -- widgets ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        own_label = self._own_language or "untagged"
        layout.addWidget(QLabel(f"Duplicating {self.source_id_slug} (currently {own_label})"))

        mode_row = QHBoxLayout()
        self.same_radio = QRadioButton("Just a duplicate (same language)")
        self.other_radio = QRadioButton("Duplicate in another language")
        self.same_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.same_radio)
        mode_group.addButton(self.other_radio)
        self.same_radio.toggled.connect(self._on_mode_change)
        mode_row.addWidget(self.same_radio)
        mode_row.addWidget(self.other_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        slug_row = QHBoxLayout()
        slug_row.addWidget(QLabel("New slug:"))
        self.slug_entry = QLineEdit(f"{_slug_of(self.source_id_slug)}-Copy")
        slug_row.addWidget(self.slug_entry, stretch=1)
        layout.addLayout(slug_row)

        # Only meaningful in "another language" mode -- "same language"
        # always keeps whatever this slide is currently tagged (or EN, for
        # an untagged legacy source: a brand-new file is never left
        # untagged, same rule AddSlideDialog's own "Create new slide" mode
        # already enforces).
        target_row = QHBoxLayout()
        self.target_label = QLabel("New slide's language:")
        target_row.addWidget(self.target_label)
        self.target_combo = QComboBox()
        self.target_combo.currentTextChanged.connect(self._sync_translate_state)
        target_row.addWidget(self.target_combo)
        target_row.addStretch(1)
        layout.addLayout(target_row)

        self.translate_checkbox = QCheckBox(
            "Auto-translate the slide body during duplication (experimental)")
        self.translate_checkbox.toggled.connect(self._sync_translate_state)
        layout.addWidget(self.translate_checkbox)
        self.translate_warning_label = QLabel(
            "Sends the whole slide body to the translation model as one block -- "
            "LaTeX commands are not guaranteed to survive untouched. Review the "
            "result carefully before saving."
        )
        self.translate_warning_label.setObjectName(MUTED_LABEL)
        self.translate_warning_label.setWordWrap(True)
        layout.addWidget(self.translate_warning_label)

        model_row = QHBoxLayout()
        self.model_label = QLabel("Translation model:")
        model_row.addWidget(self.model_label)
        self.model_combo = QComboBox()
        models = alt_draft.list_all_models()
        self.model_combo.addItems(models or [alt_draft.DEFAULT_TRANSLATION_MODEL])
        # Preselects the translation default from Settings -> "AI models"
        # (hardcoded DEFAULT_TRANSLATION_MODEL when none is set), falling
        # back to that hardcoded default if the configured model isn't
        # installed; a different pick here applies to this dialog only.
        configured = app_settings.default_model("translation")
        preferred = (
            configured if configured in models
            else alt_draft.DEFAULT_TRANSLATION_MODEL
        )
        if preferred in models:
            self.model_combo.setCurrentText(preferred)
        model_row.addWidget(self.model_combo)
        model_row.addStretch(1)
        layout.addLayout(model_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName(MUTED_LABEL)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        # Enter (in the slug field or anywhere else in the dialog) triggers
        # Create, not Cancel (2026-09-26, direct instruction): Qt gives the
        # dialog's default to the first auto-default button, which was
        # Cancel.
        cancel_button.setAutoDefault(False)
        self.create_button = QPushButton("Create")
        self.create_button.clicked.connect(self._on_create)
        self.create_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.create_button)
        layout.addLayout(button_row)

        self._on_mode_change()

    # -- mode handling --------------------------------------------------------------

    def _other_language_options(self) -> list[str]:
        return [code for code in ("EN", "DE", "mult") if code != self._own_language]

    def _on_mode_change(self) -> None:
        # Hidden, not just disabled, in "same language" mode (direct
        # report, 2026-08-30): none of this -- target language, the
        # auto-translate option, the model picker -- means anything once
        # duplicating into the same language, so it's dead clutter rather
        # than a meaningful-but-unavailable choice.
        other_mode = self.other_radio.isChecked()
        self.target_label.setVisible(other_mode)
        self.target_combo.setVisible(other_mode)
        self.translate_checkbox.setVisible(other_mode)
        if other_mode:
            self.target_combo.clear()
            self.target_combo.addItems(
                [_LANGUAGE_LABELS[c] for c in self._other_language_options()])
        self._sync_translate_state()

    def _sync_translate_state(self) -> None:
        # Only EN -> DE is actually configured today (translation_prompts.json
        # has no de->en entries, and even the hardcoded last-resort fallback
        # prompt is itself worded specifically "into German") -- offering
        # the checkbox for any other direction would silently produce a
        # mistranslation rather than an honest "not supported" refusal.
        can_translate = (
            self.other_radio.isChecked()
            and self._own_language == "EN"
            and self.target_combo.currentText() == "DE"
        )
        self.translate_checkbox.setEnabled(can_translate)
        if not can_translate:
            self.translate_checkbox.setChecked(False)
        translating = can_translate and self.translate_checkbox.isChecked()
        self.translate_warning_label.setVisible(translating)
        # Only meaningful once a translation will actually happen -- shown,
        # not just enabled, the same "hide the inapplicable" reasoning as
        # _on_mode_change() above applies here too (2026-08-30).
        self.model_label.setVisible(translating)
        self.model_combo.setVisible(translating)

    # -- submit -----------------------------------------------------------------

    def _on_create(self) -> None:
        slug = self.slug_entry.text().strip()
        if not SLUG_RE.match(slug):
            QMessageBox.critical(
                self, "Duplicate slide",
                "Slug must be non-empty and hyphen-separated alphanumeric "
                "words, e.g. MM-Theorem-Copy.",
            )
            return

        if self.other_radio.isChecked():
            label = self.target_combo.currentText()
            if not label:
                QMessageBox.critical(self, "Duplicate slide", "Pick a target language.")
                return
            language = _LABEL_TO_LANGUAGE[label]
            cross_ref_id_slug: Optional[str] = self.source_id_slug
        else:
            language = self._own_language or "EN"
            cross_ref_id_slug = None

        new_id = slide_ids.mint_slide_id()
        slide_ids.append_slide_id(new_id)
        try:
            dest = slide_ids.create_slide_file(
                new_id, slug, language,
                base_on=self.source_path, cross_ref_id_slug=cross_ref_id_slug,
            )
        except FileExistsError as exc:
            QMessageBox.critical(self, "Duplicate slide", str(exc))
            return
        new_id_slug = f"{new_id}-{language}-{slug}"

        if cross_ref_id_slug is not None:
            slide_ids.add_translation_backreference(self.source_path, language, new_id_slug)
            slide_rename.regenerate_translation_links()

        if self.translate_checkbox.isChecked() and self.translate_checkbox.isEnabled():
            self._translate_new_slide(dest, cross_ref_id_slug)

        self.new_id_slug = new_id_slug
        self.new_path = dest
        self.accept()

    def _translate_new_slide(self, dest: Path, cross_ref_id_slug: Optional[str]) -> None:
        """Translates everything in `dest` *after* its own header block --
        never the header comments themselves, which describe the file
        (deck inclusion, translation cross-reference), not its content."""
        if not self.app.try_start_ollama_task("translating a duplicated slide"):
            # Same graceful fallback as any other translation failure below
            # -- the slide itself was already created (as a same-language,
            # cross-referenced copy) by the time this runs; only the
            # auto-translate step is skipped.
            QMessageBox.warning(
                self, "Translation skipped",
                "The new slide was created with the original (untranslated) "
                "content -- translate it by hand instead, or duplicate again "
                "once the other Ollama-dependent task has finished.",
            )
            return

        self.create_button.setEnabled(False)
        self.status_label.setText("Translating...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            full_text = dest.read_bytes().decode("utf-8")
            header = slide_ids.build_new_slide_header(cross_ref_id_slug)
            body = full_text[len(header):]
            # A higher num_predict than the image-alt-text default (2048)
            # -- a slide's own body can run considerably longer than an
            # image description, and a truncated translation is worse than
            # a slightly slower one.
            backend = alt_draft.OllamaTranslationBackend(
                model=self.model_combo.currentText(), num_predict=4096)
            translated, error = backend.translate_text(body)
        finally:
            QApplication.restoreOverrideCursor()
            self.create_button.setEnabled(True)
            self.status_label.setText("")
            self.app.end_ollama_task()

        if error:
            QMessageBox.warning(
                self, "Translation failed",
                f"{error}\n\nThe new slide was created with the original "
                "(untranslated) content -- translate it by hand instead.",
            )
            return
        dest.write_text(header + translated, encoding="utf-8", newline="")
