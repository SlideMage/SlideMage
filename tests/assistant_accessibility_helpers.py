# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Throwaway workspace and scripted route for assistant and accessibility tests."""
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from conftest import SLIDE_TEXT, build_window, make_project, wait_until as wait_until
from fake_chat import FakeChatSurface, FakeTaskRunner
from slidemage.ai import ai_profile
from slidemage.ai.task_result import CANCELLED, Outcome
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

LF = SLIDE_TEXT.replace("\r\n", "\n")
BROKEN = LF.replace("\t\\end{itemize}\n", "", 1)


def pump(seconds=0.0):
    end = time.monotonic() + seconds
    QApplication.processEvents()
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


class ScopedChatSurface(FakeChatSurface):
    def __init__(self, app, state, scope, tasks):
        super().__init__(app, state, scope, tasks)
        self.scope = scope


@pytest.fixture
def env(qapp, tmp_path, monkeypatch, fake_routes):
    root = make_project(monkeypatch, tmp_path / "project")
    fake_routes.cloud.surface_factory = ScopedChatSurface
    fake_routes.cloud.runner = FakeTaskRunner(ProjectContext.at(root), {"title": "T"})
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.show()
    window.state.set_mode("source")
    window.state.set_deck(next(d for d in scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    made = SimpleNamespace(root=root, window=window, path=root / "slides/abc-EN-Hello-current.tex", routes=fake_routes)
    pump(0.05)
    yield made
    window.assistant.shutdown()


def slide_file(env):
    return env.window.centre.source.file_for(env.path)


def buttons(env):
    area = env.window.assistant
    return [bubble.label for bubble in area.header.offers(area.scope.current())]


def click(env, label):
    area = env.window.assistant
    area.run_task(next(b for b in area.header.offers(area.scope.current()) if b.label == label))


class Fake:
    def __init__(self, env):
        self.env = env

    def reply(self, script):
        answer, delay = script["answer"], script.get("delay", 0)
        def step(task, captured, request, cancel, span):
            if cancel.wait(delay):
                return Outcome(CANCELLED)
            return answer
        self.env.routes.cloud.runner = FakeTaskRunner(self.env.window.project, step)


@pytest.fixture
def fake(env, monkeypatch):
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(ai_profile.CLOUD)
    monkeypatch.setattr(env.window.assistant.workspace, "render_preview", lambda *args, **kwargs: b"png")
    return Fake(env)
