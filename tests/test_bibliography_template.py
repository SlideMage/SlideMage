# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The citation format is the template's job (v5.32.0): a deck calls
SMUseBibliography; the institution templates define SMBiblatexOptions and
SMBibliographyStyle, either on their own or (since v10.14.0) by saying
\\input{SlideMage_bibliography_default} -- the house format's own framework
file, which carries exactly bibliography_house.FULL_TEXT."""
from pathlib import Path

from slidemage import bibliography_house

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


def test_the_slidemage_template_inputs_the_default_file_instead_of_carrying_the_format():
    text = read("latex", "SlideMage_template_slidemage.tex")
    assert cs("input{SlideMage_bibliography_default}") in text
    assert "DeclareBibliographyDriver" not in text
    assert cs("renewcommand{") + cs("SMBibliographyStyle}") not in text


def test_the_default_bibliography_file_has_the_spdx_header_and_the_stock_house_format():
    text = read("latex", "SlideMage_bibliography_default.tex").replace("\r\n", "\n")
    lines = text.split("\n")
    assert lines[0] == "% SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß"
    assert lines[1] == "% SPDX-License-Identifier: LPPL-1.3c+"
    assert bibliography_house.FULL_TEXT in text
    for name in ("SMBiblatexOptions", "SMBibliographyStyle"):
        assert cs("renewcommand{" + cs(name) + "}") in text
    for entrytype in ("book", "article", "online", "report"):
        assert cs("DeclareBibliographyDriver{" + entrytype + "}") in text

