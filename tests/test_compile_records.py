# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile records capture inputs and reject stale snapshot PDFs."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from conftest import write_test_file as write

from slidemage import compile_records, compiler, deck_scan, render_evidence
from slidemage.compile_records import fresh_output, write_record
from slidemage.project import ProjectContext

JOB = "t-Deck-instructor"

WRAPPER = "\\def\\deckversionoverride{instructor}\n\\input{t-Deck.tex}\n"


@pytest.fixture
def compiled(tmp_path, monkeypatch):
    monkeypatch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.22.0")
    root = tmp_path / "Proj"
    deck = write(root / "decks" / "t-Deck.tex", "deck\n")
    slide = write(root / "slides" / "1aa-EN-One-current.tex", "slide\n")
    image = write(root / "media" / "a.png", b"png")
    bib = write(root / "SlideMage.bib", "@book{x}\n")
    cache = write(tmp_path / "MiKTeX" / "luatex-cache" / "fonts" / "fira.luc", b"cache")
    build = root / ".build"
    inv = build / "t-Deck-instructor-abc"
    wrapper = root / "decks" / "_slidemage_t-Deck-instructor_abc.tex"
    write(inv / "t-Deck-instructor.fls", "\n".join([
        f"PWD {root / 'decks'}",
        f"INPUT {wrapper}",
        "INPUT ./t-Deck.tex",
        "INPUT ../slides/1aa-EN-One-current.tex",
        "INPUT ../media/a.png",
        f"INPUT {cache}",
        f"INPUT {inv / 't-Deck-instructor.aux'}",
        "OUTPUT t-Deck-instructor.pdf",
    ]) + "\n")
    write(inv / "t-Deck-instructor.log", "LaTeX2e <2025-11-01>\nPackage: beamer 2026/01/22 v3.77 x\n")
    write(inv / f"{JOB}.blg", "INFO - Found BibTeX data source '../SlideMage.bib'\n")
    write(inv / "t-Deck-instructor.aux", "aux")
    pdf = write(root / "pdf" / "t-Deck-instructor.pdf", b"%PDF instructor")
    env = compiler.build_env(ProjectContext.at(root))
    inventory = render_evidence.search_inventory(root, env)
    configuration = render_evidence.digest(render_evidence.configuration_state(root, env))
    started = time.time() + 1
    return dict(root=root, build=build, inv=inv, wrapper=wrapper, pdf=pdf, started=started,
                deck=deck, slide=slide, image=image, bib=bib, inventory=inventory, configuration=configuration)


def record(c, *, wrapper=WRAPPER, **options):
    options.setdefault("deck_path", c["deck"])
    return write_record(ProjectContext(c["root"], c["build"]), JOB, c["inv"], c["wrapper"], wrapper,
                        c["pdf"], c["started"], c["inventory"], c["configuration"], **options)


def lookup(c, wrapper=WRAPPER):
    return fresh_output(c["build"], JOB, wrapper)


def test_a_compile_record_detects_changed_inputs_settings_and_engine(compiled, monkeypatch):
    c = compiled
    assert lookup(c) == (
        None, "no compile on record")
    assert record(c) == c["build"] / "compile-records" / "t-Deck-instructor.json"
    fresh, why = lookup(c)
    assert why == ""
    assert fresh.pdf == c["pdf"]
    assert sorted(p.name for p in fresh.inputs) == [
        "1aa-EN-One-current.tex", "SlideMage.bib", "a.png", "t-Deck.tex"]
    assert fresh.bib_sources == [c["bib"]]
    assert compile_records.parse_blg_sources(c["inv"] / f"{JOB}.blg") == [Path("../SlideMage.bib")]
    assert "Package: beamer 2026/01/22 v3.77" in fresh.log_text
    assert fresh.started == int(c["started"])
    removable = {p.name for p in compiler.removable_build_entries(ProjectContext.at(c["root"]))}
    assert c["inv"].name in removable and compile_records.RECORDS_DIRNAME not in removable

    assert lookup(c, WRAPPER.replace("instructor", "after-course")) == (None, "the deck's version settings changed")
    with monkeypatch.context() as patch:
        patch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.23.0")
        assert lookup(c) == (None, "the TeX engine changed")
    write(c["slide"], "slide, edited\n")
    assert lookup(c) == (None, "1aa-EN-One-current.tex changed")


def test_a_slide_changed_during_the_compile_is_recorded_as_changed_not_dropping_the_record(compiled):
    """Saving a slide during compilation used to discard the entire record."""
    c = compiled
    later = c["started"] + 5
    os.utime(c["slide"], (later, later))
    lines = []
    assert record(c, log=lines.append) is not None
    data = compile_records.read_record(c["build"], JOB)
    entries = {Path(e["path"]).name: e for e in data["inputs"]}
    assert entries["1aa-EN-One-current.tex"] == {"path": entries["1aa-EN-One-current.tex"]["path"], "sha256": None,
                                                 "changed_during_compile": True}
    assert entries["a.png"]["sha256"] == compile_records.sha256(c["image"])         # the others keep their hashes
    assert any("changed during the compile: 1aa-EN-One-current.tex" in line for line in lines)
    fresh, why = lookup(c)
    assert fresh is None and why == "1aa-EN-One-current.tex changed"                # never reused for a snapshot


