# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Core theme contracts without freezing the complete application stylesheet."""
from __future__ import annotations

import ast
from dataclasses import asdict, fields
import inspect
import re

from slidemage.ui.kit import kit_qss
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import DARK, FIXED, LIGHT, TYPE, Tokens


def test_fixed_contains_exactly_the_fields_equal_across_themes():
    equal = {f.name for f in fields(Tokens) if getattr(LIGHT, f.name) == getattr(DARK, f.name)}
    assert equal == set(FIXED)
    for name, value in FIXED.items():
        assert getattr(LIGHT, name) == getattr(DARK, name) == value


def test_syntax_colors_read_tokens():
    theme = ThemeManager(dark=True)
    assert theme.syntax_colors() == {
        **{name: getattr(theme.tokens, f"syntax_{name}")
           for name in ("comment", "command", "brace", "env", "math", "todo")},
        "brace_match_bg": theme.tokens.selection,
    }


def test_stylesheet_values_come_from_tokens():
    source = inspect.getsource(kit_qss)
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', source)
    assert not re.search(r'font-size:\s*\d', source)
    assert not re.search(r'radius:\s*[1-9]\d*(?:\.\d+)?(?:px)?', source)
    sizes = [node.args[1] for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "text"]
    assert sizes and all(ast.unparse(size) in {f"TYPE.{name}" for name in asdict(TYPE)} for size in sizes)


def test_built_stylesheet_uses_only_the_type_scale():
    qss = kit_qss.build_kit_qss(LIGHT, {name: f"ICON/{name}" for name in kit_qss.KIT_ICONS})
    assert {float(s) for s in re.findall(r'font-size:\s*([\d.]+)px', qss)} == set(asdict(TYPE).values())
