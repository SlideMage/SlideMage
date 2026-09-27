"""Translation prompt configuration (2026-08-25; split out of
qt_settings_dialog.py's own tabbed dialog into its own window 2026-09-27,
direct instruction: reached from Settings -> AI models' "Translation
prompts…" button, next to the Translation model picker, rather than
living as a permanent tab of its own).

Per-(model, source language, target language) prompt overrides
(translation_prompts.py), used by alt_draft.OllamaTranslationBackend for
both the Images tab's per-image "Translate now" button and its
"Translate all…" batch. Unchanged behavior from the old tab -- only the
container moved, plus this dialog's own unsaved-changes-on-close check
(previously the SettingsDialog's own reject() covered both prompt forms
and this app-models picker together; now each dialog only has its own
state to worry about)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from . import alt_draft
from . import translation_prompts as tp


class TranslationPromptsDialog(QDialog):
    def __init__(self, parent, app) -> None:
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Translation prompts")
        self.resize(680, 520)

        self._default_prompt_snapshot: tuple[str, int] | None = None
        self._prompt_form_snapshot: tuple[str, str, str, str, int] | None = None

        outer = QVBoxLayout(self)

        # -- default prompt -- used whenever no per-model override below
        # matches; the per-model list further down always takes priority
        # over this when both could apply.
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

        # Close only, same reasoning as SettingsDialog's own button_box:
        # every field here saves immediately via its own Save button, so
        # there's nothing to "commit" -- except the two prompt text forms,
        # which don't save on their own, so unsaved text sitting in either
        # when this dialog closes would otherwise silently vanish. Routed
        # through self.reject (overridden below), which is also what
        # Escape and the window's X button already funnel through.
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        outer.addWidget(button_box)

    # -- unsaved-changes-on-close ------------------------------------------------

    def _dirty_prompt_descriptions(self) -> list[str]:
        descriptions = []
        if self._default_prompt_dirty():
            descriptions.append("the default prompt")
        if self._prompt_form_dirty():
            descriptions.append("the per-model prompt shown on the right")
        return descriptions

    def reject(self) -> None:
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
                if not ok:
                    return
            elif clicked is not discard_button:
                return  # Cancel -- stay open, nothing saved or discarded
        super().reject()

    # -- default prompt --------------------------------------------------------

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

    # -- per-model overrides -----------------------------------------------------

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
