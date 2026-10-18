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
from threading import Thread
import shutil
import time
import weakref
from dataclasses import dataclass, replace
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from ... import (deck_context, deck_editor, latex_lint, preview_target, reveal_steps, slide_preview, slide_snapshot, slide_source,
                 slide_versioning)
from ...ai.claude_tasks import LANGUAGE_NAMES
from ...ai.tools.slidemage import slide_target
from ...deck_outline import SlideRow
from ...preview_target import PreviewTarget
from ...preview_requests import RenderRequest, RenderService
from ...preview_metrics import PreviewMetrics
from ...slide_language import TRANSLATION_LANGUAGES, TranslationLink, own_language, translation_link
from ...step_renders import BACKGROUND, FOREGROUND, StepRenderQueue
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit import kit_qss as q
from ..kit.tokens import Tokens
from ..kit.widgets import Button, Chip, PopoverMenu, SplitButton, Surface, clear_layout
from . import render_check
from .menus import VIEW_LABELS
from .reveal_bar import RevealBar, RowSpec
from .state import VIEWS, WorkspaceState

PAGE_ASPECT = 16 / 9
PROBE_MS = 1500          # idle time before the step bar counts a slide's steps in the background
STEP_CACHE = 12          # page lists kept (each is a slide's steps as PNGs)
NEIGHBOURS = 4           # slides around the one on show whose steps are counted while the pane is idle
SCOPES = (("slide", "Whole slide"), ("region", "Selection as frame"), ("element", "Selection as element"))
# Menu keys.
BUFFER, OVERLAY, PRESENTER, TRANSCRIPT, OPEN_PDF = "buffer", "overlay", "presenter", "transcript", "open_pdf"


def short_view(view: str) -> str:
    return VIEW_LABELS[view].replace(" course", "")


def partner_link(target: PreviewTarget, link: Optional[TranslationLink]) -> Optional[TranslationLink]:
    """`link` if it leads to the slide's file in the other language, else None."""
    return link if link is not None and link.language not in (None, own_language(target.id_slug)) else None


def chips_for(target: PreviewTarget, row: Optional[SlideRow], view: str, language: str,
              link: Optional[TranslationLink] = None, context_mode: Optional[str] = None,
              rendered: bool = False) -> list[tuple]:
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
    if target.needs_context:
        chips.append(context_chip(target, view, context_mode, rendered))
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


