# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin deck edits (edit_deck_text, insert_slides) end to end: they run the window's edit lifecycle (rescan, Undo),
insertion is all-or-nothing even when a write fails halfway, and a plugin cannot write a deck whose Deck settings
sheet holds unsaved changes (and the sheet takes over an edit made while it is clean)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import DECK_TEXT, build_window, make_project, qapp as qapp
from slidemage import deck_scan, plugin_api
from slidemage.plugins import host as host_module
from slidemage.plugins import loader, session
from slidemage.plugins.host import PluginHost, deck_snapshot
from slidemage.plugins.manifest import read_manifest
from slidemage.project import ProjectContext
from slidemage.ui import app as app_module
from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet
from slidemage.ui.plugin_ui import HOST_UI
from slidemage.ui.workspace import deck_actions

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
DECK = DECK_TEXT.replace("\\begin{document}", "\\input{Slidemaster_preamble_uni-graz}\r\n\\begin{document}", 1)
MARKER = "%% marker: set\r\n"
COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(host_module.project, "config_dir", lambda: tmp_path / "config")
    yield
    session.set_loaded([])
    sys.modules.pop("deckedit", None)


# -- the host without a window ---------------------------------------------------------------------------------

@pytest.fixture
def pctx(tmp_path, monkeypatch):
    return ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))


@pytest.fixture
def host(pctx):
    return PluginHost(read_manifest(FIXTURES / "hello"), pctx)


def snap(pctx):
    return deck_snapshot(deck_scan.read_deck(pctx.decks_dir / "test.tex"), pctx)


def tex_files(pctx):
    return {p.name: p.read_bytes() for p in pctx.slides_dir.iterdir()}


class RecordingUi:
    def __init__(self):
        self.edits = []

    def after_deck_edit(self, path, summary, previous_text):
        self.edits.append((path, summary, previous_text))


def test_the_window_is_told_after_each_successful_edit_with_the_previous_text(pctx):
    ui = RecordingUi()
    host = PluginHost(read_manifest(FIXTURES / "hello"), pctx, ui)
    deck = snap(pctx)
    host.edit_deck_text(deck, lambda t: t.replace("Intro", "Start"))
    assert ui.edits == [(deck.path, "Edited test (hello fixture)", deck.text)]
    deck = snap(pctx)
    host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a"), ("B", "b")], "en")
    assert ui.edits[1] == (deck.path, "Inserted 2 slide(s) into test (hello fixture)", deck.text)
    host.edit_deck_text(snap(pctx), lambda t: t)            # no change, no history entry
    assert len(ui.edits) == 2


def test_a_failed_edit_does_not_notify_the_window(pctx):
    ui = RecordingUi()
    host = PluginHost(read_manifest(FIXTURES / "hello"), pctx, ui)
    deck = snap(pctx)
    (pctx.decks_dir / "test.tex").write_bytes(b"other")
    with pytest.raises(plugin_api.StaleFileError):
        host.edit_deck_text(deck, lambda t: t + "x")
    assert ui.edits == []


def test_a_window_failure_after_the_edit_does_not_fail_the_plugin(pctx):
    class Broken(RecordingUi):
        def after_deck_edit(self, *args):
            raise RuntimeError("gui")

    host = PluginHost(read_manifest(FIXTURES / "hello"), pctx, Broken())
    deck = snap(pctx)
    assert host.edit_deck_text(deck, lambda t: t + "x") == deck.text + "x"




# -- the window ------------------------------------------------------------------------------------------------

@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    root = make_project(monkeypatch, tmp_path / "proj")
    (root / "decks" / "test.tex").write_bytes(DECK.encode())
    ctx = ProjectContext.at(root)
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, str(FIXTURES / "deckedit"))
    app_module.load_plugins(ctx)
    window = build_window(monkeypatch, ctx)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    return window


def sheet_of(window):
    sheet = DeckSettingsSheet(window, window.state.deck, [], tab="Edit")
    return sheet, sheet.plugin_tabs[sheet.current_tab()][1]


def disk(window):
    return window.state.deck.path.read_bytes().decode()


def test_a_plugin_save_reaches_the_window_and_the_reopened_sheet_and_is_undoable(window, monkeypatch):
    sheet, page = sheet_of(window)
    page.save_button.click()
    assert page.error == "" and MARKER in disk(window)
    assert window.state.deck.text == disk(window)                 # rescanned, not the old snapshot
    sheet.close()
    reopened, other = sheet_of(window)
    assert MARKER in other.deck.text                               # the next snapshot has the new text
    reopened.close()
    opened = []
    monkeypatch.setattr(deck_actions, "on_deck_settings", lambda w, deck, tab: opened.append(deck))
    HOST_UI.open_deck_settings(deck_snapshot(window.state.deck))   # looks up the rescanned deck
    assert MARKER in opened[0].text
    window.slide_list.undo()
    assert MARKER not in disk(window) and disk(window) == DECK
    assert MARKER not in window.state.deck.text


def test_a_plugin_insert_shows_the_calls_in_the_slide_list_and_is_undoable(window):
    sheet, page = sheet_of(window)
    sheet.plugin_button.click()
    assert page.error == ""
    calls = [line for line in disk(window).split("\r\n") if line.startswith("\\slide{")]
    assert len(calls) == 3 and "-EN-Fixture" in calls[-1]
    new_slug = calls[-1][len("\\slide{"):-1]
    assert [row.call.id_slug for row in window.slide_list.rows()][-1] == new_slug       # the list shows the call
    sheet.close()
    window.slide_list.undo()
    assert disk(window) == DECK
    assert new_slug not in [row.call.id_slug for row in window.slide_list.rows()]



