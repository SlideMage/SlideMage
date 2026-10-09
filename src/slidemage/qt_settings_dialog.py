"""Settings dialog (2026-08-25, direct instruction): a "Settings" menu
holding cross-cutting app preferences that don't belong scattered across
individual toolbars -- dark mode (moved here from its own toolbar
checkbox in the main window), the default Ollama model per AI task (an "AI
models" tab), and (2026-08-25) an "Ollama models" section to delete
models this app no longer needs -- genuinely from Ollama's own local model
store (ai.ollama_admin.delete_model(), its own DELETE /api/delete), not just
some SlideMage-side list.

Merged in v4.0.0 from Jürgen Fleiß's fork: the General tab's "Updates"
group (GitHub token for Info -> "Check for updates…"), the Ollama host
field at the top of the Ollama models section, and the "AI prompts" tab
(editable system prompts for image-description drafting and the slide
rewrite, persisted by draft_prompts.py).

v4.1.0 (direct instruction): the AI prompts tab has three pages -- Image
descriptions, Slide rewrite and Translation (TranslationPromptsPanel, the
per-(model, source language, target language) translation prompts that
used to open from a "Translation prompts…" button on the AI models tab);
the General tab's Updates group chooses the update mode (updater.py).

2026-10-09 (UI redesign step 2): the AI models tab picks provider and model
per task (local Ollama or Claude), toggles "Local AI only" (globally and for
this project) and stores the Anthropic API key. Kept deliberately small --
this dialog is rebuilt in a later step.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import ai_draft
from . import alt_draft
from . import app_settings
from .ai import credentials, ollama_admin, resolver
from .ai.providers import ANTHROPIC_FALLBACK_MODELS, AnthropicProvider, OllamaProvider
from . import draft_prompts
from . import slide_snapshot
from . import updater
from .latex_edit import DEFAULT_TAB_WIDTH_CHARS, TAB_WIDTH_SETTING_KEY
from .qt_translation_prompts_panel import TranslationPromptsPanel


def _note_label(text: str) -> QLabel:
    """A word-wrapping QLabel for explanatory text -- without wrapping, one
    long explanation sets the whole dialog's minimum width (it used to
    open about 2200px wide; v3.33.2 on Jürgen Fleiß's fork)."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


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

        # Snapshots of the two "AI prompts" fields' last-loaded-or-saved
        # text, for the unsaved-changes check in reject() below -- set for
        # real by _load_draft_prompt()/_load_rewrite_prompt() once that tab
        # is built; None until then fails safe (never "dirty").
        self._draft_prompt_snapshot: str | None = None
        self._rewrite_prompt_snapshot: str | None = None
        # Read by the main window after this dialog closes, to refresh the model
        # pickers of any dialog/tab that's still open -- filled in by
        # _reload_ollama_models().
        self.available_models: list[str] = []
        self.vision_models: list[str] = []
        self._cloud_models: list[str] = []
        self._model_combos: dict[str, QComboBox] = {}

        self._ollama_update_done.connect(self._on_ollama_update_finished)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, stretch=1)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_ai_models_tab(), "AI models")
        tabs.addTab(self._build_ai_prompts_tab(), "AI prompts")

        # Close only -- every change here (dark mode, a model default) is
        # applied and persisted immediately by its own control, same as
        # every other dialog in this app that edits durable state (e.g.
        # qt_transcript_tab.py's review panel) -- there is nothing to
        # "commit" on an OK button, and nothing a Cancel could sensibly
        # undo. The one exception is the "AI prompts" text fields
        # (including the Translation page's two forms), which only save on
        # their own Save buttons -- reject() (overridden below; also what
        # Escape and the window's X button call) asks before discarding
        # unsaved text there.
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _dirty_prompt_descriptions(self) -> list[str]:
        descriptions = []
        if self._draft_prompt_dirty():
            descriptions.append("the image description prompt")
        if self._rewrite_prompt_dirty():
            descriptions.append("the slide rewrite prompt")
        descriptions.extend(self.translation_prompts_panel.dirty_descriptions())
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
                if self._draft_prompt_dirty():
                    ok = self._on_draft_prompt_save() and ok
                if self._rewrite_prompt_dirty():
                    ok = self._on_rewrite_prompt_save() and ok
                ok = self.translation_prompts_panel.save_dirty() and ok
                if not ok:
                    # A save failed validation (an empty prompt) -- its own
                    # QMessageBox already explained why; stay open.
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

        # Source editor's own Tab-key width (2026-08-29, direct
        # instruction -- was hardcoded; Qt's own 80px default tab stop is far
        # too wide for code, see latex_edit.DEFAULT_TAB_WIDTH_CHARS). Applied immediately (like dark mode
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

        layout.addWidget(self._build_render_template_group())
        layout.addWidget(self._build_update_token_group())
        layout.addStretch(1)
        return page

    def _build_render_template_group(self) -> QGroupBox:
        """Default template for renders without a deck (2026-10-03, direct
        instruction; saved immediately): the slide editor's Render to PDF
        and Preview, tikz illustration renders. Lists the templates whose
        preamble file this project has; out of the box the SlideMage
        template (slide_snapshot.render_template())."""
        group = QGroupBox("Slide rendering")
        group_layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Default template:"))
        self.render_template_combo = QComboBox()
        current = slide_snapshot.render_template()
        for key in slide_snapshot.available_templates():
            self.render_template_combo.addItem(slide_snapshot.TEMPLATES[key], key)
            if key == current:
                self.render_template_combo.setCurrentIndex(
                    self.render_template_combo.count() - 1)
        self.render_template_combo.currentIndexChanged.connect(
            self._on_render_template_changed)
        row.addWidget(self.render_template_combo)
        row.addStretch(1)
        group_layout.addLayout(row)
        group_layout.addWidget(_note_label(
            "Used when a slide is rendered on its own, outside a deck: the slide "
            "editor's \"Render to PDF\" and \"Preview\", and tikz illustration "
            "renders. A deck's own renders always use the deck's template."))
        return group

    def _on_render_template_changed(self, index: int) -> None:
        key = self.render_template_combo.itemData(index)
        if key:
            app_settings.set(slide_snapshot.RENDER_TEMPLATE_SETTING_KEY, key)
            self.app.log(
                f"Default render template set to {slide_snapshot.TEMPLATES[key]}")

    def _build_update_token_group(self) -> QGroupBox:
        """Update mode (v4.1.0, direct instruction; saved immediately) and
        the GitHub token for update checks while the release repository is
        private. The token is saved on Enter/leaving the field, like the
        Ollama host; clearing the field removes it."""
        group = QGroupBox("Updates")
        group_layout = QVBoxLayout(group)

        self.update_mode_buttons: dict[str, QRadioButton] = {}
        mode_group = QButtonGroup(group)
        current_mode = updater.get_update_mode()
        for mode, label in (
            (updater.UPDATE_MODE_OFF, "Don't check for updates"),
            (updater.UPDATE_MODE_ASK, "Check for updates and ask before installing (default)"),
            (updater.UPDATE_MODE_AUTO, "Check for updates and install them automatically"),
        ):
            button = QRadioButton(label)
            button.setChecked(mode == current_mode)
            button.toggled.connect(
                lambda checked, m=mode: checked and self._on_update_mode_changed(m))
            mode_group.addButton(button)
            self.update_mode_buttons[mode] = button
            group_layout.addWidget(button)
        mode_note = _note_label(
            "Checked when SlideMage starts. Applies to the downloaded app; a "
            "copy run from source is updated with git. An update that "
            "changes how SlideMage works is always asked about, even when "
            "installing automatically. Info → Check for updates… always works."
        )
        mode_note.setObjectName("mutedLabel")
        group_layout.addWidget(mode_note)

        row = QHBoxLayout()
        row.addWidget(QLabel("GitHub token:"))
        self.github_token_edit = QLineEdit(updater.saved_token())
        self.github_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.github_token_edit.setPlaceholderText("ghp_… (only needed while the repository is private)")
        self.github_token_edit.editingFinished.connect(self._on_github_token_changed)
        row.addWidget(self.github_token_edit, stretch=1)
        show_box = QCheckBox("Show")
        show_box.toggled.connect(lambda shown: self.github_token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password))
        row.addWidget(show_box)
        group_layout.addLayout(row)
        note = (
            f"Read access to {updater.REPO} is enough. Stored for your user "
            "account only, not in the project folder."
        )
        if os.environ.get(updater.TOKEN_ENV_VAR):
            note += f" {updater.TOKEN_ENV_VAR} is set and takes precedence."
        note_label = _note_label(note)
        note_label.setObjectName("mutedLabel")
        group_layout.addWidget(note_label)
        return group

    def _on_update_mode_changed(self, mode: str) -> None:
        try:
            updater.set_update_mode(mode)
        except OSError as exc:
            QMessageBox.warning(self, "Updates", f"Couldn't save the update setting: {exc}")
            return
        self.app.log(f"Update mode set to {mode!r}")

    def _on_github_token_changed(self) -> None:
        token = self.github_token_edit.text().strip()
        if token == updater.saved_token():
            return
        try:
            updater.save_token(token)
        except OSError as exc:
            QMessageBox.warning(self, "GitHub token", f"Couldn't save the token: {exc}")
            return
        self.app.log("GitHub token saved" if token else "GitHub token removed")

    # -- AI models ------------------------------------------------------------

    def _build_ai_models_tab(self) -> QWidget:
        """Default Ollama model per AI task (2026-09-26, direct
        instruction; replaces the old "whatever was used last" behaviour),
        plus (2026-09-27, direct instruction: same tab, visually separated
        -- both sections are about the AI models SlideMage uses) the
        former separate "Ollama models" tab underneath a divider. Applied
        immediately, like every other control in this dialog. The dialogs
        that offer a model picker preselect the default chosen here;
        picking a different model there only affects that dialog."""
        page = QWidget()
        layout = QVBoxLayout(page)
        self._build_cloud_section(layout)
        layout.addWidget(_note_label(
            "Default model for each AI task. Every dialog with a model picker "
            "starts on the model chosen here; picking another one there "
            "applies to that dialog only."
        ))
        form = QFormLayout()
        rows = (
            ("syntax_check", "Syntax check:"),
            ("ai_draft", "AI drafting:"),
            ("image_description", "Image descriptions:"),
            ("translation", "Translation:"),
        )
        # Filled (and refilled after an Ollama host change or a model
        # delete/update) by _populate_default_model_combos(), called from
        # _reload_ollama_models() once the Ollama section below exists.
        for task, label in rows:
            combo = QComboBox()
            # Don't size to the longest model name -- a long custom model
            # tag otherwise widens the whole dialog; the dropdown list
            # still shows full names.
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            if task == "image_description":
                combo.setToolTip("Only vision-capable models are listed.")
            self._model_combos[task] = combo
            combo.activated.connect(
                lambda index, t=task, c=combo: app_settings.set(
                    app_settings.MODEL_SETTINGS[t], c.itemData(index) or ""))  # "<provider>:<model>"
            form.addRow(label, combo)
        layout.addLayout(form)
        self._models_unreachable_label = _note_label("")
        layout.addWidget(self._models_unreachable_label)

        # Visual separator (2026-09-27, direct instruction) -- a plain
        # QFrame horizontal rule plus a bold heading, so the "Ollama
        # models" section below reads as clearly distinct from the
        # per-task defaults above even though both live on one page now.
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        heading = QLabel("<b>Ollama models</b>")
        layout.addWidget(heading)
        self._build_ollama_models_section(layout)
        return page

    # -- Cloud models (Claude): Local AI only and the API key -----------------

    _PROJECT_CHOICES = (
        ("Follow the global setting", "follow"),
        ("Local AI only", "local"),
        ("Allow cloud models", "cloud"),
    )

    def _build_cloud_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(QLabel("<b>Cloud models (Claude)</b>"))
        layout.addWidget(_note_label(
            "A cloud model receives whatever the task sends it (slide text, "
            "images). The first cloud request in a project asks for "
            "confirmation."
        ))
        self.local_only_check = QCheckBox("Local AI only: never use a cloud model")
        self.local_only_check.setChecked(resolver.global_local_only())
        self.local_only_check.toggled.connect(self._on_local_only_changed)
        layout.addWidget(self.local_only_check)

        project_row = QHBoxLayout()
        project_row.addWidget(QLabel("This project:"))
        self.project_local_only_combo = QComboBox()
        for label, value in self._PROJECT_CHOICES:
            self.project_local_only_combo.addItem(label, value)
        override = resolver.project_local_only()
        self.project_local_only_combo.setCurrentIndex(
            self.project_local_only_combo.findData(
                "follow" if override is None else "local" if override else "cloud"))
        self.project_local_only_combo.activated.connect(self._on_project_local_only_changed)
        project_row.addWidget(self.project_local_only_combo)
        project_row.addStretch(1)
        layout.addLayout(project_row)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Anthropic API key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-ant-…")
        key_row.addWidget(self.api_key_edit, stretch=1)
        save_key = QPushButton("Save key")
        save_key.clicked.connect(self._on_api_key_save)
        key_row.addWidget(save_key)
        remove_key = QPushButton("Remove key")
        remove_key.clicked.connect(self._on_api_key_remove)
        key_row.addWidget(remove_key)
        layout.addLayout(key_row)
        self.api_key_status = _note_label("")
        layout.addWidget(self.api_key_status)
        self._refresh_api_key_status()
        self._load_cloud_models()

    def _refresh_api_key_status(self) -> None:
        key = credentials.get_api_key()
        self.api_key_status.setText({
            None: "No API key set.",
            credentials.SOURCE_ENV: f"Using the key from the {credentials.ENV_VAR} "
                                    "environment variable (it takes precedence).",
            credentials.SOURCE_KEYCHAIN: "Key stored in the system keychain.",
            credentials.SOURCE_FILE: "Key stored in the settings file "
                                     "(.slidemage/app_settings.json inside the project "
                                     "folder, which may be synced). Install the optional "
                                     "'keyring' package to use the system keychain instead.",
        }[key.source if key else None])

    def _load_cloud_models(self) -> None:
        """The models Claude offers (live list with a key, else the short
        built-in one); none in local-only mode."""
        if resolver.local_only():
            self._cloud_models = []
        else:
            self._cloud_models = (
                AnthropicProvider().list_models() or list(ANTHROPIC_FALLBACK_MODELS))

    def _on_cloud_settings_changed(self) -> None:
        self._refresh_api_key_status()
        self._load_cloud_models()
        self._populate_default_model_combos()

    def _on_local_only_changed(self, checked: bool) -> None:
        resolver.set_global_local_only(checked)
        self._on_cloud_settings_changed()

    def _on_project_local_only_changed(self, _index: int) -> None:
        resolver.set_project_local_only(
            {"follow": None, "local": True, "cloud": False}[
                self.project_local_only_combo.currentData()])
        self._on_cloud_settings_changed()

    def _on_api_key_save(self) -> None:
        key = self.api_key_edit.text().strip()
        if not key:
            return
        credentials.set_api_key(key)
        self.api_key_edit.clear()
        self._on_cloud_settings_changed()

    def _on_api_key_remove(self) -> None:
        credentials.set_api_key("")
        self.api_key_edit.clear()
        self._on_cloud_settings_changed()

    # -- Ollama models (a section of the AI models tab, not its own tab) --------

    def _build_ollama_models_section(self, layout: QVBoxLayout) -> None:
        # Ollama host (from Jürgen Fleiß's fork) -- applied on Enter/leaving
        # the field, no separate Save button: there is only ever one current
        # value, nothing to accidentally discard.
        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Ollama host URL:"))
        self.ollama_host_edit = QLineEdit(app_settings.get_ollama_host())
        self.ollama_host_edit.setPlaceholderText("http://localhost:11434")
        self.ollama_host_edit.editingFinished.connect(self._on_ollama_host_changed)
        host_row.addWidget(self.ollama_host_edit, stretch=1)
        layout.addLayout(host_row)

        layout.addWidget(_note_label(
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

    def _on_ollama_host_changed(self) -> None:
        app_settings.set_ollama_host(self.ollama_host_edit.text())
        # Re-read rather than trust the raw field -- an empty entry clears
        # the override (app_settings.set_ollama_host()), so this shows the
        # effective host ($OLLAMA_HOST or the plain default) instead.
        self.ollama_host_edit.setText(app_settings.get_ollama_host())
        self.app.log(f"Ollama host set to {app_settings.get_ollama_host()}")
        self._reload_ollama_models()

    def _populate_default_model_combos(self) -> None:
        """(Re)fill the per-task default pickers from the current model
        lists, keeping each task's saved default selected -- listed as
        "(not available)" rather than silently dropped when it's missing,
        so a temporarily unreachable Ollama never rewrites a setting."""
        for task, combo in self._model_combos.items():
            models = self.vision_models if task == "image_description" else self.available_models
            combo.clear()
            combo.addItem("(none chosen -- built-in fallback)", "")
            for model in models:
                combo.addItem(model, f"ollama:{model}")
            for model in self._cloud_models:
                combo.addItem(f"{model} (cloud)", f"anthropic:{model}")
            saved = app_settings.default_model(task)
            if saved and combo.findData(saved) == -1:
                combo.addItem(f"{app_settings.split_spec(saved)[1]} (not available)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
        self._models_unreachable_label.setText(
            "" if self.available_models else
            f"Ollama is not reachable at {app_settings.get_ollama_host()}, "
            "or has no models installed.")
        self._models_unreachable_label.setVisible(not self.available_models)

    def _reload_ollama_models(self) -> None:
        self.ollama_models_list.clear()
        models = OllamaProvider().installed()
        self.available_models = [model.name for model in models]
        self.vision_models = [model.name for model in models if "vision" in model.capabilities]
        self._populate_default_model_combos()
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

    def _on_ollama_model_delete(self) -> None:
        models = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ollama_models_list.selectedItems()
        ]
        models = [model for model in models if model is not None]
        if not models:
            return

        # Uses the same app-wide Ollama mutex every drafting/translation
        # call goes through (the main window's try_start_ollama_task()) -- not
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
                    ok, error = ollama_admin.delete_model(model)
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

        # which models are custom shows only when the registry is asked
        # (ollama_admin.update_model), so the note covers the case in general
        note = ("\n\nA custom model you built from another one (ollama create) "
                "is updated by updating the model it was built from and "
                "rebuilding it on top.")
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

                ok, error = ollama_admin.update_model(model, on_progress=progress)
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

    # -- AI prompts (image description drafting, whole-slide AI rewrite) ------
    #
    # From Jürgen Fleiß's fork (2026-09-23 review finding): both used to be
    # hardcoded SYSTEM_PROMPT constants (alt_draft.py/ai_draft.py) with no way
    # to tune them short of editing source -- draft_prompts.py now persists a
    # user override for each. Explicit Save button + snapshot dirty check,
    # see reject() above. v4.1.0: one inner tab per kind of prompt, the
    # translation prompts (TranslationPromptsPanel) as the third.

    def _build_ai_prompts_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.ai_prompt_pages = QTabWidget()
        page_layout.addWidget(self.ai_prompt_pages)

        draft_page = QWidget()
        layout = QVBoxLayout(draft_page)
        draft_group = QGroupBox("Image description prompt")
        draft_layout = QVBoxLayout(draft_group)
        draft_layout.addWidget(_note_label(
            "Sent as the system prompt for every \"Draft\"/\"Draft all…\" "
            "call (alt_draft.ModelBackend). Changing it can make a model "
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
        layout.addStretch(1)
        self._load_draft_prompt()
        self.ai_prompt_pages.addTab(draft_page, "Image descriptions")

        rewrite_page = QWidget()
        layout = QVBoxLayout(rewrite_page)
        rewrite_group = QGroupBox("Slide rewrite prompt")
        rewrite_layout = QVBoxLayout(rewrite_group)
        rewrite_layout.addWidget(_note_label(
            "Sent as the system prompt for the slide-source editor's own "
            "\"AI draft\" rewrite (ai_draft.SlideDrafter). Must keep "
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
        layout.addStretch(1)
        self._load_rewrite_prompt()
        self.ai_prompt_pages.addTab(rewrite_page, "Slide rewrite")

        self.translation_prompts_panel = TranslationPromptsPanel(self.app)
        self.ai_prompt_pages.addTab(self.translation_prompts_panel, "Translation")
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
