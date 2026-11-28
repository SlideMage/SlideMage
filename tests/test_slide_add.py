# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide creation, copying, translation and presentation import."""
from __future__ import annotations

import pytest

from slidemage import alt_blocks, deck_editor, fileio, project, slide_add, slide_ids, slide_import, slide_versioning
from slidemage.ai.providers import ChatReply, ProviderError

from conftest import TEMPLATE, use_new_slide_files
from slidemage.project import ProjectContext


@pytest.fixture
def relinked(tmp_path, monkeypatch):
    return use_new_slide_files(monkeypatch, tmp_path)


@pytest.fixture
def files(tmp_path, relinked):
    return tmp_path / "slides"


class Translator:
    is_local = True
    model = "fake"
    label = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.asked = []

    def chat(self, messages, **kwargs):
        self.asked.append(messages[0]["content"])
        if isinstance(self.reply, Exception):
            raise self.reply
        return ChatReply(text=self.reply)

    def abort(self):
        pass


def test_every_frame_has_a_thumbnail_and_a_body_with_the_title(ctx, files):
    assert slide_add.FRAMES[0] == slide_add.STANDARD_FRAME
    for frame in slide_add.FRAMES:
        assert slide_add.frame_thumbnail(frame).is_file(), frame
        body = slide_add.frame_body(ctx, frame, "Growth & R_D")
        assert r"Growth \& R\_D" in body, frame
        assert "\n" not in body.replace("\r\n", ""), frame
        if frame in {"standardframe", "figureframe", "sideimageframe", "highlightframe", "sectionframe", "titleframe"}:
            assert alt_blocks.frame_type(body) == frame


@pytest.mark.parametrize("custom_template", [None, TEMPLATE + "% Custom template\r\n"])
def test_empty_project_can_add_a_standard_slide(tmp_path, custom_template):
    target = tmp_path / "empty-project"
    project.init_project(target, copy_example=False)
    relative = ".scripts/R_Slidemaster/inst/templates/slide-template.tex"
    template = target / relative
    ctx = ProjectContext.at(target)
    expected = (project.template_dir("example") / relative).read_bytes().decode("utf-8")
    if custom_template is not None:
        template.parent.mkdir(parents=True)
        template.write_bytes(custom_template.encode("utf-8"))
        expected = custom_template

    created = slide_add.create_new(ctx, "First", "EN")
    assert created.path.read_bytes().decode("utf-8") == slide_ids.build_new_slide_header() + expected
    assert template.exists() == (custom_template is not None)


@pytest.mark.parametrize("bundled_available", [False, True])
def test_missing_project_and_bundled_templates_raise(tmp_path, monkeypatch, bundled_available):
    ctx = ProjectContext.at(tmp_path)     # no template in it
    monkeypatch.setattr(project, "template_dir", lambda _name: tmp_path if bundled_available else None)

    with pytest.raises(FileNotFoundError, match="No slide template found"):
        slide_ids.read_template(ctx)


def test_a_new_slide_gets_a_fresh_id_a_header_and_the_frames_text(ctx, files):
    created = slide_add.create_new(ctx, "My-Slide", "DE", "quoteframe", "Hello")
    bare, language, slug = created.id_slug.split("-", 2)
    assert (language, slug) == ("DE", "My-Slide") and created.path == files / f"{created.id_slug}-current.tex"
    text = created.path.read_bytes().decode("utf-8")
    assert text.startswith("%% Included in decks: (none)\r\n%%\r\n\r\n")
    assert "\\quoteframe{" in text and "\\SMAgendaTitle{Hello}" in text
    assert bare in slide_ids.existing_ids_from_csv(ctx)
    assert slide_versioning.parse_version(text) is None
    with pytest.raises(ValueError):
        slide_add.create_new(ctx, "Bad", "FR")


def test_copy_of_an_untagged_slide_uses_the_project_language(ctx, files):
    (files / "old-slide-current.tex").write_bytes(b"body")
    assert slide_add.create_copy(ctx, "old-slide", "Copy").id_slug.endswith("-EN-Copy")


@pytest.mark.parametrize("language", [None, "DE"])
def test_copies_start_untracked_and_only_translations_link_back(ctx, files, relinked, language):
    source = files / "abc-EN-Demo-current.tex"
    source_body = "\\setSlideVersion{1-1-0}\r\nText\r\n"
    source_bytes = (slide_ids.build_new_slide_header() + source_body).encode("utf-8")
    source.write_bytes(source_bytes)
    body = source_body.replace("Text", "Übersetzt") if language else None
    copied = slide_add.create_copy(ctx, "abc-EN-Demo", "Copy", language, body=body)

    assert slide_versioning.parse_version(copied.path.read_text()) is None
    assert slide_ids.slide_body(copied.path) == ("Übersetzt\r\n" if language else "Text\r\n")
    assert slide_ids.slide_body(source) == source_body
    assert slide_versioning.parse_version(source.read_text()) == (1, 1, 0)
    if language:
        assert f"%% DE translation: {copied.id_slug}" in source.read_text()
        assert "%% Translation of: abc-EN-Demo" in copied.path.read_text()
    else:
        assert copied.id_slug.endswith("-EN-Copy")
        assert source.read_bytes() == source_bytes and not relinked


