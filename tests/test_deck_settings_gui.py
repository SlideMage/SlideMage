# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Deck settings sheet and the ⋮ menu entries that open it (formerly the deck row's Settings button)."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from PySide6.QtWidgets import QDialog, QMessageBox

from slidemage import deck_settings
from slidemage.deck_scan import Deck
from slidemage.deck_groups import DEFAULT_GROUPS, selectable_tags
from slidemage.ui.dialogs.deck_settings import GENERAL, OUTPUT, SAVE, DeckSettingsSheet
from slidemage.ui.workspace import deck_actions
from conftest import EXAMPLE_PROJECT

TEMPLATES = [("slidemage", "SlideMage"), ("acme", "Acme University")]
DECK_TEXT = (
    "\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n"
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


def make_sheet(tmp_path, text=DECK_TEXT, tab=GENERAL, **fields):
    template = tmp_path / "SlideMage_template_acme.tex"
    if not template.exists():
        template.write_text("% SlideMage modes: light, dark\n")
    return DeckSettingsSheet(None, make_deck(tmp_path, text=text, **fields), TEMPLATES, tab=tab)


def test_sheet_loads_existing_settings_and_saves_edits(tmp_path, qapp):
    sheet = make_sheet(tmp_path)
    assert sheet.template_combo.currentData() == "acme"
    assert sheet.language_combo.currentData() == "en"
    assert sheet.footer_edit.text() == "Course | 2027s"
    assert sheet.output_edits[None].text() == "D:/Out"
    assert sheet.open_pdf_combo.currentData() == "instructor"
    assert not sheet.dirty()

    select(sheet.template_combo, "slidemage")
    select(sheet.language_combo, "de")
    sheet.footer_edit.setText("Other")
    sheet.output_edits["presenter"].setText("E:\\Talks")
    sheet.appendix_check.setChecked(True)
    select(sheet.open_pdf_combo, "presenter")
    sheet.show()
    sheet.set_current_tab(OUTPUT)
    assert sheet.dirty() and sheet.save_button.isVisible()
    sheet.save_button.click()
    assert sheet.result() == QDialog.DialogCode.Accepted and sheet.action == SAVE
    new = sheet.result_settings()
    assert (new.template, new.language, new.footer_text) == ("slidemage", "de", "Other")
    assert new.output_folders == {None: "D:/Out", "presenter": "E:/Talks"}
    assert new.appendix_toc and new.open_pdf == "presenter"


def test_cancel_changes_nothing(tmp_path, qapp):
    sheet = make_sheet(tmp_path)
    sheet.footer_edit.setText("Something else")
    sheet.reject()
    assert sheet.result() != QDialog.DialogCode.Accepted and sheet.action == ""
    assert sheet.result_settings() == deck_settings.read_settings(DECK_TEXT)


def test_an_unknown_template_and_language_stay_selectable(tmp_path, qapp):
    text = DECK_TEXT.replace("acme", "my-uni").replace("decklanguage[en]", "decklanguage[fr]")
    sheet = make_sheet(tmp_path, text=text)
    assert sheet.template_combo.currentData() == "my-uni"
    assert sheet.language_combo.currentData() == "fr"


def test_an_untouched_path_stays_exactly_as_it_was(tmp_path, qapp):
    text = DECK_TEXT.replace("D:/Out", "D:\\Old\\Way")
    sheet = make_sheet(tmp_path, text=text)
    sheet.save_button.click()
    assert sheet.result_settings().output_folders == {None: "D:\\Old\\Way"}


def test_unchanged_settings_write_nothing(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    events = []
    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", lambda *_args, **_kwargs: accepted_sheet(deck))
    deck_actions.on_deck_settings(action_window(events), deck)
    assert events == [] and deck.path.read_bytes() == DECK_TEXT.encode()


def test_settings_action_refuses_while_the_deck_source_has_edits_that_could_not_be_saved(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    window = SimpleNamespace(centre=SimpleNamespace(unsaved=lambda path: path == deck.path), project=EXAMPLE_PROJECT)
    deck_actions.on_deck_settings(window, deck)
    assert told and deck.path.read_text(encoding="utf-8") == DECK_TEXT


@pytest.mark.parametrize("field,value,mode", [
    ("footer_hide", ("id", "deck"), "preview"),
    ("footer_text", "New footer", "split"),
    ("mode", "dark", "split"),
    ("footer_text", "New footer", "source"),
])
def test_footer_changes_render_the_visible_preview_after_reloading(tmp_path, qapp, field, value, mode):
    deck = make_deck(tmp_path)
    old = deck_settings.read_settings(deck.text)
    new = replace(old, **{field: value})
    events = []
    window = action_window(events)
    window.state = SimpleNamespace(deck=deck, mode=mode)
    window.centre.preview = SimpleNamespace(render_after_save=lambda: events.append("render"))
    deck_actions.save_deck_settings(window, deck, old, new)
    assert getattr(deck_settings.read_settings(deck.path.read_text()), field) == value
    assert field.replace("_", " ") in events[0]
    assert events[1:] == ["editors", "reload"] + (["render"] if mode != "source" else [])


def test_dark_slides_round_trip_and_are_removed_for_an_unsupported_template(tmp_path, qapp):
    renamed = DECK_TEXT.replace("acme", "custom-college")
    (tmp_path / "SlideMage_template_custom-college.tex").write_text("% SlideMage modes: light, dark\n")
    sheet = make_sheet(tmp_path, text=renamed)
    assert sheet.mode_combo.isEnabled() and sheet.mode_combo.currentData() == "light"
    select(sheet.mode_combo, "dark")
    saved = save_mode(sheet, "dark")

    reopened = make_sheet(tmp_path, text=saved)
    assert reopened.mode_combo.currentData() == "dark" and not reopened.dirty()
    select(reopened.mode_combo, "light")
    assert save_mode(reopened, "") == renamed

    reopened = make_sheet(tmp_path, text=saved)
    select(reopened.template_combo, "slidemage")
    assert reopened.mode_combo.isEnabled() and reopened.mode_combo.currentData() == "dark"

    (tmp_path / "SlideMage_template_slidemage.tex").write_text("\\input{SlideMage_setup}\n")
    unsupported = make_sheet(tmp_path, text=saved)
    select(unsupported.template_combo, "slidemage")
    assert not unsupported.mode_combo.isEnabled()
    changed = save_mode(unsupported, "")
    assert r"\SMModeOverride" not in changed and r"\SMDarkMode" not in changed


def select(combo, value):
    combo.setCurrentIndex(combo.findData(value))


def save_mode(sheet, mode):
    assert sheet.dirty()
    sheet.save_button.click()
    assert sheet.action == SAVE and sheet.result_settings().mode == mode
    return deck_settings.apply_settings(sheet.deck.text, sheet.original, sheet.result_settings())


def test_a_template_with_more_modes_offers_them_for_the_deck_and_each_view(tmp_path, qapp):
    (tmp_path / "SlideMage_template_acme.tex").write_text("% SlideMage modes: light, dark, gray=Grayscale\n")
    sheet = make_sheet(tmp_path)
    assert [sheet.mode_combo.itemData(i) for i in range(sheet.mode_combo.count())] == ["light", "dark", "gray"]
    select(sheet.mode_combo, "gray")
    saved = save_mode(sheet, "gray")
    assert "\\newcommand{\\SMModeOverride}{gray}" in saved
    reopened = make_sheet(tmp_path, text=saved)
    assert reopened.mode_combo.currentData() == "gray" and not reopened.dirty()

    versioned = DeckSettingsSheet(None, replace(make_deck(tmp_path), supports_version=True), TEMPLATES)
    view = versioned.view_combos["instructor"]
    select(view, "acme")
    modes = versioned.view_mode["instructor"]
    assert modes.isEnabled() and [modes.itemData(i) for i in range(modes.count())] == ["", "dark", "gray"]
    select(modes, "gray")
    assert versioned._view_theme_entries() == {"instructor": ("acme", "gray")}


def accepted_sheet(deck, tags=(), **changes):
    old = deck_settings.read_settings(deck.text)
    return SimpleNamespace(deck=deck, original=old, action=SAVE, exec=lambda: 1, groups_changed=bool(tags),
                           chosen_groups=tags, result_settings=lambda: replace(old, **changes))


def action_window(events):
    return SimpleNamespace(
        centre=SimpleNamespace(unsaved=lambda _path: False), project=EXAMPLE_PROJECT,
        deck_groups=DEFAULT_GROUPS, log=events.append,
        refresh_open_deck_editors=lambda: events.append("editors"), reload_decks=lambda: events.append("reload"),
    )


def test_saving_changed_tags_writes_them_and_the_settings_in_one_go(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    tag = selectable_tags(DEFAULT_GROUPS)[0]
    events = []
    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", lambda *_args, **_kwargs: accepted_sheet(
        deck, (tag,), template="slidemage", open_pdf="presenter"))
    deck_actions.on_deck_settings(action_window(events), deck)
    written = deck.path.read_text(encoding="utf-8")
    assert f"\\decktags{{{tag}}}" in written
    assert "\\input{SlideMage_template_slidemage}" in written and "%% SlideMage open PDF: presenter" in written
    assert "Tagged" in events[0] and "template, open pdf" in events[3]
    assert events[1:3] == events[4:] == ["editors", "reload"]


def test_a_file_name_next_to_a_folder_is_stored_as_one_path_and_shown_split(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path)
    assert sheet.output_names[None].text() == "" and not sheet.dirty()
    sheet.output_names[None].setText("Handout.pdf")                # with the extension, which is dropped
    sheet.output_names["transcript"].setText("Notes")
    assert sheet.dirty()
    sheet.save_button.click()
    assert sheet.result_settings().output_folders == {None: "D:/Out/Handout.pdf", "transcript": "D:/Out/Notes.md"}
