# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spell checking as you type in the Source view (docs/plans/ai-spellchecker.md, step 3; decision S1 a).

One `SpellCheck` per open slide. A moment after the last keystroke (CHECK_DELAY_MS) it checks the buffer on a
worker (spelling.session: only the slide's regular text, prose_spans.py) and underlines the unknown words in the
editor. The first use of a language downloads its dictionary; the file's status line says so meanwhile, and says
when a dictionary is not available (click it to try again).

Right-click on an underlined word, or Ctrl+. at it, puts the spelling rows at the top of the editor's menu: the
suggestions (found on a worker and added to the open menu as they come; a German one can take seconds), Ignore
(for this session, every file) and Add to word list (the project's spelling-words-<lang>.txt). A suggestion is
written through prose_spans.apply_span_edits as one undo step, and only while the buffer is still the text that
was checked.

The switch is the Source view's toolbar button, remembered for this user (SPELL_CHECK_KEY).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ... import languages
from ...spelling.session import CheckResult, Misspelling, SpellingSession
from .. import layout_settings
from ..background import run_in_background_with_progress

log = logging.getLogger("slidemage.spelling")

SPELL_CHECK_KEY = "spell_check"     # this user's choice (layout_settings); on unless switched off
CHECK_DELAY_MS = 400                # after the last keystroke
SUGGESTION_LIMIT = 6
SUGGESTION_SECONDS = 15.0           # stop looking after this long, whatever was found
MENU = "spell:"                     # the keys of the menu rows this module adds
_SUGGEST, _IGNORE, _ADD, _WAIT = f"{MENU}suggest:", f"{MENU}ignore", f"{MENU}add", f"{MENU}wait"


def spell_check_on() -> bool:
    return bool(layout_settings.get(SPELL_CHECK_KEY, True))


def set_spell_check_on(on: bool) -> None:
    layout_settings.set(SPELL_CHECK_KEY, bool(on))


def file_language(project, id_slug: str) -> str:
    """The language a slide's text is checked in: its own (the code in its file name), the project's main language
    for a slide without one, and "" for a multilingual slide (only \\multilingualtext's arguments, which carry
    their own)."""
    from ... import slide_language

    project_languages = languages.project_languages(project)
    own = slide_language.own_language(id_slug, project_languages.codes)
    if own == slide_language.MULT:
        return ""
    return (own or project_languages.main).lower()


class SpellCheck(QObject):
    """The spell check of one editor. `session()` gives the window's SpellingSession (None: no checking)."""

    status_changed = Signal()
    word_list_changed = Signal()     # Ignore or Add to word list: the other open files check again

    def __init__(self, editor, session: Callable[[], Optional[SpellingSession]],
                 language: str | Callable[[], str], enabled: bool = True) -> None:
        """`language` is the file's language, or a function giving it, asked once, at the first check (it reads
        the project's languages: nothing to do while the check is off)."""
        super().__init__(editor)
        self.editor = editor
        self._session = session
        self._language = language
        self.enabled = enabled
        self.status = ""                 # for the status line: a download, or why a language is not checked
        self.result: Optional[CheckResult] = None
        self._checked_text: Optional[str] = None
        self._handle = None
        self._pending = False
        self._suggest_cancel: Optional[threading.Event] = None
        self._menu_word: Optional[Misspelling] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(CHECK_DELAY_MS)
        self._timer.timeout.connect(self.check_now)
        editor.text_changed.connect(self._on_text_changed)
        editor.destroyed.connect(self._stop_suggestions)

    @property
    def language(self) -> str:
        if callable(self._language):
            self._language = self._language()
        return self._language

    # -- checking --------------------------------------------------------------------------------------------
    def _on_text_changed(self) -> None:
        if self.enabled:
            self._timer.start()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if on:
            self.check_now()
        else:
            self._timer.stop()
            self._pending = False
            self.result, self._checked_text = None, None
            self.editor.set_spelling_marks([])
            self._set_status("")

    def check_now(self) -> None:
        self._timer.stop()
        session = self._session()
        if not self.enabled or session is None:
            return
        if self._handle is not None:
            self._pending = True        # the running check is for an older text: check again when it ends
            return
        text, language = self.editor.text(), self.language
        self._handle = run_in_background_with_progress(
            lambda report: session.check(text, language, lambda done, total, message: report(
                (done, total, message))),
            self._on_progress, lambda result, error: self._on_done(text, result, error), parent=self, logger=log)

    def _on_progress(self, value) -> None:
        done, total, message = value
        self._set_status(f"{message} {round(100 * done / total)} %" if total else message)

    def _on_done(self, text: str, result: Optional[CheckResult], error) -> None:
        self._handle = None
        if not self.enabled:
            return
        if self._pending or self.editor.text() != text:
            self._pending = False
            self.check_now()
            return
        if error is not None or result is None:
            log.error("spelling: the check failed", exc_info=error)
            self._set_status("Spelling could not be checked; click to try again.")
            return
        self.result, self._checked_text = result, text
        self.editor.set_spelling_marks([(m.start, m.end) for m in result.misspellings])
        self._set_status(_status_of(result))

    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.status_changed.emit()

    @property
    def checking(self) -> bool:
        return self._handle is not None

    def misspelling_at(self, offset: int) -> Optional[Misspelling]:
        """The underlined word at character `offset` (on it or right after it), while the buffer is still the text
        that was checked."""
        if self.result is None or self.editor.text() != self._checked_text:
            return None
        return next((m for m in self.result.misspellings if m.start <= offset <= m.end), None)

    # -- the menu --------------------------------------------------------------------------------------------
    def add_menu_rows(self, menu, offset: int) -> bool:
        """Add the spelling rows for the word at `offset` to `menu` (a PopoverMenu not shown yet; call this before
        adding its other rows, so these come first) and start looking for suggestions. False (nothing added) when
        no underlined word is there."""
        word = self.misspelling_at(offset)
        session = self._session()
        if word is None or session is None:
            return False
        self._stop_suggestions()
        self._menu_word = word
        writable = not self.editor.is_read_only()
        menu.add_header(f"“{word.word}”")
        menu.add_item(_WAIT, "Looking for suggestions…", enabled=False)
        menu.add_item(_IGNORE, "Ignore", meta="this session")
        menu.add_item(_ADD, "Add to word list", detail=f"spelling-words-{word.language}.txt")
        menu.add_separator()
        cancel = threading.Event()
        self._suggest_cancel = cancel
        found: list[str] = []

        def work(report) -> None:
            deadline = time.monotonic() + SUGGESTION_SECONDS
            for suggestion in session.suggest(word.language, word.word):
                if cancel.is_set() or time.monotonic() > deadline:
                    return
                report(suggestion)
                if len(found) + 1 >= SUGGESTION_LIMIT:
                    return

        def add(suggestion: str) -> None:
            if cancel.is_set() or len(found) >= SUGGESTION_LIMIT:
                return
            found.append(suggestion)
            menu.replace_item(_WAIT, [(f"{_SUGGEST}{suggestion}", suggestion, writable), (_WAIT, "Looking…", False)])

        def done(_result, error) -> None:
            if error is not None:
                log.error("spelling: suggestions failed", exc_info=error)
            if not cancel.is_set():
                menu.replace_item(_WAIT, [] if found else [(_WAIT, "No suggestions", False)])

        run_in_background_with_progress(work, add, done, cancel=cancel, logger=log)
        menu.closed.connect(cancel.set)
        return True

    def handle_choice(self, key: str) -> bool:
        """Do what the spelling row `key` says; False for a row that is not one of this module's."""
        if not key.startswith(MENU):
            return False
        self._stop_suggestions()
        word, session = self._menu_word, self._session()
        if word is None or session is None:
            return True
        if key.startswith(_SUGGEST):
            self.replace(word, key.removeprefix(_SUGGEST))
        elif key == _IGNORE:
            session.ignore(word.language, word.word)
            self.word_list_changed.emit()
        elif key == _ADD:
            try:
                session.add_to_word_list(word.language, word.word)
            except (OSError, ValueError) as e:
                log.error("spelling: adding %r to the word list failed: %s", word.word, e)
                self._set_status(f"“{word.word}” could not be added to the word list: {e}")
                return True
            self.word_list_changed.emit()
        return True

    def replace(self, word: Misspelling, replacement: str) -> bool:
        """Write `replacement` over the underlined `word`, as one undo step. False when the buffer is no longer the
        text that was checked, or the replacement may not go into regular text (nothing changes then)."""
        text = self.editor.text()
        if self.editor.is_read_only() or text != self._checked_text:
            return False
        try:
            new = SpellingSession.correct(text, word, replacement, self.language)
        except ValueError as e:
            log.warning("spelling: %r not replaced by %r: %s", word.word, replacement, e)
            return False
        self.editor.patch_text(new)
        self.check_now()
        return True

    def _stop_suggestions(self, *_args) -> None:
        if self._suggest_cancel is not None:
            self._suggest_cancel.set()
            self._suggest_cancel = None

    def stop(self) -> None:
        """The file is closing: no more checks; a running one ends on its own and is dropped."""
        self.enabled = False
        self._timer.stop()
        self._stop_suggestions()
        if self._handle is not None:
            self._handle.stop()
            self._handle = None


def _status_of(result: CheckResult) -> str:
    parts = [message for message in result.unavailable.values()]
    if result.unsupported:
        names = ", ".join(sorted(languages.name(code) for code in result.unsupported))
        parts.append(f"No dictionary for {names}: that text is not checked.")
    return " ".join(parts)
