"""Progress of a PDF compile, derived from the log lines the compile already
produces (2026-09-27, direct instruction: a thin progress bar at the top edge
of the log window; 4 compile passes assumed, 3 for a deck without a
bibliography; progress *within* a pass from the slide currently being
typeset; also for single-slide renders and Update previews).

No Qt in here -- `BatchProgress.feed(line)` is called by qt_gui.py's `_log()`
for every log line and returns the new (fraction, text) when something
changed, so the whole thing can be tested by replaying a captured log.

What the log gives us (measured on a real latexmk run):

* ``Run number K of rule 'lualatex'``  -- pass K starts (a biber run in
  between is ``... of rule 'biber ...'``, which just leaves the bar where
  the finished pass put it);
* ``(D:/.../slides/<id>-<LANG>-<slug>-current.tex``  -- LaTeX starts
  reading a slide file, i.e. that slide is now being typeset. Every slide
  call reads its file once per pass, so "slide files seen in this pass"
  divided by "slide calls in this job" is the position inside the pass.

fraction of a job = ((pass - 1) + slides_seen / slides_total) / passes,
held below 100% until the job really finishes. Work is weighted by
passes * slides per job, so in a queue a 395-slide deck outweighs a
10-slide chapter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import latex_lint

PASSES_WITH_BIBLIOGRAPHY = 4
PASSES_WITHOUT_BIBLIOGRAPHY = 3
SINGLE_RENDER_PASSES = 3

_RUN_RE = re.compile(r"^Run number (\d+) of rule '([^']+)'")
_SLIDE_OPEN_RE = re.compile(r"\(\S*?/slides/[0-9A-Za-z]{3}-")
_COMPILING_RE = re.compile(r"^==== Compiling \S+ -> (\S+) ====")
_RENDERING_RE = re.compile(r"^==== Rendering (\S+) -> (\S+) ====")
_MOVING_RE = re.compile(r"^==== MOVING: (\S+) ->")
_FAIL_RE = re.compile(r"^\*\*\* FAIL: (\S+) --")
_RENDER_PASS_RE = re.compile(r"^==== PASS: render of (\S+) ->")
_RENDER_FAIL_RE = re.compile(r"^\*\*\* FAIL: render of (\S+) --")
_STOPPED_RE = re.compile(r"^==== (Stopped:|Stop requested)")

_HOLD_BELOW_DONE = 0.99


@dataclass(frozen=True)
class JobSpec:
    passes: int
    slides: int          # slide calls typeset per pass (0 = unknown -> indeterminate)

    @property
    def units(self) -> int:
        return self.passes * max(self.slides, 1)


def passes_for(uses_biblatex: bool) -> int:
    return PASSES_WITH_BIBLIOGRAPHY if uses_biblatex else PASSES_WITHOUT_BIBLIOGRAPHY


def count_job_slides(deck, version: Optional[str], chapter) -> int:
    """Slide calls a compile of `deck` (in `version`, whole or one chapter)
    typesets per pass -- the same scoping the pre-render syntax check uses:
    calls left out of the version by \\conditionalslide/\\slidestep are not
    counted, a chapter job counts only its chapter, and \\input-ed deck
    fragments (test-slides.tex) count with their own calls."""
    total = 0
    text = deck.text
    for call in latex_lint._calls_in(text, deck.chapters):
        if chapter is not None and (call.chapter is None or call.chapter.order != chapter.order):
            continue
        if latex_lint._slide_included(call, version):
            total += 1
    if deck.preamble_end is not None:
        body = latex_lint._masked_same_length(text)[deck.preamble_end:]
        for m in latex_lint._INPUT_RE.finditer(body):
            name = m.group(1).strip()
            frag = latex_lint.DECKS_DIR / (name if name.endswith(".tex") else name + ".tex")
            if frag.is_file():
                frag_text = latex_lint.read_source(frag) or ""
                total += sum(1 for c in latex_lint._calls_in(frag_text, [])
                             if latex_lint._slide_included(c, version))
    return total


def spec_for_job(job) -> JobSpec:
    """JobSpec of a compiler.CompileJob."""
    return JobSpec(passes_for(job.deck.uses_biblatex),
                   count_job_slides(job.deck, job.version, job.chapter))


class BatchProgress:
    """One progress value over a queue of jobs (see the module docstring)."""

    def __init__(self) -> None:
        self.reset({})

    # -- lifecycle --------------------------------------------------------------

    def reset(self, specs: dict[str, JobSpec]) -> None:
        """Start tracking a new batch: `specs` maps jobname -> JobSpec."""
        self._specs = dict(specs)
        self._total_units = sum(s.units for s in specs.values())
        self._done_units = 0
        self._finished: set[str] = set()
        self._current: Optional[str] = None
        self._pass = 0
        self._seen = 0
        self._announced = False

    @property
    def active(self) -> bool:
        return self._current is not None

    # -- value ------------------------------------------------------------------

    def _current_fraction(self) -> float:
        spec = self._specs[self._current]  # type: ignore[index]
        if self._pass <= 0:
            return 0.0
        inside = min(self._seen / spec.slides, 1.0) if spec.slides else 0.0
        fraction = ((min(self._pass, spec.passes) - 1) + inside) / spec.passes
        if self._pass > spec.passes:
            fraction = 1.0
        return min(fraction, _HOLD_BELOW_DONE)

    @property
    def fraction(self) -> Optional[float]:
        """0..1 overall, or None while the current job's size is unknown
        (the bar then shows its indeterminate animation)."""
        if self._current is None:      # between jobs: what is done so far
            return self._done_units / self._total_units if self._total_units else None
        spec = self._specs[self._current]
        if spec.slides <= 0:
            return None
        cur = self._current_fraction() * spec.units
        return (self._done_units + cur) / max(self._total_units, 1)

    @property
    def text(self) -> str:
        if self._current is None:
            return ""
        spec = self._specs[self._current]
        if self._pass <= 0:
            return "starting"
        shown = min(self._pass, spec.passes)
        extra = f" (extra pass {self._pass})" if self._pass > spec.passes else ""
        where = f", slide {min(self._seen, spec.slides)}/{spec.slides}" if spec.slides else ""
        return f"pass {shown}/{spec.passes}{where}{extra}"

    # -- input ------------------------------------------------------------------

    def _finish_current(self) -> None:
        if self._current is not None and self._current not in self._finished:
            self._finished.add(self._current)
            self._done_units += self._specs[self._current].units
        self._current = None

    def feed(self, line: str) -> Optional[tuple[Optional[float], str, bool]]:
        """Process one log line. Returns (fraction, text, finished_batch) if
        the displayed state changed, else None. `finished_batch` is True once,
        on the line that completes the last job (the caller shows 100% and
        hides the bar shortly after)."""
        if not line:
            return None
        before = (self.fraction, self.text)

        if "/slides/" in line:
            if self._current is not None and _SLIDE_OPEN_RE.search(line):
                self._seen += 1
        elif line.startswith("Run number"):
            m = _RUN_RE.match(line)
            if m and self._current is not None and m.group(2).startswith("lualatex"):
                self._pass = int(m.group(1))
                self._seen = 0
        elif line.startswith("===="):
            m = _COMPILING_RE.match(line)
            if m:
                self._begin(m.group(1), JobSpec(SINGLE_RENDER_PASSES, 0))
            else:
                m = _RENDERING_RE.match(line)
                if m:
                    self._begin(m.group(2), JobSpec(SINGLE_RENDER_PASSES, 1), force=True)
                else:
                    m = _MOVING_RE.match(line)
                    if m and m.group(1) == self._current:
                        self._finish_current()
                    elif _RENDER_PASS_RE.match(line):
                        self._finish_current()
                    elif _STOPPED_RE.match(line):
                        self.reset({})      # stopped by the user: back to idle
                        self._announced = True
        elif line.startswith("*** FAIL"):
            if _FAIL_RE.match(line) or _RENDER_FAIL_RE.match(line):
                self._finish_current()

        if (self._current is None and not self._announced and self._specs
                and len(self._finished) >= len(self._specs)):
            self._announced = True
            return (1.0, "done", True)
        after = (self.fraction, self.text)
        if after == before:
            return None
        return (after[0], after[1], False)

    def _begin(self, jobname: str, fallback: JobSpec, force: bool = False) -> None:
        """A job starts. Jobs announced up front (reset()) keep their spec;
        anything else (an ad-hoc render, a job nobody told us about) is
        added with `fallback`."""
        self._finish_current()
        if self._announced and (force or jobname not in self._specs):
            self.reset({})          # the previous batch is over: start afresh
        if force or jobname not in self._specs:
            self._specs[jobname] = fallback
            self._total_units += fallback.units
            self._announced = False
        self._current, self._pass, self._seen = jobname, 0, 0
