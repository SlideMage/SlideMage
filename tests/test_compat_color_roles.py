# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_color_roles: c_primary_dark and its companions in slides become role colours by context."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import compat, compat_color_roles as m, project
from slidemage.compat import Pending


def new(text: str) -> str:
    return m.rewrite(text)[0]


@pytest.mark.parametrize("before, after", [
    # lines, arrows, shapes and text on the canvas
    (r"\draw[c_primary_dark] (0,0) -- (1,0);", r"\draw[c_text] (0,0) -- (1,0);"),
    (r"\draw[SMArrow, thick, c_primary_dark] (0,0) -- (1,0);", r"\draw[SMArrow, thick, c_text] (0,0) -- (1,0);"),
    (r"\draw[-{Stealth[length=2.5mm]}, thick, c_primary_dark] (0,0);", r"\draw[-{Stealth[length=2.5mm]}, thick, c_text] (0,0);"),
    (r"\addplot[c_primary_dark, thick, mark=*] coordinates {(1,0)};", r"\addplot[c_text, thick, mark=*] coordinates {(1,0)};"),
    (r"\node[right, font=\tiny, c_primary_dark] at (1,0) {x};", r"\node[right, font=\tiny, c_text] at (1,0) {x};"),
    (r"\fill[c_primary_dark] (0,0) circle (1mm);", r"\fill[c_text] (0,0) circle (1mm);"),
    (r"\tikzset{flow/.style={SMArrow, c_primary_dark, line width=0.5pt}}", r"\tikzset{flow/.style={SMArrow, c_text, line width=0.5pt}}"),
    # an outline around a coloured fill is still a line
    (r"\fill[c_custom_red, draw=c_primary_dark, line width=0.8pt] (0,0) rectangle (1,1);",
     r"\fill[c_custom_red, draw=c_text, line width=0.8pt] (0,0) rectangle (1,1);"),
    (r"\draw[c_primary_dark, fill=c_primary_highlight] (0,0) circle (1);",
     r"\draw[c_text, fill=c_primary_highlight] (0,0) circle (1);"),
    # a shape drawn in ink and filled white: the canvas
    (r"\draw[c_primary_dark, line width=1.2pt, fill=c_primary_white] (0,0) circle (0.25);",
     r"\draw[c_text, line width=1.2pt, fill=c_canvas] (0,0) circle (0.25);"),
    (r"\draw[c_primary_dark, thick, fill=white] (0,0) rectangle (1,1);", r"\draw[c_text, thick, fill=c_canvas] (0,0) rectangle (1,1);"),
    # text on a coloured fill
    (r"every node/.style={fill=c_primary_highlight, text=c_primary_dark, inner sep=3pt},",
     r"every node/.style={fill=c_primary_highlight, text=c_text_on_accent, inner sep=3pt},"),
    (r"\node[fill=c_secondary_blue, c_primary_dark] {x};", r"\node[fill=c_secondary_blue, c_text_on_accent] {x};"),
    (r"\node[fill=c_secondary_blue] at (0,0) {\textcolor{c_primary_dark}{x}};",
     r"\node[fill=c_secondary_blue] at (0,0) {\textcolor{c_text_on_accent}{x}};"),
    # an ink-filled box: the fill is ink, its white text the canvas; a mix is kept
    (r"\node[SMImageBorder, fill=c_primary_dark!85, text=white, inner sep=5pt] {q};",
     r"\node[SMImageBorder, fill=c_text!85, text=c_canvas, inner sep=5pt] {q};"),
    (r"\cornerfigure[corner=ne, node={rotate=-8, fill=c_primary_dark!85, text=c_primary_white}]{q}",
     r"\cornerfigure[corner=ne, node={rotate=-8, fill=c_text!85, text=c_canvas}]{q}"),
    (r"\draw[fill=c_primary_dark, fill opacity=0.85, draw=none] (0,0) rectangle (1,1);",
     r"\draw[fill=c_text, fill opacity=0.85, draw=none] (0,0) rectangle (1,1);"),
    # colour commands
    (r"\arrayrulecolor{c_primary_dark}", r"\arrayrulecolor{c_text}"),
    (r"{\color{c_primary_dark} x}", r"{\color{c_text} x}"),
    (r"\setbeamercolor{footnote}{fg=c_primary_dark}", r"\setbeamercolor{footnote}{fg=c_text}"),
])
def test_a_use_becomes_the_role_its_context_says(before, after):
    assert new(before) == after


