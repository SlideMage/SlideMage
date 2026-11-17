# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spell checking of a slide's regular text (docs/plans/ai-spellchecker.md, step 2). No Qt.

What may be checked and how a correction is written is decided in `prose_spans.py`; this package only answers,
for a language and a list of words, which words are unknown and what could be meant instead. A checker never sees
LaTeX.

- `checker.py`: the `Checker` protocol every checker follows, `checkable()` (which words are looked up at all) and
  `SpellingUnavailable`.
- `catalogue.py`: the dictionaries SlideMage can download, pinned by URL, size and SHA-256 (decision S6 b).
- `dictionaries.py`: the per-user dictionary folder and the download into it.
- `dictionary_checker.py`: the built-in checker. German is checked with spylls (Hunspell, so compounds and endings
  are understood), every other language with a pyspellchecker word list.
- `settings.py`: the German variant (de-AT, de-DE or de-CH; decision S5 a, default de-AT).
"""
