"""The Preview view: the focused slide as a page, in the view (Instructor /
During course / After course) and language the top bar says.

Without compiling anything it shows the slide's cached snapshot
(slide_snapshot.py; the instructor view only) or what this session rendered.
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
import hashlib
from threading import Thread
import shutil
import time
import weakref
from dataclasses import dataclass, replace
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from ... import latex_lint, slide_preview, slide_snapshot, slide_source, slide_versioning
from ...ai.claude_tasks import LANGUAGE_NAMES
from ...ai.workspace import WorkspaceContext
from ...ai.tools.slidemage import slide_target
from ...deck_outline import SlideRow
from ...preview_target import PreviewTarget
from ...preview_requests import PreviewRequest, RenderOptions, RenderRequest, RenderService, SourceRevision
from ...preview_selection import SelectedImage, legacy_reference, remember_transient, validate_captured, validate_scoped
from ...preview_metrics import PreviewMetrics
from ...slide_language import TRANSLATION_LANGUAGES, TranslationLink, own_language, translation_link
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit import kit_qss as q
from ..kit.tokens import Tokens
from ..kit.widgets import Button, Chip, PopoverMenu, SplitButton, Surface, clear_layout
from . import render_check
from .menus import VIEW_LABELS
from .state import WorkspaceState

PAGE_ASPECT = 16 / 9
SCOPES = (("slide", "Whole slide"), ("region", "Selection as frame"), ("element", "Selection as element"))
# Menu keys.
BUFFER, OVERLAY, PRESENTER, TRANSCRIPT, OPEN_PDF = "buffer", "overlay", "presenter", "transcript", "open_pdf"
ALL_SAVED, ALL_BUFFER, FORCE, STOP = "all_saved", "all_buffer", "force", "stop"


def short_view(view: str) -> str:
    return VIEW_LABELS[view].replace(" course", "")


def partner_link(target: PreviewTarget, link: Optional[TranslationLink]) -> Optional[TranslationLink]:
    """`link` if it leads to the slide's file in the other language, else None."""
    return link if link is not None and link.language not in (None, own_language(target.id_slug)) else None


def chips_for(target: PreviewTarget, row: Optional[SlideRow], view: str, language: str,
              link: Optional[TranslationLink] = None) -> list[tuple]:
    """(icon, text, tone, tooltip) of the chips above the page. `row` is the
    slide's row in the open deck, None for a file shown alone; `link` the translation
    partner of the file shown, if it has one."""
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
    if link is not None and link.outdated:
        chips.append(("translate", "Translation outdated", "warning",
                      "The original was saved after the translation was last written (Language panel)."))
    own = own_language(target.id_slug)
    if own and (partner := partner_link(target, link)):
        chips.append(("language", f"{own} + {partner.language}", "neutral",
                      f"Go to the {LANGUAGE_NAMES.get(partner.language, partner.language)} "
                      f"{'original' if partner.is_translation else 'version'}"))
    elif own:
        chips.append(("language", own, "neutral", "The slide's language; it has no translation."))
    return chips


def render_context(window, path: Path) -> Optional[tuple[PreviewTarget, str, str, bool]]:
    """(target, view, language, footer timestamp) for rendering the slide file `path` as the top bar says: in its own
    language when that is one of EN and DE, as the open deck calls it. None when `path` is no slide file."""
    state = window.state
    language = own_language(path.name)
    language = language if language in TRANSLATION_LANGUAGES else state.language
    target = slide_target(window.project, state.deck, path, state.view, language,
                          occurrence_key=getattr(state, "focused_occurrence", None))
    return None if target is None else (target, state.view, language, state.footer_timestamp)


@dataclass
class _Job:
    """A finished render, handed from the worker thread to the GUI thread."""
    pdf: Optional[Path] = None
    png: Optional[bytes] = None
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
    timestamp: bool = False
    snapshot_template: Optional[str] = None
    images: tuple = ()
    requested: float = 0
    metrics: Optional[dict] = None
    request: Optional[RenderRequest] = None
    revision_text: Optional[str] = None
    remote: bool = False


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
            owner._selection_executor.shutdown(wait=False, cancel_futures=True)
            owner._renders.close()
            owner._pending = None
            owner._generation += 1
        if self.job is not None:
            _discard_job(self.job)


