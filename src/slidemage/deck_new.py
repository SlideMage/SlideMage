# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create an empty deck: a `decks/<name>.tex` with the preamble every deck of the project shares (the template's
own preamble, the deck-version and -language defaults, the group tag) and no slides yet.

Same header as the manual's deck, so it compiles from the project root or from decks/ (the `\\input@path` and
`\\graphicspath` fallbacks, see README.md, "Directory layout")."""
from __future__ import annotations

from pathlib import Path

from . import deck_duplicate
from .project import ProjectContext

DECK_TEXT = r"""% !TeX program = lualatex
\documentclass[aspectratio=169]{beamer}

% Compile from the project root or from decks/ (see README.md, "Directory layout").
\makeatletter
\def\input@path{{../}}
\makeatother
\graphicspath{{../}}

\input{SlideMage_template_@TEMPLATE@}

\newcommand{\FooterText}{@FOOTER@}

\ifdefined\deckversionoverride
	\deckversion[\deckversionoverride]
\else
	\deckversion[instructor]           % options: instructor, during-course, after-course
\fi
\ifdefined\decklanguageoverride
	\decklanguage[\decklanguageoverride]
\else
	\decklanguage[en]                  % options: en, de
\fi
@TAGS@
\begin{document}

\end{document}
"""


def deck_text(name: str, template: str, group: str = "") -> str:
    """The text of a new, empty deck called `name` in `template` (a slide_snapshot.TEMPLATES key), tagged `group`."""
    footer = name.strip().replace("\\", "").replace("{", "").replace("}", "").replace("%", "")
    # The name is typeset in every footer: a bare _ & # $ ^ ~ is a TeX error, not text.
    for char in "_&#$":
        footer = footer.replace(char, "\\" + char)
    footer = footer.replace("^", "\\textasciicircum{}").replace("~", "\\textasciitilde{}")
    tags = f"\\decktags{{{group.strip().lower()}}}" if group.strip() else ""
    return DECK_TEXT.replace("@TEMPLATE@", template).replace("@FOOTER@", footer).replace("@TAGS@", tags)


def new_deck(ctx: ProjectContext, name: str, template: str, group: str = "") -> Path:
    """Write decks/<name>.tex; ValueError (with the reason, see deck_duplicate.is_valid_deck_name) for a bad name."""
    name = name.strip()
    reason = deck_duplicate.is_valid_deck_name(name, ctx.decks_dir)
    if reason is not None:
        raise ValueError(reason)
    ctx.decks_dir.mkdir(parents=True, exist_ok=True)
    dest = ctx.decks_dir / f"{name}.tex"
    dest.write_text(deck_text(name, template, group), encoding="utf-8")
    return dest
