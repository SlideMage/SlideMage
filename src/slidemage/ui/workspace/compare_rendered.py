"""Compare rendered: one slide's text before and after an AI edit, typeset side by side.

A dialog of its own (not modal, wider than the assistant's 360 px column) that every place showing an AI edit opens:
the task card (Review, Conflict, Done), the chat's diff cards, and the Claude Code edits (the earlier text is the one
ai_review.last_before() keeps). Both sides are rendered as drafts, for the same target, view and language as the Check
preview step (preview_view.render_context): the text goes through a RenderService, so the compile slot and the build
locks are the Preview pane's, with persistent caches and unchanged slide sources. Each side has a worker thread that waits for its request and
reads the pages of the PDF; a side that fails says so while the other is still shown. Esc or Close cancels
whatever is pending.

The reveal steps of a slide are the pages of its PDF. ‹ and › (and the arrow keys) move both sides to the same page; a
side with fewer pages shows "no page". Until the user moves, the page is the last one both sides have (the slide fully
revealed). "Text diff" shows the source diff of the same two texts.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout

from ... import ai_review, preview_pages, preview_target
from ...preview_requests import RenderService
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, IconButton, Surface
from .chat.cards import DiffCard
from .preview_view import PageView, render_context, short_view
from .task_card_model import first_error

PAGE_DPI = 130
MAX_PAGES = 60


def read_pages(pdf: Path, project_root: Path) -> list[bytes]:
    """The pages of a rendered slide as PNGs (in the raster child process, like every MuPDF read)."""
    return preview_pages.read_document(pdf, project_root=project_root, count=MAX_PAGES, dpi=PAGE_DPI)["images"]


def can_compare(window, path: Path) -> bool:
    """Whether `path` is a slide file: the only kind of file that is typeset."""
    return preview_target.for_path(window.project, path) is not None


class _Worker(QThread):
    done = Signal(object)              # this worker

    def __init__(self, request, cancel: threading.Event, project_root: Path) -> None:
        super().__init__()
        self.request, self.cancel, self.project_root = request, cancel, project_root
        self.pages: list[bytes] = []
        self.error = ""

    def run(self) -> None:
        try:
            artifact = self.request.wait(self.cancel)
            pages = preview_pages.sequence_images(self.request, count=MAX_PAGES, dpi=PAGE_DPI)
            self.pages = pages if pages is not None else read_pages(artifact[0], self.project_root)
        except Exception as exc:  # noqa: BLE001 -- whatever the render raised is this side's message
            self.error = str(exc) or type(exc).__name__
        if not self.cancel.is_set():
            self.done.emit(self)


@dataclass
class _Side:
    name: str                          # "Before" or "After"
    view: PageView
    chip: Chip
    pages: list[QPixmap] = field(default_factory=list)
    error: str = ""
    busy: bool = True
    worker: Optional[_Worker] = None


class CompareRendered(QDialog):
    """See the module docstring. `renders` is a RenderService (a test passes its own)."""

    def __init__(self, app, path: Path, before: str, after: str, *, renders: Optional[RenderService] = None) -> None:
        super().__init__(app)
        context = render_context(app, path)
        if context is None:
            raise ValueError(f"{path.name} is not a slide file")
        self.app = app
        self.target, self.view, self.language = context
        self.texts = {"Before": before, "After": after}
        self.setObjectName(q.SHEET)
        self.setModal(False)
        self.setWindowTitle(f"Compare rendered · {self.target.bare_id} · {short_view(self.view)} · {self.language}")
        self.resize(1200, 720)
        self.setMinimumSize(760, 480)
        self._page: Optional[int] = None                # None until the user moves: the last page both sides have
        self._cancel = threading.Event()
        self._renders = renders or RenderService()
        self.closed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)
        title = QLabel(self.windowTitle())
        title.setObjectName(q.SHEET_TITLE)
        root.addWidget(title)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        rendered = Surface()
        body = QVBoxLayout(rendered)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        panes = QHBoxLayout()
        panes.setSpacing(16)
        self._sides: list[_Side] = []
        for name in self.texts:
            column = QVBoxLayout()
            head = QHBoxLayout()
            label = QLabel(name)
            label.setObjectName(q.PREVIEW_TITLE)
            chip = Chip("", "info")
            head.addWidget(label)
            head.addWidget(chip)
            head.addStretch(1)
            view = PageView(lambda: self.app.theme.tokens)
            view.setAccessibleName(f"{name}, rendered slide")
            column.addLayout(head)
            column.addWidget(view, 1)
            panes.addLayout(column, 1)
            self._sides.append(_Side(name, view, chip))
        body.addLayout(panes, 1)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self._previous = IconButton("chevron_left", "Previous page (←)")
        self._next = IconButton("chevron_right", "Next page (→)")
        self._position = QLabel()
        self._position.setObjectName(q.PANEL_CAPTION)
        self._position.setMinimumWidth(110)
        self._position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._previous.clicked.connect(lambda: self.step(-1))
        self._next.clicked.connect(lambda: self.step(1))
        for widget in (self._previous, self._position, self._next):
            nav.addWidget(widget)
        nav.addStretch(1)
        body.addLayout(nav)
        self._stack.addWidget(rendered)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setObjectName(q.SURFACE)
        scroll.viewport().setObjectName(q.SURFACE)
        self.diff = DiffCard(path.name, before, after)
        self.diff.show_all()
        holder = Surface()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.diff)
        column.addStretch(1)
        scroll.setWidget(holder)
        self._stack.addWidget(scroll)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.diff_button = Button("Text diff", "secondary")
        self.diff_button.setCheckable(True)
        self.diff_button.toggled.connect(self._toggle_diff)
        close = Button("Close", "primary")
        close.clicked.connect(self.accept)
        footer.addWidget(self.diff_button)
        footer.addWidget(close)
        root.addLayout(footer)

        for key, delta in ((Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda delta=delta: self.step(delta))

        for side in self._sides:
            request = self._renders.request(self.target, self.texts[side.name], self.view, self.language,
                                            app.log, require_pdf=True)
            side.worker = _Worker(request, self._cancel, app.project.root)
            side.worker.done.connect(self._on_done)
        self._show()
        for side in self._sides:
            background.start_detached(side.worker)

    # -- the pages ---------------------------------------------------------------------------

    def _on_done(self, worker: _Worker) -> None:
        side = next(side for side in self._sides if side.worker is worker)
        side.busy, side.error = False, worker.error
        for data in worker.pages:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                side.pages.append(pixmap)
        if not side.error and not side.pages:
            side.error = "the PDF has no pages"
        self._show()

    def page(self) -> int:
        """The page both sides show (1-based)."""
        if self._page is not None:
            return self._page
        return min((len(side.pages) for side in self._sides if side.pages), default=1)

    def _last(self) -> int:
        return max((len(side.pages) for side in self._sides), default=1) or 1

    def step(self, delta: int) -> None:
        if self._stack.currentIndex() == 0:
            self._page = min(max(self.page() + delta, 1), self._last())
            self._show()

    def _show(self) -> None:
        number = self.page()
        for side in self._sides:
            if side.busy:
                text, tone, icon, message = "Rendering…", "info", "autorenew", "Rendering…"
            elif side.error:
                text, tone, icon = "Not rendered", "error", "error_outline"
                message = f"{side.name} could not be rendered: {first_error(side.error)}"
            elif number > len(side.pages):
                text, tone, icon = f"No page {number}", "warning", "remove_circle_outline"
                message = f"{side.name} has only {len(side.pages)} page{'s' if len(side.pages) != 1 else ''}."
            else:
                text, tone, icon, message = f"Page {number} of {len(side.pages)}", "muted", "", ""
            side.chip.set_text(text)
            side.chip.set_tone(tone)
            side.chip.set_icon(icon)
            if message:
                side.view.show_message(message, False)
            else:
                side.view.show_image(side.pages[number - 1])
            side.view.setAccessibleDescription(message or text)
        last = self._last()
        self._position.setText(f"Page {number} of {last}")
        self._previous.setEnabled(number > 1)
        self._next.setEnabled(number < last)

    def _toggle_diff(self, shown: bool) -> None:
        self._stack.setCurrentIndex(int(shown))
        self.diff_button.setText("Rendered pages" if shown else "Text diff")

    # -- closing -----------------------------------------------------------------------------

    def done(self, result: int) -> None:
        """Esc, Close and the window's close button: cancel what is pending (the renders end at their next check), go."""
        self.closed = True
        self._cancel.set()
        self._renders.close()
        for side in self._sides:
            side.worker.done.disconnect(self._on_done)
        super().done(result)
        self.deleteLater()


def open_compare(app, path: Path, before: str, after: str) -> Optional[CompareRendered]:
    """Show the dialog for the slide file `path`; None (nothing shown) for a file that is not a slide, or when the two
    texts are the same."""
    if before == after or not can_compare(app, path):
        return None
    dialog = CompareRendered(app, path, before, after)
    dialog.show()
    return dialog


def compare_with_last_edit(app, path: Path) -> None:
    """The slide `path` as it was before the last AI edit kept for it (ai_review.last_before) against its text now,
    as the Source view has it."""
    before = ai_review.last_before(app.project, path)
    if before is None or open_compare(app, path, before, app.centre.slide_text(path)) is None:
        app.toast.show_message("Nothing to compare: the slide is as it was before the last AI edit.")
