# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from slidemage import deck_scan, project

from conftest import EXAMPLE_PROJECT, EXAMPLE


@pytest.mark.parametrize("available", [True, False])
def test_project_discovery(monkeypatch, tmp_path, available):
    if available:
        assert project.is_project(EXAMPLE)
        assert project.find_upward(EXAMPLE / "decks") == EXAMPLE
        monkeypatch.setenv(project.ENV_VAR, str(EXAMPLE))
        assert project.discover() == EXAMPLE
        assert any(deck.name == "slidemage-manual" for deck in deck_scan.scan_decks(EXAMPLE_PROJECT))
    else:
        # 2026-09-23: an unrelated cwd must not invent a last project on first run.
        monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
        monkeypatch.delenv(project.ENV_VAR, raising=False)
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        monkeypatch.chdir(unrelated)
        assert project.discover() is None
