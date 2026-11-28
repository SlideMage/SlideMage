# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""PDF selection by deck preference and compile run."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pymupdf as fitz
import pytest
from PySide6.QtWidgets import QInputDialog, QWidget

from slidemage import compile_records, compiler, deck_scan
from slidemage.ui.workspace import deck_actions
from slidemage.compiler import DeckPdf, pdf_to_open
from conftest import EXAMPLE_PROJECT

NOW = time.time()
RUN = "2026-10-08T08:20:01"


def pdf(label, age_minutes, run_id=RUN, preferred=False):
    return DeckPdf(label, Path(f"{label}.pdf"), NOW - age_minutes * 60, preferred, run_id)


@pytest.mark.parametrize("pdfs, chosen", [
    ([pdf("During-course", 0), pdf("After-course", 30), pdf("Instructor", 90, preferred=True),
      pdf("Presenter", 120)], 2),
    ([pdf("After-course", 1, run_id="2026-10-08T09:00:00"), pdf("Instructor", 2, preferred=True)], None),
    ([pdf("After-course", 1, run_id=None), pdf("Instructor", 2, preferred=True)], None),
    ([pdf("Instructor", 2, preferred=True), pdf("Presenter", 500, run_id=None)], 0),
    ([pdf("After-course", 3)], 0),
    ([pdf("After-course", 0), pdf("Presenter", 1)], None),
], ids=["same-run", "different-run", "newer-legacy", "older-legacy", "only-pdf", "no-preferred"])
def test_pdf_choice(pdfs, chosen):
    assert pdf_to_open(pdfs) is (None if chosen is None else pdfs[chosen])


def test_run_id_read_and_stamped(tmp_path):
    path = tmp_path / "a.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    assert compile_records.read_run_id(path) is None
    with fitz.open(path) as doc:
        compile_records.stamp_run_id(doc, RUN)
        doc.save(tmp_path / "b.pdf")
    assert compile_records.read_run_id(tmp_path / "b.pdf") == RUN


def test_compile_job_stamps_its_run_without_changing_the_wrapper_hash(tmp_path):
    deck = deck_scan.Deck(name="t-A", path=tmp_path / "t-A.tex", archived=False, text="",
                          supports_version=True, uses_biblatex=False, preamble_end=None,
                          chapters=[], output_folders={})
    job = compiler.CompileJob(deck, "instructor", None, run_id=RUN)
    stamped = compiler.wrapper_text(EXAMPLE_PROJECT, job)
    job.run_id = None
    base = compiler.wrapper_text(EXAMPLE_PROJECT, job)
    assert compile_records.run_id_line(RUN) in stamped and "SlideMageRun" not in base
    assert f"\\pdfextension info{{/SlideMageRun ({RUN})}}" in stamped
    assert compile_records.wrapper_sha256(stamped) == compile_records.wrapper_sha256(base)
    assert compile_records.wrapper_sha256(stamped) != compile_records.wrapper_sha256(
        base.replace("instructor", "after-course"))


@pytest.fixture
def deck_with_pdfs(tmp_path):
    (tmp_path / "decks").mkdir()
    (tmp_path / "decks" / "t-A.tex").write_text(
        "\\documentclass{beamer}\n\\deckversionoverride\n\\begin{document}\n\\end{document}\n",
        encoding="utf-8")
    deck = deck_scan.scan_dir(tmp_path / "decks", False)[0]
    (tmp_path / "pdf").mkdir()
    for name, age_minutes, run_id in (("t-A-instructor", 30, RUN),
                                      ("t-A-after-course", 0, "2026-10-08T09:00:00")):
        path = tmp_path / "pdf" / f"{name}.pdf"
        with fitz.open() as doc:
            doc.new_page()
            compile_records.stamp_run_id(doc, run_id)
            doc.save(path)
        os.utime(path, (NOW - age_minutes * 60,) * 2)
    return deck


def test_deck_pdfs_are_ordered_and_flag_the_preferred_view(ctx, deck_with_pdfs):
    pdfs = compiler.deck_pdfs(ctx, deck_with_pdfs)
    assert [(p.label, p.preferred, p.run_id) for p in pdfs] == [
        ("After-course", False, "2026-10-08T09:00:00"), ("Instructor", True, RUN)]

    deck_with_pdfs.open_pdf = "after-course"
    pdfs = compiler.deck_pdfs(ctx, deck_with_pdfs)
    assert [(p.label, p.preferred) for p in pdfs] == [("After-course", True), ("Instructor", False)]
    # the after-course PDF is the newest: opened without asking
    assert pdf_to_open(pdfs).label == "After-course"


def test_open_pdf_asks_and_opens_the_choice(ctx, deck_with_pdfs, monkeypatch, qapp):
    asked = {}

    def get_item(parent, title, text, items, current, editable):
        asked.update(items=items, current=current)
        return items[1], True

    monkeypatch.setattr(QInputDialog, "getItem", get_item)
    opened: list[Path] = []
    monkeypatch.setattr(deck_actions.open_path, "open_in_default_app", opened.append)
    win = QWidget()
    win.log = lambda line: None
    win.project = ctx
    deck_actions.on_open_latest_pdf(win, deck_with_pdfs)
    assert asked["items"][0].startswith("After-course -- ")
    assert asked["current"] == 1                          # the instructor PDF preselected
    assert opened == [ctx.pdf_dir / "t-A-instructor.pdf"]


def test_open_pdf_setting_round_trip():
    from slidemage import deck_settings, deck_scan as scan

    text = "\\documentclass{beamer}\r\n\\input{SlideMage_template_acme}\r\n\\begin{document}\r\n"
    text2 = deck_settings.set_open_pdf(text, "during-course")
    assert "%% SlideMage open PDF: during-course\r\n\\begin{document}" in text2
    assert scan.parse_open_pdf(text2) == "during-course"
    assert deck_settings.read_settings(text2).open_pdf == "during-course"
    assert deck_settings.set_open_pdf(text2, "instructor") == text
    assert deck_settings.read_settings(text).open_pdf == "instructor"
