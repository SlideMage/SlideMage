# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A log of everything the progress card showed during a run, and when (for finding out why a status looks odd).

`StatusTrace.record()` is called after every log line the compile slot feeds; it writes a line only when the shown
state changed: seconds since the run started, the overall percentage, the running job's text, every job's state, and
the log line that caused the change. The file is `status-progression.log` in SlideMage's config folder (the newest
run only); SLIDEMAGE_STATUS_LOG names another file. No Qt.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .project import config_dir

FILE_NAME = "status-progression.log"
ENV_VAR = "SLIDEMAGE_STATUS_LOG"
LINE_CHARS = 100


def default_path() -> Path:
    return Path(os.environ[ENV_VAR]) if os.environ.get(ENV_VAR) else config_dir() / FILE_NAME


class StatusTrace:
    def __init__(self, path: Optional[Path] = None, clock=time.monotonic) -> None:
        self.path = path or default_path()
        self._clock = clock
        self._start = clock()
        self._last: Optional[tuple] = None
        self._file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "w", encoding="utf-8")
        except OSError:
            self._file = None          # a diagnostic, never a reason to stop a run

    def header(self, text: str) -> None:
        self._write(f"# {text}")

    def record(self, line: str, progress, run) -> None:
        """Note the state the card shows now, if it differs from the last one noted."""
        fraction = progress.fraction
        percent = "…" if fraction is None else f"{round(fraction * 100)}%"
        rows = " ".join(f"{name.rsplit('-', 1)[-1]}={row.state}" for name, row in run.rows.items()) if run is not None else ""
        state = (percent, progress.text, rows)
        if state == self._last:
            return
        self._last = state
        self._write(f"+{self._clock() - self._start:8.1f}s | {percent:>4} | {progress.text or '-':40s} | {rows} | {line[:LINE_CHARS]}")

    def _write(self, text: str) -> None:
        if self._file is not None:
            try:
                self._file.write(text + "\n")
                self._file.flush()
            except OSError:
                self._file = None

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
