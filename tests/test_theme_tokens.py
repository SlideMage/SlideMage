# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Core theme contracts without freezing the complete application stylesheet."""
from __future__ import annotations

import ast
from dataclasses import asdict, fields
import inspect
import re

import pytest

from slidemage.ui.kit import kit_qss
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import ACCENTS, DARK, FIXED, LIGHT, TYPE, Tokens, pill


def test_fixed_contains_exactly_the_fields_equal_across_themes():
    equal = {f.name for f in fields(Tokens) if getattr(LIGHT, f.name) == getattr(DARK, f.name)}
    assert equal == set(FIXED)
    for name, value in FIXED.items():
        assert getattr(LIGHT, name) == getattr(DARK, name) == value


@pytest.mark.parametrize("tokens", [LIGHT, DARK])
def test_semantic_aliases(tokens):
    for alias, source in {
        "cloud_bg": "warning_bg", "cloud_fg": "warning_fg",
        "local_icon": "ok", "local_fg": "ok_fg", "focus": "info", "inverse": "text",
    }.items():
        assert getattr(tokens, alias) == getattr(tokens, source)
    assert (tokens.steps[0], tokens.steps[1], tokens.steps[3]) == (tokens.text, tokens.info, tokens.ok)


@pytest.mark.parametrize("dark", [False, True])
def test_syntax_colours_read_tokens(dark):
    theme = ThemeManager(dark=dark)
    assert theme.syntax_colors() == {
        **{name: getattr(theme.tokens, f"syntax_{name}")
           for name in ("comment", "command", "brace", "env", "math", "todo")},
        "brace_match_bg": theme.tokens.selection,
    }


def test_stylesheet_values_come_from_tokens():
    source = inspect.getsource(kit_qss)
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', source)
    assert not re.search(r'font-size:\s*\d', source)
    # Zero resets a radius; all actual corners, including per-corner rules, use tokens.
    assert not re.search(r'radius:\s*[1-9]\d*(?:\.\d+)?(?:px)?', source)
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "text"]
    assert calls
    for call in calls:
        size = call.args[1]
        assert isinstance(size, ast.Attribute) and isinstance(size.value, ast.Name)
        assert size.value.id == "TYPE" and size.attr in asdict(TYPE)


@pytest.mark.parametrize("tokens", [LIGHT, DARK])
def test_built_stylesheet_uses_seven_whole_pixel_sizes(tokens):
    sizes = set(asdict(TYPE).values())
    assert sizes == {11, 12, 13, 14, 15, 18, 20}
    qss = kit_qss.build_kit_qss(tokens, {name: f"ICON/{name}" for name in kit_qss.KIT_ICONS})
    assert {float(s) for s in re.findall(r'font-size:\s*([\d.]+)px', qss)} == sizes
    for selector, size in [("QLabel#kitSegmentBadge", TYPE.micro), ("QLineEdit#kitPaletteInput", TYPE.heading)]:
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', qss)[1]
        assert f"font-size: {size}px;" in rule


def test_pill_preserves_half_height_including_odd_heights():
    assert [pill(h) for h in (14, 18, 20, 19)] == [7, 9, 10, 9.5]


def test_internal_accents_are_named_and_keep_current_status_colours_distinct():
    for mode, tokens in [("light", LIGHT), ("dark", DARK)]:
        palette = ACCENTS[mode]
        assert set(palette) == {"neutral", "slate", "blue", "teal", "green", "violet", "pink"}
        assert palette["neutral"] == tokens.text
        assert palette["blue"] == tokens.info
        assert palette["green"] != tokens.ok  # adoption belongs to track A
