# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Window and scripted route support for the selection, readability and image batch tests."""
from types import SimpleNamespace
import time

import pytest
from PySide6.QtWidgets import QApplication

from conftest import SLIDE_TEXT, build_window, make_project
from fake_chat import FakeChatSurface, FakeTaskRunner
from slidemage.ai import ai_profile
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.project import ProjectContext
from slidemage.ui.workspace import task_card_model as model

LF = SLIDE_TEXT.replace("\r\n", "\n")


def pump(seconds=0.05):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        QApplication.processEvents()
        time.sleep(0.005)


def wait_until(predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Timed out waiting for UI state"


class Fake:
    def __init__(self, env, monkeypatch, routes):
        self.env, self.monkeypatch, self.routes = env, monkeypatch, routes
        self.runner = FakeTaskRunner(env.window.project)
        routes.local.runner = routes.cloud.runner = self.runner
        self.renders, self.error = [], ""

    def rendered(self, *args, **kwargs):
        self.renders.append(args)
        if self.error:
            raise RuntimeError(self.error)
        return b"png"

    def reply(self, *replies):
        self.runner.steps = [reply["answer"] for reply in replies]
        # Calls remain available across repeated runs; restart the script at the next call.
        self.runner.steps = [self.runner.steps[0]] * len(self.runner.calls) + self.runner.steps

    def calls(self):
        return [{"request": call[2]} for call in self.runner.calls]


@pytest.fixture
def fake(qapp, tmp_path, monkeypatch, fake_routes):
    root = make_project(monkeypatch, tmp_path / "project")
    ctx = ProjectContext.at(root)
    fake_routes.local.surface_factory = fake_routes.cloud.surface_factory = FakeChatSurface
    ai_profile.set_cloud_conn(ctx, fake_routes.cloud.id)
    ai_profile.set_mode(ctx, ai_profile.CLOUD)
    ai_profile.mark_cloud_seen(ctx)
    window = build_window(monkeypatch, ctx)
    window.resize(1700, 800)
    window.show()
    window.state.set_mode("source")
    path = root / "slides" / "abc-EN-Hello-current.tex"
    window.centre.open_file(path)
    qapp.processEvents()
    env = SimpleNamespace(root=root, path=path, window=window)
    made = Fake(env, monkeypatch, fake_routes)
    window.assistant.chat.session.set_mode(EDIT_AUTO)
    monkeypatch.setattr(window.assistant.workspace, "render_preview", made.rendered)
    return made


@pytest.fixture
def ctx(fake):
    return fake.env.window.project


def slide_file(env):
    return env.window.centre.source.file_for(env.path)


def buttons(env):
    area = env.window.assistant
    return [bubble.label for bubble in area.header.offers(area.scope.current())]


def click(env, label):
    area = env.window.assistant
    area.run_task(next(b for b in area.header.offers(area.scope.current()) if b.label == label))


def settled(env):
    wait_until(lambda: not env.window.assistant.tasks.busy)
    pump()
    card = env.window.assistant.tasks.card
    return model.state_text(card) if card else env.window.assistant.task_row.status.text()


def card(env):
    return env.window.assistant.tasks.card


def phase_is(env, phase):
    return lambda: card(env) is not None and card(env).phase == phase


def shown_buttons(env):
    layout = env.window.assistant.task_card._buttons
    return [layout.itemAt(i).widget().text() for i in range(layout.count())]


def state(env):
    return env.window.assistant.task_card.state.text()
