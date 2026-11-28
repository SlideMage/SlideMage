# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings sheet controls, persistence and live changes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QMessageBox, QWidget

from slidemage import alt_draft, app_settings, draft_prompts, languages, slide_templates, updater
from slidemage import translation_prompts as tp
from slidemage.ai import ai_profile
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Button
from slidemage.ui.dialogs.settings import ABOUT, AI, GENERAL, OLLAMA, PROJECT, PROMPTS, SettingsSheet
from conftest import EXAMPLE_PROJECT
from test_templates import _framework, _project
from slidemage.project import ProjectContext


class FakeApp(QWidget):
    def __init__(self, project=EXAMPLE_PROJECT):
        super().__init__()
        self.project = project
        self.theme = ThemeManager()
        self.calls, self.logged = [], []
        self.set_dark_mode = lambda value: self.calls.append(("dark", value))
        self.set_autosave = lambda value: self.calls.append(("autosave", value))
        self.set_tab_width_chars = lambda value: self.calls.append(("tab width", value))
        self.set_hover_help = lambda value: self.calls.append(("hover help", value))
        self.log = self.logged.append
        self.commands = SimpleNamespace(run=lambda command_id, ctx: self.calls.append((command_id, ctx)))

    def acquire_route_task(self, route_id, label):
        from slidemage.plugins.host import _RouteTaskLease
        return _RouteTaskLease(lambda: None)


@pytest.fixture(autouse=True)
def fakes(tmp_path, monkeypatch, fake_routes):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")


def open_sheet(qapp, app=None, tab=GENERAL):
    app = app or FakeApp()
    sheet = SettingsSheet(app, tab=tab)
    sheet.app = app
    qapp.processEvents()
    return sheet


def answer(monkeypatch, button_text):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(
        b for b in self.buttons() if b.text().replace("&", "") == button_text))


# -- the sheet ---------------------------------------------------------------------------------

def test_the_settings_tabs_fit_the_screen_and_scroll(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QScrollArea

    from slidemage.ui.kit.widgets import SCROLL_GAP

    sheet = open_sheet(qapp)
    tabs = sheet._tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["General", "AI", "Presentation", "Project", "About", "Extensions"]
    sheet.show()
    qapp.processEvents()
    # Unwrapped notes made the sheet too wide, and a tall General tab hid Close.
    screen = sheet.screen().availableGeometry()
    assert sheet.width() < 1000 and sheet.frameGeometry().height() <= screen.height()
    area = sheet._stack.currentWidget()
    assert isinstance(area, QScrollArea) and area.widget() is sheet.general
    if sheet.general.sizeHint().height() > area.viewport().height():
        bar = area.verticalScrollBar()
        assert bar.isVisible() and bar.maximum() > 0
        viewport = area.viewport()
        assert bar.mapTo(area, QPoint()).x() - viewport.mapTo(area, QPoint(viewport.width(), 0)).x() >= SCROLL_GAP
    sheet.close()


# -- General -----------------------------------------------------------------------------------

def test_the_render_template_offers_the_project_templates_and_saves_the_choice(tmp_path, qapp):
    _framework(tmp_path / "latex", "slidemage")
    context = ProjectContext.at(_project(tmp_path / "project", "beta", "gamma", "acme"))
    app = FakeApp(context)
    sheet = open_sheet(qapp, app)
    combo = sheet.general.template_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["slidemage", "acme", "beta", "gamma", "grayscale"]
    assert combo.currentData() == "slidemage"           # out of the box
    combo.setCurrentIndex(combo.findData("acme"))
    assert app_settings.get(context, slide_templates.RENDER_TEMPLATE_SETTING_KEY) == "acme"
    assert slide_templates.render_template(context) == "acme"


def test_general_controls_apply_live_and_save_update_settings(qapp):
    app = FakeApp()
    general = open_sheet(qapp, app).general
    dark = not app.theme.dark
    general.dark_check.setChecked(dark)
    general.tab_width_spin.setValue(8)
    assert general.hover_help_check.isChecked()
    general.hover_help_check.setChecked(False)
    assert app.calls == [("dark", dark), ("tab width", 8), ("hover help", False)]

    assert general.update_mode.current() == updater.UPDATE_MODE_ASK and updater.get_update_mode() == "ask"
    general.update_mode.changed.emit(updater.UPDATE_MODE_AUTO)
    assert updater.get_update_mode() == "auto"
    general.update_mode.changed.emit(updater.UPDATE_MODE_OFF)
    assert updater.get_update_mode() == "off"

    general.token_edit.setText(" ghp_fake ")
    general.token_edit.editingFinished.emit()
    assert updater.saved_token() == "ghp_fake"
    general.token_edit.setText("")
    general.token_edit.editingFinished.emit()
    assert updater.saved_token() == ""
    general.token_show.setChecked(True)
    assert general.token_edit.echoMode().name == "Normal"


# -- AI --------------------------------------------------------------------------------------

def test_the_ai_tab_has_the_model_of_each_task(qapp):
    sheet = open_sheet(qapp, tab=OLLAMA)
    assert sheet.current_tab() == AI
    assert len(sheet.ai.models.findChildren(QComboBox)) == 2 * len(ai_profile.TASKS)


# -- Prompts -----------------------------------------------------------------------------------

def test_the_image_prompt_saves_and_resets_only_on_save(ctx, qapp):
    page = open_sheet(qapp, FakeApp(ctx), tab=PROMPTS).prompts.image
    editor = page.editor
    assert editor.edit.toPlainText() == alt_draft.SYSTEM_PROMPT and not editor.save_button.isEnabled()
    editor.edit.setPlainText("Describe it plainly.")
    assert page.dirty() and editor.save_button.isEnabled()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None
    editor.save_button.click()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) == "Describe it plainly."
    assert not page.dirty()
    editor.reset_button.click()
    assert page.dirty()
    editor.save_button.click()
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None


