# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The manual fits every template the framework ships (step 17c): each deck version of slidemage-manual.tex, compiled
under each latex/SlideMage_template_*.tex, has no tools/check_layout.py finding (slides with a `layout-check: skip`
comment are exempt as ever). The sibling deck slidemage-manual-copy.tex is held to it under the SlideMage template.
A slide that fits only one template shows up here at once. Compiles the manual, so opt-in: SLIDEMAGE_TEX_TESTS=1 and
latexmk; takes a few minutes per template."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted(p.stem.removeprefix("SlideMage_template_") for p in (ROOT / "latex").glob("SlideMage_template_*.tex"))
COPY_DECK_TEMPLATES = ("slidemage",)

needs_tex = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                               reason="compiles the manual: SLIDEMAGE_TEX_TESTS=1 and latexmk")


def test_the_framework_ships_the_templates_this_check_covers():
    assert {"slidemage", "greyscale"} <= set(TEMPLATES)


@needs_tex
@pytest.mark.parametrize("template", TEMPLATES)
def test_the_manual_has_no_layout_finding_under_the_template(template, tmp_path):
    decks = [{"deck": "decks/slidemage-manual.tex", "template": template}]
    if template in COPY_DECK_TEMPLATES:
        decks.append({"deck": "decks/slidemage-manual-copy.tex", "template": template})
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"project": str(ROOT / "example"), "framework": str(ROOT / "latex"), "copy": True,
                                  "copy_exclude": [".build", ".previews", ".scripts", ".slidemage", "pdf"],
                                  "decks": decks}), encoding="utf-8")
    out = tmp_path / "run"
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "framework_regression.py"), "record", str(config),
                           "--out", str(out), "--jobs", "2"], capture_output=True, text=True, errors="replace")
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    pdfs = sorted((out / "baseline").glob("*.pdf"))
    assert len(pdfs) == 3 * len(decks)
    check = subprocess.run([sys.executable, str(ROOT / "tools" / "check_layout.py"), "--project", str(ROOT / "example"),
                            *map(str, pdfs)], capture_output=True, text=True, errors="replace")
    assert check.returncode == 0, check.stdout
