"""compile_records: what a compile read, so a deck snapshot can reuse a
version's PDF when nothing it read has changed since."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from slidemage import compile_records, compiler, deck_scan
from slidemage.compile_records import fresh_output, write_record

WRAPPER = "\\def\\deckversionoverride{instructor}\n\\input{t-Deck.tex}\n"


def write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="")
    return path


@pytest.fixture
def compiled(tmp_path, monkeypatch):
    """A finished compile: project files, an invocation dir with .fls/.log/
    .blg/.timestamp, and the PDF published to pdf/."""
    monkeypatch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.22.0")
    root = tmp_path / "Proj"
    deck = write(root / "decks" / "t-Deck.tex", "deck\n")
    slide = write(root / "slides" / "1aa-EN-One-current.tex", "slide\n")
    image = write(root / "media" / "a.png", b"png")
    bib = write(root / "Slidemaster.bib", "@book{x}\n")
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
    write(inv / "t-Deck-instructor.blg", f"INFO - Found BibTeX data source '{bib}'\n")
    write(inv / "t-Deck-instructor.timestamp", "\\gdef\\SMCompileTimestampValue{2026-10-08 09:00}\n")
    write(inv / "t-Deck-instructor.aux", "aux")
    pdf = write(root / "pdf" / "t-Deck-instructor.pdf", b"%PDF instructor")
    started = time.time() + 1          # every file above is older than the compile
    return dict(root=root, build=build, inv=inv, wrapper=wrapper, pdf=pdf, started=started,
                deck=deck, slide=slide, image=image, bib=bib)


def record(c, wrapper_text=WRAPPER, log=None):
    return write_record(c["build"], "t-Deck-instructor", c["inv"], c["wrapper"], wrapper_text,
                        c["pdf"], c["started"], log)


def test_a_recorded_compile_is_fresh_until_something_changes(compiled):
    c = compiled
    assert record(c) == c["build"] / "compile-records" / "t-Deck-instructor.json"
    fresh, why = fresh_output(c["build"], "t-Deck-instructor", WRAPPER)
    assert why == ""
    assert fresh.pdf == c["pdf"]
    assert sorted(p.name for p in fresh.inputs) == [
        "1aa-EN-One-current.tex", "Slidemaster.bib", "a.png", "t-Deck.tex"]
    assert fresh.bib_sources == [Path(os.path.normpath(c["bib"]))]
    assert "SMCompileTimestampValue{2026-10-08 09:00}" in fresh.timestamp
    assert "Package: beamer 2026/01/22 v3.77" in fresh.log_text
    assert fresh.started == int(c["started"])
    data = json.loads((c["build"] / "compile-records" / "t-Deck-instructor.json").read_text())
    names = [Path(e["path"]).name for e in data["inputs"]]
    assert "fira.luc" not in names and "t-Deck-instructor.aux" not in names
    assert not any(n.startswith("_slidemage_") for n in names)

    write(c["slide"], "slide, edited\n")
    fresh, why = fresh_output(c["build"], "t-Deck-instructor", WRAPPER)
    assert fresh is None and why == "1aa-EN-One-current.tex changed"


@pytest.mark.parametrize("change, reason", [
    (lambda c: write(c["pdf"], b"%PDF other"), "t-Deck-instructor.pdf was replaced"),
    (lambda c: c["pdf"].unlink(), "t-Deck-instructor.pdf is gone"),
    (lambda c: c["image"].unlink(), "a.png is gone"),
    (lambda c: write(c["bib"], "@book{y}\n"), "Slidemaster.bib changed"),
])
def test_stale_when_pdf_or_input_changes(compiled, change, reason):
    record(compiled)
    change(compiled)
    assert fresh_output(compiled["build"], "t-Deck-instructor", WRAPPER) == (None, reason)


def test_stale_when_settings_or_engine_change(compiled, monkeypatch):
    record(compiled)
    other = WRAPPER.replace("instructor", "instructor}\\def\\SMFooterTimestampOverride{0")
    assert fresh_output(compiled["build"], "t-Deck-instructor", other) == (
        None, "the deck's version settings changed")
    monkeypatch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.23.0")
    assert fresh_output(compiled["build"], "t-Deck-instructor", WRAPPER) == (
        None, "the TeX engine changed")


def test_no_record_no_reuse(compiled):
    assert fresh_output(compiled["build"], "t-Deck-instructor", WRAPPER) == (
        None, "no compile on record")


def test_file_changed_during_the_compile_is_not_recorded(compiled):
    c = compiled
    record(c)
    c["started"] = time.time() - 60      # the slide was saved while compiling
    logged: list[str] = []
    assert record(c, log=logged.append) is None
    assert any("changed during it" in line for line in logged)
    # ... and the older record can't vouch for the new PDF either
    assert fresh_output(c["build"], "t-Deck-instructor", WRAPPER)[0] is None


def test_slide_previews_are_kept_not_compared(compiled):
    """The generated appendix's thumbnails (.previews/) are refreshed after
    every instructor compile; the record keeps the ones the compile read."""
    c = compiled
    preview = write(c["root"] / ".previews" / "slide_previews" / "1aa-EN-SlideMage-304-171.png",
                    b"thumb v1")
    fls = c["inv"] / "t-Deck-instructor.fls"
    fls.write_text(fls.read_text() + f"INPUT {preview}\n", encoding="utf-8")
    record(c)
    write(preview, b"thumb v2, refreshed after the compile")
    fresh, why = fresh_output(c["build"], "t-Deck-instructor", WRAPPER)
    assert why == ""
    copy = fresh.copies[compile_records.norm(preview)]
    assert copy.read_bytes() == b"thumb v1"
    copy.unlink()
    assert fresh_output(c["build"], "t-Deck-instructor", WRAPPER)[1] == (
        "the kept copy of 1aa-EN-SlideMage-304-171.png is missing")


def test_unchanged_jobs_need_the_same_destination(compiled, monkeypatch):
    c = compiled
    monkeypatch.setattr(compiler, "BUILD_DIR", c["build"])
    deck = deck_scan.Deck(name="t-Deck", path=c["deck"], archived=False, text="deck\n",
                          supports_version=True, uses_biblatex=False, preamble_end=None,
                          chapters=[], output_folders={})
    job = compiler.CompileJob(deck, "instructor", None)
    wrapper_text = compiler.wrapper_text(job)
    write_record(c["build"], "t-Deck-instructor", c["inv"], c["wrapper"], wrapper_text,
                 c["pdf"], c["started"])
    assert [j.jobname for j, _ in compiler.unchanged_jobs([job], {"t-Deck-instructor": c["pdf"]})] \
        == ["t-Deck-instructor"]
    # published elsewhere now (a new \deckoutputfolder): not "unchanged"
    elsewhere = c["root"] / "out" / "t-Deck-instructor.pdf"
    assert compiler.unchanged_jobs([job], {"t-Deck-instructor": elsewhere}) == []
    write(c["slide"], "edited\n")
    assert compiler.unchanged_jobs([job], {"t-Deck-instructor": c["pdf"]}) == []


def test_remove_temp_files_keeps_the_records(compiled, monkeypatch):
    c = compiled
    record(c)
    monkeypatch.setattr(compiler, "BUILD_DIR", c["build"])
    removable = {p.name for p in compiler.removable_build_entries()}
    assert "t-Deck-instructor-abc" in removable
    assert compile_records.RECORDS_DIRNAME not in removable


def test_failed_bibliography_is_not_recorded(compiled):
    c = compiled
    write(c["inv"] / "t-Deck-instructor.log", "Package biblatex Warning: Please (re)run Biber on the file:\n")
    assert record(c) is None


def test_compiler_records_a_published_whole_deck_compile(compiled, monkeypatch):
    """compiler._relocate_pdf_and_finish writes the record once the PDF is
    published (here a during-course job: no preview capture involved)."""
    c = compiled
    monkeypatch.setattr(compiler, "BUILD_DIR", c["build"])
    write(c["inv"] / "t-Deck-during-course.pdf", b"%PDF during")
    for ext in (".fls", ".log", ".blg", ".timestamp"):
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
        c["inv"] / "t-Deck-during-course.pdf", dest, "t-Deck-during-course", job, print,
        build_dir=c["inv"], destination_key=key, generation=generation,
        record=(c["wrapper"], WRAPPER, c["started"]))
    fresh, why = fresh_output(c["build"], "t-Deck-during-course", WRAPPER)
    assert why == "" and fresh.pdf == dest and dest.read_bytes() == b"%PDF during"
