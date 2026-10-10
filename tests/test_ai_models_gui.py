"""Model pickers (qt_ai_models): local and cloud entries, the default
preselection, and the once-per-project cloud confirmation."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QWidget

from slidemage import app_settings, qt_ai_models
from slidemage.ai import resolver


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    monkeypatch.setattr(resolver, "PROJECT_ROOT", tmp_path)


def test_picker_lists_cloud_models_only_with_a_key_and_preselects_the_default(
        settings, monkeypatch):
    combo = QComboBox()
    app_settings.set("translation_model", "qwen3")        # old bare name still preselects
    assert qt_ai_models.fill_model_combo(combo, "translation", ["llama", "qwen3"], "(none)")
    assert [combo.itemData(i) for i in range(combo.count())] == ["ollama:llama", "ollama:qwen3"]
    assert combo.currentData() == "ollama:qwen3"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    qt_ai_models.fill_model_combo(combo, "translation", ["llama"], "(none)")
    assert combo.itemText(1) == "claude-sonnet-5-5 (cloud)"
    assert combo.itemData(1) == "anthropic:claude-sonnet-5-5"

    resolver.set_global_local_only(True)
    qt_ai_models.fill_model_combo(combo, "translation", [], "(none)")
    assert not combo.isEnabled() and combo.currentText() == "(none)"
    assert not combo.currentData()


def test_first_cloud_request_asks_once_per_project(settings, monkeypatch):
    questions = []
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def question(_parent, title, text):
        questions.append(text)
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    combo = QComboBox()
    combo.addItem("claude-sonnet-5-5 (cloud)", "anthropic:claude-sonnet-5-5")
    parent = QWidget()

    assert qt_ai_models.provider_from_combo(parent, combo, "slide text") is None  # declined
    assert not resolver.cloud_consent_given()
    provider = qt_ai_models.provider_from_combo(parent, combo, "slide text")
    assert provider is not None and "slide text" in questions[1]
    assert resolver.cloud_consent_given()
    assert qt_ai_models.provider_from_combo(parent, combo, "slide text") is not None
    assert len(questions) == 2  # no third question


def test_local_only_blocks_a_stale_cloud_selection(settings, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    resolver.set_global_local_only(True)
    combo = QComboBox()
    combo.addItem("claude (cloud)", "anthropic:claude-sonnet-5-5")
    assert qt_ai_models.provider_from_combo(QWidget(), combo, "x") is None
    assert "Local AI only" in errors[0]


def test_the_provider_of_a_task_without_a_picker_follows_the_settings(settings, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, text: errors.append(text))
    parent = QWidget()
    assert qt_ai_models.provider_for_task(parent, "translation", "the slide") is None
    assert "No AI model is chosen" in errors[-1]
    app_settings.set("translation_model", "qwen3")
    provider = qt_ai_models.provider_for_task(parent, "translation", "the slide")
    assert provider.label.startswith("qwen3")
    app_settings.set("translation_model", "anthropic:claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    assert qt_ai_models.provider_for_task(parent, "translation", "the slide") is None      # consent declined
    resolver.set_global_local_only(True)
    assert qt_ai_models.provider_for_task(parent, "translation", "the slide") is None
    assert "Local AI only" in errors[-1]
