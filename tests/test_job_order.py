"""compiler.order_jobs: a multi-job compile runs version by version, then deck by deck."""
from __future__ import annotations

from pathlib import Path

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


def test_versions_first_then_decks():
    # the table gives work, course, ... order; the checkboxes ask for during-course and presenter
    jobs = [CompileJob(WORK, "during-course", None), CompileJob(WORK, "instructor", None, presenter=True),
            CompileJob(IA2, "during-course", None), CompileJob(IA2, "instructor", None, presenter=True)]
    assert [label(j) for j in order_jobs(jobs)] == [
        "#workdeck:presenter", "IA2:presenter", "#workdeck:during-course", "IA2:during-course"]


def test_full_stage_order_and_group_order():
    jobs = []
    for d in (TEST, TALK, FM2, WORK):   # deliberately not in group order
        jobs += [CompileJob(d, "after-course", None), CompileJob(d, "instructor", None)]
    jobs.append(CompileJob(IA2, "after-course", IA2.chapters[0]))
    jobs.append(CompileJob(IA2, "after-course", IA2.chapters[1]))
    jobs.append(CompileJob(IA2, "instructor", None, presenter=True))
    jobs.append(CompileJob(IA2, "during-course", None))
    assert [label(j) for j in order_jobs(jobs)] == [
        "IA2:presenter",
        "#workdeck:instructor", "FM2:instructor", "talk:instructor", "test:instructor",
        "IA2:during-course",
        "#workdeck:after-course", "FM2:after-course", "talk:after-course", "test:after-course",
        "IA2:chap1", "IA2:chap2"]


def test_order_within_a_group_and_chapters_is_kept():
    jobs = [CompileJob(FM2, "instructor", None), CompileJob(IA2, "instructor", None)]
    assert [label(j) for j in order_jobs(jobs)] == ["FM2:instructor", "IA2:instructor"]
    jobs = [CompileJob(IA2, "after-course", c) for c in reversed(IA2.chapters)]
    assert [label(j) for j in order_jobs(jobs)] == ["IA2:chap2", "IA2:chap1"]


def test_deck_without_version_support_counts_as_instructor():
    plain = CompileJob(FM2, None, None)
    assert [label(j) for j in order_jobs(
        [CompileJob(FM2, "during-course", None), plain])] == ["FM2:None", "FM2:during-course"]


def test_progress_text_counts_compiles_not_decks():
    from slidemage.qt_deck_table import build_progress_texts

    versions = ("instructor", "during-course", "after-course")
    jobs = order_jobs([CompileJob(d, v, None) for d in (WORK, IA2, FM2, TEST) for v in versions][:10])
    texts = build_progress_texts(jobs)
    assert len(jobs) == 10 and len({j.deck.name for j in jobs}) == 4
    assert [texts[j.jobname].split(" | ")[0] for j in jobs] == [f"Deck {i}/10" for i in range(1, 11)]
    assert texts[jobs[3].jobname].endswith(f"Compiling {jobs[3].deck.name}")
    # a single job has no prefix; a chapter job names its chapter
    single = [CompileJob(IA2, "after-course", IA2.chapters[1])]
    assert build_progress_texts(single)[single[0].jobname] == "Compiling IA2: Chapter 2/2"
