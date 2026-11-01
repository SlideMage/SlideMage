# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The host-owned ai.chat service: consent, route capture and worker completion through the host."""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton

from conftest import wait_until
from fake_routes import FakeRoute
from slidemage import app_settings
from slidemage.ai import ai_profile, chat, resolver, routes
from slidemage.ai.providers import ChatReply, ProviderError, RouteUnavailable
from slidemage.plugin_api import AiChatRequest, AiChatResult, AiRoute, Route, RouteContext, AiChatError
from slidemage.ui.dialogs.ai_chat import CloudRequestSheet

REQUEST = AiChatRequest("Draft JSON. Preserve <literal> & text.\nNo tools.", "Passage one.\nPassage two.", 512)


def service(ctx):
    return chat.ChatService(ctx)


def ask(svc):
    completed = []
    cancel = svc.request(REQUEST, lambda result, error: completed.append((result, error, threading.get_ident())))
    assert not completed     # even refusal is delivered later
    return cancel, completed


def answer_cloud(button, observations, before_answer=lambda: None):
    def answer():
        sheet = QApplication.activeModalWidget()
        if not isinstance(sheet, CloudRequestSheet):
            observations.append(None)
            return
        observations.append((
            [(view.accessibleName(), view.toPlainText(), view.isReadOnly())
             for view in sheet.findChildren(QPlainTextEdit)], threading.get_ident()))
        before_answer()
        next(b for b in sheet.findChildren(QPushButton) if b.text() == button).click()
    QTimer.singleShot(0, answer)


def test_local_runs_on_worker_and_completes_on_ui_thread(qapp, ctx, fake_routes, monkeypatch):
    ui_thread = threading.get_ident()
    calls = []
    original = fake_routes.local.provider

    def provider(*args):
        calls.append(("provider", threading.get_ident()))
        found = original(*args)
        original_chat = found.chat

        def generate(*args, **kwargs):
            calls.append(("chat", threading.get_ident()))
            return original_chat(*args, **kwargs)
        found.chat = generate
        # Route.is_local, rather than the provider's flag, controls consent.
        found.is_local = False
        return found

    monkeypatch.setattr(fake_routes.local, "provider", provider)
    fake_routes.local.reply = ChatReply("draft", truncated=True)
    svc = service(ctx)
    cancel, completed = ask(svc)
    ai_profile.set_mode(ctx, ai_profile.CLOUD)  # already captured: keep the local route
    wait_until(lambda: completed)
    assert completed == [(AiChatResult("draft", Route(fake_routes.local.id, "chat", "fake-1"), True), None, ui_thread)]
    assert calls[0] == ("provider", ui_thread) and calls[1][0] == "chat" and calls[1][1] != ui_thread
    assert fake_routes.local.providers[0].requests == [
        ([{"role": "user", "content": REQUEST.text}], {"system": REQUEST.instructions, "max_tokens": 512})]
    assert not fake_routes.cloud.providers
    cancel()                # after completion is harmless
    assert not fake_routes.local.providers[0].aborted and len(completed) == 1


def test_cloud_confirms_full_payload_each_time_and_keeps_captured_route(qapp, ctx, fake_routes, monkeypatch):
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    original = fake_routes.cloud.provider

    def provider(*args):
        found = original(*args)
        found.is_local = True  # a misleading provider flag must not bypass cloud consent
        return found

    monkeypatch.setattr(fake_routes.cloud, "provider", provider)
    svc = service(ctx)
    observations, before_send = [], []
    for _ in range(2):
        ai_profile.set_mode(ctx, ai_profile.CLOUD)
        _, completed = ask(svc)

        def change_selection():
            before_send.append([list(p.requests) for p in fake_routes.cloud.providers])
            ai_profile.set_mode(ctx, ai_profile.LOCAL)
            ai_profile.set_model_choice(ctx, fake_routes.cloud.id, "chat", "fake-2")

        answer_cloud("Send", observations, change_selection)
        wait_until(lambda: completed)
        assert completed[0][1:] == (None, threading.get_ident())
        assert completed[0][0].route.route == fake_routes.cloud.id
    assert len(observations) == 2
    assert all(o == ([("Instructions", REQUEST.instructions, True), ("Text", REQUEST.text, True)],
                      threading.get_ident()) for o in observations)
    assert before_send[0] == [[]] and before_send[1][-1] == []
    assert [p.model for p in fake_routes.cloud.providers] == ["fake-1", "fake-2"]
    assert all(p.requests == [([{"role": "user", "content": REQUEST.text}],
                              {"system": REQUEST.instructions, "max_tokens": 512})]
               for p in fake_routes.cloud.providers)
    assert not fake_routes.local.providers


