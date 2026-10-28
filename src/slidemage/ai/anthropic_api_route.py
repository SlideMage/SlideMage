# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Anthropic API route: Claude over the Messages API with the user's own key, a Cloud route.

AnthropicApiRoute is the AiRoute that ai/routes.py registers at start. It owns what only this route knows: the key
(credentials.py) and the models to offer. Nothing in core outside this module and the Settings page of the key names
the Anthropic API; phase 6 moves the route into the Claude plugin.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..plugin_api import Route
from ..project import ProjectContext
from . import ai_profile, credentials
from .anthropic_provider import AnthropicProvider
from .providers import ANTHROPIC_FALLBACK_MODELS, DEFAULT_ANTHROPIC_MODEL

if TYPE_CHECKING:
    import threading

NO_KEY = "No Anthropic API key yet. Add one under Settings → Cloud."


class AnthropicApiRoute:
    """The Anthropic API as an AiRoute: every task, the standard Claude model until another is chosen, a problem
    while there is no key."""

    id = "anthropic_api"
    service = "Anthropic API"
    is_local = False
    tasks = frozenset(ai_profile.TASKS)

    def problem(self, ctx: ProjectContext, route: Route) -> str:
        return "" if credentials.get_api_key(ctx) is not None else NO_KEY

    def model_choices(self, ctx: ProjectContext, task: str) -> list[str]:
        """None without a key. The static list, so opening a dialog never waits on the network; Settings shows the
        live list."""
        return [] if credentials.get_api_key(ctx) is None else list(ANTHROPIC_FALLBACK_MODELS)

    def default_choice(self, task: str) -> str:
        return DEFAULT_ANTHROPIC_MODEL

    def choice_label(self, choice: str) -> str:
        return choice

    def split_choice(self, choice: str) -> tuple[str, str | None]:
        return choice, None

    def valid_choice(self, ctx: ProjectContext, choice: str) -> bool:
        return bool(choice)

    def work_label(self, route: Route) -> str:
        return f"{route.model or 'no model chosen'} · API"

    def provider(self, ctx: ProjectContext, route: Route) -> AnthropicProvider:
        return AnthropicProvider.for_project(ctx, route.model)

    def draft_backend(self, ctx: ProjectContext, route: Route, cancel: "threading.Event | None" = None) -> None:
        return None     # core wraps provider() in alt_draft.ModelBackend

    def translation_backend(self, ctx: ProjectContext, route: Route, cancel: "threading.Event | None" = None) -> None:
        return None     # core wraps provider() in alt_draft.ModelTranslationBackend

    def slide_translator(self, ctx: ProjectContext, route: Route) -> None:
        return None     # core wraps provider() in slide_add.translate_body

    def task_runner(self, ctx: ProjectContext, route: Route) -> None:
        return None     # core's provider_tasks

    def chat_surface(self, *args: Any, **kwargs: Any) -> None:
        return None     # core's chat view

    def settings_section(self) -> None:
        return None     # the API key is still on Settings' Cloud tab; 3c makes it a section
