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
from slidemage.ai import ai_profile
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Button
from slidemage.ui.dialogs.settings import ABOUT, AI, GENERAL, OLLAMA, PROJECT, PROMPTS, SettingsSheet
from conftest import EXAMPLE_PROJECT
from test_templates import _framework, _project
from slidemage.project import ProjectContext



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
def fakes(tmp_path, monkeypatch, fake_routes):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")


def loaded(sheet, qapp):
    """The sheet once the model lists the thread fetched have arrived."""
    qapp.processEvents()
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
    context = ProjectContext.at(_project(tmp_path / "project", "beta", "gamma", "acme"))
    app = FakeApp(context)
    sheet = open_sheet(qapp, app)
    combo = sheet.general.template_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["slidemage", "acme", "beta", "gamma"]
    assert combo.currentData() == "slidemage"           # out of the box
    combo.setCurrentIndex(combo.findData("acme"))
    assert app_settings.get(context, slide_snapshot.RENDER_TEMPLATE_SETTING_KEY) == "acme"
    assert slide_snapshot.render_template(context) == "acme"


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
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == ["fake-1", "fake-2"]
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
    app = FakeApp(project_with_files(tmp_path, "SlideMage.bib", "decks/test-slides.tex"))
    sheet = open_sheet(qapp, app, tab=PROJECT)
    buttons = sheet.project_tab.edit_buttons
    assert tab_names(sheet)[PROJECT] == "Project" and all(b.isEnabled() for b in buttons.values())
    assert any(label.text() == "SlideMage.bib" for label in sheet.project_tab.findChildren(QLabel))

    buttons["bib"].click()
    assert sheet.result() == sheet.DialogCode.Accepted and app.calls == []      # closed first, nothing run yet
    sheet.after()
    assert app.calls == [("edit_bib", app)]

    sheet = open_sheet(qapp, app, tab=PROJECT)
    sheet.project_tab.edit_buttons["test_slides"].click()
    sheet.after()
    assert app.calls == [("edit_bib", app), ("edit_test_slides", app)]


def test_a_missing_file_says_not_found_and_cannot_be_edited(tmp_path, qapp):
    sheet = open_sheet(qapp, FakeApp(project_with_files(tmp_path, "SlideMage.bib")), tab=PROJECT)
    assert sheet.project_tab.edit_buttons["bib"].isEnabled()
    assert not sheet.project_tab.edit_buttons["test_slides"].isEnabled()
    texts = [label.text() for label in sheet.project_tab.findChildren(QLabel)]
    assert "test-slides.tex — not found" in texts and "SlideMage.bib — not found" not in texts


def test_unsaved_prompt_text_is_asked_about_before_edit_closes_settings(tmp_path, monkeypatch, qapp):
    app = FakeApp(project_with_files(tmp_path, "SlideMage.bib"))
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
