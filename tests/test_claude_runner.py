# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running a Claude Code task (ai/claude_runner.py) against the fake `claude` of tests/fake_claude.py: the
command line and environment of the process, the outcomes (done, nothing to change, failed, cancelled), the
repair attempt, the deadline, Stop, and that a changed file is not overwritten."""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import SLIDE_TEXT
from fake_claude import make_fake_claude

from slidemage.ai import claude_runner, tasks as ai_tasks
from slidemage.ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING
from slidemage.ai.tools.base import ToolError
from slidemage.ai.tools.edits import write_text
from slidemage.project import ProjectContext
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
        path=make_fake_claude(tmp_path), ctx=ProjectContext.at(tmp_path),
        script=lambda *replies: monkeypatch.setenv("FAKE_CLAUDE_REPLIES", json.dumps(replies)),
        calls=lambda: [json.loads(line) for line in log.read_text().splitlines()])


def run(claude, task=ai_tasks.TRANSLATE, **options):
    return claude_runner.run_task(claude.ctx, claude.path, task, LF, "THE REQUEST", **options)


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
    assert json.loads(flags[flags.index("--json-schema") + 1]) == ai_tasks.TRANSLATE.schema
    assert flags[flags.index("--system-prompt") + 1] == ai_tasks.TRANSLATE.rules
    assert "ANTHROPIC_API_KEY" not in call["env"] and "CLAUDE_CODE_USE_BEDROCK" not in call["env"]
    assert not Path(call["cwd"]).exists()                      # an empty folder of its own, gone afterwards


def test_model_and_effort_come_from_the_caller(claude):
    claude.script({"answer": FIX})
    run(claude, ai_tasks.FIX_LATEX, model="haiku", effort="low")
    assert claude.calls()[0]["argv"][:5] == ["-p", "--model", "haiku", "--effort", "low"]


def test_nothing_to_change(claude):
    claude.script({"answer": {"edits": []}})
    outcome = run(claude, ai_tasks.FIX_LATEX)
    assert (outcome.status, outcome.text) == (NOTHING, "")


def test_an_answer_that_fails_the_check_is_repaired_once(claude):
    claude.script({"answer": {"edits": [{"before": "nowhere", "after": "x"}]}}, {"answer": FIX})
    outcome = run(claude, ai_tasks.FIX_LATEX)
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
    write_text(Workspace(ProjectContext.at(root)), path, LF, GOOD["body"])
    assert path.read_bytes().decode() == SLIDE_TEXT.replace("Hello", "Hallo").replace(
        "\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-0-0+}")       # its CRLF kept; the slide's "+"


def test_a_result_is_refused_if_the_file_changed(root):
    path = root / SLIDE
    path.write_bytes((SLIDE_TEXT + "typed meanwhile\r\n").encode())
    with pytest.raises(ToolError, match="changed on disk"):
        write_text(Workspace(ProjectContext.at(root)), path, LF, GOOD["body"])
    assert path.read_bytes().decode().endswith("typed meanwhile\r\n") and "Hallo" not in path.read_text()


def test_a_frozen_version_is_never_written_by_a_task(root):
    frozen = root / "slides/abc-EN-Hello-v1-0-0.tex"
    frozen.write_bytes(SLIDE_TEXT.encode())
    with pytest.raises(ToolError, match="frozen version"):
        write_text(Workspace(ProjectContext.at(root)), frozen, LF, GOOD["body"])
    assert frozen.read_bytes().decode() == SLIDE_TEXT


def test_images_go_inline_as_one_stream_json_message(claude, tmp_path):
    claude.script({"answer": {"ok": 1}})
    picture = tmp_path / "chart.png"
    picture.write_bytes(b"\x89PNG fake")
    task = ai_tasks.Task("t", "RULES", {"type": "object", "properties": {"ok": {"type": "integer"}}})
    cancel = threading.Event()
    result = claude_runner.run_json(claude.path, task, "THE REQUEST", "haiku", "low", time.monotonic() + 20, cancel,
                                    (picture,))
    assert (result.answer, result.error) == ({"ok": 1}, "")
    (call,) = claude.calls()
    flags = call["argv"]
    assert flags[flags.index("--input-format") + 1] == "stream-json" and flags[flags.index("--output-format") + 1] == "stream-json"
    assert flags[flags.index("--system-prompt") + 1] == "RULES"
    assert call["request"] == "THE REQUEST"
    assert call["images"] == [{"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"\x89PNG fake").decode()}]


def test_a_request_without_images_stays_plain_text(claude):
    claude.script({"answer": {}})
    claude_runner.run_json(claude.path, ai_tasks.TRANSLATE, "THE REQUEST", "sonnet", "medium", time.monotonic() + 20,
                           threading.Event())
    (call,) = claude.calls()
    assert "--input-format" not in call["argv"] and call["request"] == "THE REQUEST" and call["images"] == []


@pytest.mark.parametrize("message, kind", [
    ("API Error: 429 Too Many Requests", claude_runner.RATE_LIMIT), ("Overloaded", claude_runner.RATE_LIMIT),
    ("Rate limit exceeded", claude_runner.RATE_LIMIT), ("Claude AI usage limit reached|1760000000", claude_runner.USAGE_LIMIT),
    ("Not logged in", ""), ("", "")])
def test_limit_kind_tells_rate_limits_from_the_exhausted_usage(message, kind):
    assert claude_runner.limit_kind(message) == kind
