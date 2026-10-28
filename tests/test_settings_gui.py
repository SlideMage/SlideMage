# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings sheet: each tab's controls, what they save, and what changes live (the theme, the tab
width, the model pickers). Ollama and Claude are fakes; nothing here touches the network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QWidget

from slidemage import alt_draft, app_settings, draft_prompts, slide_snapshot, updater, version
from slidemage import translation_prompts as tp
from slidemage.ai import ai_profile, credentials, ollama_admin
from slidemage.ai.anthropic_provider import AnthropicProvider
from slidemage.ai.providers import InstalledModel, OllamaProvider
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Button
from slidemage.ui.dialogs.settings import ABOUT, AI, CLOUD, GENERAL, OLLAMA, PROJECT, PROMPTS, SettingsSheet
from conftest import EXAMPLE_PROJECT, wait_until
from test_templates import _framework, _project
from slidemage.project import ProjectContext

INSTALLED = [InstalledModel("general-text", 2_000_000_000, "", ("tools",)), InstalledModel("translator", 1_000_000, ""),
             InstalledModel("vision", 7_000_000_000, "", ("vision",)), InstalledModel("vision-2", 5_000_000, "", ("vision",))]


class FakeApp(QWidget):
    """The window as far as Settings uses it."""

    def __init__(self, project=EXAMPLE_PROJECT):
        super().__init__()
        self.project = project
        self.theme = ThemeManager()
        self.calls, self.logged, self.slots, self.slot_free = [], [], [], True
        self.set_dark_mode = lambda value: self.calls.append(("dark", value))
        self.set_autosave = lambda value: self.calls.append(("autosave", value))
        self.set_tab_width_chars = lambda value: self.calls.append(("tab width", value))
        self.log = self.logged.append
        self.commands = SimpleNamespace(run=lambda command_id, ctx: self.calls.append((command_id, ctx)))

    def acquire_route_task(self, route_id, label):
        from slidemage.plugins.host import _RouteTaskLease
        if not self.slot_free:
            return None
        self.slots.append(label)
        return _RouteTaskLease(lambda: self.slots.append("end"))


@pytest.fixture(autouse=True)
def fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(OllamaProvider, "installed", lambda self, **_: list(INSTALLED))
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


# -- the sheet ---------------------------------------------------------------------------------

def test_the_sheet_has_a_tab_for_each_group_of_settings_and_a_sensible_width(qapp):
    sheet = open_sheet(qapp)
    assert tab_names(sheet) == ["General", "AI", "Presentation", "Project", "About", "Plugins"]
    sheet.show()
    qapp.processEvents()
    assert sheet.width() < 1000            # unwrapped notes once made this ~2200 px wide
    sheet.close()
    assert open_sheet(qapp, tab=OLLAMA).current_tab() == AI          # a section of the AI tab now


