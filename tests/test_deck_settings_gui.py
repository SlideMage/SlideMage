# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Deck settings sheet and the ⋮ menu entries that open it (formerly the deck row's Settings button)."""
from __future__ import annotations

import pytest

from types import SimpleNamespace

from PySide6.QtWidgets import QDialog, QMessageBox

from slidemage import deck_settings
from slidemage.deck_scan import Deck
from slidemage.deck_settings import DeckSettings
from slidemage.ui.dialogs.deck_settings import GENERAL, OUTPUT, SAVE, DeckSettingsSheet
from slidemage.ui.workspace import deck_actions
from conftest import EXAMPLE_PROJECT

TEMPLATES = [("slidemage", "SlideMage"), ("uni-graz", "University of Graz")]
DECK_TEXT = (
    "\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-graz}\n"
    "\\deckoutputfolder{D:/Out}\n\\newcommand{\\FooterText}{Course | 2027s}\n"
    "\\decklanguage[en]\n\\begin{document}\n"
)


def make_deck(tmp_path, tags=(), text=DECK_TEXT, **fields) -> Deck:
    path = tmp_path / "course.tex"
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=list(tags), **fields,
    )


def make_sheet(tmp_path, monkeypatch, text=DECK_TEXT, tab=GENERAL, **fields):
    (tmp_path / "Slidemaster_preamble_uni-graz.tex").write_text("% SlideMage dark mode: true\n")
    return DeckSettingsSheet(None, make_deck(tmp_path, text=text, **fields), TEMPLATES, tab=tab)


