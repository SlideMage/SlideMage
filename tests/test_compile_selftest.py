# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`slidemage --self-test --compile` (compile_selftest.py): its decks, its exit codes, and one real run."""
import os
import re
import shutil
from pathlib import Path

import pytest

from slidemage import cli, compile_selftest

REPO = Path(__file__).resolve().parents[1]


def test_one_deck_per_bundled_layout_and_template():
    layouts = {p.stem.removeprefix("SlideMage_layout_") for p in (REPO / "latex").glob("SlideMage_layout_*.tex")}
    templates = {p.stem.removeprefix("SlideMage_template_") for p in (REPO / "latex").glob("SlideMage_template_*.tex")}
    covered_templates = {template for _name, template, _layout, _font in compile_selftest.DECKS}
    covered_layouts = {layout or "fira" for _name, template, layout, _font in compile_selftest.DECKS if template == "slidemage"}
    assert covered_templates == templates
    assert covered_layouts == layouts


def test_deck_sets_the_layout_before_the_template_and_cites():
    text = compile_selftest.deck_text("slidemage", "lmsans")
    assert text.index(r"\newcommand{\SMLayoutProfile}{lmsans}") < text.index(r"\input{SlideMage_template_slidemage}")
    assert r"\parencite{" + compile_selftest.CITATION_KEY + "}" in text and r"\printbibliography" in text
    assert "SMLayoutProfile" not in compile_selftest.deck_text("grayscale", None)


def test_the_citation_key_is_in_the_example_bibliography():
    bib = (REPO / "example" / "SlideMage.bib").read_text(encoding="utf-8")
    assert re.search(r"@\w+\{" + compile_selftest.CITATION_KEY + ",", bib)
    assert compile_selftest.CITATION_AUTHOR in bib


def test_no_latexmk_exits_2_without_compiling(monkeypatch, capsys):
    monkeypatch.setattr(compile_selftest.shutil, "which", lambda name: None)
    monkeypatch.setattr("slidemage.tex_paths.extend_path", lambda: [])
    assert compile_selftest.run() == compile_selftest.EXIT_TEX_MISSING
    assert "latexmk was not found" in capsys.readouterr().out


def test_cli_dispatches_with_its_options(monkeypatch):
    calls = []
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))     # cli.main extends PATH; restored after the test
    monkeypatch.setattr(compile_selftest, "run", lambda verbose=False, keep=False: calls.append((verbose, keep)) or 0)
    with pytest.raises(SystemExit) as stop:
        cli.main([cli.SELF_TEST_FLAG, cli.COMPILE_FLAG, "-v"])
    assert stop.value.code == 0 and calls == [(True, False)]


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")
def test_real_run_compiles_every_deck(capsys):
    assert compile_selftest.run() == 0, capsys.readouterr().out