def test_the_sheet_fits_the_screen_and_its_tabs_scroll(qapp):
    """The General tab is taller than many screens (2026-10-26: cut off at the bottom, with no way to reach
    Close): the sheet opens at most 85 % of the screen high and the tab scrolls."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QScrollArea

    from slidemage.ui.kit.widgets import SCROLL_GAP

    sheet = open_sheet(qapp)
    sheet.show()
    qapp.processEvents()
    screen = sheet.screen().availableGeometry()
    assert sheet.frameGeometry().height() <= screen.height() and sheet.height() <= int(screen.height() * 0.85)
    area = sheet._stack.currentWidget()
    assert isinstance(area, QScrollArea) and area.widget() is sheet.general
    if sheet.general.sizeHint().height() > area.viewport().height():
        assert area.verticalScrollBar().maximum() > 0      # what does not fit can be scrolled to
        bar = area.verticalScrollBar()
        bar_left = bar.mapTo(area, QPoint(0, 0)).x()
        content_right = area.viewport().mapTo(area, QPoint(area.viewport().width(), 0)).x()
        assert bar.isVisible() and bar_left - content_right >= SCROLL_GAP            # a gap before the scroll bar
    sheet.close()


# -- General -----------------------------------------------------------------------------------

def test_dark_mode_and_tab_width_reach_the_window_as_they_change(qapp):
    app = FakeApp()
    sheet = open_sheet(qapp, app)
    sheet.general.dark_check.setChecked(not app.theme.dark)
    sheet.general.tab_width_spin.setValue(8)
    assert app.calls == [("dark", not app.theme.dark), ("tab width", 8)]


def test_the_render_template_offers_the_project_templates_and_saves_the_choice(tmp_path, monkeypatch, qapp):
    _framework(tmp_path / "latex", "slidemage")
    context = ProjectContext.at(_project(tmp_path / "project", "uni-graz", "uni-ibk", "mci"))
    app = FakeApp(context)
    sheet = open_sheet(qapp, app)
    combo = sheet.general.template_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["slidemage", "mci", "uni-graz", "uni-ibk"]
    assert combo.currentData() == "slidemage"           # out of the box
    combo.setCurrentIndex(combo.findData("mci"))
    assert app_settings.get(context, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == "mci"
    assert slide_snapshot.render_template(context) == "mci"


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


# -- AI --------------------------------------------------------------------------------------

def test_the_ai_tab_has_the_address_and_the_model_of_each_task(qapp):
    sheet = open_sheet(qapp, tab=AI)
    assert sheet.ai.language.address.current() == "Sie"
    assert len(sheet.ai.models.findChildren(QComboBox)) == 2 * len(ai_profile.TASKS)


def test_what_ollama_has_is_kept_for_the_pickers_of_the_window(qapp):
    sheet = open_sheet(qapp)
    assert [m.name for m in sheet.installed] == [m.name for m in INSTALLED]
    assert sheet.ollama.models_list.count() == len(INSTALLED)


def test_an_unreachable_ollama_is_said_by_the_ollama_tab(monkeypatch, qapp):
    monkeypatch.setattr(OllamaProvider, "installed", lambda self, **_: [])
    sheet = open_sheet(qapp)
    assert sheet.installed == [] and "not reachable" in sheet.ollama.status.text()
    assert not sheet.ollama.models_list.isEnabled() and not sheet.ollama.delete_button.isEnabled()


def test_the_models_found_reach_the_window_when_the_sheet_closes(monkeypatch, qapp):
    from slidemage.ui.workspace import window as window_module

    sheet = open_sheet(qapp)
    monkeypatch.setattr(sheet, "exec", lambda: None)
    monkeypatch.setattr(window_module, "SettingsSheet", lambda _app, _tab, **_kw: sheet)
    filled, refreshed = [], []
    app = SimpleNamespace(local_models=SimpleNamespace(fill=filled.append), refresh_ai_models=lambda: refreshed.append(True))
    window_module.WorkspaceWindow.open_settings(app)
    assert filled == [sheet.installed] and refreshed == []          # the list's `changed` refreshes the pickers


def test_a_sheet_closed_before_the_models_arrived_refreshes_nothing(monkeypatch, qapp):
    from slidemage.ui.workspace import window as window_module

    sheet = SettingsSheet(FakeApp())
    loader = sheet._loader
    sheet.reject()                                  # closed at once
    loader.wait()
    qapp.processEvents()                            # its answer arrives to nobody
    assert not sheet.loaded and sheet.installed == []

    filled, refreshed = [], []
    app = SimpleNamespace(local_models=SimpleNamespace(fill=filled.append), refresh_ai_models=lambda: refreshed.append(True))
    monkeypatch.setattr(window_module, "SettingsSheet", lambda _app, _tab, **_kw: SimpleNamespace(exec=lambda: 0, loaded=False, after=None))
    window_module.WorkspaceWindow.open_settings(app)
    assert filled == [] and refreshed == [True]       # nothing was found; the keys and defaults may have changed


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
    assert [m.name for m in sheet.installed] == [m.name for m in INSTALLED] and sheet._loader is None


def test_an_answer_that_is_not_the_current_loaders_is_dropped(qapp):
    sheet = open_sheet(qapp)
    sheet._on_models(object(), [InstalledModel("stale", 1, "")])
    assert "stale" not in [m.name for m in sheet.installed]


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


def test_the_cloud_tab_has_the_key_and_points_to_the_switch_and_ai_setup_for_the_rest(qapp):
    sheet = open_sheet(qapp, tab=CLOUD)
    assert not hasattr(sheet.cloud, "connection") and not hasattr(sheet.cloud, "project_choice")
    assert "switch at the top of the assistant" in sheet.cloud.findChildren(QLabel)[0].text()


@pytest.mark.parametrize("backend", ["missing", "unusable"])
def test_the_key_message_says_where_a_key_will_live_without_a_keychain(qapp, monkeypatch, backend):
    if backend == "unusable":
        monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring(usable=False))
    sheet = open_sheet(qapp, tab=CLOUD)
    status = sheet.cloud.key_status
    assert "No API key set" in status.text() and "settings file" in status.text() and "keyring" in status.text()

    sheet.cloud.key_edit.setText("sk-ant-fake-1")
    sheet.cloud._on_key_save()
    assert sheet.cloud.key_edit.text() == ""
    assert app_settings.get(EXAMPLE_PROJECT, credentials.FILE_SETTING_KEY) == "sk-ant-fake-1"
    assert credentials.get_api_key(EXAMPLE_PROJECT).source == "settings file"
    assert "settings file on this computer" in status.text() and "keyring" in status.text()
    assert credentials.FILE_SETTING_KEY not in (EXAMPLE_PROJECT.settings_dir / "app_settings.json").read_text(encoding="utf-8")
    assert "sk-ant-fake-1" not in status.text()                    # the key itself is never shown

    sheet.cloud._on_key_remove()
    assert app_settings.get(EXAMPLE_PROJECT, credentials.FILE_SETTING_KEY) is None and "No API key set" in status.text()


def test_the_key_message_with_a_keychain_and_with_the_environment_variable(ctx, monkeypatch, qapp):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    sheet = open_sheet(qapp, tab=CLOUD)
    status = sheet.cloud.key_status
    assert "stored in the system keychain" in status.text()

    sheet.cloud.key_edit.setText("sk-ant-fake-2")
    sheet.cloud._on_key_save()
    assert status.text() == "Key stored in the system keychain."
    assert app_settings.get(ctx, credentials.FILE_SETTING_KEY) is None and credentials.get_api_key(ctx).source == "keychain"

    monkeypatch.setenv(credentials.ENV_VAR, "sk-ant-fake-env")
    sheet.cloud._on_key_remove()                  # refreshes: the variable is still there and wins
    assert credentials.ENV_VAR in status.text() and "environment variable" in status.text()
    monkeypatch.delenv(credentials.ENV_VAR)
    sheet.cloud._on_key_remove()
    assert "No API key set" in status.text() and not keyring.store


def test_a_keychain_entry_that_cannot_be_removed_is_reported_not_swallowed(ctx, monkeypatch, qapp):
    keyring = FakeKeyring()
    keyring.store[("SlideMage", "anthropic-api-key")] = "sk-ant-old"
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)

    def refuse(service, user):
        raise RuntimeError("locked")

    keyring.delete_password = refuse
    with pytest.raises(OSError, match="locked"):
        credentials.set_api_key(ctx, "")
    assert credentials.get_api_key(ctx).value == "sk-ant-old"            # still there, and the caller was told
    keyring.priority = 0                                              # the save fails; the old entry still shadows
    with pytest.raises(OSError):
        credentials.set_api_key(ctx, "sk-ant-new")
    assert app_settings.get(ctx, credentials.FILE_SETTING_KEY) == "sk-ant-new"
    del keyring.delete_password                                       # a keychain that lets go: nothing shadows the file
    assert credentials.set_api_key(ctx, "sk-ant-newer") == credentials.SOURCE_FILE
    assert credentials.get_api_key(ctx).value == "sk-ant-newer" and not keyring.store


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
    assert app_settings.get_ollama_host(EXAMPLE_PROJECT) == "http://ollama.example:11434" and asked == [1]
    sheet.ollama.host_edit.setText("")             # empty clears the override
    sheet.ollama.host_edit.editingFinished.emit()
    assert app_settings.get(EXAMPLE_PROJECT, app_settings.OLLAMA_HOST_SETTING_KEY) is None
    assert sheet.ollama.host_edit.text() == app_settings.get_ollama_host(EXAMPLE_PROJECT)


@pytest.mark.parametrize("operation, message", [("delete", "in use"), ("update", "no space")])
def test_model_changes_run_on_a_thread_and_refresh_the_list(monkeypatch, qapp, operation, message):
    app = FakeApp()
    sheet = open_sheet(qapp, app, tab=OLLAMA)
    tab = sheet.ollama
    changed, asked, processed = [], [], []

    def change(model, host, on_progress=None):
        processed.append(model)
        if on_progress:
            on_progress(f"pulling {model}")
        return model == "general-text", message

    monkeypatch.setattr(ollama_admin, f"{operation}_model", change)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    failures = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: failures.append(args[2]))
    tab.changed.connect(lambda: changed.append(1))
    tab.models_list.item(0).setSelected(True)
    tab.models_list.item(1).setSelected(True)

    getattr(tab, f"_on_{operation}")()
    assert not tab.models_list.isEnabled()
    assert not getattr(tab, f"{operation}_button").isEnabled()
    wait_until(lambda: changed)

    assert processed == ["general-text", "translator"] and changed == [1]
    assert tab.models_list.isEnabled()
    verb = "deleting" if operation == "delete" else "updating"
    assert app.slots == [f"{verb} 2 model(s)", "end"]
    past = "Deleted" if operation == "delete" else "Updated"
    assert failures and f"{past} 1 of 2" in failures[0]
    if operation == "delete":
        assert "general-text" in asked[0] and "translator" in asked[0]
        assert "translator: in use" in failures[0]
    else:
        assert "pulling general-text" in app.logged and "Updated Ollama model general-text" in app.logged
        assert "Failed to update translator: no space" in app.logged


def test_declining_the_delete_question_deletes_nothing(monkeypatch, qapp):
    app = FakeApp()
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    deleted = []
    monkeypatch.setattr(ollama_admin, "delete_model", lambda model, host: deleted.append(model) or (True, ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    tab.models_list.item(0).setSelected(True)
    tab._on_delete()
    assert deleted == [] and app.slots == ["deleting general-text", "end"]      # the slot is given back


def test_a_request_that_blows_up_still_enables_the_list_again(monkeypatch, qapp):
    app = FakeApp()
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama

    def explode(model, host, on_progress=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(ollama_admin, "update_model", explode)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    failures, changed = [], []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: failures.append(args[2]))
    tab.changed.connect(lambda: changed.append(1))
    tab.models_list.item(0).setSelected(True)
    tab._on_update()
    wait_until(lambda: changed)
    assert tab.models_list.isEnabled() and app.slots[-1] == "end" and "boom" in failures[0]



def test_admin_lease_is_held_until_the_worker_exits(monkeypatch, qapp):
    import threading
    from slidemage.ui.dialogs import settings_ollama

    app = FakeApp()
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    gate = threading.Event()
    original_run = settings_ollama._AdminWorker.run

    def run_then_wait(worker):
        original_run(worker)
        gate.wait(5)

    monkeypatch.setattr(settings_ollama._AdminWorker, "run", run_then_wait)
    monkeypatch.setattr(ollama_admin, "update_model", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    changed = []
    tab.changed.connect(lambda: changed.append(True))
    tab.models_list.item(0).setSelected(True)
    try:
        tab._on_update()
        wait_until(lambda: changed)
        assert app.slots == ["updating general-text"]
    finally:
        gate.set()
    wait_until(lambda: app.slots == ["updating general-text", "end"])

def test_a_busy_ollama_slot_stops_a_delete_and_an_update(monkeypatch, qapp):
    app = FakeApp()
    app.slot_free = False
    tab = open_sheet(qapp, app, tab=OLLAMA).ollama
    monkeypatch.setattr(ollama_admin, "delete_model", lambda model, host: pytest.fail("deleted while busy"))
    monkeypatch.setattr(ollama_admin, "update_model", lambda model, host, on_progress=None: pytest.fail("updated while busy"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    tab.models_list.item(0).setSelected(True)
    tab._on_delete()
    tab._on_update()
    assert app.slots == []


# -- Prompts -----------------------------------------------------------------------------------

def test_a_prompt_is_unsaved_until_its_own_save_button(ctx, qapp):
    app = FakeApp(ctx)
    sheet = open_sheet(qapp, app, tab=PROMPTS)
    page = sheet.prompts.image
    assert page.editor.edit.toPlainText() == alt_draft.SYSTEM_PROMPT
    assert not page.dirty() and not page.editor.save_button.isEnabled() and page.editor.status.text() == ""

    page.editor.edit.setPlainText("Describe it plainly.")
    assert page.dirty() and page.editor.save_button.isEnabled() and page.editor.status.text() == "Unsaved changes"
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None
    page.editor.save_button.click()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) == "Describe it plainly."
    assert not page.dirty() and "Saved image description prompt" in app.logged

    page.editor.reset_button.click()               # back to the program's own, which saving clears
    assert page.dirty()
    page.editor.save_button.click()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None


def test_an_empty_prompt_is_refused_where_it_was_typed(ctx, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    page = sheet.prompts.image
    page.editor.edit.setPlainText("   ")
    page.editor.save_button.click()
    assert page.editor.status.text() == "The prompt text is required." and page.dirty()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None


def test_closing_with_unsaved_prompt_text_asks_what_to_do(monkeypatch, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    prompts = sheet.prompts
    prompts.image.editor.edit.setPlainText("Mine")
    prompts.translation.editor.edit.setPlainText("Translate it")
    assert prompts.dirty_descriptions() == ["the image description prompt", "the default translation prompt"]

    answer(monkeypatch, "Cancel")
    sheet.reject()
    assert sheet.isVisible() and draft_prompts.get_custom_prompt(EXAMPLE_PROJECT, draft_prompts.KIND_IMAGE_DRAFT) is None

    answer(monkeypatch, "Save")
    sheet.reject()
    assert not sheet.isVisible()
    assert draft_prompts.get_custom_prompt(EXAMPLE_PROJECT, draft_prompts.KIND_IMAGE_DRAFT) == "Mine"
    assert tp.get_default_prompt(EXAMPLE_PROJECT).prompt == "Translate it"


def test_discarding_closes_without_saving_and_a_refused_save_keeps_the_sheet_open(ctx, monkeypatch, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    sheet.prompts.image.editor.edit.setPlainText("Mine")
    answer(monkeypatch, "Discard")
    sheet.reject()
    assert not sheet.isVisible() and draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None

    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    sheet.prompts.image.editor.edit.setPlainText("")                   # not allowed
    answer(monkeypatch, "Save")
    sheet.reject()
    assert sheet.isVisible() and sheet.prompts.stack.currentWidget() is sheet.prompts.image
    sheet.prompts.image.editor.edit.setPlainText(alt_draft.SYSTEM_PROMPT)
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
    tp.set_prompt(EXAMPLE_PROJECT, "translator", "en", "de", tp.PromptConfig("Translate it.", 2))
    sheet = open_sheet(qapp, tab=PROMPTS)
    assert sheet.prompts.stack.currentWidget() is sheet.prompts.image
    sheet.prompts.chooser.changed.emit("translation")
    page = translation(sheet)
    assert sheet.prompts.stack.currentWidget() is page
    assert [page.chooser.itemText(i) for i in range(page.chooser.count())] == [
        "Default (models with no override)", "translator: en → de", "New override…"]
    assert page.choice() == "default" and page.keys.isHidden() and page.delete_button.isHidden()
    assert page.editor.edit.toPlainText() == tp.effective_default_prompt(EXAMPLE_PROJECT).prompt

    page.chooser.setCurrentIndex(1)
    assert page.choice() == ("translator", "en", "de") and page.keys.isHidden() and not page.delete_button.isHidden()
    assert page.editor.edit.toPlainText() == "Translate it." and page.blank_spin.value() == 2

    page.chooser.setCurrentIndex(2)
    assert page.choice() == "new" and not page.keys.isHidden() and page.editor.edit.toPlainText() == ""


def test_the_default_translation_prompt_is_saved_with_its_blank_lines(ctx, qapp):
    app = FakeApp(ctx)
    page = translation(open_sheet(qapp, app, tab=PROMPTS))
    page.editor.edit.setPlainText("Translate.")
    page.blank_spin.setValue(3)
    assert page.dirty() and page.editor.status.text() == "Unsaved changes"
    page.editor.save_button.click()
    assert tp.get_default_prompt(ctx) == tp.PromptConfig("Translate.", 3) and not page.dirty()


def test_a_new_override_needs_its_model_languages_and_text_and_is_selected_once_saved(ctx, qapp):
    app = FakeApp(ctx)
    sheet = open_sheet(qapp, app, tab=PROMPTS)
    page = translation(sheet)
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == [m.name for m in sheet.installed]
    page.chooser.setCurrentIndex(page.chooser.count() - 1)
    page.editor.edit.setPlainText("For this model.")
    page.editor.save_button.click()
    assert "all required" in page.editor.status.text() and tp.list_configs(ctx) == []

    page.model_combo.setCurrentText("translator")
    page.editor.save_button.click()
    assert [c[:3] for c in tp.list_configs(ctx)] == [("translator", "en", "de")]
    assert page.choice() == ("translator", "en", "de") and not page.dirty() and page.keys.isHidden()

    page.editor.edit.setPlainText("Changed.")
    page.editor.save_button.click()
    assert tp.get_prompt(ctx, "translator", "en", "de").prompt == "Changed."


def test_an_override_is_deleted_after_a_question_and_the_default_takes_over(monkeypatch, qapp):
    tp.set_prompt(EXAMPLE_PROJECT, "translator", "en", "de", tp.PromptConfig("Translate it.", 2))
    page = translation(open_sheet(qapp, tab=PROMPTS))
    page.chooser.setCurrentIndex(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.delete_button.click()
    assert tp.list_configs(EXAMPLE_PROJECT)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.delete_button.click()
    assert tp.list_configs(EXAMPLE_PROJECT) == [] and page.choice() == "default"


def test_the_model_list_of_the_translation_page_follows_the_models_and_keeps_what_was_typed(qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    page = translation(sheet)
    page.chooser.setCurrentIndex(page.chooser.count() - 1)
    page.model_combo.setCurrentText("typed-model")
    page.set_models(["a", "b"])
    assert page.model_combo.currentText() == "typed-model"
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == ["a", "b"]


def test_the_render_cleanup_offers_never_and_saves_the_choice(tmp_path, qapp):
    from slidemage import slide_preview

    context = ProjectContext.at(tmp_path / "project")
    app = FakeApp(context)
    sheet = open_sheet(qapp, app)
    combo = sheet.general.cleanup_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [1, 24, 72, 168, 720, 0]
    assert combo.currentData() == 24 and combo.itemText(combo.count() - 1) == "Never"
    combo.setCurrentIndex(combo.findData(slide_preview.RENDER_CLEANUP_NEVER))
    assert app_settings.get(context, slide_preview.RENDER_CLEANUP_SETTING_KEY) == 0
    assert slide_preview.render_cleanup_hours(context) == slide_preview.RENDER_CLEANUP_NEVER
    combo.setCurrentIndex(combo.findData(168))
    assert slide_preview.render_cleanup_hours(context) == 168
    assert app.logged[-1] == "Single-slide renders: after 1 week"


def test_a_cleanup_age_set_by_hand_is_shown(tmp_path, qapp):
    from slidemage import slide_preview

    context = ProjectContext.at(tmp_path / "project")
    app_settings.set(context, slide_preview.RENDER_CLEANUP_SETTING_KEY, 5)
    combo = open_sheet(qapp, FakeApp(context)).general.cleanup_combo
    assert combo.currentData() == 5 and combo.currentText() == "After 5 hours"


def test_asking_about_update_version_on_leaving_is_off_by_default_and_saved(tmp_path, qapp):
    from slidemage import slide_versioning

    context = ProjectContext.at(tmp_path / "project")
    check = open_sheet(qapp, FakeApp(context)).general.ask_version_check
    assert not check.isChecked()
    check.setChecked(True)
    assert app_settings.get(context, slide_versioning.ASK_ON_LEAVE_SETTING_KEY) is True


# -- Project and About -------------------------------------------------------------------------

def project_with_files(tmp_path, *names):
    project = ProjectContext.at(tmp_path / "project")
    for name in names:
        path = project.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return project


def test_edit_closes_settings_and_opens_the_file_in_source_afterwards(tmp_path, qapp):
    app = FakeApp(project_with_files(tmp_path, "Slidemaster.bib", "decks/test-slides.tex"))
    sheet = open_sheet(qapp, app, tab=PROJECT)
    buttons = sheet.project_tab.edit_buttons
    assert tab_names(sheet)[PROJECT] == "Project" and all(b.isEnabled() for b in buttons.values())
    assert any(label.text() == "Slidemaster.bib" for label in sheet.project_tab.findChildren(QLabel))

    buttons["bib"].click()
    assert sheet.result() == sheet.DialogCode.Accepted and app.calls == []      # closed first, nothing run yet
    sheet.after()
    assert app.calls == [("edit_bib", app)]

    sheet = open_sheet(qapp, app, tab=PROJECT)
    sheet.project_tab.edit_buttons["test_slides"].click()
    sheet.after()
    assert app.calls == [("edit_bib", app), ("edit_test_slides", app)]


def test_a_missing_file_says_not_found_and_cannot_be_edited(tmp_path, qapp):
    sheet = open_sheet(qapp, FakeApp(project_with_files(tmp_path, "Slidemaster.bib")), tab=PROJECT)
    assert sheet.project_tab.edit_buttons["bib"].isEnabled()
    assert not sheet.project_tab.edit_buttons["test_slides"].isEnabled()
    texts = [label.text() for label in sheet.project_tab.findChildren(QLabel)]
    assert "test-slides.tex — not found" in texts and "Slidemaster.bib — not found" not in texts


def test_unsaved_prompt_text_is_asked_about_before_edit_closes_settings(tmp_path, monkeypatch, qapp):
    app = FakeApp(project_with_files(tmp_path, "Slidemaster.bib"))
    sheet = open_sheet(qapp, app, tab=PROJECT)
    sheet.show()
    sheet.prompts.image.editor.edit.setPlainText("Mine")
    answer(monkeypatch, "Cancel")
    sheet.project_tab.edit_buttons["bib"].click()
    assert sheet.isVisible() and sheet.after is None            # it stayed, and runs nothing when closed later

    answer(monkeypatch, "Discard")
    sheet.project_tab.edit_buttons["bib"].click()
    assert not sheet.isVisible()
    sheet.after()
    assert app.calls == [("edit_bib", app)]


def test_the_project_and_about_buttons_run_their_commands(qapp):
    app = FakeApp()
    for tab, page, text in ((PROJECT, "project_tab", "Check…"), (ABOUT, "about", "Open…"), (ABOUT, "about", "Check…")):
        sheet = open_sheet(qapp, app, tab=tab)
        next(b for b in getattr(sheet, page).findChildren(Button) if b.text() == text).click()
        assert sheet.result() == sheet.DialogCode.Accepted
        sheet.after()
    assert app.calls == [(name, app) for name in ("project_compat", "version_history", "check_updates")]


def test_the_window_runs_what_the_sheet_leaves_after_it_has_closed(monkeypatch, qapp):
    from slidemage.ui.workspace import window as window_module

    order = []
    sheet = SimpleNamespace(exec=lambda: order.append("closed"), loaded=False, after=lambda: order.append("action"))
    monkeypatch.setattr(window_module, "SettingsSheet", lambda _app, _tab, **_kw: sheet)
    app = SimpleNamespace(refresh_ai_models=lambda: order.append("refreshed"))
    window_module.WorkspaceWindow.open_settings(app)
    assert order == ["closed", "refreshed", "action"]


def test_about_shows_the_version(qapp):
    sheet = open_sheet(qapp, tab=ABOUT)
    assert any(label.text() == f"SlideMage {version.VERSION_NUMBER}" for label in sheet.about.findChildren(QLabel))
