"""The Settings sheet: each tab's controls, what they save, and what changes live (the theme, the tab
width, the model pickers). Ollama and Claude are fakes; nothing here touches the network."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from slidemage import ai_draft, alt_draft, app_settings, draft_prompts, slide_snapshot, updater
from slidemage import translation_prompts as tp
from slidemage.ai import credentials, ollama_admin, resolver
from slidemage.ai.providers import ANTHROPIC_FALLBACK_MODELS, AnthropicProvider, InstalledModel, OllamaProvider
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.dialogs.settings import CLOUD, GENERAL, MODELS, OLLAMA, PROMPTS, SettingsSheet
from test_templates import _framework, _project

INSTALLED = [InstalledModel("general-text", 2_000_000_000, ""), InstalledModel("translator", 1_000_000, ""),
             InstalledModel("vision", 7_000_000_000, "", ("vision",)), InstalledModel("vision-2", 5_000_000, "", ("vision",))]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeApp(QWidget):
    """The window as far as Settings uses it."""

    def __init__(self):
        super().__init__()
        self.theme = ThemeManager()
        self.calls, self.logged, self.slots, self.slot_free = [], [], [], True
        self.set_dark_mode = lambda value: self.calls.append(("dark", value))
        self.set_tab_width_chars = lambda value: self.calls.append(("tab width", value))
        self.log = self.logged.append
        self.signals = SimpleNamespace(log=SimpleNamespace(emit=self.logged.append))

    def try_start_ollama_task(self, label, provider=None):
        if self.slot_free:
            self.slots.append(label)
        return self.slot_free

    def end_ollama_task(self, provider=None):
        self.slots.append("end")


@pytest.fixture(autouse=True)
def fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(OllamaProvider, "installed", lambda self: list(INSTALLED))
    monkeypatch.setattr(AnthropicProvider, "list_models", lambda self: [])


def loaded(sheet, qapp):
    """The sheet once the model lists the thread fetched have arrived."""
    sheet._loader.wait()
    qapp.processEvents()
    assert sheet.loaded
    return sheet


def open_sheet(qapp, app=None, tab=GENERAL):
    app = app or FakeApp()
    sheet = SettingsSheet(app, tab=tab)
    sheet.app = app
    return loaded(sheet, qapp)


def tab_names(sheet):
    return [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]


def answer(monkeypatch, button_text):
    """Make the next unsaved-changes question be answered with the button of that text."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(
        b for b in self.buttons() if b.text().replace("&", "") == button_text))


def wait_for(qapp, condition):
    deadline = time.time() + 5
    while not condition() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert condition()


# -- the sheet ---------------------------------------------------------------------------------

def test_the_sheet_has_a_tab_for_each_group_of_settings_and_a_sensible_width(qapp):
    sheet = open_sheet(qapp)
    assert tab_names(sheet) == ["General", "AI models", "Cloud", "Ollama", "Prompts"]
    sheet.show()
    qapp.processEvents()
    assert sheet.width() < 1000            # unwrapped notes once made this ~2200 px wide
    sheet.close()


def test_a_tab_can_be_opened_first(qapp):
    assert open_sheet(qapp, tab=OLLAMA).current_tab() == OLLAMA


# -- General -----------------------------------------------------------------------------------

def test_dark_mode_and_tab_width_reach_the_window_as_they_change(qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app)
    sheet.general.dark_check.setChecked(not app.theme.dark)
    sheet.general.tab_width_spin.setValue(8)
    assert app.calls == [("dark", not app.theme.dark), ("tab width", 8)]


