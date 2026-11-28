# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spellchecker step 4 (docs/plans/ai-spellchecker.md): every unknown word of a deck in one list, and the
descriptions of images checked on the Images page. A fake checker that knows a fixed set of words; no dictionary."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt

from slidemage import alt_images, deck_scan, prose_spans
from slidemage.spelling import deck_check, word_list
from slidemage.spelling.session import SpellingSession
from slidemage.ui import layout_settings
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import spell_check
from conftest import EXAMPLE_PROJECT, wait_until
from test_spell_check_gui import FakeChecker

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def checker():
    return FakeChecker()


@pytest.fixture
def spelling_on():
    layout_settings.set(spell_check.SPELL_CHECK_KEY, True)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def test_plain_spans_leave_out_addresses_and_file_names():
    text = "A grpah, see https://teh.org/x and plot.png; mail me@teh.org."
    spans = prose_spans.plain_spans(text, "EN")
    assert [text[s.start:s.end] for s in spans] == ["A grpah, see ", " and ", "; mail "]   # "." has no letter
    assert all(s.language == "en" and s.kind == "body" for s in spans)
    assert [w.text for w in prose_spans.words(text, spans)] == ["grpah", "see", "and", "mail"]   # "A": a capital
    assert prose_spans.plain_spans("", "en") == [] and prose_spans.plain_spans("www.x.org", "en") == []


def test_check_plain_and_correct_plain(tmp_path, checker):
    session = SpellingSession(checker, tmp_path)
    text = "The fox, \\textbf{teh} and https://teh.org\n"
    found = session.check_plain(text, "en").misspellings
    assert [m.word for m in found] == ["textbf", "teh"]       # plain text: a backslash is no command there
    teh = found[1]
    assert SpellingSession.correct_plain(text, teh, "the") == text.replace("{teh}", "{the}")
    with pytest.raises(ValueError):
        SpellingSession.correct_plain(text, teh, "the\nfox")
    with pytest.raises(ValueError):
        SpellingSession.correct_plain("x" + text, teh, "the")


def test_deck_files_cover_every_language_and_the_blocks():
    decks = {d.name: d for d in deck_scan.scan_decks(EXAMPLE_PROJECT)}
    files = deck_check.deck_files(EXAMPLE_PROJECT, decks["slidemage-manual"])
    names = [p.name for p in files]
    assert len(names) == len(set(names))
    assert any("-EN-" in n for n in names) and any("-DE-" in n for n in names)
    assert all(p.parent == EXAMPLE_PROJECT.slides_dir for p in files)


def test_check_files_groups_words_with_where_they_occur(ctx, checker):
    slides = ctx.slides_dir
    one = _write(slides / "abc-EN-One-current.tex", "\\begin{standardframe}{Title}\nTeh fox\nteh slide brwn\n"
                 "\\end{standardframe}\n")
    two = _write(slides / "def-EN-Two-current.tex", "Teh quick fox\n")
    frozen = _write(slides / "def-EN-Two-v1-0-0.tex", "brwn\n")
    german = _write(slides / "ghi-DE-Drei-current.tex", "Der Fuchs und\n")
    word_list.add(ctx.root, "en", "quick")
    session = SpellingSession(checker, ctx.root)
    progress = []
    result = deck_check.check_files(session, ctx, [one, two, frozen, german, slides / "missing-current.tex"],
                                    lambda done, total, message: progress.append((done, total)))
    assert [(f.word, f.language, f.count) for f in result.findings] == [
        ("Teh", "en", 3), ("brwn", "en", 2), ("und", "de", 1)]
    teh = result.findings[0]
    assert [(o.path.name, o.line, o.text) for o in teh.occurrences] == [
        ("abc-EN-One-current.tex", 2, "Teh"), ("abc-EN-One-current.tex", 3, "teh"), ("def-EN-Two-current.tex", 1, "Teh")]
    assert teh.files == [one, two]
    assert [o.frozen for o in result.findings[1].occurrences] == [False, True]
    assert result.files == 4 and result.missing == ["missing-current.tex"]
    assert progress[0] == (0, 5) and progress[-1] == (5, 5)


def test_check_files_stops_when_cancelled(ctx, checker):
    import threading

    paths = [_write(ctx.slides_dir / f"a{i}-EN-X-current.tex", "teh\n") for i in range(3)]
    cancel = threading.Event()
    cancel.set()
    result = deck_check.check_files(SpellingSession(checker, ctx.root), ctx, paths, cancel=cancel)
    assert result.cancelled and result.files == 0


class FakeWindow:
    def __init__(self, ctx, checker):
        self.project = ctx
        self.theme = ThemeManager()
        self.session = SpellingSession(checker, ctx.root)
        self.rechecked = 0
        self.opened = []
        self.centre = SimpleNamespace(source=SimpleNamespace(recheck_spelling=self._recheck))

    def _recheck(self):
        self.rechecked += 1

    def log(self, _line):
        pass

    def spelling_session(self):
        return self.session

    def open_slide_editor(self, path, **kwargs):
        self.opened.append((path, kwargs))


def _sheet(ctx, checker, monkeypatch, paths):
    from slidemage.ui.dialogs import deck_spelling

    monkeypatch.setattr(deck_check, "deck_files", lambda _ctx, _deck: paths)
    window = FakeWindow(ctx, checker)
    sheet = deck_spelling.DeckSpellingSheet(None, SimpleNamespace(name="course"))
    sheet.window_ = window
    sheet.run_check()
    wait_until(lambda: sheet.result is not None)
    return sheet, window


