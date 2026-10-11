import pytest

from slidemage import slide_language, slide_rename, unused_content
from slidemage.app_info import license_text

STEP_SLIDE = "1mu-EN-Slidestep-Demo"   # the manual's \slidestep demo


def test_raw_reads_work_below_python_313():
    slide_language.cross_referenced_language("1vn-EN-Languages")
    assert "slidemage-manual" in slide_rename.deck_names_referencing(STEP_SLIDE)


def test_license_found_outside_project():
    assert "Slidemaster" in license_text()


def test_slidestep_slide_counts_as_used():
    unused = {p.name for p in unused_content.find_unused_slides()}
    assert f"{STEP_SLIDE}-current.tex" not in unused


def test_line_removal_takes_whole_calls_and_crlf():
    deck = (
        "\\slide{keep-EN-A}\r\n"
        "\\slideversion{gone-EN-B}{1-0-0}\r\n"
        "\t\\slidestep{gone-EN-B}[instructor]{1,2}  \r\n"
        "\\conditionalslide[after-course]{gone-EN-B}\n"
        "\\slide{gone-EN-B-longer}\r\n"
    )
    new, n = slide_rename._line_removal_pattern("gone-EN-B").subn("", deck)
    assert n == 3
    assert new == "\\slide{keep-EN-A}\r\n\\slide{gone-EN-B-longer}\r\n"


def _fake_deck(**overrides):
    from slidemage.deck_scan import Deck

    fields = dict(
        name="fake", path=None, archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0, chapters=[], output_folders={}, tags=[],
    )
    fields.update(overrides)
    return Deck(**fields)


def test_wrapper_write_does_not_double_crlf(tmp_path):
    # Same bug slide_preview.py's own wrapper write already guards against:
    # writing CRLF content (deck_scan.py reads deck text with newline="",
    # so a real deck's preamble_text/chapter_text already carries literal
    # "\r\n") with the default newline translation doubles every "\r" into
    # "\r\r\n" on Windows. run_job() must write with newline="" too.
    from slidemage import compiler

    wrapper = tmp_path / "wrapper.tex"
    content = "line one\r\nline two\r\n"
    wrapper.write_text(content, encoding="utf-8", newline="")
    assert wrapper.read_bytes().decode("utf-8") == content


def test_deckoutputfolder_collision_falls_back_to_jobname(tmp_path):
    from slidemage.compiler import CompileJob, Chapter, _disambiguated_destinations

    deck = _fake_deck(
        name="course", chapters=[
            Chapter(order=1, title="A", slug="A", start=0, end=0),
            Chapter(order=2, title="B", slug="B", start=0, end=0),
        ],
        output_folders={"after-course": str(tmp_path / "Handout.pdf")},
    )
    jobs = [
        CompileJob(deck, "after-course", deck.chapters[0]),
        CompileJob(deck, "after-course", deck.chapters[1]),
    ]
    logged = []
    dests = _disambiguated_destinations(jobs, logged.append)
    resolved = {dests[id(job)] for job in jobs}
    assert len(resolved) == 2  # no longer collide
    assert all(stem == job.jobname for job, (_, stem) in zip(jobs, [dests[id(j)] for j in jobs]))
    assert any("shared by 2 jobs" in line for line in logged)


def test_deckoutputfolder_no_collision_keeps_literal_name(tmp_path):
    from slidemage.compiler import CompileJob, _disambiguated_destinations

    deck = _fake_deck(
        name="solo", supports_version=False,
        output_folders={None: str(tmp_path / "Handout.pdf")},
    )
    jobs = [CompileJob(deck, None, None)]
    logged = []
    dests = _disambiguated_destinations(jobs, logged.append)
    output_dir, stem = dests[id(jobs[0])]
    assert stem == "Handout"  # single job, no collision -- literal name kept
    assert not logged


