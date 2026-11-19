# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spell checking in the Source view (docs/plans/ai-spellchecker.md, step 3, test 6), offscreen, with a fake
checker that knows a fixed set of words: underlines, the spelling rows of the menu, a correction as one undo step,
Ignore, Add to word list, the switch, and what the status line says."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QPoint

from slidemage.spelling import word_list
from slidemage.spelling.checker import SpellingUnavailable
from slidemage.spelling.session import Misspelling, SpellingSession
from slidemage.ui import layout_settings
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import spell_check
from slidemage.ui.workspace.source_view import SourcePane
from conftest import wait_until
from test_source_view_gui import FakeApp

KNOWN = {"en": {"the", "quick", "fox", "slide", "title", "and"}, "de": {"der", "fuchs", "folie"}}
SUGGESTIONS = {"teh": ["the", "ten"], "brwn": ["brown"]}


class FakeChecker:
    name = "fake"

    def __init__(self):
        self.prepared, self.asked = [], []
        self.fail: dict[str, str] = {}
        self.release = threading.Event()
        self.release.set()

    def languages(self):
        return set(KNOWN)

    def prepare(self, language, report=None):
        self.prepared.append(language)
        if language in self.fail:
            raise SpellingUnavailable(self.fail[language])
        if report:
            report(50, 100, "Downloading the fake dictionary (1 MB)…")
        return True

    def unknown(self, language, words):
        self.asked.append((language, sorted(words)))
        return {w for w in words if w.lower() not in KNOWN[language]}

    def suggest(self, language, word):
        for suggestion in SUGGESTIONS.get(word.lower(), []):
            self.release.wait(5)
            yield suggestion


SLIDE = "\\begin{standardframe}{Slide title}\n\U0001F600 Teh quick brwn fox, \\url{http://teh.org} and \\SMCode{teh}\n\\end{standardframe}\n"


@pytest.fixture
def checker():
    return FakeChecker()


@pytest.fixture
def pane(ctx, qapp, checker, monkeypatch):
    layout_settings.set(spell_check.SPELL_CHECK_KEY, True)
    app = FakeApp(ctx)
    pane = SourcePane(app)
    monkeypatch.setattr(pane, "spelling_session", lambda: _session(pane, checker, ctx.root))
    return pane


def _session(pane, checker, root):
    if getattr(pane, "_test_session", None) is None:
        pane._test_session = SpellingSession(checker, root)
    return pane._test_session


def _open(pane, ctx, name="abc-EN-Demo-current.tex", text=SLIDE):
    path = ctx.root / "slides" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    pane.show_path(path)
    file = pane.file_for(path)
    wait_until(lambda: file.spell_check.result is not None and not file.spell_check.checking)
    return file


def _underlined(editor):
    return [s.cursor.selectedText() for s in editor.extraSelections() if s.format.underlineStyle() != 0]


def test_the_key_conftest_switches_off_is_the_one_the_view_reads():
    assert spell_check.SPELL_CHECK_KEY == "spell_check"


def test_underlines_land_on_the_unknown_words_only(pane, ctx, checker):
    file = _open(pane, ctx)
    # Not "teh" in the URL or in \SMCode; the emoji before them counts twice in Qt's positions.
    assert _underlined(file.editor) == ["Teh", "brwn"]
    assert [(m.word, m.language) for m in file.spell_check.result.misspellings] == [("Teh", "en"), ("brwn", "en")]
    assert checker.asked[-1][0] == "en" and "teh" not in checker.asked[-1][1]
    assert not file.spelling_chip.isVisible()


def test_typing_checks_again_after_a_pause(pane, ctx, checker):
    file = _open(pane, ctx)
    file.editor.patch_text(file.editor.text().replace("brwn", "brown fxo"))
    wait_until(lambda: "fxo" in _underlined(file.editor) and not file.spell_check.checking)
    assert _underlined(file.editor) == ["Teh", "brown", "fxo"]     # the fake does not know "brown" either


def test_a_suggestion_is_one_undo_step_and_changes_only_the_word(pane, ctx):
    file = _open(pane, ctx)
    before = file.editor.text()
    word = file.spell_check.result.misspellings[0]
    assert file.spell_check.replace(word, "The")
    after = file.editor.text()
    assert after == before[:word.start] + "The" + before[word.end:]
    wait_until(lambda: not file.spell_check.checking and _underlined(file.editor) == ["brwn"])
    file.editor.undo()
    assert file.editor.text() == before


def test_a_suggestion_is_refused_once_the_text_changed_or_with_markup(pane, ctx):
    file = _open(pane, ctx)
    word = file.spell_check.result.misspellings[0]
    assert not file.spell_check.replace(word, "\\textbf{The}")           # markup may not go into regular text
    file.editor.patch_text("x" + file.editor.text())
    assert not file.spell_check.replace(word, "The")                     # the buffer is not what was checked
    assert file.spell_check.misspelling_at(word.start) is None