@pytest.mark.parametrize("text", [
    "% \\draw[c_primary_dark] (0,0);\n",                                         # a comment
    "\\draw[c_text] (0,0); % c_primary_dark\n",                                  # after a comment sign
    "\\foreach \\c in {c_primary_dark, c_primary_highlight} {\\fill[\\c] (0,0) circle (1);}\n",  # the palette
    "\\foreach \\c/\\n [count=\\i] in {c_primary_dark/a, c_custom_gray/b} {}\n",
    "\\node[text=c_primary_white] at (0,0) {2};\n",                              # white is a physical colour
    "\\draw[c_text, fill=c_canvas] (0,0) circle (1);\n",                         # already migrated
])
def test_what_is_left_alone(text):
    out, result = m.rewrite(text)
    assert out == text and not result.findings


@pytest.mark.parametrize("text, why", [
    (r"\colorbox{c_primary_dark}{x}", "colorbox"),
    (r"\node[top color=c_primary_dark] {x};", "top color"),
    (r"\setbeamercolor{x}{bg=c_primary_dark}", "bg="),
    (r"\href{u}{\textcolor{c_custom_gray}{x}}", "c_link"),
    (r"\colorlet{mine}{c_primary_dark}", "colorlet"),
])
def test_what_cannot_be_classified_is_reported_and_kept(text, why):
    out, result = m.rewrite(text, "slides/x.tex")
    assert out == text
    assert len(result.findings) == 1 and why in result.findings[0].message
    assert result.findings[0].file == "slides/x.tex" and result.findings[0].line == 1


def test_the_rewrite_is_idempotent():
    text = (r"\node[fill=c_primary_dark!85, text=white] {q};" "\n" r"\draw[c_primary_dark, fill=c_primary_white] (0,0);")
    once = new(text)
    assert new(once) == once
    assert "c_primary" not in once


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for sub in ("decks/archive", "slides/.backups", "snippets"):
        (root / sub).mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    slide = "\\begin{tikzpicture}\r\n\\draw[c_primary_dark] (0,0) -- (1,0);\r\n\\end{tikzpicture}\r\n"
    for rel in ("slides/1aa-EN-S-current.tex", "slides/1aa-EN-S-v1-0-0.tex", "snippets/1aa-1.tex",
                "decks/d.tex", "decks/archive/o.tex", "SlideMage_project_macros.tex",
                "SlideMage_template_x.tex", "slides/.backups/1aa-EN-S-current.tex", "decks/_slidemage_p.tex"):
        (root / rel).write_bytes(slide.encode())
    (root / "slides" / "1bb-EN-T-current.tex").write_bytes(b"\\colorbox{c_primary_dark}{x}\n")
    return root


def test_the_project_scope_and_crlf(tmp_path):
    root = make_project(tmp_path)
    plan = m.migrate(root)
    assert sorted(p.as_posix() for p in plan) == [
        "SlideMage_project_macros.tex", "decks/archive/o.tex", "decks/d.tex", "slides/1aa-EN-S-current.tex",
        "slides/1aa-EN-S-v1-0-0.tex", "snippets/1aa-1.tex"]
    assert all(data == b"\\begin{tikzpicture}\r\n\\draw[c_text] (0,0) -- (1,0);\r\n\\end{tikzpicture}\r\n"
               for data in plan.values())
    found = m.detect(root)
    assert any(f.file == "slides/1bb-EN-T-current.tex" and f.line == 1 for f in found)


def test_update_project_runs_it_and_leaves_only_the_reports(tmp_path):
    root = make_project(tmp_path)
    change = next(c for c in compat.CHANGES if c.id == m.CHANGE_ID)
    compat.run_update(root, [Pending(change, m.detect(root))])
    assert b"c_text" in (root / "slides/1aa-EN-S-v1-0-0.tex").read_bytes()
    assert b"c_primary_dark" in (root / "SlideMage_template_x.tex").read_bytes()   # themes are not touched
    assert not m.migrate(root)
    assert [f.file for f in m.detect(root)] == ["slides/1bb-EN-T-current.tex"]