def test_closing_with_unsaved_prompt_text_asks_what_to_do(monkeypatch, qapp):
    sheet = open_sheet(qapp, tab=PROMPTS)
    sheet.show()
    prompts = sheet.prompts
    prompts.image.editor.edit.setPlainText("Mine")
    prompts.translation.editor.edit.setPlainText("Translate it")
    prompts.translation.blank_spin.setValue(3)
    assert prompts.dirty_descriptions() == ["the image description prompt", "the default translation prompt"]

    answer(monkeypatch, "Cancel")
    sheet.reject()
    assert sheet.isVisible() and draft_prompts.get_custom_prompt(EXAMPLE_PROJECT, draft_prompts.KIND_IMAGE_DRAFT) is None

    answer(monkeypatch, "Save")
    sheet.reject()
    assert not sheet.isVisible()
    assert draft_prompts.get_custom_prompt(EXAMPLE_PROJECT, draft_prompts.KIND_IMAGE_DRAFT) == "Mine"
    assert tp.get_default_prompt(EXAMPLE_PROJECT) == tp.PromptConfig("Translate it", 3)


def test_refused_save_keeps_the_prompt_edit_and_discard_closes(ctx, monkeypatch, qapp):
    sheet = open_sheet(qapp, FakeApp(ctx), tab=PROMPTS)
    sheet.show()
    page = sheet.prompts.image
    page.editor.edit.setPlainText("   ")
    answer(monkeypatch, "Save")
    sheet.reject()
    assert sheet.isVisible() and sheet.prompts.stack.currentWidget() is page
    assert page.editor.status.text() == "The prompt text is required." and page.dirty()
    answer(monkeypatch, "Discard")
    sheet.reject()
    assert not sheet.isVisible() and draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None


def test_translation_save_errors_keep_the_pending_edit_and_conflicted_file(ctx, qapp):
    tp.set_prompt(ctx, "translator", "en", "de", tp.PromptConfig("Stored override"))
    path = ctx.settings_dir / "translation_prompts.json"
    original = path.read_bytes()
    app = FakeApp(ctx)
    page = open_sheet(qapp, app, tab=PROMPTS).prompts.translation
    conflicted = b"<<<<<<< HEAD\n" + original + b"=======\n{}\n>>>>>>> branch\n"
    path.write_bytes(conflicted)

    for index in range(page.chooser.count()):     # default, existing override, new override
        page.chooser.setCurrentIndex(index)
        if page.choice() == "new":
            page.model_combo.setCurrentText("new-model")
            page.source_combo.setCurrentText("en")
            page.target_combo.setCurrentText("fr")
        pending = f"  Pending prompt {index}\n"
        page.editor.edit.setPlainText(pending)
        page.blank_spin.setValue(3)
        choice = page.choice()
        assert not page.save()
        assert "translation_prompts.json cannot be read" in page.editor.status.text()
        assert page.editor.status.property("tone") == "error"
        assert page.editor.edit.toPlainText() == pending and page.blank_spin.value() == 3
        assert page.choice() == choice and page.dirty() and page.editor.save_button.isEnabled()
        assert path.read_bytes() == conflicted
    assert not any(message.startswith("Saved") for message in app.logged)

    path.write_bytes(original)                  # repair the conflict and retry the pending edit
    assert page.save() and not page.dirty()
    assert tp.get_prompt(ctx, "new-model", "en", "fr") == tp.PromptConfig(pending.strip(), 3)


