# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The two Fira bugs of docs/plans/layout-from-metrics.md, section E (v10.12.0).

A footnote in revealed content (an item after \\pause, \\item<3->, \\onslide, \\uncover, \\visible) appears with that
content: the theme covers it on the steps that hide the content, as beamer covers a \\footnote<...>, in the bottom
block and in the side strip. A columns[T] below other content keeps the gap a plain list has there (beamer's 1ex
pull-up at the column head took it up to the content, below a table onto its bottom rule). The calibration deck's ZCM, ZCN/ZCO and the geometry deck's
ZG3 show both; the compile is opt-in (SLIDEMAGE_TEX_TESTS=1 and latexmk), the source checks always run.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "fixtures" / "template_stress"
THEME = ROOT / "latex" / "beamerthemeSlideMage.sty"
BS = chr(92)


def load(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def theme_definition(name: str) -> str:
    text = THEME.read_text(encoding="utf-8")
    start = text.index(f"{BS}renewcommand<>{BS}{name}[1]{{")
    end = text.index(f"{BS}color@endgroup}}}}", start)
    return text[start:end]


def words_of(code: str) -> list[str]:
    return re.findall(r"\S+", code.replace("%", " "))


def test_the_theme_covers_footnotes_in_both_of_beamers_footnote_boxes():
    for name in ("beamer@framefootnotetext", "@mpfootnotetext"):
        code = theme_definition(name)
        assert f"{BS}SM@FootnoteCover{{#2}}" in code
        assert f"{BS}uncover#2" not in code
    text = THEME.read_text(encoding="utf-8")
    assert f"{BS}let{BS}@footnotetext{BS}beamer@framefootnotetext" in text
    # the side strip covers its copy of the text again (beamer's covering stays behind in the footnote box)
    assert text.count(f"{BS}SM@SideFootnoteCover{{") == 2


@pytest.mark.skipif(not shutil.which("kpsewhich"), reason="needs a TeX installation with beamer")
def test_the_two_definitions_are_beamers_own_apart_from_the_cover():
    """If a beamer update changes the two definitions the theme replaces, the copies must follow it."""
    found = subprocess.run(["kpsewhich", "beamerbaseframecomponents.sty"], capture_output=True, text=True).stdout.strip()
    if not found:
        pytest.skip("beamerbaseframecomponents.sty not found")
    beamer = Path(found).read_text(encoding="utf-8", errors="replace")
    for name in ("beamer@framefootnotetext", "@mpfootnotetext"):
        m = re.search(r"\\(?:re)?newcommand<>\\" + re.escape(name) + r"\[1\]\{.*?\\color@endgroup\}\}", beamer, re.S)
        assert m, name
        theirs = words_of(m.group(0).replace(f"{BS}newcommand<>", f"{BS}renewcommand<>").replace(f"{BS}uncover#2{{", f"{BS}SM@FootnoteCover{{#2}}{{"))
        ours = words_of(theme_definition(name) + f"{BS}color@endgroup}}}}")
        assert ours == theirs, name


# ---------------------------------------------------------------- compiled

needs_tex = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                               reason="compiles the calibration and geometry decks: SLIDEMAGE_TEX_TESTS=1 and latexmk")


@pytest.fixture(scope="module")
def decks(tmp_path_factory):
    cal = load("calibrate_font_profile")
    out = tmp_path_factory.mktemp("reveals")
    framework = ROOT / "latex"
    cal.compile_deck(STRESS, "decks/calibration.tex", "stress-test", None, framework, out / "cal.pdf")
    cal.compile_deck(STRESS, "decks/geometry.tex", "stress-test", None, framework, out / "geo.pdf")
    cal.compile_deck(STRESS, "decks/calibration.tex", "slidemage", "fira", framework, out / "fira.pdf")
    return {name: cal.Deck(out / f"{name}.pdf") for name in ("cal", "geo", "fira")}


def shown(page, word: str) -> list[float]:
    """The tops (bp) of the spans that hold `word` and are drawn on the page: pgf's invisible text (\\uncover,
    \\visible on a hidden step) is set far outside it, or with render mode 3."""
    tops = []
    for span in page.get_texttrace():
        text = "".join(chr(c[0]) for c in span["chars"])
        box = pymupdf.Rect(span["bbox"])
        if word in text and span["type"] != 3 and box.intersects(page.rect):
            tops.append(round(box.y0, 2))
    return tops


# the footnotes of ZCM and the first step each shows on
ZCM = {"Fnalways": 1, "Fnown": 2, "Fnpause": 2, "Fnitem": 3, "Fnonslide": 4, "Fnuncover": 5, "Fnvisible": 6}


@needs_tex
@pytest.mark.parametrize("deck", ["cal", "fira"])
def test_a_footnote_in_revealed_content_appears_with_it(decks, deck):
    steps = decks[deck].pages["ZCM"]
    assert len(steps) == 6
    for word, first in ZCM.items():
        seen = [bool(shown(page, word)) for page in steps]
        assert seen == [n >= first for n in range(1, 7)], (word, seen)
    # a footnote keeps its place on every step it shows on, and the block does not move between steps
    # (within 0.02bp: tops rounded to 0.01 can straddle a rounding boundary, as the stress template's "(n)" markers
    # of v10.18.0 showed with 221.07 against 221.08)
    for word, first in ZCM.items():
        tops = [shown(page, word)[0] for page in steps[first - 1:]]
        assert max(tops) - min(tops) <= 0.02, (word, tops)


@needs_tex
def test_the_reveal_slide_shows_its_footnote_with_the_third_item(decks):
    steps = decks["cal"].pages["ZCH"]
    assert [bool(shown(page, "appears")) for page in steps] == [False, False, True]


@needs_tex
def test_a_side_footnote_in_revealed_content_appears_with_it(decks):
    steps = decks["geo"].pages["ZG3"]
    assert len(steps) == 2
    assert [bool(shown(page, "Sidealways")) for page in steps] == [True, True]
    for word in ("Sideown", "Sidepause"):
        assert [bool(shown(page, word)) for page in steps] == [False, True], word


def table_bottom(page) -> float:
    """The lowest thin rule: the table's bottom rule (the slides have no other)."""
    return max(d["rect"].y1 for d in page.get_drawings() if d["rect"].height < 1.5 and d["rect"].width > 50)


@needs_tex
@pytest.mark.parametrize("deck", ["cal", "fira"])
def test_a_T_columns_below_content_keeps_the_gap_of_a_list(decks, deck):
    d = decks[deck]
    T, plain = d.page("ZCN"), d.page("ZCO")
    assert shown(T, "first") == shown(plain, "first")
    # below a list: the columns' first line where a list's would be
    (top_T,), (top_plain,) = shown(T, "Colta"), shown(plain, "Colta")
    assert abs(top_T - top_plain) < 0.3, (top_T, top_plain)
    # below a table: the same gap under its bottom rule (ZCN's table sits higher: the columns above it end higher than a list)
    gap_T = shown(T, "Coltb")[0] - table_bottom(T)
    gap_plain = shown(plain, "Coltb")[0] - table_bottom(plain)
    assert gap_T > 2 and abs(gap_T - gap_plain) < 0.3, (gap_T, gap_plain)

@needs_tex
def test_the_image_source_line_is_shown_on_every_step(decks):
    """It lists every image of the frame (here one on the first step), although it is emitted after the \\pause."""
    steps = decks["geo"].pages["ZG4"]
    assert len(steps) == 2
    assert [bool(shown(page, "Imgsrc")) for page in steps] == [True, True]
    assert len({shown(page, "Imgsrc")[0] for page in steps}) == 1
