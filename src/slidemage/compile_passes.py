"""How many LaTeX passes each deck's compile needed last time (v5.15.0,
direct instruction: the progress label should show the number of passes a
deck really needs, not a fixed guess).

Every SlideMage compile runs latexmk in a fresh build folder of its own
(compiler.compile_job), so a deck needs the same number of passes each
time until its content changes -- the last count is a good prediction.
compile_progress.spec_for_job() reads it; compiler.compile_job() writes it
after every successful job.

Kept per deck and job kind (a version, "presenter", or "<version>-chapter")
in the project's .slidemage/compile_passes.json, not in the deck file: a
compile writing into a deck would make an open deck editor see the file as
changed on disk and refuse its next edit.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

from . import project


# latexmk's own line at the start of every pass
RUN_RE = re.compile(r"^Run number (\d+) of rule 'lualatex")

_lock = threading.Lock()


def job_kind(job) -> str:
    """Which count of a deck a compiler.CompileJob uses."""
    if job.presenter:
        return "presenter"
    kind = job.version or "deck"
    return f"{kind}-chapter" if job.chapter is not None else kind


def _store_path(ctx: project.ProjectContext) -> Path:
    return ctx.settings_dir / "compile_passes.json"


def _load(ctx: project.ProjectContext) -> dict:
    try:
        data = json.loads(_store_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(ctx: project.ProjectContext, data: dict) -> None:
    path = _store_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# Job kinds that need the same passes (v5.20.0, direct instruction: "when a
# presenter compile has finished, an instructor compile of the same deck could
# already show the correct number of necessary passes (and vice versa?)").
# The passes are what the .aux-driven parts need to settle -- bibliography,
# chapter agendas, remembered TikZ positions (logo patch, overlays), the
# automatic Top Margin -- and a presenter compile has exactly the instructor
# content (only the page layout adds a notes panel). Measured equal on every
# SlideMaster deck compiled both ways.
_SAME_PASSES = {"instructor": ("presenter", "deck"), "presenter": ("instructor", "deck"),
                "deck": ("instructor", "presenter")}
# Kinds whose count is a fair guess for another kind (shown as "(estimated)"):
# a student version has fewer slides, and "final state only" slides need one
# settling round more, so its count may differ from the instructor's.
_SIMILAR = {
    "during-course": ("after-course", "instructor", "presenter", "deck"),
    "after-course": ("during-course", "instructor", "presenter", "deck"),
}


def predict(ctx: project.ProjectContext, job) -> tuple[Optional[int], bool]:
    """(passes, known): the count this job's deck needed last time for the
    same kind of job -- or for a kind that needs the same passes (presenter /
    instructor) -- with known=True; else a related kind's count as an
    estimate (another student version, the whole deck for a chapter job),
    known=False; else (None, False)."""
    kind = job_kind(job)
    with _lock:
        counts = _load(ctx).get(job.deck.name, {})
    if not isinstance(counts, dict):
        return None, False

    def count(k: str) -> Optional[int]:
        value = counts.get(k)
        return value if isinstance(value, int) and value > 0 else None

    for k in (kind, *_SAME_PASSES.get(kind, ())):
        if count(k):
            return count(k), True
    base = kind[: -len("-chapter")] if kind.endswith("-chapter") else None
    candidates = ((base, *_SAME_PASSES.get(base, ()), *_SIMILAR.get(base, ()))
                  if base else _SIMILAR.get(kind, ()))
    for k in candidates:
        if count(k):
            return count(k), False
    return None, False


def expected(ctx: project.ProjectContext, job) -> Optional[int]:
    """The passes this job's deck needed last time, or None if unknown."""
    with _lock:
        value = _load(ctx).get(job.deck.name, {}).get(job_kind(job))
    return value if isinstance(value, int) and value > 0 else None


def remember(ctx: project.ProjectContext, job, passes: int) -> None:
    """Record a finished job's pass count (written only when it changed)."""
    if passes <= 0:
        return
    with _lock:
        data = _load(ctx)
        deck = data.setdefault(job.deck.name, {})
        if not isinstance(deck, dict):
            deck = data[job.deck.name] = {}
        kind = job_kind(job)
        if deck.get(kind) == passes:
            return
        deck[kind] = passes
        try:
            _write(ctx, data)
        except OSError:
            pass                    # a prediction only: never fail a compile over it


def copy_counts(ctx: project.ProjectContext, source_name: str, new_name: str) -> None:
    """A duplicated deck starts with the remembered counts of its original
    (v5.21.0, direct instruction): the copy has the same content, so it needs
    the same passes. Nothing happens if the original was never compiled."""
    with _lock:
        data = _load(ctx)
        counts = data.get(source_name)
        if not isinstance(counts, dict) or not counts:
            return
        data[new_name] = dict(counts)
        try:
            _write(ctx, data)
        except OSError:
            pass
