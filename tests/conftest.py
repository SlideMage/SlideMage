# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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
os.environ["SLIDEMAGE_LATEX"] = str(_REPO_ROOT / "latex")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SLIDEMAGE_NO_BACKGROUND_PREVIEWS", "1")      # a window under test renders nothing by itself


import pytest  # noqa: E402 -- after the environment setup above
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402

# Qt WebEngine (the Claude Code terminal) needs this before any QApplication exists, as the real app sets it.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


@pytest.fixture(scope="session")
def qapp():
    """The application, styled as ui/app.main() styles it (the bundled fonts, the kit's light stylesheet)
    before any widget exists: the stylesheet sizes every button, and unstyled the platform style would --
    Windows gives each text button a minimum width of about 80 px that SlideMage never shows."""
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.kit.fonts import load_fonts
    from slidemage.ui.kit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    load_fonts()
    if not _KIT_QSS:
        _KIT_QSS.append(ThemeManager()._build_qss())
    app.setStyleSheet(_KIT_QSS[0])
    return app


_KIT_QSS: list[str] = []       # the light stylesheet every test starts with (qapp)


@pytest.fixture(autouse=True)
def _no_idle_step_renders(monkeypatch):
    """The Preview counts a slide's reveal steps in the background after 1.5 s of idle time; a test that
    counts renders must not be surprised by one. Tests of the step bar set preview_view.PROBE_MS themselves."""
    from slidemage.ui.workspace import preview_view

    monkeypatch.setattr(preview_view, "PROBE_MS", 3_600_000)


@pytest.fixture(autouse=True)
def _no_cloud_credentials(monkeypatch):
    """No test may find a real Anthropic key (environment or keychain), so
    none can reach the network by accident; tests that need a key set one
    explicitly."""
    from slidemage.ai import credentials

    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)


@pytest.fixture(autouse=True)
def _claude_signed_in(monkeypatch):
    """No test may run the real `claude auth status`: Claude Code counts as signed in unless a test says not."""
    from slidemage.ai import claude_launch

    monkeypatch.setattr(claude_launch, "signed_in", lambda claude: True)


@pytest.fixture(autouse=True)
def _fresh_raster_version():
    """cache_identity reads the PyMuPDF version once per process; a test that patches it starts and leaves it unread."""
    from slidemage import preview_requests

    preview_requests._raster_version.cache_clear()
    yield
    preview_requests._raster_version.cache_clear()


@pytest.fixture(autouse=True)
def _no_scrolling(monkeypatch):
    """Tests change slides faster than anyone scrolls: the Preview would take that as scrolling and hold its checks
    back (preview_view.SCROLLING_MS). The tests of scrolling set it themselves."""
    from slidemage.ui.workspace import preview_view
    monkeypatch.setattr(preview_view, "SCROLLING_MS", 0)


@pytest.fixture(autouse=True)
def _fresh_tool_lookups():
    """The preview remembers where `which` found the TeX tools; a test that patches `which` or PATH starts and leaves it empty."""
    from slidemage import preview_cache

    preview_cache._TOOLS.clear()
    yield
    preview_cache._TOOLS.clear()


@pytest.fixture(autouse=True)
def _isolated_cache_dir(monkeypatch, tmp_path_factory):
    """The render store's index lives in the user's cache folder; a test gets one of its own."""
    from slidemage import project

    monkeypatch.setattr(project, "cache_dir", lambda path=tmp_path_factory.mktemp("cache"): path)


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
def _fresh_ai_session():
    """Every test starts with no AI mode chosen in this session (it then starts from the project's policy)."""
    from slidemage.ai import ai_profile

    ai_profile._modes.clear()


@pytest.fixture(autouse=True)
def _isolated_layout_settings(monkeypatch, tmp_path_factory):
    """Window layout belongs to this machine; tests must not read or change the user's layout."""
    from slidemage.ui import layout_settings

    store = tmp_path_factory.mktemp("layout") / "layout.json"
    monkeypatch.setattr(layout_settings, "STORE_PATH", store)


