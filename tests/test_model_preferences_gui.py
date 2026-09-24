"""Preferences model choices reach each local AI entry point."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QWidget

from slidemage import alt_draft, app_settings, qt_gui, qt_syntax_check_dialog
from slidemage.qt_ai_draft_dialog import AiDraftDialog
from slidemage.qt_settings_dialog import SettingsDialog
from slidemage.qt_syntax_check_dialog import SyntaxCheckDialog
from slidemage.qt_transcript_tab import TranscriptTab
from slidemage.syntax_check import SyntaxCheckResult


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_preferences_route_translation_and_other_models(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    names = ["general-text", "translator", "vision"]
    monkeypatch.setattr(alt_draft, "list_all_models", lambda: names)
    monkeypatch.setattr(alt_draft, "list_vision_models", lambda: ["vision"])
    monkeypatch.setattr(
        alt_draft, "list_installed_models_detailed",
        lambda: [
            alt_draft.InstalledModel(
                name, 1, "", ("vision",) if name == "vision" else ()
            ) for name in names
        ],
    )
    monkeypatch.setattr(SettingsDialog, "_build_translation_tab", lambda self: QWidget())
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
    assert settings.vision_models == ["vision"]
    for combo, name in (
        (settings.default_translation_model_combo, "translator"),
        (settings.default_other_model_combo, "general-text"),
    ):
        index = combo.findText(name)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)
    app_settings.set_ollama_host("http://ollama.example:11434")

    assert app_settings.get("translation_model") == "translator"
    assert app_settings.get_other_model() == "general-text"

    class Source(QWidget):
        def __init__(self):
            super().__init__()
            self.app = app
            self.widget = QPlainTextEdit("slide text", self)

    source = Source()
    requests = []

    class Checker:
        def __init__(self, *, model, host):
            requests.append((model, host))

        def check(self, _text):
            return SyntaxCheckResult(model="general-text")

    monkeypatch.setattr(qt_syntax_check_dialog.syntax_check, "OllamaSyntaxChecker", Checker)
    syntax = SyntaxCheckDialog(source, "slide.tex")
    draft = AiDraftDialog(source, "slide.tex")
    assert syntax.model_combo.currentText() == "general-text"
    assert draft.model_combo.currentText() == "general-text"
    assert requests == [("general-text", "http://ollama.example:11434")]

    tab = SimpleNamespace(model_combo=QComboBox(), translation_model_combo=QComboBox())
    TranscriptTab._populate_models(tab)
    TranscriptTab._populate_translation_models(tab)
    assert tab.model_combo.currentText() == "vision"  # general-text has no vision
    assert tab.translation_model_combo.currentText() == "translator"

    settings.default_other_model_combo.setCurrentText("vision")
    settings.default_other_model_combo.activated.emit(
        settings.default_other_model_combo.currentIndex()
    )
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
    monkeypatch.setattr(qt_gui, "SettingsDialog", lambda _app: settings)
    monkeypatch.setattr(settings, "exec", lambda: None)
    def no_network():
        raise AssertionError("refresh should use the Preferences model catalog")
    monkeypatch.setattr(alt_draft, "list_all_models", no_network)
    monkeypatch.setattr(alt_draft, "list_vision_models", no_network)

    qt_gui.SlideMageWindow._on_open_settings(app)
    assert syntax.model_combo.currentText() == "vision"
    assert draft.model_combo.currentText() == "vision"
    assert app.transcript_tab.model_combo.currentText() == "vision"
    assert app.transcript_tab.translation_model_combo.currentText() == "translator"
