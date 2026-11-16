# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tikz_render: the frame's own definitions go into an illustration's render, and a failed render is remembered
until its source changes (2026-11-16: the Images page hung 40 s each time it showed 1ym, whose render always
failed for want of the \\pgfmathsetmacro lines above the illustration)."""
from __future__ import annotations

import pytest

from slidemage import tikz_render

SLIDE = """% a note \\pgfmathsetmacro{\\no}{1}
\\begin{standardframe}{First}
\t\\pgfmathsetmacro{\\other}{3}
\\end{standardframe}
\\begin{standardframe}{Boxes}
\tSome text that is not a definition.
\t% \\pgfmathsetmacro{\\commented}{2}
\t\\pgfmathsetmacro{\\ymbox}{min(118, (\\linewidth-2*24pt)/3)}%
\t\\newcommand{\\ymlabel}[1]{%
\t\t\\textbf{#1}%
\t}
\t\\begin{itemize}
\t\t\\item not copied
\t\\end{itemize}
\t\\begin{tikzillustration}[part/.style={text width=\\ymbox pt}]{box-tikz}
\t\t\\node[part] {\\ymlabel{A}};
\t\\end{tikzillustration}
\\end{standardframe}
"""


def test_the_frames_definitions_above_the_illustration_are_found():
    found = tikz_render.frame_definitions(SLIDE, "box-tikz")
    assert found == ("\\pgfmathsetmacro{\\ymbox}{min(118, (\\linewidth-2*24pt)/3)}\n"
                     "\\newcommand{\\ymlabel}[1]{\n\t\t\\textbf{#1}\n\t}\n")
    assert tikz_render.frame_definitions(SLIDE, "missing-tikz") == ""
    plain = "\\begin{standardframe}{T}\nText\n\\begin{tikzillustration}{p-tikz}\n\\draw (0,0);\n\\end{tikzillustration}\n"
    assert tikz_render.frame_definitions(plain, "p-tikz") == ""


@pytest.fixture
def slide(ctx):
    ctx.slides_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.slides_dir / "box-EN-Boxes-current.tex"
    path.write_text(SLIDE, encoding="utf-8")
    return path


def test_a_failed_render_is_remembered_until_the_slide_changes(ctx, slide, monkeypatch):
    wrappers = []

    def failing(ctx, wrapper_text, job, log, **kwargs):
        wrappers.append(wrapper_text)
        raise RuntimeError("Render failed for tikz-box-tikz:\n! Package PGF Math Error")

    monkeypatch.setattr(tikz_render, "compile_and_extract", failing)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="PGF Math Error"):
            tikz_render.ensure_rendered(ctx, "tikz:box-tikz")
    assert len(wrappers) == 1                                   # compiled once, then answered from the record
    assert "\\pgfmathsetmacro{\\ymbox}" in wrappers[0] and "\\newcommand{\\ymlabel}" in wrappers[0]
    assert "not copied" not in wrappers[0] and "\\other" not in wrappers[0]

    slide.write_text(SLIDE.replace("118", "120"), encoding="utf-8")
    with pytest.raises(RuntimeError):
        tikz_render.ensure_rendered(ctx, "tikz:box-tikz")
    assert len(wrappers) == 2                                   # a new source compiles again


def test_a_render_that_works_again_drops_the_record(ctx, slide, monkeypatch, tmp_path):
    calls = []

    def failing(ctx, wrapper_text, job, log, **kwargs):
        calls.append("fail")
        raise RuntimeError("Render failed")

    def working(ctx, wrapper_text, job, log, **kwargs):
        calls.append("ok")
        folder = tmp_path / f"out{len(calls)}"
        folder.mkdir()
        return folder / "x.pdf"

    monkeypatch.setattr(tikz_render, "compile_and_extract", failing)
    with pytest.raises(RuntimeError):
        tikz_render.ensure_rendered(ctx, "tikz:box-tikz")
    failed = list(ctx.tikz_previews_dir.glob("*.failed"))
    assert len(failed) == 1
    failed[0].write_text("another wrapper\nold error", encoding="utf-8")      # as if the framework had changed
    monkeypatch.setattr(tikz_render, "compile_and_extract", working)
    monkeypatch.setattr(tikz_render, "_render_and_crop",
                        lambda ctx, pdf, png: (png.parent.mkdir(parents=True, exist_ok=True), png.write_bytes(b"png")))
    png = tikz_render.ensure_rendered(ctx, "tikz:box-tikz")
    assert png.is_file() and not list(ctx.tikz_previews_dir.glob("*.failed")) and calls == ["fail", "ok"]
    assert tikz_render.ensure_rendered(ctx, "tikz:box-tikz") == png and calls == ["fail", "ok"]
