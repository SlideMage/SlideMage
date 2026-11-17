# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The built-in checker: dictionaries, no AI. No Qt.

German goes to spylls (a pure-Python Hunspell): it understands compounds ("Nachfrageüberhang") and word endings,
which a word list cannot. Every other language with a pyspellchecker list goes to pyspellchecker, which looks
words up in a frequency list, without regard to case. Both libraries are imported only when a language is
prepared, so importing this module costs nothing.

Measured (2026-11-17, de-AT, this machine): loading the German dictionary takes about 1.6 s, once per session;
a lookup well under 1 ms. A German suggestion usually comes within 1.5 s, but the n-gram stage that follows can
take 10 s, so `suggest()` yields each suggestion as it is found. pyspellchecker loads a list in about 0.2 s and
suggests in milliseconds.

Answers are cached per (dictionary, word) for the life of the checker, so a word is looked up once a session.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from . import catalogue, dictionaries, settings
from .catalogue import Dictionary
from .checker import Report, SpellingUnavailable, sentence_start as _cap, checkable, normalized

log = logging.getLogger("slidemage.spelling")

# pyspellchecker's edit distance 2 grows with the word's length; beyond this many letters distance 1 is used.
_WORDLIST_DISTANCE2_MAX = 12


class DictionaryChecker:
    name = "dictionary"

    def __init__(self, *, base: Optional[Path] = None,
                 german_variant: Callable[[], str] = settings.german_variant,
                 entries: Optional[dict[str, Dictionary]] = None):
        """`base` is the dictionary folder (default: the per-user one), `german_variant` is read at every call so
        a changed setting applies at once, `entries` replaces the catalogue (tests)."""
        self._base = base
        self._german_variant = german_variant
        self._entries = catalogue.CATALOGUE if entries is None else entries
        self._loaded: dict[str, Any] = {}
        self._known: dict[tuple[str, str], bool] = {}
        self._lock = threading.Lock()

    # -- which dictionary ------------------------------------------------------------------------------------
    def languages(self) -> set[str]:
        return {entry.language for entry in self._entries.values()}

    def dictionary_for(self, language: str) -> Optional[Dictionary]:
        language = language.lower()
        if language == "de":
            return self._entries.get(f"de_{self._german_variant()}")
        entry = self._entries.get(language)
        return entry if entry is not None and entry.language == language else None

    def needs_download(self, language: str) -> bool:
        """Whether prepare() would download (so the status line can say so before it starts)."""
        entry = self.dictionary_for(language)
        return entry is not None and entry.key not in self._loaded and not dictionaries.installed(entry, self._base)

    def is_ready(self, language: str) -> bool:
        entry = self.dictionary_for(language)
        return entry is not None and entry.key in self._loaded

    # -- prepare ---------------------------------------------------------------------------------------------
    def prepare(self, language: str, report: Optional[Report] = None) -> bool:
        entry = self.dictionary_for(language)
        if entry is None:
            return False
        if entry.key in self._loaded:
            return True
        target = dictionaries.ensure(entry, report, base=self._base)
        with self._lock:
            if entry.key in self._loaded:
                return True
            if report:
                report(0, 0, f"Loading {entry.label}…")
            try:
                self._loaded[entry.key] = _load(entry, target)
            except Exception as e:   # a library failing on a file that passed its hash: say so, do not crash
                log.exception("spelling: loading %s failed", entry.key)
                raise SpellingUnavailable(f"{_cap(entry.label)} could not be loaded: {e}") from None
        return True

    def _engine(self, language: str) -> tuple[Dictionary, Any]:
        entry = self.dictionary_for(language)
        if entry is None or entry.key not in self._loaded:
            raise SpellingUnavailable(f"No dictionary is ready for {language!r}; prepare() it first.")
        return entry, self._loaded[entry.key]

    # -- checking --------------------------------------------------------------------------------------------
    def unknown(self, language: str, words: Iterable[str]) -> set[str]:
        entry, engine = self._engine(language)
        result = set()
        for word in words:
            if not checkable(word):
                continue
            key = (entry.key, word)
            known = self._known.get(key)
            if known is None:
                known = self._known[key] = _is_known(entry, engine, normalized(word))
            if not known:
                result.add(word)
        return result

    def suggest(self, language: str, word: str) -> Iterator[str]:
        entry, engine = self._engine(language)
        seen = {word}
        for suggestion in _suggestions(entry, engine, normalized(word)):
            suggestion = _like(word, suggestion)
            if suggestion not in seen:
                seen.add(suggestion)
                yield suggestion


def _load(entry: Dictionary, target: Path) -> Any:
    if entry.engine == "hunspell":
        from spylls.hunspell import Dictionary as Hunspell

        stem = entry.files[0].name.rsplit(".", 1)[0]
        return Hunspell.from_files(str(target / stem))
    if entry.engine == "wordlist":
        from spellchecker import SpellChecker

        return SpellChecker(language=None, local_dictionary=str(target / entry.files[0].name))
    raise SpellingUnavailable(f"Unknown dictionary engine {entry.engine!r}.")


def _is_known(entry: Dictionary, engine: Any, word: str) -> bool:
    if entry.engine == "hunspell":
        return bool(engine.lookup(word))
    return word.lower() in engine


def _suggestions(entry: Dictionary, engine: Any, word: str) -> Iterator[str]:
    if entry.engine == "hunspell":
        yield from engine.suggest(word)
        return
    lower = word.lower()
    engine.distance = 2 if len(lower) <= _WORDLIST_DISTANCE2_MAX else 1
    candidates = engine.candidates(lower) or set()
    frequency = engine.word_frequency
    yield from sorted((c for c in candidates if c != lower), key=lambda c: (-frequency[c], c))


def _like(original: str, suggestion: str) -> str:
    """The suggestion in the original's case: "Teh" -> "The" (pyspellchecker answers in lower case)."""
    if original[:1].isupper() and suggestion[:1].islower():
        return suggestion[:1].upper() + suggestion[1:]
    return suggestion