class PageView(QWidget):
    """The page: a white 16:9 rectangle with a soft shadow, holding the slide's image,
    or, when there is none, a surface-colored one with a message. `tokens()` gives the
    theme's colors."""

    def __init__(self, tokens: Callable[[], Tokens]) -> None:
        super().__init__()
        self._tokens = tokens
        self.pixmap: Optional[QPixmap] = None
        self.message = ""
        self.setMinimumSize(320, 180)
        self.render_button = Button("Render now", "primary", self)
        self.render_button.hide()

    def show_image(self, pixmap: QPixmap) -> None:
        self.pixmap, self.message = pixmap, ""
        self.render_button.hide()
        self.update()

    def show_message(self, message: str, can_render: bool) -> None:
        self.pixmap, self.message = None, message
        self.render_button.setVisible(can_render)
        self._place_button()
        self.update()

    def _page_rect(self) -> QRectF:
        aspect = self.pixmap.width() / self.pixmap.height() if self.pixmap else PAGE_ASPECT
        area = QRectF(self.rect()).adjusted(24, 24, -24, -24)
        width = min(area.width(), area.height() * aspect)
        height = width / aspect
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def _place_button(self) -> None:
        page = self._page_rect()
        hint = self.render_button.sizeHint()
        self.render_button.move(int(page.center().x() - hint.width() / 2), int(page.center().y() + 14))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_button()

    def paintEvent(self, event) -> None:
        page = self._page_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((6, 8), (3, 14), (1, 22)):   # a soft shadow, as the prototype's
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(page.adjusted(-grow, -grow, grow, grow).translated(0, grow), 4 + grow, 4 + grow)
        tokens = self._tokens()
        painter.setBrush(QColor(tokens.paper) if self.pixmap is not None else QColor(tokens.surface))
        painter.drawRoundedRect(page, 4, 4)
        if self.pixmap is not None:
            painter.drawPixmap(page, self.pixmap, QRectF(self.pixmap.rect()))
        elif self.message:
            painter.setPen(QColor(tokens.text))
            painter.drawText(page.adjusted(24, 24, -24, -24).translated(0, -18),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                             self.message)


