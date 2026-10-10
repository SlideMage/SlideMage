"""xterm.js in a Qt web view, as a widget (UI redesign step 10c). The page (assets/terminal/) is vendored
xterm.js plus a few lines of glue, loaded from disk: no network, no CDN. Python and the page talk over a
QWebChannel: `TerminalBridge` is the page's one object.

The widget knows nothing of processes. It emits what the user types (`input_data`), its size in cells
(`resized`), and shows what it is given (`write`). `ready(cols, rows)` fires once, when the page has measured
itself: the caller starts its process with that size. Copy and paste go through the system clipboard here
(the page has no clipboard access of its own); links from the terminal open in the system browser.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from ...kit.tokens import Tokens
from .theme import theme_json

# A terminal needs no GPU: software rendering spares a GPU process and the crashes of some drivers (and of the
# offscreen platform the tests use). Chromium reads it when the first web view starts.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

PAGE = Path(__file__).resolve().parents[3] / "assets" / "terminal" / "terminal.html"
LINK_SCHEMES = ("http", "https", "mailto")


class TerminalBridge(QObject):
    """The object the page sees as `bridge`: slots it calls, signals it listens to."""

    # page -> Python (through the slots below, which a page can call; it cannot call a signal)
    ready = Signal(int, int)          # cols, rows: the first fit
    resized = Signal(int, int)
    input_data = Signal(bytes)        # what the user typed or pasted, as the process should read it
    selection = Signal(str)
    # Python -> page
    output = Signal(str)              # base64 of bytes to draw
    theme = Signal(str)
    paste = Signal(str)
    focus_terminal = Signal()
    reset_terminal = Signal()

    def __init__(self, theme_text: str) -> None:
        super().__init__()
        self._theme = theme_text
        self.selected = ""

    @Slot(result=str)
    def initial_theme(self) -> str:
        return self._theme

    @Slot(int, int)
    def page_ready(self, cols: int, rows: int) -> None:
        self.ready.emit(cols, rows)

    @Slot(int, int)
    def page_resized(self, cols: int, rows: int) -> None:
        self.resized.emit(cols, rows)

    @Slot(str)
    def send_input(self, data: str) -> None:
        self.input_data.emit(data.encode("utf-8"))

    @Slot(str)
    def send_binary(self, data: str) -> None:
        self.input_data.emit(data.encode("latin-1", "replace"))

    @Slot(str)
    def selection_changed(self, text: str) -> None:
        self.selected = text
        self.selection.emit(text)

    @Slot(str)
    def copy_text(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def paste_requested(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self.paste.emit(text)

    @Slot(str)
    def open_url(self, url: str) -> None:
        if QUrl(url).scheme() in LINK_SCHEMES:
            QDesktopServices.openUrl(QUrl(url))


class _Page(QWebEnginePage):
    """Shows the terminal page and nothing else: no navigation, no new windows."""

    def acceptNavigationRequest(self, url: QUrl, kind, is_main_frame: bool) -> bool:
        return url == QUrl.fromLocalFile(str(PAGE)) or url.toString() == "about:blank"

    def createWindow(self, _kind) -> None:
        return None


_profile: QWebEngineProfile | None = None


def _shared_profile() -> QWebEngineProfile:
    """One profile for every terminal page, owned by the application (a profile must outlive its pages,
    and an owner that goes first makes Qt complain). It has no name, so nothing is stored on disk."""
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(QCoreApplication.instance())
    return _profile


class TerminalWidget(QWidget):
    ready = Signal(int, int)
    resized = Signal(int, int)
    input_data = Signal(bytes)

    def __init__(self, tokens: Tokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.bridge = TerminalBridge(theme_json(tokens))
        self.bridge.ready.connect(self.ready)
        self.bridge.resized.connect(self.resized)
        self.bridge.input_data.connect(self.input_data)
        self._page = _Page(_shared_profile(), self)
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self.bridge)
        self._page.setWebChannel(self._channel)
        self.view = QWebEngineView(self)
        self.view.setPage(self._page)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self.view.load(QUrl.fromLocalFile(str(PAGE)))

    def write(self, data: bytes) -> None:
        self.bridge.output.emit(base64.b64encode(data).decode("ascii"))

    def reset(self) -> None:
        self.bridge.reset_terminal.emit()

    def set_tokens(self, tokens: Tokens) -> None:
        self.bridge._theme = theme_json(tokens)
        self.bridge.theme.emit(self.bridge._theme)

    def focus_terminal(self) -> None:
        self.view.setFocus()
        self.bridge.focus_terminal.emit()

    def _context_menu(self, position) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy", lambda: self.bridge.copy_text(self.bridge.selected))
        copy.setEnabled(bool(self.bridge.selected))
        menu.addAction("Paste", self.bridge.paste_requested)
        menu.exec(self.view.mapToGlobal(position))

    def shutdown(self) -> None:
        """Free the page before its profile (Qt wants it in that order)."""
        self.view.setPage(None)
        self._page.deleteLater()
