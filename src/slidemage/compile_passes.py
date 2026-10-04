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
from typing import Optional

from .deck_scan import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / ".slidemage" / "compile_passes.json"

# latexmk's own line at the start of every pass
RUN_RE = re.compile(r"^Run number (\d+) of rule 'lualatex")

_lock = threading.Lock()


def job_kind(job) -> str:
    """Which count of a deck a compiler.CompileJob uses."""
    if job.presenter:
        return "presenter"
    kind = job.version or "deck"
    return f"{kind}-chapter" if job.chapter is not None else kind


def _load() -> dict:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def expected(job) -> Optional[int]:
    """The passes this job's deck needed last time, or None if unknown."""
    with _lock:
        value = _load().get(job.deck.name, {}).get(job_kind(job))
    return value if isinstance(value, int) and value > 0 else None


def remember(job, passes: int) -> None:
    """Record a finished job's pass count (written only when it changed)."""
    if passes <= 0:
        return
    with _lock:
        data = _load()
        deck = data.setdefault(job.deck.name, {})
        if not isinstance(deck, dict):
            deck = data[job.deck.name] = {}
        kind = job_kind(job)
        if deck.get(kind) == passes:
            return
        deck[kind] = passes
        try:
            STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STORE_PATH.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass                    # a prediction only: never fail a compile over it
