# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The terminal's colours from the kit's design tokens (no Qt): the background and text of the card, and an
ANSI palette whose every colour reads on that background, light or dark (so "black" is mid-grey on the dark
card and "white" mid-grey on the light one: a terminal programs draws text in them, not only fills)."""
from __future__ import annotations

import json

from ...kit.tokens import DARK_ANSI, LIGHT_ANSI, Tokens, tokens_for, with_alpha

NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")


def xterm_theme(tokens: Tokens) -> dict:
    """The `theme` option of xterm.js."""
    ansi = DARK_ANSI if tokens == tokens_for(True) else LIGHT_ANSI
    colors = {name: ansi[i] for i, name in enumerate(NAMES)}
    colors.update({f"bright{name.capitalize()}": ansi[i + 8] for i, name in enumerate(NAMES)})
    return {"background": tokens.surface, "foreground": tokens.text, "cursor": tokens.text,
            "cursorAccent": tokens.surface, "selectionBackground": with_alpha(tokens.info, 0.3), **colors}


def theme_json(tokens: Tokens) -> str:
    return json.dumps(xterm_theme(tokens))
