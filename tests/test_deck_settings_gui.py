"""The Deck settings sheet and the ⋮ menu entries that open it (formerly the deck row's Settings button)."""
from __future__ import annotations

import pytest

from types import SimpleNamespace

from PySide6.QtWidgets import QDialog, QMessageBox

from slidemage import deck_settings
from slidemage.course_schedule import CourseSchedule
from slidemage.deck_scan import Deck
from slidemage.deck_settings import DeckSettings
from slidemage.ui.dialogs import deck_settings as sheet_module
from slidemage.ui.dialogs.deck_settings import ADMIN, GENERAL, INSERT, OUTPUT, SAVE, DeckSettingsSheet
from slidemage.ui.workspace import deck_actions
from conftest import EXAMPLE_PROJECT, command_context
from slidemage.ui.workspace.menus import build_more_menu
from test_admin_slides import DETAIL, GROUP

COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
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
    monkeypatch.setattr(sheet_module.AdminSlidesTab, "start", lambda self: None)     # no network
    return DeckSettingsSheet(None, make_deck(tmp_path, text=text, **fields), TEMPLATES, tab=tab)


def test_the_sheet_shows_the_deck_settings(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    assert sheet.template_combo.currentData() == "uni-graz"
    assert sheet.language_combo.currentData() == "en"
    assert sheet.footer_edit.text() == "Course | 2027s"
    assert sheet.output_edits[None].text() == "D:/Out"
    assert sheet.open_pdf_combo.currentData() == "instructor"
    assert not sheet.open_button.isEnabled() and not sheet.dirty()


def test_save_returns_the_edited_checked_settings(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.template_combo.setCurrentIndex(sheet.template_combo.findData("slidemage"))
    sheet.language_combo.setCurrentIndex(sheet.language_combo.findData("de"))
    sheet.url_edit.setText(COURSE_URL)
    assert sheet.open_button.isEnabled() and sheet.dirty()
    sheet.output_edits["presenter"].setText("E:\\Talks")
    sheet.appendix_check.setChecked(True)
    sheet.open_pdf_combo.setCurrentIndex(sheet.open_pdf_combo.findData("presenter"))
    sheet.save_button.click()

    assert sheet.result() == QDialog.DialogCode.Accepted and sheet.action == SAVE
    new = sheet.result_settings()
    assert new.template == "slidemage" and new.language == "de"
    assert new.course_url == COURSE_URL
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


def test_a_bad_course_link_shows_under_the_form_and_the_sheet_stays_open(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.url_edit.setText("not a url")
    sheet.save_button.click()
    assert sheet.result() != QDialog.DialogCode.Accepted and sheet.action == ""
    assert "Course link" in sheet.note.text() and sheet.note.property("tone") == "error"


def test_an_untouched_path_stays_exactly_as_it_was(tmp_path, monkeypatch, qapp):
    text = DECK_TEXT.replace("D:/Out", "D:\\Old\\Way")
    sheet = make_sheet(tmp_path, monkeypatch, text=text)
    sheet.save_button.click()
    assert sheet.result_settings().output_folders == {None: "D:\\Old\\Way"}


def test_open_link_opens_the_address_as_typed_without_saving(tmp_path, monkeypatch, qapp):
    opened = []
    monkeypatch.setattr(sheet_module.open_path, "open_in_default_app", opened.append)
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.url_edit.setText(COURSE_URL)
    sheet.open_button.click()
    assert opened == [COURSE_URL] and sheet.action == ""
    sheet.url_edit.setText("nonsense")
    sheet.open_button.click()
    assert opened == [COURSE_URL] and sheet.note.property("tone") == "error"


def test_the_footer_follows_the_tab(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch)
    sheet.show()
    assert sheet.save_button.isVisible() and not sheet.insert_button.isVisible()
    sheet.set_current_tab(OUTPUT)
    assert sheet.save_button.isVisible() and not sheet.insert_button.isVisible()
    sheet.set_current_tab(ADMIN)
    assert not sheet.save_button.isVisible() and sheet.insert_button.isVisible()
    assert not sheet.insert_button.isEnabled()        # nothing planned yet
    sheet.close()


def test_insert_slides_waits_for_unsaved_form_changes(tmp_path, monkeypatch, qapp):
    sheet = make_sheet(tmp_path, monkeypatch, tab=ADMIN, course_url=COURSE_URL)
    sheet.show()
    sheet.admin._on_loaded(CourseSchedule((GROUP,)), DETAIL)
    assert sheet.insert_button.isEnabled() and sheet.note.text() == ""

    sheet.footer_edit.setText("Changed")
    assert sheet.save_button.isVisible() and not sheet.insert_button.isEnabled()
    assert "Save the deck settings first" in sheet.note.text()
    sheet.footer_edit.setText("Course | 2027s")
    assert sheet.insert_button.isEnabled() and not sheet.save_button.isVisible()

    sheet.insert_button.click()
    assert sheet.action == INSERT and sheet.result() == QDialog.DialogCode.Accepted
    assert [suffix for suffix, _ in sheet.admin.slide_specs] == ["Title-Slide", "Course-Sessions"]


def test_the_admin_tab_is_fetched_when_first_shown_and_cancelled_on_close(tmp_path, monkeypatch, qapp):
    started = []
    sheet = make_sheet(tmp_path, monkeypatch, course_url=COURSE_URL)
    monkeypatch.setattr(sheet.admin, "start", lambda: started.append(1))
    assert started == []
    sheet.set_current_tab(ADMIN)
    assert started == [1]
    sheet.reject()
    sheet.admin._on_loaded(CourseSchedule((GROUP,)), DETAIL)         # a late answer
    assert sheet.admin.slide_specs == []


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
            new.course_url = COURSE_URL
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
    assert f"%% SlideMage course URL: {COURSE_URL}" in written
    assert "%% SlideMage open PDF: presenter" in written
    assert refreshed == [True] and reloaded == [True]
    assert "template" in logged[0] and "course url" in logged[0] and "open pdf" in logged[0]


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


def test_insert_action_creates_the_slides_and_opens_the_first(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    inserted, edits, opened = [], [], []
    admin = SimpleNamespace(position="position", slide_specs=[("Course-Sessions", "source")], language="de")

    class InsertSheet:
        action = INSERT

        def __init__(self, _parent, _deck, _templates, tab):
            self.admin = admin
            self.tab = tab
            tabs.append(tab)

        def exec(self):
            return 1

    tabs = []
    monkeypatch.setattr(deck_actions, "DeckSettingsSheet", InsertSheet)
    monkeypatch.setattr(deck_actions.admin_slides, "insert_admin_slides",
                        lambda *args: inserted.append(args) or [tmp_path / "new-current.tex"])
    window = SimpleNamespace(
        centre=SimpleNamespace(unsaved=lambda _path: False), project=EXAMPLE_PROJECT,
        after_deck_edit=lambda *args, **kwargs: edits.append((args, kwargs)), open_slide_editor=opened.append)

    deck_actions.on_admin_slides(window, deck)

    assert tabs == [ADMIN]                                      # the Admin slides entry opens that tab
    assert inserted == [(EXAMPLE_PROJECT, deck, "position", admin.slide_specs, "de")]
    assert edits == [((deck.path, "Inserted admin slides into course"), {"previous_text": deck.text})]
    assert opened == [tmp_path / "new-current.tex"]


def test_settings_action_refuses_while_the_deck_source_has_edits_that_could_not_be_saved(tmp_path, monkeypatch, qapp):
    deck = make_deck(tmp_path)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    window = SimpleNamespace(centre=SimpleNamespace(unsaved=lambda path: path == deck.path), project=EXAMPLE_PROJECT)
    deck_actions.on_deck_settings(window, deck)
    assert told and deck.path.read_text(encoding="utf-8") == DECK_TEXT


def test_admin_slides_entry_is_only_for_a_linked_course_deck(tmp_path, qapp):
    def enabled(deck):
        menu = build_more_menu(None, command_context(deck))
        return next(e for e in menu._entries if e[0] == "item" and e[1] == "admin_slides")[6]

    course = make_deck(tmp_path, ["course"], course_url=COURSE_URL)
    assert enabled(course)
    assert not enabled(make_deck(tmp_path, ["course"], course_url=None))        # no linked course page
    assert not enabled(make_deck(tmp_path, ["research"], course_url=COURSE_URL))  # not a course deck


@pytest.mark.parametrize("field,value", [("footer_hide", ("id", "deck")), ("footer_text", "New footer")])
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