def test_a_new_override_needs_its_model_languages_and_text_and_is_selected_once_saved(ctx, qapp):
    sheet = open_sheet(qapp, FakeApp(ctx), tab=PROMPTS)
    page = sheet.prompts.translation
    sheet.prompts.chooser.changed.emit("translation")
    assert sheet.prompts.stack.currentWidget() is page and page.choice() == "default"
    assert page.editor.edit.toPlainText() == tp.effective_default_prompt(ctx).prompt
    assert [page.model_combo.itemText(i) for i in range(page.model_combo.count())] == ["fake-1", "fake-2"]
    page.chooser.setCurrentIndex(page.chooser.count() - 1)
    page.editor.edit.setPlainText("For this model.")
    page.editor.save_button.click()
    assert "all required" in page.editor.status.text() and tp.list_configs(ctx) == []

    page.model_combo.setCurrentText("translator")
    page.set_models(["a", "b"])
    assert page.model_combo.currentText() == "translator"
    page.editor.save_button.click()
    assert [c[:3] for c in tp.list_configs(ctx)] == [("translator", "en", "de")]
    assert page.choice() == ("translator", "en", "de") and not page.dirty() and page.keys.isHidden()

    page.editor.edit.setPlainText("Changed.")
    page.editor.save_button.click()
    assert tp.get_prompt(ctx, "translator", "en", "de").prompt == "Changed."


def test_an_override_is_deleted_after_a_question_and_the_default_takes_over(monkeypatch, qapp):
    tp.set_prompt(EXAMPLE_PROJECT, "translator", "en", "de", tp.PromptConfig("Translate it.", 2))
    page = open_sheet(qapp, tab=PROMPTS).prompts.translation
    page.chooser.setCurrentIndex(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.delete_button.click()
    assert tp.list_configs(EXAMPLE_PROJECT)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.delete_button.click()
    assert tp.list_configs(EXAMPLE_PROJECT) == [] and page.choice() == "default"


def test_the_render_cleanup_offers_never_and_saves_the_choice(tmp_path, qapp):
    from slidemage import slide_preview

    context = ProjectContext.at(tmp_path / "project")
    app = FakeApp(context)
    sheet = open_sheet(qapp, app)
    combo = sheet.general.cleanup_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [1, 24, 72, 168, 720, 0]
    assert combo.currentData() == 24
    combo.setCurrentIndex(combo.findData(slide_preview.RENDER_CLEANUP_NEVER))
    assert app_settings.get(context, slide_preview.RENDER_CLEANUP_SETTING_KEY) == 0
    assert slide_preview.render_cleanup_hours(context) == slide_preview.RENDER_CLEANUP_NEVER
    combo.setCurrentIndex(combo.findData(168))
    assert slide_preview.render_cleanup_hours(context) == 168
    app_settings.set(context, slide_preview.RENDER_CLEANUP_SETTING_KEY, 5)
    assert open_sheet(qapp, app).general.cleanup_combo.currentData() == 5


# -- Project and About -------------------------------------------------------------------------

def test_editing_a_project_file_waits_for_unsaved_prompt_resolution(tmp_path, monkeypatch, qapp):
    (tmp_path / "SlideMage.bib").touch()
    app = FakeApp(ProjectContext.at(tmp_path))
    sheet = open_sheet(qapp, app, tab=PROJECT)
    buttons = sheet.project_tab.edit_buttons
    assert buttons["bib"].isEnabled() and not buttons["test_slides"].isEnabled()
    sheet.show()
    sheet.prompts.image.editor.edit.setPlainText("Mine")
    answer(monkeypatch, "Cancel")
    buttons["bib"].click()
    assert sheet.isVisible() and sheet.after is None and app.calls == []

    answer(monkeypatch, "Discard")
    buttons["bib"].click()
    assert sheet.result() == sheet.DialogCode.Accepted and not sheet.isVisible()
    assert app.calls == []
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


def test_about_toggles_the_debug_log_and_offers_logs_and_a_report(qapp, tmp_path, monkeypatch):
    from slidemage import diagnostics

    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.delenv(diagnostics.DEBUG_ENV, raising=False)
    diagnostics.setup("app")
    sheet = open_sheet(qapp, tab=ABOUT)
    check = sheet.about.debug_check
    assert not check.isChecked()
    check.setChecked(True)
    assert diagnostics.debug_enabled() and diagnostics.saved()
    check.setChecked(False)
    assert not diagnostics.debug_enabled()
    buttons = {button.text(): button for button in sheet.about.findChildren(Button)}
    buttons["Open"].click()
    assert sheet.app.calls == [("open_logs", sheet.app)] and sheet.after is None
    buttons["Save…"].click()
    sheet.after()
    assert sheet.app.calls[-1] == ("debug_report", sheet.app)


# -- Languages (Project) ---------------------------------------------------------------------

def languages_page(tmp_path, qapp, stated=("en", ["de"]), **files):
    """The Languages section of a project with the given slide files and decks (name: text) that states its
    languages (`stated`: none for a project from before the key)."""
    project = ProjectContext.at(tmp_path / "project")
    for folder in ("slides", "decks"):
        (project.root / folder).mkdir(parents=True)
    for name, text in files.items():
        (project.root / name).write_text(text, encoding="utf-8")
    if stated:
        languages.set_project_languages(project, *stated)
    app = FakeApp(project)
    return open_sheet(qapp, app, tab=PROJECT).project_tab.languages, app


def shown(page):
    return [page.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(page.list.count())]


def test_the_languages_page_of_a_project_without_the_key_shows_what_it_uses_and_writes_nothing(tmp_path, qapp):
    page, app = languages_page(tmp_path, qapp, stated=None, **{"slides/aaa-DE-Eins-current.tex": "x\n"})
    assert page.main.currentData() == "en" and shown(page) == ["de"]
    assert page.address.current() == "formal"
    assert not (app.project.root / ".slidemage" / "project.json").exists()


def test_secondary_languages_can_be_added_removed_and_reordered(tmp_path, qapp, monkeypatch):
    page, app = languages_page(tmp_path, qapp, stated=("en", []))
    assert page.main.currentData() == "en" and shown(page) == []
    assert not (page.remove_button.isEnabled() or page.up_button.isEnabled() or page.down_button.isEnabled())
    assert page.add_button.isEnabled()
    page.main.activated.emit(page.main.findData("fr"))              # the old main language becomes the secondary one
    assert languages.project_languages(app.project) == languages.Languages("fr", ("en",))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: pytest.fail("asked about an unused language"))
    assert page.add_language("de") and page.remove_language() and page.remove_language() is False
    page.list.setCurrentRow(0)
    assert page.remove_language() and shown(page) == []
    assert languages.project_languages(app.project) == languages.Languages("fr")
    page.move(1)  # Nothing selected.
    assert page.add_language("de") and page.add_language("it")
    assert shown(page) == ["de", "it"] and page.selected() == "it"
    page.move(-1)
    page.move(-1)  # Already first.
    assert languages.project_languages(app.project).secondary == ("it", "de")
    assert page.selected() == "it" and not page.up_button.isEnabled() and page.down_button.isEnabled()


