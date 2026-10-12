"""The v5.x figure helpers name their image as an argument: the image scan and
the pre-render check must see it."""
from slidemage import alt_blocks, latex_lint
from slidemage.project import ProjectContext


SLIDE = (
    "\\begin{standardframe}{T}\n"
    "\\begin{besidefigure}[height=4cm, border]{media/a.png}\n text \\end{besidefigure}\n"
    "\\cornerfigure[width=3cm]{media/b.png}\n"
    "\\cornerfigure[block]{\\begin{gothamfloatinginfoblock}{5cm}{T} x \\end{gothamfloatinginfoblock}}\n"
    "\\cornerfigure{\\includegraphics[width=2cm]{media/c.png}}\n"
    "\\fitfigure[top=here]{media/d.png}\n"
    "\\end{standardframe}\n"
)


def test_referenced_images_finds_the_figure_helpers():
    refs = alt_blocks.referenced_images(SLIDE + "\\begin{sectionframe}{S}\\sectionfigure{media/e.pdf}\\end{sectionframe}")
    assert refs == ["media/a.png", "media/b.png", "media/c.png", "media/d.png", "media/e.pdf"]


def test_lint_reports_a_missing_figure_helper_image(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    missing = sorted(i.message for i in latex_lint.lint_text(ctx, SLIDE) if i.code == "image")
    assert missing == [f"image file 'media/{n}.png' does not exist" for n in "abcd"]