def test_slugs():
    assert slide_import.slug_from_title("Growth of R&D spend (50% YoY)", "") == "Growth-of-R-D-spend-50-YoY"
    assert slide_import.slug_from_title("!!!", "Imported-Slide-1") == "Imported-Slide-1"
    assert slide_add.SLUG_RE.fullmatch("MM-Theorem")
    assert not any(slide_add.SLUG_RE.fullmatch(slug) for slug in ("", "-a", "a-", "a--b", "a b", "ä"))


def test_translation_keeps_the_body_whole_and_reports_provider_errors(ctx):
    model = Translator("Hallo\nWelt")
    text, error = slide_add.translate_body(ctx, model, "Hello\r\nWorld\r\n")
    assert (text, error) == ("Hallo\r\nWelt", None) and len(model.asked) == 1 and "Hello\r\nWorld" in model.asked[0]
    assert slide_add.translate_body(ctx, Translator("Hallo\r\nWelt"), "Hello\nWorld")[0] == "Hallo\nWelt"
    text, error = slide_add.translate_body(ctx, Translator(ProviderError("rate limited")), "Hello")
    assert (text, error) == ("", "rate limited")


def test_the_call_follows_the_load_and_the_views():
    views = deck_editor.DEFAULT_CONDITIONS
    assert slide_add.call_spec("live", views) == slide_add.CallSpec("slide")
    assert slide_add.call_spec("live", ["after-course", "instructor"]) == slide_add.CallSpec(
        "conditionalslide", conditions=["instructor", "after-course"])
    assert slide_add.call_spec("frozen", [], "1-0-0") == slide_add.CallSpec("slideversion", "1-0-0")
    assert slide_add.call_spec("step", ["during-course"], steps=" 1, 2 ") == slide_add.CallSpec(
        "slidestep", conditions=["during-course"], steps="1,2")
    assert slide_add.call_spec("step", views).steps == "1"
    for bad in (lambda: slide_add.call_spec("live", []), lambda: slide_add.call_spec("step", views, steps="x"),
                lambda: slide_add.call_spec("frozen", views)):
        with pytest.raises(ValueError):
            bad()
    spec = slide_add.call_spec("step", views, steps="2-")
    assert deck_editor.format_call(spec.macro, "abc-EN-Demo", spec.version, spec.conditions, spec.steps) == \
        "\\slidestep{abc-EN-Demo}[instructor,during-course,after-course]{2-}"


def test_the_project_slides_with_title_and_language(ctx, files):
    (files / "bbb-DE-Zwei-current.tex").write_text("\\begin{standardframe}{Zwei}\nx\n\\end{standardframe}\n")
    (files / "aaa-EN-One-current.tex").write_text("\\begin{standardframe}{One}\nx\n\\end{standardframe}\n")
    (files / "aaa-EN-One-v1-0-0.tex").write_text("frozen")
    assert slide_add.project_slides(ctx) == [
        slide_add.ProjectSlide("aaa-EN-One", "One", "[EN]"), slide_add.ProjectSlide("bbb-DE-Zwei", "Zwei", "[DE]")]


_FAKE_SVM = b"VCLMTF\x01\x001\x00\x00\x00"


TITLE = "Growth of R&D spend (50% YoY)"
BULLETS = ("Top level point #1", "Nested detail A", "Nested detail B", "Second top-level point with $5 cost")


def _make_test_pptx(path, image):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = TITLE
    text = slide.placeholders[1].text_frame
    text.text = BULLETS[0]
    for content, level in zip(BULLETS[1:], (1, 1, 0)):
        paragraph = text.add_paragraph()
        paragraph.text = content
        paragraph.level = level
    slide.shapes.add_picture(str(image), Inches(1), Inches(4))
    prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_picture(str(image), Inches(1), Inches(1))
    prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(path)


def _odp_document():
    from odf.opendocument import OpenDocumentPresentation
    from odf.style import MasterPage, PageLayout

    doc = OpenDocumentPresentation()
    layout = PageLayout(name="PM1")
    doc.automaticstyles.addElement(layout)
    master = MasterPage(name="Default", pagelayoutname=layout)
    doc.masterstyles.addElement(master)
    return doc, master


