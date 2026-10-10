"""The Preview view: the focused slide as a page, in the view (Instructor /
During course / After course) and language the top bar says.

Without compiling anything it shows the slide's cached snapshot
(slide_snapshot.py; the instructor view only) or what this session rendered.
"Render" compiles the saved slide in the view and language, and the Render
menu renders the editor's buffer instead (Ctrl+R: the whole slide, or the
selection as a frame or as a cropped element, optionally one reveal step), a
presenter PDF, or a transcript. Rendering runs on a worker thread; what a
render depends on is in preview_target.py. Every render is preceded by the
quick static syntax check (latex_lint through render_check), which asks
before rendering a slide that has errors.

Chips say what the page is not showing at first sight: a version the deck
pins, a language, a missing translation, a view that does not typeset the
slide. They come from the deck outline and the slide's file name, nothing
is guessed.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from ... import latex_lint, preview_target, slide_preview, slide_snapshot, slide_source, slide_versioning
from ...deck_outline import SlideRow
from ...preview_target import PreviewTarget
from ...slide_language import TranslationLink, translation_link
from ..dialogs.transcript_preview import show_transcript_preview
from ..kit import kit_qss as q
from ..kit.tokens import Tokens
from ..kit.widgets import Button, Chip, PopoverMenu, SplitButton, Surface
from . import render_check
from .menus import VIEW_LABELS
from .state import WorkspaceState

PAGE_ASPECT = 16 / 9
SCOPES = (("slide", "Whole slide"), ("region", "Selection as frame"), ("element", "Selection as element"))
# Menu keys.
BUFFER, OVERLAY, PRESENTER, TRANSCRIPT, OPEN_PDF = "buffer", "overlay", "presenter", "transcript", "open_pdf"


def short_view(view: str) -> str:
    return VIEW_LABELS[view].replace(" course", "")


def chips_for(target: PreviewTarget, row: Optional[SlideRow], view: str, language: str,
              link: Optional[TranslationLink] = None) -> list[tuple]:
    """(icon, text, tone, tooltip) of the chips above the page. `row` is the
    slide's row in the open deck, None for a file shown alone; `link` its translation
    partner, if it has one."""
    chips = []
    if row is None:
        if target.version:
            chips.append(("lock", f"Frozen {slide_versioning.version_label(target.version)}", "muted",
                          "A past version of the slide, shown on its own."))
    else:
        call = row.call
        if call.version:
            chips.append(("push_pin", f"Deck stays on {slide_versioning.version_label(call.version)}", "info",
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
    badge = row.badge.strip("[]") if row is not None else ""
    if badge:
        chips.append(("language", badge, "neutral", "The slide's language, and its translation if it has one."))
    return chips


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


class _Page(QWidget):
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
        painter.setBrush(QColor("#ffffff") if self.pixmap is not None else QColor(tokens.surface))
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
    _finished = Signal(object)    # a _Job, from the worker thread

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
        self._title = ""
        self._message = ""
        self._busy = False
        self._error = ""
        self._last_pdf: Optional[Path] = None
        self._scope = "slide"
        self._overlay = 0
        # Renders of the saved slide this session: (target.key, view, language) -> (pixmap, source mtime).
        self._pixmaps: dict[tuple, tuple[QPixmap, int]] = {}
        # The latest render of the editor buffer: (target.key, view, language) -> (pixmap, note).
        self._adhoc: Optional[tuple[tuple, QPixmap, str]] = None
        self._finished.connect(self._on_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(8)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        layout.addLayout(self._chips)
        self._page = _Page(lambda: self.app.theme.tokens)
        self._page.render_button.clicked.connect(self.render_now)
        layout.addWidget(self._page, 1)

        status = QHBoxLayout()
        status.setSpacing(8)
        self._status_chip = Chip("", "muted")
        status.addWidget(self._status_chip)
        self._status_button = Button("Render now", "secondary", compact=True)
        self._status_button.clicked.connect(self.render_now)
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

    def show_slide(self, target: Optional[PreviewTarget], row: Optional[SlideRow], title: str, message: str) -> None:
        """Show `target` (None: just `message`). `row` is its row in the open deck, if it has one."""
        if target is None or self._target is None or target.key != self._target.key:
            self._error = ""
            self._adhoc = None
        self._target, self._row, self._title, self._message = target, row, title, message
        self._refresh()

    def _on_context_changed(self, _value: str) -> None:
        self._error = ""      # a failure belongs to the view and language it happened in
        self._refresh()

    def _image(self, target: PreviewTarget) -> Optional[tuple[QPixmap, bool, str]]:
        """(the page, whether it is as new as the slide's source, a note) -- the latest
        render of the buffer, else this session's render of the saved file, else the
        cached snapshot (instructor view only)."""
        view, language = self.state.view, self.state.language
        key = (target.key, view, language)
        if self._adhoc is not None and self._adhoc[0] == key:
            return self._adhoc[1], True, self._adhoc[2]
        mtime = _mtime(target.source_path)
        rendered = self._pixmaps.get(key)
        if rendered is not None and rendered[1] == mtime:
            return rendered[0], True, ""
        cached = preview_target.cached_image(target) if view == "instructor" else None
        if cached is not None and (cached[1] or rendered is None):
            pixmap = QPixmap(str(cached[0]))
            if not pixmap.isNull():
                return pixmap, cached[1], ""
        return (rendered[0], False, "") if rendered is not None else None

    def _refresh(self) -> None:
        target, row = self._target, self._row
        view, language = self.state.view, self.state.language
        while (item := self._chips.takeAt(0)) is not None:
            if item.widget() is not None:
                item.widget().setParent(None)
        if target is not None:
            link = translation_link(row.call.id_slug) if row is not None else None
            for icon, text, tone, tooltip in chips_for(target, row, view, language, link):
                chip = Chip(text, tone, icon)
                chip.setToolTip(tooltip)
                self._chips.addWidget(chip)
        self._chips.addStretch(1)

        self._id.setText(target.bare_id if target else "")
        self._name.setText(self._title if target else "")
        self._render.setVisible(target is not None)
        self._render.setEnabled(target is not None and not self._busy)
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
                    f"No preview for the {VIEW_LABELS[view]} view yet." if not self._busy else "Rendering…",
                    not self._busy)
            else:
                self._page.show_image(found[0])
                if found[2]:
                    status, tone, icon = found[2], "info", "edit_note"
                elif not found[1]:
                    status, tone, icon, can_render = "Older than the slide's source", "warning", "history", True
        if self._busy:
            status, tone, icon, can_render = "Rendering…", "info", "autorenew", False
        elif self._error:
            status, tone, icon, can_render = "Render failed", "error", "error_outline", target is not None
        self._status_chip.setVisible(bool(status))
        self._status_chip.set_text(status)
        self._status_chip.set_tone(tone)
        self._status_button.setVisible(can_render)
        self._error_label.setText(self._error)
        self._error_label.setVisible(bool(self._error))

    def _rebuild_menu(self) -> None:
        if self._menu is not None:
            self._menu.deleteLater()
        menu = PopoverMenu(self, min_width=260)
        has_buffer = self._target is not None
        menu.add_header("Editor buffer, as it is now")
        menu.add_item(BUFFER, "Render the buffer", meta="Ctrl+R", enabled=has_buffer and not self._busy)
        for scope, label in SCOPES:
            menu.add_item(f"scope:{scope}", label, icon="check" if scope == self._scope else "")
        menu.add_item(OVERLAY, f"Reveal step: {self._overlay or 'all'}…", enabled=self._scope != "element")
        menu.add_separator()
        menu.add_item(PRESENTER, "Presenter PDF", meta="opens in the viewer", enabled=has_buffer and not self._busy)
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

    def _footer_timestamp(self) -> bool:
        return self.state.footer_timestamp

    def _start(self, work: Callable[[], Path], job: _Job) -> None:
        self._busy, self._error = True, ""
        self._refresh()
        threading.Thread(target=self._run, args=(work, job), daemon=True).start()

    def _run(self, work: Callable[[], Path], job: _Job) -> None:
        try:
            job.pdf = work()
            job.png = slide_snapshot.page_png(job.pdf)
        except Exception as exc:  # noqa: BLE001 -- shown as the error; the render must always end
            job.error = str(exc) or type(exc).__name__
        self._finished.emit(job)

    def _on_finished(self, job: _Job) -> None:
        self._busy = False
        if job.error:
            self._error = job.error
            self.app.log(f"*** Render failed: {job.error} ***")
        else:
            self._last_pdf = job.pdf
            if job.external:
                slide_preview.open_pdf(job.pdf)
            else:
                pixmap = QPixmap()
                if job.png is not None and pixmap.loadFromData(job.png):
                    key = (job.target_key, job.view, job.language)
                    if job.note:
                        self._adhoc = (key, pixmap, job.note)
                    else:
                        self._adhoc = None
                        self._pixmaps[key] = (pixmap, job.mtime)
            self.rendered.emit()
        self._refresh()

    def _job(self, target: PreviewTarget, **fields) -> _Job:
        return _Job(target_key=target.key, view=self.state.view, language=self.state.language,
                    mtime=_mtime(target.source_path), **fields)

    def render_now(self) -> None:
        """Compile the saved slide in the view and language being edited."""
        self._render_saved(precheck=True)

    def _render_saved(self, precheck: bool) -> None:
        target = self._target
        if target is None or self._busy:
            return
        path = target.source_path
        if precheck and not render_check.confirm_render(
                self, self.app, latex_lint.check_slide_files([path]), f"{path.name} (saved file)",
                show_in_editor=lambda issue: render_check.open_issue_in_editor(self.app, issue)):
            return
        view, language = self.state.view, self.state.language
        self._start(lambda: preview_target.render(
            target, view, language, footer_timestamp=self._footer_timestamp(), log=self.app.signals.log.emit),
            self._job(target))

    def render_after_save(self) -> None:
        """The slide was saved: render it again, unless its source has errors (then
        the page just stays older than the source, and Render asks)."""
        target = self._target
        if target is not None and not latex_lint.check_slide_files([target.source_path]).errors:
            self._render_saved(precheck=False)

    def render_buffer(self, presenter: bool = False) -> None:
        """Compile the editor's buffer, saved or not, per the scope and reveal step chosen."""
        target = self._target
        if target is None or self._busy:
            return
        text, selection = self._buffer() or (slide_source.read_slide_source(target.source_path)[0], "")
        scope = "slide" if presenter else self._scope
        body = text if scope == "slide" else selection
        if not body.strip():
            QMessageBox.information(self, "Render the buffer", "Select some LaTeX to render first.")
            return
        path = target.source_path
        if not render_check.confirm_render(
                self, self.app, latex_lint.check_buffer(body, path.name, path), f"{path.name} (editor buffer)",
                show_in_editor=lambda issue: self.app.open_slide_editor(path, line=issue.line)):
            return
        view, language = self.state.view, self.state.language
        overlay = None if scope == "element" else (self._overlay or None)
        self._start(lambda: preview_target.render_text(
            target, body, view, language, footer_timestamp=self._footer_timestamp(), log=self.app.signals.log.emit,
            presenter=presenter, mode=scope, overlay=overlay),
            self._job(target, external=presenter, note="Rendered from the editor buffer, not the saved file"))

    def render_transcript(self) -> None:
        """A one-slide transcript preview of the buffer (nothing is written to disk)."""
        target = self._target
        if target is None:
            return
        buffer = self._buffer()
        text = buffer[0] if buffer else slide_source.read_slide_source(target.source_path)[0]
        show_transcript_preview(self.app, text, target.bare_id, target.id_slug, self.state.view, self.state.language)


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
