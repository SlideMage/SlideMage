"""Translation prompt configuration, as the "Translation" page of the
Settings dialog's "AI prompts" tab (v4.1.0, direct instruction: the
translation prompts belong with the other AI prompts). Replaces
qt_translation_prompts_dialog.py's TranslationPromptsDialog, which was
reached from a "Translation prompts…" button on the AI models tab
(2026-09-27 to v4.0.0); before that it was a tab of its own (2026-08-25).

Per-(model, source language, target language) prompt overrides
(translation_prompts.py), used by alt_draft.OllamaTranslationBackend for
both the Images tab's per-image "Translate now" button and its
"Translate all…" batch. The two forms here only save on their own Save
buttons; SettingsDialog.reject() asks about unsaved text through
dirty_descriptions()/save_dirty() below."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
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
    QWidget,
)

from . import alt_draft
from . import translation_prompts as tp


def _note_label(text: str) -> QLabel:
    """A word-wrapping QLabel -- an unwrapped long explanation sets the
    whole dialog's minimum width (same fix as qt_settings_dialog.py)."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class TranslationPromptsPanel(QWidget):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.app = app

        self._default_prompt_snapshot: tuple[str, int] | None = None
        self._prompt_form_snapshot: tuple[str, str, str, str, int] | None = None

        outer = QVBoxLayout(self)

        # -- default prompt -- used whenever no per-model override below
        # matches; the per-model list further down always takes priority
        # over this when both could apply.
        default_group = QGroupBox("Default prompt")
        default_layout = QVBoxLayout(default_group)
        default_layout.addWidget(_note_label(
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

        overrides_group = QGroupBox("Per-model overrides")
        overrides_layout = QVBoxLayout(overrides_group)
        outer.addWidget(overrides_group, stretch=1)
        overrides_layout.addWidget(_note_label(
            "When the model + From + To below match exactly, this prompt "
            "is used instead of the default above -- for both the Images "
            "tab's per-image \"Translate now\" button and \"Translate all…\"."
        ))

        body = QHBoxLayout()
        overrides_layout.addLayout(body, stretch=1)

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
        # Don't size to the longest model name -- that would widen the
        # whole Settings dialog (same as the AI models tab's pickers).
        self.prompt_model_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.prompt_model_combo.setMinimumContentsLength(16)
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

        form.addWidget(_note_label(
            "Prompt -- sent as a single message: this text, then the "
            "blank line(s) below, then the text to translate verbatim "
            "(no separate system-role turn):"
        ))
        self.prompt_text_edit = QPlainTextEdit()
        self.prompt_text_edit.setMinimumHeight(120)
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

    # -- unsaved changes (asked about by SettingsDialog.reject()) ----------------

    def dirty_descriptions(self) -> list[str]:
        descriptions = []
        if self._default_prompt_dirty():
            descriptions.append("the default translation prompt")
        if self._prompt_form_dirty():
            descriptions.append("the per-model translation prompt")
        return descriptions

    def save_dirty(self) -> bool:
        """Save whichever form has unsaved text; False if a save failed
        validation (its own QMessageBox already explained why)."""
        ok = True
        if self._default_prompt_dirty():
            ok = self._on_default_prompt_save() and ok
        if self._prompt_form_dirty():
            ok = self._on_prompt_save() and ok
        return ok

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
            "Translation will fall back to the default prompt for this "
            "model/pair afterward.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        tp.delete_prompt(model, source, target)
        self.app.log(f"Deleted translation prompt for {model} ({source} → {target})")
        self._reload_prompt_list()