def _make_test_odp(path, image):
    from odf.draw import Frame, Image, Page, TextBox
    from odf.namespaces import PRESENTATIONNS
    from odf.text import List, ListItem, P

    doc, master = _odp_document()
    href = doc.addPicture(str(image))

    def frame(page, kind, content):
        element = Frame(width="10cm", height="3cm", x="1cm", y="1cm")
        element.setAttrNS(PRESENTATIONNS, "class", kind)
        element.addElement(content)
        page.addElement(element)

    def item(text):
        element = ListItem()
        element.addElement(P(text=text))
        return element

    first, images, blank = [Page(name=name, masterpagename=master) for name in ("Text", "Image", "Blank")]
    title = TextBox()
    title.addElement(P(text=TITLE))
    frame(first, "title", title)

    top = item(BULLETS[0])
    nested = List()
    for text in BULLETS[1:3]:
        nested.addElement(item(text))
    top.addElement(nested)
    outline = List()
    outline.addElement(top)
    outline.addElement(item(BULLETS[-1]))
    box = TextBox()
    box.addElement(outline)
    frame(first, "outline", box)

    for page in (first, images):
        frame(page, "graphic", Image(href=href))
    for page in (first, images, blank):
        doc.presentation.addElement(page)
    doc.save(str(path))


@pytest.fixture(params=["pptx", "odp"])
def sample_presentation(request, tmp_path):
    from PIL import Image

    image = tmp_path / "red.png"
    Image.new("RGB", (200, 100), color=(255, 0, 0)).save(image)
    path = tmp_path / f"sample.{request.param}"
    make = _make_test_pptx if request.param == "pptx" else _make_test_odp
    make(path, image)
    return path


def test_escape_latex_special_characters():
    from slidemage.slide_import import escape_latex

    assert escape_latex("50% off & $5 #1 a_b {x} ~y ^z \\end") == (
        r"50\% off \& \$5 \#1 a\_b \{x\} \textasciitilde{}y "
        r"\textasciicircum{}z \textbackslash{}end"
    )


def _odp_with_one_page(tmp_path, build_page):
    from odf.draw import Page
    doc, master = _odp_document()
    page = Page(name="Slide1", masterpagename=master)
    doc.presentation.addElement(page)
    build_page(doc, page)
    path = tmp_path / "sample.odp"
    doc.save(str(path))
    return path


def test_extract_odp_skips_starview_metafile_masquerading_as_png(tmp_path):
    # A mislabeled LibreOffice metafile used to break the PDF build.
    from odf.draw import Frame, Image

    def build(doc, page):
        href = doc.addPicture("fake.png", mediatype="image/png", content=_FAKE_SVM)
        frame = Frame(width="5cm", height="3cm", x="1cm", y="1cm")
        frame.addElement(Image(href=href))
        page.addElement(frame)

    slides = slide_import.extract_odp(_odp_with_one_page(tmp_path, build))
    assert all(not slide.images for slide in slides)


def test_extract_odp_imports_table_instead_of_its_preview(tmp_path):
    # Import the editable table cells and discard the rendered preview.
    from odf.draw import Frame, Image, TextBox
    from odf.namespaces import PRESENTATIONNS
    from odf.table import CoveredTableCell, Table, TableCell, TableColumn, TableRow
    from odf.text import P

    def build(doc, page):
        table = Table()
        for _ in range(3):
            table.addElement(TableColumn())
        for cells in [(("Date",), ("Topic", "Lecturer")), (("7.10.",), ("Intro & SQL",), ())]:
            row = TableRow()
            for paragraphs in cells:
                cell = TableCell(numbercolumnsspanned=2) if len(paragraphs) == 2 else TableCell()
                for text in paragraphs:
                    cell.addElement(P(text=text))
                row.addElement(cell)
                if len(paragraphs) == 2:
                    row.addElement(CoveredTableCell())
            table.addElement(row)

        table_frame = Frame(width="20cm", height="10cm", x="1cm", y="2cm")
        table_frame.addElement(table)
        href = doc.addPicture("Pictures/TablePreview1.svm", mediatype="image/png", content=_FAKE_SVM)
        table_frame.addElement(Image(href=href))
        page.addElement(table_frame)

        number_frame = Frame(width="5cm", height="1cm", x="1cm", y="18cm")
        number_frame.setAttrNS(PRESENTATIONNS, "class", "page-number")
        tb = TextBox(); tb.addElement(P(text="<Foliennummer>"))
        number_frame.addElement(tb); page.addElement(number_frame)

    [slide] = slide_import.extract_odp(_odp_with_one_page(tmp_path, build))
    assert slide.images == []
    assert slide.bullets == []
    assert [[(c.paragraphs, c.colspan) for c in row] for row in slide.tables[0]] == [
        [(["Date"], 1), (["Topic", "Lecturer"], 2)],
        [(["7.10."], 1), (["Intro & SQL"], 1), ([], 1)],
    ]

    layout, tex = slide_import.slide_content_to_tex(slide, [])
    assert layout == "standardframe"
    assert r"{lll}" in tex and r"\begin{SMTable}" in tex
    assert (
        r"Date & \multicolumn{2}{l@{}}{\begin{tabular}[t]{@{}l@{}}Topic \\ Lecturer\end{tabular}} \\"
        in tex
    )
    assert r"7.10. & Intro \& SQL &  \\" in tex