def test_presenter_fallback_collision_is_disambiguated(tmp_path):
    from slidemage.compiler import CompileJob, _disambiguated_destinations

    deck = _fake_deck(
        name="course", supports_version=True,
        output_folders={"instructor": str(tmp_path / "Handout.pdf")},
    )
    ordinary = CompileJob(deck, "instructor", None)
    presenter = CompileJob(deck, "instructor", None, presenter=True)
    logged = []
    dests = _disambiguated_destinations([ordinary, presenter], logged.append)
    assert dests[id(ordinary)] != dests[id(presenter)]


def _fake_deck_with_text(text, **overrides):
    from slidemage.deck_scan import Deck

    doc_begin = text.find("\\begin{document}")
    fields = dict(
        name="fake", path=None, archived=False, text=text, supports_version=False,
        uses_biblatex=False,
        preamble_end=(doc_begin + len("\\begin{document}")) if doc_begin != -1 else None,
        chapters=[], output_folders={}, tags=[],
    )
    fields.update(overrides)
    return Deck(**fields)


def test_commented_out_section_is_not_a_chapter():
    from slidemage.deck_scan import parse_chapters

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\section{Intro}\n\\slide{aaa-EN-A}\n"
        "% \\section{Old stuff}\n\\slide{bbb-EN-B}\n\\end{document}\n"
    )
    chapters = parse_chapters(text)
    assert [c.title for c in chapters] == ["Intro"]
    # The real chapter's own span still covers the commented line as
    # ordinary content -- offsets must stay into the *original* text.
    expected = text[text.index("\\section{Intro}"):text.index("\\end{document}")]
    assert text[chapters[0].start:chapters[0].end] == expected


def test_commented_out_slide_call_is_excluded_from_appendix():
    from slidemage import deck_editor

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{abc-EN-Old}\n% \\slide{xyz-EN-Old}\n\\end{document}\n"
    )
    deck = _fake_deck_with_text(text)
    calls = deck_editor.parse_slide_calls(deck)
    commented = {c.id_slug: deck_editor.is_commented_out(deck.text, c) for c in calls}
    assert commented == {"abc-EN-Old": False, "xyz-EN-Old": True}


def test_save_slide_source_detects_stale_disk_content(tmp_path):
    from slidemage import slide_source

    slide_path = tmp_path / "abc-EN-Test-current.tex"
    slide_path.write_text("original\n", encoding="utf-8", newline="")

    # Another writer (a citation dialog, header regeneration, ...) changes
    # the file after this "tab" read it.
    loaded_text, eol = slide_source.read_slide_source(slide_path)
    slide_path.write_text("changed elsewhere\n", encoding="utf-8", newline="")

    import pytest

    with pytest.raises(slide_source.StaleFileError):
        slide_source.save_slide_source(
            slide_path, "my edit\n", eol, expected_text=loaded_text
        )
    # Nothing was overwritten or backed up.
    assert slide_path.read_text(encoding="utf-8") == "changed elsewhere\n"
    assert not (tmp_path / ".backups").exists()


def test_save_slide_source_without_expected_text_still_overwrites(tmp_path):
    from slidemage import slide_source

    slide_path = tmp_path / "abc-EN-Test-current.tex"
    slide_path.write_text("original\n", encoding="utf-8", newline="")
    slide_source.save_slide_source(slide_path, "new content\n", "\n")
    assert slide_path.read_text(encoding="utf-8") == "new content\n"


def test_stale_translation_is_not_written_as_in_sync(monkeypatch, tmp_path):
    """A batch translation whose English text has since been edited must
    not be saved with a translated_from_hash that makes translation_state()
    call it 'in sync' -- see alt_draft.apply_one_translation's own comment
    for the full scenario (a long-running 'Translate all' batch snapshots
    its queue once up front)."""
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="original english", takeaway_default="t1")
    original_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    # The batch translates from a queue snapshot taken before this edit.
    stale_result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated from the OLD text",
        takeaway_de="t1-de", model="test", source_hash=original_hash,
    )

    # ... then, while that translation was in flight, the user edits the
    # English text (e.g. via the review tab, on the GUI thread).
    def edit_english(entries):
        entries["media/x.png"].long = "edited english"
        return True

    alt_images.update_store(edit_english)

    written = alt_draft.apply_one_translation("media/x.png", stale_result, "test")
    assert written is False

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == ""  # stale translation was NOT written
    assert current.translated_from_hash == ""


