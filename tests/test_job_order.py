# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compiler.order_jobs: a multi-job compile runs version by version, then deck by deck."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage.compiler import CompileJob, order_jobs
from slidemage.deck_scan import Chapter, Deck


def deck(name: str, tag: str, chapters: int = 0) -> Deck:
    return Deck(
        name=name, path=Path(f"{name}.tex"), archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0,
        chapters=[Chapter(i + 1, f"C{i + 1}", f"C{i + 1}", 0, 0) for i in range(chapters)],
        output_folders={}, tags=[tag])


WORK = deck("#workdeck", "work")
IA2 = deck("IA2", "course", chapters=2)
FM2 = deck("FM2", "course")
TALK = deck("talk", "research")
TEST = deck("test", "test")


def label(job: CompileJob) -> str:
    kind = "presenter" if job.presenter else f"chap{job.chapter.order}" if job.chapter else job.version
    return f"{job.deck.name}:{kind}"


@pytest.mark.parametrize("jobs, expected", [
    ([CompileJob(WORK, "during-course", None), CompileJob(WORK, "instructor", None, presenter=True),
      CompileJob(IA2, "during-course", None), CompileJob(IA2, "instructor", None, presenter=True)],
     ["#workdeck:presenter", "IA2:presenter", "#workdeck:during-course", "IA2:during-course"]),
    ([job for d in (TEST, TALK, FM2, WORK)
      for job in (CompileJob(d, "after-course", None), CompileJob(d, "instructor", None))]
     + [CompileJob(IA2, "after-course", c) for c in IA2.chapters]
     + [CompileJob(IA2, "instructor", None, presenter=True), CompileJob(IA2, "during-course", None)],
     ["IA2:presenter", "#workdeck:instructor", "FM2:instructor", "talk:instructor", "test:instructor",
      "IA2:during-course", "#workdeck:after-course", "FM2:after-course", "talk:after-course",
      "test:after-course", "IA2:chap1", "IA2:chap2"]),
    ([CompileJob(FM2, "instructor", None), CompileJob(IA2, "instructor", None)],
     ["FM2:instructor", "IA2:instructor"]),
    ([CompileJob(IA2, "after-course", c) for c in reversed(IA2.chapters)],
     ["IA2:chap2", "IA2:chap1"]),
    ([CompileJob(FM2, "during-course", None), CompileJob(FM2, None, None)],
     ["FM2:None", "FM2:during-course"]),
], ids=["versions-first", "stages-and-groups", "stable-decks", "stable-chapters", "unversioned"])
def test_job_order(jobs, expected):
    assert [label(j) for j in order_jobs(jobs)] == expected
