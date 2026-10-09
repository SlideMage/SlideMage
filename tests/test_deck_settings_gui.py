"""The deck row's Settings button and dialog (formerly "Course link...")."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

from slidemage import deck_settings, qt_gui
from slidemage.deck_scan import Deck
from slidemage.deck_settings import DeckSettings
from slidemage.qt_deck_settings_dialog import DeckSettingsDialog
from slidemage.qt_deck_table import DeckTable
from slidemage.ui.kit.theme import ThemeManager

COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
TEMPLATES = [("slidemage", "SlideMage"), ("uni-graz", "University of Graz")]
DECK_TEXT = (
    "\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-graz}\n"
    "\\deckoutputfolder{D:/Out}\n\\newcommand{\\FooterText}{Course | 2027s}\n"
    "\\decklanguage[en]\n\\begin{document}\n"
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_deck(tmp_path, tags=(), text=DECK_TEXT) -> Deck:
    path = tmp_path / "course.tex"
    path.write_text(text, encoding="utf-8", newline="")
    return Deck(
        name="course", path=path, archived=False, text=text,
        supports_version=False, uses_biblatex=False, preamble_end=0,
        chapters=[], output_folders={}, tags=list(tags),
    )


def test_dialog_shows_the_deck_settings_and_returns_the_edited_ones(qapp):
    old = deck_settings.read_settings(DECK_TEXT)
    dialog = DeckSettingsDialog(None, "course", old, TEMPLATES)
    assert dialog.template_combo.currentData() == "uni-graz"
    assert dialog.language_combo.currentData() == "en"
    assert dialog.footer_edit.text() == "Course | 2027s"
    assert dialog.output_edits[None].text() == "D:/Out"
    assert not dialog.open_button.isEnabled()

    dialog.template_combo.setCurrentIndex(dialog.template_combo.findData("slidemage"))
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("de"))
    dialog.url_edit.setText(COURSE_URL)
    assert dialog.open_button.isEnabled()
    dialog.output_edits["presenter"].setText("E:\\Talks")
    dialog.appendix_check.setChecked(True)
    dialog._on_accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    new = dialog.result_settings()
    assert new.template == "slidemage" and new.language == "de"
    assert new.course_url == COURSE_URL
    assert new.output_folders == {None: "D:/Out", "presenter": "E:/Talks"}
    assert new.appendix_toc


def test_dialog_keeps_an_unknown_template_and_language_selectable(qapp):
    old = DeckSettings(template="my-uni", language="fr")
    dialog = DeckSettingsDialog(None, "x", old, TEMPLATES)
    assert dialog.template_combo.currentData() == "my-uni"
    assert dialog.language_combo.currentData() == "fr"


def test_dialog_refuses_a_bad_course_url(qapp, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    dialog = DeckSettingsDialog(None, "x", DeckSettings(template="uni-graz"), TEMPLATES)
    dialog.url_edit.setText("not a url")
    dialog._on_accept()
    assert warned and dialog.result() != QDialog.DialogCode.Accepted


def test_dialog_leaves_an_untouched_path_exactly_as_it_was(qapp):
    old = DeckSettings(template="uni-graz", output_folders={None: "D:\\Old\\Way"})
    dialog = DeckSettingsDialog(None, "x", old, TEMPLATES)
    dialog._on_accept()
    assert dialog.result_settings().output_folders == {None: "D:\\Old\\Way"}


def test_settings_action_saves_all_changes_then_opens_the_link(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)

    class AcceptedDialog:
        def __init__(self, _parent, _name, settings, _templates):
            self.settings = settings
            self.open_link_requested = True

        def exec(self):
            return 1

        def result_settings(self):
            new = DeckSettings(**vars(self.settings))
            new.template = "slidemage"
            new.course_url = COURSE_URL
            return new

    opened, refreshed, reloaded, logged = [], [], [], []
    monkeypatch.setattr(qt_gui, "DeckSettingsDialog", AcceptedDialog)
    monkeypatch.setattr(qt_gui.open_path, "open_in_default_app", opened.append)
    window = SimpleNamespace(
        _slide_source_tabs={}, _log=logged.append,
        refresh_open_deck_editors=lambda: refreshed.append(True),
        reload_decks=lambda: reloaded.append(True),
    )

    qt_gui.SlideMageWindow._on_deck_settings(window, deck)

    written = deck.path.read_text(encoding="utf-8")
    assert "\\input{Slidemaster_preamble_slidemage}" in written
    assert f"%% SlideMage course URL: {COURSE_URL}" in written
    assert opened == [COURSE_URL] and refreshed == [True] and reloaded == [True]
    assert "template" in logged[0] and "course url" in logged[0]


def test_settings_action_refuses_while_the_deck_source_is_open(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    window = SimpleNamespace(_slide_source_tabs={deck.path: object()})
    qt_gui.SlideMageWindow._on_deck_settings(window, deck)
    assert told and deck.path.read_text(encoding="utf-8") == DECK_TEXT


@pytest.mark.parametrize("archivable", [True, False])
@pytest.mark.parametrize("tags, enabled", [
    ([], True), (["course"], True), (["work"], True), (["research"], True),
    (["test"], True), (["manual"], False),
])
def test_settings_button_is_in_every_deck_row(tmp_path, qapp, archivable, tags, enabled):
    deck = make_deck(tmp_path, tags)
    clicked = []
    table = DeckTable(
        ThemeManager(), archivable=archivable,
        on_open=lambda _deck: None,
        on_archive=None, on_edit=None, on_duplicate=None, on_export_pptx=None,
        on_compile_selected=lambda _rows: None,
        on_stop_compilation=lambda: None,
        on_create_transcript=lambda _rows: None,
        on_refresh=lambda: None,
        on_settings=clicked.append,
    )
    table.rebuild([deck])

    buttons = [b for b in table.findChildren(QPushButton) if b.text().endswith("Settings")]
    assert len(buttons) == 1
    assert buttons[0].isEnabled() == enabled
    if enabled:
        buttons[0].click()
        assert clicked == [deck]
