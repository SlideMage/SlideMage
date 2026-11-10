# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preview view: the focused slide as a page, in the view (Instructor /
During course / After course) and language the top bar says.

Without compiling anything it shows the render store's current page, previous
render or Instructor reference.
"Render" compiles the saved slide in the view and language, and the Render
menu renders the editor's buffer instead (Ctrl+Enter: the whole slide, or the
selection as a frame or as a cropped element, optionally one reveal step), a
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
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from ... import (deck_context, deck_editor, languages, latex_lint, render_lookup, reveal_steps, slide_preview, slide_snapshot, slide_source,
                 slide_versioning, timing)
from ...ai.workspace import WorkspaceContext
from ...ai.tools.slidemage import slide_target
from ...deck_outline import SlideRow
from ...fileio import text_sha256
from ...preview_target import PreviewTarget
from ...preview_requests import PreviewRequest, RenderOptions, RenderRequest, RenderService, SourceRevision
from ...preview_metrics import PreviewMetrics
from ...slide_language import MULT, LanguageBadge, TranslationLink, own_language, translation_group
from ...step_renders import BACKGROUND, FOREGROUND, StepRenderQueue
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit.tokens import SPACE, RADIUS_SM
from ..kit import kit_qss as q
from ..kit.tokens import Tokens
from ..kit.widgets import Button, Chip, PopoverMenu, SplitButton, Surface, clear_layout
from . import render_check
from .menus import VIEW_LABELS
from .reveal_bar import RevealBar, RowSpec
from .state import VIEWS, WorkspaceState

PAGE_ASPECT = 16 / 9
PANE_SIDE_MARGIN = SPACE.xl    # the Preview's margin left and right (chips, page, footer)
PAGE_SIDE_INSET = 8      # the page inside its area, left and right: the shadow's room
PROBE_MS = 1500          # idle time before the step bar counts a slide's steps in the background
SETTLE_MS = 150          # the selection must rest this long before the step bar starts counting the slide's steps
DISPLAY_WIDTH = slide_snapshot.FULL_SIZE[0]   # a page held for display is at most a render's full width: a large or
# high-DPI pane shows that much, so a smaller copy would look softer than the current page
DISPLAY_ENTRIES = 12     # pages held decoded for display ...
DISPLAY_BYTES = 64 << 20 # ... and at most this much memory for them (width x height x 4 each)
CHECKING = "Checking current source and settings…"
STEP_CACHE = 12          # page lists kept (each is a slide's steps as PNGs)
NEIGHBOURS = 4           # slides around the one on show whose steps are counted while the pane is idle
PREFETCHED = 20          # stored pages of the nearest slides held decoded, ready for the next slide (about 8 MB each)
PRELOAD_BYTES = 512 << 20   # stored pages (PNG) of the rest of the deck's view held compressed, decoded when shown
PRELOAD_PAUSE = 0.01     # seconds the read-ahead worker rests before each store lookup, so the GUI thread gets its turn
PRELOAD_RETRY = 120.0    # seconds before a slide whose store had no page is asked again
SCROLLING_MS = 300       # slide changes closer than this are scrolling: no checks until the selection rests
LOADING = "Loading…"
SCOPES = (("slide", "Whole slide"), ("region", "Selection as frame"), ("element", "Selection as element"))
# Menu keys.
BUFFER, OVERLAY, PRESENTER, TRANSCRIPT, OPEN_PDF = "buffer", "overlay", "presenter", "transcript", "open_pdf"
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


@dataclass
class _Job:
    """A finished render, handed from the worker thread to the GUI thread."""
    pdf: Optional[Path] = None
    png: Optional[bytes] = None
    image: Optional[QImage] = None
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
    revision_text: Optional[str] = None
    remote: bool = False
    steps_ok: bool = True           # a whole-slide render: count its reveal steps
    cancel: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)


def _discard_job(job: _Job) -> None:
    # Shared PDFs remain available to every consumer; the normal render sweep removes them.
    if job.request is None and job.pdf is not None and job.pdf.parent.name.startswith('slidemage_preview_'):
        shutil.rmtree(job.pdf.parent, ignore_errors=True)


@dataclass
class _Shown:
    """A decoded whole-slide page of a saved render, as it was when it was made."""
    pixmap: QPixmap
    mtime: int                      # of the slide's source file
    content_hash: Optional[str]     # of the text rendered (the saved file's)
    image_hash: str                 # of the PNG the pixels came from: the same image is never decoded twice


class DisplayCache:
    """Decoded pages for display, newest last: (target.key, view, language) -> _Shown. GUI thread only. Only saved
    whole-slide renders go in (never a draft or a part of a slide), at display size and within a byte budget. What
    is held is not current: only the selection's validation makes a page current; the revision only says whether
    the page may be shown, marked as being checked, while that runs."""

    def __init__(self) -> None:
        self._items: OrderedDict[tuple, _Shown] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    @property
    def bytes(self) -> int:
        return sum(item.pixmap.width() * item.pixmap.height() * 4 for item in self._items.values())

    def get(self, key: tuple) -> Optional[_Shown]:
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
        return item

    def put(self, key: tuple, pixmap: QPixmap, mtime: int, content_hash: Optional[str], image_hash: str) -> QPixmap:
        """Keep `pixmap` at display size; the pixmap held (to show) is returned."""
        if pixmap.width() > DISPLAY_WIDTH:
            pixmap = pixmap.scaledToWidth(DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)
        self._items[key] = _Shown(pixmap, mtime, content_hash, image_hash)
        self._items.move_to_end(key)
        while len(self._items) > 1 and (len(self._items) > DISPLAY_ENTRIES or self.bytes > DISPLAY_BYTES):
            self._items.popitem(last=False)
        return pixmap

    def clear(self) -> None:
        self._items.clear()