class PreviewPane(Surface):
    rendered = Signal()           # a render finished; the slide's snapshot (the list's thumbnail) may be new
    rendered_target = Signal(object)  # exact source path for affected thumbnail rows
    partner_requested = Signal(object)   # the language chip: the Path of the slide's file in the other language
    _finished = Signal(object)    # a _Job, from the worker thread
    _batch_progressed = Signal(object)
    _batch_finished = Signal(object, str)
    _selection_finished = Signal(object)

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
        self._selection_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='preview-selection')
        self._selection_ticket = 0
        self._selection_pending = None
        self._selection_pending_key = None
        self._selection_result = None
        self._selection_result_key = None
        self._selection_validated_at = 0.0
        self._selection_metrics = {}
        self._selection_gui_latency = 0.0
        self._background_validation = True
        self._selection_finished.connect(self._on_selection_finished)
        self._remote = {}
        self._shown_mtime = 0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
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
        self._last_pdf: Optional[Path] = None
        self._displayed_spec = None
        self._image_selection = None
        self._scope = "slide"
        self._overlay = 0
        # Renders this session: (target.key, view, language, timestamp) -> image.
        self._pixmaps: OrderedDict[tuple, tuple[QPixmap, int]] = OrderedDict()
        # The latest render of the editor buffer: (target.key, view, language) -> (pixmap, note).
        self._adhoc: Optional[tuple[tuple, QPixmap, str]] = None
        self._adhoc_text: Optional[str] = None
        self._finished.connect(self._on_finished)
        self._batch_progressed.connect(self._on_batch_progress)
        self._batch_finished.connect(self._on_batch_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(8)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        layout.addLayout(self._chips)
        self._page = PageView(lambda: self.app.theme.tokens)
        self._page.render_button.clicked.connect(self.render_now)
        layout.addWidget(self._page, 1)

        status = QHBoxLayout()
        status.setSpacing(8)
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
        footer.setSpacing(12)
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

        state.view_changed.connect(self._on_context_changed)
        state.language_changed.connect(self._on_context_changed)
        state.footer_timestamp_changed.connect(self._on_context_changed)
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
            self._last_pdf = None
            self._displayed_spec = None
            self._image_selection = None
        if changed:
            self._error = ""
            self._adhoc = None
            self._adhoc_spec = None
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
        self._last_pdf = None
        self._displayed_spec = None
        self._image_selection = None
        self._error = ""      # a failure belongs to the view and language it happened in
        self._refresh()

    def buffer_changed(self, path: Path) -> None:
        """Refresh a buffer preview's age after typing pauses, without compiling."""
        if self._target is not None and path == self._target.source_path:
            if self._batch_cancel is None:
                self._batch_status = ''
            self._buffer_notice.start()

    def _select_in_background(self, target, text, view, language, timestamp, reference, *, scoped_spec=None):
        key = (self._generation, target.key, view, language, timestamp,
               hashlib.sha256(text.encode('utf-8')).hexdigest(),
               scoped_spec.options.mode if scoped_spec is not None else 'slide',
               scoped_spec.options.overlay if scoped_spec is not None else None)
        if self._selection_result_key == key and time.monotonic() - self._selection_validated_at < 5:
            return self._selection_result
        retained = self._selection_result if (self._selection_result_key is not None and
                  self._selection_result_key[1:5] == key[1:5] and
                  self._selection_result_key[6:] == key[6:]) else None
        if self._selection_pending_key != key:
            if self._selection_pending is not None:
                self._selection_pending.cancel()
            self._selection_ticket += 1
            ticket = self._selection_ticket
            self._selection_pending_key = key
            dispatched = time.perf_counter()
            QTimer.singleShot(0, lambda: setattr(self, '_selection_gui_latency',
                                                 time.perf_counter() - dispatched)
                              if not self._closed else None)
            if scoped_spec is None:
                revision = SourceRevision.capture(target.source_path, text)
                specs = (PreviewRequest(target, revision, view, language, RenderOptions(timestamp, saved=True)),)
                future = self._selection_executor.submit(validate_captured, specs, reference)
            else:
                future = self._selection_executor.submit(validate_scoped, scoped_spec)
            self._selection_pending = future
            owner = weakref.ref(self)

            def finished(done):
                pane = owner()
                if pane is None or pane._closed:
                    return
                try:
                    value = done.result()
                except Exception as exc:  # noqa: BLE001 -- failed validation is a missing image
                    value = (None, {'error': str(exc)})
                try:
                    pane._selection_finished.emit((ticket, key, value))
                except RuntimeError:
                    pass

            future.add_done_callback(finished)
        if retained is not None and retained.image is not None and retained.state == 'verified':
            return replace(retained, state='previous', pdf=None,
                           note='Checking current source and settings…')
        return retained

    def _show_accepted_while_validating(self, spec, png):
        if (not self._background_validation or png is None or spec.options.mode != 'slide'
                or spec.options.overlay is not None):
            return
        self._selection_ticket += 1
        if self._selection_pending is not None:
            self._selection_pending.cancel()
        self._selection_pending = self._selection_pending_key = None
        key = (self._generation, spec.target.key, spec.view, spec.language,
               spec.options.footer_timestamp, spec.revision.content_hash,
               spec.options.mode, spec.options.overlay)
        self._selection_result_key = key
        self._selection_result = SelectedImage(
            'previous', png, spec, hashlib.sha256(png).hexdigest(), spec.view, None,
            'Rendered; checking current source and settings…',
            artifact_revision_hash=spec.revision.content_hash)
        self._selection_validated_at = 0.0

    def _on_selection_finished(self, payload):
        ticket, key, (selected, metrics) = payload
        if self._closed or ticket != self._selection_ticket or key != self._selection_pending_key:
            return
        self._selection_pending = None
        self._selection_pending_key = None
        target = self._target
        if target is None or (self._generation, target.key, self.state.view, self.language,
                              self._footer_timestamp()) != key[:5]:
            return
        try:
            buffer = self._buffer()
            current = buffer[0] if buffer is not None else target.source_path.read_text(encoding='utf-8')
        except OSError:
            return
        if hashlib.sha256(current.encode('utf-8')).hexdigest() != key[5]:
            self._refresh()  # recapture the editor/disk revision after a mid-validation edit
            return
        if metrics.get('unstable'):
            QTimer.singleShot(150, self._refresh)
            return
        self._selection_result_key = key
        self._selection_result = selected
        self._selection_validated_at = time.monotonic()
        self._selection_metrics = metrics
        self._selection_metrics['gui_event_latency_seconds'] = self._selection_gui_latency
        if selected is not None and selected.cache_entry is not None and selected.cache_entry.pdf is not None:
            from ...preview_cache import PreviewCache
            try:
                self._renders._retain_display(PreviewCache(target.context.root), selected.cache_entry,
                                              blocking=False)
            except OSError:
                selected = replace(selected, pdf=None)
                self._selection_result = selected
        self._refresh()

    def _poll_selection(self):
        if self._target is not None and self.isVisible() and not self._closed:
            self._refresh()

    def _image(self, target: PreviewTarget, *, background=False) -> Optional[tuple[QPixmap, bool, str]]:
        """Select one whole-slide image policy, with explicit previous/reference states."""
        view, language = self.state.view, self.language
        key = (target.key, view, language, self._footer_timestamp())
        verified = None
        selected = None
        self._image_selection = None
        scoped = False
        text = None
        adhoc_here = self._adhoc is not None and self._adhoc[0] == key
        try:
            buffer = self._buffer()
            text = buffer[0] if buffer is not None else target.source_path.read_text(encoding='utf-8')
            adhoc_spec = getattr(self, '_adhoc_spec', None)
            scoped = (adhoc_here and adhoc_spec is not None
                      and (adhoc_spec.options.mode != 'slide' or adhoc_spec.options.overlay is not None))
            if scoped and (buffer is None or buffer[0] == self._adhoc_text):
                if background:
                    selected = self._select_in_background(target, text, view, language,
                                self._footer_timestamp(), None, scoped_spec=adhoc_spec)
                    self._image_selection = selected
                else:
                    verified = self._renders.cached_spec(adhoc_spec)
            else:
                legacy = None if target.is_frozen_alone else legacy_reference(
                    target.context, target.bare_id, target.template, target.id_slug)
                selected = (self._select_in_background(target, text, view, language,
                            self._footer_timestamp(), legacy) if background else
                            self._renders.selected_preview(target, text, view, language,
                                                           self._footer_timestamp(), reference=legacy))
                self._image_selection = selected
        except (OSError, ValueError):
            pass
        if verified is not None and verified.display_png is not None:
            pixmap = QPixmap()
            if pixmap.loadFromData(verified.display_png):
                self._last_pdf = verified.pdf
                self._displayed_spec = getattr(verified, 'request_spec', None)
                return pixmap, True, self._adhoc[2] if adhoc_here else ''
        if selected is not None and selected.image is not None and selected.fresh:
            pixmap = QPixmap()
            if isinstance(selected.image, bytes) and pixmap.loadFromData(selected.image):
                self._last_pdf = selected.pdf
                self._displayed_spec = selected.request
                return pixmap, True, ''
        if selected is not None and selected.state == 'previous' and isinstance(selected.image, bytes):
            pixmap = QPixmap()
            if pixmap.loadFromData(selected.image):
                self._last_pdf = selected.pdf
                self._displayed_spec = None
                return pixmap, False, selected.note
        if selected is not None and selected.state == 'reference' and selected.image is not None:
            pixmap = QPixmap(str(selected.image))
            if not pixmap.isNull():
                self._last_pdf = None
                self._displayed_spec = None
                return pixmap, False, selected.note
        if scoped and self._adhoc is not None and self._adhoc[0] == key:
            buffer = self._buffer()
            same_text = buffer is None or buffer[0] == self._adhoc_text
            note = ('Render to verify current source and dependencies' if same_text else 'Older than the editor buffer')
            return self._adhoc[1], False, note
        return None

    def _refresh(self) -> None:
        target, row = self._target, self._row
        view, language = self.state.view, self.language
        job = self._pending[1] if self._pending else self._active
        busy_here = (target is not None and job is not None and job.generation == self._generation
                     and job.target_key == target.key and (job.view, job.language) == (view, language))
        clear_layout(self._chips)
        if target is not None:
            link = translation_link(self.app.project, target.id_slug)
            partner = partner_link(target, link)
            for icon, text, tone, tooltip in chips_for(target, row, view, language, link):
                jump = icon == "language" and partner is not None
                chip = Chip(text, tone, icon, pressable=jump)
                chip.setToolTip(tooltip)
                if jump:
                    chip.clicked.connect(lambda path=partner.path: self._show_partner(path))
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
        if target is None:
            self._page.show_message(self._message or "Select a slide in the list.", False)
        elif target.hidden or (row is not None and row.hidden):
            self._page.show_message(f"This slide is not typeset in the {VIEW_LABELS[view]} view.", False)
        else:
            found = self._image(target, background=self._background_validation)
            if found is None:
                self._page.show_message(
                    f"No preview for the {VIEW_LABELS[view]} view yet." if not busy_here else "Rendering…",
                    not busy_here)
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
            target.key, view, language, self._footer_timestamp()) and self._buffer() is not None \
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

    def _rebuild_menu(self) -> None:
        if self._menu is not None:
            self._menu.deleteLater()
        menu = PopoverMenu(self, min_width=260)
        has_buffer = self._target is not None and self._batch_cancel is None
        all_enabled = self.can_render_all
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
        pdf_available = self._last_pdf is not None or (self._target is not None and self._page.pixmap is not None)
        menu.add_item(OPEN_PDF, "Open PDF for this view", enabled=pdf_available and not self._busy)
        if self._batch_cancel is not None:
            menu.add_separator()
            menu.add_item(STOP, "Stop rendering all views")
        menu.triggered.connect(self._on_menu)
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
        """Open this view's PDF, rendering it lazily when its image was shared."""
        if self._last_pdf is not None:
            slide_preview.open_pdf(self._last_pdf)
            return
        target = self._target
        if target is None or self._busy or self._page.pixmap is None:
            return
        key = (target.key, self.state.view, self.language, self._footer_timestamp())
        adhoc_here = self._adhoc is not None and self._adhoc[0] == key
        scoped_adhoc = (adhoc_here and self._adhoc_spec is not None and
                        (self._adhoc_spec.options.mode != 'slide' or
                         self._adhoc_spec.options.overlay is not None))
        displayed_spec = self._displayed_spec
        if (displayed_spec is not None and (displayed_spec.target.key, displayed_spec.view,
                displayed_spec.language, displayed_spec.options.footer_timestamp) != key):
            displayed_spec = None
        adhoc_spec = self._adhoc_spec if scoped_adhoc else displayed_spec
        try:
            buffer = self._buffer() if adhoc_spec is None else None
            text = (adhoc_spec.revision.text if adhoc_spec is not None else self._adhoc_text) if scoped_adhoc else \
                   (displayed_spec.revision.text if displayed_spec is not None else
                    buffer[0] if buffer is not None else target.source_path.read_text(encoding='utf-8'))
            saved = adhoc_spec.options.saved if adhoc_spec is not None else buffer is None and not scoped_adhoc
        except OSError as exc:
            self._error = str(exc)
            self._refresh()
            return
        job = self._job(target, external=True, revision_text=text)
        job.request = self._renders.request(
            target, text, self.state.view, self.language, self._footer_timestamp(), self.app.log,
            saved=saved, spec=adhoc_spec, require_pdf=True)
        self._start(lambda: None, job)

    # -- rendering ---------------------------------------------------------------------

    def _footer_timestamp(self) -> bool:
        return self.state.footer_timestamp

    @property
    def _closed(self) -> bool:
        return self._lifetime.closed.is_set()

    def _dispose(self) -> None:
        self._lifetime.close()

    def _invalidate(self) -> None:
        self._generation += 1
        self._selection_ticket += 1
        if self._selection_pending is not None:
            self._selection_pending.cancel()
        self._selection_pending = self._selection_pending_key = None
        self._selection_result = self._selection_result_key = None
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
        if self._closed or self._active is not None or self._pending is None or self._debounce.isActive():
            return
        work, job = self._pending
        self._pending = None
        self._active = job
        self._lifetime.job = job
        Thread(target=self._run, args=(work, job), daemon=True).start()

    def _run(self, work: Callable[[], Path], job: _Job) -> None:
        with PreviewMetrics() as metrics:
            try:
                if job.request is not None:
                    job.pdf, job.png, job.images, _ = job.request.wait()
                else:
                    job.pdf = work()
                if job.request is None and not job.external and not self._closed and job.generation == self._generation:
                    job.png, job.images = slide_snapshot.prepare_preview(job.pdf, bool(job.snapshot_template))
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
        slide_preview.sweep_old_renders()   # renders older than 24 h; best effort, never raises

    _discard = staticmethod(_discard_job)

    def _accepts(self, job: _Job) -> bool:
        target = self._target
        if job.request is not None and job.request.cancelled():
            return False
        if (target is None or job.generation != self._generation or target.key != job.target_key
                or (self.state.view, self.language, self.state.footer_timestamp)
                != (job.view, job.language, job.timestamp)
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
            if job.error:   # a superseded render that failed still ends in the log, never silently
                self.app.log(f"*** Render failed: {job.error} ***")
        elif job.error:
            self._discard(job)
            self._error = job.error
            self.app.log(f"*** Render failed: {job.error} ***")
        else:
            if job.images and job.snapshot_template:
                try:
                    slide_snapshot.publish_preview(self.app.project, job.images, self._target.bare_id, job.snapshot_template)
                except Exception as exc:
                    self.app.log(f"    (preview snapshot not updated: {exc})")
            self._last_pdf = job.pdf
            if job.external:
                slide_preview.open_pdf(job.pdf)
            else:
                pixmap = QPixmap()
                if job.png is not None and pixmap.loadFromData(job.png):
                    try:
                        spec = job.request.spec if job.request is not None else PreviewRequest(
                            self._target, SourceRevision.capture(job.source, job.revision_text),
                            job.view, job.language, RenderOptions(job.timestamp, job.buffer_text is None))
                        cached = (job.request is not None and job.request.preview_result is not None
                                  and job.request.preview_result._artifact_owner is not None)
                        remember_transient(spec, job.png, job.pdf, cached=cached)
                        self._show_accepted_while_validating(spec, job.png)
                    except (OSError, ValueError):
                        pass
                    key = (job.target_key, job.view, job.language, job.timestamp)
                    if job.note:
                        self._adhoc = (key, pixmap, job.note)
                        self._adhoc_text = job.buffer_text
                        self._adhoc_spec = job.request.spec if job.request is not None else None
                    else:
                        self._adhoc = None
                        self._adhoc_spec = None
                        self._pixmaps[key] = (pixmap, job.mtime)
                        self._pixmaps.move_to_end(key)
                        while len(self._pixmaps) > 12:
                            self._pixmaps.popitem(last=False)
            self.rendered.emit()
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
                    mtime=_mtime(target.source_path), source=target.source_path,
                    timestamp=self._footer_timestamp(), **fields)

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

    def _render_saved(self, precheck: bool, *, debounce: bool = False, force: bool = False) -> None:
        target = self._target
        if target is None or target.hidden or self._batch_cancel is not None:
            return
        path = target.source_path
        if precheck and not render_check.confirm_render(
                self, self.app, latex_lint.check_slide_files(self.app.project, [path]), f"{path.name} (saved file)",
                show_in_editor=lambda issue: render_check.open_issue_in_editor(self.app, issue)):
            return
        view, language = self.state.view, self.language
        timestamp = self._footer_timestamp()
        text = path.read_text(encoding='utf-8')
        job = self._job(target, revision_text=text, snapshot_template=target.template
                        if view == 'instructor' and not target.is_frozen_alone else None)
        self._batch_status = ''
        job.request = self._renders.request(target, text, view, language, timestamp, self.app.log, saved=True, force=force)
        self._start(lambda: None, job, debounce=debounce)

    def render_after_save(self) -> None:
        """The slide was saved: render it again, unless its source has errors (then
        the page just stays older than the source, and Render asks)."""
        target = self._target
        if target is not None and not latex_lint.check_slide_files(self.app.project, [target.source_path]).errors:
            self._render_saved(precheck=False, debounce=True)
        elif target is not None:
            self._invalidate()
            self._refresh()

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
        timestamp = self._footer_timestamp()
        job = self._job(target, external=presenter, buffer_text=text, revision_text=text,
                        snapshot_template=target.template if view == 'instructor' and not presenter
                        and scope == 'slide' and overlay is None and not target.is_frozen_alone else None,
                        note="Rendered from the editor buffer, not the saved file")
        job.request = self._renders.request(target, body, view, language, timestamp, self.app.log,
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
                                       footer_timestamp=self._footer_timestamp(),
                                       occurrence_key=self.state.focused_occurrence)
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
        if progress.status == 'rendering':
            self._batch_status = f"Rendering {VIEW_LABELS[progress.view]} · {progress.index}/{progress.total}"
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

    def request_render(self, target, text, view, language, timestamp) -> RenderRequest:
        """GUI-thread entry for tools; publication uses the ordinary job acceptance checks."""
        if self._closed:
            raise RuntimeError('Preview pane closed')
        saved = target.source_path.read_text(encoding='utf-8') == text
        request = self._renders.request(target, text, view, language, timestamp, self.app.log, saved=saved)
        # An ordinary pane worker already delivers this exact build to the GUI.
        for job in (self._active, self._pending[1] if self._pending else None, self._remote.get(request)):
            if job is not None and job.request is request and job.generation == self._generation:
                return request
        job = _Job(target_key=target.key, source=target.source_path, mtime=_mtime(target.source_path),
                   view=view, language=language, timestamp=timestamp, generation=self._generation,
                   revision_text=text, buffer_text=None if saved else text,
                   note='' if saved else 'Rendered from the editor buffer, not the saved file',
                   snapshot_template=target.template if view == 'instructor' and not target.is_frozen_alone else None,
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
            job.pdf, job.png, job.images, _ = request.result
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
                    and (self.state.view, self.language, self._footer_timestamp()) ==
                    (spec.view, spec.language, options.footer_timestamp))
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
                                        spec.view, spec.language, options.footer_timestamp,
                                        result.artifact(), self._generation,
                                        cached=result._artifact_owner is not None)
        if options.saved:
            return 'superseded'
        if not matching or buffer is None:
            return 'cached'
        pixmap = QPixmap()
        if result.display_png is None or not pixmap.loadFromData(result.display_png):
            raise RuntimeError('The rendered preview image could not be read')
        key = (target.key, spec.view, spec.language, options.footer_timestamp)
        self._adhoc = (key, pixmap, 'Rendered from the editor buffer, not the saved file')
        self._adhoc_text = revision.text
        self._adhoc_spec = spec
        self._last_pdf = result.pdf
        remember_transient(spec, result.display_png, result.pdf,
                           cached=result._artifact_owner is not None)
        self._show_accepted_while_validating(spec, result.display_png)
        self._error = ''
        self._refresh()
        self.rendered.emit()
        self.rendered_target.emit(target.source_path)
        return 'displayed'

    def publish_refresh(self, target, text, revision, view, language, timestamp, artifact, generation,
                        *, cached=False) -> str:
        """GUI-thread publication of a saved snapshot refresh, without changing the focus."""
        if self._closed:
            return 'superseded'
        try:
            if _mtime(target.source_path) != revision or target.source_path.read_text(encoding='utf-8') != text:
                return 'superseded'
        except OSError:
            return 'superseded'
        matching = (self._target is not None and self._target.key == target.key
                    and (self.state.view, self.language, self.state.footer_timestamp) == (view, language, timestamp))
        # A changed buffer or a later pane render owns the visible page, even if disk is unchanged.
        if matching and (generation != self._generation or (self._buffer() is not None and self._buffer()[0] != text)):
            return 'superseded'
        pdf, png, images, _ = artifact
        pixmap = QPixmap()
        if png is None or not pixmap.loadFromData(png):
            raise RuntimeError('The rendered preview image could not be read')
        if view == 'instructor' and not target.is_frozen_alone:
            slide_snapshot.publish_preview(target.context, images, target.bare_id, target.template)
        key = (target.key, view, language, timestamp)
        self._pixmaps[key] = (pixmap, revision)
        try:
            remembered = PreviewRequest(target, SourceRevision.capture(target.source_path, text), view, language,
                                        RenderOptions(timestamp, saved=True))
            remember_transient(remembered, png, pdf, cached=cached)
            if matching:
                self._show_accepted_while_validating(remembered, png)
        except (OSError, ValueError):
            pass
        self._pixmaps.move_to_end(key)
        while len(self._pixmaps) > 12:
            self._pixmaps.popitem(last=False)
        if matching:
            self._adhoc = None
            self._adhoc_spec = None
            self._adhoc_text = None
            self._last_pdf = pdf
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