def test_the_sheet_lists_the_words_and_adds_the_ticked_ones(ctx, checker, monkeypatch):
    paths = [_write(ctx.slides_dir / "abc-EN-One-current.tex", "Teh fox brwn\nteh\n")]
    sheet, window = _sheet(ctx, checker, monkeypatch, paths)
    rows = sheet._rows()
    assert [(r.text(0), r.text(1), r.text(2)) for r in rows] == [("Teh", "English", "2"), ("brwn", "English", "1")]
    assert rows[0].childCount() == 2 and rows[0].child(1).text(3) == "abc-EN-One-current.tex, line 2"
    assert not sheet.add_word_button.isEnabled()
    rows[1].setCheckState(0, Qt.CheckState.Checked)
    assert sheet.add_word_button.isEnabled()
    sheet.add_word_button.click()
    assert word_list.path(ctx.root, "en").read_text(encoding="utf-8") == "brwn\n"
    assert [r.text(0) for r in sheet._rows()] == ["Teh"] and window.rechecked == 1
    sheet.tick_all.click()
    sheet.ignore_button.click()
    assert sheet._rows() == [] and window.rechecked == 2
    sheet.again_button.click()
    wait_until(lambda: sheet._handle is None and sheet.result is not None)
    assert sheet._rows() == []
    sheet.close()


def test_double_click_opens_the_slide_at_the_line(ctx, checker, monkeypatch):
    paths = [_write(ctx.slides_dir / "abc-EN-One-current.tex", "fox\nfox teh\n")]
    sheet, window = _sheet(ctx, checker, monkeypatch, paths)
    row = sheet._rows()[0]
    sheet._open(row.child(0), 3)
    assert window.opened == [(paths[0], {"line": 2, "tab": True})]
    sheet.close()


def test_the_sheet_says_what_is_not_checked(ctx, checker, monkeypatch):
    checker.fail["en"] = "The English dictionary could not be downloaded: no network"
    paths = [_write(ctx.slides_dir / "abc-EN-One-current.tex", "teh\n")]
    sheet, _window = _sheet(ctx, checker, monkeypatch, paths)
    assert sheet._rows() == []
    assert sheet.status.text() == ("No unknown words in 1 slide files. "
                                   "The English dictionary could not be downloaded: no network")
    sheet.close()


def test_the_deck_menu_command_opens_the_sheet(ctx, checker, monkeypatch):
    from slidemage.ui.dialogs import deck_spelling
    from slidemage.ui.workspace import actions

    opened = []
    monkeypatch.setattr(deck_spelling, "open_for", lambda window, deck: opened.append(deck))
    window = SimpleNamespace(state=SimpleNamespace(deck="the deck"))
    actions._deck_spelling(window)
    assert opened == ["the deck"]


def _form(ctx, checker, short="", long="", short_de=""):
    from slidemage.ui.pages.image_form import ImageForm

    entry = alt_images.ImageEntry("media/plot.png", short=short, long=long, short_de=short_de)
    app = FakeWindow(ctx, checker)
    form = ImageForm(app, "media/plot.png", entry, "abc", "")
    return form, app


def _underlined(edit):
    return [s.cursor.selectedText() for s in edit.extraSelections()]


def test_description_spelling_checks_prose_and_corrects_in_one_undo_step(ctx, checker, spelling_on):
    form, _app = _form(ctx, checker, short="Teh fox graph", long="A slide, see https://teh.org", short_de="Der Fuks")
    short, long, german = form.fields["short"], form.fields["long"], form.fields["short_tr"]
    for edit in (short, long, german):
        wait_until(lambda e=edit: e.spell_check.result is not None and not e.spell_check.checking)
    assert _underlined(short) == ["Teh", "graph"]
    assert _underlined(long) == ["see"]          # the fake knows no "see"; nothing in the address
    assert german.spell_check.language == "de" and _underlined(german) == ["Fuks"]
    assert not hasattr(form.fields["source"], "spell_check")
    word = short.spell_check.result.misspellings[0]
    assert short.spell_check.replace(word, "The")
    assert short.toPlainText() == "The fox graph"
    short.undo()
    assert short.toPlainText() == "Teh fox graph"


def test_the_description_menu_has_the_spelling_rows(ctx, checker, spelling_on, monkeypatch):
    form, app = _form(ctx, checker, short="Teh fox")
    short = form.fields["short"]
    wait_until(lambda: short.spell_check.result is not None and not short.spell_check.checking)
    shown = []
    monkeypatch.setattr(PopoverMenu, "popup_at", lambda self, point: shown.append(self))
    form.resize(600, 800)
    form.show()
    caret = short.cursorRect(short.cursorForPosition(QPoint(0, 0)))
    short.customContextMenuRequested.emit(short.viewport().mapTo(short, caret.center()))
    menu = shown[-1]
    keys = [e[1] for e in menu._entries if e[0] == "item"]
    assert keys[:3] == ["spell:wait", "spell:ignore", "spell:add"] and "copy" in keys
    menu.triggered.emit("spell:add")
    assert word_list.path(ctx.root, "en").read_text(encoding="utf-8") == "Teh\n" and app.rechecked == 1
    form.close()


def test_no_check_when_switched_off(ctx, checker):
    form, _app = _form(ctx, checker, short="Teh fox")     # conftest switches the check off
    assert not hasattr(form.fields["short"], "spell_check")
