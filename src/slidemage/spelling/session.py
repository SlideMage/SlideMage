# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking a slide's source: from text to misspelt words, and a correction back into the text. No Qt.

    check(text, language)  ->  prose_spans -> words -> per language: word list, ignored words, Checker.unknown
    correct(text, misspelling, replacement)  ->  prose_spans.apply_span_edits (the only write path)

One `SpellingSession` serves every open file of a window: the checker's cache, and the words ignored "for the
session", are shared. `check()` blocks (a first use downloads and loads a dictionary): call it from a worker.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .. import prose_spans
from . import word_list
from .checker import Checker, Report, SpellingUnavailable, checkable, normalized

log = logging.getLogger("slidemage.spelling")


@dataclass(frozen=True)
class Misspelling:
    start: int          # character offsets into the text that was checked
    end: int
    word: str
    language: str


@dataclass
class CheckResult:
    misspellings: list[Misspelling] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)    # language -> message (download failed, ...)
    unsupported: set[str] = field(default_factory=set)           # languages no dictionary covers
    checked: set[str] = field(default_factory=set)               # languages that were checked


class SpellingSession:
    def __init__(self, checker: Checker, root: Path):
        """`root` is the project folder (its word lists)."""
        self.checker = checker
        self.root = Path(root)
        self._ignored: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    # -- checking --------------------------------------------------------------------------------------------
    def check(self, text: str, language: str, report: Optional[Report] = None) -> CheckResult:
        """The misspelt words of `text` (a slide's source; `language` is the file's own, the arguments of
        \\multilingualtext carry theirs). Text in a language without a dictionary is left alone and reported."""
        return self._check_words(prose_spans.words(text, prose_spans.prose_spans(text, language)), report)

    def check_plain(self, text: str, language: str, report: Optional[Report] = None) -> CheckResult:
        """The misspelt words of plain text in `language` (an image's description): no LaTeX, so every word is
        prose except addresses and file names."""
        return self._check_words(prose_spans.words(text, prose_spans.plain_spans(text, language)), report)

    def _check_words(self, found: list[prose_spans.Word], report: Optional[Report]) -> CheckResult:
        result = CheckResult()
        by_language: dict[str, list[prose_spans.Word]] = {}
        for word in found:
            if word.language and checkable(word.text):
                by_language.setdefault(word.language, []).append(word)
        supported = self.checker.languages()
        with self._lock:
            ignored = set(self._ignored)
        for lang, items in by_language.items():
            if lang not in supported:
                result.unsupported.add(lang)
                continue
            try:
                if not self.checker.prepare(lang, report):
                    result.unsupported.add(lang)
                    continue
            except SpellingUnavailable as e:
                result.unavailable[lang] = str(e)
                continue
            own = word_list.words(self.root, lang)
            candidates = {w.text for w in items
                          if (lang, _key(w.text)) not in ignored and _key(w.text) not in own}
            unknown = self.checker.unknown(lang, candidates)
            result.checked.add(lang)
            result.misspellings += [Misspelling(w.start, w.end, w.text, lang) for w in items if w.text in unknown]
        result.misspellings.sort(key=lambda m: m.start)
        return result

    def suggest(self, language: str, word: str) -> Iterator[str]:
        """Corrections for `word`, best first, as they are found (may take seconds: read them on a worker)."""
        return self.checker.suggest(language, word)

    # -- what the person decides ------------------------------------------------------------------------------
    def ignore(self, language: str, word: str) -> None:
        """Not underlined again in this session, in any file."""
        with self._lock:
            self._ignored.add((language, _key(word)))

    def add_to_word_list(self, language: str, word: str) -> bool:
        return word_list.add(self.root, language, word)

    @staticmethod
    def correct_plain(text: str, misspelling: Misspelling, replacement: str) -> str:
        """`text` (plain, not LaTeX) with the misspelt word replaced. Raises ValueError when the text changed there
        since the check, or the replacement holds a line break."""
        if text[misspelling.start:misspelling.end] != misspelling.word:
            raise ValueError(f"the text at {misspelling.start} no longer reads {misspelling.word!r}")
        if "\n" in replacement or "\r" in replacement:
            raise ValueError(f"the replacement {replacement!r} contains a line break")
        return text[:misspelling.start] + replacement + text[misspelling.end:]

    @staticmethod
    def correct(text: str, misspelling: Misspelling, replacement: str, file_language: str) -> str:
        """`text` with the misspelt word replaced, through prose_spans.apply_span_edits. Raises ValueError when the
        text changed there since the check, or the replacement may not go into regular text."""
        edit = prose_spans.SpanEdit(misspelling.start, misspelling.end, misspelling.word, replacement)
        new, problems = prose_spans.apply_span_edits(text, [edit], file_language)
        if problems:
            raise ValueError("; ".join(problems))
        return new


def _key(word: str) -> str:
    return normalized(word).casefold()


def slide_language(project, id_slug: str) -> str:
    """The language a slide's text is checked in: its own (the code in its file name), the project's main language
    for a slide without one, and "" for a multilingual slide (only \\multilingualtext's arguments, which carry
    their own)."""
    from .. import languages
    from .. import slide_language as slide_languages

    project_languages = languages.project_languages(project)
    own = slide_languages.own_language(id_slug, project_languages.codes)
    if own == slide_languages.MULT:
        return ""
    return (own or project_languages.main).lower()
