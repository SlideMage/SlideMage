# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A Claude Code task on a Local or API provider (ai/provider_tasks.py): the rules and the schema go to the provider's chat, the
reply is parsed as JSON and checked as a Claude answer is, a refused or non-JSON reply gets one repair round, and an
abort or an error ends it. A stand-in provider answers; no model is used."""
from __future__ import annotations

import json
import threading

import pytest
from conftest import SLIDE_TEXT

from slidemage.ai import task_result, tasks as ai_tasks, provider_tasks
from slidemage.ai.providers import Cancelled, ChatReply, ProviderError
from slidemage.project import ProjectContext

LF = SLIDE_TEXT.replace("\r\n", "\n")
BIGGER = LF.replace("\\begin{itemize}", "\\begin{itemize}\\small", 1)
REQUEST = "Make this slide readable.\n<slide>\n" + LF + "\n</slide>"


class Provider:
    """Answers each chat() with the next of `replies` (a ChatReply, a string, or an exception to raise)."""

    model, is_local, label = "offline", True, "offline"

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, ChatReply) else ChatReply(reply)

    def abort(self):
        pass


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)


def run(ctx, provider, cancel=None):
    return provider_tasks.run_task(ctx, provider, ai_tasks.READABLE, LF, REQUEST, cancel)


def test_the_rules_the_schema_and_the_request_go_to_the_provider_and_a_good_answer_is_the_result(ctx):
    provider = Provider('{"body": %s, "note": "Split after the list."}' % json.dumps(BIGGER))
    outcome = run(ctx, provider)
    assert (outcome.status, outcome.text, outcome.attempts, outcome.note) == (task_result.DONE, BIGGER, 1, "Split after the list.")
    (messages, kwargs), = provider.calls
    assert messages == [{"role": "user", "content": REQUEST}]
    assert kwargs["system"] == ai_tasks.READABLE.rules and kwargs["schema"] == ai_tasks.READABLE.schema
    assert kwargs["max_tokens"] == provider_tasks.MAX_TOKENS and kwargs["num_ctx"] == provider_tasks.NUM_CTX


def test_a_reply_in_a_fence_or_in_the_thinking_field_is_read(ctx):
    fenced = '```json\n{"body": %s}\n```' % json.dumps(BIGGER)
    assert run(ctx, Provider(fenced)).text == BIGGER
    assert run(ctx, Provider(ChatReply("", thinking='{"body": %s}' % json.dumps(BIGGER)))).text == BIGGER


def test_an_answer_that_changes_nothing_is_nothing_to_change_with_the_models_note(ctx):
    outcome = run(ctx, Provider('{"body": %s, "note": "Too much text: split."}' % json.dumps(LF)))
    assert (outcome.status, outcome.text, outcome.note) == (task_result.NOTHING, "", "Too much text: split.")


def test_a_refused_answer_gets_one_repair_round_with_the_reasons(ctx):
    broken = json.dumps(LF.replace("1-0-0", "2-0-0"))
    provider = Provider('{"body": %s}' % broken, '{"body": %s}' % json.dumps(BIGGER))
    outcome = run(ctx, provider)
    assert (outcome.status, outcome.text, outcome.attempts) == (task_result.DONE, BIGGER, 2)
    repair = provider.calls[1][0][0]["content"]
    assert repair.startswith(REQUEST) and "Your previous answer was refused" in repair and "protected part" in repair
    twice = run(ctx, Provider('{"body": %s}' % broken, '{"body": %s}' % broken))
    assert twice.status == task_result.FAILED and twice.attempts == 2
    assert twice.message.startswith("The model's answer was refused: ") and "protected part" in twice.message


def test_a_reply_that_is_not_json_is_repaired_once_then_fails(ctx):
    provider = Provider("Sure! Here is the slide: \\begin{frame}", '{"body": %s}' % json.dumps(BIGGER))
    outcome = run(ctx, provider)
    assert outcome.status == task_result.DONE and outcome.attempts == 2
    assert "was not a JSON object" in provider.calls[1][0][0]["content"]
    bad = run(ctx, Provider("not json", ""))
    assert bad.status == task_result.FAILED and bad.attempts == 2
    assert bad.message == "The model's answer was refused: the answer was not a JSON object."


def test_a_reply_cut_off_at_the_token_limit_fails_without_a_second_try(ctx):
    provider = Provider(ChatReply('{"body": "\\begin{', truncated=True))
    outcome = run(ctx, provider)
    assert outcome.status == task_result.FAILED and outcome.attempts == 1 and "cut off" in outcome.message
    assert len(provider.calls) == 1


def test_a_provider_error_is_the_message_and_an_abort_is_a_cancel(ctx):
    outcome = run(ctx, Provider(ProviderError("Ollama is not reachable.")))
    assert (outcome.status, outcome.message, outcome.attempts) == (task_result.FAILED, "Ollama is not reachable.", 1)
    assert run(ctx, Provider(Cancelled("stopped"))).status == task_result.CANCELLED
    cancel = threading.Event()
    cancel.set()
    assert run(ctx, Provider('{"body": "x"}'), cancel).status == task_result.CANCELLED
