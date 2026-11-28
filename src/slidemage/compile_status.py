# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-job state of a compile run, read off the log lines the compile already
writes (the same lines compile_progress.py follows for the progress bar).

No Qt in here: `RunStatus.feed(line)` is called for every log line by the
window (ui/workspace/compile_jobs.py) and says which job's row changed, so a
whole run can be tested by replaying a captured log. A job goes
queued -> running -> (moving) -> done / failed / stopped:

* ``==== Compiling <deck> -> <job> ====``   the job starts;
* ``==== MOVING: <job> -> ...``              latexmk is done, the PDF is being
                                             published in the background;
* ``==== PASS: <job> -> ...``                the PDF is in place (this can
                                             come after the next job started);
* ``*** FAIL: <job> -- <reason> ***``        failed, or "stopped by user";
* ``==== Finished: <job> ====``              a job that publishes no PDF
                                             (deck snapshots) is done;
* ``==== Skipped: <job> ====``, ``==== Stopped: N job(s) skipped ====``
                                             queued jobs the user stopped.

With ``latexmk -file-line-error`` (the project's .latexmkrc) every TeX error
is a line ``<file>:<line>: <message>``; the first one of a job is kept as the
job's `error`, so the window can jump to the failing file and line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .compile_log import (
    COMPILING_RE as _COMPILING_RE,
    FAIL_RE as _FAIL_RE,
    FINISHED_RE as _FINISHED_RE,
    MOVING_RE as _MOVING_RE,
    PASS_RE as _PASS_RE,
    SKIPPED_RE as _SKIPPED_RE,
    STOPPED_ALL_RE as _STOPPED_ALL_RE,
)
from .compiler import CompileJob, job_label
from .partial_compile import format_page_spec
from .slide_language import bare_id

QUEUED, RUNNING, MOVING, DONE, FAILED, STOPPED = "queued", "running", "moving", "done", "failed", "stopped"

# "slides/1ab-EN-Title-current.tex:47: Undefined control sequence." (-file-line-error)
_ERROR_RE = re.compile(r"^(?P<file>\S.*?\.tex):(?P<line>\d+): (?P<message>\S.*)$")
# The wrapper a compile writes next to the deck (compiler.py) is deleted afterwards.
_WRAPPER_PREFIX = "_slidemage_"
STOPPED_BY_USER = "stopped by user"


def job_title(job: CompileJob) -> str:
    """What a run's rows call a job: "course · After-course, chapter 2: Title",
    with the page numbers of a page compile."""
    title = f"{job.deck.name} · {job_label(job)}"
    return f"{title} · pages {format_page_spec(job.pages)}" if job.pages else title


@dataclass(frozen=True)
class LatexError:
    path: Path
    line: Optional[int]    # None: in a wrapper that no longer exists, `path` is the deck
    message: str

    @property
    def slide_id(self) -> Optional[str]:
        """The slide the error is in, or None for a deck or any other file."""
        return bare_id(self.path.name) if self.path.parent.name == "slides" else None

    @property
    def where(self) -> str:
        """"1ab" or "1ab · line 47"; the file name for anything but a slide."""
        name = self.slide_id or self.path.name
        return f"{name} · line {self.line}" if self.line else name


def parse_error(line: str, root: Path, deck_path: Optional[Path] = None) -> Optional[LatexError]:
    """The error a log line reports, with its file resolved against the
    project `root`. Errors in the compile's own wrapper file have no line of
    the deck, so they point at `deck_path` (the job's deck) without one."""
    match = _ERROR_RE.match(line)
    if match is None:
        return None
    path = Path(match["file"])
    message = match["message"].strip()
    if path.name.startswith(_WRAPPER_PREFIX):
        return LatexError(deck_path, None, message) if deck_path is not None else None
    return LatexError(path if path.is_absolute() else root / path, int(match["line"]), message)


@dataclass
class JobRow:
    jobname: str
    label: str
    state: str = QUEUED
    started: bool = False                    # a stopped job that never started was "skipped"
    pdf: Optional[Path] = None               # where the PDF lands, when the job makes one
    error: Optional[LatexError] = None


class RunStatus:
    """The jobs of one run, in queue order, and what became of each."""

    def __init__(self, labels: dict[str, str], *, root: Path, verb: str = "", pdfs: Optional[dict[str, Path]] = None,
                 decks: Optional[dict[str, Path]] = None) -> None:
        """`labels`: jobname -> what to call it; `verb` goes before the label
        of the running job ("Compiling"). `pdfs`: jobname -> its PDF. `decks`:
        jobname -> its deck's file (where an error in the compile's wrapper
        file is shown)."""
        self.verb = verb
        self.rows = {name: JobRow(name, label, pdf=(pdfs or {}).get(name)) for name, label in labels.items()}
        self._decks = decks or {}
        self._root = root
        self._current: Optional[str] = None

    def feed(self, line: str) -> Optional[JobRow]:
        """Apply one log line; the row that changed, or None."""
        if line.startswith("===="):
            if m := _COMPILING_RE.match(line):
                self._current = m[1] if m[1] in self.rows else None
                return self._set(m[1], RUNNING)
            if m := _MOVING_RE.match(line):
                return self._set(m[1], MOVING)
            if m := _PASS_RE.match(line) or _FINISHED_RE.match(line):
                return self._set(m[1], DONE)
            if m := _SKIPPED_RE.match(line):
                return self._set(m[1], STOPPED)
            if _STOPPED_ALL_RE.match(line):
                return self._stop_queued()
        elif line.startswith("*** FAIL"):
            if m := _FAIL_RE.match(line):
                return self._set(m[1], STOPPED if m[2].startswith(STOPPED_BY_USER) else FAILED)
        elif self._current is not None:
            row = self.rows[self._current]
            if row.error is None and (error := parse_error(line, self._root, self._decks.get(row.jobname))):
                row.error = error
                return row
        return None

    def _set(self, jobname: str, state: str) -> Optional[JobRow]:
        row = self.rows.get(jobname)
        if row is None or row.state == state:
            return None
        row.state = state
        row.started = row.started or state == RUNNING
        return row

    def _stop_queued(self) -> Optional[JobRow]:
        changed = None
        for row in self.rows.values():
            if row.state == QUEUED:
                row.state, changed = STOPPED, row
        return changed

    def finish(self, stopped: bool) -> None:
        """The worker is done. What never started was skipped; what still
        runs (and is not just being moved into place) ended without a
        message: stopped by the user, else failed."""
        for row in self.rows.values():
            if row.state == QUEUED:
                row.state = STOPPED
            elif row.state == RUNNING:
                row.state = STOPPED if stopped else FAILED

    def stop_row(self, jobname: str) -> None:
        """A queued job taken out of the queue (compiler.CancelToken.skip)."""
        self._set(jobname, STOPPED)

    # -- what the panels show ----------------------------------------------------

    def count(self, *states: str) -> int:
        return sum(row.state in states for row in self.rows.values())

    @property
    def settled(self) -> bool:
        """No job is waiting, running or having its PDF moved into place."""
        return self.count(QUEUED, RUNNING, MOVING) == 0

    @property
    def failed(self) -> list[JobRow]:
        return [row for row in self.rows.values() if row.state == FAILED]

    def summary(self) -> str:
        """"2 passed, 1 failed, 1 stopped"; the zero counts left out."""
        parts = [f"{self.count(DONE, MOVING)} passed"]
        parts += [f"{n} {name}" for name, n in (("failed", self.count(FAILED)), ("stopped", self.count(STOPPED))) if n]
        return ", ".join(parts)
