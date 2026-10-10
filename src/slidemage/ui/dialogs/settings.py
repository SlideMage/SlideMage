"""The Settings sheet (UI_REDESIGN_PLAN.md, step 9): the preferences that are not about one deck.

* General: dark mode, the Source editor's tab width, the template single slides render with, how
  updates are handled and the GitHub token for them.
* AI models: the default model of each AI task (a local Ollama model or a Claude one).
* Cloud: "Local AI only" -- for every project, and this project's own override -- and the
  Anthropic API key, with where it is stored.
* Ollama: the server address and the installed models (update, delete): ui/dialogs/settings_ollama.py.
* Prompts: the system prompts of image descriptions, slide rewrite and translation:
  ui/dialogs/settings_prompts.py.

Every control applies when it changes and is saved at once, as before; only a prompt has its own
Save button, and closing the sheet asks about prompt text not yet saved. The model lists come from
Ollama and Claude on a thread, so opening the sheet never waits on the network;
the window refreshes the pickers that are open from `available_models` and `vision_models` when the
sheet closes with `loaded` set.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QMessageBox, QSpinBox, QWidget

from ... import app_settings, slide_snapshot, updater
from ...ai import credentials, resolver
from ...ai.providers import ANTHROPIC_FALLBACK_MODELS, AnthropicProvider, InstalledModel, OllamaProvider
from ...latex_edit import DEFAULT_TAB_WIDTH_CHARS, TAB_WIDTH_SETTING_KEY
from .. import background
from ..kit.widgets import Button, Field, ModalSheet, Page, SegmentedControl, caption, columns, row
from .settings_ollama import OllamaTab
from .settings_prompts import PromptsTab

GENERAL, MODELS, CLOUD, OLLAMA, PROMPTS = range(5)
TASKS = (
    ("syntax_check", "Syntax check"),
    ("ai_draft", "AI drafting"),
    ("image_description", "Image descriptions"),
    ("translation", "Translation"),
    ("chat", "Chat assistant"),
)
UPDATE_MODES = (
    (updater.UPDATE_MODE_OFF, "Off"), (updater.UPDATE_MODE_ASK, "Ask"), (updater.UPDATE_MODE_AUTO, "Automatic"))
UPDATE_NOTES = {
    updater.UPDATE_MODE_OFF: "SlideMage does not check for updates by itself. ⋮ → Check for updates… "
                             "always works.",
    updater.UPDATE_MODE_ASK: "Checked when SlideMage starts; a newer release is offered, and you decide "
                             "whether to install it.",
    updater.UPDATE_MODE_AUTO: "Checked when SlideMage starts; a newer release is installed automatically. "
                              "One that changes how SlideMage works is always asked about.",
}
PROJECT_CHOICES = (("follow", "Follow the global setting"), ("local", "Local AI only"), ("cloud", "Allow cloud models"))
PROJECT_OVERRIDES = {"follow": None, "local": True, "cloud": False}


class _ModelLoader(QThread):
    """The installed Ollama models and the Claude models on offer (the live list with a key, else the
    built-in one; none in local-only mode)."""

    loaded = Signal(object, object, object)       # this loader, [InstalledModel], [model id]

    def run(self) -> None:
        installed = OllamaProvider().installed()
        cloud = [] if resolver.local_only() else AnthropicProvider().list_models() or list(ANTHROPIC_FALLBACK_MODELS)
        self.loaded.emit(self, installed, cloud)


class GeneralTab(Page):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        layout = self.body

        self.dark_check = QCheckBox("Dark mode")
        self.dark_check.setChecked(app.theme.dark)
        self.dark_check.toggled.connect(app.set_dark_mode)
        self.tab_width_spin = QSpinBox()
        self.tab_width_spin.setRange(1, 16)
        self.tab_width_spin.setValue(app_settings.get(TAB_WIDTH_SETTING_KEY, DEFAULT_TAB_WIDTH_CHARS))
        self.tab_width_spin.valueChanged.connect(app.set_tab_width_chars)
        layout.addWidget(columns(Field("Appearance", self.dark_check), Field("Source editor tab width (characters)", self.tab_width_spin)))

        self.template_combo = QComboBox()
        current = slide_snapshot.render_template()
        for key in slide_snapshot.available_templates():
            self.template_combo.addItem(slide_snapshot.TEMPLATES[key], key)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(current), 0))
        self.template_combo.currentIndexChanged.connect(self._on_template)
        layout.addWidget(Field("Default template for slides rendered on their own", self.template_combo))
        layout.addWidget(caption(
            "Used by the slide's Render and Preview and by tikz illustration renders, outside a deck. A "
            "deck's own renders always use the deck's template."))

        self.update_mode = SegmentedControl(UPDATE_MODES, current=updater.get_update_mode())
        self.update_mode.changed.connect(self._on_update_mode)
        self.update_note = caption(UPDATE_NOTES[updater.get_update_mode()])
        layout.addWidget(Field("Updates", self.update_mode))
        layout.addWidget(self.update_note)

        self.token_edit = QLineEdit(updater.saved_token())
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("ghp_… (only needed while the repository is private)")
        self.token_edit.editingFinished.connect(self._on_token)
        self.token_show = QCheckBox("Show")
        self.token_show.toggled.connect(lambda shown: self.token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password))
        layout.addWidget(Field("GitHub token for update checks", row(self.token_edit, self.token_show)))
        note = f"Read access to {updater.REPO} is enough. Stored for your user account only, not in the project folder."
        if os.environ.get(updater.TOKEN_ENV_VAR):
            note += f" {updater.TOKEN_ENV_VAR} is set and takes precedence."
        layout.addWidget(caption(note))
        layout.addStretch(1)

    def _on_template(self, index: int) -> None:
        key = self.template_combo.itemData(index)
        if key:
            slide_snapshot.set_render_template(key)
            self.app.log(f"Default render template set to {slide_snapshot.TEMPLATES[key]}")

    def _on_update_mode(self, mode: str) -> None:
        try:
            updater.set_update_mode(mode)
        except OSError as exc:
            QMessageBox.warning(self, "Updates", f"Couldn't save the update setting: {exc}")
            return
        self.update_note.setText(UPDATE_NOTES[mode])
        self.app.log(f"Update mode set to {mode!r}")

    def _on_token(self) -> None:
        token = self.token_edit.text().strip()
        if token == updater.saved_token():
            return
        try:
            updater.save_token(token)
        except OSError as exc:
            QMessageBox.warning(self, "GitHub token", f"Couldn't save the token: {exc}")
            return
        self.app.log("GitHub token saved" if token else "GitHub token removed")


class ModelsTab(Page):
    def __init__(self) -> None:
        super().__init__()
        self.combos: dict[str, QComboBox] = {}
        layout = self.body
        layout.addWidget(caption(
            "The model each AI task starts on. Every model picker begins here; choosing another one in the "
            "picker applies to that use only. Claude models are listed unless \"Local AI only\" is on (Cloud tab); "
            "a picker offers them once an API key is set."))
        for start in range(0, len(TASKS), 2):
            fields = []
            for task, label in TASKS[start:start + 2]:
                combo = QComboBox()
                # A long model tag must not widen the whole sheet; the dropdown still shows full names.
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(16)
                if task == "image_description":
                    combo.setToolTip("Only vision-capable local models are listed.")
                combo.activated.connect(lambda i, t=task, c=combo: app_settings.set(
                    app_settings.MODEL_SETTINGS[t], c.itemData(i) or ""))       # "<provider>:<model>"
                self.combos[task] = combo
                fields.append(Field(label, combo))
            layout.addWidget(columns(*fields, *([QWidget()] * (2 - len(fields)))))   # an odd last row keeps its column
        self.unreachable = caption("")
        layout.addWidget(self.unreachable)
        layout.addStretch(1)

    def fill(self, local: list[str], vision: list[str], cloud: list[str]) -> None:
        """(Re)fill the pickers from the model lists, keeping each task's saved default selected --
        listed as "(not available)" rather than silently dropped when it is missing, so an unreachable
        Ollama never rewrites a setting."""
        for task, combo in self.combos.items():
            combo.clear()
            combo.addItem("(none chosen -- built-in fallback)", "")
            for model in vision if task == "image_description" else local:
                combo.addItem(model, f"ollama:{model}")
            for model in cloud:
                combo.addItem(f"{model} (cloud)", f"anthropic:{model}")
            saved = app_settings.default_model(task)
            if saved and combo.findData(saved) == -1:
                combo.addItem(f"{app_settings.split_spec(saved)[1]} (not available)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
        self.unreachable.setText(
            "" if local else f"Ollama is not reachable at {app_settings.get_ollama_host()}, or has no models installed.")
        self.unreachable.setVisible(not local)


class CloudTab(Page):
    cloud_changed = Signal()         # Local AI only or the API key changed: the model lists differ now

    def __init__(self) -> None:
        super().__init__()
        layout = self.body
        layout.addWidget(caption(
            "A cloud model (Claude) receives whatever its task sends: slide text, images. The first cloud "
            "request in a project asks for confirmation."))
        self.local_only_check = QCheckBox("Local AI only: never use a cloud model")
        self.local_only_check.setChecked(resolver.global_local_only())
        self.local_only_check.toggled.connect(self._on_local_only)
        layout.addWidget(Field("Every project", self.local_only_check))

        override = resolver.project_local_only()
        self.project_choice = SegmentedControl(
            PROJECT_CHOICES, current="follow" if override is None else "local" if override else "cloud")
        self.project_choice.changed.connect(self._on_project_choice)
        layout.addWidget(Field("This project", self.project_choice))
        self.project_note = caption("")
        layout.addWidget(self.project_note)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")
        save_key = Button("Save key", compact=True)
        save_key.clicked.connect(self._on_key_save)
        remove_key = Button("Remove key", compact=True)
        remove_key.clicked.connect(self._on_key_remove)
        layout.addWidget(Field("Anthropic API key", row(self.key_edit, save_key, remove_key)))
        self.key_status = caption("")
        layout.addWidget(self.key_status)
        layout.addStretch(1)
        self._refresh_notes()

    def _refresh_notes(self) -> None:
        key = credentials.get_api_key()
        if resolver.local_only():
            self.project_note.setText("Cloud models are off in this project.")
        else:
            self.project_note.setText(
                "Cloud models can be used in this project" + ("." if key else ", once an API key is set."))
        self.key_status.setText(self.key_message(key))

    @staticmethod
    def key_message(key: credentials.ApiKey | None) -> str:
        """Where the key in use lives, or where a key saved now would go."""
        keychain = credentials.keychain_available()
        if key is None:
            return "No API key set. " + (
                "A key you save is stored in the system keychain." if keychain else
                "A key you save is stored in the settings file (.slidemage/app_settings.json inside the project "
                "folder, which may be synced), because no system keychain is available. Install the optional "
                "'keyring' package to use it.")
        return {
            credentials.SOURCE_ENV: f"Using the key from the {credentials.ENV_VAR} environment variable "
                                    "(it takes precedence over a saved key).",
            credentials.SOURCE_KEYCHAIN: "Key stored in the system keychain.",
            credentials.SOURCE_FILE: "Key stored in the settings file (.slidemage/app_settings.json inside the "
                                     "project folder, which may be synced). " + (
                                         "Save it again to move it to the system keychain." if keychain else
                                         "Install the optional 'keyring' package to use the system keychain instead."),
        }[key.source]

    def _on_cloud_changed(self) -> None:
        self._refresh_notes()
        self.cloud_changed.emit()

    def _on_local_only(self, checked: bool) -> None:
        resolver.set_global_local_only(checked)
        self._on_cloud_changed()

    def _on_project_choice(self, key: str) -> None:
        resolver.set_project_local_only(PROJECT_OVERRIDES[key])
        self._on_cloud_changed()

    def _on_key_save(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            return
        self._store_key(key)

    def _on_key_remove(self) -> None:
        self._store_key("")

    def _store_key(self, key: str) -> None:
        try:
            credentials.set_api_key(key)
        except OSError as exc:
            QMessageBox.warning(self, "API key", f"Couldn't save the API key: {exc}")
            return
        self.key_edit.clear()
        self._on_cloud_changed()


class SettingsSheet(ModalSheet):
    def __init__(self, app, tab: int = GENERAL) -> None:
        """`app` is the window (its theme, tab width, log and the Ollama slot)."""
        super().__init__("Settings", app, width=760)
        self.app = app
        self.available_models: list[str] = []
        self.vision_models: list[str] = []
        self.loaded = False
        self._loader: QThread | None = None
        self._reload_pending = False
        self.general = GeneralTab(app)
        self.models = ModelsTab()
        self.cloud = CloudTab()
        self.ollama = OllamaTab(app)
        self.prompts = PromptsTab(app)
        for label, tab_widget in (("General", self.general), ("AI models", self.models), ("Cloud", self.cloud),
                                  ("Ollama", self.ollama), ("Prompts", self.prompts)):
            self.add_tab(label, tab_widget)
        self.add_button("Close", kind="primary", role="accept")
        self.cloud.cloud_changed.connect(self.reload_models)
        self.ollama.changed.connect(self.reload_models)
        self.set_current_tab(tab)
        self.reload_models()

    def reload_models(self) -> None:
        """Ask Ollama and Claude again; while a request is out, the next one waits for its answer."""
        if self._loader is not None:
            self._reload_pending = True
            return
        loader = _ModelLoader()
        loader.loaded.connect(self._on_models)
        self._loader = loader
        background.start_detached(loader)

    def _on_models(self, loader: QThread, installed: list[InstalledModel], cloud: list[str]) -> None:
        if loader is not self._loader:
            return
        self.available_models = [model.name for model in installed]
        self.vision_models = [model.name for model in installed if "vision" in model.capabilities]
        self._loader = None
        self.loaded = True
        self.models.fill(self.available_models, self.vision_models, cloud)
        self.ollama.fill(installed)
        self.prompts.translation.set_models(self.available_models)
        if self._reload_pending:
            self._reload_pending = False
            self.reload_models()

    def done(self, result: int) -> None:
        """Closing asks first about prompt text that is not saved."""
        if self.prompts.confirm_close():
            self._loader = None          # a late answer is not for this sheet any more
            self._reload_pending = False
            super().done(result)
