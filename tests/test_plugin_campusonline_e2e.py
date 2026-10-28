# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real CampusOnline plugin against the real host (PLUGIN_HOST_PLAN step 9): it is built to its own drafted
Host Protocol, so this is where a mismatch between that draft and plugin_api shows. Runs only when
SLIDEMAGE_E2E_CAMPUSONLINE names a checkout of slidemage-plugin-campusonline; skipped otherwise."""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

import pytest

from conftest import DECK_TEXT, build_window, make_project, qapp as qapp
from slidemage.plugins import loader, session
from slidemage.project import ProjectContext
from slidemage.ui import app as app_module
from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet

CHECKOUT = os.environ.get("SLIDEMAGE_E2E_CAMPUSONLINE", "")
pytestmark = pytest.mark.skipif(not (CHECKOUT and (Path(CHECKOUT) / "plugin.toml").is_file()),
                                reason="SLIDEMAGE_E2E_CAMPUSONLINE names no plugin checkout")
COURSE_URL = "https://online.uni-graz.at/kfu_online/ee/ui/ca2/app/desktop/#/slc.tm.cp/student/courses/1002516"
LINKED = DECK_TEXT.replace("\\begin{document}", f"%% SlideMage course URL: {COURSE_URL}\r\n\\begin{{document}}", 1)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    root = make_project(monkeypatch, tmp_path / "proj")
    (root / "decks" / "test.tex").write_bytes(LINKED.encode())
    ctx = ProjectContext.at(root)
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, CHECKOUT)
    # The plugin asks for the first SlideMage with the host (>=9.0); this branch is still numbered below it.
    monkeypatch.setattr(loader, "load_all", functools.partial(loader.load_all, app_version="v9.0.0"))
    app_module.load_plugins(ctx)
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    yield window
    session.set_loaded([])
    for name in [m for m in sys.modules if m == "campusonline" or m.startswith("campusonline.")]:
        del sys.modules[name]


def test_the_plugin_activates_against_the_real_host(window):
    [plugin] = [p for p in session.loaded() if p.id == "campusonline"]
    assert plugin.state == "loaded", plugin.reason
    ids = {c.id for c in window.commands}
    assert {"campusonline.admin_slides", "campusonline.open_course_page"} <= ids
    assert window.commands["campusonline.open_course_page"].enabled(window)


def test_the_course_tab_and_the_box_build(window):
    sheet = DeckSettingsSheet(window, window.state.deck, [], tab="Course")
    assert "Course" in [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]
    sheet.close()
    box = window.side_panels.panels["plugin:campusonline:course"]
    assert box.offered()
    box.refresh()