def test_the_deck_file_changed_during_the_compile_still_drops_the_record(compiled):
    c = compiled
    record(c)
    later = c["started"] + 5
    os.utime(c["deck"], (later, later))
    lines = []
    assert record(c, log=lines.append, deck_path=c["deck"]) is None
    assert compile_records.read_record(c["build"], JOB) is None     # the old record goes too
    assert any("t-Deck.tex changed during it" in line for line in lines)


def test_slide_previews_are_kept_not_compared(compiled):
    """The generated appendix's thumbnails (.build/appendix-thumbs/) are refreshed after
    every instructor compile; the record keeps the ones the compile read."""
    c = compiled
    preview = write(c["root"] / ".build" / "appendix-thumbs" / "slidemage" / "1aa-EN-SlideMage-304-171.png",
                    b"thumb v1")
    fls = c["inv"] / "t-Deck-instructor.fls"
    fls.write_text(fls.read_text() + f"INPUT {preview}\n", encoding="utf-8")
    record(c)
    write(preview, b"thumb v2, refreshed after the compile")
    fresh, why = lookup(c)
    assert why == ""
    copy = fresh.copies[compile_records.norm(preview)]
    assert copy.read_bytes() == b"thumb v1"
    copy.unlink()
    assert lookup(c)[1] == (
        "the kept copy of 1aa-EN-SlideMage-304-171.png is missing")


def test_unchanged_jobs_need_the_same_destination(compiled):
    c = compiled
    ctx = ProjectContext.at(c["build"].parent)
    deck = deck_scan.Deck(name="t-Deck", path=c["deck"], archived=False, text="deck\n",
                          supports_version=True, uses_biblatex=False, preamble_end=None,
                          chapters=[], output_folders={})
    job = compiler.CompileJob(deck, "instructor", None)
    wrapper_text = compiler.wrapper_text(ctx, job)
    record(c, wrapper=wrapper_text)
    assert [j.jobname for j, _ in compiler.unchanged_jobs(ctx, [job], {"t-Deck-instructor": c["pdf"]})] \
        == ["t-Deck-instructor"]
    # published elsewhere now (a new \deckoutputfolder): not "unchanged"
    elsewhere = c["root"] / "out" / "t-Deck-instructor.pdf"
    assert compiler.unchanged_jobs(ctx, [job], {"t-Deck-instructor": elsewhere}) == []
    write(c["slide"], "edited\n")
    assert compiler.unchanged_jobs(ctx, [job], {"t-Deck-instructor": c["pdf"]}) == []


def test_failed_bibliography_is_not_recorded(compiled):
    c = compiled
    write(c["inv"] / "t-Deck-instructor.log", "Package biblatex Warning: Please (re)run Biber on the file:\n")
    assert record(c) is None


def test_compiler_records_a_published_whole_deck_compile(compiled):
    """compiler._relocate_pdf_and_finish writes the record once the PDF is
    published (here a during-course job: no preview capture involved)."""
    c = compiled
    ctx = ProjectContext.at(c["build"].parent)
    write(c["inv"] / "t-Deck-during-course.pdf", b"%PDF during")
    for ext in (".fls", ".log", ".blg"):
        src = c["inv"] / f"t-Deck-instructor{ext}"
        write(c["inv"] / f"t-Deck-during-course{ext}", src.read_bytes())
    deck = deck_scan.Deck(name="t-Deck", path=c["deck"], archived=False, text="deck\n",
                          supports_version=True, uses_biblatex=False, preamble_end=None,
                          chapters=[], output_folders={})
    job = compiler.CompileJob(deck, "during-course", None)
    dest = c["root"] / "pdf" / "t-Deck-during-course.pdf"
    key, generation = compiler._register_output(dest)
    assert compiler._mark_output_success(key, generation)
    compiler.set_build_dir_active(c["inv"], True)
    compiler._relocate_pdf_and_finish(
        ctx, c["inv"] / "t-Deck-during-course.pdf", dest, "t-Deck-during-course", job, print,
        build_dir=c["inv"], destination_key=key, generation=generation,
        record=(c["wrapper"], WRAPPER, c["started"], c["inventory"], c["configuration"]))
    fresh, why = fresh_output(c["build"], "t-Deck-during-course", WRAPPER)
    assert why == "" and fresh.pdf == dest and dest.read_bytes() == b"%PDF during"


def test_a_relative_bib_name_in_the_blg_is_read_from_the_folder_latexmk_ran_in(tmp_path):
    blg = tmp_path / "t.blg"
    blg.write_text("INFO - Found BibTeX data source '../SlideMage.bib'\n", encoding="utf-8")
    decks = tmp_path / "proj" / "decks"
    assert compile_records.parse_blg_sources(blg, decks) == [tmp_path / "proj" / "SlideMage.bib"]
    assert compile_records.parse_blg_sources(blg) == [Path("../SlideMage.bib")]