def test_the_menu_has_the_spelling_rows_and_the_suggestions_arrive_while_it_is_open(pane, ctx, checker, monkeypatch):
    file = _open(pane, ctx)
    shown = []
    monkeypatch.setattr(SourcePane, "_popup_at", staticmethod(lambda menu, point: shown.append(menu)))
    checker.release.clear()                          # the suggestions wait until released
    word = file.spell_check.result.misspellings[0]
    pane._on_spelling_key(word.start + 1, QPoint(0, 0))
    menu = shown[-1]
    keys = [e[1] for e in menu._entries if e[0] == "item"]
    assert keys == ["spell:wait", "spell:ignore", "spell:add"]
    menu._prepare()
    menu.show()
    checker.release.set()
    wait_until(lambda: not menu.has_item("spell:wait"))
    assert [r.key for r in menu._rows][:3] == ["spell:suggest:the", "spell:suggest:ten", "spell:ignore"]
    menu.close()


def test_a_word_without_suggestions_says_so(pane, ctx, monkeypatch):
    _open(pane, ctx, text="Qwzx fox\n")
    shown = []
    monkeypatch.setattr(SourcePane, "_popup_at", staticmethod(lambda menu, point: shown.append(menu)))
    pane._on_spelling_key(0, QPoint(0, 0))
    menu = shown[-1]
    wait_until(lambda: any(e[0] == "item" and e[2] == "No suggestions" for e in menu._entries))


def test_choosing_a_suggestion_from_the_menu(pane, ctx, monkeypatch):
    file = _open(pane, ctx)
    shown = []
    monkeypatch.setattr(SourcePane, "_popup_at", staticmethod(lambda menu, point: shown.append(menu)))
    word = file.spell_check.result.misspellings[1]                       # brwn
    pane._on_spelling_key(word.end, QPoint(0, 0))
    shown[-1].triggered.emit("spell:suggest:brown")
    assert "quick brown fox" in file.editor.text()


def test_no_menu_rows_away_from_an_underlined_word(pane, ctx, monkeypatch):
    file = _open(pane, ctx)
    shown = []
    monkeypatch.setattr(SourcePane, "_popup_at", staticmethod(lambda menu, point: shown.append(menu)))
    pane._on_spelling_key(file.editor.text().index("quick") + 1, QPoint(0, 0))
    assert shown == []
    menu = PopoverMenu()
    assert not file.spell_check.add_menu_rows(menu, file.editor.text().index("fox"))
    assert menu._entries == []


def test_ignore_holds_for_the_session_and_every_file(pane, ctx):
    file = _open(pane, ctx)
    other = _open(pane, ctx, "def-EN-Other-current.tex", "Teh other slide\n")
    assert _underlined(other.editor) == ["Teh", "other"]
    other.spell_check._menu_word = other.spell_check.result.misspellings[0]
    other.spell_check.handle_choice("spell:ignore")
    wait_until(lambda: _underlined(other.editor) == ["other"] and not other.spell_check.checking)
    # The first slide was dropped when the other was shown (no tab holds it): opened again, it is checked afresh.
    pane.show_path(file.path)
    again = pane.file_for(file.path)
    wait_until(lambda: again.spell_check.result is not None and not again.spell_check.checking)
    assert _underlined(again.editor) == ["brwn"]


def test_add_to_word_list_writes_the_project_file(pane, ctx):
    file = _open(pane, ctx)
    file.spell_check._menu_word = file.spell_check.result.misspellings[1]
    assert file.spell_check.handle_choice("spell:add")
    assert word_list.path(ctx.root, "en").read_text(encoding="utf-8") == "brwn\n"
    wait_until(lambda: _underlined(file.editor) == ["Teh"] and not file.spell_check.checking)
    assert not file.spell_check.handle_choice("undo")                  # not a spelling row


def test_a_word_on_the_word_list_is_never_underlined(pane, ctx):
    word_list.path(ctx.root, "en").write_text("# our words\nBRWN\n", encoding="utf-8")
    file = _open(pane, ctx)
    assert _underlined(file.editor) == ["Teh"]


def test_the_switch_clears_the_underlines_and_is_remembered(pane, ctx):
    file = _open(pane, ctx)
    pane.set_spell_check(False)
    assert _underlined(file.editor) == [] and not spell_check.spell_check_on()
    assert "off" in pane._spell_button.toolTip()
    file.editor.patch_text(file.editor.text() + "zzzz\n")
    pane.set_spell_check(True)
    wait_until(lambda: not file.spell_check.checking and "zzzz" in _underlined(file.editor))
    assert "on" in pane._spell_button.toolTip()


