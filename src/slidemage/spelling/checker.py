# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The protocol a spell checker follows, and the rule for which words are looked up at all. No Qt.

A checker gets words and a language code (ISO 639-1, lower case, as `languages.py` has them), never LaTeX. Every
method but `languages()` may block (a download, loading a dictionary, slow suggestions), so the editor calls them
from a worker thread.
"""
from __future__ import annotations

from typing import Callable, Iterable, Iterator, Optional, Protocol

# report(done_bytes, total_bytes, message): progress of prepare(), for the status line. total_bytes is 0 while
# nothing is downloaded (loading only).
Report = Callable[[int, int, str], None]


class SpellingUnavailable(Exception):
    """A language that is supported cannot be checked now: the download or the dictionary failed. The message is
    written for the person, e.g. "The German dictionary could not be downloaded: ..."."""


class Checker(Protocol):
    name: str

    def languages(self) -> set[str]:
        """The language codes this checker can check now or after a download."""

    def prepare(self, language: str, report: Optional[Report] = None) -> bool:
        """Download and load what `language` needs. True when it can be checked, False when this checker does
        not support it. Raises SpellingUnavailable when a supported language cannot be made ready."""

    def unknown(self, language: str, words: Iterable[str]) -> set[str]:
        """The words, as given, that the dictionary does not know. Words `checkable()` skips are never unknown.
        Fast; prepare() first."""

    def suggest(self, language: str, word: str) -> Iterator[str]:
        """Corrections for `word`, best first, as they are found. May be slow (seconds for a German compound):
        the caller stops reading when it has enough."""


def sentence_start(text: str) -> str:
    """`text` with its first letter in capitals and the rest unchanged ("the German dictionary" -> "The German
    dictionary"; str.capitalize() would lower the rest)."""
    return text[:1].upper() + text[1:]


def normalized(word: str) -> str:
    """The form that is looked up: the typographic apostrophe as a plain one."""
    return word.replace("’", "'")


def checkable(word: str) -> bool:
    """Whether `word` is looked up at all. Not: single letters, abbreviations in capitals (PDF, OECD), and words
    with a capital after the first letter (SlideMage, iPhone), which are names far more often than typos."""
    word = normalized(word).strip("'")
    if len(word) < 2 or not any(c.isalpha() for c in word):
        return False
    if word.isupper():
        return False
    return not any(c.isupper() for c in word[1:])
