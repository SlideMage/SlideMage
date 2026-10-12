"""Running one Claude Code task as its own `claude -p` process (Claude Code tasks plan, step 1).

The request goes to stdin, the answer comes back as the structured result of the stream-json events; the
process runs in an empty folder, with the user's own login and without their settings, plugins, tools and
default system prompt (see ISOLATION; the benchmark in docs/CLAUDE_CODE_TASKS_BENCHMARK.md measured them).
run_task() blocks, so the caller runs it on a thread; setting `cancel` (Stop) or running over the deadline
kills the process, and whatever it would have answered is dropped. No Qt.
"""
from __future__ import annotations

import json
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..processes import no_console_kwargs
from . import claude_tasks
from .claude_launch import clean_environment
from .tools.base import ToolError
from .tools.edits import write_text
from .workspace import Workspace

# Chosen by docs/CLAUDE_CODE_TASKS_BENCHMARK.md: the fastest and best setup measured. A text task takes
# 2-10 s there (the slowest run 13 s), so 60 s is a deadline for a service that has gone wrong.
MODEL = "sonnet"
EFFORT = "medium"
TEXT_DEADLINE_S = 60
# What a task skips: the user's and the project's MCP servers, settings, hooks, plugins and skills. Together
# with --system-prompt (replacing Claude Code's own) and the empty working folder (no CLAUDE.md, no memory).
ISOLATION = ("--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands")

DONE, NOTHING, FAILED, CANCELLED = "done", "nothing to change", "failed", "cancelled"
NOT_LOGGED_IN = "Claude Code is not logged in: run claude in a terminal and sign in with /login."


@dataclass
class Outcome:
    status: str                      # DONE, NOTHING, FAILED or CANCELLED
    text: str = ""                   # the new text, for DONE
    message: str = ""                # why, for FAILED
    attempts: int = 0                # processes started: 2 when the first answer needed a repair
    first_s: float | None = None     # until the first answer event of the first process
    elapsed_s: float = 0.0           # until the outcome is known
    turns: int = 0
    tokens_in: int = 0               # input tokens, cached ones included
    tokens_out: int = 0


@dataclass
class _Run:
    """What one process did."""
    answer: dict | None = None
    error: str = ""
    cancelled: bool = False
    first_s: float | None = None
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def _command(claude: Path, task: claude_tasks.Task, model: str, effort: str) -> list[str]:
    return [str(claude), "-p", "--model", model, "--effort", effort, "--tools", "", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(task.schema),
            *ISOLATION, "--system-prompt", task.rules]


def _take_result(run: _Run, event: dict) -> None:
    """Note the answer, the error and the usage of a stream-json result event in `run`."""
    usage = event.get("usage", {})
    run.turns = event.get("num_turns", 0)
    run.tokens_in = sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens"))
    run.tokens_out = usage.get("output_tokens", 0)
    if event.get("is_error"):
        reason = str(event.get("result", ""))
        run.error = NOT_LOGGED_IN if "Not logged in" in reason else reason or "Claude reported an error."
    elif isinstance(event.get("structured_output"), dict):
        run.answer = event["structured_output"]
    else:
        run.error = "Claude gave no structured answer."


def _read_lines(stream, lines: queue.Queue) -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


def _run(argv: list[str], request: str, cwd: Path, env: dict[str, str], deadline: float,
         cancel: threading.Event) -> _Run:
    """Start `argv`, give it `request` and wait for its result event (until time.monotonic() is `deadline`);
    the process is gone when this returns."""
    started = time.monotonic()
    run = _Run()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=cwd, env=env, text=True, encoding="utf-8", **no_console_kwargs())
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_read_lines, args=(proc.stdout, lines), daemon=True).start()
    noise: list[str] = []             # what the process printed that is no event: its error message
    try:
        try:
            proc.stdin.write(request)
            proc.stdin.close()
        except OSError:
            pass                      # it ended already; its output says why
        while True:
            if cancel.is_set():
                run.cancelled = True
                break
            if time.monotonic() > deadline:
                run.error = "Claude did not answer in time."
                break
            try:
                line = lines.get(timeout=0.05)
            except queue.Empty:
                continue
            if line is None:
                run.error = " ".join(noise)[-300:] or f"Claude ended without an answer (exit code {proc.wait()})."
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                noise.append(line.strip())
                continue
            if event.get("type") == "assistant" and run.first_s is None:
                run.first_s = time.monotonic() - started
            if event.get("type") == "result":
                _take_result(run, event)
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    return run


def run_task(claude: Path, task: claude_tasks.Task, captured: str, request: str, model: str = MODEL,
             effort: str = EFFORT, deadline_s: float = TEXT_DEADLINE_S,
             cancel: threading.Event | None = None) -> Outcome:
    """Run `task` on the `captured` text with `request` (claude_tasks.translate_request / fix_request) and
    check the answer; an answer that fails the check gets one repair attempt. The deadline covers both
    attempts."""
    cancel = cancel or threading.Event()
    started = time.monotonic()
    argv = _command(claude, task, model, effort)
    env = clean_environment(claude)
    outcome = Outcome(FAILED)
    with tempfile.TemporaryDirectory(prefix="slidemage-claude-task-") as empty:
        for attempt in (1, 2):
            run = _run(argv, request, Path(empty), env, started + deadline_s, cancel)
            outcome.attempts = attempt
            outcome.turns += run.turns
            outcome.tokens_in += run.tokens_in
            outcome.tokens_out += run.tokens_out
            if attempt == 1:
                outcome.first_s = run.first_s
            if run.cancelled:
                outcome.status, outcome.message = CANCELLED, ""
                break
            if run.error:
                outcome.message = run.error
                break
            text, problems = claude_tasks.check(task, captured, run.answer)
            if not problems:
                outcome.status, outcome.text, outcome.message = (NOTHING, "", "") if text == captured else (DONE, text, "")
                break
            outcome.message = "Claude's answer was refused: " + "; ".join(problems)
            request = claude_tasks.repair_request(request, run.answer, problems)
    outcome.elapsed_s = time.monotonic() - started
    return outcome


def apply_result(workspace: Workspace, path: Path, captured: str, text: str) -> str | None:
    """Put `text` in place of `captured` in `path` unless the file has changed since `captured` was read.
    None when done, else why not (nothing is written)."""
    try:
        write_text(workspace, path, captured, text)
    except ToolError as exc:
        return str(exc)
    return None