def test_the_render_template_offers_the_project_templates_and_saves_the_choice(tmp_path, monkeypatch, qapp):
    _framework(tmp_path / "latex", "slidemage")
    monkeypatch.setattr(slide_snapshot, "PROJECT_ROOT", _project(tmp_path / "project", "uni-graz", "uni-ibk", "mci"))
    app = FakeApp()
    sheet = open_sheet(qapp, app)
    combo = sheet.general.template_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["uni-graz", "uni-ibk", "mci", "slidemage"]
    assert combo.currentData() == "slidemage"           # out of the box
    combo.setCurrentIndex(combo.findData("mci"))
    assert app_settings.get(slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == "mci"
    assert slide_snapshot.render_template() == "mci"
    assert "Default render template set to Mci" in app.logged[-1]


def test_the_update_mode_and_the_github_token_are_saved_when_changed(qapp):
    sheet = open_sheet(qapp)
    general = sheet.general
    assert general.update_mode.current() == updater.UPDATE_MODE_ASK and updater.get_update_mode() == "ask"
    general.update_mode.changed.emit(updater.UPDATE_MODE_AUTO)
    assert updater.get_update_mode() == "auto" and "installed automatically" in general.update_note.text()
    general.update_mode.changed.emit(updater.UPDATE_MODE_OFF)
    assert updater.get_update_mode() == "off" and "does not check" in general.update_note.text()

    general.token_edit.setText(" ghp_fake ")
    general.token_edit.editingFinished.emit()
    assert updater.saved_token() == "ghp_fake"
    general.token_edit.setText("")
    general.token_edit.editingFinished.emit()
    assert updater.saved_token() == ""
    general.token_show.setChecked(True)
    assert general.token_edit.echoMode().name == "Normal"


# -- AI models ---------------------------------------------------------------------------------

def choose(sheet, task, model):
    combo = sheet.models.combos[task]
    index = combo.findData(f"ollama:{model}")
    assert index != -1, (task, model)
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def test_the_pickers_list_the_installed_models_and_keep_a_default_that_is_missing(qapp):
    app_settings.set(app_settings.MODEL_SETTINGS["translation"], "ollama:gone")
    sheet = open_sheet(qapp)
    assert sheet.available_models == [m.name for m in INSTALLED]
    assert sheet.vision_models == ["vision", "vision-2"]
    # Image descriptions offer vision models among the local ones; the cloud list is the built-in one.
    image = sheet.models.combos["image_description"]
    assert [image.itemData(i) for i in range(image.count())] == [
        "", "ollama:vision", "ollama:vision-2", *(f"anthropic:{m}" for m in ANTHROPIC_FALLBACK_MODELS)]
    translation = sheet.models.combos["translation"]
    assert translation.currentData() == "ollama:gone" and translation.currentText() == "gone (not available)"
    assert app_settings.default_model("translation") == "ollama:gone"      # an unreachable model never rewrites it


def test_an_unreachable_ollama_is_said_and_costs_no_setting(monkeypatch, qapp):
    monkeypatch.setattr(OllamaProvider, "installed", lambda self: [])
    sheet = open_sheet(qapp)
    assert not sheet.models.unreachable.isHidden() and "not reachable" in sheet.models.unreachable.text()
    assert not sheet.ollama.models_list.isEnabled() and not sheet.ollama.delete_button.isEnabled()


def test_choosing_a_default_saves_it_for_that_task_only(qapp):
    sheet = open_sheet(qapp)
    choose(sheet, "syntax_check", "general-text")
    choose(sheet, "image_description", "vision-2")
    cloud = sheet.models.combos["ai_draft"]
    cloud.setCurrentIndex(cloud.findData(f"anthropic:{ANTHROPIC_FALLBACK_MODELS[0]}"))
    cloud.activated.emit(cloud.currentIndex())
    assert app_settings.default_model("syntax_check") == "ollama:general-text"
    assert app_settings.default_model("image_description") == "ollama:vision-2"
    assert app_settings.default_model("ai_draft") == f"anthropic:{ANTHROPIC_FALLBACK_MODELS[0]}"
    assert app_settings.default_model("translation") == ""


def test_per_task_defaults_reach_the_open_pickers_when_the_sheet_closes(tmp_path, monkeypatch, qapp):
    from slidemage.qt_ai_draft_dialog import AiDraftDialog
    from slidemage.ui.pages.images import ImagesPage
    from slidemage.syntax_check import SyntaxCheckResult
    from slidemage.ui.workspace import ai_fix
    from slidemage.ui.workspace import window as window_module
    from slidemage.ui.workspace.source_file import SourceFile
    from PySide6.QtWidgets import QComboBox

    app = FakeApp()
    sheet = open_sheet(qapp, app)
    choose(sheet, "syntax_check", "general-text")
    choose(sheet, "ai_draft", "translator")
    choose(sheet, "image_description", "vision-2")
    choose(sheet, "translation", "translator")
    app_settings.set_ollama_host("http://ollama.example:11434")

    (tmp_path / "slide.tex").write_text("slide text", encoding="utf-8")
    file = SourceFile(app, tmp_path / "slide.tex")       # holds the open "Ask AI to fix" panel
    requests = []

    class Checker:
        def __init__(self, provider):
            requests.append((provider.model, provider.host))

        def check(self, _text):
            return SyntaxCheckResult(model="general-text")

    monkeypatch.setattr(ai_fix.syntax_check, "SyntaxChecker", Checker)
    syntax = file.fix_panel
    syntax.run_check()
    if syntax._worker is not None:
        syntax._worker.wait()
    qapp.processEvents()
    draft = AiDraftDialog(app, file.editor, "slide.tex")
    assert syntax.model_combo.currentText() == "general-text"
    assert draft.model_combo.currentText() == "translator"
    assert requests == [("general-text", "http://ollama.example:11434")]

    tab = SimpleNamespace(draft_model=QComboBox(), translate_model=QComboBox(), _update_buttons=lambda: None)
    ImagesPage.refresh_model_preferences(tab)
    assert tab.draft_model.currentText() == "vision-2" and tab.translate_model.currentText() == "translator"

    # Picking another model in a dialog applies to that dialog only.
    draft.model_combo.setCurrentText("vision")
    draft.model_combo.activated.emit(draft.model_combo.currentIndex())
    assert app_settings.default_model("ai_draft") == "ollama:translator"

    # A default changed in Settings reaches the open pickers from the sheet's own model lists.
    choose(sheet, "syntax_check", "vision")
    choose(sheet, "ai_draft", "general-text")
    choose(sheet, "image_description", "vision")
    file.ai_dialog = draft
    app.centre = SimpleNamespace(refresh_model_preferences=file.refresh_model_preference)
    app.assistant = SimpleNamespace(chat=SimpleNamespace(refresh_route=lambda: None))

    class OpenImages:
        refresh_model_preferences = ImagesPage.refresh_model_preferences

        def __init__(self):
            self.draft_model = QComboBox()
            self.translate_model = QComboBox()
            self._update_buttons = lambda: None

    app.images_page = OpenImages()
    monkeypatch.setattr(window_module, "SettingsSheet", lambda _app: sheet)
    monkeypatch.setattr(sheet, "exec", lambda: None)

    def no_network():
        raise AssertionError("refresh should use the sheet's model lists")

    monkeypatch.setattr(OllamaProvider, "list_models", no_network)
    monkeypatch.setattr(OllamaProvider, "installed", no_network)

    window_module.WorkspaceWindow._on_open_settings(app)
    assert syntax.model_combo.currentText() == "vision"
    assert draft.model_combo.currentText() == "general-text"
    assert app.images_page.draft_model.currentText() == "vision"
    assert app.images_page.translate_model.currentText() == "translator"


def test_a_sheet_closed_before_the_models_arrived_refreshes_nothing(monkeypatch, qapp):
    from slidemage.ui.workspace import window as window_module

    sheet = SettingsSheet(FakeApp())
    loader = sheet._loader
    sheet.reject()                                  # closed at once
    loader.wait()
    qapp.processEvents()                            # its answer arrives to nobody
    assert not sheet.loaded and sheet.available_models == []

    refreshed = []
    app = SimpleNamespace(
        images_page=SimpleNamespace(refresh_model_preferences=lambda *args: refreshed.append(args)),
        centre=SimpleNamespace(refresh_model_preferences=lambda *args: refreshed.append(args)))
    monkeypatch.setattr(window_module, "SettingsSheet", lambda _app: SimpleNamespace(exec=lambda: 0, loaded=False))
    window_module.WorkspaceWindow._on_open_settings(app)
    assert refreshed == []


def test_a_reload_while_one_is_running_waits_for_its_answer_instead_of_stacking(qapp):
    sheet = SettingsSheet(FakeApp())
    first = sheet._loader
    sheet.reload_models()
    sheet.reload_models()
    assert sheet._loader is first and sheet._reload_pending      # no second loader yet
    first.wait()
    qapp.processEvents()                                         # the answer arrives and starts the rerun
    second = sheet._loader
    assert second is not None and second is not first and not sheet._reload_pending
    loaded(sheet, qapp)
    assert sheet.available_models == [m.name for m in INSTALLED] and sheet._loader is None


def test_an_answer_that_is_not_the_current_loaders_is_dropped(qapp):
    sheet = open_sheet(qapp)
    sheet._on_models(object(), [InstalledModel("stale", 1, "")], [])
    assert "stale" not in sheet.available_models


# -- Cloud -------------------------------------------------------------------------------------

class FakeKeyring:
    """A keychain; `usable=False` is keyring's `fail` backend."""

    def __init__(self, usable=True):
        self.store, self.priority = {}, 5 if usable else 0

    def get_keyring(self):
        return self

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        if self.priority == 0:
            raise RuntimeError("no backend")
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


def test_local_only_hides_the_cloud_models_at_once(qapp):
    sheet = open_sheet(qapp, tab=CLOUD)
    cloud = sheet.cloud
    assert not cloud.local_only_check.isChecked()
    translation = sheet.models.combos["translation"]
    assert translation.findData(f"anthropic:{ANTHROPIC_FALLBACK_MODELS[0]}") != -1

    cloud.local_only_check.setChecked(True)
    assert resolver.global_local_only() and "off in this project" in cloud.project_note.text()
    loaded(sheet, qapp)
    assert [translation.itemData(i) for i in range(translation.count())] == ["", *(f"ollama:{m.name}" for m in INSTALLED)]

    cloud.local_only_check.setChecked(False)
    loaded(sheet, qapp)
    assert translation.findData(f"anthropic:{ANTHROPIC_FALLBACK_MODELS[0]}") != -1


def test_this_project_can_override_the_global_switch_either_way(qapp):
    sheet = open_sheet(qapp, tab=CLOUD)
    cloud = sheet.cloud
    assert cloud.project_choice.current() == "follow" and resolver.project_local_only() is None
    cloud.project_choice.changed.emit("local")
    assert resolver.project_local_only() is True and resolver.local_only()
    assert "off in this project" in cloud.project_note.text()
    resolver.set_global_local_only(True)
    cloud.project_choice.changed.emit("cloud")
    assert resolver.project_local_only() is False and not resolver.local_only()
    assert "once an API key is set" in cloud.project_note.text()
    cloud.project_choice.changed.emit("follow")
    assert resolver.project_local_only() is None and resolver.local_only()      # the global switch again


def test_the_override_of_a_project_is_shown_when_the_sheet_opens(qapp):
    resolver.set_project_local_only(False)
    assert open_sheet(qapp).cloud.project_choice.current() == "cloud"
    resolver.set_project_local_only(True)
    assert open_sheet(qapp).cloud.project_choice.current() == "local"


def test_the_key_message_says_where_a_key_will_live_without_a_keychain(qapp):
    sheet = open_sheet(qapp, tab=CLOUD)
    status = sheet.cloud.key_status
    assert "No API key set" in status.text() and "settings file" in status.text() and "keyring" in status.text()

    sheet.cloud.key_edit.setText("sk-ant-fake-1")
    sheet.cloud._on_key_save()
    assert sheet.cloud.key_edit.text() == ""
    assert app_settings.get(credentials.FILE_SETTING_KEY) == "sk-ant-fake-1"
    assert "Key stored in the settings file" in status.text() and "keyring" in status.text()
    assert "sk-ant-fake-1" not in status.text()                    # the key itself is never shown

    sheet.cloud._on_key_remove()
    assert app_settings.get(credentials.FILE_SETTING_KEY) is None and "No API key set" in status.text()


def test_the_key_message_with_a_keychain_and_with_the_environment_variable(monkeypatch, qapp):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    sheet = open_sheet(qapp, tab=CLOUD)
    status = sheet.cloud.key_status
    assert "stored in the system keychain" in status.text()

    sheet.cloud.key_edit.setText("sk-ant-fake-2")
    sheet.cloud._on_key_save()
    assert status.text() == "Key stored in the system keychain."
    assert app_settings.get(credentials.FILE_SETTING_KEY) is None and credentials.get_api_key().source == "keychain"

    monkeypatch.setenv(credentials.ENV_VAR, "sk-ant-fake-env")
    sheet.cloud._on_key_remove()                  # refreshes: the variable is still there and wins
    assert credentials.ENV_VAR in status.text() and "environment variable" in status.text()
    monkeypatch.delenv(credentials.ENV_VAR)
    sheet.cloud._on_key_remove()
    assert "No API key set" in status.text() and not keyring.store


def test_a_key_saved_into_the_file_can_move_to_a_keychain_that_appeared_later(monkeypatch, qapp):
    app_settings.set(credentials.FILE_SETTING_KEY, "sk-ant-fake-3")
    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring())
    assert "move it to the system keychain" in open_sheet(qapp, tab=CLOUD).cloud.key_status.text()