def test_fresh_translation_is_written_normally(monkeypatch, tmp_path):
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="english text", takeaway_default="t1")
    current_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated text",
        takeaway_de="t1-de", model="test", source_hash=current_hash,
    )
    written = alt_draft.apply_one_translation("media/x.png", result, "test")
    assert written is True

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == "translated text"
    assert current.translated_from_hash == current_hash


def test_relaunch_with_project_saves_and_spawns(monkeypatch, tmp_path):
    """2026-09-23: on a fresh machine's first real run, cli.py's discovery
    chain (env var / upward search / last project) can silently reuse a
    stale last-project pointer left over from unrelated testing, so the
    user never sees the folder picker they expected. The fix adds an
    explicit "Open Project..." action; this covers its
    underlying relaunch mechanism, since a live in-process project switch
    isn't possible (PROJECT_ROOT and everything derived from it are fixed
    at import time across the whole package)."""
    from slidemage import project

    new_root = tmp_path / "other-project"
    new_root.mkdir()
    (new_root / project.MARKER).write_text("id,slug\n", encoding="utf-8")
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")

    calls = []
    monkeypatch.setattr(
        project.subprocess, "Popen",
        lambda argv, env: calls.append((argv, env)),
    )

    project.relaunch_with_project(new_root)

    assert project.load_last_project() == new_root
    assert len(calls) == 1
    argv, env = calls[0]
    assert str(new_root) in argv
    assert env[project.ENV_VAR] == str(new_root)


def test_discover_ignores_unrelated_cwd_with_no_last_project(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.delenv(project.ENV_VAR, raising=False)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert project.discover() is None


def _make_project(root):
    from slidemage import project

    root.mkdir(parents=True, exist_ok=True)
    (root / project.MARKER).write_text("id,slug\n", encoding="utf-8")
    return root


def test_last_project_is_also_kept_beside_the_exe(monkeypatch, tmp_path):
    """A second PC running the same cloud-synced exe has no %APPDATA% pointer;
    the copy beside the exe lets it open the project without the picker."""
    import sys
    from slidemage import project

    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "SlideMage.exe"))
    root = _make_project(tmp_path / "Slidemaster")

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc1")
    project.save_last_project(root)
    assert (exe_dir / "last_project").read_text(encoding="utf-8") == str(root)

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc2")  # nothing there
    assert project.load_last_project() == root


