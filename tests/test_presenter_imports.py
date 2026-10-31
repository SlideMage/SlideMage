# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Presenting a PDF without a project stays free of the heavy parts of SlideMage (docs/plans/presenter-app.md):
SlideMage Presenter is built from these modules, and PyInstaller bundles whatever they import. When this fails,
make the new import lazy or move the project-specific part out of presentation/ and ui/presentation/; do not
shorten the list."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import slidemage

# What the Presenter imports: presenting a PDF, the presentation settings page, the kit's theme.
PRESENTER_MODULES = ("slidemage.ui.presentation.standalone", "slidemage.ui.presentation.settings_page",
                     "slidemage.ui.presentation.resume_ui", "slidemage.ui.kit.theme",
                     "slidemage.presenter_app", "slidemage.ui.presentation.presenter_window")

# Never needed for presenting a PDF. A package listed here also forbids its submodules.
FORBIDDEN = (
    "slidemage.ai", "slidemage.compiler", "slidemage.compile_records", "slidemage.deck_scan",
    "slidemage.plugins", "slidemage.preview_build", "slidemage.render_scheduler", "slidemage.ui.app",
    "slidemage.ui.workspace", "slidemage.ui.dialogs", "slidemage.presentation.frames", "slidemage.presentation.locate",
    "slidemage.ui.presentation.launch", "slidemage.cli",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtNetwork",
    "lxml", "pptx", "odf", "segno", "winpty", "ptyprocess",
)


def _loaded_after_import() -> list[str]:
    script = ("import json, sys\n"
              f"for name in {PRESENTER_MODULES!r}:\n"
              "    __import__(name)\n"
              "print(json.dumps(sorted(sys.modules)))\n")
    # The package under test, not an editable install of another checkout.
    env = {**os.environ, "PYTHONPATH": str(Path(slidemage.__file__).resolve().parents[1]),
           "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_presenting_a_pdf_imports_nothing_heavy():
    loaded = _loaded_after_import()
    found = [name for name in loaded if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)]
    assert not found, f"the Presenter's modules now import {found}"