def test_an_unusable_keychain_stores_the_key_in_the_settings_file(monkeypatch, qapp):
    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring(usable=False))
    sheet = open_sheet(qapp, tab=CLOUD)
    assert "settings file" in sheet.cloud.key_status.text()
    sheet.cloud.key_edit.setText("sk-ant-fake-4")
    sheet.cloud._on_key_save()
    assert credentials.get_api_key().source == "settings file"


def test_an_empty_key_is_not_saved(qapp):
    sheet = open_sheet(qapp, tab=CLOUD)
    sheet.cloud.key_edit.setText("   ")
    sheet.cloud._on_key_save()
    assert credentials.get_api_key() is None


# -- Ollama ------------------------------------------------------------------------------------

def test_the_installed_models_are_listed_with_their_size_and_selection_enables_the_buttons(qapp):
    sheet = open_sheet(qapp, tab=OLLAMA)
    tab = sheet.ollama
    texts = [tab.models_list.item(i).text() for i in range(tab.models_list.count())]
    assert texts[0] == "general-text   —   1.9 GB" and texts[2].endswith("(vision)")
    assert not tab.update_button.isEnabled() and not tab.delete_button.isEnabled()
    tab.models_list.item(1).setSelected(True)
    assert tab.selected() == ["translator"] and tab.update_button.isEnabled() and tab.delete_button.isEnabled()


