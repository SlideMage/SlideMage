# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preview view: the focused slide as a page, in the view (Instructor /
During course / After course) and language the top bar says.

Without compiling anything it shows the render store's current page, previous
render or Instructor reference.
"Render" compiles the saved slide in the view and language, and the Render
menu renders the editor's buffer instead (Ctrl+Enter), a
presenter PDF, or a transcript. Rendering runs on a worker thread; what a
render depends on is in preview_target.py. Every render is preceded by the
quick static syntax check (latex_lint through render_check), which asks
before rendering a slide that has errors.

Chips say what the page is not showing at first sight: a version the deck
pins, a language, a missing translation, a view that does not typeset the
slide. They come from the deck outline and the slide's file name, nothing
is guessed. The language chip of a slide with a translation partner is a
button that shows the partner file instead (one slide; the top bar's
language stays), and back from there: it is typeset in its own language.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
from threading import Thread
import shutil
import time
import tempfile
import weakref
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import (deck_context, deck_editor, deck_language, languages, latex_lint, render_key, render_lookup, reveal_steps, slide_preview, slide_snapshot, slide_source,
                 slide_versioning, timing)
from ...ai.workspace import WorkspaceContext
from ...ai.tools.slidemage import slide_target
from ...deck_outline import SlideRow
from ...preview_target import PreviewTarget
from ...preview_requests import PreviewRequest, RenderOptions, RenderRequest, RenderService, SourceRevision
from ...preview_metrics import PreviewMetrics
from ...slide_usage import deck_calls, decks_by
from ...slide_language import MULT, LanguageBadge, TranslationLink, own_language, translation_group
from ...step_renders import BACKGROUND, FOREGROUND, StepRenderQueue
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit.tokens import SPACE, RADIUS_SM
from ..kit import kit_qss as q
from ..kit.review_mark import paint_review_mark
from ..kit.tokens import Tokens
from ..polling import PollTimer
from .version_bar import VersionBar
from ..kit.widgets import Button, Chip, ElidedLabel, PopoverMenu, SplitButton, Surface, clear_layout
from . import render_check
from .menus import VIEW_LABELS
from .preview_model import (DISPLAY_BYTES, DISPLAY_ENTRIES, DISPLAY_WIDTH, PREFETCHED, PRELOAD_BYTES, PRELOAD_PAUSE,  # noqa: F401
                            PRELOAD_RETRY, STEP_CACHE, DisplayCache, PreviewModel, display_pixmap)
from .reveal_bar import RevealBar, RowSpec
from .state import VIEWS, WorkspaceState

PAGE_ASPECT = 16 / 9
PAGE_MIN_WIDTH = 320
TITLE_MAX = 90      # characters of a slide's title shown in the footer; the rest is cut off


def shortened(title: str) -> str:
    """A title longer than TITLE_MAX characters, cut off with "…"."""
    return title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"
PANE_SIDE_MARGIN = SPACE.xl    # the Preview's margin left and right (chips, page, footer)
PAGE_SIDE_INSET = 8      # the page inside its area, left and right: the shadow's room
PROBE_MS = 1500          # idle time before the step bar counts a slide's steps in the background
SETTLE_MS = 150          # the selection must rest this long before the step bar starts counting the slide's steps
NEIGHBOURS = 4           # slides around the one on show whose steps are counted while the pane is idle
SCROLLING_MS = 300       # slide changes closer than this are scrolling: no checks until the selection rests
LOADING = "Loading…"
SOURCE_CHANGED = "Source changed"   # the page shows an older text: said on the page and in the status
# Menu keys.
BUFFER, PRESENTER, TRANSCRIPT, OPEN_PDF = "buffer", "presenter", "transcript", "open_pdf"
ALL_SAVED, ALL_BUFFER, FORCE, STOP = "all_saved", "all_buffer", "force", "stop"


def short_view(view: str) -> str:
    return VIEW_LABELS[view].replace(" course", "")


def partner_link(links: list[TranslationLink]) -> Optional[TranslationLink]:
    """The link the language chip jumps to: the original when the file shown is a translation, else the first
    translation; None for a file with no translation."""
    return next((link for link in links if link.is_translation), links[0] if links else None)


def chips_for(target: PreviewTarget, row: Optional[SlideRow], view: str, language: str, own: Optional[str],
              links: list[TranslationLink] = (), context_mode: Optional[str] = None,
              rendered: bool = False) -> list[tuple]:
    """(icon, text, tone, tooltip) of the chips above the page. `row` is the
    slide's row in the open deck, None for a file shown alone; `own` its language; `links` the other
    members of its translation group."""
    chips = []
    if row is None:
        if target.version:
            chips.append(("lock", f"Frozen {slide_versioning.version_label(target.version)}", "muted",
                          "A past version of the slide, shown on its own."))
    else:
        call = row.call
        if target.version:
            chips.append(("push_pin", f"Deck stays on {slide_versioning.version_label(target.version)}", "info",
                          "The deck pins this version; changes to the current slide don't show here."))
        if not call.editable:
            chips.append(("lock", "Read-only in the deck", "muted", call.readonly_reason or ""))
        if row.hidden:
            chips.append(("visibility_off", f"Hidden in {VIEW_LABELS[view]}", "warning",
                          "The deck does not typeset this slide in the view being edited."))
        if row.missing_translation:
            chips.append(("translate", f"No {language} version", "warning",
                          f"The slide has no translation into {language}."))
    if target.needs_context:
        chips.append(context_chip(target, view, context_mode, rendered))
    if any(link.outdated for link in links):
        chips.append(("translate", "Translation outdated", "warning",
                      "The original was saved after the translation was last written (Language panel)."))
    if own and (partner := partner_link(links)):
        chips.append(("language", LanguageBadge(own, tuple(link.language for link in links)).text().strip("[]"), "neutral",
                      f"Go to the {languages.name(partner.language)} "
                      f"{'original' if partner.is_translation else 'version'}"))
    elif own:
        chips.append(("language", own, "neutral", "The slide's language; it has no translation."))
    return chips


def context_chip(target: PreviewTarget, view: str, mode: Optional[str], rendered: bool) -> tuple:
    """The chip of a slide that needs its deck (deck_context): whether the page shows it in the deck's context."""
    why = deck_context.describe(target.needs_context)
    if mode == deck_context.DECK:
        return ("account_tree", "In the deck's context", "info",
                f"This slide shows {why}. It was typeset in the last compile of the deck, so those are the real ones.")
    if mode == deck_context.SKELETON:
        return ("warning", "Rendered without the deck: may differ from the full deck", "warning",
                f"This slide shows {why}. It was typeset with the deck's sections and agenda around it, but page "
                f"numbers of sections are not the real ones. Compile the deck ({VIEW_LABELS[view]}) once, then render "
                "again: click here to compile it.")
    if rendered:
        return ("warning", "Rendered without deck context: may differ from the full deck", "warning",
                f"This slide shows {why}, which a single-slide render cannot know. Click to compile the deck "
                f"({VIEW_LABELS[view]}); a render after that uses it.")
    return ("account_tree", "Needs the deck around it", "muted",
            f"This slide shows {why}: a render typesets it with the deck's context.")


def _shown_occurrence(window, state=None):
    """The occurrence key of the slide on show: a slide file tab's own, else the focused slide's."""
    centre = getattr(window, "centre", None)
    if hasattr(centre, "shown_occurrence"):
        return centre.shown_occurrence
    return getattr(state or getattr(window, "state", None), "focused_occurrence", None)


def render_context(window, path: Path) -> Optional[tuple[PreviewTarget, str, str]]:
    """(target, view, language) for rendering the slide file `path` as the top bar says: in its own
    language when that is one of the project's, as the open deck calls it. None when `path` is no slide file."""
    state = window.state
    language = own_language(path.name, languages.project_languages(window.project).codes)
    language = language if language not in (None, MULT) else state.language
    target = slide_target(window.project, state.deck, path, state.view, language,
                          occurrence_key=_shown_occurrence(window))
    return None if target is None else (target, state.view, language)


@dataclass(frozen=True)
class _PageResult:
    ticket: int
    request: PreviewRequest
    status: str
    record: dict | None = None
    pages: tuple[bytes, ...] = ()
    decoded: tuple[int, str, QImage | QPixmap | None] | None = None

    @property
    def key(self) -> tuple:
        return (self.request.target.key, self.request.view, self.request.language)

    @property
    def count(self) -> int:
        return len(self.pages) or int(self.decoded is not None)


def _read_pages(renderer, ticket, spec, choice, cached=(), *, prefetch=False, decode=True):
    status, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec),
                                          strict=not prefetch)
    if record is None:
        return _PageResult(ticket, spec, status)
    if prefetch:
        data = renderer.store.page(record, record['pages'])
        pages = (data,) if data is not None else ()
    else:
        pages = tuple(renderer.store.pages(record) or ())
    if not pages:
        return _PageResult(ticket, spec, status, record)
    i = min(max(len(pages) if choice is None else choice, 1), len(pages)) - 1
    digest = hashlib.sha256(pages[i]).hexdigest()
    image = QImage.fromData(pages[i]) if decode and digest not in cached else None
    return _PageResult(ticket, spec, status, record, pages, (i, digest, image))


@dataclass
class _Job:
    """A finished render, handed from the worker thread to the GUI thread."""
    pdf: Optional[Path] = None
    png: Optional[bytes] = None
    image: Optional[QImage] = None
    record: dict | None = None
    error: Optional[str] = None
    target_key: tuple = ()
    view: str = ""
    language: str = ""
    mtime: int = 0                  # of the slide's source when the render started
    note: str = ""                  # set: rendered from the editor buffer, not the saved file
    external: bool = False          # open the PDF in the viewer instead of showing it
    generation: int = 0
    source: Optional[Path] = None
    buffer_text: Optional[str] = None
    requested: float = 0
    metrics: Optional[dict] = None
    request: Optional[RenderRequest] = None
    spec: PreviewRequest | None = None
    revision_text: Optional[str] = None
    remote: bool = False
    steps_ok: bool = True           # a whole-slide render: count its reveal steps
    cancel: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)


def _discard_job(job: _Job) -> None:
    # Shared PDFs remain available to every consumer; the normal render sweep removes them.
    if job.request is None and job.pdf is not None and job.pdf.parent.name.startswith('slidemage_preview_'):
        shutil.rmtree(job.pdf.parent, ignore_errors=True)


class _Lifetime:
    """Plain Python receiver: it survives QObject destruction and queued results."""

    def __init__(self, pane):
        self.owner = weakref.ref(pane)
        self.closed = threading.Event()
        self.job = None

    def close(self, *_args):
        self.closed.set()
        owner = self.owner()
        if owner is not None:
            # Only Python attributes; the C++ QWidget may already be gone.
            if owner._batch_cancel is not None:
                owner._batch_cancel.set()
            owner._display_executor.shutdown(wait=False, cancel_futures=True)
            owner._prefetch_executor.shutdown(wait=False, cancel_futures=True)
            owner.model.close()
            owner._pdf_copies.close()
            owner._renders.close()
            owner._steps.close()
            owner._pending = None
            owner._generation += 1
        if self.job is not None:
            self.job.cancel.set()
            _discard_job(self.job)


