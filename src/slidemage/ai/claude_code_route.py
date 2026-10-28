# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude Code route: the user's own `claude`, a Cloud route. Its tasks run as one-shot `claude -p` processes
(claude_runner, claude_images) and its chat is a terminal (claude_launch starts it); it has no ChatProvider.

ClaudeCodeRoute is the AiRoute that ai/routes.py registers at start. Nothing in core outside this module (and the
UI that still builds the terminal and the task bubbles, 3b) names Claude Code; phase 6 moves the route into the
Claude plugin.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..plugin_api import Route
from ..project import ProjectContext
from . import ai_profile, claude_launch, claude_runner
from .claude_images import ClaudeDraftBackend, ClaudeTranslationBackend
from .claude_runner import Outcome, SlideTranslator
from .providers import RouteUnavailable

NO_CLAUDE = "Claude Code is not installed on this computer, so nothing was sent and no other model is used."
CHAT_IN_TERMINAL = ("On Cloud · Claude Code the conversation is the terminal in the assistant; the chat "
                    "with Ollama or the API is not available on this route.")


def claude_path() -> Path:
    """The `claude` executable, or RouteUnavailable(NO_CLAUDE)."""
    claude = claude_launch.find_claude()
    if claude is None:
        raise RouteUnavailable(NO_CLAUDE)
    return claude


class ClaudeCodeRoute:
    """Claude Code as an AiRoute. A choice is "<model>:<effort>" ("haiku:medium"); its tasks default to the
    benchmarked setup, and its chat inherits Claude Code's own default until one is chosen."""

    id = "claude_code"
    service = "Claude Code"
    is_local = False
    tasks = frozenset(ai_profile.TASKS)

    def problem(self, ctx: ProjectContext, route: Route) -> str:
        return CHAT_IN_TERMINAL if route.task == ai_profile.CHAT else ""

    def model_choices(self, ctx: ProjectContext, task: str) -> list[str]:
        return [f"{model}:{effort}" for model in claude_runner.MODELS for effort in claude_runner.EFFORTS]

    def default_choice(self, task: str) -> str:
        return "" if task == ai_profile.CHAT else f"{claude_runner.MODEL}:{claude_runner.EFFORT}"

    def choice_label(self, choice: str) -> str:
        """"Sonnet · medium"."""
        model, _, effort = choice.partition(":")
        return f"{model.capitalize()} · {effort}"

    def split_choice(self, choice: str) -> tuple[str, str | None]:
        model, _, effort = choice.partition(":")
        return model, effort or None

    def valid_choice(self, ctx: ProjectContext, choice: str) -> bool:
        return choice in self.model_choices(ctx, ai_profile.CHAT)

    def work_label(self, route: Route) -> str:
        return " · ".join(["Claude Code", *([route.model.capitalize(), f"effort {route.effort}"] if route.model
                                             else ["terminal"])])

    def provider(self, ctx: ProjectContext, route: Route) -> None:
        return None     # no ChatProvider: the chat is the terminal, the tasks run through task_runner

    def draft_backend(self, ctx: ProjectContext, route: Route, cancel: threading.Event | None = None) -> Any:
        return ClaudeDraftBackend(ctx, claude_path(), route.model, route.effort, cancel or threading.Event())

    def translation_backend(self, ctx: ProjectContext, route: Route, cancel: threading.Event | None = None) -> Any:
        return ClaudeTranslationBackend(ctx, claude_path(), route.model, route.effort, cancel or threading.Event())

    def slide_translator(self, ctx: ProjectContext, route: Route) -> SlideTranslator:
        return SlideTranslator(ctx, claude_path(), route.model, route.effort)

    def task_runner(self, ctx: ProjectContext, route: Route) -> Callable[..., Outcome]:
        claude = claude_path()

        def run(task, captured: str, request: str, cancel: threading.Event | None = None,
                span: tuple[int, int] | None = None) -> Outcome:
            return claude_runner.run_task(ctx, claude, task, captured, request, route.model, route.effort,
                                          cancel=cancel, span=span)
        return run

    def chat_surface(self, *args: Any, **kwargs: Any) -> Any:
        """The terminal view (3b/3d reshape its construction; imported here so core's AI layer never imports the UI)."""
        from ..ui.workspace.chat.plugin_surface import ChatSurfaceContext
        return ChatSurfaceContext(*args, **kwargs)._builtin_surface()

    def chat_surface_v2(self, context):
        return context._builtin_surface()

    def settings_section(self):
        from ..ui.dialogs.settings_ai import build_claude_code_section
        return build_claude_code_section
