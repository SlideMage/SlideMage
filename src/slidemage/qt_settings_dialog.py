"""Settings dialog (2026-08-25, direct instruction): a "Settings" menu
holding cross-cutting app preferences that don't belong scattered across
individual toolbars -- dark mode (moved here from its own toolbar
checkbox in qt_gui.py), per-(model, source language, target language)
translation prompt configuration (translation_prompts.py), used by
alt_draft.OllamaTranslationBackend for both the Images tab's per-image
"Translate now" button and its "Translate all…" batch, and (2026-08-25)
an "Ollama models" tab to delete models this app no longer needs --
genuinely from Ollama's own local model store (alt_draft.delete_model(),
its own DELETE /api/delete), not just some SlideMage-side list.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import ai_draft
from . import alt_draft
from . import app_settings
from . import draft_prompts
from . import translation_prompts as tp
from .qt_slide_source_tab import DEFAULT_TAB_WIDTH_CHARS, TAB_WIDTH_SETTING_KEY


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # unreachable, satisfies type checkers


class SettingsDialog(QDialog):
    # Carries a list[tuple[model, ok, error]] back to the GUI thread once a
    # background "Update selected…" (2026-09-18) finishes -- see
    # _on_ollama_model_update()/_update_ollama_models_bg()/
    # _on_ollama_update_finished(). Same per-instance Signal(object)
    # cross-thread pattern qt_transcript_tab.py's _ImageEditor.translation_done
    # already uses for its own backgrounded Ollama call.
    _ollama_update_done = Signal(object)

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Settings")
        self.resize(680, 520)

        # Snapshots of the two prompt forms' last-loaded-or-saved state,
        # for the unsaved-changes check in reject() below -- set for real
        # by _load_default_prompt()/_on_prompt_selected()/_on_prompt_new()
        # once the tabs are built just below; these placeholders only
        # exist so a dirty-check somehow running before then (shouldn't
        # happen) fails safe (nothing to compare -> not dirty) rather than
        # raising AttributeError.
        self._default_prompt_snapshot: tuple[str, int] | None = None
        self._prompt_form_snapshot: tuple[str, str, str, str, int] | None = None
        # Same snapshot-then-compare dirty tracking as the translation
        # tab's own default-prompt field above, for the two draft_prompts.py
        # fields on the "AI prompts" tab below.
        self._draft_prompt_snapshot: str | None = None
        self._rewrite_prompt_snapshot: str | None = None

        self._ollama_update_done.connect(self._on_ollama_update_finished)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, stretch=1)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_translation_tab(), "Translation prompts")
        tabs.addTab(self._build_ai_prompts_tab(), "AI prompts")
        tabs.addTab(self._build_ollama_models_tab(), "Ollama models")

        # Close only -- every change here (dark mode, a saved/deleted
        # prompt) is applied and persisted immediately by its own control,
        # same as every other dialog in this app that edits durable state
        # (e.g. qt_transcript_tab.py's review panel) -- there is nothing
        # to "commit" on an OK button, and nothing a Cancel could sensibly
        # undo. The two prompt text forms are the one exception -- typing
        # into either doesn't save on its own, so text sitting there
        # unsaved when the dialog closes would silently vanish (2026-08-26,
        # direct instruction). Routed through self.reject (overridden
        # below) rather than self.accept, since reject() is also what
        # QDialog's own Escape-key handling and the window's X button both
        # already funnel through -- one check point covers all three.
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _dirty_prompt_descriptions(self) -> list[str]:
        descriptions = []
        if self._default_prompt_dirty():
            descriptions.append("the default prompt")
        if self._prompt_form_dirty():
            descriptions.append("the per-model prompt shown on the right")
        if self._draft_prompt_dirty():
            descriptions.append("the image description prompt")
        if self._rewrite_prompt_dirty():
            descriptions.append("the slide rewrite prompt")
        return descriptions

    def reject(self) -> None:
        # The one check point every close path funnels through -- the
        # window's X button (QDialog's own default closeEvent() calls
        # reject()) and the Escape key (QDialog's keyPressEvent calls
        # reject() directly) both already went through this before this
        # override existed; the Close button now does too (wired above).
        dirty = self._dirty_prompt_descriptions()
        if dirty:
            box = QMessageBox(self)
            box.setWindowTitle("Unsaved changes")
            box.setText(
                "You have unsaved changes to " + " and ".join(dirty) + ". "
                "Save before closing?"
            )
            save_button = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
            discard_button = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(save_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is save_button:
                ok = True
                if self._default_prompt_dirty():
                    ok = self._on_default_prompt_save() and ok
                if self._prompt_form_dirty():
                    ok = self._on_prompt_save() and ok
                if self._draft_prompt_dirty():
                    ok = self._on_draft_prompt_save() and ok
                if self._rewrite_prompt_dirty():
                    ok = self._on_rewrite_prompt_save() and ok
                if not ok:
                    # A save failed validation (e.g. an empty prompt) --
                    # its own critical QMessageBox already explained why;
                    # stay open rather than closing with something still
                    # genuinely unsaved.
                    return
            elif clicked is not discard_button:
                return  # Cancel -- stay open, nothing saved or discarded
        super().reject()

    # -- General ----------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.dark_mode_checkbox = QCheckBox("Dark mode")
        self.dark_mode_checkbox.setChecked(self.app.theme.dark)
        self.dark_mode_checkbox.toggled.connect(self.app.set_dark_mode)
        layout.addWidget(self.dark_mode_checkbox)

        # Slide-source editor's own Tab-key width (2026-08-29, direct
        # instruction -- was hardcoded, see qt_slide_source_tab.py's own
        # DEFAULT_TAB_WIDTH_CHARS comment for why 80px-default-tab-stop was
        # worth changing at all). Applied immediately (like dark mode
        # above), not deferred to this dialog's Close button -- there's
        # nothing to "commit", same reasoning as every other control here.
        tab_width_row = QHBoxLayout()
        tab_width_row.addWidget(QLabel("Slide editor tab width (characters):"))
        self.tab_width_spin = QSpinBox()
        self.tab_width_spin.setRange(1, 16)
        self.tab_width_spin.setValue(
            app_settings.get(TAB_WIDTH_SETTING_KEY, DEFAULT_TAB_WIDTH_CHARS)
        )
        self.tab_width_spin.valueChanged.connect(self.app.set_tab_width_chars)
        tab_width_row.addWidget(self.tab_width_spin)
        tab_width_row.addStretch(1)
        layout.addLayout(tab_width_row)

        layout.addStretch(1)
        return page

    # -- Translation prompts ------------------------------------------------

    def _build_translation_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        # -- default prompt (2026-08-25, direct instruction) -- used
        # whenever no per-model override below matches; the per-model
        # list further down always takes priority over this when both
        # could apply.
        default_group = QGroupBox("Default prompt")
        default_layout = QVBoxLayout(default_group)
        default_layout.addWidget(QLabel(
            "Used for any model/language pair with no override below. "
            "Same single-message format: this text, then the blank "
            "line(s), then the text to translate."
        ))
        self.default_prompt_edit = QPlainTextEdit()
        self.default_prompt_edit.setMinimumHeight(90)
        default_layout.addWidget(self.default_prompt_edit)
        default_blank_row = QHBoxLayout()
        default_blank_row.addWidget(QLabel("Blank lines before the text:"))
        self.default_blank_lines_spin = QSpinBox()
        self.default_blank_lines_spin.setRange(0, 10)
        self.default_blank_lines_spin.setValue(1)
        default_blank_row.addWidget(self.default_blank_lines_spin)
        default_blank_row.addStretch(1)
        default_save_button = QPushButton("Save default")
        default_save_button.clicked.connect(self._on_default_prompt_save)
        default_blank_row.addWidget(default_save_button)
        default_layout.addLayout(default_blank_row)
        outer.addWidget(default_group)
        self._load_default_prompt()

        outer.addWidget(QLabel(
            "Per-model, per-language-pair overrides. When the model + "
            "From + To below match exactly, this prompt is used instead "
            "of the default above -- for both the Images tab's per-image "
            "\"Translate now\" button and \"Translate all…\"."
        ))

        body = QHBoxLayout()
        outer.addLayout(body, stretch=1)

        self.prompt_list = QListWidget()
        self.prompt_list.setMaximumWidth(240)
        self.prompt_list.currentRowChanged.connect(self._on_prompt_selected)
        body.addWidget(self.prompt_list)

        form = QVBoxLayout()
        body.addLayout(form, stretch=1)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.prompt_model_combo = QComboBox()
        self.prompt_model_combo.setEditable(True)
        self.prompt_model_combo.addItems(alt_draft.list_all_models())
        model_row.addWidget(self.prompt_model_combo, stretch=1)
        form.addLayout(model_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("From:"))
        self.prompt_source_combo = QComboBox()
        self.prompt_source_combo.setEditable(True)
        self.prompt_source_combo.addItems(["en", "de"])
        # An editable QComboBox otherwise sizes itself to its *current
        # text* (2 characters here), not to comfortably hold one -- read
        # as a near-invisible sliver next to its own dropdown arrow.
        self.prompt_source_combo.setMinimumWidth(70)
        lang_row.addWidget(self.prompt_source_combo)
        lang_row.addWidget(QLabel("To:"))
        self.prompt_target_combo = QComboBox()
        self.prompt_target_combo.setEditable(True)
        self.prompt_target_combo.addItems(["de", "en"])
        self.prompt_target_combo.setMinimumWidth(70)
        lang_row.addWidget(self.prompt_target_combo)
        lang_row.addStretch(1)
        form.addLayout(lang_row)

        form.addWidget(QLabel(
            "Prompt -- sent as a single message: this text, then the "
            "blank line(s) below, then the text to translate verbatim "
            "(no separate system-role turn):"
        ))
        self.prompt_text_edit = QPlainTextEdit()
        self.prompt_text_edit.setMinimumHeight(180)
        form.addWidget(self.prompt_text_edit)

        blank_row = QHBoxLayout()
        blank_row.addWidget(QLabel("Blank lines before the text:"))
        self.prompt_blank_lines_spin = QSpinBox()
        self.prompt_blank_lines_spin.setRange(0, 10)
        self.prompt_blank_lines_spin.setValue(1)
        blank_row.addWidget(self.prompt_blank_lines_spin)
        blank_row.addStretch(1)
        form.addLayout(blank_row)

        button_row = QHBoxLayout()
        new_button = QPushButton("New")
        new_button.clicked.connect(self._on_prompt_new)
        button_row.addWidget(new_button)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._on_prompt_save)
        button_row.addWidget(save_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._on_prompt_delete)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        form.addLayout(button_row)

        self._configs: list[tuple[str, str, str, tp.PromptConfig]] = []
        self._reload_prompt_list()
        return page

    def _load_default_prompt(self) -> None:
        config = tp.get_default_prompt()
        if config is None:
            config = tp._FALLBACK_DEFAULT  # what would actually be used if nothing is saved
        self.default_prompt_edit.setPlainText(config.prompt)
        self.default_blank_lines_spin.setValue(config.blank_lines)
        self._default_prompt_snapshot = (config.prompt.strip(), config.blank_lines)

    def _default_prompt_dirty(self) -> bool:
        return (
            self.default_prompt_edit.toPlainText().strip(),
            self.default_blank_lines_spin.value(),
        ) != self._default_prompt_snapshot

    def _on_default_prompt_save(self) -> bool:
        prompt = self.default_prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.critical(self, "Save default prompt", "The prompt text is required.")
            return False
        blank_lines = self.default_blank_lines_spin.value()
        tp.set_default_prompt(tp.PromptConfig(prompt=prompt, blank_lines=blank_lines))
        self.app.log("Saved default translation prompt")
        self._default_prompt_snapshot = (prompt, blank_lines)
        return True

    def _reload_prompt_list(self, select: tuple[str, str, str] | None = None) -> None:
        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        self._configs = tp.list_configs()
        select_row = -1
        for i, (model, source, target, _cfg) in enumerate(self._configs):
            self.prompt_list.addItem(QListWidgetItem(f"{model}: {source} → {target}"))
            if select == (model, source, target):
                select_row = i
        self.prompt_list.blockSignals(False)
        if select_row != -1:
            self.prompt_list.setCurrentRow(select_row)
        elif self._configs:
            self.prompt_list.setCurrentRow(0)
        else:
            self._on_prompt_new()

    def _on_prompt_selected(self, row: int) -> None:
        if not (0 <= row < len(self._configs)):
            return
        model, source, target, cfg = self._configs[row]
        self.prompt_model_combo.setCurrentText(model)
        self.prompt_source_combo.setCurrentText(source)
        self.prompt_target_combo.setCurrentText(target)
        self.prompt_text_edit.setPlainText(cfg.prompt)
        self.prompt_blank_lines_spin.setValue(cfg.blank_lines)
        self._prompt_form_snapshot = (model, source, target, cfg.prompt.strip(), cfg.blank_lines)

    def _on_prompt_new(self) -> None:
        self.prompt_list.setCurrentRow(-1)
        self.prompt_model_combo.setCurrentText("")
        self.prompt_source_combo.setCurrentText("en")
        self.prompt_target_combo.setCurrentText("de")
        self.prompt_text_edit.setPlainText("")
        self.prompt_blank_lines_spin.setValue(1)
        self.prompt_model_combo.setFocus()
        self._prompt_form_snapshot = ("", "en", "de", "", 1)

    def _prompt_form_dirty(self) -> bool:
        return (
            self.prompt_model_combo.currentText().strip(),
            self.prompt_source_combo.currentText().strip(),
            self.prompt_target_combo.currentText().strip(),
            self.prompt_text_edit.toPlainText().strip(),
            self.prompt_blank_lines_spin.value(),
        ) != self._prompt_form_snapshot

    def _on_prompt_save(self) -> bool:
        model = self.prompt_model_combo.currentText().strip()
        source = self.prompt_source_combo.currentText().strip()
        target = self.prompt_target_combo.currentText().strip()
        prompt = self.prompt_text_edit.toPlainText().strip()
        if not model or not source or not target or not prompt:
            QMessageBox.critical(
                self, "Save prompt",
                "Model, From, To, and the prompt text are all required.")
            return False
        blank_lines = self.prompt_blank_lines_spin.value()
        tp.set_prompt(model, source, target, tp.PromptConfig(prompt=prompt, blank_lines=blank_lines))
        self._reload_prompt_list(select=(model, source, target))
        self.app.log(f"Saved translation prompt for {model} ({source} → {target})")
        return True

    def _on_prompt_delete(self) -> None:
        row = self.prompt_list.currentRow()
        if not (0 <= row < len(self._configs)):
            return
        model, source, target, _cfg = self._configs[row]
        confirm = QMessageBox.question(
            self, "Delete prompt",
            f"Delete the translation prompt for {model} ({source} → {target})? "
            "Translation will fall back to the built-in default for this "
            "model/pair afterward.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        tp.delete_prompt(model, source, target)
        self.app.log(f"Deleted translation prompt for {model} ({source} → {target})")
        self._reload_prompt_list()

    # -- AI prompts (image description drafting, whole-slide AI rewrite) ------
    #
    # Both used to be hardcoded SYSTEM_PROMPT constants (alt_draft.py/
    # ai_draft.py) with no way to tune them short of editing source
    # (2026-09-23 review finding) -- draft_prompts.py now persists a
    # user override for each, one prompt per feature (no per-model grid
    # like translation's own tab above: neither feature has a language
    # pair, and there was no request for per-model tuning here). Same
    # single-field, explicit-"Save"-button, snapshot-dirty-checked pattern
    # as the translation tab's own "Default prompt" field.

    def _build_ai_prompts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        draft_group = QGroupBox("Image description prompt")
        draft_layout = QVBoxLayout(draft_group)
        draft_layout.addWidget(QLabel(
            "Sent as the system prompt for every \"Draft\"/\"Draft all…\" "
            "call (alt_draft.OllamaBackend). Changing it can make a model "
            "abandon the required JSON output format -- see the per-image "
            "\"Tune prompt…\" dialog for a way to experiment on one image "
            "before changing this default for every batch."
        ))
        self.draft_prompt_edit = QPlainTextEdit()
        self.draft_prompt_edit.setMinimumHeight(120)
        draft_layout.addWidget(self.draft_prompt_edit)
        draft_button_row = QHBoxLayout()
        draft_button_row.addStretch(1)
        draft_reset_button = QPushButton("Reset to default")
        draft_reset_button.clicked.connect(self._on_draft_prompt_reset)
        draft_button_row.addWidget(draft_reset_button)
        draft_save_button = QPushButton("Save")
        draft_save_button.clicked.connect(self._on_draft_prompt_save)
        draft_button_row.addWidget(draft_save_button)
        draft_layout.addLayout(draft_button_row)
        layout.addWidget(draft_group)
        self._load_draft_prompt()

        rewrite_group = QGroupBox("Slide rewrite prompt")
        rewrite_layout = QVBoxLayout(rewrite_group)
        rewrite_layout.addWidget(QLabel(
            "Sent as the system prompt for the slide-source editor's own "
            "\"AI draft\" rewrite (ai_draft.OllamaSlideDrafter). Must keep "
            "the instruction to reproduce every \"%%%PROTECTED_N%%%\" "
            "placeholder line verbatim -- removing it lets the model edit "
            "content this feature is specifically meant to protect (the "
            "slide's own header comment, \\setSlideVersion{} line, and "
            "\\vbox to 0pt{...} overlays)."
        ))
        self.rewrite_prompt_edit = QPlainTextEdit()
        self.rewrite_prompt_edit.setMinimumHeight(120)
        rewrite_layout.addWidget(self.rewrite_prompt_edit)
        rewrite_button_row = QHBoxLayout()
        rewrite_button_row.addStretch(1)
        rewrite_reset_button = QPushButton("Reset to default")
        rewrite_reset_button.clicked.connect(self._on_rewrite_prompt_reset)
        rewrite_button_row.addWidget(rewrite_reset_button)
        rewrite_save_button = QPushButton("Save")
        rewrite_save_button.clicked.connect(self._on_rewrite_prompt_save)
        rewrite_button_row.addWidget(rewrite_save_button)
        rewrite_layout.addLayout(rewrite_button_row)
        layout.addWidget(rewrite_group)
        self._load_rewrite_prompt()

        layout.addStretch(1)
        return page

    def _load_draft_prompt(self) -> None:
        text = draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) or alt_draft.SYSTEM_PROMPT
        self.draft_prompt_edit.setPlainText(text)
        self._draft_prompt_snapshot = text.strip()

    def _draft_prompt_dirty(self) -> bool:
        return self.draft_prompt_edit.toPlainText().strip() != self._draft_prompt_snapshot

    def _on_draft_prompt_save(self) -> bool:
        prompt = self.draft_prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.critical(self, "Save prompt", "The prompt text is required.")
            return False
        # Saving the stock text verbatim is the same as never having
        # customized it (draft_prompts.set_custom_prompt() treats an
        # unchanged-from-default save the same as a reset) -- avoids a
        # redundant on-disk override that would just silently diverge if
        # alt_draft.SYSTEM_PROMPT itself is later revised in a code update.
        draft_prompts.set_custom_prompt(
            draft_prompts.KIND_IMAGE_DRAFT,
            "" if prompt == alt_draft.SYSTEM_PROMPT.strip() else prompt,
        )
        self.app.log("Saved image description prompt")
        self._draft_prompt_snapshot = prompt
        return True

    def _on_draft_prompt_reset(self) -> None:
        self.draft_prompt_edit.setPlainText(alt_draft.SYSTEM_PROMPT)

    def _load_rewrite_prompt(self) -> None:
        text = draft_prompts.get_custom_prompt(draft_prompts.KIND_SLIDE_REWRITE) or ai_draft.SYSTEM_PROMPT
        self.rewrite_prompt_edit.setPlainText(text)
        self._rewrite_prompt_snapshot = text.strip()

    def _rewrite_prompt_dirty(self) -> bool:
        return self.rewrite_prompt_edit.toPlainText().strip() != self._rewrite_prompt_snapshot

    def _on_rewrite_prompt_save(self) -> bool:
        prompt = self.rewrite_prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.critical(self, "Save prompt", "The prompt text is required.")
            return False
        draft_prompts.set_custom_prompt(
            draft_prompts.KIND_SLIDE_REWRITE,
            "" if prompt == ai_draft.SYSTEM_PROMPT.strip() else prompt,
        )
        self.app.log("Saved slide rewrite prompt")
        self._rewrite_prompt_snapshot = prompt
        return True

    def _on_rewrite_prompt_reset(self) -> None:
        self.rewrite_prompt_edit.setPlainText(ai_draft.SYSTEM_PROMPT)

    # -- Ollama models --------------------------------------------------------

    def _build_ollama_models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        host_group = QGroupBox("Ollama host")
        host_layout = QHBoxLayout(host_group)
        host_layout.addWidget(QLabel("URL:"))
        self.ollama_host_edit = QLineEdit(app_settings.get_ollama_host())
        self.ollama_host_edit.setPlaceholderText("http://localhost:11434")
        # Applied immediately on losing focus/Enter, no separate Save
        # button -- same "nothing to lose on close" pattern as dark mode/
        # tab width on the General tab, not the translation tab's own
        # explicit-save fields (there is only ever one current value here,
        # nothing to accidentally discard).
        self.ollama_host_edit.editingFinished.connect(self._on_ollama_host_changed)
        host_layout.addWidget(self.ollama_host_edit, stretch=1)
        layout.addWidget(host_group)

        default_models_group = QGroupBox("Default models")
        default_models_layout = QVBoxLayout(default_models_group)
        translation_model_row = QHBoxLayout()
        translation_model_row.addWidget(QLabel("Translation:"))
        self.default_translation_model_combo = QComboBox()
        self.default_translation_model_combo.setPlaceholderText(
            "No Ollama models available"
        )
        self.default_translation_model_combo.activated.connect(
            self._on_default_translation_model_selected
        )
        translation_model_row.addWidget(
            self.default_translation_model_combo, stretch=1
        )
        default_models_layout.addLayout(translation_model_row)

        other_model_row = QHBoxLayout()
        other_model_row.addWidget(QLabel("Other AI tasks:"))
        self.default_other_model_combo = QComboBox()
        self.default_other_model_combo.setPlaceholderText(
            "No Ollama models available"
        )
        self.default_other_model_combo.activated.connect(
            self._on_default_other_model_selected
        )
        other_model_row.addWidget(self.default_other_model_combo, stretch=1)
        default_models_layout.addLayout(other_model_row)
        vision_note = QLabel(
            "Other AI tasks include Check syntax, AI draft, image descriptions, "
            "and image prompt tuning. Image descriptions need a vision-capable "
            "model; when this choice cannot process images, an available "
            "vision model is selected."
        )
        vision_note.setWordWrap(True)
        default_models_layout.addWidget(vision_note)
        layout.addWidget(default_models_group)

        layout.addWidget(QLabel(
            "Every model currently installed in Ollama, drafting and "
            "translation alike. Deleting one here removes it from Ollama's "
            "own local model store -- its actual files on disk -- not just "
            "something SlideMage was tracking; there is nothing else to "
            "clean up. This can't be undone short of re-pulling the model.\n\n"
            "\"Update selected…\" re-pulls the latest weights for a plain "
            "model, or -- for one of this project's own custom models "
            "(built as a num_ctx/temperature variant of a base model, e.g. "
            "\"gemma4:64k\") -- pulls that base and relinks the custom "
            "model to it, since the custom tag itself has no registry entry "
            "to pull."
        ))

        self.ollama_models_list = QListWidget()
        # Multi-select (2026-08-26, direct instruction) -- ctrl/shift-click
        # to pick several, deleted together by one "Delete selected…" click
        # instead of one model at a time.
        self.ollama_models_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.ollama_models_list, stretch=1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_ollama_models)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        self.ollama_update_button = QPushButton("Update selected…")
        self.ollama_update_button.setEnabled(False)
        self.ollama_update_button.clicked.connect(self._on_ollama_model_update)
        button_row.addWidget(self.ollama_update_button)
        self.ollama_delete_button = QPushButton("Delete selected…")
        self.ollama_delete_button.setEnabled(False)
        self.ollama_delete_button.clicked.connect(self._on_ollama_model_delete)
        button_row.addWidget(self.ollama_delete_button)
        layout.addLayout(button_row)

        self.ollama_models_list.itemSelectionChanged.connect(
            lambda: (
                self.ollama_delete_button.setEnabled(bool(self.ollama_models_list.selectedItems())),
                self.ollama_update_button.setEnabled(bool(self.ollama_models_list.selectedItems())),
            ))

        self._reload_ollama_models()
        return page

    def _on_ollama_host_changed(self) -> None:
        app_settings.set_ollama_host(self.ollama_host_edit.text())
        # Re-read it rather than trust the raw text field -- an
        # empty/whitespace-only entry clears the override (see
        # app_settings.set_ollama_host()'s own docstring), so this shows
        # the actual effective host (falling back to $OLLAMA_HOST/the
        # plain default) rather than leaving a blank field.
        self.ollama_host_edit.setText(app_settings.get_ollama_host())
        self.app.log(f"Ollama host set to {app_settings.get_ollama_host()}")
        self._reload_ollama_models()

    def _reload_ollama_models(self) -> None:
        self.ollama_models_list.clear()
        models = alt_draft.list_installed_models_detailed()
        self.available_models = [model.name for model in models]
        self.vision_models = [
            model.name for model in models if "vision" in model.capabilities
        ]
        self._populate_default_model_combos(self.available_models)
        if not models:
            self.ollama_models_list.addItem("(Ollama not reachable, or no models installed)")
            self.ollama_models_list.setEnabled(False)
            self.ollama_delete_button.setEnabled(False)
            self.ollama_update_button.setEnabled(False)
            return
        self.ollama_models_list.setEnabled(True)
        for model in models:
            item = QListWidgetItem(f"{model.name}   —   {_human_size(model.size_bytes)}")
            item.setData(Qt.ItemDataRole.UserRole, model.name)
            self.ollama_models_list.addItem(item)
        self.ollama_delete_button.setEnabled(False)
        self.ollama_update_button.setEnabled(False)

    def _populate_default_model_combos(self, models: list[str]) -> None:
        combos = (
            self.default_translation_model_combo,
            self.default_other_model_combo,
        )
        for combo in combos:
            combo.clear()
            combo.setEnabled(bool(models))
            if models:
                combo.addItems(models)

        if not models:
            return

        translation_model = app_settings.get("translation_model")
        if translation_model not in models:
            translation_model = alt_draft.DEFAULT_TRANSLATION_MODEL
        if translation_model not in models:
            translation_model = models[0]
        self.default_translation_model_combo.setCurrentText(translation_model)

        other_model = app_settings.get_other_model()
        if other_model not in models:
            other_model = models[0]
        self.default_other_model_combo.setCurrentText(other_model)

    def _on_default_translation_model_selected(self, index: int) -> None:
        app_settings.set(
            "translation_model", self.default_translation_model_combo.itemText(index)
        )

    def _on_default_other_model_selected(self, index: int) -> None:
        app_settings.set("other_model", self.default_other_model_combo.itemText(index))

    def _on_ollama_model_delete(self) -> None:
        models = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ollama_models_list.selectedItems()
        ]
        models = [model for model in models if model is not None]
        if not models:
            return

        # Uses the same app-wide Ollama mutex every drafting/translation
        # call goes through (qt_gui.py's try_start_ollama_task()) -- not
        # because deleting itself is an Ollama *inference* call, but to
        # refuse deleting a model out from under a draft/translate batch
        # that's actively using it. Held for the whole loop below (2026-08-26,
        # direct instruction: delete every selected model in one go), not
        # re-acquired per model.
        if not self.app.try_start_ollama_task(
            f"deleting {len(models)} model(s)" if len(models) > 1 else f"deleting {models[0]}"
        ):
            return
        try:
            if len(models) == 1:
                detail = f"Permanently delete \"{models[0]}\""
            else:
                detail = "Permanently delete these {} models:\n\n{}".format(
                    len(models), "\n".join(f"  • {m}" for m in models)
                )
            confirm = QMessageBox.question(
                self, "Delete Ollama model" + ("s" if len(models) > 1 else ""),
                f"{detail} from Ollama's local model store? This removes "
                "the file(s) from disk and cannot be undone short of "
                "re-pulling.\n\n"
                "Safe to do even if another installed model was created "
                "from one of these (e.g. via \"ollama create\") and shares "
                "its underlying files -- Ollama's own deletion only removes "
                "files no other installed model still references, exactly "
                "like the \"ollama rm\" command.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            self.ollama_delete_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                failures: list[tuple[str, str]] = []
                deleted = 0
                for model in models:
                    ok, error = alt_draft.delete_model(model)
                    if ok:
                        deleted += 1
                        self.app.log(f"Deleted Ollama model {model}")
                    else:
                        failures.append((model, error or "Unknown error"))
            finally:
                QApplication.restoreOverrideCursor()
        finally:
            self.app.end_ollama_task()

        if failures:
            QMessageBox.critical(
                self, "Delete failed",
                f"Deleted {deleted} of {len(models)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures),
            )
        self._reload_ollama_models()

    def _on_ollama_model_update(self) -> None:
        models = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ollama_models_list.selectedItems()
        ]
        models = [model for model in models if model is not None]
        if not models:
            return

        derived = [m for m in models if m in alt_draft.DERIVED_MODEL_BASES]
        note = ""
        if derived:
            plural = len(derived) > 1
            note = (
                "\n\nNote: " + ", ".join(derived) + (" are" if plural else " is") +
                " custom model(s) built on top of another base model -- "
                "updating " + ("them" if plural else "it") + " pulls and "
                "relinks to that base instead of pulling " +
                ("themselves" if plural else "itself") + " directly."
            )
        detail = (f'"{models[0]}"' if len(models) == 1 else
                   "these {} models:\n\n{}".format(
                       len(models), "\n".join(f"  • {m}" for m in models)))
        confirm = QMessageBox.question(
            self, "Update Ollama model" + ("s" if len(models) > 1 else ""),
            f"Update {detail} to the latest version?{note}\n\n"
            "This re-downloads the underlying weights (can be several GB "
            "per model and take a while) and cannot be cancelled once "
            "started.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Same app-wide Ollama mutex delete uses above -- refuses to start
        # a many-minute download out from under an active draft/translate
        # batch, and vice versa. Released from the worker thread itself
        # (see _update_ollama_models_bg() below), not from the GUI-thread
        # signal handler, so it's freed even if this dialog is closed
        # before the update finishes.
        if not self.app.try_start_ollama_task(
            f"updating {len(models)} model(s)" if len(models) > 1 else f"updating {models[0]}"
        ):
            return

        self.ollama_delete_button.setEnabled(False)
        self.ollama_update_button.setEnabled(False)
        self.ollama_models_list.setEnabled(False)
        threading.Thread(
            target=self._update_ollama_models_bg, args=(models,), daemon=True
        ).start()

    def _update_ollama_models_bg(self, models: list[str]) -> None:
        results: list[tuple[str, bool, str]] = []
        try:
            for model in models:
                self.app.signals.log.emit(f"Updating Ollama model {model}…")

                def progress(line: str) -> None:
                    self.app.signals.log.emit(line)

                ok, error = alt_draft.update_model(model, on_progress=progress)
                results.append((model, ok, error))
                if ok:
                    self.app.signals.log.emit(f"Updated Ollama model {model}")
                else:
                    self.app.signals.log.emit(f"Failed to update {model}: {error}")
        finally:
            self.app.end_ollama_task()
        try:
            self._ollama_update_done.emit(results)
        except RuntimeError:
            # This dialog was closed before the update finished -- nothing
            # left to update it with; the result is still in the log above,
            # not silently dropped, same as _ImageEditor.translation_done's
            # own equivalent guard in qt_transcript_tab.py.
            pass

    def _on_ollama_update_finished(self, results: list[tuple[str, bool, str]]) -> None:
        self.ollama_models_list.setEnabled(True)
        self._reload_ollama_models()
        failures = [(model, error) for model, ok, error in results if not ok]
        if failures:
            QMessageBox.critical(
                self, "Update failed",
                f"Updated {len(results) - len(failures)} of {len(results)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures),
            )