def render_context(window, path: Path) -> Optional[tuple[PreviewTarget, str, str]]:
    """(target, view, language) for rendering the slide file `path` as the top bar says: in its own
    language when that is one of EN and DE, as the open deck calls it. None when `path` is no slide file."""
    state = window.state
    language = own_language(path.name)
    language = language if language in TRANSLATION_LANGUAGES else state.language
    target = slide_target(window.project, state.deck, path, state.view, language)
    return None if target is None else (target, state.view, language)


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
    snapshot_template: Optional[str] = None
    images: tuple = ()
    requested: float = 0
    metrics: Optional[dict] = None
    request: Optional[RenderRequest] = None
    revision_text: Optional[str] = None
    remote: bool = False
    steps_ok: bool = True           # a whole-slide render: the step bar can use its PDF


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
            owner._renders.close()
            owner._steps.close()
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
    partner_requested = Signal(object)   # the language chip: the Path of the slide's file in the other language
    compile_requested = Signal(str)      # the deck-context chip: compile the deck in this view
    _finished = Signal(object)    # a _Job, from the worker thread
    _steps_ready = Signal(object, object, str)   # (key, PNG pages, error), from the step queue's thread

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
        self._generation = 0
        self._active: Optional[_Job] = None
        self._pending = None
        self._lifetime = _Lifetime(self)
        self._renders = RenderService()
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
        self.destroyed.connect(self._lifetime.close)
        self._error = ""
        self._last_pdf: Optional[Path] = None
        self._scope = "slide"
        self._overlay = 0
        # Renders this session: (target.key, view, language) -> image.
        self._pixmaps: OrderedDict[tuple, tuple[QPixmap, int]] = OrderedDict()
        # The latest render of the editor buffer: (target.key, view, language) -> (pixmap, note).
        self._adhoc: Optional[tuple[tuple, QPixmap, str]] = None
        self._adhoc_text: Optional[str] = None
        self._adhoc_full = False       # the buffer render is a whole slide (the step bar may use it)
        # The step bar: page lists of all-steps renders, rendered one at a time in the background.
        self._steps = StepRenderQueue(self._steps_busy, self._steps_done)
        self._step_pages: OrderedDict[tuple, list[bytes]] = OrderedDict()
        self._step_choice: dict[Path, int] = {}      # the step picked per slide; none: the last one
        self._step_pixmap: Optional[tuple[tuple, int, QPixmap]] = None
        self._scans: dict[tuple, reveal_steps.SlideScan] = {}
        self._step_failed: set[tuple] = set()      # page lists that did not render: not asked for again
        self._context_modes: dict[tuple, Optional[str]] = {}   # (target key, view, language) -> deck_context mode
        # An edit of the open deck, (failed title, summary, change(path, text), cleanup) -> done: the slide list's
        # `edit`, which the window hands over. Without it the ticks of the step bar are not editable.
        self.edit_deck: Optional[Callable[..., bool]] = None
        # The slides around the focused one, [(target, row)]: the centre column knows the deck's order.
        self.neighbours: Callable[[], list] = lambda: []
        self._finished.connect(self._on_finished)
        self._steps_ready.connect(self._on_steps_ready)
        self._probe = QTimer(self)
        self._probe.setSingleShot(True)
        self._probe.setInterval(PROBE_MS)
        self._probe.timeout.connect(self._probe_steps)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(8)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        layout.addLayout(self._chips)
        self._page = PageView(lambda: self.app.theme.tokens)
        self._page.render_button.clicked.connect(self.render_now)
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
        status.setSpacing(8)
        self._status_chip = Chip("", "muted")
        status.addWidget(self._status_chip)
        self._status_button = Button("Render now", "secondary", compact=True)
        self._status_button.clicked.connect(self._status_clicked)
        self._status_draft = False   # the button renders the unsaved buffer, not the saved file
        status.addWidget(self._status_button)
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
        if changed:
            self._error = ""
            self._adhoc = None
            self._steps.drop_background()
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
        self._error = ""      # a failure belongs to the view and language it happened in
        self._refresh()

    def buffer_changed(self, path: Path) -> None:
        """Refresh a buffer preview's age after typing pauses, without compiling."""
        if self._target is not None and path == self._target.source_path:
            self._buffer_notice.start()

    def _image(self, target: PreviewTarget) -> Optional[tuple[QPixmap, bool, str]]:
        """(the page, whether it is as new as the slide's source, a note) -- the latest
        render of the buffer, else this session's render of the saved file, else the
        cached snapshot (instructor view only)."""
        view, language = self.state.view, self.language
        key = (target.key, view, language)
        if self._adhoc is not None and self._adhoc[0] == key:
            buffer = self._buffer()
            fresh = buffer is None or buffer[0] == self._adhoc_text
            return self._adhoc[1], fresh, self._adhoc[2] if fresh else "Older than the editor buffer"
        mtime = _mtime(target.source_path)
        rendered = self._pixmaps.get(key)
        if rendered is not None:
            self._pixmaps.move_to_end(key)
        if rendered is not None and rendered[1] == mtime:
            return rendered[0], True, ""
        cached = preview_target.cached_image(target) if view == "instructor" else None
        if cached is not None and (cached[1] or rendered is None):
            pixmap = QPixmap(str(cached[0]))
            if not pixmap.isNull():
                return pixmap, False, "Cached preview; render to verify current settings"
        return (rendered[0], False, "") if rendered is not None else None

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
            mode_key = (target.key, view, language)
            for icon, text, tone, tooltip in chips_for(
                    target, row, view, language, link, self._context_modes.get(mode_key),
                    mode_key in self._context_modes):
                jump = icon == "language" and partner is not None
                compile_deck = icon == "warning" and target.needs_context and row is not None
                chip = Chip(text, tone, icon, pressable=jump or compile_deck)
                chip.setToolTip(tooltip)
                if jump:
                    chip.clicked.connect(lambda path=partner.path: self._show_partner(path))
                elif compile_deck:
                    chip.clicked.connect(lambda v=view: self.compile_requested.emit(v))
                self._chips.addWidget(chip)
        self._chips.addStretch(1)

        self._id.setText(target.bare_id if target else "")
        self._name.setText(self._title if target else "")
        self._render.setVisible(target is not None)
        self._render.setEnabled(target is not None)
        self._render.set_text(f"Render · {short_view(view)} · {language}")
        self._rebuild_menu()

        status, tone, icon, can_render = "", "muted", "", False
        if target is None:
            self._page.show_message(self._message or "Select a slide in the list.", False)
        elif row is not None and row.hidden:
            self._page.show_message(f"This slide is not typeset in the {VIEW_LABELS[view]} view.", False)
        else:
            found = self._image(target)
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
        shown = target is not None and not (row is not None and row.hidden)
        draft = shown and not busy_here and self._is_draft(target)
        current = shown and self._adhoc is not None and self._adhoc[0] == (
            target.key, view, language) and self._buffer() is not None \
            and self._buffer()[0] == self._adhoc_text
        self._status_draft = bool(draft and not current)
        if self._status_draft:
            if not status:
                status, tone, icon = "Unsaved edits are not in this preview", "warning", "edit_note"
            can_render = True
        self._status_button.setText("Render draft · Ctrl+Enter" if self._status_draft else "Render now")
        self._status_chip.setVisible(bool(status))
        self._status_chip.set_text(status)
        self._status_chip.set_tone(tone)
        self._status_button.setVisible(can_render)
        self._error_label.setText(self._error)
        self._error_label.setVisible(bool(self._error))
        self._update_reveal(target, row, shown, shown and self._image(target) is not None)

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
        """What a page list depends on. `stamp`: the source's mtime (a saved render) or the buffer's text."""
        identity = target.key[1:3] + target.key[5:]       # not the macro, the versions or the steps of the call
        return ("draft" if draft else "saved", str(target.source_path), identity, view, language,
                hash(stamp) if draft else stamp)

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
            return key, text, True, self._scan_of(target.source_path, text, hash(text))
        mtime = _mtime(target.source_path)
        return (self._steps_key(target, view, language, False, mtime), None, False,
                self._scan_of(target.source_path, None, mtime))

    def _after_render(self, job: _Job) -> None:
        """A render of the slide was accepted: its pages are the step list when it kept every step."""
        target = self._target
        if target is None or not job.steps_ok:
            return
        draft = bool(job.note)
        text = job.buffer_text if draft else job.revision_text
        key = self._steps_key(target, job.view, job.language, draft,
                              text if draft else job.mtime)
        if key in self._step_pages or self._steps.pending(key):
            return
        scan = self._scan_of(target.source_path, text, hash(text) if draft else job.mtime)
        adoptable = (job.pdf is not None and job.request is not None and target.macro not in ("slidestep",)
                     and scan.own_frame_spec is None and not scan.frame_breaks
                     and not (scan.final_flag and job.view != reveal_steps.INSTRUCTOR))
        if adoptable:
            pdf = job.pdf
            self._steps.submit(key, FOREGROUND, lambda _cancel: pdf)
        else:
            self._request_steps(target, key, text, draft, FOREGROUND)

    def _request_steps(self, target: PreviewTarget, key: tuple, text: Optional[str], draft: bool,
                       priority: int) -> None:
        """Queue the all-steps render for `key` (kind, path, target key, view, language, stamp)."""
        view, language = key[3], key[4]
        if text is None:
            try:
                text = target.source_path.read_text(encoding='utf-8')
            except OSError:
                return
        service, log = self._renders, self.app.log

        def build(cancel):
            request = service.request(target, text, view, language, log, saved=not draft, all_steps=True)
            return request.wait(cancel)[0]

        self._steps.submit(key, priority, build)

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
            other_key = self._steps_key(other, view, language, False, _mtime(other.source_path))
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
            saved = self._step_pages.get(("saved",) + key[1:6] + (_mtime(self._target.source_path),)) \
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
        pages = self._step_pages.get(key)
        if pages is None:
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
                pixmap = QPixmap()
                if pixmap.loadFromData(pages[step - 1]):
                    self._step_pixmap = (key, step, pixmap)
                else:
                    self._step_pixmap = None
            if self._step_pixmap is not None and self._step_pixmap[:2] == (key, step):
                self._page.show_image(self._step_pixmap[2])

    def _rebuild_menu(self) -> None:
        if self._menu is not None:
            self._menu.deleteLater()
        menu = PopoverMenu(self, min_width=260)
        has_buffer = self._target is not None
        menu.add_header("Editor buffer, as it is now")
        menu.add_item(BUFFER, "Render the buffer", meta="Ctrl+Enter", enabled=has_buffer)
        for scope, label in SCOPES:
            menu.add_item(f"scope:{scope}", label, icon="check" if scope == self._scope else "")
        menu.add_item(OVERLAY, f"Reveal step: {self._overlay or 'all'}…", enabled=self._scope != "element")
        menu.add_separator()
        menu.add_item(PRESENTER, "Presenter PDF", meta="opens in the viewer", enabled=has_buffer)
        menu.add_item(TRANSCRIPT, "Render transcript", enabled=has_buffer)
        menu.add_item(OPEN_PDF, "Open the last PDF", enabled=self._last_pdf is not None)
        menu.triggered.connect(self._on_menu)
        self._menu = menu
        self._render.set_menu(menu)

    def _on_menu(self, key: str) -> None:
        if key == BUFFER:
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
            slide_preview.open_pdf(self._last_pdf)

    # -- rendering ---------------------------------------------------------------------

    @property
    def _closed(self) -> bool:
        return self._lifetime.closed.is_set()

    def _dispose(self) -> None:
        self._lifetime.close()

    def _invalidate(self) -> None:
        self._generation += 1
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
            if self._target is not None and self._target.needs_context and not job.external:
                self._context_modes[(job.target_key, job.view, job.language)] = deck_context.mode_of(job.pdf)
                while len(self._context_modes) > 64:
                    self._context_modes.pop(next(iter(self._context_modes)))
            if job.external:
                slide_preview.open_pdf(job.pdf)
            else:
                pixmap = QPixmap()
                if job.png is not None and pixmap.loadFromData(job.png):
                    key = (job.target_key, job.view, job.language)
                    if job.note:
                        self._adhoc = (key, pixmap, job.note)
                        self._adhoc_text = job.buffer_text
                        self._adhoc_full = job.steps_ok
                    else:
                        self._adhoc = None
                        self._pixmaps[key] = (pixmap, job.mtime)
                        self._pixmaps.move_to_end(key)
                        while len(self._pixmaps) > 12:
                            self._pixmaps.popitem(last=False)
            self.rendered.emit()
            if not job.external:
                self._after_render(job)
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

    def _render_saved(self, precheck: bool, *, debounce: bool = False) -> None:
        target = self._target
        if target is None:
            return
        path = target.source_path
        if precheck and not render_check.confirm_render(
                self, self.app, latex_lint.check_slide_files(self.app.project, [path]), f"{path.name} (saved file)",
                show_in_editor=lambda issue: render_check.open_issue_in_editor(self.app, issue)):
            return
        view, language = self.state.view, self.language
        text = path.read_text(encoding='utf-8')
        job = self._job(target, revision_text=text, snapshot_template=target.template
                        if view == 'instructor' and not target.is_frozen_alone else None)
        job.request = self._renders.request(target, text, view, language, self.app.log, saved=True)
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
        if target is None:
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
                        snapshot_template=target.template if view == 'instructor' and not presenter
                        and scope == 'slide' and overlay is None and not target.is_frozen_alone else None,
                        note="Rendered from the editor buffer, not the saved file",
                        steps_ok=scope == "slide" and overlay is None and not presenter)
        job.request = self._renders.request(target, body, view, language, self.app.log,
                                            presenter=presenter, mode=scope, overlay=overlay)
        self._start(lambda: None, job)

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
