"""Settings -> "AI models" per-task defaults reach each local AI entry point.

Each AI task (syntax check, AI drafting, image descriptions, translation)
has its own default model; every model picker preselects its task's
default, and changing a default in Settings reaches pickers that are
already open once the Settings dialog closes.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QWidget

from slidemage import app_settings, qt_syntax_check_dialog
from slidemage.ui.workspace import window as window_module
from slidemage.ai.providers import ANTHROPIC_FALLBACK_MODELS, InstalledModel, OllamaProvider
from slidemage.qt_ai_draft_dialog import AiDraftDialog
from slidemage.qt_settings_dialog import SettingsDialog
from slidemage.qt_syntax_check_dialog import SyntaxCheckDialog
from slidemage.qt_transcript_tab import TranscriptTab
from slidemage.syntax_check import SyntaxCheckResult


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _choose(settings: SettingsDialog, task: str, model: str) -> None:
    combo = settings._model_combos[task]
    index = combo.findData(f"ollama:{model}")
    assert index != -1, (task, model)
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def test_per_task_model_defaults_reach_every_picker(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    names = ["general-text", "translator", "vision", "vision-2"]
    vision = ["vision", "vision-2"]
    monkeypatch.setattr(
        OllamaProvider, "installed",
        lambda self: [
            InstalledModel(name, 1, "", ("vision",) if name in vision else ())
            for name in names
        ],
    )
    monkeypatch.setattr(
        OllamaProvider, "list_models",
        lambda self, vision_only=False: vision if vision_only else names)
    monkeypatch.setattr(SettingsDialog, "_build_ai_prompts_tab", lambda self: QWidget())

    class App(QWidget):
        def __init__(self):
            super().__init__()
            self.theme = SimpleNamespace(dark=False)
            self.set_dark_mode = lambda _value: None
            self.set_tab_width_chars = lambda _value: None
            self.try_start_ollama_task = lambda _label: True
            self.end_ollama_task = lambda: None
            self.log = lambda _message: None

    app = App()
    settings = SettingsDialog(app)
    assert settings.available_models == names
    assert settings.vision_models == vision
    # Image descriptions only offer vision models among the local ones (plus
    # the "none" entry); without an API key the cloud list is the built-in one.
    image_combo = settings._model_combos["image_description"]
    assert [image_combo.itemData(i) for i in range(image_combo.count())] == [
        "", *(f"ollama:{m}" for m in vision),
        *(f"anthropic:{m}" for m in ANTHROPIC_FALLBACK_MODELS)]

    _choose(settings, "syntax_check", "general-text")
    _choose(settings, "ai_draft", "translator")
    _choose(settings, "image_description", "vision-2")
    _choose(settings, "translation", "translator")
    app_settings.set_ollama_host("http://ollama.example:11434")
    assert app_settings.default_model("syntax_check") == "ollama:general-text"
    assert app_settings.default_model("ai_draft") == "ollama:translator"
    assert app_settings.default_model("image_description") == "ollama:vision-2"
    assert app_settings.default_model("translation") == "ollama:translator"

    class Source(QWidget):
        def __init__(self):
            super().__init__()
            self.app = app
            self.widget = QPlainTextEdit("slide text", self)

    source = Source()
    requests = []

    class Checker:
        def __init__(self, provider):
            requests.append((provider.model, provider.host))

        def check(self, _text):
            return SyntaxCheckResult(model="general-text")

    monkeypatch.setattr(qt_syntax_check_dialog.syntax_check, "SyntaxChecker", Checker)
    syntax = SyntaxCheckDialog(source, "slide.tex")
    # The check itself runs on a worker thread; let it finish.
    if syntax._worker is not None:
        syntax._worker.wait()
    qapp.processEvents()
    draft = AiDraftDialog(source, "slide.tex")
    assert syntax.model_combo.currentText() == "general-text"
    assert draft.model_combo.currentText() == "translator"
    assert requests == [("general-text", "http://ollama.example:11434")]

    tab = SimpleNamespace(model_combo=QComboBox(), translation_model_combo=QComboBox())
    TranscriptTab._populate_models(tab)
    TranscriptTab._populate_translation_models(tab)
    assert tab.model_combo.currentText() == "vision-2"
    assert tab.translation_model_combo.currentText() == "translator"

    # Picking another model in a dialog applies to that dialog only.
    draft.model_combo.setCurrentText("vision")
    draft.model_combo.activated.emit(draft.model_combo.currentIndex())
    assert app_settings.default_model("ai_draft") == "ollama:translator"

    # A default changed in Settings reaches already-open pickers when the
    # Settings dialog closes -- from the dialog's own model lists, with no
    # further Ollama round trip.
    _choose(settings, "syntax_check", "vision")
    _choose(settings, "ai_draft", "general-text")
    _choose(settings, "image_description", "vision")
    source._syntax_check_dialog = syntax
    source._ai_draft_dialog = draft
    app._slide_source_tabs = {"source": source}

    class OpenTranscript:
        _populate_models = TranscriptTab._populate_models
        _populate_translation_models = TranscriptTab._populate_translation_models
        refresh_model_preferences = TranscriptTab.refresh_model_preferences

        def __init__(self):
            self.model_combo = QComboBox()
            self.translation_model_combo = QComboBox()
            self._update_draft_button = lambda: None

    app.transcript_tab = OpenTranscript()
    monkeypatch.setattr(window_module, "SettingsDialog", lambda _app: settings)
    monkeypatch.setattr(settings, "exec", lambda: None)

    def no_network():
        raise AssertionError("refresh should use the Settings dialog's model lists")

    monkeypatch.setattr(OllamaProvider, "list_models", no_network)
    monkeypatch.setattr(OllamaProvider, "installed", no_network)

    window_module.WorkspaceWindow._on_open_settings(app)
    assert syntax.model_combo.currentText() == "vision"
    assert draft.model_combo.currentText() == "general-text"
    assert app.transcript_tab.model_combo.currentText() == "vision"
    assert app.transcript_tab.translation_model_combo.currentText() == "translator"
