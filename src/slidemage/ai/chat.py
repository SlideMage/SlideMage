# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-owned ai.chat: one captured route, per-request cloud consent, one abortable worker.

Used by Exam Forge drafting; also suitable for Slide Atlas's explanations of slide changes.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from .. import app_settings
from ..plugin_api import AiChatRequest, AiChatResult, Route, AiChatError
from ..project import ProjectContext
from ..ui.background import start_detached
from . import ai_profile, resolver, routes
from .providers import Cancelled, ProviderError, RouteUnavailable

log = logging.getLogger(__name__)
def _error(exc: BaseException) -> AiChatError:
    if not isinstance(exc, (ProviderError, AiChatError)):
        log.error("ai.chat failed", exc_info=exc)
    return AiChatError(str(exc) if isinstance(exc, (ProviderError, AiChatError))
                        else f"AI request failed: {type(exc).__name__}: {exc}")


def _request_route(ctx: ProjectContext) -> Route:
    route = ai_profile.resolve(ctx, ai_profile.CHAT)
    # The picker replaces a missing saved cloud connection. A request must instead refuse it.
    stored = ai_profile.route_id(app_settings.get(ctx, ai_profile.CONNECTION_KEY))
    if ai_profile.mode(ctx) == ai_profile.CLOUD and stored and stored != route.route:
        raise RouteUnavailable(f"The selected AI route {stored!r} is unavailable; nothing was sent "
                               "and no other route or model is used.")
    models = ai_profile._stored_models(app_settings.load(ctx)).get(route.route)
    choice = models.get(ai_profile.CHAT) if isinstance(models, dict) else None
    impl = routes.get(route.route)
    if isinstance(choice, str) and choice:
        selected = impl.split_choice(choice) if impl else (choice, None)
        if selected != (route.model, route.effort):
            raise RouteUnavailable(f"The selected AI model {choice!r} is unavailable; nothing was sent "
                                   "and no other model is used.")
    return route


class ChatService:
    def __init__(self, ctx: ProjectContext) -> None:
        self.ctx = ctx

    def available(self) -> bool:
        """Whether the selected Chat route/model can supply a request provider; never raises or sends text.
        A key-related ProviderError still counts: request() will explain the missing or invalid key."""
        try:
            route = _request_route(self.ctx)
            try:
                resolver.request_provider_for(self.ctx, route)
                return True
            except RouteUnavailable:
                return False
            except ProviderError as exc:
                return "key" in str(exc).casefold()
        except (Exception, SystemExit):
            return False

    def request(self, request: AiChatRequest,
                done: Callable[[AiChatResult | None, AiChatError | None], None]) -> Callable[[], None]:
        app = QApplication.instance()
        if app is None or QThread.currentThread() != app.thread():
            raise AiChatError("AI text requests need the UI thread and a running GUI event loop.")
        call = _Call(self.ctx, request, done)
        QTimer.singleShot(0, call.begin)
        return call.cancel


class _Call:
    def __init__(self, ctx: ProjectContext, request: AiChatRequest, done: Callable) -> None:
        self.request, self.done = request, done
        self.provider = self.dialog = self.worker = None
        self.cancelled = self.finished = False
        self.error = None
        try:
            self.route = _request_route(ctx)
            found = routes.get(self.route.route)
            self.is_local = bool(found and found.is_local)
            self.provider = resolver.request_provider_for(ctx, self.route)
        except (Exception, SystemExit) as exc:
            self.error = _error(exc)

    def begin(self) -> None:
        if self.cancelled or self.error is not None:
            self.finish(error=self.error)
            return
        try:
            if not self.is_local:
                from ..ui.dialogs.ai_chat import CloudRequestSheet

                self.dialog = CloudRequestSheet(self.route, self.request, QApplication.activeWindow())
                try:
                    accepted = self.dialog.exec() == self.dialog.DialogCode.Accepted
                finally:
                    self.dialog.deleteLater()
                    self.dialog = None
                if not accepted or self.cancelled:
                    self.finish()
                    return
            self.worker = _Worker(self.provider, self.route, self.request)
            start_detached(self.worker, self.worker_finished)
        except (Exception, SystemExit) as exc:
            self.finish(error=_error(exc))

    def cancel(self) -> None:
        if self.finished or self.cancelled:
            return
        self.cancelled = True
        if self.dialog is not None:
            self.dialog.reject()
        if self.worker is not None:
            try:
                self.provider.abort()
            except (Exception, SystemExit):
                log.exception("ai.chat abort failed")

    def worker_finished(self) -> None:
        try:
            self.finish(self.worker.result, self.worker.error)
        finally:
            self.worker.deleteLater()

    def finish(self, result: AiChatResult | None = None, error: AiChatError | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        try:
            self.done(None if self.cancelled else result, None if self.cancelled else error)
        except (Exception, SystemExit):
            log.exception("ai.chat completion callback raised")


class _Worker(QThread):
    result = error = None

    def __init__(self, provider, route, request: AiChatRequest) -> None:
        super().__init__()
        self.provider, self.route, self.request = provider, route, request

    def run(self) -> None:
        try:
            reply = self.provider.chat([{"role": "user", "content": self.request.text}],
                                       system=self.request.instructions, max_tokens=self.request.max_tokens)
            self.result = AiChatResult(reply.text, self.route, reply.truncated)
        except Cancelled:
            pass
        except (Exception, SystemExit) as exc:
            self.error = _error(exc)
