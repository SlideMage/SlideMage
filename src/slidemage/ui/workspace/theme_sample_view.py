# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sample slides above the theme form (docs/plans/theme-editor.md, section 3.3, stage C1c): the theme sample deck
rendered with the theme as it is in the editor, in the colour mode picked here, one page at a time.

A render starts a pause after the last change of the buffer (from the form or from typing), runs in a thread, and a
change during a render stops it and starts again once it has ended. Nothing renders while the panel is hidden; it
catches up when it is shown."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout

from ... import compiler, theme_fields, theme_measures, theme_probe, theme_sample
from ...theme_file import ThemeFile
from ...theme_form_model import parse_modes_header
from ..kit.tokens import SPACE
from ..kit.widgets import Button, Surface, caption, text_label

RENDER_DELAY_MS = 1200      # after the last change of the buffer
RENDER_DPI = 110


def pdf_pages(pdf: Path, dpi: int = RENDER_DPI) -> list[QImage]:
    """Every page of `pdf` as an image."""
    import pymupdf

    images = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            images.append(QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy())
    return images


class ThemeSampleView(Surface):
    """`render(project, text, key, mode, cancel=...)` makes the PDF (theme_sample.render; tests pass their own)."""

    rendered = Signal(object)       # theme_sample.SampleResult, from the render thread
    probed = Signal(object, object)     # (the probe's key, theme_probe.UsageMap or None), from the probe thread
    geometry_changed = Signal()         # a render brought the page's geometry (theme_sample.read_geometry)

    def __init__(self, editor, key: str, project, render: Optional[Callable] = None,
                 read_usage: Optional[Callable] = None) -> None:
        super().__init__()
        self.editor = editor
        self.key = key
        self.project = project
        self._render = render or theme_sample.render
        self._images: list[QImage] = []
        self._page = 2                          # the title bar, lists and footnotes: the page most fields change
        self._cancel: Optional[compiler.CancelToken] = None
        self._again = False
        self._stale = True
        self._error = ""
        self._external_mode = False
        self.geometry: dict = {}        # of the last render: the hooks' lengths and the page's size, in bp
        self._measure: Optional[tuple[str, Optional[float]]] = None     # (key, value in bp or None) of a layout field
        # Where a colour is used (theme_probe): the focused field's (kind, name, mode), the maps by (kind, mode, text).
        self._read_usage = read_usage or theme_probe.usage_map
        self._usage: Optional[tuple[str, str, str]] = None
        self._maps: dict[tuple[str, str, str], Optional[theme_probe.UsageMap]] = {}
        self._probing: set[tuple[str, str, str]] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.lg, SPACE.md, SPACE.lg, SPACE.sm)
        layout.setSpacing(SPACE.xs)
        head = QHBoxLayout()
        head.addWidget(text_label("Sample slides", "heading"))
        head.addStretch(1)
        self.mode_combo = QComboBox()
        self.mode_combo.setToolTip("The colour mode the sample slides are rendered in")
        self.mode_combo.activated.connect(lambda _i: self.render_soon(0))
        head.addWidget(self.mode_combo)
        self.previous = Button("‹", "ghost", compact=True)
        self.previous.setToolTip("Previous page")
        self.previous.clicked.connect(lambda: self.show_page(self._page - 1))
        self.next = Button("›", "ghost", compact=True)
        self.next.setToolTip("Next page")
        self.next.clicked.connect(lambda: self.show_page(self._page + 1))
        head.addWidget(self.previous)
        head.addWidget(self.next)
        layout.addLayout(head)
        self.page_label = caption("")
        layout.addWidget(self.page_label)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(120)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.image, 1)
        # One small picture per page: a click shows it; a dot under the pages that use the focused colour.
        self.thumbs = QHBoxLayout()
        self.thumbs.setSpacing(SPACE.sm)
        self._thumb_buttons: list[QToolButton] = []
        layout.addLayout(self.thumbs)
        self.usage_label = caption("")
        self.usage_label.hide()
        layout.addWidget(self.usage_label)
        self.status = caption("")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RENDER_DELAY_MS)
        self._timer.timeout.connect(self.start)
        editor.text_changed.connect(self._on_text_changed)
        self.rendered.connect(self._on_rendered)
        self.probed.connect(self._on_probed)
        self._update_modes()
        self._show()

    # --- rendering ---------------------------------------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData() or ""

    def _on_text_changed(self) -> None:
        self._update_modes()
        self._maps.clear()          # a probe of the old text says nothing about the new one
        self.render_soon()

    def render_soon(self, delay: Optional[int] = None) -> None:
        self._stale = True
        self._timer.start(RENDER_DELAY_MS if delay is None else delay)

    def start(self) -> None:
        """Render now (or once the running render has stopped); nothing while the panel is not on show."""
        if self.project is None or not self.isVisible():
            return
        if self._cancel is not None:
            self._again = True
            self._cancel.request_stop(wait=False)
            return
        self._stale = False
        self._cancel = cancel = compiler.CancelToken()
        text, mode = self.editor.text(), self.mode
        self.status.setText("Rendering the sample slides…")

        def work() -> None:
            try:
                result = self._render(self.project, text, self.key, mode, cancel=cancel)
            except Exception as exc:        # a failed render must not end the thread silently
                result = theme_sample.SampleResult(None, f"The sample slides could not be rendered: {exc}", mode)
            self.rendered.emit(result)

        threading.Thread(target=work, daemon=True, name="theme-sample").start()

    def _on_rendered(self, result) -> None:
        self._cancel = None
        if self._again:
            self._again = False
            self.start()
            return
        if result.pdf is not None:
            if getattr(result, "geometry", None):
                self.geometry = dict(result.geometry)
                self.geometry_changed.emit()
            try:
                self._images = pdf_pages(result.pdf)
                self._error = ""
            except Exception as exc:
                self._error = f"The sample slides could not be read: {exc}"
        elif result.log:
            self._error = result.log
        self._show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.render_soon(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._show_image()

    # --- where a colour is used ------------------------------------------------------------------------------------

    def show_usage(self, kind: str, name: str, mode: str) -> None:
        """A colour field has the focus: dim the slides but where `name` (a role id or a palette colour) is used, in its
        column's mode `mode`, on a page that uses it."""
        if kind not in theme_probe.KINDS:
            return
        self._usage = (kind, name, mode)
        index = self.mode_combo.findData(mode)
        if index >= 0 and index != self.mode_combo.currentIndex():
            self.mode_combo.setCurrentIndex(index)
            self.render_soon(0)
        self._probe(kind, mode)
        self._jump_to_usage()
        self._show()

    def show_measure(self, key: str, value_bp: Optional[float]) -> None:
        """A layout field has the focus: mark what it sets (theme_measures.marks), at `value_bp` (None: as rendered),
        on a slide with the ordinary title bar and footer."""
        self._measure = (key, value_bp)
        if self._page in (1, 6, 7) and len(self._images) >= 2:     # the title, standout and quote frames have neither
            self._page = 2
        self._show()

    def clear_measure(self) -> None:
        self._measure = None
        self._show()

    def _paint_marks(self, image: QImage) -> QImage:
        """`image` with the focused layout field's marks drawn over it (never into the render)."""
        if self._measure is None or theme_sample.PAGE_WIDTH not in self.geometry:
            return image
        found = theme_measures.marks(self._measure[0], self._measure[1], self.geometry)
        if not found:
            return image
        result = image.convertToFormat(QImage.Format.Format_ARGB32)
        scale = result.width() / self.geometry[theme_sample.PAGE_WIDTH]
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(max(11, int(result.height() / 32)))
        font.setBold(True)
        painter.setFont(font)
        strong, thin = QColor("#2563eb"), QColor(37, 99, 235, 140)
        for mark in found:
            pen = QPen(strong if mark.focus else thin, 3 if mark.focus else 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            at = mark.at * scale
            if mark.kind == "h":
                painter.drawLine(0, int(at), result.width(), int(at))
                if mark.arrow:
                    solid = QPen(strong, 2)
                    painter.setPen(solid)
                    x = int(result.width() * 0.58)
                    painter.drawLine(x, 0, x, int(at))
                    painter.drawLine(x - 5, int(at) - 7, x, int(at))
                    painter.drawLine(x + 5, int(at) - 7, x, int(at))
                self._label(painter, mark, int(result.width() * 0.58) + 8, int(at) - 6, result)
            elif mark.kind == "v":
                painter.drawLine(int(at), 0, int(at), result.height())
                self._label(painter, mark, int(at) + 6, int(result.height() * 0.5), result)
            else:
                painter.drawRect(1, int(at), result.width() - 2, int(mark.size * scale) - 1)
                self._label(painter, mark, 8, int(at) - 6, result)
        painter.end()
        return result

    @staticmethod
    def _label(painter: QPainter, mark, x: int, y: int, image: QImage) -> None:
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(mark.label) + 10
        x = min(max(x, 2), image.width() - width - 2)
        y = min(max(y, metrics.height() + 2), image.height() - 2)
        box = QRect(x, y - metrics.height(), width, metrics.height() + 2)
        painter.fillRect(box, QColor("#2563eb") if mark.focus else QColor(37, 99, 235, 170))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, mark.label)

    def clear_usage(self) -> None:
        self._usage = None
        self._show()

    def _map(self):
        if self._usage is None:
            return None
        kind, _name, mode = self._usage
        return self._maps.get((kind, mode, self.editor.text()))

    def _probe(self, kind: str, mode: str) -> None:
        """Make the usage map of `kind` in `mode` for the current text, unless it is there or under way."""
        text = self.editor.text()
        key = (kind, mode, text)
        if key in self._maps or key in self._probing or self.project is None:
            return
        try:
            probe_text, mapping = theme_probe.probe_text(text, kind, mode)
        except ValueError:
            self._maps[key] = None
            return
        self._probing.add(key)
        render, read = self._render, self._read_usage

        def work() -> None:
            usage = None
            try:
                result = render(self.project, probe_text, f"{self.key}--probe-{kind}", mode,
                                cancel=compiler.CancelToken())
                if result.pdf is not None:
                    usage = read(result.pdf, mapping, kind, mode, dpi=RENDER_DPI)
            except Exception:       # no map: the slides stay undimmed, the form still works
                usage = None
            self.probed.emit(key, usage)

        threading.Thread(target=work, daemon=True, name="theme-probe").start()

    def _on_probed(self, key, usage) -> None:
        self._probing.discard(key)
        if key[2] == self.editor.text():
            self._maps[key] = usage
        self._jump_to_usage()
        self._show()

    def _jump_to_usage(self) -> None:
        usage = self._map()
        if usage is None or self._usage is None or not self._images:
            return
        pages = usage.pages_using(self._usage[1])
        if pages and self._page not in pages:
            self._page = pages[0]

    def _usage_text(self) -> str:
        if self._usage is None:
            return ""
        kind, name, mode = self._usage
        field = theme_fields.BY_NAME.get(("role:" + name) if kind == "role" else name)
        label = field.label if field else name
        key = (kind, mode, self.editor.text())
        if key in self._probing or (key not in self._maps and self.project is not None):
            return f"Finding where {label} is used on the sample slides…"
        usage = self._maps.get(key)
        if usage is None:
            return ""
        pages = usage.pages_using(name)
        if not pages:
            return f"{label} is not used on the sample slides."
        listed = ", ".join(str(p) for p in pages)
        return f"Lit up: where {label} is used (page{'s' if len(pages) > 1 else ''} {listed})."

    def _composite(self, image: QImage) -> QImage:
        """`image` dimmed but where the focused colour is used."""
        usage = self._map()
        if usage is None or self._usage is None or not usage.width:
            return image
        mask_bytes = usage.mask(self._page, self._usage[1])
        if not any(mask_bytes):
            return image
        mask = QImage(mask_bytes, usage.width, usage.height, usage.width, QImage.Format.Format_Grayscale8).copy()
        mask = mask.scaled(image.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        lit = image.convertToFormat(QImage.Format.Format_ARGB32)
        lit.setAlphaChannel(mask)
        result = image.convertToFormat(QImage.Format.Format_ARGB32)
        painter = QPainter(result)
        painter.fillRect(result.rect(), QColor(0, 0, 0, 165))
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):     # one pixel wider, so thin text shows
            painter.drawImage(dx, dy, lit)
        painter.end()
        return result

    # --- showing -----------------------------------------------------------------------------------------------------

    def _update_modes(self) -> None:
        file = ThemeFile(self.editor.text())
        labels = dict(parse_modes_header(file.value("header:modes") or ""))
        wanted = [(mode_id, labels.get(mode_id) or mode_id.capitalize()) for mode_id, _ in file.modes()] or [("", "Colours")]
        current = [(self.mode_combo.itemData(i), self.mode_combo.itemText(i)) for i in range(self.mode_combo.count())]
        if [data for data, _ in current] != [data for data, _ in wanted]:
            keep = self.mode
            self.mode_combo.clear()
            for data, text in wanted:
                self.mode_combo.addItem(text, data)
            index = self.mode_combo.findData(keep)
            self.mode_combo.setCurrentIndex(max(index, 0))
        self.mode_combo.setVisible(len(wanted) > 1 and not self._external_mode)

    def follow_mode_bar(self) -> None:
        """The theme tab's mode bar picks the mode (set_mode): the panel's own picker goes."""
        self._external_mode = True
        self.mode_combo.hide()

    def set_mode(self, mode: str) -> None:
        """Render in `mode` from now on (the mode bar's pick)."""
        self._update_modes()
        index = self.mode_combo.findData(mode)
        if index >= 0 and index != self.mode_combo.currentIndex():
            self.mode_combo.setCurrentIndex(index)
            self._images = []
            self.render_soon(0)

    def _update_thumbs(self) -> None:
        count = len(self._images)
        while len(self._thumb_buttons) < count:
            button = QToolButton()
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            number = len(self._thumb_buttons) + 1
            button.clicked.connect(lambda _=False, n=number: self.show_page(n))
            self.thumbs.addWidget(button)
            self._thumb_buttons.append(button)
        usage = self._map()
        used = set(usage.pages_using(self._usage[1])) if usage is not None and self._usage is not None else set()
        names = dict(theme_sample.PAGES)
        for number, button in enumerate(self._thumb_buttons, start=1):
            if number > count:
                button.hide()
                continue
            image = self._images[number - 1]
            button.setIcon(QPixmap.fromImage(image.scaledToWidth(84, Qt.TransformationMode.SmoothTransformation)))
            button.setIconSize(QSize(84, 48))
            button.setText(f"{number} \u25cf" if number in used else str(number))
            button.setToolTip(names.get(number, "") + (" · uses the focused colour" if number in used else ""))
            button.setDown(number == self._page)
            button.show()

    def show_page(self, page: int) -> None:
        if self._images:
            self._page = min(max(page, 1), len(self._images))
        self._show()

    def _show(self) -> None:
        count = len(self._images)
        self._page = min(max(self._page, 1), count) if count else self._page
        names = dict(theme_sample.PAGES)
        self.page_label.setText(f"Page {self._page} of {count}: {names.get(self._page, '')}" if count else "")
        self.previous.setEnabled(count > 0 and self._page > 1)
        self.next.setEnabled(count > 0 and self._page < count)
        if self._error.strip():
            first = self._error.strip().splitlines()[0]
            self.status.setText(f"The theme does not compile as it is: {first} (the whole message is the tooltip)")
            self.status.setToolTip(self._error)
        elif self._cancel is None:
            self.status.setText("" if count else ("The sample slides render when the panel is shown."
                                                  if self.project is not None else "No project: nothing to render."))
            self.status.setToolTip("")
        usage_text = self._usage_text()
        self.usage_label.setText(usage_text)
        self.usage_label.setVisible(bool(usage_text))
        self._update_thumbs()
        self._show_image()

    def _show_image(self) -> None:
        if not self._images:
            self.image.clear()
            return
        image = self._paint_marks(self._composite(self._images[self._page - 1]))
        size = self.image.size()
        if size.width() < 10 or size.height() < 10:
            return
        self.image.setPixmap(QPixmap.fromImage(image).scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
