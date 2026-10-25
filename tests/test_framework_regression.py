# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The comparison logic of tools/framework_regression.py (no TeX involved)."""
import importlib.util
import json
from pathlib import Path

import pymupdf
import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "framework_regression.py"
spec = importlib.util.spec_from_file_location("framework_regression", TOOL)
fr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fr)


def record(pages, fonts=("Fira (Type1)",), ok=True):
    return {"ok": ok, "pages": list(pages), "fonts": list(fonts)}


def test_identical_records_have_no_differences():
    assert fr.compare_entry(record("abc"), record("abc")) == []


def test_changed_page_is_named():
    problems = fr.compare_entry(record(["a", "b", "c"]), record(["a", "x", "y"]))
    assert problems == ["pages differ: 2, 3"]


def test_page_count_and_fonts_are_reported():
    problems = fr.compare_entry(record(["a", "b"]), record(["a"], fonts=["Other (Type1)"]))
    assert "page count 2 -> 1" in problems
    assert any(p.startswith("fonts changed") and "Fira" in p and "Other" in p for p in problems)


def test_compile_failure_is_a_difference_but_failed_both_times_is_not():
    assert fr.compare_entry(record("a"), {"ok": False}) == ["compile ok: True -> False"]
    assert fr.compare_entry({"ok": False}, {"ok": False}) == []


def make_pdf(path: Path, text: str, font="helv") -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontname=font)
    doc.save(path)


def test_describe_pdf_ignores_metadata_but_sees_content(tmp_path):
    make_pdf(tmp_path / "a.pdf", "hello")
    make_pdf(tmp_path / "b.pdf", "hello")
    make_pdf(tmp_path / "c.pdf", "hellp")
    a, b, c = (fr.describe_pdf(tmp_path / f"{n}.pdf", 72) for n in "abc")
    assert a == b
    assert fr.compare_entry(dict(a, ok=True), dict(c, ok=True)) == ["pages differ: 1"]


def test_diff_image_is_written_for_differing_pages(tmp_path):
    make_pdf(tmp_path / "a.pdf", "hello")
    make_pdf(tmp_path / "c.pdf", "hellp")
    fr.write_diff_images(tmp_path / "a.pdf", tmp_path / "c.pdf", [1], tmp_path / "diff", 72)
    assert (tmp_path / "diff" / "p1.png").stat().st_size > 0


def test_font_names_lose_their_subset_tag():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "x")
    assert all("+" not in name for name in fr.font_list(doc))
    assert fr.SUBSET_TAG_RE.sub("", "ABCDEF+FiraSans-Light") == "FiraSans-Light"


def test_template_swap_edits_only_the_wrapper_text(tmp_path):
    deck = tmp_path / "deck.tex"
    original = r"\documentclass{beamer}" "\n" r"\input{SlideMage_template_slidemage}" "\n" r"\begin{document}\end{document}" "\n"
    deck.write_text(original, encoding="utf-8")
    entry = fr.Entry(deck, "uni-graz", "instructor")
    swapped = fr.swapped_deck_text(entry)
    assert "SlideMage_template_uni-graz" in swapped and "slidemage}" not in swapped
    assert deck.read_text(encoding="utf-8") == original
    assert entry.key == "deck@uni-graz-instructor"
    assert fr.wrapper_text(entry, swapped).startswith(r"\def\deckversionoverride{instructor}")


def test_template_swap_without_template_input_is_an_error(tmp_path):
    deck = tmp_path / "deck.tex"
    deck.write_text(r"\documentclass{beamer}" "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fr.swapped_deck_text(fr.Entry(deck, "mci", "instructor"))


def test_config_paths_and_entries(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps(
        {"project": "p", "framework": "f", "decks": [{"deck": "decks/a.tex"}, {"deck": "decks/b.tex", "template": "mci"}]}))
    cfg = fr.load_config(tmp_path / "c.json")
    entries = fr.entries_of(cfg, cfg["project"], None)
    assert [e.key for e in entries] == [f"{n}-{v}" for n in ("a", "b@mci") for v in fr.DEFAULT_VERSIONS]
    assert [e.group for e in fr.entries_of(cfg, cfg["project"], {"b@mci"})] == ["b@mci"] * 3
    assert {e.group for e in fr.entries_of(cfg, cfg["project"], {"a"})} == {"a"}
