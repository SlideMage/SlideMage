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
    window.close()