def test_adding_a_language_that_names_slides_asks_what_language_they_are_in(tmp_path, qapp, monkeypatch):
    from slidemage.ui.dialogs.settings_languages import UntaggedSlugsSheet

    page, app = languages_page(tmp_path, qapp, **{
        "slides/x7k-IT-Governance-current.tex": "x\n", "slides/y8m-EN-Other-current.tex": "y\n",
        "decks/course.tex": "\\documentclass{beamer}\n\\begin{document}\n\\slide{x7k-IT-Governance}\n\\end{document}\n"})
    seen = []

    def answer(sheet):
        seen.append((sheet.windowTitle(), sorted(sheet.combos), [c.currentData() for c in sheet.combos.values()]))
        sheet.combos["x7k-IT-Governance"].setCurrentIndex(sheet.combos["x7k-IT-Governance"].findData("DE"))
        return 1

    monkeypatch.setattr(UntaggedSlugsSheet, "exec", lambda sheet: 0)
    assert not page.add_language("it")                          # cancelled: nothing renamed, nothing added
    assert (app.project.slides_dir / "x7k-IT-Governance-current.tex").is_file() and shown(page) == ["de"]
    monkeypatch.setattr(UntaggedSlugsSheet, "exec", answer)
    assert page.add_language("it")
    assert seen == [("Slides named like Italian", ["x7k-IT-Governance"], ["EN"])]       # the main language to start
    assert (app.project.slides_dir / "x7k-DE-IT-Governance-current.tex").is_file()
    assert "\\slide{x7k-DE-IT-Governance}" in (app.project.decks_dir / "course.tex").read_text(encoding="utf-8")
    assert shown(page) == ["de", "it"]


def test_removing_a_language_in_use_asks_with_the_counts(tmp_path, qapp, monkeypatch):
    deck = "\\documentclass{beamer}\n\\decklanguage[de]\n\\begin{document}\n\\end{document}\n"
    page, app = languages_page(tmp_path, qapp, **{
        "slides/aaa-DE-Eins-current.tex": "x\n", "slides/bbb-DE-Zwei-current.tex": "x\n",
        "slides/ccc-EN-Three-current.tex": "x\n", "decks/kurs.tex": deck})
    asked = []

    def question(_parent, _title, text, *_args):
        asked.append(text)
        return QMessageBox.StandardButton.No if len(asked) == 1 else QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    page.list.setCurrentRow(0)
    assert not page.remove_language() and shown(page) == ["de"]
    assert page.remove_language() and shown(page) == [] and languages.project_languages(app.project).secondary == ()
    assert asked == ["2 slides and 1 deck are in German; they stay as they are, but SlideMage no longer offers "
                     "German. Remove it?"] * 2