def test_german_text_and_a_multilingual_slide(pane, ctx, checker):
    file = _open(pane, ctx, "ghi-DE-Folie-current.tex", "Der Fuchs und die Folie\n")
    assert _underlined(file.editor) == ["und", "die"]
    multi = _open(pane, ctx, "jkl-mult-Both-current.tex",
                  "\\multilingualtext{The fox sliide}{Der Fuchs Foile}\nbody text is not checked\n")
    assert [(m.word, m.language) for m in multi.spell_check.result.misspellings] == [("sliide", "en"),
                                                                                       ("Foile", "de")]


def test_the_status_line_says_when_a_dictionary_is_not_available(pane, ctx, checker):
    checker.fail["en"] = "The English dictionary could not be downloaded: no network"
    file = _open(pane, ctx)
    assert _underlined(file.editor) == []
    assert file.spell_check.status.startswith("The English dictionary could not be downloaded")
    assert not file.spelling_chip.isHidden()
    assert "no network" in pane._spell_button.toolTip()
    del checker.fail["en"]
    file.spelling_chip.clicked.emit()                                   # click: try again
    wait_until(lambda: not file.spell_check.checking and _underlined(file.editor) == ["Teh", "brwn"])
    assert file.spelling_chip.isHidden()


def test_text_in_a_language_without_a_dictionary_is_left_alone(pane, ctx, monkeypatch):
    from slidemage import languages

    monkeypatch.setattr(languages, "project_languages", lambda _ctx: languages.Languages("en", ("de", "fr")))
    file = _open(pane, ctx, "mno-FR-Diapo-current.tex", "Le renard et la diapositive\n")
    assert _underlined(file.editor) == []
    assert file.spell_check.status == "No dictionary for French: that text is not checked."


def test_only_slides_are_checked(pane, ctx):
    bib = ctx.root / "SlideMage.bib"
    bib.write_text("@book{x, title={Teh}}\n", encoding="utf-8")
    pane.show_path(bib)
    assert pane.file_for(bib).spell_check is None
    assert not pane._spell_button.isVisibleTo(pane)


def test_file_language(ctx):
    assert spell_check.file_language(ctx, "abc-EN-Demo") == "en"
    assert spell_check.file_language(ctx, "abc-DE-Demo") == "de"
    assert spell_check.file_language(ctx, "abc-mult-Demo") == ""
    assert spell_check.file_language(ctx, "abc-Demo") == "en"          # the project's main language


def test_session_check_skips_ignored_and_listed_words(tmp_path, checker):
    session = SpellingSession(checker, tmp_path)
    text = "Teh brwn fox\n"
    assert [m.word for m in session.check(text, "en").misspellings] == ["Teh", "brwn"]
    session.ignore("en", "TEH")
    session.add_to_word_list("en", "brwn")
    assert session.check(text, "en").misspellings == []
    assert SpellingSession.correct(text, Misspelling(4, 8, "brwn", "en"), "brown", "en") == "Teh brown fox\n"
    with pytest.raises(ValueError):
        SpellingSession.correct(text, Misspelling(4, 8, "brwx", "en"), "brown", "en")


def test_an_underlined_word_whose_check_is_stale_says_so_in_the_menu(pane, ctx):
    file = _open(pane, ctx)
    word = file.spell_check.result.misspellings[1]
    file.spell_check._checked_text = "something else"        # the text changed since it was checked
    menu = PopoverMenu()
    assert file.spell_check.add_menu_rows(menu, word.end)
    assert any(e[0] == "item" and "checked again" in e[2] for e in menu._entries)


def test_a_real_right_click_finds_the_word_under_the_pointer_beside_the_line_numbers(pane, ctx, monkeypatch):
    """customContextMenuRequested gives viewport coordinates; the viewport starts right of the line numbers, so
    treating them as the editor's shifted the offset by the width of that margin."""
    from PySide6.QtGui import QContextMenuEvent, QTextCursor
    from PySide6.QtWidgets import QApplication

    file = _open(pane, ctx, text="Teh quick brwn fox and teh slide title and brwn fox\n")
    editor = file.editor
    pane.resize(700, 400)
    pane.show()
    QApplication.processEvents()
    assert editor.viewport().x() > 0
    shown = []
    monkeypatch.setattr(SourcePane, "_popup_at", staticmethod(lambda menu, point: shown.append(menu)))
    start = editor.text().rindex("brwn")
    cursor = QTextCursor(editor.document())
    cursor.setPosition(start + 2)
    rect = editor.cursorRect(cursor)
    point = QPoint(rect.x(), rect.y() + rect.height() // 2)
    editor.viewport().setFocus()
    QApplication.sendEvent(editor.viewport(), QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, editor.viewport().mapToGlobal(point)))
    wait_until(lambda: bool(shown))
    assert any(e[0] == "header" and "brwn" in str(e) for e in shown[-1]._entries)
    shown[-1].close()
