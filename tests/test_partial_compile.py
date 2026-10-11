"""partial_compile: compile some slides of a deck, numbered as in the whole
deck, and swap the new pages into the whole-deck PDF."""
from __future__ import annotations

import time
from pathlib import Path

import pymupdf as fitz
import pytest

from slidemage import compile_records, compiler, deck_scan, partial_compile
from slidemage.partial_compile import PartialError, format_page_spec, parse_page_spec

DECK = ("\\documentclass{beamer}\n\\begin{document}\n"
        "\\section{One}\n"
        "\\slide{1aa-EN-A}\n"
        "\\slide{1bb-EN-B}\n"
        "\\slide{1cc-EN-C}\n"
        "\\end{document}\n")


def make_pdf(path: Path, pages: list[tuple[str, str, int]], links=None) -> Path:
    """pages: (body text, slide id, frame number) per page."""
    doc = fitz.open()
    for body, slide_id, frame in pages:
        page = doc.new_page(width=400, height=225)
        page.insert_text((20, 40), body)
        page.insert_text((20, 215), f"(slide id: {slide_id} | v1.0.0EN | instructor deck)  {frame}",
                         fontsize=5)
    for i, page_links in (links or {}).items():
        for link in page_links:
            doc[i].insert_link(link)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def full_pages():
    return [("A text", "1aa", 1), ("B old step 1", "1bb", 2), ("B old step 2", "1bb", 2),
            ("C text", "1cc", 3)]


@pytest.fixture
def deck_on_record(tmp_path, monkeypatch, request):
    root = tmp_path / "Proj"
    build = root / ".build"
    monkeypatch.setattr(compiler, "BUILD_DIR", build)
    monkeypatch.setattr(compiler, "PROJECT_ROOT", root)
    monkeypatch.setattr(compile_records, "engine_version", lambda: "E")
    deck_file = root / "decks" / "t-D.tex"
    deck_file.parent.mkdir(parents=True)
    deck_text = DECK
    inputs = [deck_file]
    if getattr(request, "param", None):
        fragment = deck_file.parent / "fragment.tex"
        fragment.write_text("\\section{Fragment}\n% " + "padding " * 20 + "\n"
                            "\\slide{1bb-EN-B}\n", encoding="utf-8")
        inputs.append(fragment)
        deck_text = DECK.replace("\\slide{1bb-EN-B}\n", f"\\{request.param}{{fragment}}\n")
    deck_file.write_text(deck_text, encoding="utf-8", newline="")
    for slug in ("1aa-EN-A", "1bb-EN-B", "1cc-EN-C"):
        f = root / "slides" / f"{slug}-current.tex"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"slide {slug}\n", encoding="utf-8")
    deck = deck_scan.scan_dir(root / "decks", False)[0]
    job = compiler.CompileJob(deck, None, None)
    inv = build / "t-D-x"
    inv.mkdir(parents=True)
    (inv / "t-D.fls").write_text("".join(
        f"INPUT {p}\n" for p in [*inputs, *sorted((root / "slides").iterdir())]), encoding="utf-8")
    (inv / "t-D.log").write_text("ok\n", encoding="utf-8")
    (inv / "t-D.aux").write_text("\\relax\n", encoding="utf-8")
    pdf = make_pdf(root / "pdf" / "t-D.pdf", full_pages())
    assert compile_records.write_record(build, "t-D", inv, deck_file / "_w.tex",
                                        compiler.wrapper_text(job), pdf, time.time() + 1,
                                        deck_path=deck_file)
    return root, job, pdf


def test_page_spec():
    assert parse_page_spec("4, 5, 7-10, 15") == [4, 5, 7, 8, 9, 10, 15]
    assert format_page_spec([4, 5, 7, 8, 9, 10, 15]) == "4-5, 7-10, 15"
    for bad in ("", "a", "5-3", "0"):
        with pytest.raises(PartialError):
            parse_page_spec(bad)


@pytest.mark.parametrize("deck_on_record", [None, "input", "include"], indirect=True,
                         ids=["inline", "input", "include"])
