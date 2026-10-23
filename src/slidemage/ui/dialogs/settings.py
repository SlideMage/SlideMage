# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings sheet (UI_REDESIGN_PLAN.md, step 9): the preferences that are not about one deck.

* General: dark mode, the Source editor's tab width, live rendering after an autosave, whether leaving a changed slide asks
  about Update Version, the template single slides render with, when single-slide renders are deleted, how updates are
  handled and the GitHub token for them.
* AI: how Claude Code translations address the audience in German (this project's `de_address`;
  ai/translation_style.py) and the glossary. The model of each AI task on each side, what Cloud means and the
  project's Local | Cloud setting are not here: they are AI setup, the ▾ of the AI switch at the top of the
  assistant (workspace/ai_setup.py).
* Cloud: the Anthropic API key, with where it is stored.
* Ollama: the server address and the installed models (update, delete): ui/dialogs/settings_ollama.py.
* Prompts: the system prompts of image descriptions and translation:
  ui/dialogs/settings_prompts.py.
* Presentation: layout, laser and pen colours, links, timer and clock, projector screen:
  ui/presentation/settings_page.py.
* Project: the .bib file and test-slides.tex (Edit opens them in Source), the project compatibility check and the
  project's deck groups (ui/dialogs/settings_deck_groups.py; `SettingsSheet(app, PROJECT, focus=DECK_GROUPS)`, the
  window's `open_deck_groups()`).
* About: the version, the version history and the check for updates.
The buttons of Project and About close the sheet first, then run their window command (`after`: the window runs
it when the sheet has closed).

Every control applies when it changes and is saved at once, as before; only a prompt has its own
Save button, and closing the sheet asks about prompt text not yet saved. The installed Ollama models come
from Ollama on a thread, so opening the sheet never waits on the network; the window refreshes the pickers
that are open from `installed` when the sheet closes with `loaded` set.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QMessageBox, QSpinBox, QWidget

from ... import app_settings, slide_preview, slide_snapshot, slide_versioning, updater, version
from ...ai import credentials, translation_style
from ...ai.providers import InstalledModel, OllamaProvider
from ...latex_edit import DEFAULT_TAB_WIDTH_CHARS, TAB_WIDTH_SETTING_KEY
from ...project import ProjectContext
from .. import background
from ..ai_models import add_route_badge
from ..kit.widgets import Button, Field, ModalSheet, Page, SegmentedControl, action_row, caption, columns, row
from ..workspace.source_file import autosave_on
from .settings_deck_groups import DeckGroupsSection
from .settings_ollama import OllamaTab
from ..presentation.settings_page import PresentationTab
from .settings_prompts import PromptsTab

GENERAL, AI, CLOUD, OLLAMA, PROMPTS, PRESENTATION, PROJECT, ABOUT = range(8)
DECK_GROUPS = "deck_groups"       # a `focus` of the sheet: the Project tab with its deck groups list focused
LIVE_RENDER_SETTING_KEY = "live_render_on_autosave"    # app_settings: render the Preview after each autosave
UPDATE_MODES = (
    (updater.UPDATE_MODE_OFF, "Off"), (updater.UPDATE_MODE_ASK, "Ask"), (updater.UPDATE_MODE_AUTO, "Automatic"))
UPDATE_NOTES = {
    updater.UPDATE_MODE_OFF: "SlideMage does not check for updates by itself. Help → Check for updates… "
                             "always works.",
    updater.UPDATE_MODE_ASK: "Checked when SlideMage starts; a newer release is offered, and you decide "
                             "whether to install it.",
    updater.UPDATE_MODE_AUTO: "Checked when SlideMage starts; a newer release is installed automatically. "
                              "One that changes how SlideMage works is always asked about.",
}