def test_cloud_decline_sends_nothing(qapp, ctx, fake_routes):
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    _, completed = ask(service(ctx))
    observations = []
    answer_cloud("Cancel", observations)
    wait_until(lambda: completed)
    assert completed == [(None, None, threading.get_ident())]
    assert len(observations) == 1 and observations[0] is not None
    assert all(not p.requests for p in fake_routes.cloud.providers)
    assert not fake_routes.local.providers


def test_no_route_or_provider_reports_unavailable_without_fallback(qapp, ctx, monkeypatch):
    svc = service(ctx)
    assert not svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert completed[0][0] is None and isinstance(completed[0][1], AiChatError)
    assert "not installed" in str(completed[0][1])
    other = FakeRoute(id="other_cloud")
    routes.register(other)
    app_settings.set(ctx, ai_profile.CONNECTION_KEY, "missing_cloud")
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    assert not svc.available()  # the installed cloud route cannot replace the missing saved route
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert "missing_cloud" in str(completed[0][1]) and "no other route" in str(completed[0][1])
    assert not other.providers
    ai_profile.set_cloud_conn(ctx, other.id)
    monkeypatch.setattr(other, "provider", lambda *_: None)
    assert not svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert isinstance(completed[0][1], AiChatError) and "not available" in str(completed[0][1])


def test_removed_saved_model_is_refused_without_fallback(qapp, ctx, fake_routes):
    ai_profile.set_model_choice(ctx, fake_routes.local.id, ai_profile.CHAT, "fake-2")
    fake_routes.local.choices.remove("fake-2")
    svc = service(ctx)
    assert ai_profile.resolve(ctx, ai_profile.CHAT).model == "fake-1"
    assert not svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    result, error, _ = completed[0]
    assert result is None and isinstance(error, AiChatError)
    assert "fake-2" in str(error) and "nothing was sent" in str(error) and "no other model" in str(error)
    assert not fake_routes.local.providers and not fake_routes.cloud.providers


def test_request_provider_supports_terminal_route_without_changing_provider_for(qapp, ctx):
    contexts = []

    class TerminalRoute(FakeRoute):
        def provider(self, context, route):
            return None

        def problem(self, context, route):     # as Claude Code: chat is the terminal, for the assistant only
            return "Chat is in the terminal."

        def request_provider(self, context, route):
            contexts.append(context)
            return super().provider(context, route)

    terminal = TerminalRoute(id="terminal", service="Terminal AI")
    routes.register(terminal)
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    svc = service(ctx)
    assert svc.available()
    assert all(not p.requests for p in terminal.providers)
    with pytest.raises(RouteUnavailable, match="not available"):
        resolver.provider_for(ctx, ai_profile.resolve(ctx, ai_profile.CHAT))
    _, completed = ask(svc)
    observations = []
    answer_cloud("Send", observations)
    wait_until(lambda: completed)
    assert completed == [(AiChatResult("fake reply", Route(terminal.id, "chat", "fake-1")),
                          None, threading.get_ident())]
    assert len(observations) == 1 and observations[0] is not None
    assert len(contexts) == 2 and all(isinstance(c, RouteContext) and c.root == ctx.root for c in contexts)
    assert [len(p.requests) for p in terminal.providers] == [0, 1]


def test_inherited_request_provider_defaults_to_provider(qapp, ctx):
    class InheritedRoute(FakeRoute, AiRoute):
        pass

    local = InheritedRoute(is_local=True)
    routes.register(local)
    svc = service(ctx)
    assert svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert completed[0][0].text == "fake reply" and completed[0][1] is None


def test_available_follows_selected_route_and_model(ctx, fake_routes, monkeypatch):
    svc = service(ctx)
    assert svc.available()  # no request_provider method: use provider()
    monkeypatch.setattr(fake_routes.cloud, "provider", lambda *_: None)
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    assert not svc.available()  # the local route can still chat
    monkeypatch.setattr(fake_routes.cloud, "provider", FakeRoute.provider.__get__(fake_routes.cloud))
    ai_profile.set_model_choice(ctx, fake_routes.cloud.id, ai_profile.CHAT, "fake-2")
    assert svc.available()
    assert fake_routes.cloud.providers[-1].model == "fake-2"
    assert all(not p.requests for p in fake_routes.local.providers + fake_routes.cloud.providers)


