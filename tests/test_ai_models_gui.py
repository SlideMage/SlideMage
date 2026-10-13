"""Model pickers (ai_models): only the models of the active route, the default preselection, the Route a pick
makes, and the once-per-project cloud confirmation."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QMessageBox, QWidget

from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import API, CLAUDE_CODE, CLOUD, LOCAL, TRANSLATION
from slidemage.ui import ai_models


def items(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def test_a_picker_lists_only_the_models_of_the_active_route_and_preselects_the_default(ctx, qapp, monkeypatch):
    combo = QComboBox()
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "qwen3")
    ai_profile.set_model_choice(ctx, API, TRANSLATION, "claude-opus-5-5")
    ai_profile.set_model_choice(ctx, CLAUDE_CODE, TRANSLATION, "haiku:high")
    assert ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", local_models=["llama", "qwen3"])
    assert items(combo) == ["llama", "qwen3"] and combo.currentData() == "qwen3"          # no cloud models in Local

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_cloud_conn(ctx, API)
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", local_models=["llama"])
    assert combo.itemText(0) == "claude-sonnet-5-5" and combo.currentData() == "claude-opus-5-5"   # no local ones

    ai_profile.set_cloud_conn(ctx, CLAUDE_CODE)
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", local_models=["llama"])
    assert items(combo) == ai_profile.claude_code_choices() and combo.currentData() == "haiku:high"
    assert combo.currentText() == "Haiku · high"


def test_a_picker_has_nothing_to_offer_without_installed_models_or_a_key(ctx, qapp):
    combo = QComboBox()
    assert not ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", local_models=[])
    assert not combo.isEnabled() and combo.currentText() == "(none)" and not combo.currentData()
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_cloud_conn(ctx, API)
    assert not ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(no API key)")          # no key
    assert combo.currentText() == "(no API key)"


def test_the_fallback_model_is_preselected_only_on_local(ctx, qapp):
    combo = QComboBox()
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", local_models=["a", "fallback"], fallback_local="fallback")
    assert combo.currentData() == "fallback"
    ai_profile.set_mode(ctx, CLOUD)
    ai_models.fill_model_combo(ctx, combo, TRANSLATION, "(none)", fallback_local="fallback")
    assert combo.currentData() == "haiku:medium"


def test_the_route_of_a_pick_carries_the_picked_model_and_the_active_route(ctx, qapp, monkeypatch):
    combo = QComboBox()
    combo.addItem("qwen3", "qwen3")
    route = ai_models.picked_route(QWidget(), ctx, combo, TRANSLATION, "the text")
    assert (route.route, route.model) == (LOCAL, "qwen3")                           # Local needs no confirmation
    combo.clear()
    combo.addItem("(no AI models available)", "")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    assert ai_models.picked_route(QWidget(), ctx, combo, TRANSLATION, "the text") is None
    assert "Choose an Ollama model" in errors[-1]


def test_first_cloud_request_asks_once_per_project(ctx, qapp, monkeypatch):
    questions = []
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def question(_parent, title, text):
        questions.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_cloud_conn(ctx, API)
    combo = QComboBox()
    combo.addItem("claude-sonnet-5-5", "claude-sonnet-5-5")
    parent = QWidget()

    assert ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text") is None  # declined
    assert not ai_profile.cloud_seen(ctx)
    route = ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text")
    assert route is not None and "slide text" in questions[1] and "claude-sonnet-5-5 · API" in questions[1]
    assert ai_profile.cloud_seen(ctx)
    assert ai_models.picked_route(parent, ctx, combo, TRANSLATION, "slide text") is not None
    assert len(questions) == 2  # no third question


def test_a_route_without_a_provider_is_refused_with_its_name(ctx, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.mark_cloud_seen(ctx)
    combo = QComboBox()
    combo.addItem("Haiku · low", "haiku:low")
    assert ai_models.provider_from_combo(QWidget(), ctx, combo, TRANSLATION, "the text") is None
    assert "not available on Cloud · Claude Code" in errors[-1] and "no other route" in errors[-1]


def test_the_route_of_a_task_without_a_picker_follows_the_active_route(ctx, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    parent = QWidget()
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None
    assert "Choose an Ollama model" in errors[-1]
    ai_profile.set_model_choice(ctx, LOCAL, TRANSLATION, "qwen3")
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide").label == "qwen3 · Ollama"
    ai_profile.set_mode(ctx, CLOUD)
    ai_profile.set_cloud_conn(ctx, API)
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None             # no key: nothing else is used
    assert "API key" in errors[-1]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    assert ai_models.task_route(parent, ctx, TRANSLATION, "the slide") is None             # consent declined
