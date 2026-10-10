"""The terminal's colours from the kit's design tokens (no Qt): the background and text of the card, and an
ANSI palette whose every colour reads on that background, light or dark (so "black" is mid-grey on the dark
card and "white" mid-grey on the light one: a terminal programs draws text in them, not only fills)."""
from __future__ import annotations

import json

from ...kit.tokens import Tokens, tokens_for, with_alpha

LIGHT_ANSI = ("#1d1d1d", "#b91c1c", "#047857", "#b45309", "#1d4ed8", "#7e22ce", "#0e7490", "#6b7280",
              "#4b5563", "#dc2626", "#059669", "#d97706", "#2563eb", "#9333ea", "#0891b2", "#858b96")
DARK_ANSI = ("#808080", "#f87171", "#34d399", "#fbbf24", "#60a5fa", "#c084fc", "#22d3ee", "#d4d4d4",
             "#9a9a9a", "#fca5a5", "#6ee7b7", "#fde68a", "#93c5fd", "#d8b4fe", "#67e8f9", "#ffffff")
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