class _ModelLoader(QThread):
    """The installed Ollama models."""

    loaded = Signal(object, object)       # this loader, [InstalledModel]

    def __init__(self, project: ProjectContext) -> None:
        super().__init__()
        self.project = project

    def run(self) -> None:
        self.loaded.emit(self, OllamaProvider.for_project(self.project).installed(detailed=True))


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
        self.tab_width_spin.setValue(app_settings.get(app.project, TAB_WIDTH_SETTING_KEY, DEFAULT_TAB_WIDTH_CHARS))
        self.tab_width_spin.valueChanged.connect(app.set_tab_width_chars)
        layout.addWidget(columns(Field("Appearance", self.dark_check), Field("Source editor tab width (characters)", self.tab_width_spin)))

        self.autosave_check = QCheckBox("Save edits as you type (AutoSave)")
        self.autosave_check.setChecked(autosave_on())
        self.autosave_check.toggled.connect(app.set_autosave)
        layout.addWidget(Field("Saving", self.autosave_check))
        layout.addWidget(caption("Off, a file is saved with Ctrl+S; its edits stay in the editor until then, and "
                                 "leaving them is asked about. The same switch is in the top bar."))

        self.live_render_check = QCheckBox("Render the Preview after each autosave")
        self.live_render_check.setChecked(bool(app_settings.get(app.project, LIVE_RENDER_SETTING_KEY, False)))
        self.live_render_check.toggled.connect(
            lambda on: app_settings.set(app.project, LIVE_RENDER_SETTING_KEY, bool(on)))
        layout.addWidget(Field("Live preview", self.live_render_check))
        layout.addWidget(caption(
            "While you type in the Source view, the slide is rendered again a moment after each autosave, "
            "when the Preview or Split view is showing it and its source has no errors. Off by default: "
            "each render is a LaTeX run."))

        self.ask_version_check = QCheckBox("Ask about Update version when leaving a changed slide")
        self.ask_version_check.setChecked(
            bool(app_settings.get(app.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY, False)))
        self.ask_version_check.toggled.connect(
            lambda on: app_settings.set(app.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY, bool(on)))
        layout.addWidget(Field("Versions", self.ask_version_check))
        layout.addWidget(caption(
            "When you switch to another slide after editing one in the Source view, and it shows a \"+\" "
            "(changed since its last version), SlideMage asks whether to make the changes a version now. "
            "Off by default: your edits are saved either way."))

        self.template_combo = QComboBox()
        current = slide_snapshot.render_template(self.app.project)
        for key in slide_snapshot.available_templates(self.app.project.root):
            self.template_combo.addItem(slide_snapshot.template_label(key, self.app.project.root), key)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(current), 0))
        self.template_combo.currentIndexChanged.connect(self._on_template)
        layout.addWidget(Field("Default template for slides rendered on their own", self.template_combo))
        layout.addWidget(caption(
            "Used by the slide's Render and Preview and by tikz illustration renders, outside a deck. A "
            "deck's own renders always use the deck's template."))

        self.cleanup_combo = QComboBox()
        for hours, label in slide_preview.RENDER_CLEANUP_CHOICES:
            self.cleanup_combo.addItem(label, hours)
        current_hours = slide_preview.render_cleanup_hours(app.project)
        if self.cleanup_combo.findData(current_hours) < 0:      # a value set by hand in app_settings.json
            self.cleanup_combo.addItem(f"After {current_hours} hours", current_hours)
        self.cleanup_combo.setCurrentIndex(self.cleanup_combo.findData(current_hours))
        self.cleanup_combo.currentIndexChanged.connect(self._on_cleanup)
        layout.addWidget(Field("Delete single-slide renders", self.cleanup_combo))
        layout.addWidget(caption(
            "Every Render of a single slide leaves a PDF in a folder of its own in the temporary folder. SlideMage "
            "deletes those that are older than this when it starts and after each render; Never keeps them."))

        self._add_background_previews(layout)

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
            slide_snapshot.set_render_template(self.app.project, key)
            self.app.log(f"Default render template set to {slide_snapshot.template_label(key, self.app.project.root)}")

    def _add_background_previews(self, layout) -> None:
        """Prepare previews in the background: on/off, only on mains power, speed, disk limit, clear."""
        from ... import background_renders as bg

        project = self.app.project
        self.bg_check = QCheckBox("Prepare previews in the background when SlideMage is idle")
        self.bg_check.setChecked(bool(app_settings.get(project, bg.ENABLED_KEY, True)))
        self.bg_mains_check = QCheckBox("Only when plugged in")
        self.bg_mains_check.setChecked(bool(app_settings.get(project, bg.ONLY_MAINS_KEY, True)))
        self.bg_profile = QComboBox()
        def at_once(key: str) -> str:
            count = bg.PROFILES[key][0]
            return "one at a time" if count == 1 else f"up to {count} at once"
        for key, label in (("gentle", f"Gentle ({at_once('gentle')}, long rests)"),
                           ("normal", f"Normal ({at_once('normal')}, short rests)"),
                           ("fast", f"Fast ({at_once('fast')})")):
            self.bg_profile.addItem(label, key)
        self.bg_profile.setToolTip("Each render beyond the first starts only while the processor is less than "
                                   f"{round(bg.CPU_LIMIT * 100)}% busy. Background renders, reveal steps and "
                                   "\"Rerender all\" share one limit, so together they never run more than "
                                   f"{bg.PROFILES['fast'][0]} at once; your own render never waits.")
        self.bg_profile.setCurrentIndex(max(self.bg_profile.findData(app_settings.get(project, bg.PROFILE_KEY, bg.DEFAULT_PROFILE)), 0))
        self.bg_limit = QDoubleSpinBox()
        self.bg_limit.setRange(0.1, 500.0)
        self.bg_limit.setDecimals(1)
        self.bg_limit.setSuffix(" GB")
        self.bg_limit.setValue(float(app_settings.get(project, bg.LIMIT_GB_KEY, bg.DEFAULT_LIMIT_GB)))
        self.bg_clear = Button("Clear background previews")
        for control, apply in ((self.bg_check, lambda on: app_settings.set(project, bg.ENABLED_KEY, bool(on))),
                               (self.bg_mains_check, lambda on: app_settings.set(project, bg.ONLY_MAINS_KEY, bool(on)))):
            control.toggled.connect(lambda on, apply=apply: (apply(on), self._background_changed()))
        self.bg_profile.currentIndexChanged.connect(
            lambda _i: (app_settings.set(project, bg.PROFILE_KEY, self.bg_profile.currentData()), self._background_changed()))
        self.bg_limit.editingFinished.connect(
            lambda: (app_settings.set(project, bg.LIMIT_GB_KEY, float(self.bg_limit.value())), self._background_changed()))
        self.bg_clear.clicked.connect(self._clear_background)
        layout.addWidget(Field("Background previews", row(self.bg_check, self.bg_mains_check)))
        layout.addWidget(columns(Field("Speed", self.bg_profile), Field("Disk limit", self.bg_limit)))
        layout.addWidget(row(self.bg_clear))
        self.bg_caption = caption("")
        layout.addWidget(self.bg_caption)
        layout.addWidget(caption(
            "When you switch to another window, or leave SlideMage untouched for a minute, it renders the slides of "
            "your decks, with all their "
            "reveal steps, most recently used decks first and the instructor version first, so they are ready when you "
            "open them. Coming back to SlideMage stops it at once, and it never runs during a presentation. The previews are kept on this computer, outside the project folder (so the sync never carries them); "
            "a deck can be left out in the chip that shows the progress."))
        self._background_size()

    def _background_controller(self):
        return getattr(self.app, "background", None)

    def _background_changed(self) -> None:
        controller = self._background_controller()
        if controller is not None:
            controller.settings_changed()

    def _background_size(self) -> None:
        controller = self._background_controller()
        store = getattr(controller, "store", None)
        self.bg_caption.setText("" if store is None else f"{store.count()} renders stored, {store.total_bytes() / 1024 ** 2:.0f} MB.")

    def _clear_background(self) -> None:
        controller = self._background_controller()
        if controller is None or controller.store is None:
            return
        if QMessageBox.question(self, "Clear background previews", "Delete all prepared previews? They are rendered again "
                                "when SlideMage is idle.") != QMessageBox.StandardButton.Yes:
            return
        controller.store.clear()
        controller.renderer.replan()
        self._background_size()

    def _on_cleanup(self, index: int) -> None:
        hours = self.cleanup_combo.itemData(index)
        if hours is None:
            return
        app_settings.set(self.app.project, slide_preview.RENDER_CLEANUP_SETTING_KEY, int(hours))
        self.app.log(f"Single-slide renders: {self.cleanup_combo.itemText(index).lower()}")

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