def test_page_compile_maps_slides_and_preserves_numbers(deck_on_record):
    _root, job, _pdf = deck_on_record
    plan = partial_compile.plan(job, "2, 9")
    assert [k.call.id for k in plan.kept] == ["1bb"]
    assert plan.kept[0].first_frame == 2 and plan.kept[0].first_page == 2
    assert plan.missing == [9]
    chapter = "One" if job.deck.text == DECK else "Fragment"
    assert plan.kept[0].call.chapter.title == chapter
    assert partial_compile.frames_for_slides(job, ["1bb", "1cc"]) == [2, 3]
    assert partial_compile.frames_for_slides(job, ["1cc", "1bb"]) == [2, 3]
    assert partial_compile.frames_for_slides(job, ["1AA"]) == [1]
    assert partial_compile.frames_for_slides(job, ["1zz"]) == []     # not in that PDF
    assert partial_compile.plan(job, partial_compile.frames_for_slides(job, ["1bb"])).kept[0].call.id == "1bb"
    text = partial_compile.wrapper_text(plan)
    assert f"\\section{{{chapter}}}" in text
    assert "\\setcounter{framenumber}{1}\\setcounter{page}{2}%\n\\slide{1bb-EN-B}" in text
    assert "1aa-EN-A" not in text and "1cc-EN-C" not in text
    assert "{fragment}" not in text
    assert text.rstrip().endswith("\\end{document}")
    plan = partial_compile.plan(job, [3])
    assert plan.kept[0].call.id == "1cc" and plan.kept[0].first_page == 4
    text = partial_compile.wrapper_text(plan)
    assert "\\setcounter{framenumber}{2}\\setcounter{page}{4}%\n\\slide{1cc-EN-C}" in text
    assert "1aa-EN-A" not in text and "1bb-EN-B" not in text


@pytest.mark.parametrize("deck_on_record", [None, "input", "include"], indirect=True,
                         ids=["inline", "input", "include"])
def test_deck_changes_after_the_asked_for_slides_are_fine(deck_on_record):
    root, job, _pdf = deck_on_record
    original = job.deck.text
    set_deck(root, original.replace("\\slide{1cc-EN-C}\n", "\\slide{1cc-EN-C}\n\\slide{1dd-EN-D}\n"))
    assert [k.call.id for k in partial_compile.plan(job, "2").kept] == ["1bb"]
    if original == DECK:
        set_deck(root, original.replace("\\slide{1aa-EN-A}\n", "\\slide{1aa-EN-A}\n\\slide{1zz-EN-Z}\n"))
        with pytest.raises(PartialError, match="changed before or at page 2"):
            partial_compile.plan(job, "2")
    else:
        set_deck(root, original.replace("\\slide{1cc-EN-C}\n", "\\slide{1zz-EN-Z}\n\\slide{1cc-EN-C}\n"))
        with pytest.raises(PartialError, match="changed before or at page 3"):
            partial_compile.plan(job, "3")


@pytest.mark.parametrize("deck_on_record", ["input", "include"], indirect=True)
def test_frames_for_slides_finds_a_fragment_translation(deck_on_record, monkeypatch):
    from slidemage import slide_language

    root, job, _pdf = deck_on_record
    monkeypatch.setattr(slide_language, "SLIDES_DIR", root / "slides")
    (root / "slides" / "1dd-DE-B-current.tex").write_text(
        "%% Translation of: 1bb-EN-B\nText\n", encoding="utf-8")
    assert partial_compile.frames_for_slides(job, ["1dd"]) == [2]


def test_plan_lists_other_changed_slides(deck_on_record):
    root, job, _pdf = deck_on_record
    (root / "slides" / "1cc-EN-C-current.tex").write_text("edited\n", encoding="utf-8")
    (root / "slides" / "1bb-EN-B-current.tex").write_text("edited too\n", encoding="utf-8")
    assert partial_compile.plan(job, "2").other_changed == ["1cc"]


def set_deck(root: Path, text: str) -> None:
    (root / "decks" / "t-D.tex").write_text(text, encoding="utf-8", newline="")


def test_no_deck_copy_on_record_means_any_change_counts(deck_on_record):
    root, job, _pdf = deck_on_record
    (root / ".build" / "compile-records" / "t-D" / "deck.tex").unlink()
    set_deck(root, DECK + "% a comment at the end\n")
    with pytest.raises(PartialError, match="changed in its preamble"):
        partial_compile.plan(job, "2")