def test_last_project_without_exe_writes_only_the_config_file(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    root = _make_project(tmp_path / "p")
    project.save_last_project(root)
    assert project.load_last_project() == root
    assert not (tmp_path / "last_project").exists()


def test_last_project_hint_is_nearest_existing_folder(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    root = _make_project(tmp_path / "cloud" / "Slidemaster")
    project.save_last_project(root)
    (root / project.MARKER).unlink()
    root.rmdir()
    assert project.load_last_project() is None
    assert project.last_project_hint() == tmp_path / "cloud"


def test_ollama_host_setting_overrides_default(monkeypatch, tmp_path):
    """2026-09-23 review finding: the Ollama host was a hardcoded constant
    duplicated in alt_draft.py and ai_draft.py, with no way to point this
    app at a non-default Ollama server. app_settings.get_ollama_host()
    resolves it; OllamaProvider reads it when constructed instead of
    freezing a constant at class-definition time."""
    from slidemage import app_settings
    from slidemage.ai.providers import OllamaProvider

    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    assert app_settings.get_ollama_host() == "http://localhost:11434"

    app_settings.set_ollama_host("http://gpu-box:9999")
    assert app_settings.get_ollama_host() == "http://gpu-box:9999"
    assert OllamaProvider("m").host == "http://gpu-box:9999"

    # An explicit host= still wins over the saved setting.
    assert OllamaProvider("m", host="http://explicit").host == "http://explicit"

    # Clearing it falls back through $OLLAMA_HOST, then the plain default.
    app_settings.set_ollama_host("")
    assert app_settings.get_ollama_host() == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://from-env:8000")
    assert app_settings.get_ollama_host() == "http://from-env:8000"


def test_draft_prompt_is_customizable_and_persists(monkeypatch, tmp_path):
    """2026-09-23 review finding: alt_draft.py's image-description prompt
    was a hardcoded SYSTEM_PROMPT constant -- unlike translation_prompts.py's
    already-customizable prompts, there was no way to tune it without
    editing source."""
    from slidemage import alt_draft, draft_prompts
    from slidemage.ai.providers import OllamaProvider

    monkeypatch.setattr(draft_prompts, "STORE_PATH", tmp_path / "draft_prompts.json")

    assert alt_draft.effective_system_prompt() == alt_draft.SYSTEM_PROMPT

    draft_prompts.set_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT, "Custom draft prompt.")
    assert alt_draft.effective_system_prompt() == "Custom draft prompt."

    # A freshly constructed backend with no explicit system_prompt picks
    # up the current custom default; an explicit one still overrides it.
    provider = OllamaProvider("m")
    assert alt_draft.ModelBackend(provider).system_prompt == "Custom draft prompt."
    assert alt_draft.ModelBackend(provider, system_prompt="one-off").system_prompt == "one-off"

    # Clearing (empty string) reverts to the hardcoded default.
    draft_prompts.set_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT, "")
    assert alt_draft.effective_system_prompt() == alt_draft.SYSTEM_PROMPT
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None


def test_init_project_seeds_from_example_and_compiles(tmp_path):
    """2026-09-23, direct report: picked an intentionally empty folder on
    first startup, meant to become a brand-new project, and got only
    "has no slide_ids.csv" with no way to actually create one there.
    init_project() (wired into both cli.py's first-run picker and
    the "Open Project..." action) fixes that -- verifies the seeded copy
    is not just a valid project by marker, but an actually compilable one."""
    from slidemage import project

    assert project.has_example_template()
    target = tmp_path / "new_project"
    project.init_project(target, copy_example=True)
    assert project.is_project(target)
    assert (target.parent / "latex").is_dir()
    assert (target / "decks" / "slidemage-manual.tex").is_file()
    # No build output copied in -- a new project compiles its own.
    assert not (target / "decks" / "slidemage-manual.pdf").exists()
    assert not (target / ".build").exists()
    # The real logo asset (not build output) must still be there, or the
    # copy can't actually compile.
    assert (target / "schemes" / "scheme_uni_graz" /
            "Logo_Uni-Graz_4c-cropped.pdf").is_file()


def test_init_project_empty_fallback(tmp_path):
    from slidemage import project

    target = tmp_path / "blank_project"
    project.init_project(target, copy_example=False)
    assert project.is_project(target)
    assert (target / "slide_ids.csv").read_bytes() == b'"id"\r\n'
    for sub in ("slides", "decks", "media"):
        assert (target / sub).is_dir()


def test_init_project_never_overwrites_existing_latex_sibling(tmp_path):
    """A sibling latex/ several projects might already share must never
    be silently stomped by scaffolding a new project next to it."""
    from slidemage import project

    (tmp_path / "latex").mkdir()
    (tmp_path / "latex" / "sentinel.txt").write_text("do not touch")
    target = tmp_path / "new_project"
    project.init_project(target, copy_example=True)
    assert (tmp_path / "latex" / "sentinel.txt").read_text() == "do not touch"


