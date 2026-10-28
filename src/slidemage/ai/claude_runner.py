# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running one Claude Code task as its own `claude -p` process (Claude Code tasks plan, step 1).

The request goes to stdin, the answer comes back as the structured result of the stream-json events; the
process runs in an empty folder, with the user's own login and without their settings, plugins, tools and
default system prompt (see ISOLATION; the benchmark in docs/CLAUDE_CODE_TASKS_BENCHMARK.md measured them).
run_task() blocks, so the caller runs it on a thread; setting `cancel` (Stop) or running over the deadline
kills the process, and whatever it would have answered is dropped. No Qt.
"""
from __future__ import annotations

import base64
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..processes import no_console_kwargs
from ..project import ProjectContext
from . import tasks as ai_tasks, translation_style
from .claude_launch import clean_environment
from .task_result import CANCELLED, DONE, FAILED, NOTHING, Outcome, judge
from .task_result import NOT_LOGGED_IN, RATE_LIMIT, USAGE_LIMIT, limit_kind  # noqa: F401 -- legacy exports

# The default of Claude Code tasks: Haiku at medium effort, tested by the user as good enough (2026-10-13;
# docs/CLAUDE_CODE_TASKS_BENCHMARK.md measured Sonnet). A text task takes 2-10 s there (the slowest run 13 s),
# so 60 s is a deadline for a service that has gone wrong.
MODEL = "haiku"
EFFORT = "medium"
MODELS = ("sonnet", "haiku", "opus")      # what the tab's picker offers
EFFORTS = ("low", "medium", "high")
TEXT_DEADLINE_S = 60
IMAGE_DEADLINE_S = 120           # per image: it is read as well as described
# What Claude reads as an image, by file suffix (a task with images sends them over stream-json input).
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
# What a task skips: the user's and the project's MCP servers, settings, hooks, plugins and skills. Together
# with --system-prompt (replacing Claude Code's own) and the empty working folder (no CLAUDE.md, no memory).
ISOLATION = ("--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands")




@dataclass
class Run:
    """What one process did."""
    answer: dict | None = None
    error: str = ""
    cancelled: bool = False
    first_s: float | None = None
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def _command(claude: Path, task: ai_tasks.Task, model: str, effort: str, images: bool) -> list[str]:
    return [str(claude), "-p", "--model", model, "--effort", effort, "--tools", "", "--no-session-persistence",
            *(("--input-format", "stream-json") if images else ()),
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(task.schema),
            *ISOLATION, "--system-prompt", task.rules]


def _stdin(request: str, images: Sequence[Path]) -> str:
    """What the process reads: `request`, or with `images` (suffixes of MEDIA_TYPES) one stream-json user
    message, a line holding the images as base64 blocks before the text."""
    if not images:
        return request
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": MEDIA_TYPES[image.suffix.lower()],
                                           "data": base64.b64encode(image.read_bytes()).decode()}}
              for image in images]
    message = {"role": "user", "content": [*blocks, {"type": "text", "text": request}]}
    return json.dumps({"type": "user", "message": message}) + "\n"


def _take_result(run: Run, event: dict) -> None:
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
         cancel: threading.Event) -> Run:
    """Start `argv`, give it `request` and wait for its result event (until time.monotonic() is `deadline`);
    the process is gone when this returns."""
    started = time.monotonic()
    run = Run()
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


def run_json(claude: Path, task: ai_tasks.Task, request: str, model: str, effort: str, deadline: float,
             cancel: threading.Event, images: Sequence[Path] = ()) -> Run:
    """One process for `task` with `request` (and `images`): what it answered, unchecked. `deadline` is a
    time.monotonic() value."""
    empty = Path(tempfile.mkdtemp(prefix="slidemage-claude-task-"))
    try:
        return _run(_command(claude, task, model, effort, bool(images)), _stdin(request, images), empty,
                    clean_environment(claude), deadline, cancel)
    finally:
        _remove_folder(empty)


def _remove_folder(folder: Path, tries: int = 40, delay: float = 0.05) -> None:
    """Delete the process's working folder (empty, unless Claude wrote into it). On Windows it can stay in use for a moment after the
    process ended (a child it started, e.g. the Python behind a launcher .exe, ends a little later), so this
    retries for up to two seconds and then leaves it: an empty folder in the temp directory must not turn
    an answer that arrived into a failed task."""
    for attempt in range(tries):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt + 1 < tries:
                time.sleep(delay)


def run_task(ctx: ProjectContext, claude: Path, task: ai_tasks.Task, captured: str, request: str, model: str = MODEL,
             effort: str = EFFORT, deadline_s: float = TEXT_DEADLINE_S,
             cancel: threading.Event | None = None, span: tuple[int, int] | None = None) -> Outcome:
    """Run `task` on the `captured` text with `request` (ai_tasks.translate_request / fix_request) and
    check the answer; an answer that fails the check gets one repair attempt. The deadline covers both
    attempts. `span`: the task is on that range of `captured` only (ai_tasks.check)."""
    cancel = cancel or threading.Event()
    started = time.monotonic()
    outcome = Outcome(FAILED)
    for attempt in (1, 2):
        run = run_json(claude, task, request, model, effort, started + deadline_s, cancel)
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
        if not (problems := judge(ctx, task, captured, run.answer, outcome, span=span)):
            break
        request = ai_tasks.repair_request(request, run.answer, problems)
    outcome.elapsed_s = time.monotonic() - started
    return outcome



@dataclass
class SlideTranslator:
    """slide_add.translate_body on Claude Code: the Translate task on a slide body, its answer checked. What
    the Add slide sheet holds in place of a provider: it takes no Ollama slot and abort() ends the process."""
    ctx: ProjectContext
    claude: Path
    model: str
    effort: str
    cancel: threading.Event = field(default_factory=threading.Event, init=False)
    is_local = False

    @property
    def label(self) -> str:
        return f"Claude {self.model}"

    def abort(self) -> None:
        self.cancel.set()

    def translate(self, body: str) -> tuple[str, str | None]:
        """(translation, error) of an English slide body into German, with the line ends of `body`."""
        request = ai_tasks.translate_request(body, "EN", "DE", translation_style.de_address(self.ctx),
                                                 translation_style.glossary(self.ctx))
        outcome = run_task(self.ctx, self.claude, ai_tasks.TRANSLATE, body, request, self.model, self.effort,
                           cancel=self.cancel)
        if outcome.status == DONE:
            return (outcome.text.replace("\n", "\r\n") if "\r\n" in body else outcome.text), None
        if outcome.status == NOTHING:
            return body, None
        return "", "Cancelled" if outcome.status == CANCELLED else outcome.message
