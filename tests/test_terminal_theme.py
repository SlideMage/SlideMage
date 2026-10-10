"""The terminal's colours (ui/workspace/terminal/theme.py): every ANSI colour must be readable on the card
it is drawn on, in both themes (the stock xterm palette has yellow and white that vanish on white)."""
from __future__ import annotations

import json

import pytest

from slidemage.ui.kit.tokens import DARK, LIGHT
from slidemage.ui.workspace.terminal.theme import NAMES, theme_json, xterm_theme


def luminance(color: str) -> float:
    def channel(index: int) -> float:
        value = int(color[1 + 2 * index:3 + 2 * index], 16) / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_every_colour_reads_on_the_background(tokens):
    theme = xterm_theme(tokens)
    assert theme["background"] == tokens.surface and theme["foreground"] == tokens.text
    colours = [theme[name] for name in NAMES] + [theme[f"bright{name.capitalize()}"] for name in NAMES]
    assert len(colours) == 16
    for name in NAMES:
        assert contrast(theme[name], theme["background"]) >= 3.0, name
        assert contrast(theme[f"bright{name.capitalize()}"], theme["background"]) >= 3.0, name
    assert contrast(theme["foreground"], theme["background"]) >= 7


def test_the_json_is_what_the_page_applies():
    assert json.loads(theme_json(DARK))["background"] == DARK.surface
    assert json.loads(theme_json(LIGHT))["selectionBackground"].startswith("rgba(")
