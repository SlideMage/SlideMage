import importlib
import pkgutil

import pytest

import slidemage
from slidemage import project

from conftest import EXAMPLE, build_window


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
    assert "slidemage-manual.tex" in names


@pytest.mark.parametrize(
    "name", [m.name for m in pkgutil.walk_packages(slidemage.__path__, "slidemage.") if not m.ispkg]
)
def test_module_imports(name):
    importlib.import_module(name)


def test_main_window_builds(monkeypatch):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = build_window(monkeypatch)
    window.show()
    app.processEvents()
    window._log("line one")
    assert window.log_drawer.text.toPlainText() == "line one"
    window.log_drawer.clear()
    assert window.log_drawer.text.toPlainText() == ""
    window.close()
