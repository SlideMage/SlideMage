"""compile_status: per-job state and error location read off a compile log, and
the per-job stop and skip of compiler.CancelToken / run_jobs that feed it."""
from __future__ import annotations

from pathlib import Path

from slidemage import compile_progress, compile_status, compiler
from slidemage.compile_status import DONE, FAILED, MOVING, QUEUED, RUNNING, STOPPED, RunStatus, parse_error
from slidemage.deck_scan import Chapter, Deck

ROOT = Path("/proj")


def run_of(*names: str) -> RunStatus:
    return RunStatus({n: n.upper() for n in names}, root=ROOT, decks={n: ROOT / "decks" / f"{n}.tex" for n in names})


def feed(run: RunStatus, *lines: str) -> None:
    for line in lines:
        run.feed(line)


def states(run: RunStatus) -> dict[str, str]:
    return {name: row.state for name, row in run.rows.items()}


def test_a_run_goes_through_its_jobs_in_the_order_of_the_log():
    run = run_of("a", "b")
    assert run.feed("==== Rendering 1ab -> x ====") is None
    assert run.feed("==== Compiling deck -> other ====") is None
    assert run.feed("slides/1ab-EN-T-current.tex:3: Oops") is None     # no current job
    assert run.feed("*** FAIL: render of other -- x ***") is None
    assert states(run) == {"a": QUEUED, "b": QUEUED}

    assert run.feed("==== Compiling deck -> a ====").state == RUNNING
    assert run.feed("Run number 1 of rule 'lualatex'") is None
    assert run.feed("==== MOVING: a -> pdf/a.pdf ==== (now backgrounded)").state == MOVING
    feed(run, "==== Compiling deck -> b ====")
    # the PDF of a is published in the background, after b has started
    assert run.feed("==== PASS: a -> pdf/a.pdf ====").state == DONE
    assert states(run) == {"a": DONE, "b": RUNNING}
    assert not run.settled
    feed(run, "==== MOVING: b -> pdf/b.pdf ====")
    assert not run.settled                     # b's PDF is still being moved into place
    run.feed("==== PASS: b -> pdf/b.pdf ====")
    assert run.settled and run.summary() == "2 passed"


def test_failures_and_stops_are_told_apart():
    run = run_of("a", "b", "c")
    feed(run, "==== Compiling deck -> a ====", "*** FAIL: a -- see .build/a.log ***",
         "==== Compiling deck -> b ====", "*** FAIL: b -- stopped by user ***",
         "==== Stopped: 1 job(s) skipped ====")
    assert states(run) == {"a": FAILED, "b": STOPPED, "c": STOPPED}
    assert [row.started for row in run.rows.values()] == [True, True, False]
    assert [row.jobname for row in run.failed] == ["a"]
    assert run.summary() == "0 passed, 1 failed, 2 stopped"


def test_a_job_without_a_pdf_and_a_skipped_job():
    run = run_of("snapshot~a", "b")
    feed(run, "==== Compiling deck -> snapshot~a ====", "==== Finished: snapshot~a ====", "==== Skipped: b ====")
    assert states(run) == {"snapshot~a": DONE, "b": STOPPED}


def test_finish_marks_what_never_ended():
    run = run_of("a", "b", "c")
    feed(run, "==== Compiling deck -> a ====", "==== MOVING: a -> x ====", "==== Compiling deck -> b ====")
    run.finish(stopped=False)
    assert states(run) == {"a": MOVING, "b": FAILED, "c": STOPPED}
    run = run_of("a")
    feed(run, "==== Compiling deck -> a ====")
    run.finish(stopped=True)
    assert states(run) == {"a": STOPPED}


def test_the_first_tex_error_of_a_job_is_kept_with_its_file_and_line():
    run = run_of("a", "b")
    feed(run, "==== Compiling deck -> a ====", "(./slides/1ab-EN-Title-current.tex",
         "slides/1ab-EN-Title-current.tex:47: Undefined control sequence.",
         "slides/1cd-EN-Other-current.tex:5: Missing } inserted.",
         "*** FAIL: a -- see .build/a.log ***", "==== Compiling deck -> b ====")
    error = run.rows["a"].error
    assert error == compile_status.LatexError(ROOT / "slides/1ab-EN-Title-current.tex", 47, "Undefined control sequence.")
    assert error.slide_id == "1ab" and error.where == "1ab · line 47"
    assert run.rows["b"].error is None


