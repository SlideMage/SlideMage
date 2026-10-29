# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/calibrate_font_profile.py (v10.9.0): checks the values the base derives against the geometry their hooks ask
for, measured in the calibration deck's PDF; a profile holds no number for it to suggest any more. The pure
parts are tested here; the compile-and-measure run is opt-in (needs LuaLaTeX: SLIDEMAGE_TEX_TESTS=1), like the other
tests that compile."""
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


def test_the_shipped_profiles_hold_none_of_the_numbers_the_base_derives():
    for profile in ("fira", "lmsans"):
        text = cal.profile_text(ROOT / "latex", profile)
        # derived since v10.8.0, and the three pull-ups since v10.9.0
        for name in ("SMFooterTextDrop", "SMSectionframeHeightCorrection", "SMLabelItemWidth", "SMLabelItemSep",
                     "SMEnumerateNestedMinNumber", "SMEnumerateNestedLeftMargin", "SMContentTopShift",
                     "SMColumnsTopCorrection", "SMColumnsTTopCompensation"):
            assert cal.tex_length(text, name) is None, (profile, name)
    assert not hasattr(cal, "Row") and not hasattr(cal, "T_COLUMNS_OFFSET")    # nothing to suggest, no Fira offset


def test_a_check_is_ok_within_its_tolerance_and_when_nothing_was_measured():
    assert cal.Check("x", 1.0, 1.2, "").ok and not cal.Check("x", 1.0, 1.5, "").ok
    assert cal.Check("x", None, 1.5, "").ok and cal.Check("x", 1.0, None, "").ok
    assert cal.Check("x", 0.1, 0.0, "", tolerance=0.05).ok is False


def test_a_catalog_default_in_em_is_read_from_the_setup_file():
    setup = (BS + "newcommand{" + BS + "SMLabelItemGap}{0.475em}  % gap" + chr(10)
             + BS + "newcommand{" + BS + "SMOther}{3pt}" + chr(10))
    assert cal.em_default(setup, "SMLabelItemGap") == 0.475
    assert cal.em_default(setup, "SMOther") is None and cal.em_default(setup, "SMMissing") is None
    shipped = (ROOT / "latex" / "SlideMage_setup.tex").read_text(encoding="utf-8")
    for name in ("SMLabelItemGap", "SMEnumerateNestedSlotExtra", "SMEnumerateNestedLabelGap"):
        assert cal.em_default(shipped, name) is not None, name


def test_the_template_input_of_a_deck_is_swapped_for_a_template_under_a_profile():
    deck = (STRESS / "decks" / "calibration.tex").read_text(encoding="utf-8")
    assert len(cal.TEMPLATE_INPUT_RE.findall(deck)) == 1
    swapped, n = cal.TEMPLATE_INPUT_RE.subn(lambda m: "X", deck, count=1)
    assert n == 1 and "SlideMage_template_stress-test" not in swapped


def test_the_calibration_deck_has_a_slide_for_each_measurement():
    slides = {p.name.split("-")[0] for p in (STRESS / "slides").glob("*-current.tex")}
    deck = (STRESS / "decks" / "calibration.tex").read_text(encoding="utf-8")
    ids = (STRESS / "slide_ids.csv").read_text(encoding="utf-8")
    for slide_id in ("ZC2", "ZC3", "ZC4", "ZC5", "ZC8", "ZCI", "ZCJ", "ZCK", "ZCL"):
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
def test_a_shipped_profile_meets_its_hooks(profile, tmp_path):
    out = tmp_path / "cal.pdf"
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "calibrate_font_profile.py"), "--profile", profile,
                           "--keep-pdf", str(out)], capture_output=True, text=True, errors="replace")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL" not in proc.stdout and out.is_file()
    assert proc.stdout.count("manual-top frame") == 3
    assert "footer number centred" in proc.stdout and "footnote descenders" in proc.stdout and "section bar height" in proc.stdout


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
