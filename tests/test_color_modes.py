# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Colour modes and role colours of the framework (latex/SlideMage_setup.tex, "Colour modes and role colours").

TeX tests, run only with SLIDEMAGE_TEX_TESTS set and lualatex installed (as the other compile tests). A template that
declares modes is compiled once per mode; the pixel at the slide's right edge, halfway down, is the canvas."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"
BS = chr(92)

TEMPLATE = r"""\input{SlideMage_setup}
\SMDeclareMode{light}{}
\SMDeclareMode{dark}{dark}
\SMDeclareMode{grey}{grey}
\SMDeclareMode{cb}{colorblind}
\SMDeclareMode{mine}{dark}
\SMSetRole{canvas}{mine}{c_secondary_violet!30!black}
\SMSetRole{text}{mine}{c_secondary_yellow}
\SMSetRole{block_body_fill}{mine}{red}
\SMSetRole{alerted_block_title_fill}{mine}{blue}
\input{SlideMage_base}
"""
DECK = r"""\documentclass[aspectratio=169]{beamer}
\input{template}
\newcommand{\FooterText}{modes}
\begin{document}
\begin{frame}{Modes}
\begin{alertblock}{Alert}body\end{alertblock}
\end{frame}
\end{document}
"""

pytestmark = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                                reason="set SLIDEMAGE_TEX_TESTS and install lualatex to compile")


def compile_mode(tmp_path: Path, mode: str | None, flag: bool = False):
    work = tmp_path / (mode or "base")
    work.mkdir()
    (work / "template.tex").write_text(TEMPLATE, encoding="utf-8")
    pre = ""
    if mode:
        pre += BS + "newcommand{" + BS + "SMModeOverride}{" + mode + "}"
    if flag:
        pre += BS + "newcommand{" + BS + "SMDarkMode}{}"
    (work / "deck.tex").write_text(pre + DECK, encoding="utf-8")
    env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), str(work), ""]))
    subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error", "deck.tex"], cwd=work, env=env,
                   capture_output=True, timeout=300)
    pdf = work / "deck.pdf"
    assert pdf.exists(), (work / "deck.log").read_text(encoding="utf-8", errors="replace")[-2000:]
    pix = pymupdf.open(pdf)[0].get_pixmap(dpi=72)
    return pix


def canvas(pix) -> tuple[int, int, int]:
    return pix.pixel(pix.width - 2, pix.height // 2)[:3]


def test_the_base_mode_is_the_templates_own_colours(tmp_path):
    assert canvas(compile_mode(tmp_path, None)) == (255, 255, 255)
    assert canvas(compile_mode(tmp_path, "light")) == (255, 255, 255)


def test_a_dark_preset_mixes_the_dark_colour_with_white(tmp_path):
    r, g, b = canvas(compile_mode(tmp_path, "dark"))
    assert r == g == b and 60 <= r <= 76  # c_primary_dark (1e1e1e) mixed 17 % with white


def test_the_dark_flag_alone_is_the_mode_dark(tmp_path):
    assert canvas(compile_mode(tmp_path, None, flag=True)) == canvas(compile_mode(tmp_path, "dark"))


def test_an_explicit_role_line_wins_over_the_preset(tmp_path):
    r, g, b = canvas(compile_mode(tmp_path, "mine"))
    assert b > g and r > g and (r, g, b) != canvas(compile_mode(tmp_path, "dark"))  # violet mixed with black


def test_the_grey_preset_leaves_no_colour(tmp_path):
    pix = compile_mode(tmp_path, "grey")
    stray = [s for s in (pix.pixel(x, y) for x in range(0, pix.width, 7) for y in range(pix.height * 2 // 5, pix.height, 7))  # below the logo, which is an image
             if max(s[:3]) - min(s[:3]) > 3]
    assert not stray


def test_the_colorblind_preset_changes_the_alert_block(tmp_path):
    base, cb = compile_mode(tmp_path, None), compile_mode(tmp_path, "cb")
    assert base.samples != cb.samples


def count(pix, rgb) -> int:
    return sum(1 for x in range(0, pix.width, 3) for y in range(0, pix.height, 3) if pix.pixel(x, y)[:3] == rgb)


def test_block_roles_set_the_fill_of_a_block_body_and_title(tmp_path):
    mine, dark = compile_mode(tmp_path, "mine"), compile_mode(tmp_path, "dark")
    assert count(mine, (255, 0, 0)) > 50 and count(dark, (255, 0, 0)) == 0   # block_body_fill
    assert count(mine, (0, 0, 255)) > 50 and count(dark, (0, 0, 255)) == 0   # alerted_block_title_fill
