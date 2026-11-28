# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory AI routes for core tests; no service, credentials, process or network.

Register via the ``fake_routes`` fixture. Each route exposes mutable choices,
problem_text, runner and surface_factory so tests can exercise the public route
contract without assuming a particular plugin implementation. Providers record
requests and may be scripted with a reply or an exception.
"""
from slidemage.ai import ai_profile
from slidemage.ai.agent_types import AssistantMessage
from slidemage.ai.providers import Cancelled, ChatReply


class FakeProvider:
    def __init__(self, model="fake-1", *, is_local=True, reply="fake reply"):
        self.model, self.is_local, self.reply = model, is_local, reply
        self.requests = []
        self.aborted = False

    @property
    def label(self):
        return self.model

    def list_models(self):
        return [self.model]

    def abort(self):
        self.aborted = True

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        if self.aborted:
            raise Cancelled("Aborted.")
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, ChatReply) else ChatReply(self.reply)

    def stream_turn(self, system, messages, tools, on_text, *, max_tokens=0):
        reply = self.chat(messages, system=system, tools=tools, max_tokens=max_tokens)
        on_text(reply.text)
        return AssistantMessage(text=reply.text)


class FakeRoute:
    tasks = frozenset(ai_profile.TASKS)

    def __init__(self, is_local=False, id="fake_cloud", service=None):
        self.is_local, self.id = is_local, id
        self.service = service or ("Fake local" if is_local else "Fake cloud")
        self.choices = ["fake-1", "fake-2"]
        self.problem_text = ""
        self.reply = "fake reply"
        self.runner = None
        self.surface_factory = None
        self.providers = []

    def problem(self, ctx, route):
        return self.problem_text

    def model_choices(self, ctx, task):
        return list(self.choices)

    def default_choice(self, task):
        return self.choices[0] if self.choices else ""

    def choice_label(self, choice):
        return choice.upper()

    def split_choice(self, choice):
        return choice, None

    def valid_choice(self, ctx, choice):
        return choice in self.choices

    def work_label(self, route):
        return route.model

    def provider(self, ctx, route):
        provider = FakeProvider(route.model, is_local=self.is_local, reply=self.reply)
        self.providers.append(provider)
        return provider

    def draft_backend(self, ctx, route, cancel=None):
        return None

    translation_backend = draft_backend

    def slide_translator(self, ctx, route):
        return None

    def task_runner(self, ctx, route):
        return self.runner

    def chat_surface(self, *args, **kwargs):
        return self.surface_factory(*args, **kwargs) if self.surface_factory else None

    def settings_section(self):
        return None