class PageView(QWidget):
    """The page: a white 16:9 rectangle with a soft shadow, holding the slide's image,
    or, when there is none, a surface-colored one with a message. `tokens()` gives the
    theme's colors."""

    wheeled = Signal(int)         # one notch of the mouse wheel: +1 forward (wheel down), -1 back

    def __init__(self, tokens: Callable[[], Tokens]) -> None:
        super().__init__()
        self._tokens = tokens
        self._wheel = 0
        self.pixmap: Optional[QPixmap] = None
        self._scaled: Optional[tuple[QSize, QPixmap]] = None    # the pixmap at the page's size: not rescaled per paint
        self.message = ""
        self.badge = ""         # a short note drawn on the page's top-right corner
        self.review = ("", "")  # the watermark's text and note for a slide its deck marks as under review
        self.setMinimumSize(PAGE_MIN_WIDTH, 180)
        self.render_button = Button("Render now", "primary", self)
        self.render_button.hide()

    def show_image(self, pixmap: QPixmap, badge: str = "") -> None:
        if self.pixmap is pixmap and self.badge == badge:
            return
        if self.pixmap is not pixmap:
            self._scaled = None
        self.pixmap, self.message, self.badge = pixmap, "", badge
        self.render_button.hide()
        self.update()

    def set_review(self, text: str, note: str = "") -> None:
        """Draw the "under review in this deck" watermark over the slide's image ("" for none)."""
        if self.review != (text, note):
            self.review = (text, note)
            self.update()

    def show_message(self, message: str, can_render: bool) -> None:
        self.pixmap, self.message, self._scaled, self.badge = None, message, None, ""
        self.render_button.setVisible(can_render)
        self._place_button()
        self.update()

    def _page_rect(self) -> QRectF:
        aspect = self.pixmap.width() / self.pixmap.height() if self.pixmap else PAGE_ASPECT
        if abs(aspect / PAGE_ASPECT - 1) < 0.01:
            aspect = PAGE_ASPECT      # a page rounded to whole pixels is still the 16:9 page: no change of size between slides
        # 8 px at the sides is room for the shadow (6 px): in a narrow Split view the width sets the page's size.
        area = QRectF(self.rect()).adjusted(PAGE_SIDE_INSET, 24, -PAGE_SIDE_INSET, -24)
        width = min(area.width(), area.height() * aspect)
        height = width / aspect
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def _scaled_pixmap(self, page: QRectF) -> QPixmap:
        """The pixmap scaled to the page (in device pixels), kept until the size or the pixmap changes."""
        ratio = self.devicePixelRatioF()
        size = QSize(max(1, round(page.width() * ratio)), max(1, round(page.height() * ratio)))
        if self._scaled is None or self._scaled[0] != size:
            scaled = self.pixmap.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self._scaled = (size, scaled)
        return self._scaled[1]

    def _place_button(self) -> None:
        page = self._page_rect()
        hint = self.render_button.sizeHint()
        self.render_button.move(int(page.center().x() - hint.width() / 2), int(page.center().y() + 14))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_button()

    def wheelEvent(self, event) -> None:
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= 120:
            self.wheeled.emit(-1 if self._wheel > 0 else 1)
            self._wheel -= 120 if self._wheel > 0 else -120
        event.accept()

    def paintEvent(self, event) -> None:
        page = self._page_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((6, 8), (3, 14), (1, 22)):   # a soft shadow, as the prototype's
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(page.adjusted(-grow, -grow, grow, grow).translated(0, grow), RADIUS_SM + grow, RADIUS_SM + grow)
        tokens = self._tokens()
        painter.setBrush(QColor(tokens.paper) if self.pixmap is not None else QColor(tokens.surface))
        painter.drawRoundedRect(page, RADIUS_SM, RADIUS_SM)
        if self.pixmap is not None:
            scaled = self._scaled_pixmap(page)
            painter.drawPixmap(page, scaled, QRectF(scaled.rect()))
            if self.review[0]:
                paint_review_mark(painter, page, *self.review)
            if self.badge:
                metrics = painter.fontMetrics()
                box = QRectF(0, 0, metrics.horizontalAdvance(self.badge) + 16, metrics.height() + 8)
                box.moveTopRight(page.topRight() + QPointF(-8, 8))
                painter.setBrush(QColor(tokens.warning_solid))
                painter.drawRoundedRect(box, RADIUS_SM, RADIUS_SM)
                painter.setPen(QColor(tokens.on_solid))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self.badge)
        elif self.message:
            painter.setPen(QColor(tokens.text))
            painter.drawText(page.adjusted(24, 24, -24, -24).translated(0, -18),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                             self.message)