class AiTab(Page):
    """The AI settings that AI setup does not have."""

    def __init__(self, project: ProjectContext) -> None:
        super().__init__()
        layout = self.body
        layout.addWidget(caption(
            "The model of each AI task, what Cloud means and the project's Local | Cloud setting are in AI setup, "
            "the ▾ of the Local | Cloud switch at the top of the assistant."))
        self.address = SegmentedControl(tuple((a, a) for a in translation_style.ADDRESSES),
                                        current=translation_style.de_address(project))
        self.address.changed.connect(lambda value: translation_style.set_de_address(project, value))
        layout.addWidget(Field("German address in Claude Code translations (this project)", self.address))
        layout.addWidget(caption(
            f"Put terms that must be translated one way in {translation_style.GLOSSARY_PATH}, one \"English = "
            "German\" per line; every translation request carries the file as it is."))
        layout.addStretch(1)


class CloudTab(Page):
    cloud_changed = Signal()         # the API key changed: the models on offer differ now

    def __init__(self, project: ProjectContext) -> None:
        super().__init__()
        self.project = project
        layout = self.body
        layout.addWidget(caption(
            "A cloud route (Claude Code or the Anthropic API) receives whatever its task sends: slide text, images, "
            "notes. Which side the project uses is the Local | Cloud switch at the top of the assistant; what Cloud means (Claude Code or the "
            "Anthropic API) and the project's own setting are in AI setup, its ▾."))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")
        save_key = Button("Save key", compact=True)
        save_key.clicked.connect(self._on_key_save)
        remove_key = Button("Remove key", compact=True)
        remove_key.clicked.connect(self._on_key_remove)
        layout.addWidget(Field("Anthropic API key", row(self.key_edit, save_key, remove_key)))
        self.key_status = caption(self.key_message(credentials.get_api_key(project)))
        layout.addWidget(self.key_status)
        layout.addStretch(1)

    @staticmethod
    def key_message(key: credentials.ApiKey | None) -> str:
        """Where the key in use lives, or where a key saved now would go."""
        keychain = credentials.keychain_available()
        if key is None:
            return "No API key set. " + (
                "A key you save is stored in the system keychain." if keychain else
                "A key you save is stored in SlideMage's settings file on this computer (ai_settings.json, "
                "outside the project), because no system keychain is available. Install the optional "
                "'keyring' package to use it.")
        return {
            credentials.SOURCE_ENV: f"Using the key from the {credentials.ENV_VAR} environment variable "
                                    "(it takes precedence over a saved key).",
            credentials.SOURCE_KEYCHAIN: "Key stored in the system keychain.",
            credentials.SOURCE_FILE: "Key stored in SlideMage's settings file on this computer (ai_settings.json, "
                                     "outside the project). " + (
                                         "Save it again to move it to the system keychain." if keychain else
                                         "Install the optional 'keyring' package to use the system keychain instead."),
        }[key.source]

    def _on_cloud_changed(self) -> None:
        self.key_status.setText(self.key_message(credentials.get_api_key(self.project)))
        self.cloud_changed.emit()

    def _on_key_save(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            return
        self._store_key(key)

    def _on_key_remove(self) -> None:
        self._store_key("")

    def _store_key(self, key: str) -> None:
        try:
            credentials.set_api_key(self.project, key)
        except OSError as exc:
            QMessageBox.warning(self, "API key", f"Couldn't save the API key: {exc}")
            return
        self.key_edit.clear()
        self._on_cloud_changed()


def _command_row(app, leave, command_id: str, title: str, note: str, text: str, *,
                 enabled: bool = True) -> tuple[QWidget, Button]:
    """A row whose button closes the sheet (`leave`), then runs the window command `command_id`."""
    button = Button(text, compact=True)
    button.setEnabled(enabled)
    button.clicked.connect(lambda: leave(partial(app.commands.run, command_id, app)))
    return action_row(title, note, button), button


class ProjectTab(Page):
    """The project's .bib file and test slides, which open in Source, its compatibility check and its deck
    groups."""

    def __init__(self, app, leave) -> None:
        super().__init__()
        layout = self.body
        self.edit_buttons: dict[str, Button] = {}
        for key, title, path, command_id in (
                ("bib", "Bibliography file", app.project.bibliography_path, "edit_bib"),
                ("test_slides", "Test slides", app.project.test_slides_path, "edit_test_slides")):
            found = path.is_file()
            line, self.edit_buttons[key] = _command_row(
                app, leave, command_id, title, path.name if found else f"{path.name} — not found", "Edit",
                enabled=found)
            layout.addWidget(line)
        layout.addWidget(_command_row(
            app, leave, "project_compat", "Project compatibility",
            "Whether this project's files fit this version of SlideMage.", "Check…")[0])
        self.deck_groups = DeckGroupsSection(app)
        layout.addWidget(self.deck_groups)
        layout.addStretch(1)


class AboutTab(Page):
    """The version, its history and the update check."""

    def __init__(self, app, leave) -> None:
        super().__init__()
        layout = self.body
        layout.addWidget(Field("Version", QLabel(f"SlideMage {version.VERSION_NUMBER}")))
        layout.addWidget(_command_row(
            app, leave, "version_history", "Version history", "What changed in each release; the license is there too.",
            "Open…")[0])
        layout.addWidget(_command_row(
            app, leave, "check_updates", "Check for updates", "Look for a newer release now.", "Check…")[0])
        layout.addStretch(1)


class SettingsSheet(ModalSheet):
    def __init__(self, app, tab: int = GENERAL, *, focus: str | None = None) -> None:
        """`app` is the window (its theme, tab width, log, the Ollama slot and its decks). `focus` DECK_GROUPS
        opens the Project tab at its deck groups."""
        super().__init__("Settings", app, width=760)
        self.app = app
        add_route_badge(self, app)
        self.installed: list[InstalledModel] = []       # what Ollama has, once `loaded`
        self.loaded = False
        self._loader: QThread | None = None
        self._reload_pending = False
        self.general = GeneralTab(app)
        self.ai = AiTab(app.project)
        self.cloud = CloudTab(app.project)
        self.ollama = OllamaTab(app)
        self.prompts = PromptsTab(app)
        self.presentation = PresentationTab()
        self.after: Callable[[], None] | None = None     # what the window runs once the sheet has closed
        self.project_tab = ProjectTab(app, self.close_then)
        self.about = AboutTab(app, self.close_then)
        for label, tab_widget in (("General", self.general), ("AI", self.ai), ("Cloud", self.cloud),
                                  ("Ollama", self.ollama), ("Prompts", self.prompts),
                                  ("Presentation", self.presentation), ("Project", self.project_tab),
                                  ("About", self.about)):
            self.add_tab(label, tab_widget)
        self.add_button("Close", kind="primary", role="accept")
        self.cloud.cloud_changed.connect(self.reload_models)
        self.ollama.changed.connect(self.reload_models)
        self.set_current_tab(PROJECT if focus == DECK_GROUPS else tab)
        if focus == DECK_GROUPS:
            self.project_tab.deck_groups.list.setFocus()
        self.reload_models()

    def reload_models(self) -> None:
        """Ask Ollama again; while a request is out, the next one waits for its answer."""
        if self._loader is not None:
            self._reload_pending = True
            return
        loader = _ModelLoader(self.app.project)
        loader.loaded.connect(self._on_models)
        self._loader = loader
        background.start_detached(loader)

    def _on_models(self, loader: QThread, installed: list[InstalledModel]) -> None:
        if loader is not self._loader:
            return
        self.installed = installed
        self._loader = None
        self.loaded = True
        self.ollama.fill(installed)
        self.prompts.translation.set_models([model.name for model in installed])
        if self._reload_pending:
            self._reload_pending = False
            self.reload_models()

    def close_then(self, action: Callable[[], None]) -> None:
        """Close the sheet, and let the window run `action` after it (the sheet is modal)."""
        self.after = action
        self.accept()

    def done(self, result: int) -> None:
        """Closing asks first about prompt text that is not saved."""
        if self.prompts.confirm_close():
            self._loader = None          # a late answer is not for this sheet any more
            self._reload_pending = False
            super().done(result)
        else:
            self.after = None
