# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What counts as AI work that is running (workspace v6 handoff, section 2: the busy popup of the AI switch).

Every place that starts AI work answers `running_work()` with a `RunningWork` per thing it has under way, built
from its own state, so nothing is registered and the answer cannot go stale. The window gathers them
(`WorkspaceWindow.running_ai_work`): Claude Code tasks and batches (terminal/tasks.py: a task card in Generate, Apply
or Check preview, not one in Review), a chat answer streaming
(chat/view.py), a drafting or translation run of the Images page (pages/images.py), an "Ask AI to fix" check
(ai_fix.py) and, last, the app-wide Ollama slot when none of those accounts for it (an Add slide translation or a
prompt-tuning request, which run inside a sheet of their own).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RunningWork:
    text: str                           # what it is: "Updating a translation · 1y8", "Chat answer"
    route: str                          # the Route.label it captured when it started
    local: bool                         # it holds the Ollama slot
    stop: Callable[[], None] | None     # cancels it; None when it can only be waited for
    note: str = ""                      # a line after the route: what happens to the rest when it is stopped

    @property
    def line(self) -> str:
        """The row of the busy popup's list."""
        return " · ".join(part for part in (self.text, self.route) if part) + (f". {self.note}" if self.note else "")
