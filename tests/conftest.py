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


_windows = []


def build_window(monkeypatch):
    """The main window on the example project. Every window built is freed
    after its test (_free_windows), not whenever the garbage collector gets to
    it: a late teardown of its widget tree crashed the interpreter at exit."""
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    QApplication.instance() or QApplication([])
    window = WorkspaceWindow(ThemeManager())
    _windows.append(window)
    return window


@pytest.fixture(autouse=True)
def _free_windows():
    yield
    from PySide6.QtCore import QCoreApplication, QEvent

    while _windows:
        window = _windows.pop()
        window.hide()   # not close(): that asks about unsaved edits
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pytest_sessionfinish(session):
    """Delete the widgets the tests left behind (dialogs, menus, tabs) while
    their Python wrappers are still alive. Left to the interpreter's exit,
    PySide destroys them in no particular order and the process sometimes
    aborts with "pure virtual method called"."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def use_slides_folder(monkeypatch, folder):
    """Point every module that looks a slide up at `folder` (and keep the backups of saves in it)."""
    from slidemage import deck_editor, deck_outline, preview_target, slide_language, slide_source
    from slidemage.ui.workspace import centre, details_view

    for module in (deck_editor, deck_outline, preview_target, slide_language, slide_source, centre, details_view):
        monkeypatch.setattr(module, "SLIDES_DIR", folder)
    monkeypatch.setattr(slide_source, "BACKUPS_DIR", folder / ".backups")
