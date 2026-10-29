# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A Claude Code task (ai_tasks.Task) on a Local or API provider: the same rules, request, answer shape and check
as claude_runner.run_task, with the provider's chat in place of the `claude -p` process.

The rules go in as the system prompt and the schema is asked for as JSON (Ollama's `format`, the API's system
prompt); the reply is parsed, then ai_tasks.check decides as it does for Claude. A reply that is not JSON or does
not pass the check gets one repair round with the refused answer and the reasons, like run_task's. Blocking: the
caller runs it on a thread, and abort() on the provider ends it. No Qt.
"""
from __future__ import annotations

import threading
import time

from ..project import ProjectContext
from . import tasks as ai_tasks
from .task_result import CANCELLED, FAILED, Outcome, judge
from .providers import Cancelled, ChatProvider, ProviderError, parse_json_object

NUM_CTX = 16384         # Ollama's context window: a slide, its findings and the answer fit with room to spare
MAX_TOKENS = 8192       # the whole new slide source comes back
TIMEOUT_S = 600.0


def run_task(ctx: ProjectContext, provider: ChatProvider, task: ai_tasks.Task, captured: str, request: str,
             cancel: threading.Event | None = None, span: tuple[int, int] | None = None) -> Outcome:
    """Run `task` on the `captured` text (or its `span`, ai_tasks.check) with `request` on `provider` and check the
    answer."""
    cancel = cancel or threading.Event()
    started = time.monotonic()
    outcome = Outcome(FAILED)
    for attempt in (1, 2):
        outcome.attempts = attempt
        try:
            reply = provider.chat(
                [{"role": "user", "content": request}], system=task.rules, schema=task.schema, max_tokens=MAX_TOKENS,
                timeout=TIMEOUT_S, num_ctx=NUM_CTX)
        except Cancelled:
            outcome.status, outcome.message = CANCELLED, ""
            break
        except ProviderError as exc:
            outcome.message = str(exc)
            break
        if cancel.is_set():
            outcome.status, outcome.message = CANCELLED, ""
            break
        answer = parse_json_object(reply.text) or parse_json_object(reply.thinking)
        if answer is None:
            problems = ["the answer was cut off" if reply.truncated else "the answer was not a JSON object"]
            outcome.message = f"The model's answer was refused: {problems[0]}."
            if reply.truncated:
                break
        elif not (problems := judge(ctx, task, captured, answer, outcome, "The model", span)):
            break
        request = ai_tasks.repair_request(request, answer, problems)
    outcome.elapsed_s = time.monotonic() - started
    return outcome
