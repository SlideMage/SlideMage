import importlib
import pkgutil

import pytest

import slidemage
from slidemage import project

from conftest import EXAMPLE


def test_example_is_a_project():
    assert project.is_project(EXAMPLE)
    assert project.find_upward(EXAMPLE / "decks") == EXAMPLE


def test_discover_prefers_env_var():
    assert project.discover() == EXAMPLE


def test_project_root_is_example():
    from slidemage import deck_scan

    assert deck_scan.PROJECT_ROOT == EXAMPLE


def test_scan_finds_demo_decks():
    from slidemage import deck_scan

    names = {deck.path.name for deck in deck_scan.scan_decks()}
    assert {"test.tex", "test-student.tex"} <= names


@pytest.mark.parametrize(
    "name", [m.name for m in pkgutil.iter_modules(slidemage.__path__)]
)
def test_module_imports(name):
    importlib.import_module(f"slidemage.{name}")


def test_main_window_builds():
    from PySide6.QtWidgets import QApplication

    from slidemage import qt_gui

    app = QApplication.instance() or QApplication([])
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())
    window.show()
    app.processEvents()
    window._log("line one")
    window.clear_log_button.click()
    assert window.log_text.toPlainText() == ""
    window.close()


def test_preferences_dialog_has_a_sensible_width():
    # Unwrapped description labels once made this dialog ~2200px wide.
    from PySide6.QtWidgets import QApplication

    from slidemage import qt_gui
    from slidemage.qt_settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())
    dialog = SettingsDialog(window)
    dialog.show()
    app.processEvents()
    assert dialog.width() < 1000
    dialog.close()
    window.close()


def test_preferences_ai_prompts_tab_holds_the_translation_prompts():
    from PySide6.QtWidgets import QApplication, QTabWidget

    from slidemage import qt_gui
    from slidemage.qt_settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())
    dialog = SettingsDialog(window)
    tabs = dialog.findChild(QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "General", "AI models", "AI prompts"]
    pages = dialog.ai_prompt_pages
    assert [pages.tabText(i) for i in range(pages.count())] == [
        "Image descriptions", "Slide rewrite", "Translation"]
    assert pages.widget(2) is dialog.translation_prompts_panel
    # General tab: one radio button per update mode, the saved one checked.
    from slidemage import updater
    buttons = dialog.update_mode_buttons
    assert list(buttons) == list(updater.UPDATE_MODES)
    assert [m for m, b in buttons.items() if b.isChecked()] == [updater.get_update_mode()]

    panel = dialog.translation_prompts_panel
    assert dialog._dirty_prompt_descriptions() == []
    saved_text = panel.default_prompt_edit.toPlainText()
    panel.default_prompt_edit.setPlainText(saved_text + " (edited)")
    assert dialog._dirty_prompt_descriptions() == ["the default translation prompt"]
    panel.default_prompt_edit.setPlainText(saved_text)  # close without the unsaved-changes box
    app.processEvents()
    dialog.close()
    window.close()
