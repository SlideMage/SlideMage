import importlib
import pkgutil

import pytest

import slidemage
from slidemage import project

from conftest import EXAMPLE


@pytest.mark.parametrize("available", [True, False])
def test_project_discovery(monkeypatch, tmp_path, available):
    if available:
        assert project.is_project(EXAMPLE)
        assert project.find_upward(EXAMPLE / "decks") == EXAMPLE
        assert project.discover() == EXAMPLE
    else:
        # 2026-09-23: an unrelated cwd must not invent a last project on first run.
        monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
        monkeypatch.delenv(project.ENV_VAR, raising=False)
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        monkeypatch.chdir(unrelated)
        assert project.discover() is None


def test_scan_finds_demo_decks():
    from slidemage import deck_scan

    names = {deck.path.name for deck in deck_scan.scan_decks()}
    assert "slidemage-manual.tex" in names


@pytest.mark.parametrize(
    "name", [m.name for m in pkgutil.walk_packages(slidemage.__path__, "slidemage.") if not m.ispkg]
)
def test_module_imports(name):
    importlib.import_module(name)