def _preload_page(background, target, view: str, language: str, data: Optional[bytes], decode: bool):
    """(PNG, digest, QImage or None) of the stored whole-slide page, or None. Runs on the read-ahead worker: `data`
    is the PNG already held (then only decoded), else the store is asked; `decode` decodes it too."""
    if data is None:
        time.sleep(PRELOAD_PAUSE)
        renderer = background.renderer
        if renderer is None:
            return None
        try:
            spec = PreviewRequest(target, SourceRevision.capture(target.source_path), view, language)
            _state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec), strict=False)
            data = renderer.store.page(record, record['pages']) if record is not None else None
        except (OSError, ValueError):
            return None
        if data is None:
            return None
    image = None
    if decode:
        image = QImage()
        if not image.loadFromData(data):
            return None
    return data, hashlib.sha256(data).hexdigest(), image


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
            owner._drop_preloaded()
            owner._lookups.clear()
            owner._pdf_copies.close()
            owner._renders.close()
            owner._steps.close()
            owner._pending = None
            owner._generation += 1
            owner._pixmaps.clear()
            owner._stored = None
            owner._step_pixmap = owner._step_image = None
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
        self.dimmed = False     # the page of the slide shown before, kept faint while the new one loads
        self.setMinimumSize(320, 180)
        self.render_button = Button("Render now", "primary", self)
        self.render_button.hide()

    def show_image(self, pixmap: QPixmap) -> None:
        self.pixmap, self.message, self._scaled, self.dimmed = pixmap, "", None, False
        self.render_button.hide()
        self.update()

    def keep_dimmed(self) -> None:
        """Keep the page on show, faint: it is the slide shown before, while the new one's check is out."""
        if self.pixmap is not None and not self.dimmed:
            self.dimmed = True
            self.render_button.hide()
            self.update()

    def show_message(self, message: str, can_render: bool) -> None:
        self.pixmap, self.message, self._scaled, self.dimmed = None, message, None, False
        self.render_button.setVisible(can_render)
        self._place_button()
        self.update()

    def _page_rect(self) -> QRectF:
        aspect = self.pixmap.width() / self.pixmap.height() if self.pixmap else PAGE_ASPECT
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
            if self.dimmed:
                painter.setOpacity(0.35)
            painter.drawPixmap(page, scaled, QRectF(scaled.rect()))
            painter.setOpacity(1.0)
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
    _finished = Signal(object)    # a _Job, from the worker thread
    _batch_progressed = Signal(object)
    _batch_finished = Signal(object, str)
    _steps_ready = Signal(object, object, str)   # (key, PNG pages, error), from the step queue's thread
    _looked_up = Signal(object, object, object, object)   # (slot, identity, arrive, found), from the display worker
    _prefetch_done = Signal(object, object, object)        # (context, ident, (PNG, digest, QImage) or None), read ahead

    def __init__(self, app, state: WorkspaceState,
                 buffer: Callable[[], Optional[tuple[str, str]]]) -> None:
        """`buffer()` gives (the text, the selected text) of the slide in the Source view,
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
        # The render store's lookups, page reads and PNG decodes run here, not in the selection executor: a lookup
        # must not wait behind a long validation. One pending lookup per slot ('page', ('steps', key)); a newer one
        # for the slot replaces it, and a selection change drops them all.
        self._display_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='preview-display')
        self._lookups: dict = {}              # slot -> (identity with the generation first, Future)
        self._looked_up.connect(self._on_looked_up)
        self._stored: Optional[tuple] = None  # identity, pixmap, digest, chooser state, record
        self._stored_asked = None             # what the page was last looked up for; the poll asks again
        # The stored pages of the deck's view, read ahead on a worker of their own (not behind the selection's lookups),
        # outward from the slide on show: the nearest PREFETCHED decoded (ident -> (QPixmap, digest)), the others as
        # PNG (ident -> (PNG, digest), at most PRELOAD_BYTES). Keyed with the file's mtime, so they outlive a change of
        # slide, unlike `_lookups`, and the slide scrolled or clicked to shows at once. One deck, view and language.
        self.deck_targets: Callable[[], list] = lambda: []
        self._prefetch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='preview-prefetch')
        self._prefetched: OrderedDict = OrderedDict()
        self._compressed: dict = {}
        self._compressed_bytes = 0
        self._preload_rank: dict = {}         # ident -> its place in the read-ahead order (0 = nearest)
        self._preload_context: Optional[tuple] = None   # (deck name, view, language) the held pages are of
        self._preload_missing: dict = {}      # ident -> when the store had no page for it
        self._prefetching: dict = {}          # ident -> Future, queued or running
        self._prefetch_done.connect(self._on_prefetched)
        self._changed_at = 0.0                # when the slide on show last changed (time.monotonic)
        self._defer_checks = False            # scrolling: show what is held, check once the selection rests
        self._count_after: dict[tuple, Callable[[], None]] = {}   # steps key -> the render to queue if the store has none
        self._remote = {}
        self._shown_mtime = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        # Autosave already waits for typing to settle. Coalesce save notifications in this event-loop turn
        # without adding another 300 ms before starting the focused preview.
        self._debounce.setInterval(0)
        self._debounce.timeout.connect(self._launch_pending)
        self._buffer_notice = QTimer(self)
        self._buffer_notice.setSingleShot(True)
        self._buffer_notice.setInterval(150)
        self._buffer_notice.timeout.connect(self._refresh)
        self._validation_poll = QTimer(self)
        self._validation_poll.setInterval(5000)
        self._validation_poll.timeout.connect(self._poll_selection)
        self._validation_poll.start()
        self.destroyed.connect(self._lifetime.close)
        self._error = ""
        self._record = None
        self._pdf_copies = ExitStack()
        self._last_request = None      # observes publication after the pixels arrive
        self._scope = "slide"
        self._overlay = 0
        # Decoded pages of this session's saved renders, shown while a return visit is validated.
        self._pixmaps = DisplayCache()
        # The latest render of the editor buffer: (target.key, view, language) -> (pixmap, note).
        self._adhoc: Optional[tuple[tuple, QPixmap, str]] = None
        self._adhoc_spec = None
        self._adhoc_text: Optional[str] = None
        self._adhoc_full = False       # the temporary render is a whole slide (the step bar may use it)
        # The step bar: page lists of all-steps renders, rendered one at a time in the background.
        self._steps = StepRenderQueue(self._steps_busy, self._steps_done, read_pages=lambda pages: pages)
        self._step_pages: OrderedDict[tuple, list[bytes]] = OrderedDict()
        self._step_choice: dict[Path, int] = {}      # the step picked per slide; none: the last one
        self._step_pixmap: Optional[tuple[tuple, int, QPixmap]] = None
        self._step_image: Optional[tuple[tuple, int, QImage]] = None   # the picked step of a stored render, decoded off-thread
        self._scans: dict[tuple, reveal_steps.SlideScan] = {}
        self._step_failed: set[tuple] = set()      # page lists that did not render: not asked for again
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
        self._chips_built: Optional[list] = None     # what the chips were built from, and the menu: a poll finds
        self._menu_built: Optional[tuple] = None     # them unchanged and leaves them

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANE_SIDE_MARGIN, SPACE.xl, PANE_SIDE_MARGIN, SPACE.xl)
        layout.setSpacing(SPACE.md)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(SPACE.sm)
        layout.addLayout(self._chips)
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

        status = QHBoxLayout()
        status.setSpacing(SPACE.md)
        self._status_chip = Chip("", "muted")
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
        layout.addLayout(status)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE.xl)
        self._id = QLabel()
        self._id.setObjectName(q.PREVIEW_ID)
        self._name = QLabel()
        self._name.setObjectName(q.PREVIEW_TITLE)
        footer.addWidget(self._id)
        footer.addWidget(self._name, 1)
        self._render = SplitButton("Render")
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
        changed = target is None or self._target is None or target.key != self._target.key
        mtime = _mtime(target.source_path) if target else 0
        if changed or mtime != self._shown_mtime:
            self._invalidate()
            self._record = None
        if changed:
            self._error = ""
            self._adhoc = None
            self._adhoc_spec = None
            self._steps.drop_background()
            now = time.monotonic()
            # Another slide within SCROLLING_MS of the last change: scrolling. Its checks would be superseded before
            # they answer, so none starts until the selection rests (_settled); a single click checks at once.
            self._defer_checks = target is not None and now - self._changed_at < SCROLLING_MS / 1000
            self._changed_at = now
            if target is not None:
                self._settle.start()
        self._target, self._row, self._title, self._message = target, row, title, message
        self._language = language
        self._shown_mtime = mtime
        self._refresh()

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
        self._record = None
        self._error = ""      # a failure belongs to the view and language it happened in
        self._refresh()

    def buffer_changed(self, path: Path) -> None:
        """Cancel this slide's queued views and refresh its age after typing pauses."""
        renderer = self._renders._background
        if renderer is not None:
            renderer.scheduler.cancel_group(f"other:{path.resolve()}")
        if self._target is not None and path == self._target.source_path:
            if self._batch_cancel is None:
                self._batch_status = ''
            self._buffer_notice.start()

    def _poll_selection(self):
        if self._target is not None and self.isVisible() and not self._closed:
            self._stored_asked = None
            self._step_pages = OrderedDict((key, pages) for key, pages in self._step_pages.items() if key[0] == 'draft')
            self._step_pixmap = self._step_image = None
            self._refresh()

    def _image(self, target: PreviewTarget) -> Optional[tuple[QPixmap, bool, str]]:
        """Show the chooser's page; held pixels authorize nothing while the strict check runs."""
        view, language = self.state.view, self.language
        key = (target.key, view, language)
        self._record = None
        try:
            buffer = self._buffer()
            text = buffer[0] if buffer is not None else target.source_path.read_text(encoding='utf-8')
            mtime, text_hash = _mtime(target.source_path), text_sha256(text)
            spec = PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language)
        except (OSError, ValueError):
            return None
        adhoc_here = self._adhoc is not None and self._adhoc[0] == key
        if adhoc_here and self._adhoc_spec is not None and not self._adhoc_spec.complete:
            same = text == self._adhoc_text
            return self._adhoc[1], same, self._adhoc[2] if same else 'Older than the editor buffer'
        request = self._last_request
        if (request is not None and not request.done.is_set() and request.spec.revision.content_hash == text_hash
                and (request.spec.target.key, request.spec.view, request.spec.language) == key):
            if adhoc_here:
                return self._adhoc[1], True, self._adhoc[2]
            held = self._pixmaps.get(key)
            if held is not None and (held.mtime, held.content_hash) == (mtime, text_hash):
                return held.pixmap, True, ''
        ident = (*key, mtime, text_hash)
        keep = (mtime, text_hash) if not self._is_draft(target) else None
        if not self._defer_checks and self._stored_asked != (self._generation, ident):
            self._stored_asked = (self._generation, ident)
            renderer = self._renders._renderer(target.context)
            choice = self._step_choice.get(target.source_path)

            def select():
                state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec),
                                                     strict=True)
                pages = renderer.store.pages(record) if record is not None else None
                data = pages[-1] if pages else None
                image = QImage.fromData(data) if data is not None else QImage()
                n = len(pages or ())
                step = min(max(choice if choice is not None else n, 1), n)
                step_image = QImage.fromData(pages[step - 1]) if pages and step != n else image
                return state, record, hashlib.sha256(data).hexdigest() if data else None, image, (pages, step, step_image)

            self._look_up('page', ident, select, lambda found: self._page_found(ident, keep, found))
        if self._stored is not None and self._stored[0] == ident and not self._checking():
            _, pixmap, _, state, record = self._stored
            if (state != 'current' and adhoc_here and self._adhoc_text == text
                    and (pixmap is None or (self._adhoc_spec is not None and self._adhoc_spec.target.needs_context))):
                return self._adhoc[1], False, 'Temporary preview; render to verify current source and settings.'
            if pixmap is not None:
                self._record = record
                note = {'current': '', 'previous': 'Previous render; render to verify current source and settings.',
                        'reference': 'Instructor reference; not verified for this deck, view or reveal steps.'}[state]
                return pixmap, state == 'current', note
            return None
        held = self._pixmaps.get(key)
        if held is not None and (held.mtime, held.content_hash) == (mtime, text_hash):
            return held.pixmap, False, CHECKING
        preloaded = self._preloaded(ident[:4])
        return (preloaded[0], False, CHECKING) if preloaded is not None else None

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
                self._stored_asked = None
                self._refresh()
        if getattr(request, 'done', None) is not None:
            QTimer.singleShot(50, poll)

    def _remember(self, key: tuple, pixmap: QPixmap, png: Optional[bytes], mtime: int, text: Optional[str]) -> None:
        """Hold saved pixels for checking, and the selected render as temporary until the store can answer."""
        if self._target is not None and key == (self._target.key, self.state.view, self.language):
            self._adhoc = (key, pixmap, '')
            self._adhoc_text = text
            self._adhoc_spec = None
            self._adhoc_full = False
        self._pixmaps.put(key, pixmap, mtime, text_sha256(text)
                          if text is not None else None,
                          hashlib.sha256(png).hexdigest() if png is not None else str(pixmap.cacheKey()))

    def _deck_name(self) -> str:
        deck = self.state.deck
        return deck.name if deck is not None else ""

    def _look_up(self, slot, identity: tuple, work: Callable, arrive: Callable) -> None:
        """Run `work()` (a store lookup with its reads and decodes) on the display worker; `arrive(its result)` runs
        on the GUI thread, if the selection is still the one asked for (the generation is part of the identity)."""
        identity = (self._generation, identity)
        held = self._lookups.get(slot)
        if self._closed or (held is not None and held[0] == identity):
            return
        if held is not None:
            held[1].cancel()
        future = self._display_executor.submit(work)
        self._lookups[slot] = (identity, future)
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
                pane._looked_up.emit(slot, identity, arrive, found)
            except RuntimeError:     # the pane is gone
                pass

        future.add_done_callback(finished)

    def _on_looked_up(self, slot, identity: tuple, arrive: Callable, found) -> None:
        held = self._lookups.get(slot)
        if self._closed or held is None or held[0] != identity:
            return                      # replaced or dropped since
        del self._lookups[slot]
        if identity[0] == self._generation:
            arrive(found)

    def _page_found(self, ident: tuple, keep: Optional[tuple], found) -> None:
        target = self._target
        if target is None or (target.key, self.state.view, self.language, _mtime(target.source_path)) != ident[:4]:
            return
        buffer = self._buffer()
        try:
            text = buffer[0] if buffer is not None else target.source_path.read_text(encoding='utf-8')
        except OSError:
            return
        if text_sha256(text) != ident[4]:
            self._refresh()
            return
        state, record, digest, image, steps = found if found is not None else ('missing', None, None, QImage(), None)
        pixmap = None
        if not image.isNull():
            held = self._pixmaps.get(ident[:3])
            if held is not None and held.image_hash == digest:
                pixmap = held.pixmap
                if keep is not None:
                    held.mtime, held.content_hash = keep
            else:
                pixmap = QPixmap.fromImage(image)
                if keep is not None:
                    pixmap = self._pixmaps.put(ident[:3], pixmap, *keep, digest)
        self._stored = (ident, pixmap, digest, state, record)
        if state == 'current' and pixmap is not None and target.needs_context:
            self._context_modes[ident[:3]] = deck_context.DECK
            if self._adhoc is not None and self._adhoc[0] == ident[:3]:
                self._adhoc = self._adhoc_spec = None
                self._adhoc_full = False
        if (steps is not None and steps[0]
                and (state == 'current' or self._adhoc_spec is None or not self._adhoc_spec.target.needs_context)):
            self._steps_found(self._current_steps(target)[0], steps)
        else:
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
        """Read the stored pages of the deck's view ahead, outward from the slide on show: the nearest PREFETCHED are
        decoded, the others kept as PNG (up to PRELOAD_BYTES), so the slide scrolled or clicked to shows at once. Only
        what the background renders stored: nothing is compiled. Called once the selection rests; reads queued for
        the order of before are dropped and queued again in the new one."""
        background = getattr(self.app, "background", None)
        if background is None or self._closed or self._overlay or self._scope != "slide":
            return
        view, language, deck = self.state.view, self.language, self._deck_name()
        context = (deck, view, language)
        if context != self._preload_context:
            self._drop_preloaded()
            self._preload_context = context
        for ident, future in list(self._prefetching.items()):
            if future.cancel():
                del self._prefetching[ident]
        now = time.monotonic()
        self._preload_missing = {i: at for i, at in self._preload_missing.items() if now - at < PRELOAD_RETRY}
        order = [(other, (other.key, view, language, _mtime(other.source_path))) for other in self._preload_order()]
        self._preload_rank = {ident: rank for rank, (_other, ident) in enumerate(order)}
        near = {ident for _other, ident in order[:PREFETCHED]}
        for ident in [i for i in self._prefetched if i not in near]:
            del self._prefetched[ident]
        owner = weakref.ref(self)
        for other, ident in order:
            decode = ident in near and ident not in self._prefetched
            held = self._compressed.get(ident)
            if ident in self._prefetching or ident in self._preload_missing or not decode and held is not None:
                continue
            future = self._prefetch_executor.submit(_preload_page, background, other, view, language,
                                                    held[0] if held is not None else None, decode)
            self._prefetching[ident] = future

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

    def _on_prefetched(self, context, ident, found) -> None:
        self._prefetching.pop(ident, None)
        if self._closed or context != self._preload_context:
            return
        if found is None:
            self._preload_missing[ident] = time.monotonic()
            return
        data, digest, image = found
        self._keep_compressed(ident, data, digest)
        if image is None or ident in self._prefetched or self._preload_rank.get(ident, PREFETCHED) >= PREFETCHED:
            return
        self._hold_decoded(ident, self._display_pixmap(QPixmap.fromImage(image)), digest)
        target = self._target                  # scrolled there while it was read: show it now
        if target is not None and (target.key, self.state.view, self.language, _mtime(target.source_path)) == ident:
            self._refresh()

    def _keep_compressed(self, ident, data: bytes, digest: str) -> None:
        """Hold the PNG of `ident`; beyond PRELOAD_BYTES the pages farthest from the slide on show give way (or this
        one, when it is the farthest)."""
        if ident in self._compressed:
            return
        rank = self._preload_rank.get(ident, len(self._preload_rank))
        while self._compressed and self._compressed_bytes + len(data) > PRELOAD_BYTES:
            farthest = max(self._compressed, key=lambda i: self._preload_rank.get(i, len(self._preload_rank)))
            if self._preload_rank.get(farthest, len(self._preload_rank)) <= rank:
                return
            self._compressed_bytes -= len(self._compressed.pop(farthest)[0])
        self._compressed[ident] = (data, digest)
        self._compressed_bytes += len(data)

    def _preloaded(self, ident) -> Optional[tuple]:
        """(QPixmap, digest) of a page read ahead for `ident`: decoded already, or decoded now from its PNG (a few
        milliseconds), or None."""
        if self._preload_context != (self._deck_name(), ident[1], ident[2]):
            return None
        if ident in self._prefetched:
            self._prefetched.move_to_end(ident)
            return self._prefetched[ident]
        held = self._compressed.get(ident)
        if held is None:
            return None
        pixmap = QPixmap()
        if not pixmap.loadFromData(held[0]):
            return None
        entry = (self._display_pixmap(pixmap), held[1])
        self._hold_decoded(ident, *entry)
        return entry

    def _hold_decoded(self, ident, pixmap: QPixmap, digest: str) -> None:
        """Keep a decoded page; at most PREFETCHED, the longest unused giving way (scrolling without a rest decodes
        page after page; the rest re-centres them on the slide on show)."""
        self._prefetched[ident] = (pixmap, digest)
        self._prefetched.move_to_end(ident)
        while len(self._prefetched) > PREFETCHED:
            self._prefetched.popitem(last=False)

    @staticmethod
    def _display_pixmap(pixmap: QPixmap) -> QPixmap:
        if pixmap.width() > DISPLAY_WIDTH:
            pixmap = pixmap.scaledToWidth(DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)
        return pixmap

    def _drop_preloaded(self) -> None:
        """Forget the pages read ahead (another deck, view or language; the pane closes). Python objects only."""
        for future in self._prefetching.values():
            future.cancel()
        self._prefetching.clear()
        self._prefetched.clear()
        self._compressed.clear()
        self._compressed_bytes = 0
        self._preload_rank = {}
        self._preload_missing = {}
        self._preload_context = None

    def _checking(self) -> bool:
        """Whether a check of the slide on show is still out (or waits for the selection to rest)."""
        return self._defer_checks or 'page' in self._lookups

    def _refresh(self) -> None:
        if self._closed:
            return
        target, row = self._target, self._row
        view, language = self.state.view, self.language
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
                chip = Chip(text, tone, icon, self, pressable=jump is not None or compile_view is not None)
                chip.setToolTip(tooltip)
                if jump is not None:
                    chip.clicked.connect(lambda path=jump: self._show_partner(path))
                elif compile_view is not None:
                    chip.clicked.connect(lambda v=compile_view: self.compile_requested.emit(v))
                self._chips.addWidget(chip)
            self._chips.addStretch(1)

        self._id.setText(target.bare_id if target else "")
        self._name.setText(self._title if target else "")
        self._render.setVisible(target is not None)
        self._render.setEnabled(target is not None)
        hidden = target is not None and (target.hidden or (row is not None and row.hidden))
        self._render.buttons()[0].setEnabled(target is not None and not hidden and self._batch_cancel is None)
        self._render.buttons()[0].setToolTip("This slide is hidden in the selected view." if hidden
                                           else "Render the saved file in the selected view")
        self._render.set_text(f"Render · {short_view(view)} · {language}")

        status, tone, icon, can_render = "", "muted", "", False
        has_image = False
        if target is None:
            self._page.show_message(self._message or "Select a slide in the list.", False)
        elif target.hidden or (row is not None and row.hidden):
            self._page.show_message(f"This slide is not typeset in the {VIEW_LABELS[view]} view.", False)
        else:
            found = self._image(target)
            has_image = found is not None
            if found is None and not busy_here and self._checking():
                # Its check is out: the last page stays with "Loading…" until the answer, not a flash of "No preview"
                # for every slide scrolled past (v8.53.0).
                if self._page.pixmap is None:
                    self._page.show_message(LOADING, False)
                else:
                    self._page.keep_dimmed()
                status, tone, icon = LOADING, "info", "autorenew"
            elif found is None:
                self._page.show_message(
                    f"No preview for the {VIEW_LABELS[view]} view yet." if not busy_here else "Rendering…",
                    not busy_here)
                if not busy_here:
                    self._render_context_slide(target)
            else:
                self._page.show_image(found[0])
                if found[2]:
                    status, tone, icon, can_render = found[2], "info" if found[1] else "warning", "edit_note", not found[1]
                elif not found[1]:
                    status, tone, icon, can_render = "Older than the slide's source", "warning", "history", True
        if busy_here:
            status = "Rendering…" if job is self._active else "Waiting to render…"
            tone, icon, can_render = "info", "autorenew", False
        elif self._error:
            status, tone, icon, can_render = "Render failed", "error", "error_outline", target is not None
        # An unsaved draft is not in a page rendered from the file; offer to render the buffer.
        shown = target is not None and not hidden
        draft = shown and not busy_here and self._is_draft(target)
        current = shown and self._adhoc is not None and self._adhoc[0] == (
            target.key, view, language) and self._buffer() is not None \
            and self._buffer()[0] == self._adhoc_text
        self._status_draft = bool(draft and not current)
        if self._status_draft:
            if not status:
                status, tone, icon = "Unsaved edits are not in this preview", "warning", "edit_note"
            can_render = True
        if self._batch_status:
            if self._batch_cancel is not None:
                status, tone, can_render = self._batch_status, "info", False
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
        self._status_chip.set_tone(tone)
        self._status_button.setVisible(can_render)
        self._error_label.setText(self._error)
        self._error_label.setVisible(bool(self._error))
        # Cache lookup above may have changed the PDF for this exact view.
        self._rebuild_menu()
        # The image found above: asking again would redo (and replace) the selection the background check made.
        self._update_reveal(target, row, shown, shown and has_image)

    # -- the reveal steps --------------------------------------------------------------------

    def _steps_busy(self) -> bool:
        """The pane is rendering for the user: background step renders wait (read from the queue's thread)."""
        return self._active is not None or self._pending is not None

    def _steps_done(self, key: tuple, pages: list[bytes], error: str) -> None:
        try:
            self._steps_ready.emit(key, pages, error)
        except RuntimeError:     # the pane is gone
            pass

    def _steps_key(self, target: PreviewTarget, view: str, language: str, draft: bool,
                   stamp) -> tuple:
        """Pane state for an all-steps selection or a temporary buffer render."""
        identity = target.key[1:3] + target.key[5:]       # not the macro, the versions or the steps of the call
        return ("draft" if draft else "saved", str(target.source_path), identity, view, language,
                hash(stamp) if draft else self._generation)

    def _scan_of(self, path: Path, text: Optional[str], stamp) -> reveal_steps.SlideScan:
        key = (str(path), stamp if text is not None else _mtime(path))
        scan = self._scans.get(key)
        if scan is None:
            if text is None:
                try:
                    text = slide_source.read_slide_source(path)[0]
                except OSError:
                    text = ""
            scan = self._scans[key] = reveal_steps.scan_slide(text)
            while len(self._scans) > 64:
                self._scans.pop(next(iter(self._scans)))
        return scan

    def _current_steps(self, target: PreviewTarget):
        """(key, text, draft, scan) of the page list that belongs to what the pane shows now."""
        view, language = self.state.view, self.language
        shown = (target.key, view, language)
        if self._adhoc is not None and self._adhoc[0] == shown and self._adhoc_full and self._adhoc_text is not None:
            text = self._adhoc_text
            key = self._steps_key(target, view, language, True, text)
            return key, text, bool(self._adhoc[2]), self._scan_of(target.source_path, text, hash(text))
        mtime = _mtime(target.source_path)
        return (self._steps_key(target, view, language, False, None), None, False,
                self._scan_of(target.source_path, None, mtime))

    def _after_render(self, job: _Job) -> None:
        """A render of the slide was accepted: its pages are the step list when it kept every step."""
        target = self._target
        if target is None or not job.steps_ok:
            return
        draft = bool(job.note)
        text = job.buffer_text if draft else job.revision_text
        key = self._steps_key(target, job.view, job.language, draft or bool(target.needs_context), text)
        if key in self._step_pages or self._steps.pending(key):
            return
        self._request_steps(target, key, job.request.spec.revision.text if job.request is not None else text,
                            draft, FOREGROUND)

    def _request_steps(self, target: PreviewTarget, key: tuple, text: Optional[str], draft: bool,
                       priority: int) -> None:
        """Queue the all-steps render for this pane selection."""
        if text is None:
            try:
                text = target.source_path.read_text(encoding='utf-8')
            except OSError:
                return
        if key[0] == 'draft':
            self._queue_steps(target, key, text, draft, priority)
        elif key not in self._step_pages:      # the store's pages first (off the GUI thread), a render if it has none
            self._adopt_stored_steps(target, key, lambda: self._queue_steps(target, key, text, draft, priority))

    def _queue_steps(self, target: PreviewTarget, key: tuple, text: str, draft: bool, priority: int) -> None:
        view, language = key[3], key[4]
        service, log = self._renders, self.app.log
        renderer = service._renderer(target.context)

        def build(cancel):
            request = service.request(target, text, view, language, log, saved=not draft, all_steps=True)
            pdf = request.wait(cancel)[0]
            state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=request.spec.unit,
                                                     spec=request.spec), strict=True)
            pages = renderer.store.pages(record) if state == 'current' else None
            return pages if pages is not None else reveal_steps.read_pages(pdf)

        self._steps.submit(key, priority, build)

    def _adopt_stored_steps(self, target: PreviewTarget, key: tuple,
                            render: Optional[Callable[[], None]] = None) -> None:
        """Read the chooser's step pages off-thread; `render` runs if none were found for this selection."""
        background = getattr(self.app, "background", None)
        if key in self._step_pages:
            return
        if background is None:
            if render is not None:
                render()
            return
        if render is not None:
            self._count_after[key] = render
        choice = self._step_choice.get(target.source_path)

        def read():
            renderer = background.renderer
            if renderer is None:
                return None
            spec = PreviewRequest(target, SourceRevision.capture(target.source_path), key[3], key[4],
                                  RenderOptions(all_steps=True))
            _state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec), strict=True)
            pages = renderer.store.pages(record) if record is not None else None
            if not pages:
                return None
            step = min(max(choice if choice is not None else len(pages), 1), len(pages))
            image = QImage.fromData(pages[step - 1]) if len(pages) > 1 else None
            return pages, step, image

        self._look_up(('steps', key), key, read, lambda found: self._steps_found(key, found))

    def _steps_found(self, key: tuple, found) -> None:
        render = self._count_after.pop(key, None)
        if found is None:
            if render is not None:
                render()
            return
        pages, step, image = found
        self._step_pixmap = None
        self._step_pages[key] = pages
        self._step_pages.move_to_end(key)
        while len(self._step_pages) > STEP_CACHE:
            self._step_pages.popitem(last=False)
        if image is not None:
            self._step_image = (key, step, image)
        self._refresh()

    def _settled(self) -> None:
        """The selection rested: the step bar may count the slide now, if it is still waiting for its steps."""
        target = self._target
        if self._defer_checks:
            self._defer_checks = False         # the selection rests: check the slide on show now
            if target is not None and not self._closed:
                self._refresh()
        if target is not None and not self._closed:
            hidden = target.hidden or (self._row is not None and self._row.hidden)
            self._update_reveal(target, self._row, not hidden, not hidden and self._page.pixmap is not None)
            self._prefetch_neighbours()

    def _probe_steps(self) -> None:
        """Idle: count the steps of the slide on show (and of its other versions when its reveals depend on them)."""
        target = self._target
        if target is None or self._closed or (self._row is not None and self._row.hidden):
            return
        if self._steps_busy():
            self._probe.start(PROBE_MS)       # the user's own render first; ask again afterwards
            return
        key, text, draft, scan = self._current_steps(target)
        if key not in self._step_pages and key not in self._step_failed:
            self._request_steps(target, key, text, draft, BACKGROUND)
        if scan.version_dependent and self._reveal.expanded:
            self._request_other_views(target, key, text, draft, self._served_views())
        view, language = self.state.view, self.language
        for other, _row in self.neighbours()[:NEIGHBOURS]:
            other_key = self._steps_key(other, view, language, False, None)
            if other_key not in self._step_pages and other_key not in self._step_failed:
                self._request_steps(other, other_key, None, False, BACKGROUND)

    def _block_calls(self, row: Optional[SlideRow]) -> tuple[list, list]:
        """(every slide call of the open deck, the calls that decide the steps at `row`'s place)."""
        deck = self.state.deck
        if row is None or deck is None:
            return [], []
        calls = deck_editor.parse_slide_calls(deck)
        physical = row.deck_call
        if not any(c.call_start == physical.call_start for c in calls):
            return calls, []
        return calls, deck_editor.step_block(deck.text, calls, physical)

    def _served_views(self) -> list[str]:
        """The versions the selected place of the deck typesets; all of them for a slide shown without the deck."""
        if self._row is None:
            return list(VIEWS)
        block = self._block_calls(self._row)[1] or [self._row.call]
        return [v for v in VIEWS if any(c.included_in(v) for c in block)]

    def _request_other_views(self, target: PreviewTarget, key: tuple, text: Optional[str], draft: bool,
                             views: list[str]) -> None:
        for view in views:
            other = key[:3] + (view,) + key[4:]
            if view != key[3] and other not in self._step_pages and other not in self._step_failed:
                self._request_steps(target, other, text, draft, BACKGROUND)

    def _on_steps_ready(self, key: tuple, pages: list[bytes], error: str) -> None:
        if self._closed:
            return
        if error:
            self._step_failed.add(key)
            self.app.log(f"    (reveal steps not counted: {error})")
            return
        self._step_failed.discard(key)
        self._step_pages[key] = pages
        self._step_pages.move_to_end(key)
        while len(self._step_pages) > STEP_CACHE:
            self._step_pages.popitem(last=False)
        self._refresh()

    def _on_tick_toggled(self, view: str, step: int) -> None:
        """A tick of the step bar was clicked: add the step to (or take it from) what `view` typesets at this place of
        the open deck, by rewriting the deck's \\slidestep calls (deck_editor.steps_edit)."""
        target, row, deck, edit = self._target, self._row, self.state.deck, self.edit_deck
        if target is None or row is None or deck is None or edit is None:
            return
        key, _text, draft, scan = self._current_steps(target)
        pages = self._step_pages.get(key)
        if pages is None:
            return
        rows = self._step_rows(target, row, key, len(pages), scan, draft)
        spec = rows[view]
        if not spec.editable or spec.plan is None:
            return
        steps = set(spec.plan.included) ^ {step}
        if not steps:
            self.app.toast.show_message("A version must keep at least one step: hide the slide in the "
                                        "visibility matrix instead.")
            return
        calls, block = self._block_calls(row)
        served = [v for v in VIEWS if any(c.included_in(v) for c in block)]
        counts = {v: len(self._step_pages.get(key[:3] + (v,) + key[4:]) or ()) or
                  (len(pages) if not scan.version_dependent else 0) for v in served}
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
            self._step_choice.pop(path, None)
        else:
            self._step_choice[path] = step

    def _on_step_selected(self, step: int) -> None:
        target = self._target
        if target is not None:
            self._step_choice[target.source_path] = step
            self._refresh()

    def _step_rows(self, target: PreviewTarget, row: Optional[SlideRow], key: tuple, n: int,
                   scan: reveal_steps.SlideScan, draft: bool = False) -> dict[str, RowSpec]:
        call = row.call if row is not None else None
        calls, block = self._block_calls(row) if self.edit_deck is not None else ([], [])
        served = [v for v in VIEWS if any(c.included_in(v) for c in block)]
        counts: dict[str, int] = {}
        for view in VIEWS:
            pages = self._step_pages.get(key[:3] + (view,) + key[4:])
            counts[view] = len(pages) if pages is not None else (n if not scan.version_dependent else 0)
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
            saved = self._step_pages.get(("saved",) + key[1:5] + (self._generation,)) \
                if self._target is not None else None
            if saved is None or len(saved) != counts[view]:
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

    def _update_reveal(self, target: Optional[PreviewTarget], row: Optional[SlideRow], shown: bool,
                       has_image: bool) -> None:
        """Show the step bar for the slide on show, and the page of the step picked."""
        bar = self._reveal
        if target is None or not shown:
            bar.setVisible(False)
            return
        key, text, draft, scan = self._current_steps(target)
        if key not in self._step_pages and key[0] != 'draft' and key not in self._step_failed and not self._defer_checks:
            self._adopt_stored_steps(target, key)           # a current render in the store: no counting at all
        pages = self._step_pages.get(key)
        if pages is None:
            if scan.may_reveal and key not in self._step_failed:
                bar.show_counting()
                # The user is looking at "Counting": do it now, ahead of any neighbour's count, not after the idle wait
                # - once the selection has rested (`_settled`): moving through slides starts no count.
                if not self._steps_busy() and not self._settle.isActive():
                    self._request_steps(target, key, text, draft, FOREGROUND)
            else:
                bar.setVisible(False)
            self._probe.start(PROBE_MS)
            return
        self._step_pages.move_to_end(key)
        self._probe.start(PROBE_MS)
        n = len(pages)
        view = self.state.view
        rows = self._step_rows(target, row, key, n, scan, draft)
        step = min(max(self._step_choice.get(target.source_path, n), 1), n)
        bar.set_state(view, step, rows, draft)
        if bar.expanded and scan.version_dependent:
            self._probe.start(0)
        restricted = (target.macro == "slidestep" or scan.own_frame_spec is not None or scan.frame_breaks
                      or (scan.final_flag and view != reveal_steps.INSTRUCTOR))
        if n > 1 and (step != n or restricted or not has_image):
            if self._step_pixmap is None or self._step_pixmap[:2] != (key, step):
                if self._step_image is not None and self._step_image[:2] == (key, step):
                    pixmap = QPixmap.fromImage(self._step_image[2])       # decoded by the display worker
                else:
                    pixmap = QPixmap()
                    pixmap = pixmap if pixmap.loadFromData(pages[step - 1]) else None
                self._step_image = None
                self._step_pixmap = (key, step, pixmap) if pixmap is not None else None
            if self._step_pixmap is not None and self._step_pixmap[:2] == (key, step):
                self._page.show_image(self._step_pixmap[2])

    def _rebuild_menu(self) -> None:
        all_enabled = self.can_render_all
        pdf_available = self._record is not None or self._adhoc_spec is not None
        built = (self._target is not None and not self._target.hidden, self._batch_cancel is not None, all_enabled,
                 self._busy, self._scope, self._overlay, pdf_available)
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
        reason = ("Wait for the current preview render to finish." if self._busy or self._batch_cancel is not None
                  else "All views requires Whole slide and all reveal steps.")
        menu.setToolTip(reason if not all_enabled and self._target is not None else "")
        menu.add_header("Saved file")
        menu.add_item(ALL_SAVED, "Render all views · saved file", enabled=all_enabled,
                      meta="" if all_enabled else reason)
        menu.add_item(FORCE, "Force rerender current view", enabled=has_buffer and not self._target.hidden,
                      meta="bypass completed cache")
        menu.add_separator()
        menu.add_header("Editor buffer, as it is now")
        menu.add_item(BUFFER, "Render the buffer", meta="Ctrl+Enter", enabled=has_buffer)
        menu.add_item(ALL_BUFFER, "Render all views · editor buffer", enabled=all_enabled,
                      meta="" if all_enabled else reason)
        for scope, label in SCOPES:
            menu.add_item(f"scope:{scope}", label, icon="check" if scope == self._scope else "")
        menu.add_item(OVERLAY, f"Reveal step: {self._overlay or 'all'}…", enabled=self._scope != "element")
        menu.add_separator()
        menu.add_item(PRESENTER, "Presenter PDF", meta="opens in the viewer", enabled=has_buffer)
        menu.add_item(TRANSCRIPT, "Render transcript", enabled=has_buffer)
        menu.add_item(OPEN_PDF, "Open PDF for this view", enabled=pdf_available and not self._busy)
        if self._batch_cancel is not None:
            menu.add_separator()
            menu.add_item(STOP, "Stop rendering all views")
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
        elif key.startswith("scope:"):
            self._scope = key.removeprefix("scope:")
            self._rebuild_menu()
        elif key == OVERLAY:
            number, ok = QInputDialog.getInt(
                self, "Reveal step", "Show only this step of each frame (0: all steps):", self._overlay, 0, 9999)
            if ok:
                self._overlay = number
                self._rebuild_menu()
        elif key == PRESENTER:
            self.render_buffer(presenter=True)
        elif key == TRANSCRIPT:
            self.render_transcript()
        elif key == OPEN_PDF:
            self._open_pdf()

    def _open_pdf(self) -> None:
        """Open a copy independent of store replacement and eviction."""
        if self._record is not None:
            target, view, language = self._target, self.state.view, self.language
            buffer = self._buffer()
            text = buffer[0] if buffer is not None else None
            renderer = self._renders._renderer(target.context)

            def copy():
                spec = PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language)
                _state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec),
                                                      strict=True)
                if record is None:
                    return None
                owner = renderer.store.pdf_copy(record)
                return owner, owner.__enter__()

            def open_copy(found):
                if found is not None:
                    owner, pdf = found
                    self._pdf_copies.push(owner)
                    if pdf is not None:
                        slide_preview.open_pdf(pdf)

            self._look_up('pdf', (target.key, view, language, text), copy, open_copy)
        elif self._target is not None and self._adhoc_spec is not None and not self._busy:
            spec = self._adhoc_spec
            job = self._job(self._target, external=True, revision_text=self._adhoc_text)
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
        # `_pixmaps` stay for a return visit.
        self._generation += 1
        if self._active is not None:
            self._active.cancel.set()
        for _identity, future in self._lookups.values():
            future.cancel()
        self._lookups.clear()
        self._count_after.clear()
        self._step_pages.clear()
        self._step_pixmap = self._step_image = None
        self._stored = None
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
                            # Recording continues independently; its PNG is the fallback if the temp file vanished.
                            job.pdf, job.png, _, _ = job.request.wait(job.cancel)
                    if job.png is not None:
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
        if text is None:
            return True
        try:
            current = buffer[0] if buffer is not None else job.source.read_text(encoding='utf-8')
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
            self._stored_asked = None
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
            else:
                pixmap = QPixmap.fromImage(job.image) if job.image is not None else QPixmap()
                if not pixmap.isNull() or (job.png is not None and pixmap.loadFromData(job.png)):
                    key = (job.target_key, job.view, job.language)
                    if job.note or (job.request is not None and (not job.request.spec.complete
                                                               or job.request.spec.target.needs_context)):
                        self._adhoc = (key, pixmap, job.note)
                        self._adhoc_text = job.revision_text
                        self._adhoc_full = job.steps_ok
                        self._adhoc_spec = job.request.spec if job.request is not None else None
                    else:
                        self._remember(key, pixmap, job.png, job.mtime, job.revision_text)
            job.pdf = None
            self.rendered.emit()
            if not job.external:
                if job.request is not None:
                    self._renders._renderer(job.request.spec.target.context).submit_other_views(job.request.spec)
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
        return _Job(target_key=target.key, view=self.state.view, language=self.language,
                    mtime=_mtime(target.source_path), source=target.source_path, **fields)

    def render_now(self) -> None:
        """Compile the saved slide in the view and language being edited."""
        self._render_saved(precheck=True)

    def _status_clicked(self) -> None:
        if self._status_draft:
            self.render_buffer()
        else:
            self.render_now()

    def _is_draft(self, target: PreviewTarget) -> bool:
        """The editor holds text that is not in the saved file."""
        buffer = self._buffer()
        if buffer is None:
            return False
        try:
            return buffer[0] != slide_source.read_slide_source(target.source_path)[0]
        except OSError:
            return False

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
        text = (self._buffer() or (saved_text, ""))[0]
        if latex_lint.check_buffer(self.app.project, text, path.name, path).errors:
            self._invalidate()
            self._refresh()
            return
        render_text = text
        if text != saved_text and slide_versioning.is_current_slide(path):
            # Autosave adds the version marker; capture the same text now so its later write is a store hit.
            render_text, _ = slide_versioning.prepare_autosave(path, target.id_slug, saved_text, text)
        job = self._job(target, revision_text=text, buffer_text=text,
                        note="Rendered from the editor buffer, not the saved file" if text != saved_text else "")
        job.request = self._renders.request(target, render_text, self.state.view, self.language, self.app.log,
                                            saved=text == saved_text)
        self._start(lambda: None, job, debounce=True)

    def render_buffer(self, presenter: bool = False) -> None:
        """Compile the editor's buffer, saved or not, per the scope and reveal step chosen."""
        target = self._target
        if target is None or self._batch_cancel is not None or (target.hidden and not presenter):
            return
        text, selection = self._buffer() or (slide_source.read_slide_source(target.source_path)[0], "")
        scope = "slide" if presenter else self._scope
        body = text if scope == "slide" else selection
        if not body.strip():
            QMessageBox.information(self, "Render the buffer", "Select some LaTeX to render first.")
            return
        path = target.source_path
        if not render_check.confirm_render(
                self, self.app, latex_lint.check_buffer(self.app.project, body, path.name, path), f"{path.name} (editor buffer)",
                show_in_editor=lambda issue: self.app.open_slide_editor(path, line=issue.line)):
            return
        view, language = self.state.view, self.language
        overlay = None if scope == "element" else (self._overlay or None)
        job = self._job(target, external=presenter, buffer_text=text, revision_text=text,
                        note="Rendered from the editor buffer, not the saved file",
                        steps_ok=scope == "slide" and overlay is None and not presenter)
        job.request = self._renders.request(target, body, view, language, self.app.log,
                                            presenter=presenter, mode=scope, overlay=overlay)
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
        return (self._current_render_context()[0] is not None and self._scope == 'slide' and not self._overlay
                and self._batch_cancel is None and not self._busy and not self._closed)

    def render_all_views(self, *, saved: bool = True) -> None:
        """Render one captured revision in all views on a worker, without moving focus."""
        if not self.can_render_all:
            return
        self._sync_render_context()
        target = self._target
        try:
            text = target.source_path.read_text(encoding='utf-8') if saved else (
                self._buffer() or (target.source_path.read_text(encoding='utf-8'), ''))[0]
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
        job = _Job(target_key=target.key, source=target.source_path, mtime=_mtime(target.source_path),
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
        job.metrics = dict(request.metrics or {})
        self._on_finished(job)
        job.remote = False

    def publish_batch_result(self, result, generation) -> str:
        """Publish a valid batch result without changing the selected slide or view."""
        if self._closed:
            return 'superseded'
        spec = result.request
        target, revision, options = spec.target, spec.revision, spec.options
        matching = (self._target is not None and self._target.key == target.key
                    and (self.state.view, self.language) == (spec.view, spec.language))
        try:
            saved = target.source_path.read_text(encoding='utf-8') == revision.text
        except OSError:
            saved = False
        buffer = self._buffer() if matching else None
        if buffer is not None and buffer[0] != revision.text:
            return 'superseded'
        # A newer render owns the visible pane. A view switch alone need not
        # reject useful batch output when the captured revision is still current.
        if matching and generation != self._generation and (self._adhoc is not None or self._active is not None):
            return 'superseded'
        if saved:
            return self.publish_refresh(target, revision.text, _mtime(target.source_path),
                                        spec.view, spec.language,
                                        result.artifact(), self._generation)
        if options.saved:
            return 'superseded'
        if not matching or buffer is None:
            return 'cached'
        pixmap = QPixmap()
        if result.display_png is None or not pixmap.loadFromData(result.display_png):
            raise RuntimeError('The rendered preview image could not be read')
        key = (target.key, spec.view, spec.language)
        self._adhoc = (key, pixmap, 'Rendered from the editor buffer, not the saved file')
        self._adhoc_text = revision.text
        self._adhoc_spec = spec
        self._stored_asked = None
        self._error = ''
        self._refresh()
        self.rendered.emit()
        self.rendered_target.emit(target.source_path)
        return 'displayed'

    def publish_refresh(self, target, text, revision, view, language, artifact, generation) -> str:
        """GUI-thread publication of a saved preview refresh, without changing the focus."""
        if self._closed:
            return 'superseded'
        try:
            if _mtime(target.source_path) != revision or target.source_path.read_text(encoding='utf-8') != text:
                return 'superseded'
        except OSError:
            return 'superseded'
        matching = (self._target is not None and self._target.key == target.key
                    and (self.state.view, self.language) == (view, language))
        # A changed buffer or a later pane render owns the visible page, even if disk is unchanged.
        if matching and (generation != self._generation or (self._buffer() is not None and self._buffer()[0] != text)):
            return 'superseded'
        pdf, png, _, _ = artifact
        pixmap = QPixmap()
        if png is None or not pixmap.loadFromData(png):
            raise RuntimeError('The rendered preview image could not be read')
        key = (target.key, view, language)
        self._remember(key, pixmap, png, revision, text)
        if matching:
            self._stored_asked = None
            self._error = ''
            self._refresh()
        self.rendered.emit()
        self.rendered_target.emit(target.source_path)
        return 'displayed' if matching else 'cached'

    def render_transcript(self) -> None:
        """A one-slide transcript preview of the buffer (nothing is written to disk)."""
        target = self._target
        if target is None:
            return
        buffer = self._buffer()
        text = buffer[0] if buffer else slide_source.read_slide_source(target.source_path)[0]
        show_transcript_preview(self.app, text, target.bare_id, target.id_slug, self.state.view, self.language)


def _mtime(path: Optional[Path]) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
