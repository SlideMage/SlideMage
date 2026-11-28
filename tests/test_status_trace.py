# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The status-progression log: one line per change of what the progress card shows."""
import logging

from slidemage import compile_log, compile_progress
from slidemage.compile_status import RunStatus
from slidemage.status_trace import StatusTrace


def test_only_changes_are_written_with_the_state_and_the_line_that_caused_them(tmp_path, caplog):
    clock = iter(range(100, 200))
    trace = StatusTrace(clock=lambda: float(next(clock)))
    progress = compile_progress.BatchProgress()
    progress.reset({"deck-a": compile_progress.JobSpec(2, 2)})
    run = RunStatus({"deck-a": "A"}, root=tmp_path)
    for line in (compile_log.compiling("deck", "deck-a"), "Run number 1 of rule 'lualatex'", "no change here",
                 "Run number 2 of rule 'lualatex'"):
        progress.feed(line)
        run.feed(line)
        with caplog.at_level(logging.DEBUG, logger="slidemage.status"):
            trace.record(line, progress, run)
    lines = [r.getMessage() for r in caplog.records if r.name == "slidemage.status"]
    assert len(lines) == 3 and "starting" in lines[0] and "pass 2/2" in lines[2]
    assert "a=running" in lines[1] and "Run number 1" in lines[1]