def test_the_sheet_shows_the_deck_settings(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    assert sheet.template_combo.currentData() == "uni-graz"
    assert sheet.language_combo.currentData() == "en"
    assert sheet.footer_edit.text() == "Course | 2027s"
    assert sheet.output_edits[None].text() == "D:/Out"
    assert sheet.open_pdf_combo.currentData() == "instructor"
    assert not sheet.dirty()


def test_save_returns_the_edited_checked_settings(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.template_combo.setCurrentIndex(sheet.template_combo.findData("slidemage"))
    sheet.language_combo.setCurrentIndex(sheet.language_combo.findData("de"))
    sheet.footer_edit.setText("Other")
    assert sheet.dirty()
    sheet.output_edits["presenter"].setText("E:\\Talks")
    sheet.appendix_check.setChecked(True)
    sheet.open_pdf_combo.setCurrentIndex(sheet.open_pdf_combo.findData("presenter"))
    sheet.save_button.click()

    assert sheet.result() == QDialog.DialogCode.Accepted and sheet.action == SAVE
    new = sheet.result_settings()
    assert new.template == "slidemage" and new.language == "de"
    assert new.output_folders == {None: "D:/Out", "presenter": "E:/Talks"}
    assert new.appendix_toc and new.open_pdf == "presenter"


def test_cancel_changes_nothing(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.footer_edit.setText("Something else")
    sheet.reject()
    assert sheet.result() != QDialog.DialogCode.Accepted and sheet.action == ""
    assert sheet.result_settings() == deck_settings.read_settings(DECK_TEXT)


def test_an_unknown_template_and_language_stay_selectable(tmp_path, monkeypatch, qapp):
    text = DECK_TEXT.replace("uni-graz", "my-uni").replace("decklanguage[en]", "decklanguage[fr]")
    sheet = make_sheet(tmp_path, monkeypatch, text=text)
    assert sheet.template_combo.currentData() == "my-uni"
    assert sheet.language_combo.currentData() == "fr"


def test_an_untouched_path_stays_exactly_as_it_was(tmp_path, monkeypatch, qapp):
    text = DECK_TEXT.replace("D:/Out", "D:\\Old\\Way")
    sheet = make_sheet(tmp_path, monkeypatch, text=text)
    sheet.save_button.click()
    assert sheet.result_settings().output_folders == {None: "D:\\Old\\Way"}


def test_the_footer_follows_the_tab(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.show()
    assert sheet.save_button.isVisible()
    sheet.set_current_tab(OUTPUT)
    assert sheet.save_button.isVisible()
    sheet.close()


def test_settings_action_saves_all_changes(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)

    class AcceptedSheet:
        def __init__(self, _parent, deck, _templates, tab):
            self.original = deck_settings.read_settings(deck.text)
            self.action = SAVE

        def exec(self):
            return 1

        def result_settings(self):
            new = DeckSettings(**vars(self.original))
            new.template = "slidemage"
            new.open_pdf = "presenter"
            return new

    refreshed, reloaded, logged = [], [], []
    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", AcceptedSheet)
    window = SimpleNamespace(
        centre=SimpleNamespace(unsaved=lambda _path: False), log=logged.append, project=EXAMPLE_PROJECT,
        refresh_open_deck_editors=lambda: refreshed.append(True),
        reload_decks=lambda: reloaded.append(True),
    )

    deck_actions.on_deck_settings(window, deck)

    written = deck.path.read_text(encoding="utf-8")
    assert "\\input{Slidemaster_preamble_slidemage}" in written
    assert "%% SlideMage open PDF: presenter" in written
    assert refreshed == [True] and reloaded == [True]
    assert "template" in logged[0] and "open pdf" in logged[0]


def test_unchanged_settings_write_nothing(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)

    class SameSheet:
        action = SAVE

        def __init__(self, _parent, deck, _templates, tab):
            self.original = deck_settings.read_settings(deck.text)

        def exec(self):
            return 1

        def result_settings(self):
            return self.original

    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", SameSheet)
    logged = []
    window = SimpleNamespace(centre=SimpleNamespace(unsaved=lambda _path: False), log=logged.append, project=EXAMPLE_PROJECT)
    deck_actions.on_deck_settings(window, deck)
    assert logged == [] and deck.path.read_text(encoding="utf-8") == DECK_TEXT


def test_settings_action_refuses_while_the_deck_source_has_edits_that_could_not_be_saved(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    window = SimpleNamespace(centre=SimpleNamespace(unsaved=lambda path: path == deck.path), project=EXAMPLE_PROJECT)
    deck_actions.on_deck_settings(window, deck)
    assert told and deck.path.read_text(encoding="utf-8") == DECK_TEXT


@pytest.mark.parametrize("field,value", [("footer_hide", ("id", "deck")), ("footer_text", "New footer"), ("dark_mode", True)])
@pytest.mark.parametrize("mode", ["preview", "split", "source"])
def test_footer_changes_render_the_visible_preview_after_reloading(tmp_path, qapp, field, value, mode):
    deck = make_deck(tmp_path)
    old = deck_settings.read_settings(deck.text)
    new = DeckSettings(**vars(old))
    setattr(new, field, value)
    events = []
    window = SimpleNamespace(
        state=SimpleNamespace(deck=deck, mode=mode),
        centre=SimpleNamespace(preview=SimpleNamespace(render_after_save=lambda: events.append("render"))),
        log=lambda message: events.append(message),
        refresh_open_deck_editors=lambda: events.append("editors"),
        reload_decks=lambda: events.append("reload"),
    )

    deck_actions.save_deck_settings(window, deck, old, new)

    assert deck_settings.read_settings(deck.path.read_text()).footer_hide == new.footer_hide
    assert field.replace("_", " ") in events[0]
    assert events[1:] == ["editors", "reload"] + (["render"] if mode != "source" else [])



def test_dark_slides_setting_saves_reopens_and_disables_for_other_templates(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    assert sheet.dark_mode_check.isEnabled() and not sheet.dark_mode_check.isChecked()
    sheet.dark_mode_check.setChecked(True)
    assert sheet.dirty()
    sheet.save_button.click()
    assert sheet.action == SAVE and sheet.result_settings().dark_mode
    saved = deck_settings.apply_settings(DECK_TEXT, sheet.original, sheet.result_settings())
    reopened = make_sheet(tmp_path, monkeypatch, text=saved)
    assert reopened.dark_mode_check.isChecked() and not reopened.dirty()
    reopened.dark_mode_check.setChecked(False)
    assert reopened.dirty()
    reopened.save_button.click()
    assert deck_settings.apply_settings(saved, reopened.original, reopened.result_settings()) == DECK_TEXT

    other = make_sheet(tmp_path, monkeypatch, text=saved)
    other.template_combo.setCurrentIndex(other.template_combo.findData("slidemage"))
    assert not other.dark_mode_check.isEnabled()
    other.save_button.click()
    assert not other.result_settings().dark_mode
    changed = deck_settings.apply_settings(saved, other.original, other.result_settings())
    assert r"\SMDarkMode" not in changed


def test_dark_slides_work_for_a_renamed_template(tmp_path, monkeypatch, qapp):
    (tmp_path / "Slidemaster_preamble_custom-college.tex").write_text("% SlideMage dark mode: true\n")
    sheet = make_sheet(tmp_path, monkeypatch, text=DECK_TEXT.replace("uni-graz", "custom-college"))
    assert sheet.dark_mode_check.isEnabled()
    sheet.dark_mode_check.setChecked(True)
    sheet.save_button.click()
    assert sheet.result_settings().dark_mode
