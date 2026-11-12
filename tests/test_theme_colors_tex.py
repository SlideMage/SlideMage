# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Color menu's swatches (theme_colors) are the colours LuaLaTeX gives each name, in every colour mode: a deck
prints each role colour and palette colour as HTML after the framework resolved the mode, and the reader must agree
within rounding. TeX tests: SLIDEMAGE_TEX_TESTS=1 and lualatex."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from slidemage import theme_colors

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"

pytestmark = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                                reason="set SLIDEMAGE_TEX_TESTS and install lualatex to compile")

ACME = r"""% SlideMage modes: light, dark, grey, cb, mine
\input{SlideMage_setup}
\definecolor{c_secondary_blue}{HTML}{2266AA}
\colorlet{c_tertiary_blue}{c_secondary_blue!50!white}
\definecolor{SMCanvasColor}{HTML}{FAF8F0}
\SMDeclareMode{light}{}
\SMDeclareMode{dark}{dark}
\SMDeclareMode{grey}{grey}
\SMDeclareMode{cb}{colorblind}
\SMDeclareMode{mine}{dark}
\SMSetRole{link}{light}{c_secondary_blue}
\SMSetRole{canvas}{mine}{c_secondary_violet!30!black}
\SMSetRole{text}{mine}{c_secondary_yellow}
\SMSetColor{c_custom_gray}{mine}{HTML}{C6C6C6}
\SMSetRole{text_muted}{mine}{c_custom_gray}
\input{SlideMage_base}
"""

NAMES = ["c_" + role for role in theme_colors.ROLES] + [
    "c_primary_dark", "c_primary_highlight", "c_primary_gray", "c_secondary_violet", "c_secondary_blue",
    "c_tertiary_blue", "c_secondary_red", "c_tertiary_gray", "c_custom_gray", "c_custom_red"]

DECK = r"""\documentclass[aspectratio=169]{beamer}
%(pre)s\input{SlideMage_template_%(key)s}
\newcommand{\FooterText}{colours}
\begin{document}
\makeatletter
\def\SMPrint#1{\extractcolorspecs{#1}{\SM@m}{\SM@s}\convertcolorspec{\SM@m}{\SM@s}{HTML}\SM@h
  \typeout{SMCOLOUR #1=\SM@h}}
\makeatother
%(prints)s
\begin{frame}{x}x\end{frame}
\end{document}
"""


def tex_colours(work: Path, key: str, mode: str) -> dict[str, str]:
    pre = "\\newcommand{\\SMModeOverride}{%s}\n" % mode if mode else ""
    prints = "\n".join("\\SMPrint{%s}" % name for name in NAMES)
    (work / "deck.tex").write_text(DECK % {"pre": pre, "key": key, "prints": prints}, encoding="utf-8")
    env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), str(work), ""]))
    subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error", "deck.tex"], cwd=work, env=env,
                   capture_output=True, timeout=300)
    log = (work / "deck.log").read_text(encoding="utf-8", errors="replace")
    found = dict(re.findall(r"SMCOLOUR (\w+)=([0-9A-Fa-f]{6})", log))
    assert len(found) == len(NAMES), log[-2000:]
    return {name: "#" + value.lower() for name, value in found.items()}


def close(a: str, b: str) -> bool:
    return all(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) <= 1 for i in (1, 3, 5))


@pytest.mark.parametrize("key,mode", [
    ("acme", ""), ("acme", "light"), ("acme", "dark"), ("acme", "grey"), ("acme", "cb"), ("acme", "mine"),
    ("acme", "unknown"), ("slidemage", ""), ("slidemage", "dark"), ("grayscale", ""), ("grayscale", "dark")])
def test_the_menu_swatches_are_the_colours_tex_resolves(key, mode, tmp_path):
    (tmp_path / "SlideMage_template_acme.tex").write_text(ACME, encoding="utf-8")
    expected = theme_colors.theme_colors(key, tmp_path, mode)       # "unknown": undeclared, no preset, no lines
    tex = tex_colours(tmp_path, key, mode)
    wrong = {name: (expected.get(name), tex[name]) for name in NAMES
             if name not in expected or not close(expected[name], tex[name])}
    assert not wrong, wrong