def test_a_changed_host_is_saved_and_the_models_are_asked_for_again(qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app, tab=OLLAMA)
    asked = []
    sheet.ollama.changed.connect(lambda: asked.append(1))
    sheet.ollama.host_edit.setText("http://ollama.example:11434")
    sheet.ollama.host_edit.editingFinished.emit()
    assert app_settings.get_ollama_host() == "http://ollama.example:11434" and asked == [1]
    assert "Ollama host set to http://ollama.example:11434" in app.logged[-1]
    sheet.ollama.host_edit.setText("")             # empty clears the override
    sheet.ollama.host_edit.editingFinished.emit()
    assert app_settings.get(app_settings.OLLAMA_HOST_SETTING_KEY) is None
    assert sheet.ollama.host_edit.text() == app_settings.get_ollama_host()


def test_selected_models_are_deleted_after_a_question_and_hold_the_ollama_slot(monkeypatch, qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app, tab=OLLAMA)
    tab = sheet.ollama
    deleted, changed, asked = [], [], []
    monkeypatch.setattr(ollama_admin, "delete_model", lambda model: deleted.append(model) or (model != "translator", "in use"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    failures = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: failures.append(args[2]))
    tab.changed.connect(lambda: changed.append(1))
    tab.models_list.item(0).setSelected(True)
    tab.models_list.item(1).setSelected(True)

    tab._on_delete()

    assert deleted == ["general-text", "translator"] and changed == [1]
    assert app.slots == ["deleting 2 model(s)", "end"]
    assert "general-text" in asked[0] and "translator" in asked[0]
    assert failures and "Deleted 1 of 2" in failures[0] and "translator: in use" in failures[0]


def test_declining_the_delete_question_deletes_nothing(monkeypatch, qapp):
    app = FakeApp()
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    deleted = []
    monkeypatch.setattr(ollama_admin, "delete_model", lambda model: deleted.append(model) or (True, ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    tab.models_list.item(0).setSelected(True)
    tab._on_delete()
    assert deleted == [] and app.slots == ["deleting general-text", "end"]      # the slot is given back


def test_a_busy_ollama_slot_stops_a_delete_and_an_update(monkeypatch, qapp):
    app = FakeApp()
    app.slot_free = False
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    monkeypatch.setattr(ollama_admin, "delete_model", lambda model: pytest.fail("deleted while busy"))
    monkeypatch.setattr(ollama_admin, "update_model", lambda model, on_progress=None: pytest.fail("updated while busy"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    tab.models_list.item(0).setSelected(True)
    tab._on_delete()
    tab._on_update()
    assert app.slots == []


def test_an_update_runs_on_a_thread_and_the_list_is_asked_for_again_when_it_ends(monkeypatch, qapp):
    app = FakeApp()
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    monkeypatch.setattr(ollama_admin, "update_model", lambda model, on_progress=None: (
        on_progress and on_progress(f"pulling {model}"), (model == "general-text", "no space"))[1])
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    failures, changed = [], []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: failures.append(args[2]))
    tab.changed.connect(lambda: changed.append(1))
    tab.models_list.item(0).setSelected(True)
    tab.models_list.item(1).setSelected(True)

    tab._on_update()
    assert not tab.models_list.isEnabled() and not tab.update_button.isEnabled()
    wait_for(qapp, lambda: changed)

    assert tab.models_list.isEnabled()
    assert app.slots == ["updating 2 model(s)", "end"]
    assert "pulling general-text" in app.logged and "Updated Ollama model general-text" in app.logged
    assert "Failed to update translator: no space" in app.logged
    assert failures and "Updated 1 of 2" in failures[0]


# -- Prompts -----------------------------------------------------------------------------------

def test_a_prompt_is_unsaved_until_its_own_save_button(qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app, tab=PROMPTS)
    page = sheet.prompts.image
    assert page.editor.edit.toPlainText() == alt_draft.SYSTEM_PROMPT
    assert not page.dirty() and not page.editor.save_button.isEnabled() and page.editor.status.text() == ""

    page.editor.edit.setPlainText("Describe it plainly.")
    assert page.dirty() and page.editor.save_button.isEnabled() and page.editor.status.text() == "Unsaved changes"
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None
    page.editor.save_button.click()
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) == "Describe it plainly."
    assert not page.dirty() and "Saved image description prompt" in app.logged

    page.editor.reset_button.click()               # back to the program's own, which saving clears
    assert page.dirty()
    page.editor.save_button.click()
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None


def test_an_empty_prompt_is_refused_where_it_was_typed(qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    page = sheet.prompts.rewrite
    page.editor.edit.setPlainText("   ")
    page.editor.save_button.click()
    assert page.editor.status.text() == "The prompt text is required." and page.dirty()
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_SLIDE_REWRITE) is None


def test_the_pages_are_switched_by_the_chooser(qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    prompts = sheet.prompts
    assert prompts.stack.currentWidget() is prompts.image
    prompts.chooser.changed.emit("translation")
    assert prompts.stack.currentWidget() is prompts.translation


def test_closing_with_unsaved_prompt_text_asks_what_to_do(monkeypatch, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    prompts = sheet.prompts
    prompts.image.editor.edit.setPlainText("Mine")
    prompts.translation.editor.edit.setPlainText("Translate it")
    assert prompts.dirty_descriptions() == ["the image description prompt", "the default translation prompt"]

    answer(monkeypatch, "Cancel")
    sheet.reject()
    assert sheet.isVisible() and draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None

    answer(monkeypatch, "Save")
    sheet.reject()
    assert not sheet.isVisible()
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) == "Mine"
    assert tp.get_default_prompt().prompt == "Translate it"


def test_discarding_closes_without_saving_and_a_refused_save_keeps_the_sheet_open(monkeypatch, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    sheet.prompts.image.editor.edit.setPlainText("Mine")
    answer(monkeypatch, "Discard")
    sheet.reject()
    assert not sheet.isVisible() and draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None

    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    sheet.prompts.rewrite.editor.edit.setPlainText("")                 # not allowed
    answer(monkeypatch, "Save")
    sheet.reject()
    assert sheet.isVisible() and sheet.prompts.stack.currentWidget() is sheet.prompts.rewrite
    sheet.prompts.rewrite.editor.edit.setPlainText(ai_draft.SYSTEM_PROMPT)
    sheet.reject()
    assert not sheet.isVisible()


def test_nothing_unsaved_closes_without_a_question(monkeypatch, qapp):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: pytest.fail("asked with nothing unsaved"))
    sheet = open_sheet(qapp)
    sheet.show()
    sheet.reject()
    assert not sheet.isVisible()


def translation(sheet):
    return sheet.prompts.translation


def test_the_translation_chooser_lists_the_default_the_overrides_and_a_new_one(qapp):
    tp.set_prompt("translator", "en", "de", tp.PromptConfig("Translate it.", 2))
    page = translation(open_sheet(qapp, tab=PROMPTS))
    assert [page.chooser.itemText(i) for i in range(page.chooser.count())] == [
        "Default (models with no override)", "translator: en → de", "New override…"]
    assert page.choice() == "default" and page.keys.isHidden() and page.delete_button.isHidden()
    assert page.editor.edit.toPlainText() == tp.effective_default_prompt().prompt

    page.chooser.setCurrentIndex(1)
    assert page.choice() == ("translator", "en", "de") and page.keys.isHidden() and not page.delete_button.isHidden()
    assert page.editor.edit.toPlainText() == "Translate it." and page.blank_spin.value() == 2

    page.chooser.setCurrentIndex(2)
    assert page.choice() == "new" and not page.keys.isHidden() and page.editor.edit.toPlainText() == ""


def test_the_default_translation_prompt_is_saved_with_its_blank_lines(qapp):
    app = FakeApp()
    page = translation(open_sheet(qapp, app, tab=PROMPTS))
    page.editor.edit.setPlainText("Translate.")
    page.blank_spin.setValue(3)
    assert page.dirty() and page.editor.status.text() == "Unsaved changes"
    page.editor.save_button.click()
    assert tp.get_default_prompt() == tp.PromptConfig("Translate.", 3) and not page.dirty()
    assert "Saved default translation prompt" in app.logged


def test_a_new_override_needs_its_model_languages_and_text_and_is_selected_once_saved(qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app, tab=PROMPTS)
    page = translation(sheet)
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == sheet.available_models
    page.chooser.setCurrentIndex(page.chooser.count() - 1)
    page.editor.edit.setPlainText("For this model.")
    page.editor.save_button.click()
    assert "all required" in page.editor.status.text() and tp.list_configs() == []

    page.model_combo.setCurrentText("translator")
    page.editor.save_button.click()
    assert [c[:3] for c in tp.list_configs()] == [("translator", "en", "de")]
    assert page.choice() == ("translator", "en", "de") and not page.dirty() and page.keys.isHidden()
    assert "Saved translation prompt for translator (en → de)" in app.logged

    page.editor.edit.setPlainText("Changed.")
    page.editor.save_button.click()
    assert tp.get_prompt("translator", "en", "de").prompt == "Changed."


def test_an_override_is_deleted_after_a_question_and_the_default_takes_over(monkeypatch, qapp):
    tp.set_prompt("translator", "en", "de", tp.PromptConfig("Translate it.", 2))
    page = translation(open_sheet(qapp, tab=PROMPTS))
    page.chooser.setCurrentIndex(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.delete_button.click()
    assert tp.list_configs()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.delete_button.click()
    assert tp.list_configs() == [] and page.choice() == "default"


def test_the_model_list_of_the_translation_page_follows_the_models_and_keeps_what_was_typed(qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    page = translation(sheet)
    page.chooser.setCurrentIndex(page.chooser.count() - 1)
    page.model_combo.setCurrentText("typed-model")
    page.set_models(["a", "b"])
    assert page.model_combo.currentText() == "typed-model"
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == ["a", "b"]