@pytest.fixture(autouse=True)
def _isolated_machine_ai_settings(monkeypatch, tmp_path_factory):
    """The AI settings of this machine (app_settings.MACHINE_KEYS, v8.58.0): tests must not read or change the
    user's own."""
    from slidemage import app_settings

    monkeypatch.setattr(app_settings, "MACHINE_STORE_PATH", tmp_path_factory.mktemp("machine") / "ai_settings.json")


def command_context(deck=None, *, compiling=False, selected=(), decks=()):
    """Stands in for the window as the context of the command registry, for the menus and
    predicates that only read the deck, the selection and whether a compile run is going."""
    from types import SimpleNamespace

    from slidemage.ui.workspace.actions import build_registry

    state = SimpleNamespace(deck=deck, focused_slide=None, selected_or_focused=lambda: tuple(selected))
    return SimpleNamespace(commands=build_registry(), state=state, compiling=compiling, decks=list(decks),
                           left_column_hidden=False, right_column_hidden=False)


def menu_bar_ids() -> list[str]:
    """Every command id the menu bar can show (menus.py MENU_BAR), its submenus included."""
    from slidemage.ui.workspace.menus import menu_bar_ids as ids

    return ids(command_context())


_FILLED_MENUS: list = []     # kept, so the actions a test holds on to outlive the expression that built their menu


def filled_menu(ctx, title: str):
    """The menu bar's menu `title` ("Deck"), filled for `ctx` as when it opens."""
    from PySide6.QtWidgets import QMenu

    from slidemage.ui.workspace.menus import MENU_BAR, fill_menu

    menu = QMenu()
    _FILLED_MENUS.append(menu)
    fill_menu(menu, ctx, {t.replace("&", ""): sections for t, sections in MENU_BAR}[title])
    return menu


def menu_actions(menu) -> dict:
    """A filled menu's actions by name: command ids, "submenu:<title>" for a submenu's row, submenus included."""
    found = {}
    for action in menu.actions():
        sub = action.menu()
        if sub is not None:
            found[sub.objectName()] = action
            found.update(menu_actions(sub))
        elif action.objectName():
            found[action.objectName()] = action
    return found


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
    from PySide6.QtWidgets import QApplication

    while _windows:
        window = _windows.pop()
        window.hide()   # not close(): that asks about unsaved edits
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app = QApplication.instance()
    if app is not None and _KIT_QSS and app.styleSheet() != _KIT_QSS[0]:
        app.setStyleSheet(_KIT_QSS[0])    # a test that switched the theme: the next one starts as the app does


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
    (root / "SlideMage.bib").write_text(BIB_TEXT, encoding="utf-8", newline="\n")
    (root / ".slidemage").mkdir()
    (root / ".slidemage" / "app_settings.json").write_text('{"anthropic_api_key": "sk-secret"}')
    return root.resolve()


class Resolutions:
    """What resolving a deck has cost since `reset()`: slots resolved (deck_outline.resolve_slots, also inside the
    outline builders), outlines built (build_outline) and scans of the slides folder (TranslationLinks)."""

    slots = outlines = scans = 0

    def reset(self):
        self.slots = self.outlines = self.scans = 0

    def __repr__(self):
        return f"Resolutions(slots={self.slots}, outlines={self.outlines}, scans={self.scans})"


@pytest.fixture
def resolutions(monkeypatch):
    from slidemage import deck_outline, slide_language

    count = Resolutions()

    def counting(module, name, field):
        real = getattr(module, name)

        def wrapper(*args, **kwargs):
            setattr(count, field, getattr(count, field) + 1)
            return real(*args, **kwargs)
        monkeypatch.setattr(module, name, wrapper)

    counting(deck_outline, "resolve_slots", "slots")
    counting(deck_outline, "build_outline", "outlines")

    class CountingLinks(slide_language.TranslationLinks):
        def __init__(self, *args, **kwargs):
            count.scans += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(slide_language, "TranslationLinks", CountingLinks)
    return count


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
