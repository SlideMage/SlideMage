"""The status protocol's writers keep the captured log text and match groups."""
from pathlib import Path

import pytest

from slidemage import compile_log


@pytest.mark.parametrize("writer,args,expected,recognizers", [
    (compile_log.compiling, ("course", "course-instructor"),
     "==== Compiling course -> course-instructor ====",
     [(compile_log.COMPILING_RE, ("course-instructor",))]),
    (compile_log.compiling, ("Übung", "snapshot~Übung"),
     "==== Compiling Übung -> snapshot~Übung ====",
     [(compile_log.COMPILING_RE, ("snapshot~Übung",))]),
    (compile_log.moving, ("job", "pdf/job.pdf"),
     "==== MOVING: job -> pdf/job.pdf ====",
     [(compile_log.MOVING_RE, ("job",))]),
    (compile_log.moving, ("job", "D:/My course/job.pdf",
                         " (now backgrounded -- retrying for up to 15 min if needed, "
                         "no longer blocking the rest of the queue)"),
     "==== MOVING: job -> D:/My course/job.pdf ==== "
     "(now backgrounded -- retrying for up to 15 min if needed, "
     "no longer blocking the rest of the queue)",
     [(compile_log.MOVING_RE, ("job",))]),
    (compile_log.passed, ("job", Path("job.pdf")),
     "==== PASS: job -> job.pdf ====",
     [(compile_log.PASS_RE, ("job",))]),
    (compile_log.passed, ("job", "D:/My course/Übung.pdf", " (after 12s)"),
     "==== PASS: job -> D:/My course/Übung.pdf (after 12s) ====",
     [(compile_log.PASS_RE, ("job",))]),
    (compile_log.failed, ("job", "see .build/job.log"),
     "*** FAIL: job -- see .build/job.log ***",
     [(compile_log.FAIL_RE, ("job", "see .build/job.log")),
      (compile_log.FAIL_PREFIX_RE, ("job",))]),
    (compile_log.failed, ("job", "stopped by user"),
     "*** FAIL: job -- stopped by user ***",
     [(compile_log.FAIL_RE, ("job", "stopped by user")),
      (compile_log.FAIL_PREFIX_RE, ("job",))]),
    (compile_log.failed, ("job", ""),
     "*** FAIL: job --  ***",
     [(compile_log.FAIL_RE, ("job", "")), (compile_log.FAIL_PREFIX_RE, ("job",))]),
    (compile_log.finished, ("verify~job",),
     "==== Finished: verify~job ====",
     [(compile_log.FINISHED_RE, ("verify~job",))]),
    (compile_log.skipped, ("job",),
     "==== Skipped: job ====",
     [(compile_log.SKIPPED_RE, ("job",))]),
    (compile_log.stopped, (0,),
     "==== Stopped: 0 job(s) skipped ====",
     [(compile_log.STOPPED_ALL_RE, ()), (compile_log.STOPPED_RE, ("Stopped:",))]),
    (compile_log.stopped, (3,),
     "==== Stopped: 3 job(s) skipped ====",
     [(compile_log.STOPPED_ALL_RE, ()), (compile_log.STOPPED_RE, ("Stopped:",))]),
    (compile_log.stop_requested, (),
     "==== Stop requested -- killing current job and skipping the rest ====",
     [(compile_log.STOPPED_RE, ("Stop requested",))]),
    (compile_log.rendering, ("1ab-EN-Title", "preview-job"),
     "==== Rendering 1ab-EN-Title -> preview-job ====",
     [(compile_log.RENDERING_RE, ("1ab-EN-Title", "preview-job"))]),
    (compile_log.render_passed, ("1ab-EN-Title", Path("slide.pdf")),
     "==== PASS: render of 1ab-EN-Title -> slide.pdf ====",
     [(compile_log.RENDER_PASS_RE, ("1ab-EN-Title",))]),
    (compile_log.render_failed, ("1ab-EN-Title", "see log tail below"),
     "*** FAIL: render of 1ab-EN-Title -- see log tail below ***",
     [(compile_log.RENDER_FAIL_RE, ("1ab-EN-Title",))]),
    (compile_log.tikz_rendering, ("diagram-1", "1ab-EN-My slide-current.tex"),
     "==== Rendering tikz illustration diagram-1 (from 1ab-EN-My slide-current.tex) ====",
     [(compile_log.TIKZ_RENDERING_RE, ("diagram-1", "1ab-EN-My slide-current.tex"))]),
    (compile_log.tikz_passed, ("diagram-1", Path("diagram.png")),
     "==== PASS: tikz illustration diagram-1 -> diagram.png ====",
     [(compile_log.TIKZ_PASS_RE, ("diagram-1",))]),
])
def test_status_line_text_and_groups(writer, args, expected, recognizers):
    line = writer(*args)
    assert line.encode("utf-8") == expected.encode("utf-8")
    for regex, groups in recognizers:
        match = regex.match(line)
        assert match is not None
        assert match.groups() == groups


def test_failure_parsers_keep_their_different_prefix_matching():
    assert compile_log.FAIL_RE.match("*** FAIL: job -- reason").groups() == ("job", "reason")
    line = compile_log.failed("job", "first line\nsecond line")
    assert compile_log.FAIL_RE.match(line) is None
    assert compile_log.FAIL_PREFIX_RE.match(line).groups() == ("job",)


def test_stop_request_does_not_match_the_stopped_summary_parser():
    assert compile_log.STOPPED_ALL_RE.match(compile_log.stop_requested()) is None