def _make_test_pptx(path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Growth of R&D spend (50% YoY)"
    tf = slide.placeholders[1].text_frame
    tf.text = "Top level point #1"
    p2 = tf.add_paragraph(); p2.text = "Nested detail A"; p2.level = 1
    p3 = tf.add_paragraph(); p3.text = "Nested detail B"; p3.level = 1
    p4 = tf.add_paragraph(); p4.text = "Second top-level point with $5 cost"; p4.level = 0

    img_path = path.parent / "red.png"
    from PIL import Image
    Image.new("RGB", (200, 100), color=(255, 0, 0)).save(img_path)
    slide.shapes.add_picture(str(img_path), Inches(1), Inches(4))

    image_only = prs.slides.add_slide(prs.slide_layouts[6])
    image_only.shapes.add_picture(str(img_path), Inches(1), Inches(1))

    prs.slides.add_slide(prs.slide_layouts[6])  # blank
    prs.save(str(path))


def _make_test_odp(path):
    from odf.draw import Frame, Image, Page, TextBox
    from odf.namespaces import PRESENTATIONNS
    from odf.opendocument import OpenDocumentPresentation
    from odf.style import MasterPage, PageLayout
    from odf.text import P, List, ListItem

    doc = OpenDocumentPresentation()
    layout = PageLayout(name="PM1")
    doc.automaticstyles.addElement(layout)
    master = MasterPage(name="Default", pagelayoutname=layout)
    doc.masterstyles.addElement(master)

    def make_page(name):
        p = Page(name=name, masterpagename=master)
        doc.presentation.addElement(p)
        return p

    page1 = make_page("Slide1")
    title_frame = Frame(width="25cm", height="3cm", x="1cm", y="1cm")
    title_frame.setAttrNS(PRESENTATIONNS, "class", "title")
    tb = TextBox(); tb.addElement(P(text="Growth of R&D spend (50% YoY)"))
    title_frame.addElement(tb); page1.addElement(title_frame)

    content_frame = Frame(width="20cm", height="10cm", x="1cm", y="4cm")
    content_frame.setAttrNS(PRESENTATIONNS, "class", "outline")
    tb2 = TextBox()
    top_level = List()
    top_item = ListItem(); top_item.addElement(P(text="Top level point #1"))
    nested = List()
    li1 = ListItem(); li1.addElement(P(text="Nested detail A")); nested.addElement(li1)
    li2 = ListItem(); li2.addElement(P(text="Nested detail B")); nested.addElement(li2)
    top_item.addElement(nested)
    top_level.addElement(top_item)
    second_item = ListItem()
    second_item.addElement(P(text="Second top-level point with $5 cost"))
    top_level.addElement(second_item)
    tb2.addElement(top_level)
    content_frame.addElement(tb2); page1.addElement(content_frame)

    img_path = path.parent / "red.png"
    from PIL import Image as PILImage
    PILImage.new("RGB", (200, 100), color=(255, 0, 0)).save(img_path)
    img_href = doc.addPicture(str(img_path))
    img_frame = Frame(width="5cm", height="3cm", x="2cm", y="15cm")
    img_frame.addElement(Image(href=img_href)); page1.addElement(img_frame)

    page2 = make_page("Slide2")
    img_frame2 = Frame(width="10cm", height="6cm", x="2cm", y="2cm")
    img_frame2.addElement(Image(href=img_href)); page2.addElement(img_frame2)

    make_page("Slide3")  # blank
    doc.save(str(path))


@pytest.fixture(params=["pptx", "odp"])
def sample_presentation(request, tmp_path):
    from slidemage import slide_import

    if request.param == "pptx":
        path = tmp_path / "sample.pptx"
        _make_test_pptx(path)
        return path, slide_import.extract_pptx
    path = tmp_path / "sample.odp"
    _make_test_odp(path)
    return path, slide_import.extract_odp


def test_escape_latex_special_characters():
    from slidemage.slide_import import escape_latex

    assert escape_latex("50% off & $5 #1 a_b {x} ~y ^z \\end") == (
        r"50\% off \& \$5 \#1 a\_b \{x\} \textasciitilde{}y "
        r"\textasciicircum{}z \textbackslash{}end"
    )


def test_slug_from_title():
    from slidemage.slide_import import slug_from_title

    assert slug_from_title("Growth of R&D spend (50% YoY)", "fallback") == \
        "Growth-of-R-D-spend-50-YoY"
    assert slug_from_title("", "Imported-Slide-1") == "Imported-Slide-1"
    assert slug_from_title("!!!", "Imported-Slide-2") == "Imported-Slide-2"


_FAKE_SVM = b"VCLMTF\x01\x001\x00\x00\x00"


def _odp_with_one_page(tmp_path, build_page):
    from odf.draw import Page
    from odf.opendocument import OpenDocumentPresentation
    from odf.style import MasterPage, PageLayout

    doc = OpenDocumentPresentation()
    layout = PageLayout(name="PM1")
    doc.automaticstyles.addElement(layout)
    master = MasterPage(name="Default", pagelayoutname=layout)
    doc.masterstyles.addElement(master)
    page = Page(name="Slide1", masterpagename=master)
    doc.presentation.addElement(page)
    build_page(doc, page)
    path = tmp_path / "sample.odp"
    doc.save(str(path))
    return path


def test_extract_odp_skips_starview_metafile_masquerading_as_png(tmp_path):
    # LibreOffice's VCLMTF format, labeled image/png in the manifest, used
    # to be written as "imported-...png" and broke the PDF build (libpng:
    # "Not a PNG file").
    from odf.draw import Frame, Image
    from slidemage import slide_import

    def build(doc, page):
        href = doc.addPicture("fake.png", mediatype="image/png", content=_FAKE_SVM)
        frame = Frame(width="5cm", height="3cm", x="1cm", y="1cm")
        frame.addElement(Image(href=href))
        page.addElement(frame)

    slides = slide_import.extract_odp(_odp_with_one_page(tmp_path, build))
    assert all(not slide.images for slide in slides)


def test_extract_odp_imports_table_instead_of_its_preview(tmp_path):
    # A table frame carries both the <table:table> and a TablePreview .svm
    # picture of it; the table's own cells are the content.
    from odf.draw import Frame, Image, TextBox
    from odf.namespaces import PRESENTATIONNS
    from odf.table import CoveredTableCell, Table, TableCell, TableColumn, TableRow
    from odf.text import P
    from slidemage import slide_import

    def build(doc, page):
        table = Table()
        for _ in range(3):
            table.addElement(TableColumn())
        header = TableRow()
        c1 = TableCell(); c1.addElement(P(text="Date")); header.addElement(c1)
        c2 = TableCell(numbercolumnsspanned=2)
        c2.addElement(P(text="Topic")); c2.addElement(P(text="Lecturer"))
        header.addElement(c2); header.addElement(CoveredTableCell())
        table.addElement(header)
        body = TableRow()
        for text in ["7.10.", "Intro & SQL", ""]:
            cell = TableCell()
            if text:
                cell.addElement(P(text=text))
            body.addElement(cell)
        table.addElement(body)

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
    assert r"\begin{gothamtable}[gap=12pt]{lll}" in tex
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


def test_bullets_to_itemize_nesting_and_jumps():
    from slidemage.slide_import import Bullet, _bullets_to_itemize

    tex = _bullets_to_itemize([
        Bullet("top", level=0),
        Bullet("deep", level=2),  # missing level 1 collapses to a valid child list
        Bullet("back to top", level=0),
    ])
    assert tex == (
        "\t\\begin{itemize}\n"
        "\t\t\\item top\n"
        "\t\t\\begin{itemize}\n"
        "\t\t\t\\item deep\n"
        "\t\t\\end{itemize}\n"
        "\t\t\\item back to top\n"
        "\t\\end{itemize}"
    )


def test_bullets_to_itemize_keeps_repeated_depth_jumps_as_siblings():
    from slidemage.slide_import import Bullet, _bullets_to_itemize

    tex = _bullets_to_itemize([
        Bullet("top", level=0),
        Bullet("deep A", level=3),
        Bullet("deep B", level=3),
        Bullet("back to top", level=0),
    ])

    assert tex == (
        "\t\\begin{itemize}\n"
        "\t\t\\item top\n"
        "\t\t\\begin{itemize}\n"
        "\t\t\t\\item deep A\n"
        "\t\t\t\\item deep B\n"
        "\t\t\\end{itemize}\n"
        "\t\t\\item back to top\n"
        "\t\\end{itemize}"
    )


def test_extract_matches_across_pptx_and_odp(sample_presentation):
    path, extractor = sample_presentation
    slides = extractor(path)

    assert len(slides) == 3
    text_slide, image_only_slide, blank_slide = slides

    assert text_slide.title == "Growth of R&D spend (50% YoY)"
    assert [(b.text, b.level) for b in text_slide.bullets] == [
        ("Top level point #1", 0),
        ("Nested detail A", 1),
        ("Nested detail B", 1),
        ("Second top-level point with $5 cost", 0),
    ]
    assert len(text_slide.images) == 1
    assert text_slide.images[0][0][:4] == b"\x89PNG"
    assert text_slide.has_text and not text_slide.is_blank

    assert not image_only_slide.has_text
    assert len(image_only_slide.images) == 1
    assert not image_only_slide.is_blank

    assert blank_slide.is_blank


def test_slide_content_to_tex_standardframe_vs_figureframe():
    from slidemage.slide_import import Bullet, SlideContent, slide_content_to_tex

    text_content = SlideContent(title="A title", bullets=[Bullet("point", level=0)])
    layout, tex = slide_content_to_tex(text_content, [])
    assert layout == "standardframe"
    assert tex.startswith(r"\begin{standardframe}{A title}")
    assert r"\item point" in tex

    image_content = SlideContent(images=[(b"x", ".png")])
    layout, tex = slide_content_to_tex(image_content, ["media/x.png"])
    assert layout == "figureframe"
    assert tex.startswith(r"\begin{figureframe}{Untitled}")
    assert r"\includegraphics[height=0.72\textheight]{media/x.png}" in tex


def test_import_presentation_writes_files_and_appends_deck_calls(sample_presentation, tmp_path, monkeypatch):
    from slidemage import deck_scan, slide_ids, slide_import

    path, _extractor = sample_presentation
    project_root = tmp_path / "project"
    (project_root / "slides").mkdir(parents=True)
    (project_root / "decks").mkdir()
    monkeypatch.setattr(slide_import, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", project_root / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", project_root / "slide_ids.csv")

    deck_text = "\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n"
    deck_path = project_root / "decks" / "test.tex"
    deck_path.write_text(deck_text, encoding="utf-8", newline="")
    deck = deck_scan.Deck(
        name="test", path=deck_path, archived=False, text=deck_text, supports_version=False,
        uses_biblatex=False, preamble_end=None, chapters=[], output_folders={}, tags=[],
    )

    summary = slide_import.import_presentation(path, deck, "EN")

    assert len(summary.imported) == 2
    assert summary.skipped_blank == 1
    assert [s.layout for s in summary.imported] == ["standardframe", "figureframe"]

    new_deck_text = deck_path.read_bytes().decode("utf-8")
    for slide in summary.imported:
        assert f"\\slide{{{slide.id_slug}}}" in new_deck_text
        slide_file = project_root / "slides" / f"{slide.id_slug}-current.tex"
        assert slide_file.is_file()

    csv_text = (project_root / "slide_ids.csv").read_bytes().decode("utf-8")
    for slide in summary.imported:
        expected_id = slide.id_slug.split("-", 1)[0]
        assert f'"{expected_id}"' in csv_text

    media_files = list((project_root / "media").glob("*.png"))
    assert len(media_files) == 2
