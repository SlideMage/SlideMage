# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neutral result of an AI task, shared by route implementations."""
from dataclasses import dataclass

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


