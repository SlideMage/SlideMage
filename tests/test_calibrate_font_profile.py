# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/calibrate_font_profile.py (v9.6.0): reads a profile's numbers, compares them with a measurement of the
calibration deck's PDF. The pure parts are tested here; the compile-and-measure run is opt-in (needs LuaLaTeX:
SLIDEMAGE_TEX_TESTS=1), like the other tests that compile."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "fixtures" / "template_stress"
BS = chr(92)


def load(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # a dataclass looks its module up
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


cal = load("calibrate_font_profile")


def test_a_profiles_lengths_are_read_in_pt():
    text = (BS + "newlength{" + BS + "SMA}" + BS + "setlength{" + BS + "SMA}{4.6pt}\n"
            + BS + "setlength{" + BS + "SMB}{-0.49pt}\n" + BS + "setlength{" + BS + "SMC}{10bp}\n"
            + BS + "setlength{" + BS + "SMD}{2.2ex}\n")
    assert cal.tex_length(text, "SMA") == 4.6
    assert cal.tex_length(text, "SMB") == -0.49
    assert cal.tex_length(text, "SMC") == pytest.approx(10 * 72.27 / 72)
    assert cal.tex_length(text, "SMD") is None and cal.tex_length(text, "SMZ") is None


def test_the_shipped_profiles_numbers_are_all_readable():
    for profile in ("fira", "lmsans"):
        text = cal.profile_text(ROOT / "latex", profile)
        for name in ("SMFooterTextDrop", "SMContentTopShift",
                     "SMColumnsTopCorrection", "SMColumnsTTopCompensation", "SMSectionframeHeightCorrection",
                     "SMLabelItemWidth", "SMLabelItemSep", "SMEnumerateNestedMinNumber",
                     "SMEnumerateNestedLeftMargin"):
            assert cal.tex_length(text, name) is not None, (profile, name)


def test_a_row_is_ok_within_the_tolerance_and_an_advisory_one_never_fails():
    assert cal.Row("SMA", 4.6, 4.8, "").ok and cal.Row("SMA", 4.6, 4.6 + cal.TOLERANCE, "").ok
    assert not cal.Row("SMA", 4.6, 5.0, "").ok
    assert cal.Row("SMA", 4.6, None, "").ok and cal.Row("SMA", None, 5.0, "").ok
    assert cal.Row("SMA", 4.6, 9.0, "", advisory=True).ok


def test_the_template_input_of_a_deck_is_swapped_for_a_template_under_a_profile():
    deck = (STRESS / "decks" / "calibration.tex").read_text(encoding="utf-8")
    assert len(cal.TEMPLATE_INPUT_RE.findall(deck)) == 1
    swapped, n = cal.TEMPLATE_INPUT_RE.subn(lambda m: "X", deck, count=1)
    assert n == 1 and "SlideMage_template_stress-test" not in swapped


def test_the_calibration_deck_has_a_slide_for_each_measurement():
    slides = {p.name.split("-")[0] for p in (STRESS / "slides").glob("*-current.tex")}
    deck = (STRESS / "decks" / "calibration.tex").read_text(encoding="utf-8")
    ids = (STRESS / "slide_ids.csv").read_text(encoding="utf-8")
    for slide_id in ("ZC2", "ZC3", "ZC4", "ZC5", "ZCI", "ZCJ", "ZCK", "ZCL"):
        assert slide_id in slides and f"slide{{{slide_id}-" in deck and f'"{slide_id}"' in ids
    # every frame type the framework has is on a slide of the deck
    text = "".join((STRESS / "slides" / name).read_text(encoding="utf-8")
                   for name in (p.name for p in (STRESS / "slides").glob("ZC*-current.tex")))
    for frame in ("titleframe", "sectionframe", "standardframe", "quoteframe", "sideimageframe", "figureframe",
                  "highlightframe", "[standout]", "fullbleedframe", "progressstrip", "SMAlphaItemize",
                  "SMNumItemize", "SMAlphaPeriodItemize", "SMNumPeriodItemize", "enumerate", "columns",
                  "definitionblock", "exampleblock", "alertblock", "infoblock", "referenceblock",
                  "SMFloatingBlock", "footnote", "source", "pause", "SMCodeFile"):
        assert frame in text, frame
    assert text.count("\\begin{itemize}") >= 8


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="compiles the calibration deck: SLIDEMAGE_TEX_TESTS=1 and latexmk")
@pytest.mark.parametrize("profile", ["fira", "lmsans"])
def test_a_shipped_profile_reads_back_its_own_calibrations(profile, tmp_path):
    out = tmp_path / "cal.pdf"
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "calibrate_font_profile.py"), "--profile", profile,
                           "--keep-pdf", str(out)], capture_output=True, text=True, errors="replace")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SET" not in proc.stdout and "SMFooterTextDrop" in proc.stdout and out.is_file()


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="compiles the calibration deck: SLIDEMAGE_TEX_TESTS=1 and latexmk")
def test_the_stress_template_deck_is_clean_against_its_own_margins(tmp_path):
    out = tmp_path / "stress.pdf"
    cal.compile_deck(STRESS, cal.DEFAULT_DECK, "stress-test", None, ROOT / "latex", out)
    check = load("check_layout")
    doc = pymupdf.open(out)
    info = check.pdf_info(doc)
    assert info["top_margin"] == 50.0 and info["left_margin"] != check.LEFT_MARGIN      # the template's own margins
    assert info["ascender"] != check.FIRA_ASCENDER                                       # and its font's own ascender
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "check_layout.py"), "--project", str(STRESS), str(out)],
                          capture_output=True, text=True, errors="replace")
    assert proc.returncode == 0, proc.stdout
