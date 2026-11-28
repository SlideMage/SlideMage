# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from slidemage import alt_blocks, latex_lint
from slidemage.project import ProjectContext


SLIDE = (
    "\\begin{standardframe}{T}\n"
    "\\begin{besidefigure}[height=4cm, border]{media/a.png}\n text \\end{besidefigure}\n"
    "\\cornerfigure[width=3cm]{media/b.png}\n"
    "\\cornerfigure[block]{\\begin{SMFloatingInfoBlock}{5cm}{T} x \\end{SMFloatingInfoBlock}}\n"
    "\\cornerfigure{\\includegraphics[width=2cm]{media/c.png}}\n"
    "\\fitfigure[top=here]{media/d.png}\n"
    "\\end{standardframe}\n"
)


def test_figure_helper_images_are_found_and_missing_ones_are_reported(tmp_path):
    refs = alt_blocks.referenced_images(SLIDE + "\\begin{sectionframe}{S}\\sectionfigure{media/e.pdf}\\end{sectionframe}")
    assert refs == ["media/a.png", "media/b.png", "media/c.png", "media/d.png", "media/e.pdf"]
    ctx = ProjectContext.at(tmp_path)
    missing = sorted(i.message for i in latex_lint.lint_text(ctx, SLIDE) if i.code == "image")
    assert missing == [f"image file 'media/{n}.png' does not exist" for n in "abcd"]
