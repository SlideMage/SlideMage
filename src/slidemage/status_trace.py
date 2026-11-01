# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the progress card showed during a run, and when, in the debug log (area `status`; for finding out why a
status looks odd).

`StatusTrace.record()` is called after every log line the compile slot feeds; it writes a debug line only when
the shown state changed: seconds since the run started, the overall percentage, the running job's text, every
job's state, and the log line that caused the change. While the debug log is off it does nothing. Until v0.13.7
this was status-progression.log in the config folder, written on every run. No Qt.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

LINE_CHARS = 100
log = logging.getLogger("slidemage.status")


class StatusTrace:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._start = clock()
        self._last: Optional[tuple] = None

    def header(self, text: str) -> None:
        log.debug("%s", text)

    def record(self, line: str, progress, run) -> None:
        """Note the state the card shows now, if it differs from the last one noted."""
        if not log.isEnabledFor(logging.DEBUG):
            return
        fraction = progress.fraction
        percent = "…" if fraction is None else f"{round(fraction * 100)}%"
        rows = " ".join(f"{name.rsplit('-', 1)[-1]}={row.state}" for name, row in run.rows.items()) if run is not None else ""
        state = (percent, progress.text, rows)
        if state == self._last:
            return
        self._last = state
        log.debug("+%.1fs | %4s | %-40s | %s | %s", self._clock() - self._start, percent, progress.text or "-", rows,
                  line[:LINE_CHARS])
