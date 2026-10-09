import os
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "example"

# Must be set before any slidemage module computes PROJECT_ROOT at import.
os.environ["SLIDEMASTER_PROJECT"] = str(EXAMPLE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402 -- after the environment setup above


@pytest.fixture(autouse=True)
def _no_cloud_credentials(monkeypatch):
    """No test may find a real Anthropic key (environment or keychain), so
    none can reach the network by accident; tests that need a key set one
    explicitly."""
    from slidemage.ai import credentials

    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)


@pytest.fixture(autouse=True)
def _isolated_app_settings(monkeypatch, tmp_path_factory):
    """UI preferences (dark mode, the open deck, views ...) go to a throwaway
    file, so a test neither changes the example project's own settings nor
    depends on them."""
    from slidemage import app_settings

    store = tmp_path_factory.mktemp("settings") / "app_settings.json"
    monkeypatch.setattr(app_settings, "STORE_PATH", store)


def build_window(monkeypatch, with_deck_editor: bool = False):
    """The main window on the example project. Its deck editor (a row for
    every slide of the manual, most of a second) is not built unless
    `with_deck_editor` is passed: only a few tests look at it."""
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    QApplication.instance() or QApplication([])
    if not with_deck_editor:
        monkeypatch.setattr(WorkspaceWindow, "open_deck_editor",
                            lambda self, deck: self.stack.setCurrentWidget(self.placeholder))
    return WorkspaceWindow(ThemeManager())
