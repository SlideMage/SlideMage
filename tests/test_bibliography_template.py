# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The citation format is the template's job (v5.32.0): a deck calls
SMUseBibliography; the institution templates define SMBiblatexOptions and
SMBibliographyStyle."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BS = chr(92)


def cs(name: str) -> str:
    return BS + name


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_framework_defines_the_command_with_stock_defaults():
    base = read("latex", "SlideMage_base.tex")
    for name in ("SMUseBibliography", "SMBiblatexOptions", "SMBibliographyStyle"):
        assert cs("newcommand{" + cs(name) + "}") in base
    assert "style=authoryear, backend=biber}" in base


def test_manual_deck_uses_the_template_not_its_own_copy():
    deck = read("example", "decks", "slidemage-manual.tex")
    assert cs("SMUseBibliography") in deck
    assert "DeclareBibliographyDriver" not in deck
    assert cs("usepackage[style=authoryear") not in deck
