import atexit
import os
import shutil
import tempfile
import time
from pathlib import Path

from slidemage.project import ProjectContext, _ignore_template_build_output


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SESSION_DIR = Path(tempfile.mkdtemp(prefix="slidemage-tests-"))
atexit.register(shutil.rmtree, _SESSION_DIR, ignore_errors=True)
EXAMPLE = _SESSION_DIR / "example"
shutil.copytree(_REPO_ROOT / "example", EXAMPLE, ignore=_ignore_template_build_output)
EXAMPLE_PROJECT = ProjectContext.at(EXAMPLE)
# Both .latexmkrc files and preview discovery honor this; no framework copy or
# symlink is needed, including on Windows where symlinks may need privileges.
os.environ["SLIDEMASTER_LATEX"] = str(_REPO_ROOT / "latex")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402 -- after the environment setup above
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

# Qt WebEngine (the Claude Code terminal) needs this before any QApplication exists, as the real app sets it.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_cloud_credentials(monkeypatch):
    """No test may find a real Anthropic key (environment or keychain), so
    none can reach the network by accident; tests that need a key set one
    explicitly."""
    from slidemage.ai import credentials

    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)


@pytest.fixture(autouse=True)
def _isolated_temp_dir(monkeypatch, tmp_path_factory):
    """Renders leave their PDF folder (slidemage_preview_*) under the temp directory and sweep
    old ones after every render; a test must neither litter nor sweep the real one."""
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path_factory.mktemp("temp")))


@pytest.fixture(autouse=True)
def _fresh_example_state():
    """Every test starts with what the app keeps inside the example project (settings, prompts,
    project.json) empty, so a test neither changes the example's own state nor depends on it."""
    shutil.rmtree(EXAMPLE_PROJECT.settings_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_layout_settings(monkeypatch, tmp_path_factory):
    """Window layout belongs to this machine; tests must not read or change the user's layout."""
    from slidemage.ui import layout_settings

    store = tmp_path_factory.mktemp("layout") / "layout.json"
    monkeypatch.setattr(layout_settings, "STORE_PATH", store)


def command_context(deck=None, *, compiling=False, selected=(), decks=()):
    """Stands in for the window as the context of the command registry, for the menus and
    predicates that only read the deck, the selection and whether a compile run is going."""
    from types import SimpleNamespace

    from slidemage.ui.workspace.actions import build_registry

    state = SimpleNamespace(deck=deck, focused_slide=None, selected_or_focused=lambda: tuple(selected))
    return SimpleNamespace(commands=build_registry(), state=state, compiling=compiling, decks=list(decks),
                           left_column_hidden=False, right_column_hidden=False)


@pytest.fixture(autouse=True)
def _restore_app_stylesheet():
    """`ThemeManager.apply()` sets the stylesheet of the whole application, and a test that calls it would leave
    it on for every later one: with it, building a window takes several times as long. Put back what was there."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before = app.styleSheet() if app is not None else ""
    yield
    app = QApplication.instance()
    if app is not None and app.styleSheet() != before:
        app.setStyleSheet(before)


_windows = []


def build_window(monkeypatch, context=EXAMPLE_PROJECT):
    """The main window on the example project (or on `context`). Every window built is freed
    after its test (_free_windows), not whenever the garbage collector gets to
    it: a late teardown of its widget tree crashed the interpreter at exit."""
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    QApplication.instance() or QApplication([])
    window = WorkspaceWindow(ThemeManager(project=context), context)
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


TEMPLATE = "\\begin{standardframe}{Title}\r\n\t\\begin{itemize}\r\n\t\t\\item\r\n\t\\end{itemize}\r\n\\end{standardframe}\r\n"


def use_new_slide_files(monkeypatch, root):
    """Make `root` the project that new slides (slide_add) are written to: its slides/ folder, a
    slide_ids.csv, and a starter slide. Translation links are not regenerated; the ids of the
    calls are in the returned list."""
    from slidemage import slide_rename

    context = ProjectContext.at(root)
    context.slides_dir.mkdir(exist_ok=True)
    context.slide_ids_csv.write_bytes(b'"id"\r\n')
    template = context.slide_template_path
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_bytes(TEMPLATE.encode("utf-8"))
    relinked = []
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: relinked.append(True))
    return relinked


SLIDE_TEXT = (
    "%% Included in decks: test\r\n%%\r\n\r\n% A note on this slide\r\n\\setSlideVersion{1-0-0}\r\n"
    "\\begin{standardframe}{Hello}\r\n\t\\begin{itemize}\r\n\t\t\\item First point\r\n"
    "\t\t\\item Second point\r\n\t\\end{itemize}\r\n\t\\vbox to 0pt{\\vss\\hbox{overlay}}\r\n"
    "\\end{standardframe}\r\n")
DECK_TEXT = (
    "\\documentclass{beamer}\r\n\\begin{document}\r\n\\section{Intro}\r\n\\slide{abc-EN-Hello}\r\n"
    "\\section{Main}\r\n\\slide{abd-EN-Second}\r\n\\end{document}\r\n")
BIB_TEXT = "@book{old2000,\n\tauthor = {Old, Ann},\n\ttitle = {Older},\n\tyear = {2000},\n}\n"


def make_project(monkeypatch, root):
    """A small throwaway project at `root` (two slides, one with a frozen version, one deck, a
    .bib) that every module looks up its files in, for tests that change files (the real
    example/ must never be written). The text of the slides is SLIDE_TEXT (CRLF, as in real
    projects); returns `root` resolved."""
    root.mkdir(parents=True, exist_ok=True)
    relinked = use_new_slide_files(monkeypatch, root)    # slides/, slide_ids.csv, slide-template.tex
    assert relinked == []
    slides = root / "slides"
    for name, text in (("abc-EN-Hello-current.tex", SLIDE_TEXT), ("abc-EN-Hello-v1-0-0.tex", SLIDE_TEXT),
                       ("abd-EN-Second-current.tex", SLIDE_TEXT.replace("Hello", "Second"))):
        (slides / name).write_bytes(text.encode())
    (root / "decks").mkdir()
    (root / "decks" / "test.tex").write_bytes(DECK_TEXT.encode())
    (root / "Slidemaster.bib").write_text(BIB_TEXT, encoding="utf-8", newline="\n")
    (root / ".slidemage").mkdir()
    (root / ".slidemage" / "app_settings.json").write_text('{"anthropic_api_key": "sk-secret"}')
    return root.resolve()


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The shared throwaway project for agent tools, MCP and the Claude hook."""
    return make_project(monkeypatch, tmp_path / "project")


@pytest.fixture
def ctx(tmp_path):
    """The project that tests build their files in directly under tmp_path."""
    return ProjectContext.at(tmp_path)


@pytest.fixture
def server():
    """A local provider API; streaming tests override its content type."""
    from fake_http import Server

    srv = Server()
    yield srv
    srv.close()


def wait_until(condition, seconds=5.0):
    """Wait for background work while keeping Qt signals and events moving."""
    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + seconds
    while not condition():
        QApplication.processEvents()
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)
    QApplication.processEvents()


def write_test_file(path: Path, text: str | bytes, *, newline: str | None = "") -> Path:
    """Create a fixture file and its parents, preserving bytes and the requested newlines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline=newline)
    return path
