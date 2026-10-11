""""Open pdf": the instructor PDF, unless a newer PDF of the deck comes from
another compile run (2026-10-08, direct instructions). Every PDF of one click
on Create PDF carries the same /SlideMageRun in its info dictionary."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QWidget

from slidemage import compile_records, compiler, deck_scan
from slidemage.ui.workspace import deck_actions
from slidemage.compiler import DeckPdf, pdf_to_open

NOW = time.time()
RUN = "2026-10-08T08:20:01"


def pdf(label, age_minutes, run_id=RUN, preferred=False):
    return DeckPdf(label, Path(f"{label}.pdf"), NOW - age_minutes * 60, preferred, run_id)


def test_instructor_when_newer_pdfs_come_from_the_same_run():
    instructor = pdf("Instructor", 90, preferred=True)
    # presenter compiled first in the same run, the others after the instructor PDF
    pdfs = [pdf("During-course", 0), pdf("After-course", 30), instructor, pdf("Presenter", 120)]
    assert pdf_to_open(pdfs) is instructor


def test_ask_when_a_newer_pdf_comes_from_another_run():
    pdfs = [pdf("After-course", 1, run_id="2026-10-08T09:00:00"),
            pdf("Instructor", 2, preferred=True)]
    assert pdf_to_open(pdfs) is None


def test_ask_when_a_newer_pdf_has_no_run_older_ones_dont_matter():
    assert pdf_to_open([pdf("After-course", 1, run_id=None),
                        pdf("Instructor", 2, preferred=True)]) is None
    instructor = pdf("Instructor", 2, preferred=True)
    assert pdf_to_open([instructor, pdf("Presenter", 500, run_id=None)]) is instructor


def test_only_one_pdf_opens_directly_no_instructor_asks():
    only = pdf("After-course", 3)
    assert pdf_to_open([only]) is only
    assert pdf_to_open([pdf("After-course", 0), pdf("Presenter", 1)]) is None


def test_run_id_line_is_left_out_of_the_record_hash():
    base = "\\def\\deckversionoverride{instructor}\n\\input{t-A.tex}\n"
    stamped = ("\\def\\deckversionoverride{instructor}\n" + compile_records.run_id_line(RUN)
               + "\n\\input{t-A.tex}\n")
    assert compile_records.run_id_line(RUN) == "\\pdfextension info{/SlideMageRun (" + RUN + ")}"
    assert compile_records.wrapper_sha256(stamped) == compile_records.wrapper_sha256(base)
    assert compile_records.wrapper_sha256(stamped) != compile_records.wrapper_sha256(
        base.replace("instructor", "after-course"))


def test_run_id_read_and_stamped(tmp_path):
    path = tmp_path / "a.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    assert compile_records.read_run_id(path) is None
    with fitz.open(path) as doc:
        compile_records.stamp_run_id(doc, RUN)
        doc.save(tmp_path / "b.pdf")
    assert compile_records.read_run_id(tmp_path / "b.pdf") == RUN


def test_compile_job_stamps_its_run(tmp_path):
    deck = deck_scan.Deck(name="t-A", path=tmp_path / "t-A.tex", archived=False, text="",
                          supports_version=True, uses_biblatex=False, preamble_end=None,
                          chapters=[], output_folders={})
    job = compiler.CompileJob(deck, "instructor", None, run_id=RUN)
    assert compile_records.run_id_line(RUN) in compiler.wrapper_text(job)
    assert "SlideMageRun" not in compiler.wrapper_text(compiler.CompileJob(deck, "instructor", None))


@pytest.fixture
def deck_with_pdfs(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "PDF_DIR", tmp_path / "pdf")
    monkeypatch.setattr(compiler, "PROJECT_ROOT", tmp_path)
    (tmp_path / "decks").mkdir()
    (tmp_path / "decks" / "t-A.tex").write_text(
        "\\documentclass{beamer}\n\\deckversionoverride\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8")
    deck = deck_scan.scan_dir(tmp_path / "decks", False)[0]
    (tmp_path / "pdf").mkdir()
    for name, age_minutes, run_id in (("t-A-instructor", 30, RUN),
                                      ("t-A-after-course", 0, "2026-10-08T09:00:00")):
        path = tmp_path / "pdf" / f"{name}.pdf"
        doc = fitz.open()
        doc.new_page()
        compile_records.stamp_run_id(doc, run_id)
        doc.save(path)
        doc.close()
        os.utime(path, (NOW - age_minutes * 60,) * 2)
    return deck


def test_deck_pdfs_newest_first_with_labels_and_runs(deck_with_pdfs):
    pdfs = compiler.deck_pdfs(deck_with_pdfs)
    assert [(p.label, p.preferred, p.run_id) for p in pdfs] == [
        ("After-course", False, "2026-10-08T09:00:00"), ("Instructor", True, RUN)]


def test_open_pdf_asks_and_opens_the_choice(deck_with_pdfs, monkeypatch):
    QApplication.instance() or QApplication([])
    asked = {}

    def get_item(parent, title, text, items, current, editable):
        asked.update(items=items, current=current)
        return items[1], True

    monkeypatch.setattr(QInputDialog, "getItem", get_item)
    opened: list[Path] = []
    monkeypatch.setattr(deck_actions.open_path, "open_in_default_app", opened.append)
    win = QWidget()
    win._log = lambda line: None
    deck_actions.DeckActionsMixin._on_open_latest_pdf(win, deck_with_pdfs)
    assert asked["items"][0].startswith("After-course -- ")
    assert asked["current"] == 1                          # the instructor PDF preselected
    assert opened == [compiler.PDF_DIR / "t-A-instructor.pdf"]


def test_deck_setting_chooses_the_preferred_pdf(deck_with_pdfs):
    deck_with_pdfs.open_pdf = "after-course"
    pdfs = compiler.deck_pdfs(deck_with_pdfs)
    assert [(p.label, p.preferred) for p in pdfs] == [("After-course", True), ("Instructor", False)]
    # the after-course PDF is the newest: opened without asking
    assert pdf_to_open(pdfs).label == "After-course"


def test_open_pdf_setting_round_trip():
    from slidemage import deck_settings, deck_scan as scan

    text = "\\documentclass{beamer}\r\n\\input{Slidemaster_preamble_uni-graz}\r\n\\begin{document}\r\n"
    text2 = deck_settings.set_open_pdf(text, "during-course")
    assert "%% SlideMage open PDF: during-course\r\n\\begin{document}" in text2
    assert scan.parse_open_pdf(text2) == "during-course"
    assert deck_settings.read_settings(text2).open_pdf == "during-course"
    assert deck_settings.set_open_pdf(text2, "instructor") == text
    assert deck_settings.read_settings(text).open_pdf == "instructor"
