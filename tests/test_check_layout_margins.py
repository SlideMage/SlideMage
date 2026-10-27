# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/check_layout.py takes the Top and Left Margin from the PDF's info dictionary (no TeX involved)."""
import importlib.util
from pathlib import Path

import pymupdf

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_layout.py"
spec = importlib.util.spec_from_file_location("check_layout", TOOL)
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)


def pdf(tmp_path, **info):
    """A one-page PDF whose info dictionary holds `info` as PDF strings, as SlideMage_base.tex writes them."""
    doc = pymupdf.open()
    doc.new_page(width=455.24, height=256.07)
    doc.set_metadata({"title": "probe"})
    kind, ref = doc.xref_get_key(-1, "Info")
    for key, value in info.items():
        doc.xref_set_key(int(ref.split()[0]), key, f"({value})")
    path = tmp_path / "probe.pdf"
    doc.save(path)
    return pymupdf.open(path)


def test_margins_come_from_the_pdf(tmp_path):
    doc = pdf(tmp_path, SMTopMargin="50.5", SMLeftMargin="20.25")
    assert cl.pdf_margins(doc) == (50.5, 20.25)
    page = cl.Page(doc[0], *cl.pdf_margins(doc))
    assert (page.top_margin, page.left_margin) == (50.5, 20.25)


def test_a_pdf_without_the_keys_falls_back_to_the_slidemage_template(tmp_path):
    assert cl.pdf_margins(pdf(tmp_path)) == (cl.TOP_MARGIN, cl.LEFT_MARGIN)
    assert cl.pdf_margins(pdf(tmp_path, SMTopMargin="45")) == (45.0, cl.LEFT_MARGIN)
    assert cl.pdf_margins(pdf(tmp_path, SMLeftMargin="not a number")) == (cl.TOP_MARGIN, cl.LEFT_MARGIN)