def test_request_provider_none_does_not_fall_back_to_provider(qapp, ctx, fake_routes, monkeypatch):
    monkeypatch.setattr(fake_routes.local, "request_provider", lambda *_: None, raising=False)
    svc = service(ctx)
    assert not svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert completed[0][0] is None and "not available" in str(completed[0][1])
    assert not fake_routes.local.providers and not fake_routes.cloud.providers


def test_a_route_without_its_own_request_provider_keeps_its_problem_check(qapp, ctx, fake_routes):
    fake_routes.local.problem_text = "This route needs setup."
    svc = service(ctx)
    assert not svc.available()
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert completed[0][0] is None and str(completed[0][1]) == fake_routes.local.problem_text
    assert all(not p.requests for p in fake_routes.local.providers)
    assert not fake_routes.cloud.providers


@pytest.mark.parametrize("error, available", [
    (ProviderError("No API key configured."), True),
    (ProviderError("The provider is unavailable."), False),
    (RouteUnavailable("A key is not enough for this route."), False),
    (ValueError("Broken provider."), False),
    (SystemExit("Plugin exited."), False),
])
def test_available_handles_provider_setup_errors(qapp, ctx, fake_routes, monkeypatch, error, available):
    def fail(*_):
        raise error

    monkeypatch.setattr(fake_routes.local, "request_provider", fail, raising=False)
    svc = service(ctx)
    assert svc.available() is available
    _, completed = ask(svc)
    wait_until(lambda: completed)
    assert completed[0][0] is None and str(error) in str(completed[0][1])
    assert not fake_routes.local.providers and not fake_routes.cloud.providers


@pytest.mark.parametrize("error", [ValueError("Broken profile."), ProviderError("Profile key error."),
                                  SystemExit("Profile exited.")])
def test_available_handles_profile_errors(ctx, monkeypatch, error):
    def fail(*_):
        raise error

    monkeypatch.setattr(ai_profile, "resolve", fail)
    assert not service(ctx).available()


def test_cancel_aborts_only_its_request_and_discards_a_late_reply(qapp, ctx, fake_routes, monkeypatch):
    svc = service(ctx)
    cancel, early = ask(svc)
    cancel()
    cancel()
    wait_until(lambda: early)
    assert early == [(None, None, threading.get_ident())]
    assert not fake_routes.local.providers[0].requests
    started, aborted = threading.Event(), threading.Event()
    original = fake_routes.local.provider

    def provider(*args):
        found = original(*args)

        def generate(*args, **kwargs):
            started.set()
            assert aborted.wait(5), "abort was not called"
            return ChatReply("late reply")

        def abort():
            found.aborted = True
            aborted.set()
        found.chat, found.abort = generate, abort
        return found

    monkeypatch.setattr(fake_routes.local, "provider", provider)
    cancel, completed = ask(svc)
    wait_until(started.is_set)
    cancel()
    cancel()
    wait_until(lambda: completed)
    assert completed == [(None, None, threading.get_ident())] and aborted.is_set()
    assert not fake_routes.local.providers[0].aborted
    monkeypatch.setattr(fake_routes.local, "provider", original)
    _, next_completed = ask(svc)
    wait_until(lambda: next_completed)
    assert next_completed[0][0].text == "fake reply" and next_completed[0][1] is None


def test_provider_error_is_service_error_and_never_retries_another_route(qapp, ctx, fake_routes):
    fake_routes.local.reply = ProviderError("The provider refused this request.")
    other = FakeRoute(is_local=True, id="other_local")
    routes.register(other)
    _, completed = ask(service(ctx))
    wait_until(lambda: completed)
    assert completed[0][0] is None and type(completed[0][1]) is AiChatError
    assert str(completed[0][1]) == "The provider refused this request."
    assert completed[0][2] == threading.get_ident()
    assert completed[0][1].__cause__ is None and completed[0][1].__context__ is None
    assert len(fake_routes.local.providers[0].requests) == 1
    assert not other.providers and not fake_routes.cloud.providers


def test_plugin_host_ai_chat(qapp, ctx, fake_routes):
    from pathlib import Path

    from slidemage.plugins.host import PluginHost
    from slidemage.plugins.manifest import read_manifest

    manifest = read_manifest(Path(__file__).parent / "fixtures" / "plugins" / "hello")
    ai = PluginHost(manifest, ctx).ai_chat()
    assert isinstance(ai, chat.ChatService)
    assert ai.ctx is ctx
    assert ai.available()
    fake_routes.local.reply = ChatReply("host reply")
    _, completed = ask(ai)
    wait_until(lambda: completed)
    assert completed[0][0].text == "host reply"
    assert completed[0][1] is None
