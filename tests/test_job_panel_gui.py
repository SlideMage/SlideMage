# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The progress card names the job that is being compiled, not an earlier one whose PDF is still being moved."""
from pathlib import Path

from PySide6.QtWidgets import QWidget

from slidemage import compile_log
from slidemage.compile_status import RunStatus
from slidemage.ui.workspace.job_panel import JobPanel


def test_the_card_shows_the_running_job_while_the_previous_ones_pdf_is_moved(qapp, tmp_path):
    parent = QWidget()
    parent.resize(800, 600)
    panel = JobPanel(parent)
    run = RunStatus({"deck-a": "Deck · Instructor", "deck-b": "Deck · During course", "deck-c": "Deck · After course"},
                    root=tmp_path, verb="Compiling")
    panel.start(run, per_job_stop=True, can_retry=True)
    for line in (compile_log.compiling("deck", "deck-a"), compile_log.moving("deck-a", Path("a.pdf")),
                 compile_log.compiling("deck", "deck-b")):
        run.feed(line)
    panel.refresh(0.34, "pass 1/5, slide 3/390", over=False)
    assert panel._title.text() == "Compiling Deck · During course"
    assert panel._sub.text() == "2 of 3 · pass 1/5, slide 3/390"
    run.feed(compile_log.moving("deck-b", Path("b.pdf")))
    run.feed(compile_log.passed("deck-a", Path("a.pdf")))
    panel.refresh(0.67, "", over=False)           # nothing runs but a PDF is moved: that job is shown
    assert panel._title.text() == "Compiling Deck · During course"
    assert "moving the PDF" in panel._sub.text()