def test_error_lines_are_read_in_every_form_a_log_has():
    deck = ROOT / "decks/course.tex"
    absolute = parse_error("/proj/slides/2xy-DE-T-current.tex:9: Bad", ROOT)
    assert absolute.path == Path("/proj/slides/2xy-DE-T-current.tex") and absolute.line == 9
    assert parse_error("./decks/course.tex:12: Runaway argument?", ROOT).path == ROOT / "decks/course.tex"
    # the compile's wrapper file is gone afterwards: the deck, without a line
    wrapped = parse_error("decks/_slidemage_course-instructor_ab12.tex:80: Missing $", ROOT, deck)
    assert (wrapped.path, wrapped.line, wrapped.where) == (deck, None, "course.tex")
    assert parse_error("decks/_slidemage_x.tex:80: Missing $", ROOT) is None
    for text in ("LaTeX Warning: Reference undefined on input line 12.", "l.47 \\begin{x}", "Package biblatex: 3: x",
                 "/usr/share/texmf/foo.sty:123: Undefined control sequence."):
        assert parse_error(text, ROOT, deck) is None


def test_job_titles_name_the_deck_view_chapter_and_pages():
    deck = Deck(name="course", path=Path("course.tex"), archived=False, text="", supports_version=True,
                uses_biblatex=False, preamble_end=0, chapters=[], output_folders={})
    chapter = Chapter(2, "Title", "Title", 0, 0)
    assert compile_status.job_title(compiler.CompileJob(deck, "during-course", None)) == "course · During-course"
    assert compile_status.job_title(compiler.CompileJob(deck, "after-course", chapter)) \
        == "course · After-course, chapter 2: Title"
    assert compile_status.job_title(compiler.CompileJob(deck, "instructor", None, pages=[4, 5, 7])) \
        == "course · Instructor · pages 4-5, 7"


# -- the per-job stop of the cancel token ------------------------------------------

class FakeProcess:
    def __init__(self) -> None:
        self.killed = False

    def poll(self):
        return 0 if self.killed else None

    def kill(self) -> None:
        self.killed = True


def test_stopping_the_current_job_kills_its_process_and_leaves_the_run_going():
    token = compiler.CancelToken()
    token.stop_current()                       # nothing runs: nothing to stop, nothing remembered
    assert not token.job_stopped()
    proc = FakeProcess()
    token._set_process(proc)
    token.stop_current()
    assert proc.killed and not token.is_set()
    assert token.job_stopped() and not token.job_stopped()      # read once
    other = compiler.CancelToken()
    other.request_stop()
    assert other.is_set() and other.job_stopped()


def test_run_jobs_leaves_out_the_jobs_taken_out_of_the_queue(ctx, monkeypatch):
    deck = Deck(name="d", path=Path("d.tex"), archived=False, text="", supports_version=True,
                uses_biblatex=False, preamble_end=0, chapters=[], output_folders={})
    jobs = [compiler.CompileJob(deck, v, None) for v in ("instructor", "during-course", "after-course")]
    ran: list[str] = []
    monkeypatch.setattr(compiler, "run_job", lambda ctx, job, log, cancel=None, dest_override=None: ran.append(job.jobname) or True)
    token, log = compiler.CancelToken(), []
    token.skip("d-during-course")
    results = compiler.run_jobs(ctx, jobs, log.append, cancel=token)
    assert ran == ["d-instructor", "d-after-course"] and results == {"d-instructor": True, "d-after-course": True}
    assert "==== Skipped: d-during-course ====" in log
    token.request_stop()
    log.clear()
    compiler.run_jobs(ctx, jobs, log.append, cancel=token)
    assert log == ["==== Stopped: 3 job(s) skipped ===="]


def test_a_skipped_job_counts_as_done_work_for_the_progress_bar():
    progress = compile_progress.BatchProgress()
    progress.reset({"a": compile_progress.JobSpec(3, 1), "b": compile_progress.JobSpec(3, 1)})
    progress.feed("==== Compiling d -> a ====")
    progress.feed("==== MOVING: a -> pdf/a.pdf ====")
    update = progress.feed("==== Skipped: b ====")
    assert update is not None and update[2] is True            # the batch is complete