class PreviewPane(Surface):
    rendered = Signal()           # a render finished; the list's thumbnail may be new
    rendered_target = Signal(object)  # exact source path for affected thumbnail rows
    partner_requested = Signal(object)   # the language chip: the Path of the slide's file in the other language
    compile_requested = Signal(str)      # the deck-context chip: compile the deck in this view
    slide_requested = Signal(int)        # the wheel ran past the first/last reveal step: -1 the slide before, +1 after
    version_revert_requested = Signal(str)       # the version buttons (version_bar): id_slug
    version_overwrite_requested = Signal(str)
    version_level_requested = Signal(str, str)   # id_slug, level
    version_new_slide_requested = Signal(str)
    _finished = Signal(object)    # a _Job, from the worker thread
    _batch_progressed = Signal(object)
    _batch_finished = Signal(object, str)
    _steps_ready = Signal(object, object, str)   # (key, result, error), from the step queue's thread
    _looked_up = Signal(object, object, object, object, object)   # slot, identity, future, receiver, result
    _prefetch_done = Signal(object, object, object)        # (context, identity, result), read ahead

    def __init__(self, app, state: WorkspaceState,
                 buffer: Callable[[], Optional[str]]) -> None:
        """`buffer()` gives the text of the slide in the Source view,
        or None when it is not open there."""
        super().__init__()
        self.app = app
        self.state = state
        self._buffer = buffer
        self._target: Optional[PreviewTarget] = None
        self._row: Optional[SlideRow] = None
        self._language: Optional[str] = None
        self._title = ""
        self._message = ""
        self._busy = False
        self._batch_cancel = None
        self._batch_status = ""
        self._generation = 0
        self._active: Optional[_Job] = None
        self._pending = None
        self._lifetime = _Lifetime(self)
        self._renders = RenderService()
        # The render store's lookups, page reads and image decodes run here, not in the selection executor: a lookup
        # must not wait behind a long validation. One pending lookup per slot ('page', ('steps', key)); a newer one
        # for the slot replaces it, and a selection change drops them all.
        self._display_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='preview-display')
        self._looked_up.connect(self._on_looked_up)
        # Read ahead on a separate worker. A selected lookup can reuse these decoded pixels by digest.
        self.deck_targets: Callable[[], list] = lambda: []
        self._prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='preview-prefetch')
        self.model = PreviewModel()           # what the pane remembers (preview_model): pages held, read ahead, ...
        self._prefetch_done.connect(self._on_prefetched)
        self._changed_at = 0.0                # when the slide on show last changed (time.monotonic)
        self._defer_checks = False            # scrolling: show what is held, check once the selection rests
        self._remote = {}
        self._shown_mtime = 0
        self._shown_language = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        # Autosave already waits for typing to settle. Coalesce save notifications in this event-loop turn
        # without adding another 300 ms before starting the focused preview.
        self._debounce.setInterval(0)
        self._debounce.timeout.connect(self._launch_pending)
        # What the page on show was rendered from: ((target key, view, language), content hash of its text).
        self._shown_page: tuple | None = None
        self._buffer_notice = QTimer(self)
        self._buffer_notice.setSingleShot(True)
        self._buffer_notice.setInterval(150)
        self._buffer_notice.timeout.connect(self._refresh)
        self._validation_poll = PollTimer(self, 5000)
        self._validation_poll.timeout.connect(self._poll_selection)
        self._validation_poll.start()
        self.destroyed.connect(self._lifetime.close)
        self._error = ""
        self._record = None
        self._pdf_copies = ExitStack()
        self._last_request = None      # observes publication after the pixels arrive
        # The step bar: page lists of all-steps renders, rendered one at a time in the background.
        self._steps = StepRenderQueue(self._steps_busy, self._steps_done, read_pages=lambda pages: pages)
        self._context_modes: dict[tuple, Optional[str]] = {}   # (target key, view, language) -> deck_context mode
        self._auto_rendered: set[tuple] = set()    # (target key, view, language, mtime) of slides rendered on show
        # An edit of the open deck, (failed title, summary, change(path, text), cleanup) -> done: the slide list's
        # `edit`, which the window hands over. Without it the ticks of the step bar are not editable.
        self.edit_deck: Optional[Callable[..., bool]] = None
        # The slides around the focused one, [(target, row)]: the centre column knows the deck's order.
        self.neighbours: Callable[[], list] = lambda: []
        self._finished.connect(self._on_finished)
        self._batch_progressed.connect(self._on_batch_progress)
        self._batch_finished.connect(self._on_batch_finished)
        self._steps_ready.connect(self._on_steps_ready)
        self._probe = QTimer(self)
        self._probe.setSingleShot(True)
        self._probe.setInterval(PROBE_MS)
        self._probe.timeout.connect(self._probe_steps)
        self._settle = QTimer(self)      # restarted by every new slide: the count waits for the selection to rest
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self._settled)
        self._version_state = None                   # the Source view's VersionState (version_bar)
        self._chips_built: Optional[list] = None     # what the chips were built from, and the menu: a poll finds
        self._menu_built: Optional[tuple] = None     # them unchanged and leaves them

        # The pane's width never depends on what it shows (a long title, chip, notice or step label): an explicit minimum
        # replaces the layout's, so the slide list beside it cannot be pushed narrower when a slide's content arrives.
        self.setMinimumWidth(PAGE_MIN_WIDTH + 2 * PANE_SIDE_MARGIN)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANE_SIDE_MARGIN, SPACE.xl, PANE_SIDE_MARGIN, SPACE.xl)
        layout.setSpacing(SPACE.md)
        self._block_notice = Surface()
        self._block_notice.setObjectName(q.CHIP)
        self._block_notice.setProperty("tone", "info")
        notice = QHBoxLayout(self._block_notice)
        notice.setContentsMargins(SPACE.lg, SPACE.md, SPACE.lg, SPACE.md)
        self._block_text = QLabel()
        self._block_text.setWordWrap(True)
        notice.addWidget(self._block_text, 1)
        library = Button("Show in Library", "secondary", compact=True)
        library.clicked.connect(lambda: self.app.slide_list.show_in_library())
        notice.addWidget(library)
        self._block_notice.hide()
        layout.addWidget(self._block_notice)
        top = QHBoxLayout()
        top.setSpacing(SPACE.md)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(SPACE.sm)
        top.addLayout(self._chips, 1)
        self._versions = VersionBar(lambda: self.app.theme.tokens)      # top right: Revert, Overwrite, Patch, Minor, Major
        self._versions.revert_requested.connect(self.version_revert_requested)
        self._versions.overwrite_requested.connect(self.version_overwrite_requested)
        self._versions.level_requested.connect(self.version_level_requested)
        self._versions.new_slide_requested.connect(self.version_new_slide_requested)
        top.addWidget(self._versions)
        layout.addLayout(top)
        self._page = PageView(lambda: self.app.theme.tokens)
        self._page.render_button.clicked.connect(self.render_now)
        self._page.wheeled.connect(self._on_wheel)
        layout.addWidget(self._page, 1)
        self._reveal = RevealBar(lambda: self.app.theme.tokens)
        self._reveal.step_selected.connect(self._on_step_selected)
        self._reveal.view_requested.connect(self.state.set_view)
        self._reveal.expanded_changed.connect(self._on_reveal_expanded)
        self._reveal.tick_toggled.connect(self._on_tick_toggled)
        layout.addWidget(self._reveal)
        for key, delta in ((Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)):
            shortcut = QShortcut(QKeySequence(Qt.Modifier.ALT | key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda delta=delta: self._reveal.move(delta))

        # The status line (the outdated/rendering notice, its button) keeps its height when nothing is shown, so the
        # slide above it does not jump when the next slide has a notice and the last one had none.
        self._status_row = Surface()
        status = QHBoxLayout(self._status_row)
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(SPACE.md)
        self._status_chip = Chip("", "muted", elide=True)   # a long notice shortens, it does not widen the pane
        self._status_chip.setProperty("plain", True)         # muted: text on the card, not a black pill in dark mode
        status.addWidget(self._status_chip)
        self._status_button = Button("Render now", "secondary", compact=True)
        self._status_button.clicked.connect(self._status_clicked)
        self._status_draft = False   # the button renders the unsaved buffer, not the saved file
        status.addWidget(self._status_button)
        self._stop_batch = Button("Stop", "secondary", compact=True)
        self._stop_batch.clicked.connect(self.cancel_batch)
        self._stop_batch.hide()
        status.addWidget(self._stop_batch)
        self._error_label = QLabel()
        self._error_label.setObjectName(q.SOURCE_NOTE)
        self._error_label.setWordWrap(True)
        status.addWidget(self._error_label, 1)
        self._status_chip.set_text("Rendering…")
        self._status_row.setMinimumHeight(max(self._status_chip.sizeHint().height(), self._status_button.sizeHint().height()))
        self._status_chip.set_text("")
        layout.addWidget(self._status_row)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE.xl)
        self._id = QLabel()
        self._id.setObjectName(q.PREVIEW_ID)
        self._name = ElidedLabel()      # a long title (a title slide's) is cut with …, it does not widen the pane
        self._name.setObjectName(q.PREVIEW_TITLE)
        footer.addWidget(self._id)
        footer.addWidget(self._name, 1)
        self._render = SplitButton("Render this slide")
        self._render.clicked.connect(self.render_now)
        footer.addWidget(self._render)
        layout.addLayout(footer)
        self._menu: Optional[PopoverMenu] = None
        self._menu_stale = False

        state.view_changed.connect(self._on_context_changed)
        state.language_changed.connect(self._on_context_changed)
        self._refresh()

    # -- what is shown -----------------------------------------------------------------

    @property
    def language(self) -> str:
        """The language the page is typeset in: the top bar's, but the file's own for a translation partner that the
        language chip showed in place of the slide's file in the language being edited."""
        return self._language or self.state.language

    def show_slide(self, target: Optional[PreviewTarget], row: Optional[SlideRow], title: str, message: str,
                   language: Optional[str] = None) -> None:
        """Show `target` (None: just `message`). `row` is its row in the open deck, if it has one; `language` the
        one to typeset it in when that is not the top bar's."""
        previous = self._target
        changed = (target is None or previous is None or target.key != previous.key
                   or target.source_path != previous.source_path
                   or getattr(target.deck, 'path', None) != getattr(previous.deck, 'path', None))
        mtime = _mtime(target.source_path) if target else 0
        if changed or mtime != self._shown_mtime or language != self._shown_language:
            self._invalidate()
        if changed:
            self.model.invalidate_slide()
            self._steps.drop_background()
            now = time.monotonic()
            # Another slide within SCROLLING_MS of the last change: scrolling. Its checks would be superseded before
            # they answer, so none starts until the selection rests (_settled); a single click checks at once.
            self._defer_checks = target is not None and now - self._changed_at < SCROLLING_MS / 1000
            self._changed_at = now
            if target is not None:
                self._settle.start()
        self._target, self._row, self._title, self._message = target, row, title, message
        block = row.deck_call.block if row else None
        self._block_notice.setVisible(bool(block))
        if block:
            block_title = self.app.slide_list.blocks.get(row.deck_call.source, block)
            decks = [d.name for d in decks_by(deck_calls(self.app.project, getattr(self.app, "decks", None)), "block").get(block, [])]
            count = len(decks)
            self._block_text.setText(
                f"From the topic block {block_title}. Reordering or removing it here changes the block, "
                f"which {count} {'deck uses' if count == 1 else 'decks use'}: {', '.join(decks)}.")
        self._language = language
        self._shown_mtime = mtime
        self._shown_language = language
        self._refresh()

    def set_version_state(self, state) -> None:
        """The version buttons for the slide in the Source view (a VersionState), None to hide them."""
        self._version_state = state
        self._show_versions()

    def _show_versions(self) -> None:
        """Shown for the current file of the slide on show, not for a frozen version or another slide."""
        state, target = self._version_state, self._target
        shown = state is not None and target is not None and not target.version and state.id_slug == target.id_slug
        self._versions.set_state(state if shown else None)

    @property
    def target_path(self) -> Optional[Path]:
        return self._target.source_path if self._target is not None else None

    def _show_partner(self, path: Path) -> None:
        """The language chip: show the slide's file in the other language, if it is still there."""
        if path.is_file():
            self.partner_requested.emit(path)
        else:
            self.app.toast.show_message(f"{path.name} is missing: the translation link points to a file that is gone.")

    def _on_context_changed(self, _value: str) -> None:
        self._invalidate()
        self._refresh()

    def buffer_changed(self, path: Path) -> None:
        """Cancel this slide's queued views and refresh its age after typing pauses."""
        renderer = self._renders._background
        if renderer is not None:
            renderer.scheduler.cancel_group(f"other:{path.resolve()}")
        if self._target is not None and path == self._target.source_path:
            self._invalidate()
            self._buffer_notice.start()

    def _poll_selection(self):
        if self._target is not None and self.isVisible() and not self._closed:
            self.model.lookups.asked = None
            # Ask the store again for the saved step lists, but keep showing them until it answers: dropping them
            # here put "Counting…" in the step bar and the last step on the page every 5 s.
            self.model.steps.recheck_saved()
            self._refresh()

    @staticmethod
    def _capture(target: PreviewTarget, text: str | None = None) -> SourceRevision | None:
        try:
            return SourceRevision.capture(target.source_path, text)
        except (OSError, ValueError):
            return None

    def _selection_revision(self, target: PreviewTarget, saved: SourceRevision | None) -> SourceRevision | None:
        buffer = self._buffer()
        if buffer is None or (saved is not None and buffer == saved.text):
            return saved
        return self._capture(target, buffer)

    def _matches(self, result: _PageResult, revision: SourceRevision | None) -> bool:
        target = self._target
        return (target is not None and not target.hidden and result.ticket == self._generation
                and result.key == (target.key, self.state.view, self.language) and revision is not None
                and result.request.revision.path == revision.path
                and result.request.revision.content_hash == revision.content_hash
                and result.request.revision.mtime_ns == revision.mtime_ns)

    def _decode_hints(self, spec: PreviewRequest) -> set[str]:
        key = (spec.target.key, spec.view, spec.language)
        held = self.model.pixmaps.get(key)
        recent = self.model.steps.pixmap
        ahead = self.model.ahead
        ident = (*key, spec.revision.mtime_ns)
        prefetched = ahead.prefetched.get(ident) if ahead.context == (self._deck_name(), *key[1:]) else None
        return {digest for digest in (held.image_hash if held else None, recent[0] if recent else None,
                                      prefetched[1] if prefetched else None) if digest is not None}

    def _local_page(self, target: PreviewTarget, revision: SourceRevision | None) -> _PageResult | None:
        adhoc = self.model.adhoc
        if (revision is not None and adhoc.holds((target.key, self.state.view, self.language))
                and adhoc.value.ticket == self._generation and adhoc.text == revision.text):
            return adhoc.value
        return None

    def _selected_lookup(self, target: PreviewTarget, revision: SourceRevision | None) -> _PageResult | None:
        if revision is None:
            return None
        spec = PreviewRequest(target, revision, self.state.view, self.language)
        ticket = self._generation
        ident = (target.key, spec.view, spec.language, revision.mtime_ns, revision.content_hash)
        recording = (self._last_request is not None and not self._last_request.done.is_set()
                     and self._local_page(target, revision) is not None)
        if not self._defer_checks and not recording and self.model.lookups.asked != (ticket, ident):
            self.model.lookups.asked = (ticket, ident)
            renderer = self._renders.renderer(target.context)
            choice = self.model.steps.choice.get(target.source_path)
            hints = self._decode_hints(spec)
            missing = _PageResult(ticket, spec, 'missing')
            self._look_up('page', ident, lambda: _read_pages(renderer, ticket, spec, choice, hints),
                          lambda result: self._page_found(result if result is not None else missing))
        result = self.model.lookups.stored
        return result if result is not None and self._matches(result, revision) else None

    def _check_when_recorded(self, request) -> None:
        """Check the delivered pixels as soon as publication finishes."""
        def poll():
            if self._closed:
                return
            if not request.done.is_set():
                QTimer.singleShot(50, poll)
                return
            self.rendered_target.emit(request.spec.target.source_path)
            if self._last_request is request:
                self._last_request = None
                self.model.lookups.asked = None
                self._refresh()
        if getattr(request, 'done', None) is not None:
            QTimer.singleShot(50, poll)

    def _remember(self, result: _PageResult, text: str, note: str = "", *, full: bool = False) -> None:
        self.model.adhoc.hold(result, text, note, full=full)
        if not note and not full and result.request.complete and result.decoded is not None:
            _, digest, pixmap = result.decoded
            revision = result.request.revision
            self.model.pixmaps.put(result.key, pixmap, revision.mtime_ns, revision.content_hash, digest)

    def _deck_name(self) -> str:
        deck = self.state.deck
        return deck.name if deck is not None else ""

    def _look_up(self, slot, identity: tuple, work: Callable, arrive: Callable) -> None:
        """Run `work()` (a store lookup with its reads and decodes) on the display worker; `arrive(its result)` runs
        on the GUI thread, if the selection is still the one asked for (the generation is part of the identity)."""
        identity = (self._generation, identity)
        if self._closed or not self.model.lookups.begin(slot, identity):
            return
        future = self._display_executor.submit(work)
        self.model.lookups.add(slot, identity, future)
        owner = weakref.ref(self)

        def finished(done):
            pane = owner()
            if pane is None or pane._closed or done.cancelled():
                return
            try:
                found = done.result()
            except Exception:  # noqa: BLE001 -- the store is a help: a failed lookup finds nothing
                found = None
            try:
                pane._looked_up.emit(slot, identity, done, arrive, found)
            except RuntimeError:     # the pane is gone
                pass

        future.add_done_callback(finished)

    def _on_looked_up(self, slot, identity: tuple, future, arrive: Callable, found) -> None:
        if self._closed or self.model.lookups.slots.get(slot) != (identity, future):
            return
        self.model.lookups.arrive(slot, identity)
        if identity[0] == self._generation:
            arrive(found)

    def _page_found(self, result: _PageResult) -> None:
        target = self._target
        if target is None or not self._matches(result, self._selection_revision(target, self._capture(target))):
            self._refresh()
            return
        self.model.lookups.stored = result
        if result.status == 'current' and result.pages and target.needs_context and self._last_request is None:
            self._context_modes[result.key] = deck_context.DECK
            if self.model.adhoc.holds(result.key):
                self.model.adhoc.forget()
        self._refresh()

    def _preload_order(self) -> list:
        """The slides whose stored pages are read ahead, nearest first: one after, one before, two after, ... through
        the whole view of the deck (`deck_targets`), or the neighbours when the deck's slides are not known."""
        everything = self.deck_targets()
        if not everything:
            return [other for other, _row in self.neighbours()]
        here = self._row.position if self._row is not None else None
        index = next((i for i, (_t, row) in enumerate(everything) if row.position == here), None)
        if index is None:                      # the slide on show is not one of the deck's (a file, a hidden slide)
            shown = self._target.key if self._target is not None else None
            return [target for target, _row in everything if target.key != shown]
        order = []
        for distance in range(1, len(everything)):
            for i in (index + distance, index - distance):
                if 0 <= i < len(everything):
                    order.append(everything[i][0])
        return order

    def _prefetch_neighbours(self) -> None:
        """Warm the decode cache outward from the selected slide without delaying its lookup."""
        background = getattr(self.app, "background", None)
        if background is None or self._closed:
            return
        view, language, deck = self.state.view, self.language, self._deck_name()
        ticket = self._generation
        context = (deck, view, language)
        ahead = self.model.ahead
        ahead.switch_context(context)
        ahead.cancel_queued()
        order = [(other, (other.key, view, language, _mtime(other.source_path))) for other in self._preload_order()]
        owner = weakref.ref(self)

        def read(other, held, decode):
            if held is None:
                time.sleep(PRELOAD_PAUSE)
            revision = PreviewPane._capture(other)
            renderer = background.renderer
            if revision is None or renderer is None:
                return None
            spec = PreviewRequest(other, revision, view, language)
            if held is not None:
                return _PageResult(ticket, spec, 'decoded', pages=(held,),
                                   decoded=(0, hashlib.sha256(held).hexdigest(), QImage.fromData(held)))
            return _read_pages(renderer, ticket, spec, None, prefetch=True, decode=decode)

        for other, ident, decode, held in ahead.plan(order, time.monotonic()):
            future = self._prefetch_executor.submit(read, other, held, decode)
            ahead.prefetching[ident] = future

            def finished(done, ident=ident):
                pane = owner()
                if pane is None or pane._closed or done.cancelled():
                    return
                try:
                    found = done.result()
                except Exception:  # noqa: BLE001 -- a page read ahead is a help, not needed
                    found = None
                try:
                    pane._prefetch_done.emit(context, ident, found)
                except RuntimeError:
                    pass

            future.add_done_callback(finished)

    def _on_prefetched(self, context, ident, result: _PageResult | None) -> None:
        if self._closed or context != self.model.ahead.context:
            return
        found = None
        if result is not None and result.decoded is not None:
            i, digest, image = result.decoded
            found = result.pages[i], digest, image
        self.model.ahead.arrived(context, ident, found)

    def _checking(self) -> bool:
        """Whether a check of the slide on show is still out (or waits for the selection to rest)."""
        return self._defer_checks or 'page' in self.model.lookups

    def _refresh(self) -> None:
        if self._closed:
            return
        target, row = self._target, self._row
        view, language = self.state.view, self.language
        deck = self.state.deck
        marked = target is not None and row is not None and deck is not None and row.review
        self._page.set_review(deck.review_text if marked else "", row.review_note if marked else "")
        job = self._pending[1] if self._pending else self._active
        busy_here = (target is not None and job is not None and job.generation == self._generation
                     and job.target_key == target.key and (job.view, job.language) == (view, language))
        chips = []
        if target is not None:
            outline = self.state.current_outline()
            own = own_language(target.id_slug, languages.project_languages(self.app.project).codes)
            links = translation_group(self.app.project, target.id_slug, links=outline.links if outline else None)
            partner = partner_link(links)
            mode_key = (target.key, view, language)
            for icon, text, tone, tooltip in chips_for(
                    target, row, view, language, own, links, self._context_modes.get(mode_key),
                    mode_key in self._context_modes):
                jump = icon == "language" and partner is not None
                compile_deck = icon == "warning" and target.needs_context and row is not None
                chips.append((icon, text, tone, tooltip, partner.path if jump else None, view if compile_deck else None))
        if chips != self._chips_built:       # the 5 s poll finds them as they were: nothing to rebuild
            self._chips_built = chips
            clear_layout(self._chips)
            for icon, text, tone, tooltip, jump, compile_view in chips:
                # Made in the pane: a widget without a parent is briefly a window of its own, and that closes any open
                # menu or popup.
                chip = Chip(text, tone, icon, self, pressable=jump is not None or compile_view is not None, elide=True)
                chip.setToolTip(tooltip)
                if jump is not None:
                    chip.clicked.connect(lambda path=jump: self._show_partner(path))
                elif compile_view is not None:
                    chip.clicked.connect(lambda v=compile_view: self.compile_requested.emit(v))
                self._chips.addWidget(chip)
            self._chips.addStretch(1)

        self._show_versions()
        self._id.setText(target.bare_id if target else "")
        self._name.set_full_text(shortened(self._title) if target else "")
        self._name.setToolTip(self._title if target else "")
        self._render.setVisible(target is not None)
        self._render.setEnabled(target is not None)
        hidden = target is not None and (target.hidden or (row is not None and row.hidden))
        self._render.buttons()[0].setEnabled(target is not None and not hidden and self._batch_cancel is None)
        self._render.buttons()[0].setToolTip("This slide is hidden in the selected view." if hidden
                                           else "Render the saved file in the selected view")
        self._render.set_text(f"Render this slide · {short_view(view)} · {language}")

        saved = self._capture(target) if target is not None and not hidden else None
        revision = self._selection_revision(target, saved) if target is not None and not hidden else None
        whole = self._selected_lookup(target, revision) if revision is not None else None
        local = self._local_page(target, revision) if revision is not None else None
        step_state = self._current_steps(target, saved, local) if saved is not None else None
        steps = self._update_reveal(target, row, step_state, whole)
        status, tone, can_render = self._show_selected_page(target, hidden, busy_here, whole, local, steps,
                                                                 step_state, revision)
        if busy_here:
            progress = "Rendering…" if job is self._active else "Waiting to render…"
            status = f"{status} · {progress}" if self._page.pixmap is not None else progress
            tone, can_render = "info", False
        elif self._error:
            status = f"{status} · Render failed" if self._page.pixmap is not None else "Render failed"
            tone, can_render = "error", target is not None
        self._status_draft = bool(revision is not None and saved is not None and not busy_here
                                  and revision.text != saved.text and local is None)
        if self._status_draft:
            if not status:
                status, tone = "Unsaved edits are not in this preview", "warning"
            can_render = True
        if self._batch_status:
            if self._batch_cancel is not None:
                status = f"{status} · {self._batch_status}" if self._page.pixmap is not None else self._batch_status
                tone, can_render = "info", False
            elif status:
                status = f"{status} · {self._batch_status}"
            else:
                status, tone = self._batch_status, "info"
        self._stop_batch.setVisible(self._batch_cancel is not None)
        if self._batch_cancel is not None:
            self._page.render_button.hide()
        self._status_button.setText("Render draft · Ctrl+Enter" if self._status_draft else "Render now")
        self._status_chip.setVisible(bool(status))
        self._status_chip.set_text(status)
        self._status_chip.setToolTip(status)
        self._status_chip.set_tone(tone)
        self._status_button.setVisible(can_render)
        self._error_label.setText(self._error)
        self._error_label.setVisible(bool(self._error))
        self._rebuild_menu()

    def _page_pixmap(self, result: _PageResult, index: int) -> QPixmap | None:
        if result.decoded is not None and result.decoded[0] == index:
            _, digest, image = result.decoded
        else:
            digest, image = hashlib.sha256(result.pages[index]).hexdigest(), None
        recent = self.model.steps.pixmap
        if recent is not None and recent[0] == digest:
            return recent[1]
        key, revision = result.key, result.request.revision
        held = self.model.pixmaps.get(key)
        if held is not None and held.image_hash == digest:
            return held.pixmap
        prepared = self.model.steps.image
        if image is None and prepared is not None and prepared[0] == digest:
            image = prepared[1]
        if isinstance(image, QPixmap):
            pixmap = image
        elif image is not None:
            pixmap = QPixmap.fromImage(image)
        else:
            ahead = self.model.ahead.page((*key, revision.mtime_ns), (self._deck_name(), *key[1:]), digest)
            pixmap = ahead[0] if ahead is not None else QPixmap.fromImage(QImage.fromData(result.pages[index]))
        if pixmap.isNull():
            return None
        pixmap = display_pixmap(pixmap)
        if result.status == 'current' and index == result.count - 1 and result.request.complete:
            pixmap = self.model.pixmaps.put(key, pixmap, revision.mtime_ns, revision.content_hash, digest)
        self.model.steps.pixmap = (digest, pixmap)
        return pixmap

    @staticmethod
    def _page_label(result: _PageResult, index: int) -> str:
        spec, record = result.request, result.record
        view, language = spec.view, spec.language
        known_revision = record is None
        if record is not None:
            unit = record.get('unit', '').rsplit(':', 3)
            view, language = unit[-2:] if len(unit) == 4 else ("", "")
            root = spec.target.context.root.absolute()
            source = spec.revision.path
            known_revision = (len(unit) == 4 and unit[1] == spec.target.id_slug and source.is_relative_to(root)
                              and [render_key.KIND_PROJECT, source.relative_to(root).as_posix(),
                                   spec.revision.content_hash] in record.get('manifest', ()))
        version = (slide_versioning.version_text(spec.revision.text) or spec.target.version) if known_revision else None
        origin = f"{short_view(view)} · {language}" if view in VIEW_LABELS and language else "Unknown origin"
        revision = (slide_versioning.version_label(version) if version else "Unversioned") if known_revision else "Unknown revision"
        label = f"{origin} · {revision}"
        if result.count > 1:
            label += f" · Step {index + 1}/{result.count}"
        prefix = {'previous': 'Previous render', 'reference': 'Instructor reference',
                  'rendered': 'Temporary preview'}.get(result.status)
        return f"{prefix} · {label}" if prefix else label

    def _show_selected_page(self, target, hidden, busy, whole, local, steps, step_state, revision) -> tuple:
        """Choose the page and describe the result that supplied its pixels."""
        self._record = None
        empty = "", "muted", False
        if target is None:
            self._page.show_message(self._message or "Select a slide in the list.", False)
            return empty
        if hidden:
            self._page.show_message(f"This slide is not typeset in the {VIEW_LABELS[self.state.view]} view.", False)
            return empty
        choice = self.model.steps.choice.get(target.source_path)
        result = whole if whole is not None and whole.count else None
        if local is not None and (result is None or (local.request.target.needs_context and result.status != 'current')
                                  or not local.request.complete):
            result = local
        if step_state is not None:
            key, step_revision, _draft, scan = step_state
            restricted = (target.macro in ("slidestep", "slidefinal") or scan.own_frame_spec is not None
                          or scan.frame_breaks or (scan.final_flag and self.state.view != reveal_steps.INSTRUCTOR))
            matching_steps = steps is not None and self._matches(steps, step_revision)
            needs_steps = restricted or result is None or not result.pages
            same_source = revision is not None and (revision.content_hash == step_revision.content_hash or
                                                    (local is not None and local.request.revision == step_revision))
            if same_source and matching_steps and (result is None or (steps.count > 1 and needs_steps
                                                                     and (restricted or choice is not None))):
                result = steps
            elif (same_source and not matching_steps and choice is not None and needs_steps and scan.may_reveal
                  and key not in self.model.steps.failed):
                self._page.show_message(LOADING, False)
                return LOADING, "info", False
        if result is not None:
            index = min(max(result.count if choice is None else choice, 1), result.count) - 1
            pixmap = self._page_pixmap(result, index)
            if pixmap is not None:
                self._record = result.record
                self._page.show_image(pixmap)
                self._shown_page = ((target.key, self.state.view, self.language), result.request.revision.content_hash)
                label = self._page_label(result, index)
                if result is local and self.model.adhoc.note:
                    label = f"{label} · {self.model.adhoc.note}"
                current = result.status == 'current'
                return label, "info" if current else "warning", not current
        if self._checking():
            # An edit of the slide on show: keep its page on the screen, marked as older, until the answer comes.
            # Swapping it for the message and back would flicker at every pause between keystrokes.
            shown = self._shown_page
            if (shown is not None and self._page.pixmap is not None and revision is not None
                    and shown[0] == (target.key, self.state.view, self.language)
                    and shown[1] != revision.content_hash):
                self._page.show_image(self._page.pixmap, SOURCE_CHANGED)
                return SOURCE_CHANGED, "warning", True
            self._page.show_message(LOADING, False)
            return LOADING, "info", False
        if whole is not None:
            adhoc = self.model.adhoc
            label = "Unknown origin"
            if adhoc.holds(whole.key) and adhoc.text != revision.text:
                old = adhoc.value
                older = self._page_pixmap(old, old.count - 1)
                label = self._page_label(old, old.count - 1)
                self._record = old.record if older is not None else None
            else:
                held = self.model.pixmaps.get(whole.key)
                older = held.pixmap if held is not None and held.content_hash != revision.content_hash else None
            if older is not None:
                self._page.show_image(older, SOURCE_CHANGED)
                return f"{SOURCE_CHANGED} · {label}", "warning", True
        self._page.show_message("Rendering…" if busy else f"No preview for the {VIEW_LABELS[self.state.view]} view yet.",
                                not busy)
        if not busy:
            self._render_context_slide(target)
        return empty

    # -- the reveal steps --------------------------------------------------------------------

    def _steps_busy(self) -> bool:
        """The pane is rendering for the user: background step renders wait (read from the queue's thread)."""
        return self._active is not None or self._pending is not None

    def _steps_done(self, key: tuple, result: _PageResult, error: str) -> None:
        try:
            self._steps_ready.emit(key, result if not error else None, error)
        except RuntimeError:     # the pane is gone
            pass

    def _steps_key(self, spec: PreviewRequest, ticket: int, temporary: bool) -> tuple:
        target, revision = spec.target, spec.revision
        identity = target.key[1:3] + target.key[5:]       # the all-steps render drops the call's restriction
        return ("draft" if temporary else "saved", str(revision.path), identity, spec.view, spec.language,
                (ticket, revision.mtime_ns, revision.content_hash))

    def _current_steps(self, target: PreviewTarget, saved: SourceRevision | None = None,
                       local: _PageResult | None = None):
        """The key, captured revision, draft flag and scan for this slide's all-steps render."""
        if saved is None:
            saved = self._capture(target)
        if saved is None:
            return None
        adhoc = self.model.adhoc
        if local is None:
            local = self._local_page(target, self._selection_revision(target, saved))
        temporary = local is not None and adhoc.full
        revision = local.request.revision if temporary else saved
        spec = PreviewRequest(target, revision, self.state.view, self.language, RenderOptions(all_steps=True))
        key = self._steps_key(spec, self._generation, temporary)
        scan = self.model.steps.scan((revision.path, revision.content_hash),
                                     lambda: reveal_steps.scan_slide(revision.text))
        return key, revision, temporary and bool(adhoc.note), scan

    def _after_render(self, job: _Job) -> None:
        """Count the reveal steps of the accepted render."""
        if not job.steps_ok or job.spec is None:
            return
        current = self._current_steps(job.spec.target)
        if current is not None:
            key, revision, draft, scan = current
            # The foreground PDF already has the steps of an unrestricted standalone render.
            reuse = (job.spec.complete and job.spec.revision == revision and not job.spec.target.needs_context
                     and (not scan.final_flag or job.view == reveal_steps.INSTRUCTOR))
            self._request_steps(job.spec.target, key, revision, draft, FOREGROUND, job.request if reuse else None)

    def _request_steps(self, target: PreviewTarget, key: tuple, revision: SourceRevision, draft: bool,
                       priority: int, rendered: RenderRequest | None = None) -> None:
        """Queue the all-steps render for this pane selection."""
        if key in self.model.steps.pages:
            return
        spec = PreviewRequest(target, revision, key[3], key[4], RenderOptions(saved=not draft, all_steps=True))

        def render():
            self._queue_steps(spec, key, priority, rendered)

        if key[0] == 'draft':
            render()
        else:
            self._adopt_stored_steps(spec, key, render)

    def _queue_steps(self, spec: PreviewRequest, key: tuple, priority: int,
                     rendered: RenderRequest | None = None) -> None:
        service, log = self._renders, self.app.log
        ticket = key[-1][0]
        renderer = service.renderer(spec.target.context)

        def build(cancel):
            request = rendered or service.request(spec.target, spec.revision.text, spec.view, spec.language, log, spec=spec)
            pdf = request.wait(cancel)[0]
            found = _read_pages(renderer, ticket, spec, None)
            if found.status == 'current':
                return found
            record = request.preview_result.record if request.preview_result is not None else None
            return _PageResult(ticket, spec, 'previous' if record is not None else 'rendered', record,
                               tuple(reveal_steps.read_pages(pdf)))

        self._steps.submit(key, priority, build)

    def _adopt_stored_steps(self, spec: PreviewRequest, key: tuple,
                            render: Optional[Callable[[], None]] = None) -> None:
        """Read the chooser's step pages off-thread and queue a count if none were found."""
        background = getattr(self.app, "background", None)
        if key in self.model.steps.pages and key not in self.model.steps.recheck:
            return
        if background is None:
            if render is not None:
                render()
            return
        if render is not None:
            self.model.steps.count_after[key] = render
        choice = self.model.steps.choice.get(spec.target.source_path)
        ticket = key[-1][0]
        hints = self._decode_hints(spec)
        missing = _PageResult(ticket, spec, 'missing')

        def read():
            renderer = background.renderer
            return _read_pages(renderer, ticket, spec, choice, hints) if renderer is not None else missing

        self._look_up(('steps', key), key, read,
                      lambda result: self._steps_found(key, result if result is not None else missing))

    def _accepts_steps(self, key: tuple, result: _PageResult) -> bool:
        if result.ticket != self._generation or key != self._steps_key(result.request, result.ticket, key[0] == 'draft'):
            return False
        spec = result.request
        if key[0] == 'draft':
            target = self._target
            current = self._current_steps(target) if target is not None else None
            return current is not None and key[:3] + key[4:] == current[0][:3] + current[0][4:]
        saved = self._capture(spec.target)
        return (saved is not None and spec.revision.path == saved.path
                and (spec.revision.mtime_ns, spec.revision.content_hash) == (saved.mtime_ns, saved.content_hash))

    def _steps_found(self, key: tuple, result: _PageResult) -> None:
        if not self._accepts_steps(key, result):
            self.model.steps.count_after.pop(key, None)
            return
        changed, render = self.model.steps.read(key, self._keep_step_decode(result))
        if changed:
            self._refresh()
        if render is not None:
            render()

    def _keep_step_decode(self, result: _PageResult) -> _PageResult:
        if result.decoded is None or result.decoded[2] is None:
            return result
        i, digest, image = result.decoded
        self.model.steps.image = (digest, image)
        return replace(result, decoded=(i, digest, None))

    def _settled(self) -> None:
        """The selection rested: the step bar may count the slide now."""
        self._defer_checks = False
        if self._target is not None and not self._closed:
            self._refresh()
            self._prefetch_neighbours()

    def _probe_steps(self) -> None:
        """Idle: count the steps of the slide on show and of the nearest slides."""
        target = self._target
        if target is None or self._closed or (self._row is not None and self._row.hidden):
            return
        if self._steps_busy():
            self._probe.start(PROBE_MS)
            return
        current = self._current_steps(target)
        if current is None:
            return
        key, revision, draft, scan = current
        if key not in self.model.steps.failed:
            self._request_steps(target, key, revision, draft, BACKGROUND)
        if scan.version_dependent and self._reveal.expanded:
            self._request_other_views(target, key, revision, draft, self._served_views())
        for other, _row in self.neighbours()[:NEIGHBOURS]:
            saved = self._capture(other)
            if saved is None:
                continue
            spec = PreviewRequest(other, saved, self.state.view, self.language, RenderOptions(all_steps=True))
            other_key = self._steps_key(spec, self._generation, False)
            if other_key not in self.model.steps.failed:
                self._request_steps(other, other_key, saved, False, BACKGROUND)

    def _block_calls(self, row: Optional[SlideRow]) -> tuple[list, list]:
        """(every slide call of the open deck, the calls that decide the steps at `row`'s place)."""
        deck = self.state.deck
        if row is None or deck is None:
            return [], []
        resolution = deck_language.resolve(deck)
        calls = resolution.calls
        physical = next((c for c in calls if c.identity == row.deck_call.identity), None)
        if physical is None:
            return calls, []
        occurrence = [c.expanded for c in calls if c.source == physical.source and (
            physical.index is None or c.call_start == physical.call_start)]
        group = deck_editor.step_block(resolution.deck.text, occurrence, physical.expanded)
        identities = {c.call_start for c in group}
        return calls, [c for c in calls if c.expanded.call_start in identities]

    def _served_views(self) -> list[str]:
        """The versions the selected place of the deck typesets; all of them for a slide shown without the deck."""
        if self._row is None:
            return list(VIEWS)
        block = self._block_calls(self._row)[1] or [self._row.call]
        return [v for v in VIEWS if any(c.included_in(v) for c in block)]

    def _request_other_views(self, target: PreviewTarget, key: tuple, revision: SourceRevision, draft: bool,
                             views: list[str]) -> None:
        for view in views:
            other = key[:3] + (view,) + key[4:]
            if view != key[3] and other not in self.model.steps.pages and other not in self.model.steps.failed:
                self._request_steps(target, other, revision, draft, BACKGROUND)

    def _on_steps_ready(self, key: tuple, result: _PageResult | None, error: str) -> None:
        if self._closed or key[-1][0] != self._generation or (not error and not self._accepts_steps(key, result)):
            return
        if not error and not result.pages:
            error = "the render has no pages"
        if not error:
            result = self._keep_step_decode(result)
        if not self.model.steps.rendered(key, result, error):
            self.app.log(f"    (reveal steps not counted: {error})")
        self._refresh()

    def _on_tick_toggled(self, view: str, step: int) -> None:
        """A tick of the step bar was clicked: add the step to (or take it from) what `view` typesets at this place of
        the open deck, by rewriting the deck's \\slidestep calls (deck_editor.steps_edit)."""
        target, row, deck, edit = self._target, self._row, self.state.deck, self.edit_deck
        if target is None or row is None or deck is None or edit is None:
            return
        current = self._current_steps(target)
        if current is None:
            return
        key, _revision, draft, scan = current
        pages = self.model.steps.pages.get(key)
        if pages is None:
            return
        rows = self._step_rows(target, row, key, pages.count, scan, draft)
        spec = rows[view]
        if not spec.editable or spec.plan is None:
            return
        steps = set(spec.plan.included) ^ {step}
        if not steps:
            self.app.toast.show_message("A version must keep at least one step: hide the slide in the "
                                        "visibility matrix instead.")
            return
        calls, block = self._block_calls(row)
        counts = self._step_counts(key, pages.count, scan)
        call = row.deck_call
        id_slug, project = call.id_slug, self.app.project
        wording = deck_editor.format_steps(steps, counts[view]) if len(steps) < counts[view] else "all steps"
        edit("Change steps failed", f"Set the steps of {id_slug} in {VIEW_LABELS[view]} to {wording} in {deck.name}",
             lambda path, text: deck_editor.set_steps_for_version(
                 path, text, calls, call, view, steps, counts, scan.final_flag),
             cleanup=lambda: reveal_steps.drop_dead_final_flag(project, id_slug))

    def _on_reveal_expanded(self, expanded: bool) -> None:
        if expanded:
            self._probe.start(0)

    def _on_wheel(self, direction: int) -> None:
        """As in a presentation: the wheel goes through the reveal steps of the slide, then on to the next slide
        (back: the previous one)."""
        stops = self._reveal.track.stops if self._reveal.isVisibleTo(self) else []
        step = self._reveal.step
        if stops and step in stops:
            position = stops.index(step) + direction
            if 0 <= position < len(stops):
                self._on_step_selected(stops[position])
                return
        self.slide_requested.emit(direction)

    def set_step_choice(self, path: Path, step: Optional[int]) -> None:
        """Which step the slide in `path` opens at (None: its last one)."""
        if step is None:
            self.model.steps.choice.pop(path, None)
        else:
            self.model.steps.choice[path] = step

    def _on_step_selected(self, step: int) -> None:
        target = self._target
        if target is not None:
            self.model.steps.choice[target.source_path] = step
            self._refresh()

    def _step_counts(self, key: tuple, n: int, scan: reveal_steps.SlideScan) -> dict[str, int]:
        counts = {key[3]: n}
        for view in VIEWS:
            if view != key[3]:
                pages = self.model.steps.pages.get(key[:3] + (view,) + key[4:])
                counts[view] = pages.count if pages is not None else (n if not scan.version_dependent else 0)
        return counts

    def _step_rows(self, target: PreviewTarget, row: Optional[SlideRow], key: tuple, n: int,
                   scan: reveal_steps.SlideScan, draft: bool = False) -> dict[str, RowSpec]:
        call = row.call if row is not None else None
        _calls, block = self._block_calls(row) if self.edit_deck is not None else ([], [])
        served = [v for v in VIEWS if any(c.included_in(v) for c in block)]
        counts = self._step_counts(key, n, scan)
        rows: dict[str, RowSpec] = {}
        for view in VIEWS:
            present = call is None or call.included_in(view)
            plan = reveal_steps.plan_for(call, view, counts[view], scan) if counts[view] and present else None
            editable, reason = False, ""
            if plan is not None and block:
                editable, reason = self._row_edit(block, view, served, counts, scan, plan, draft, key)
                if editable and not plan.marked:
                    plan = replace(plan, marked=True)      # a plain call: its ticks are all "in", and can be clicked
            rows[view] = RowSpec(view, plan, editable=editable, reason=reason, present=present)
        return rows

    def _row_edit(self, block: list, view: str, served: list[str], counts: dict[str, int],
                  scan: reveal_steps.SlideScan, plan: reveal_steps.StepPlan, draft: bool, key: tuple):
        """(whether the ticks of `view` can be edited, why not or what to know) for the selected place."""
        owner = next((c for c in block if c.included_in(view)), None)
        problem = deck_editor.step_edit_problem(owner or block[0], view)
        if problem is not None:
            return False, problem
        if scan.own_frame_spec is not None or scan.frame_breaks or not plan.reliable:
            return False, ("The slide's own frame decides which steps exist (\\begin{frame}<spec> or "
                           "allowframebreaks); \\slidestep has no effect on it.")
        if draft:
            revision = self._capture(self._target)
            spec = PreviewRequest(self._target, revision, key[3], key[4]) if revision is not None else None
            saved = self.model.steps.pages.get(self._steps_key(spec, self._generation, False)) if spec is not None else None
            if saved is None or saved.count != counts[view]:
                return False, "Save the slide to edit its steps: the editor buffer may have other steps."
        if any(not counts.get(v) for v in served):
            return False, "Counting the steps of the other versions\u2026"
        notes = []
        if scan.version_dependent:
            notes.append("Numbered per version: the same step number can be other content in another version.")
        if plan.final_only:
            notes.append("Students see only the final state (\\SMFinalStateForStudents); an edit writes explicit "
                         "\\slidestep calls that override it.")
        return True, " ".join(notes)

    def _update_reveal(self, target: PreviewTarget | None, row: SlideRow | None, selection,
                       whole: _PageResult | None) -> _PageResult | None:
        """Update the bar and its counts, and schedule any missing all-steps render."""
        bar = self._reveal
        if selection is None:
            bar.setVisible(False)
            return None
        key, revision, draft, scan = selection
        if ((key not in self.model.steps.pages or key in self.model.steps.recheck) and key[0] != 'draft'
                and key not in self.model.steps.failed and not self._defer_checks):
            spec = PreviewRequest(target, revision, key[3], key[4], RenderOptions(all_steps=True))
            self._adopt_stored_steps(spec, key)
        steps = self.model.steps.pages.get(key)
        count = steps.count if steps is not None else 0
        if steps is not None:
            self.model.steps.pages.move_to_end(key)
        elif whole is not None and whole.request.revision.content_hash == revision.content_hash:
            count = len(whole.pages)
        self._probe.start(PROBE_MS)
        if not count:
            if scan.may_reveal and key not in self.model.steps.failed:
                bar.show_counting()
                if not self._steps_busy() and not self._settle.isActive():
                    self._request_steps(target, key, revision, draft, FOREGROUND)
            else:
                bar.setVisible(False)
            return None
        view = self.state.view
        rows = self._step_rows(target, row, key, count, scan, draft)
        step = min(max(self.model.steps.choice.get(target.source_path, count), 1), count)
        bar.set_state(view, step, rows, draft)
        stops = bar.track.stops
        if stops and step not in stops and step in (1, count) and bar.deck_only.isChecked():
            # Arriving by the wheel opens at step 1 (or the last one), which this version may leave out: with "Deck steps
            # only" the slide opens at the nearest step the deck includes, forward from the first, back from the last.
            snapped = reveal_steps.snap_to_stops(step, stops)
            self.model.steps.choice[target.source_path] = snapped
            bar.set_state(view, snapped, rows, draft)
            QTimer.singleShot(0, self._refresh)
        if bar.expanded and scan.version_dependent:
            self._probe.start(0)
        return steps

    def _rebuild_menu(self) -> None:
        all_enabled = self.can_render_all
        pdf_available = self._record is not None or self.model.adhoc.spec is not None
        built = (self._target is not None and not self._target.hidden, self._batch_cancel is not None, all_enabled,
                 self._busy, pdf_available)
        if built == self._menu_built and self._menu is not None:
            self._menu_stale = False     # a refresh that changed nothing the menu shows
            return
        if self._menu is not None and self._menu.isVisible():
            # Every refresh (the background checks too) lands here: replacing an open menu closed it under the cursor.
            self._menu_stale = True
            return
        self._menu_stale = False
        self._menu_built = built
        if self._menu is not None:
            self._menu.deleteLater()
        menu = PopoverMenu(self, min_width=260)
        has_buffer = self._target is not None and self._batch_cancel is None
        reason = "Wait for the current preview render to finish."
        menu.setToolTip(reason if not all_enabled and self._target is not None else "")
        menu.add_header("Open")
        menu.add_item(OPEN_PDF, "PDF for this view", enabled=pdf_available and not self._busy,
                      tip="Open the PDF of the slide as this view shows it")
        menu.add_item(PRESENTER, "Presenter PDF", meta="opens in the viewer", enabled=has_buffer,
                      tip="Render the slide with its speaker notes and open it in the PDF viewer")
        menu.add_separator()
        menu.add_header("Render")
        menu.add_item(BUFFER, "Slide with unsaved changes", meta="Ctrl+Enter", enabled=has_buffer,
                      tip="Render the preview from the text in the editor, saved or not")
        menu.add_item(ALL_BUFFER, "All views with unsaved changes", enabled=all_enabled,
                      tip="Render the slide in every view from the text in the editor",
                      meta="" if all_enabled else reason)
        menu.add_item(ALL_SAVED, "All views latest saved version", enabled=all_enabled,
                      tip="Render the slide in every view from the saved file",
                      meta="" if all_enabled else reason)
        menu.add_item(TRANSCRIPT, "Transcript", enabled=has_buffer,
                      tip="Show the slide's entry in the accessible transcript")
        menu.add_item(FORCE, "Rerender preview, ignore cache", enabled=has_buffer and not self._target.hidden,
                      tip="Render this view again even when a finished render is cached",
                      meta="of this view")
        if self._batch_cancel is not None:
            menu.add_separator()
            menu.add_item(STOP, "Stop rendering all views", tip="Stop the renders of the other views")
        menu.triggered.connect(self._on_menu)
        menu.closed.connect(lambda: self._menu_stale and self._rebuild_menu())
        self._menu = menu
        self._render.set_menu(menu)

    def _on_menu(self, key: str) -> None:
        if key == ALL_SAVED:
            self.render_all_views(saved=True)
        elif key == ALL_BUFFER:
            self.render_all_views(saved=False)
        elif key == FORCE:
            self._render_saved(precheck=True, force=True)
        elif key == STOP:
            self.cancel_batch()
        elif key == BUFFER:
            self.render_buffer()
        elif key == PRESENTER:
            self.render_buffer(presenter=True)
        elif key == TRANSCRIPT:
            self.render_transcript()
        elif key == OPEN_PDF:
            self._open_pdf()

    def _open_pdf(self) -> None:
        """Open a copy independent of store replacement and eviction."""
        if self._record is not None:
            record = self._record
            renderer = self._renders.renderer(self._target.context)

            def copy():
                owner = renderer.store.pdf_copy(record)
                return owner, owner.__enter__()

            def open_copy(found):
                if found is not None:
                    owner, pdf = found
                    self._pdf_copies.push(owner)
                    if pdf is not None:
                        slide_preview.open_pdf(pdf)

            self._look_up('pdf', (record['key'], record.get('rendered_at')), copy, open_copy)
        elif self._target is not None and self.model.adhoc.spec is not None and not self._busy:
            spec = self.model.adhoc.spec
            job = self._job(self._target, external=True, revision_text=self.model.adhoc.text)
            job.request = self._renders.request(spec.target, spec.revision.text, spec.view, spec.language,
                                                self.app.log, spec=spec)
            self._start(lambda: None, job)

    # -- rendering ---------------------------------------------------------------------

    @property
    def _closed(self) -> bool:
        return self._lifetime.closed.is_set()

    def _dispose(self) -> None:
        self._lifetime.close()

    def _invalidate(self) -> None:
        # Drops the selection and what is running, so stale completions are discarded; the decoded pages in
        # `model.pixmaps` stay for a return visit.
        self._generation += 1
        if self._active is not None:
            self._active.cancel.set()
        self.model.invalidate_selection()
        self._record = None
        if self._batch_cancel is None:
            self._batch_status = ''
        self._error = ''
        self._forget_pending()
        self._pending = None
        self._debounce.stop()
        self._buffer_notice.stop()
        self._busy = self._active is not None

    def _forget_pending(self) -> None:
        if self._pending is not None and self._pending[1].request is not None:
            self._pending[1].request.forget_unstarted()

    def _start(self, work: Callable[[], Path], job: _Job, *, debounce: bool = False) -> None:
        """One running compile and one replaceable latest request; never overlap."""
        self._generation += 1
        self._steps.preempt()
        job.generation = self._generation
        if job.request is not None:
            job.spec = replace(job.request.spec, target=job.spec.target, view=job.view, language=job.language)
        job.requested = time.perf_counter()
        self._shown_mtime = job.mtime
        if self._pending is None or self._pending[1].request is not job.request:
            self._forget_pending()
        self._pending = (work, job)
        self._busy, self._error = True, ""
        if debounce:
            self._debounce.start()
        else:
            self._debounce.stop()
            self._launch_pending()
        self._refresh()

    def _launch_pending(self) -> None:
        if self._closed or self._pending is None or self._debounce.isActive():
            return
        if self._active is not None:
            active = self._active.request
            pending = self._pending[1].request
            if active is not None and active is not pending:
                # Detach only this pane. RenderRequest stops TeX when its last waiter leaves; an AI/tool
                # consumer can finish the old revision independently. Never kill a shared request here.
                self._active.cancel.set()
            return
        work, job = self._pending
        self._pending = None
        if job.request is not None and job.request.cancelled():
            # A rapid edit/undo can have joined the old revision just before its last waiter detached.
            # Reacquire that immutable request after cancellation instead of displaying a cancellation error.
            spec = job.request.spec
            job.request = self._renders.request(spec.target, spec.revision.text, spec.view, spec.language,
                                                self.app.log, spec=spec)
        self._active = job
        self._lifetime.job = job
        Thread(target=self._run, args=(work, job), daemon=True).start()

    def _run(self, work: Callable[[], Path], job: _Job) -> None:
        with PreviewMetrics() as metrics:
            try:
                if job.request is not None:
                    # The pixels are enough to show the slide; the cache record follows on the request's worker.
                    job.pdf, job.png, _, _ = job.request.wait(job.cancel, pixels_only=not job.external)
                    if isinstance(job.png, Path):
                        with timing.span('preview.decode_raw'):
                            job.image = QImage(str(job.png))
                        job.png = None
                        if job.image.isNull():
                            # Recording continues independently; its stored image is the fallback if the temp file vanished.
                            job.pdf, job.png, _, _ = job.request.wait(job.cancel)
                    if job.png is not None:
                        built = job.request.preview_result
                        # Publication can advance while the pane still owns the early pixels.
                        if built is not None and built.display_png is job.png:
                            job.record = built.record
                        job.image = QImage.fromData(job.png)
                else:
                    job.pdf = work()
                if job.request is None and not job.external and not self._closed and job.generation == self._generation:
                    displays, _ = slide_snapshot.prepare_preview_images(job.pdf, False, (slide_snapshot.FULL_SIZE[0],))
                    job.png = displays[0]
            except Exception as exc:  # noqa: BLE001 -- shown as the error; the render must always end
                job.error = str(exc) or type(exc).__name__
        job.metrics = dict(job.request.metrics or {}) if job.request is not None else metrics.to_dict()
        if self._closed:
            self._discard(job)
            return
        try:
            self._finished.emit(job)
        except RuntimeError:  # Qt owner was destroyed while TeX finished.
            self._discard(job)
        slide_preview.sweep_renders(self.app.project)   # renders older than the cleanup setting; never raises

    _discard = staticmethod(_discard_job)

    def _accepts(self, job: _Job) -> bool:
        target = self._target
        if job.request is not None and job.request.cancelled():
            return False
        if (target is None or job.generation != self._generation or target.key != job.target_key
                or (self.state.view, self.language)
                != (job.view, job.language)
                or _mtime(job.source) != job.mtime):
            return False
        buffer = self._buffer()
        text = job.revision_text if job.revision_text is not None else job.buffer_text
        if text is None and job.spec is not None:
            text = job.spec.revision.text
        if text is None:
            return True
        try:
            current = buffer if buffer is not None else job.source.read_text(encoding='utf-8')
            return current == text
        except OSError:
            return False

    def _on_finished(self, job: _Job) -> None:
        self._remote.pop(job.request, None)
        if self._closed:
            self._discard(job)
            return
        if self._active is not job and not job.remote:
            self._discard(job)
            return
        if self._active is job:
            self._active = None
            self._lifetime.job = None
        self._busy = self._active is not None or self._pending is not None
        publish_start = time.perf_counter()
        accepted = self._accepts(job)
        if not accepted:
            self._discard(job)
            if job.error and not job.cancel.is_set():   # cancellation of an obsolete revision is not a failure
                self.app.log(f"*** Render failed: {job.error} ***")
        elif job.error:
            self._discard(job)
            self._error = job.error
            self.app.log(f"*** Render failed: {job.error} ***")
        else:
            self._last_request = job.request
            if not job.external:
                self.model.lookups.cancel_all()
                self.model.lookups.stored = None
            self.model.lookups.asked = None
            self._check_when_recorded(job.request)
            if self._target is not None and self._target.needs_context and not job.external:
                pdf = job.request.preview_result.pdf if job.request is not None else job.pdf
                self._context_modes[(job.target_key, job.view, job.language)] = deck_context.mode_of(pdf)
                while len(self._context_modes) > 64:
                    self._context_modes.pop(next(iter(self._context_modes)))
            if job.external:
                folder = self._pdf_copies.enter_context(tempfile.TemporaryDirectory(prefix='slidemage-open-'))
                pdf = Path(folder) / job.pdf.name
                shutil.copyfile(job.pdf, pdf)
                slide_preview.open_pdf(pdf)
            elif job.spec is not None:
                result = self._rendered_page(job.spec, job.generation, job.png, job.record, job.image)
                if result is not None:
                    full = job.steps_ok and (job.note or job.spec.target.needs_context or not job.spec.complete)
                    text = job.spec.revision.text if job.revision_text is None else job.revision_text
                    self._remember(result, text, job.note, full=bool(full))
            job.pdf = None
            self.rendered.emit()
            if not job.external:
                if job.request is not None:
                    self._renders.renderer(job.request.spec.target.context).submit_other_views(job.request.spec)
                self._after_render(job)
            if job.request is None:
                self.rendered_target.emit(job.source)
        self._launch_pending()
        self._refresh()
        if job.metrics is not None:
            job.metrics['accepted'] = accepted
            job.metrics['publication_seconds'] = time.perf_counter() - publish_start
            job.metrics['request_to_finished_seconds'] = time.perf_counter() - job.requested
            self.app.log(f"Preview timing: {job.metrics}")

    def _job(self, target: PreviewTarget, **fields) -> _Job:
        view, language = self.state.view, self.language
        revision = self._capture(target, fields.get('revision_text'))
        spec = PreviewRequest(target, revision, view, language) if revision is not None else None
        return _Job(target_key=target.key, view=view, language=language, spec=spec,
                    mtime=_mtime(target.source_path), source=target.source_path, **fields)

    def render_now(self) -> None:
        """Compile the saved slide in the view and language being edited."""
        self._render_saved(precheck=True)

    def _status_clicked(self) -> None:
        if self._status_draft:
            self.render_buffer()
        else:
            self.render_now()

    def _render_saved(self, precheck: bool, *, force: bool = False) -> None:
        target = self._target
        if target is None or target.hidden or self._batch_cancel is not None:
            return
        path = target.source_path
        if precheck and not render_check.confirm_render(
                self, self.app, latex_lint.check_slide_files(self.app.project, [path]), f"{path.name} (saved file)",
                show_in_editor=lambda issue: render_check.open_issue_in_editor(self.app, issue)):
            return
        view, language = self.state.view, self.language
        text = path.read_text(encoding='utf-8')
        job = self._job(target, revision_text=text)
        self._batch_status = ''
        job.request = self._renders.request(target, text, view, language, self.app.log, saved=True, force=force)
        self._start(lambda: None, job)

    def _render_context_slide(self, target: PreviewTarget) -> None:
        """A slide that needs its deck has no picture yet (the background previews wait for a deck compile): render it
        once, as Render now does, instead of leaving "No preview" and a button (v8.67.0). Once per file revision, view
        and language: a failure leaves its message, and Render now tries again."""
        view, language = self.state.view, self.language
        key = (target.key, view, language, _mtime(target.source_path))
        if not target.needs_context or self._error or self._batch_cancel is not None or key in self._auto_rendered:
            return
        if len(self._auto_rendered) > 256:
            self._auto_rendered.clear()
        self._auto_rendered.add(key)

        def start() -> None:
            shown = self._target
            if self._closed or shown is None or shown.key != target.key or _mtime(shown.source_path) != key[3]:
                return
            if (view, language) != (self.state.view, self.language):
                return
            if self._pending or self._active:
                self._auto_rendered.discard(key)        # another render is out: the next refresh asks again
                return
            if latex_lint.check_slide_files(self.app.project, [shown.source_path]).errors:
                return                      # Render now asks about those
            self._render_saved(precheck=False)

        QTimer.singleShot(0, start)

    def render_after_save(self) -> None:
        """Render the current buffer after a typing pause or save, unless it has syntax errors."""
        target = self._target
        if target is None or target.hidden or self._batch_cancel is not None:
            return
        path = target.source_path
        saved_text = slide_source.read_slide_source(path)[0]
        text = self._buffer() or saved_text
        if latex_lint.check_buffer(self.app.project, text, path.name, path).errors:
            self._invalidate()
            self._refresh()
            return
        render_text = text
        if text != saved_text and slide_versioning.is_current_slide(path):
            # Autosave adds the version marker; capture the same text now so its later write is a store hit.
            render_text = slide_versioning.autosave_text(path, target.id_slug, saved_text, text)
        job = self._job(target, revision_text=text, buffer_text=text,
                        note="Rendered from the editor buffer, not the saved file" if text != saved_text else "")
        job.request = self._renders.request(target, render_text, self.state.view, self.language, self.app.log,
                                            saved=text == saved_text)
        self._start(lambda: None, job, debounce=True)

    def render_buffer(self, presenter: bool = False) -> None:
        """Compile the editor's buffer, saved or not."""
        target = self._target
        if target is None or self._batch_cancel is not None or (target.hidden and not presenter):
            return
        text = self._buffer() or slide_source.read_slide_source(target.source_path)[0]
        path = target.source_path
        if not render_check.confirm_render(
                self, self.app, latex_lint.check_buffer(self.app.project, text, path.name, path), f"{path.name} (editor buffer)",
                show_in_editor=lambda issue: self.app.open_slide_editor(path, line=issue.line)):
            return
        view, language = self.state.view, self.language
        job = self._job(target, external=presenter, buffer_text=text, revision_text=text,
                        note="Rendered from the editor buffer, not the saved file", steps_ok=not presenter)
        job.request = self._renders.request(target, text, view, language, self.app.log, presenter=presenter)
        self._batch_status = ''
        self._start(lambda: None, job)

    def _current_render_context(self):
        # Source/Details can change focus while the hidden Preview still holds
        # its previous target. Palette actions resolve the current focus first.
        centre = getattr(self.app, 'centre', None)
        if (self.state.mode not in ('preview', 'split') and centre is not None
                and getattr(centre, 'preview', None) is self):
            return centre._preview_context()
        return self._target, self._row, self._title, self._language

    def _sync_render_context(self) -> None:
        target, row, title, language = self._current_render_context()
        self.show_slide(target, row, title, 'Select a slide in the list.', language)

    @property
    def can_force_render(self) -> bool:
        target = self._current_render_context()[0]
        return (target is not None and not target.hidden and self._batch_cancel is None
                and not self._busy and not self._closed)

    def force_rerender(self) -> None:
        if self.can_force_render:
            self._sync_render_context()
            self._render_saved(precheck=True, force=True)

    @property
    def can_render_all(self) -> bool:
        return (self._current_render_context()[0] is not None
                and self._batch_cancel is None and not self._busy and not self._closed)

    def render_all_views(self, *, saved: bool = True) -> None:
        """Render one captured revision in all views on a worker, without moving focus."""
        if not self.can_render_all:
            return
        self._sync_render_context()
        target = self._target
        try:
            text = target.source_path.read_text(encoding='utf-8') if saved else (
                self._buffer() or target.source_path.read_text(encoding='utf-8'))
            issues = latex_lint.check_buffer(self.app.project, text, target.source_path.name, target.source_path)
            if not render_check.confirm_render(self, self.app, issues,
                                               f"{target.source_path.name} ({'saved file' if saved else 'editor buffer'})",
                                               show_in_editor=lambda issue: render_check.open_issue_in_editor(self.app, issue)):
                return
            workspace = self.app.assistant.workspace
            context = WorkspaceContext(deck=self.state.deck, slide_id=target.bare_id, path=target.source_path,
                                       view=self.state.view, language=self.language,
                                       occurrence_key=_shown_occurrence(self.app, self.state))
            requests = workspace.prepare_preview_batch(target.source_path, saved=saved, context=context)
        except (OSError, ValueError, RuntimeError) as exc:
            self._batch_status = ''
            self._error = str(exc) or type(exc).__name__
            self.app.log(f"*** Render all views failed: {self._error} ***")
            self._refresh()
            return
        ticket = self._generation
        cancel = threading.Event()
        self._batch_cancel = cancel
        self._batch_status = 'Rendering all views…'
        self._error = ''
        Thread(target=self._run_batch, args=(workspace, target.source_path, saved, cancel, requests, ticket),
               daemon=True).start()
        self._refresh()

    def _run_batch(self, workspace, path, saved, cancel, requests, ticket) -> None:
        results, error = (), ''
        try:
            results = workspace.render_preview_batch(path, saved=saved, cancel=cancel, requests=requests, ticket=ticket,
                                                      progress=self._batch_progressed.emit)
        except Exception as exc:  # noqa: BLE001 -- shown on the GUI thread
            error = str(exc) or type(exc).__name__
        if not self._closed:
            try:
                self._batch_finished.emit(results, error)
            except RuntimeError:  # The pane was destroyed while the batch finished.
                pass

    def _on_batch_progress(self, progress) -> None:
        if self._closed or self._batch_cancel is None:
            return
        # Several views render at once: every event moves the count of the finished ones
        self._batch_status = f"Rendering all views · {progress.done}/{progress.total} done"
        self._refresh()

    def _on_batch_finished(self, results, error: str) -> None:
        if self._closed:
            return
        self._batch_cancel = None
        details = []
        for result in results:
            if result.status in ('hidden', 'failed', 'cancelled'):
                details.append(f"{VIEW_LABELS[result.request.view]}: {result.status}")
        self._batch_status = error or ('; '.join(details) if details else 'All views ready')
        for result in results:
            if result.error:
                self.app.log(f"Preview · {VIEW_LABELS[result.request.view]}: {result.error}")
        self._refresh()

    def cancel_batch(self) -> None:
        if self._batch_cancel is not None:
            self._batch_cancel.set()
            self._batch_status = 'Stopping all-view render…'
            self._refresh()

    def request_render(self, target, text, view, language) -> RenderRequest:
        """GUI-thread entry for tools; publication uses the ordinary job acceptance checks."""
        if self._closed:
            raise RuntimeError('Preview pane closed')
        saved = target.source_path.read_text(encoding='utf-8') == text
        request = self._renders.request(target, text, view, language, self.app.log, saved=saved)
        # An ordinary pane worker already delivers this exact build to the GUI.
        for job in (self._active, self._pending[1] if self._pending else None, self._remote.get(request)):
            if job is not None and job.request is request and job.generation == self._generation:
                return request
        spec = replace(request.spec, target=target)
        job = _Job(target_key=target.key, source=target.source_path, mtime=_mtime(target.source_path), spec=spec,
                   view=view, language=language, generation=self._generation,
                   revision_text=text, buffer_text=None if saved else text,
                   note='' if saved else 'Rendered from the editor buffer, not the saved file',
                   requested=time.perf_counter(), request=request, remote=True)
        self._remote[request] = job
        return request

    def finish_render(self, request: RenderRequest) -> None:
        """Publish a tool's settled request on the GUI thread before returning its image."""
        job = self._remote.pop(request, None)
        if self._active is not None and self._active.request is request and self._active.generation == self._generation:
            job = self._active
        elif (self._pending is not None and self._pending[1].request is request
              and self._pending[1].generation == self._generation):
            job = self._pending[1]
            self._pending = None
            self._debounce.stop()
            job.remote = True
        if job is None or not request.done.is_set():
            return
        if request.error is not None:
            job.error = str(request.error)
        else:
            job.pdf, job.png, _, _ = request.result
            job.record = request.preview_result.record if request.preview_result is not None else None
        job.metrics = dict(request.metrics or {})
        self._on_finished(job)
        job.remote = False

    @staticmethod
    def _rendered_page(spec, ticket, png, record=None, image=None) -> _PageResult | None:
        if isinstance(png, Path):
            png = png.read_bytes()
        pixmap = QPixmap.fromImage(image) if image is not None else QPixmap()
        if pixmap.isNull() and (png is None or not pixmap.loadFromData(png)):
            return None
        digest = hashlib.sha256(png).hexdigest() if png is not None else str(pixmap.cacheKey())
        return _PageResult(ticket, spec, 'current' if record is not None else 'rendered', record,
                           decoded=(0, digest, pixmap))

    def publish_batch_result(self, result, generation) -> str:
        """Publish a batch result with its captured pane ticket."""
        if self._closed:
            return 'superseded'
        spec = result.request
        saved = self._capture(spec.target)
        if saved is None or (spec.options.saved and saved.text != spec.revision.text):
            return 'superseded'
        matching = (self._target is not None and self._target.key == spec.target.key
                    and (self.state.view, self.language) == (spec.view, spec.language))
        if not matching:
            if saved.text == spec.revision.text:
                self.rendered_target.emit(spec.revision.path)
            return 'cached'
        revision = self._selection_revision(self._target, self._capture(self._target))
        page = self._rendered_page(spec, generation, result.display_png, result.record)
        if page is None:
            raise RuntimeError('The rendered preview image could not be read')
        note = 'Rendered from the editor buffer, not the saved file' if saved.text != spec.revision.text else ''
        return self._publish_page(page, revision, note)

    def publish_refresh(self, target, text, revision, view, language, artifact, generation) -> str:
        """GUI-thread publication of a saved preview refresh, without changing the focus."""
        if self._closed:
            return 'superseded'
        saved = self._capture(target)
        if saved is None or saved.mtime_ns != revision or saved.text != text:
            return 'superseded'
        if self._target is None or (target.key, view, language) != (self._target.key, self.state.view, self.language):
            self.rendered_target.emit(target.source_path)
            return 'cached'
        spec = PreviewRequest(target, saved, view, language, RenderOptions(saved=True))
        page = self._rendered_page(spec, generation, artifact[1])
        if page is None:
            raise RuntimeError('The rendered preview image could not be read')
        return self._publish_page(page, self._selection_revision(self._target, saved))

    def _publish_page(self, page: _PageResult, revision: SourceRevision | None, note: str = "") -> str:
        if not self._matches(page, revision):
            return 'superseded'
        self._remember(page, page.request.revision.text, note)
        self.model.lookups.cancel_all()
        self.model.lookups.stored = None
        self.model.lookups.asked = None
        self._error = ''
        self._refresh()
        self.rendered.emit()
        self.rendered_target.emit(page.request.revision.path)
        return 'displayed'

    def render_transcript(self) -> None:
        """A one-slide transcript preview of the buffer (nothing is written to disk)."""
        target = self._target
        if target is None:
            return
        buffer = self._buffer()
        text = buffer if buffer else slide_source.read_slide_source(target.source_path)[0]
        show_transcript_preview(self.app, text, target.bare_id, target.id_slug, self.state.view, self.language)


def _mtime(path: Optional[Path]) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
