"""Running a Claude Code task (ai/claude_runner.py) against the fake `claude` of tests/fake_claude.py: the
command line and environment of the process, the outcomes (done, nothing to change, failed, cancelled), the
repair attempt, the deadline, Stop, and that a changed file is not overwritten."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import SLIDE_TEXT
from fake_claude import make_fake_claude

from slidemage.ai import claude_runner, claude_tasks
from slidemage.ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING
from slidemage.ai.workspace import Workspace

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")
GOOD = {"body": LF.replace("Hello", "Hallo")}
FIX = {"edits": [{"before": "First point", "after": "1st point"}]}


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """The fake `claude`; `script(*replies)` sets its answers, `calls()` reads what it was started with."""
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-reach-claude")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    return SimpleNamespace(
        path=make_fake_claude(tmp_path),
        script=lambda *replies: monkeypatch.setenv("FAKE_CLAUDE_REPLIES", json.dumps(replies)),
        calls=lambda: [json.loads(line) for line in log.read_text().splitlines()])


def run(claude, task=claude_tasks.TRANSLATE, **options):
    return claude_runner.run_task(claude.path, task, LF, "THE REQUEST", **options)


def test_a_task_runs_in_isolation_and_returns_the_new_text(claude):
    claude.script({"answer": GOOD})
    outcome = run(claude)
    assert (outcome.status, outcome.text, outcome.message, outcome.attempts) == (DONE, GOOD["body"], "", 1)
    assert (outcome.turns, outcome.tokens_in, outcome.tokens_out) == (2, 103, 7)
    assert outcome.first_s is not None and 0 <= outcome.first_s <= outcome.elapsed_s
    (call,) = claude.calls()
    flags = call["argv"]
    assert call["request"] == "THE REQUEST"
    assert flags[:5] == ["-p", "--model", claude_runner.MODEL, "--effort", claude_runner.EFFORT]
    assert flags[flags.index("--tools") + 1] == "" and flags[flags.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--verbose"} <= set(flags)
    assert flags[flags.index("--output-format") + 1] == "stream-json"
    assert json.loads(flags[flags.index("--json-schema") + 1]) == claude_tasks.TRANSLATE.schema
    assert flags[flags.index("--system-prompt") + 1] == claude_tasks.TRANSLATE.rules
    assert "ANTHROPIC_API_KEY" not in call["env"] and "CLAUDE_CODE_USE_BEDROCK" not in call["env"]
    assert not Path(call["cwd"]).exists()                      # an empty folder of its own, gone afterwards


def test_model_and_effort_come_from_the_caller(claude):
    claude.script({"answer": FIX})
    run(claude, claude_tasks.FIX_LATEX, model="haiku", effort="low")
    assert claude.calls()[0]["argv"][:5] == ["-p", "--model", "haiku", "--effort", "low"]


def test_nothing_to_change(claude):
    claude.script({"answer": {"edits": []}})
    outcome = run(claude, claude_tasks.FIX_LATEX)
    assert (outcome.status, outcome.text) == (NOTHING, "")


def test_an_answer_that_fails_the_check_is_repaired_once(claude):
    claude.script({"answer": {"edits": [{"before": "nowhere", "after": "x"}]}}, {"answer": FIX})
    outcome = run(claude, claude_tasks.FIX_LATEX)
    assert (outcome.status, outcome.attempts, outcome.text) == (DONE, 2, LF.replace("First point", "1st point"))
    first, second = claude.calls()
    assert first["request"] == "THE REQUEST"
    assert second["request"].startswith("THE REQUEST") and "does not occur" in second["request"]
    assert (outcome.turns, outcome.tokens_out) == (4, 14)      # both processes counted


def test_bad_output_twice_is_a_failure_after_one_repair(claude):
    claude.script({"answer": {"wrong": 1}})
    outcome = run(claude)
    assert outcome.status == FAILED and outcome.attempts == 2 and len(claude.calls()) == 2
    assert outcome.message.startswith("Claude's answer was refused:") and "must be" in outcome.message


def test_an_answer_that_is_no_structured_result_is_refused(claude):
    claude.script({})
    outcome = run(claude)
    assert (outcome.status, outcome.message, outcome.attempts) == (FAILED, "Claude gave no structured answer.", 1)


def test_a_missing_login_is_reported_and_not_repeated(claude):
    claude.script({"error": "Not logged in · Please run /login"})
    outcome = run(claude)
    assert (outcome.status, outcome.message, outcome.attempts) == (FAILED, claude_runner.NOT_LOGGED_IN, 1)


def test_a_process_that_dies_is_a_failure_with_what_it_printed(claude):
    claude.script({"exit": 2})
    outcome = run(claude)
    assert outcome.status == FAILED and "boom" in outcome.message and outcome.attempts == 1


def test_the_deadline_ends_the_process(claude, tmp_path):
    claude.script({"answer": GOOD, "delay": 5, "marker": str(tmp_path / "late")})
    started = time.monotonic()
    outcome = run(claude, deadline_s=0.5)
    assert (outcome.status, outcome.message) == (FAILED, "Claude did not answer in time.")
    assert time.monotonic() - started < 3 and not (tmp_path / "late").exists()


def test_stop_cancels_and_a_late_result_is_dropped(claude, tmp_path):
    claude.script({"answer": GOOD, "delay": 1.2, "marker": str(tmp_path / "late")})
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    outcome = run(claude, cancel=cancel)
    assert (outcome.status, outcome.text, outcome.message) == (CANCELLED, "", "")
    time.sleep(1.5)                                            # the result would have been there by now
    assert not (tmp_path / "late").exists()


def test_a_result_is_applied_if_the_file_is_as_captured(root):
    path = root / SLIDE
    assert claude_runner.apply_result(Workspace(root), path, LF, GOOD["body"]) is None
    assert path.read_bytes().decode() == SLIDE_TEXT.replace("Hello", "Hallo")        # its CRLF kept


def test_a_result_is_refused_if_the_file_changed(root):
    path = root / SLIDE
    path.write_bytes((SLIDE_TEXT + "typed meanwhile\r\n").encode())
    problem = claude_runner.apply_result(Workspace(root), path, LF, GOOD["body"])
    assert problem and "changed on disk" in problem
    assert path.read_bytes().decode().endswith("typed meanwhile\r\n") and "Hallo" not in path.read_text()