def test_item_text_starting_with_overlay_bracket_is_protected():
    from slidemage.slide_import import Bullet, _bullets_to_itemize

    tex = _bullets_to_itemize([Bullet("<Foliennummer>"), Bullet("[optional] note")])
    assert r"\item {}<Foliennummer>" in tex
    assert r"\item {}[optional] note" in tex


@pytest.mark.parametrize("children,expected", [
    ([("deep", 2)], "\t\t\t\\item deep\n"),
    ([("deep A", 3), ("deep B", 3)], "\t\t\t\\item deep A\n\t\t\t\\item deep B\n"),
], ids=["missing-level", "repeated-depth-jump-regression"])
def test_bullets_to_itemize_nesting_and_jumps(children, expected):
    from slidemage.slide_import import Bullet, _bullets_to_itemize

    tex = _bullets_to_itemize([
        Bullet("top", level=0),
        *(Bullet(text, level=level) for text, level in children),
        Bullet("back to top", level=0),
    ])
    assert tex == (
        "\t\\begin{itemize}\n"
        "\t\t\\item top\n"
        "\t\t\\begin{itemize}\n"
        + expected +
        "\t\t\\end{itemize}\n"
        "\t\t\\item back to top\n"
        "\t\\end{itemize}"
    )


def test_import_presentation_writes_files_and_appends_deck_calls(sample_presentation, tmp_path):
    from slidemage import deck_scan

    ctx = ProjectContext.at(tmp_path / "project")
    ctx.slides_dir.mkdir(parents=True)
    ctx.decks_dir.mkdir()
    deck_path = ctx.decks_dir / "test.tex"
    deck_path.write_text("\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n")
    deck = deck_scan.read_deck(deck_path)

    progress = []
    summary = slide_import.import_presentation(ctx, sample_presentation, deck, "EN", on_progress=progress.append)
    text_slide, image_slide = summary.imported
    assert summary.skipped_blank == 1
    assert (text_slide.layout, image_slide.layout) == ("standardframe", "figureframe")
    assert progress[0].fraction is None and progress[-1].fraction == 1
    assert summary.after == deck_path.read_bytes().decode("utf-8")
    for slide in summary.imported:
        assert f"\\slide{{{slide.id_slug}}}" in summary.after
        assert slide.id_slug.split("-", 1)[0] in slide_ids.existing_ids_from_csv(ctx)

    text, image = ((ctx.slides_dir / f"{slide.id_slug}-current.tex").read_text() for slide in summary.imported)
    assert r"\begin{standardframe}{Growth of R\&D spend (50\% YoY)}" in text
    assert r"\item Top level point \#1" in text and r"\item Second top-level point with \$5 cost" in text
    assert "\n\t\t\\begin{itemize}\n\t\t\t\\item Nested detail A\n\t\t\t\\item Nested detail B\n" in text
    assert r"\begin{figureframe}{Untitled}" in image and r"\includegraphics" in image
    media = list((ctx.root / "media").glob("*.png"))
    assert len(media) == 2 and all(path.read_bytes().startswith(b"\x89PNG") for path in media)


@pytest.mark.parametrize("target", ["slide", "registry"])
def test_new_slide_write_failure_leaves_neither_file_nor_id(ctx, monkeypatch, target):
    before = slide_ids.existing_ids_from_csv(ctx)
    publish = fileio.atomic_write

    def fail_write(path, data, **kwargs):
        if (path == ctx.slide_ids_csv) == (target == "registry"):
            raise OSError("write failed")
        return publish(path, data, **kwargs)

    monkeypatch.setattr(fileio, "atomic_write", fail_write)
    with pytest.raises(OSError, match="write failed"):
        slide_add.create_new(ctx, "Failed", "EN")
    assert not list(ctx.slides_dir.glob("*-Failed-current.tex"))
    assert slide_ids.existing_ids_from_csv(ctx) == before
