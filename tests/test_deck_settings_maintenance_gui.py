# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deck settings hands maintenance commands back to the window."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from slidemage.ui.dialogs.deck_settings import COMMAND, DeckSettingsSheet
from slidemage.ui.workspace import deck_actions
from conftest import EXAMPLE_PROJECT, command_context
from test_deck_settings_gui import TEMPLATES, make_deck
from slidemage.ui.dialogs import deck_settings as sheet_module

IDS = ["create_snapshot", "rerender_deck_previews", "update_deck_versions"]


class Window(QWidget):
    def __init__(self, deck=None):
        super().__init__()
        self.__dict__.update(vars(command_context(deck)))


@pytest.fixture
def make_sheet(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(sheet_module, "add_route_badge", lambda *_args: None)       # the stand-in has no AI state
    (tmp_path / "SlideMage_template_acme.tex").write_text("")
    windows = []

    def make(*, with_deck=True):
        deck = make_deck(tmp_path)
        windows.append(Window(deck if with_deck else None))      # keeps the parent alive
        return DeckSettingsSheet(windows[-1], deck, TEMPLATES)
    return make


def ask(monkeypatch, answer):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(args[2]) or answer)
    return asked


@pytest.mark.parametrize("command_id", IDS)
def test_a_button_closes_the_unchanged_sheet_without_prompting(make_sheet, command_id, monkeypatch):
    sheet = make_sheet()
    asked = ask(monkeypatch, QMessageBox.StandardButton.Cancel)
    sheet.maintenance_buttons[command_id].click()
    assert not asked and sheet.result() == QDialog.DialogCode.Accepted and sheet.action == COMMAND + command_id


def test_unsaved_changes_are_asked_about_and_cancel_keeps_the_sheet_open(make_sheet, monkeypatch):
    sheet = make_sheet()
    sheet.footer_edit.setText("Changed")
    asked = ask(monkeypatch, QMessageBox.StandardButton.Cancel)
    sheet.maintenance_buttons["create_snapshot"].click()
    assert len(asked) == 1 and sheet.action == "" and sheet.result() != QDialog.DialogCode.Accepted

    ask(monkeypatch, QMessageBox.StandardButton.Discard)
    sheet.maintenance_buttons["create_snapshot"].click()
    assert sheet.action == COMMAND + "create_snapshot" and sheet.result() == QDialog.DialogCode.Accepted


def test_a_button_is_disabled_when_its_command_is_not_enabled(make_sheet):
    sheet = make_sheet(with_deck=False)          # no deck in the window: only the snapshot command is left
    assert {cid: b.isEnabled() for cid, b in sheet.maintenance_buttons.items()} == {
        "create_snapshot": True, "rerender_deck_previews": False, "update_deck_versions": False}


def test_the_window_runs_the_command_after_the_sheet_has_closed(make_sheet, monkeypatch):
    sheet = make_sheet()
    events = []

    def fake_exec():
        sheet.maintenance_buttons["rerender_deck_previews"].click()
        events.append(("closed", sheet.result()))
        return sheet.result()

    sheet.exec = fake_exec
    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", lambda *_args, **_kwargs: sheet)
    window = SimpleNamespace(
        centre=SimpleNamespace(unsaved=lambda _path: False), project=EXAMPLE_PROJECT,
        commands=SimpleNamespace(run=lambda command_id, ctx: events.append((command_id, ctx))), deck_groups=())
    deck_actions.on_deck_settings(window, sheet.deck)
    assert events == [("closed", QDialog.DialogCode.Accepted), ("rerender_deck_previews", window)]
