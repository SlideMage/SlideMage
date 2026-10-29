# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neutral result of an AI task, shared by route implementations."""
from dataclasses import dataclass

from ..project import ProjectContext
from . import tasks as ai_tasks

DONE, NOTHING, FAILED, CANCELLED = "done", "nothing to change", "failed", "cancelled"


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
    note: str = ""                   # the model's remark on its answer (ai_tasks.answer_note)
    measured: object = None          # Make readable: the readability Report of the new text as a draft, or why not (str)


def judge(ctx: ProjectContext, task: ai_tasks.Task, captured: str, answer: dict | None, outcome: Outcome,
          who: str = "Claude", span: tuple[int, int] | None = None) -> list[str]:
    """Settle `outcome` by the model's `answer` (ai_tasks.check): DONE with the new text, or NOTHING when it
    changes nothing; the problems, when the answer is refused (then `outcome` says so, and they go into the repair
    request)."""
    outcome.note = ai_tasks.answer_note(task, answer)
    text, problems = ai_tasks.check(ctx, task, captured, answer, span)
    if problems:
        outcome.message = f"{who}'s answer was refused: " + "; ".join(problems)
    else:
        outcome.status, outcome.text, outcome.message = (NOTHING, "", "") if text == captured else (DONE, text, "")
    return problems



RATE_LIMIT, USAGE_LIMIT = "rate limit", "usage limit"


def limit_kind(message: str) -> str:
    """RATE_LIMIT (try again with fewer processes at once), USAGE_LIMIT (the subscription's window is used up:
    nothing more will run for now) or "" for the error text `message` of a failed task. Matched on the words
    the service uses in its error result."""
    text = message.lower()
    if "usage limit" in text:
        return USAGE_LIMIT
    return RATE_LIMIT if any(word in text for word in ("rate limit", "429", "overloaded", "concurren")) else ""



NOT_LOGGED_IN = "Claude Code is not logged in: run claude in a terminal and sign in with /login."