@pytest.mark.parametrize("change, message", [
    (lambda root, pdf: set_deck(root, DECK.replace("\\begin{document}", "% x\n\\begin{document}")),
     "t-D.tex changed in its preamble"),
    (lambda root, pdf: pdf.write_bytes(pdf.read_bytes() + b"\n%x"), "t-D.pdf was changed"),
    (lambda root, pdf: (root / ".build" / "compile-records" / "t-D.json").unlink(),
     "has no whole-deck compile on record"),
])
def test_plan_refuses_when_the_whole_deck_is_needed(deck_on_record, change, message):
    root, job, pdf = deck_on_record
    change(root, pdf)
    with pytest.raises(PartialError, match=message):
        partial_compile.plan(job, "2")
    if "no whole-deck compile" in message:
        with pytest.raises(PartialError, match="compile the whole deck once"):
            partial_compile.frames_for_slides(job, ["1bb"])


def output_for(tmp_path, pages, links=None):
    pdf = make_pdf(tmp_path / "part" / "t-D.pdf", pages, links)
    return partial_compile.PartialOutput(pdf, tmp_path / "part", partial_compile.page_infos(pdf))


def test_patch_swaps_the_pages_in_and_keeps_the_rest(deck_on_record, tmp_path):
    root, job, pdf = deck_on_record
    (root / "slides" / "1bb-EN-B-current.tex").write_text("edited\n", encoding="utf-8")
    assert partial_compile.plan(job, "3").other_changed == ["1bb"]
    plan = partial_compile.plan(job, "2")
    uri = {"kind": fitz.LINK_URI, "from": fitz.Rect(10, 10, 60, 30), "uri": "https://x.org"}
    goto = {"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 50, 60, 70), "page": 1}
    output = output_for(tmp_path, [("B new step 1", "1bb", 2), ("B new step 2", "1bb", 2)],
                        {0: [uri, goto]})
    result = partial_compile.patch(plan, output, print)
    assert result.replaced == [2] and result.mismatched == []
    with fitz.open(pdf) as doc:
        texts = [page.get_text() for page in doc]
        assert len(texts) == 4
        assert "A text" in texts[0] and "C text" in texts[3]
        assert "B new step 1" in texts[1] and "B old" not in texts[1]
        assert "B new step 2" in texts[2]
        links = doc[1].get_links()
    assert {link["kind"] for link in links} == {fitz.LINK_URI, fitz.LINK_GOTO}
    # the in-PDF link to the slide's second page now points at its full-deck page
    assert next(link for link in links if link["kind"] == fitz.LINK_GOTO)["page"] == 2
    # the record vouches for the patched PDF, so another page compile can follow
    assert partial_compile.plan(job, "3").kept[0].call.id == "1cc"
    assert partial_compile.plan(job, "3").other_changed == []


def test_slide_with_a_new_page_count_is_not_swapped(deck_on_record, tmp_path):
    _root, job, pdf = deck_on_record
    plan = partial_compile.plan(job, "2")
    before = pdf.read_bytes()
    output = output_for(tmp_path, [("B 1", "1bb", 2), ("B 2", "1bb", 2), ("B 3", "1bb", 2)])
    result = partial_compile.patch(plan, output, print)
    assert result.replaced == [] and result.mismatched == [2]
    assert pdf.read_bytes() == before
    with fitz.open(result.separate_pdf) as doc:
        assert doc.page_count == 3


def test_progress_bar_stops_after_a_page_compile():
    """A page compile logs no "MOVING" line, only PASS (v5.35.1: the busy bar
    kept running after it)."""
    from slidemage import compile_progress

    progress = compile_progress.BatchProgress()
    job = compiler.CompileJob(deck_scan.Deck(
        name="t-D", path=Path("t-D.tex"), archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=None, chapters=[], output_folders={}),
        "instructor", None, pages=[4])
    progress.reset({job.jobname: compile_progress.spec_for_job(job)})
    progress.feed("==== Compiling t-D -> t-D-instructor ====")
    progress.feed("Run number 1 of rule 'lualatex'")
    assert progress.active and progress.fraction is None          # busy bar
    update = progress.feed("==== PASS: t-D-instructor -> pdf/t-D-instructor.pdf ====")
    assert not progress.active and update[2] is True              # batch finished
