# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every unknown word of a deck at once (docs/plans/ai-spellchecker.md, step 4). No Qt.

`deck_files()` lists the slide files a deck shows, in every language of the project: the calls of the deck and of
its topic blocks, each with its translations (deck_language), the file a call loads (a frozen version when the
deck keeps one). `check_files()` checks them one after the other with the window's SpellingSession (the same
dictionaries, word lists and ignored words as the Source view) and groups the unknown words by language and word,
case ignored, most frequent first, each with where it occurs (file, line, offset). It reads the files on disk:
the Source view saves as you type, so that is what the deck has.

Blocking (a first use downloads a dictionary): call it from a worker. `cancel` stops it between files.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import deck_language, languages, slide_language
from .checker import normalized
from .session import SpellingSession, slide_language as language_of

# report(done_files, total_files, message)
Progress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class Occurrence:
    path: Path
    line: int           # 1-based
    start: int          # character offsets into the file's text
    end: int
    text: str           # the word as written there

    @property
    def frozen(self) -> bool:
        """In a frozen version (read-only until unlocked), not the slide's current file."""
        return not self.path.name.endswith("-current.tex")


@dataclass
class Finding:
    word: str                       # as written where it first occurs
    language: str
    occurrences: list[Occurrence] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def files(self) -> list[Path]:
        return sorted({o.path for o in self.occurrences}, key=lambda p: p.name)


@dataclass
class DeckSpelling:
    findings: list[Finding] = field(default_factory=list)       # most frequent first, then by word
    files: int = 0                                              # files checked
    missing: list[str] = field(default_factory=list)            # files the deck calls that do not exist
    unavailable: dict[str, str] = field(default_factory=dict)   # language -> why it was not checked
    unsupported: set[str] = field(default_factory=set)          # languages without a dictionary
    cancelled: bool = False


def deck_files(ctx, deck) -> list[Path]:
    """The slide files `deck` shows, in every language of the project, in deck order, each once."""
    resolution = deck_language.resolve(deck)
    links = slide_language.links_for(ctx)
    seen: dict[str, None] = {}
    for code in languages.project_languages(ctx).codes:
        for slot in deck_language.slots(ctx, resolution.calls, code, links=links):
            for call in (slot.call, *slot.folded):
                seen.setdefault(call.source_filename, None)
    return [ctx.slides_dir / name for name in seen]


def _id_slug(path: Path) -> str:
    name = path.name.removesuffix(".tex")
    if name.endswith("-current"):
        return name.removesuffix("-current")
    head, sep, tail = name.rpartition("-v")
    return head if sep and tail.replace("-", "").isdigit() else name


def check_files(session: SpellingSession, ctx, paths: list[Path], report: Optional[Progress] = None,
                cancel: Optional[threading.Event] = None) -> DeckSpelling:
    result = DeckSpelling()
    by_word: dict[tuple[str, str], Finding] = {}
    for index, path in enumerate(paths):
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        if report:
            report(index, len(paths), f"Checking {path.name}…")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result.missing.append(path.name)
            continue
        language = language_of(ctx, _id_slug(path))

        def forward(done: int, total: int, message: str, index=index) -> None:
            if report:                              # a dictionary download inside the deck check
                report(index, len(paths), f"{message} {round(100 * done / total)} %" if total else message)

        checked = session.check(text, language, forward)
        result.files += 1
        result.unavailable.update(checked.unavailable)
        result.unsupported |= checked.unsupported
        line_starts = _line_starts(text)
        for m in checked.misspellings:
            key = (m.language, normalized(m.word).casefold())
            finding = by_word.setdefault(key, Finding(m.word, m.language))
            finding.occurrences.append(Occurrence(path, _line_of(line_starts, m.start), m.start, m.end, m.word))
    if report and not result.cancelled:
        report(len(paths), len(paths), "Done")
    result.findings = sorted(by_word.values(), key=lambda f: (-f.count, f.word.casefold(), f.language))
    return result


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts += [i + 1 for i, char in enumerate(text) if char == "\n"]
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    import bisect

    return bisect.bisect_right(starts, offset)
