# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Model pickers use registered routes and ask before the first cloud request."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QMessageBox, QWidget

from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import CLOUD, TRANSLATION
from slidemage.ui import ai_models


def items(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def test_a_picker_lists_only_the_models_of_the_active_route_and_preselects_the_default(ctx, qapp, fake_routes):
    combo = QComboBox()
    fake_routes.local.choices = ["local-1", "local-2"]
    fake_routes.cloud.choices = ["cloud-1", "cloud-2"]
    ai_profile.set_model_choice(ctx, fake_routes.local.id, TRANSLATION, "local-2")
    ai_profile.set_model_choice(ctx, fake_routes.cloud.id, TRANSLATION, "cloud-2")
    assert ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)")
    assert items(combo) == ["local-1", "local-2"] and combo.currentData() == "local-2"
    ai_profile.set_mode(ctx, CLOUD)
    assert ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)")
    assert items(combo) == ["cloud-1", "cloud-2"] and combo.currentData() == "cloud-2"
    assert combo.currentText() == "CLOUD-2"


def test_a_picker_has_nothing_to_offer_without_models_or_a_route(ctx, qapp, fake_routes):
    combo = QComboBox()
    fake_routes.local.choices = []
    assert not ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)")
    assert not combo.isEnabled() and combo.currentText() == "(none)" and not combo.currentData()
    fake_routes.cloud.choices = []
    ai_profile.set_mode(ctx, CLOUD)
    assert not ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(no models)")
    assert combo.currentText() == "(no models)"


def test_the_fallback_model_is_preselected_only_on_local(ctx, qapp, fake_routes):
    combo = QComboBox()
    fake_routes.local.choices = fake_routes.cloud.choices = ["a", "fallback"]
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", fallback_local="fallback")
    assert combo.currentData() == "a"  # the route's default takes precedence
    # A saved default no longer offered permits the local fallback.
    fake_routes.local.default_choice = lambda task: ""
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", fallback_local="fallback")
    assert combo.currentData() == "fallback"
    ai_profile.set_mode(ctx, CLOUD)
    fake_routes.cloud.default_choice = lambda task: ""
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", fallback_local="fallback")
    assert combo.currentData() == "a"


def test_the_route_of_a_pick_carries_the_picked_model_and_the_active_route(ctx, qapp, monkeypatch, fake_routes):
    combo = QComboBox()
    combo.addItem("fake-2", "fake-2")
    route = ai_models.picked_route(QWidget(), ctx, combo, TRANSLATION, "the text")
    assert (route.route, route.model) == (fake_routes.local.id, "fake-2")
    combo.clear()
    combo.addItem("(no AI models available)", "")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    assert ai_models.picked_route(QWidget(), ctx, combo, TRANSLATION, "the text") is None
    assert "No AI model" in errors[-1]


@pytest.mark.parametrize("route_id", ["", "missing-route"])
def test_missing_route_is_reported_without_retry(ctx, qapp, monkeypatch, route_id):
    monkeypatch.setattr(ai_profile, "active_route", lambda _ctx: route_id)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    combo = QComboBox()
    combo.addItem("model", "model")
    assert ai_models.picked_route(QWidget(), ctx, combo, TRANSLATION, "text") is None
    assert len(errors) == 1 and "not installed" in errors[0]
    assert ai_models.task_route(QWidget(), ctx, TRANSLATION, "text") is None
    assert len(errors) == 2 and "not installed" in errors[1]


def test_first_cloud_request_asks_once_per_project(ctx, qapp, monkeypatch, fake_routes):
    questions = []
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def question(_parent, title, text):
        questions.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)
    ai_profile.set_mode(ctx, CLOUD)
    combo = QComboBox()
    combo.addItem("fake-1", "fake-1")
    parent = QWidget()
    assert ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text") is None
    assert not ai_profile.cloud_seen(ctx)
    route = ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text")
    assert route is not None and "slide text" in questions[1] and route.label in questions[1]
    assert ai_profile.cloud_seen(ctx)
    assert ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text") is not None
    assert len(questions) == 2


def test_a_route_without_a_provider_is_refused_with_its_name(ctx, qapp, monkeypatch, fake_routes):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    monkeypatch.setattr(fake_routes.cloud, "provider", lambda *_: None)
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.mark_cloud_seen(ctx)
    combo = QComboBox()
    combo.addItem("fake-1", "fake-1")
    assert ai_models.provider_from_combo(QWidget(), ctx, combo, TRANSLATION, "the text") is None
    assert fake_routes.cloud.service in errors[-1] and "no other route" in errors[-1]


def test_the_route_of_a_task_without_a_picker_follows_the_active_route(ctx, qapp, monkeypatch, fake_routes):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    parent = QWidget()
    fake_routes.local.problem_text = "Choose a model"
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None
    assert "Choose a model" in errors[-1]
    fake_routes.local.problem_text = ""
    ai_profile.set_model_choice(ctx, fake_routes.local.id, TRANSLATION, "fake-2")
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide").model == "fake-2"
    ai_profile.set_mode(ctx, CLOUD)
    fake_routes.cloud.problem_text = "Missing credentials"
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None
    assert "Missing credentials" in errors[-1]
    fake_routes.cloud.problem_text = ""
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None
