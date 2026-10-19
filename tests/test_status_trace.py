# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The status-progression log: one line per change of what the progress card shows."""
from slidemage import compile_log, compile_progress
from slidemage.compile_status import RunStatus
from slidemage.status_trace import StatusTrace


def test_only_changes_are_written_with_the_state_and_the_line_that_caused_them(tmp_path):
    clock = iter(range(100, 200))
    trace = StatusTrace(tmp_path / "trace.log", clock=lambda: float(next(clock)))
    progress = compile_progress.BatchProgress()
    progress.reset({"deck-a": compile_progress.JobSpec(2, 2)})
    run = RunStatus({"deck-a": "A"}, root=tmp_path)
    for line in (compile_log.compiling("deck", "deck-a"), "Run number 1 of rule 'lualatex'", "no change here",
                 "Run number 2 of rule 'lualatex'"):
        progress.feed(line)
        run.feed(line)
        trace.record(line, progress, run)
    trace.close()
    lines = (tmp_path / "trace.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and "starting" in lines[0] and "pass 2/2" in lines[2]
    assert "a=running" in lines[1] and "Run number 1" in lines[1]
