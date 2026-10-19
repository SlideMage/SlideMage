# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The slide list's tree: sections with their slides, painted as in the prototype
(thumbnail, id line, title, call-variant chip) -- the view half of slide_list.py.

The tree holds no file-format logic: it shows a `deck_outline` outline, tells
its owner what the user did (`command` for keys, `moved` for a drop) and
leaves every edit to it. A section is a top-level item that collapses on a
click; the slides under it are selectable and can be dragged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...deck_editor import SlideCall
from ...deck_outline import SectionRow, SlideRow
from ..kit import kit_qss as q
from ..kit.theme import ThemeManager
from ..kit.tokens import FONT_ICONS, FONT_MONO, FONT_SANS
from .state import WorkspaceState
from .topbar import VIEW_TONES

DATA = Qt.ItemDataRole.UserRole       # the SectionRow or SlideRow of an item
SECTION_HEIGHT = 36                   # 8 px gap above the heading, then 28
SLIDE_HEIGHT = 44
REVIEW_HEIGHT = 68
THUMB_W, THUMB_H = 56, 31.5


def variant_label(call: SlideCall) -> str:
    """The chip on a row: how the deck calls the slide ("" for a plain, live \\slide)."""
    views = "·".join(v[0].upper() for v in call.conditions or ())
    return {
        "slide": "",
        "slidefinal": "final",
        "omitslide": "omit",
        "conditionalslide": views,
        "slidestep": " · ".join(filter(None, (f"step {call.steps}", views))),
        "slideversion": f"v{call.version}",
        "omitslideversion": f"omit v{call.version}",
    }[call.macro]


def meta_text(row: SlideRow, language: str) -> str:
    """The small line above the title: "3 · 1y8 [EN] · hidden"."""
    parts = [f"{row.position} · {row.call.id}" + (f" {row.badge}" if row.badge else "")]
    if row.hidden:
        parts.append("hidden")
    if row.missing_translation:
        parts.append(f"no {language}")
    if row.lint_error:
        parts.append("source error")
    if row.stale_preview:
        parts.append("preview old")
    elif row.thumbnail is not None and row.thumbnail_note and not row.thumbnail_verified:
        parts.append("reference preview")
    return " · ".join(parts)


def tooltip_text(row: SlideRow, view_label: str, language: str) -> str:
    call = row.call
    lines = [call.id_slug]
    if row.unreviewed:
        lines.append("Not reviewed: changed by Claude. Click the check button to mark reviewed after checking it.")
    if row.hidden:
        lines.append(f"Not typeset in {view_label}.")
    if row.missing_translation:
        lines.append(f"No {language} version of this slide.")
    if row.lint_error:
        lines.append("The source has an error the pre-render check would stop at.")
    if row.stale_preview:
        lines.append("The preview is older than the source.")
    if row.thumbnail_note:
        lines.append(row.thumbnail_note)
    if not call.editable:
        lines.append(f"Read-only here: {call.readonly_reason}.")
    return "\n".join(lines)


class SlideDelegate(QStyledItemDelegate):
    """Paints sections and slides, and edits a section's name inline."""

    reviewed = Signal(object)       # SlideRow whose review button was clicked
    renamed = Signal(object, str)    # SectionRow, new title

    def __init__(self, tree: "SlideTree", theme: ThemeManager, state: WorkspaceState) -> None:
        super().__init__(tree)
        self._tree = tree
        self._theme = theme
        self._state = state
        self._pixmaps: dict[Path, QPixmap] = {}

    def forget_pixmaps(self, paths=None) -> None:
        if paths is None:
            self._pixmaps.clear()
        else:
            for path in paths:
                self._pixmaps.pop(path, None)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        row = index.data(DATA)
        return QSize(0, SECTION_HEIGHT if isinstance(row, SectionRow) else REVIEW_HEIGHT if row.unreviewed else SLIDE_HEIGHT)

    @staticmethod
    def review_button(rect) -> QRectF:
        return QRectF(rect.right() - 28, rect.bottom() - 25, 24, 20)

    def editorEvent(self, event, model, option, index) -> bool:
        row = index.data(DATA)
        if (isinstance(row, SlideRow) and row.unreviewed
                and event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                and self.review_button(option.rect).contains(event.position())):
            self.reviewed.emit(row)
            return True
        return super().editorEvent(event, model, option, index)

    # -- inline rename -------------------------------------------------------

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:
        editor = QLineEdit(parent)
        editor.setObjectName(q.SLIDES_RENAME)
        return editor

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        editor.setText(index.data(DATA).title)
        editor.selectAll()

    def setModelData(self, editor: QWidget, model, index: QModelIndex) -> None:
        self.renamed.emit(index.data(DATA), editor.text())   # the list rebuilds after the edit

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        editor.setGeometry(option.rect.adjusted(0, 8, 0, 0))

    # -- painting ------------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        data = index.data(DATA)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = self._theme.tokens
        if isinstance(data, SectionRow):
            self._paint_section(painter, option, index, data, tokens)
        else:
            self._paint_slide(painter, option, index, data, tokens)
        painter.restore()

    @staticmethod
    def _font(family: str, px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(family)
        font.setPixelSize(round(px))
        font.setWeight(weight)
        return font

    def _paint_section(self, painter, option, index, section: SectionRow, t) -> None:
        rect = QRectF(option.rect.adjusted(0, 8, 0, 0))
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QColor(t.hover))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(t.text_2))
        painter.setFont(self._font(FONT_SANS, 9))
        caret = "▾" if option.state & QStyle.StateFlag.State_Open else "▸"
        painter.drawText(QRectF(rect.left() + 6, rect.top(), 12, rect.height()), Qt.AlignmentFlag.AlignVCenter, caret)
        count = str(len(section.rows))
        font = self._font(FONT_SANS, 13, QFont.Weight.Medium)
        painter.setFont(font)
        count_width = QFontMetrics(font).horizontalAdvance(count)
        painter.drawText(QRectF(rect.right() - 6 - count_width, rect.top(), count_width, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, count)
        left = rect.left() + 22
        right = rect.right() - 14 - count_width
        if section.chapter is not None and not section.editable:
            painter.setFont(self._font(FONT_ICONS, 15))
            painter.setPen(QColor(t.text_3))
            painter.drawText(QRectF(right - 15, rect.top(), 16, rect.height()), Qt.AlignmentFlag.AlignCenter, "lock")
            right -= 20
            painter.setPen(QColor(t.text_2))
        painter.setFont(font)
        name = QFontMetrics(font).elidedText(section.title, Qt.TextElideMode.ElideRight, int(right - left))
        painter.drawText(QRectF(left, rect.top(), right - left, rect.height()), Qt.AlignmentFlag.AlignVCenter, name)

    def _paint_slide(self, painter, option, index, row: SlideRow, t) -> None:
        # one selected slide is just the focused one; the tint marks a group
        selected = bool(option.state & QStyle.StateFlag.State_Selected) and self._tree.multi
        current = index == self._tree.currentIndex()
        rect = QRectF(option.rect.adjusted(0, 1, 0, -1))
        view_color = QColor(t.view_color(VIEW_TONES[self._state.view]))
        if selected:
            fill = QColor(t.info_bg)
        elif current:
            fill = QColor(t.surface)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            fill = QColor(t.hover)
        else:
            fill = None
        painter.setPen(Qt.PenStyle.NoPen)
        if fill is not None:
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)
        if current:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(view_color, 1.5))
            painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), 4, 4)
        if row.hidden and not current:
            painter.setOpacity(0.4)

        if row.unreviewed:
            font = self._font(FONT_SANS, 10.5, QFont.Weight.Medium)
            width = QFontMetrics(font).horizontalAdvance("Not reviewed") + 14
            chip = QRectF(rect.left() + THUMB_W + 15, rect.bottom() - 22, width, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.warning_bg))
            painter.drawRoundedRect(chip, 8, 8)
            painter.setFont(font)
            painter.setPen(QColor(t.warning_fg))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, "Not reviewed")
            button = self.review_button(option.rect)
            painter.setBrush(QColor(t.line))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(button, 4, 4)
            painter.setPen(QColor(t.text_2))
            painter.setFont(self._font(FONT_ICONS, 16))
            painter.drawText(button, Qt.AlignmentFlag.AlignCenter, "done")
            rect.setBottom(rect.bottom() - 24)

        # thumbnail, white like a slide, with a red dot when the source has an error
        thumb = QRectF(rect.left() + 6, rect.center().y() - THUMB_H / 2, THUMB_W, THUMB_H)
        pixmap = self._thumbnail(row.thumbnail)
        painter.setPen(QPen(QColor(0, 0, 0, 20), 1))
        painter.setBrush(QColor(t.paper) if pixmap is not None else QColor(t.line))
        painter.drawRoundedRect(thumb, 3, 3)
        if pixmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(thumb, pixmap, QRectF(pixmap.rect()))
        if row.lint_error:
            dot = QRectF(thumb.right() - 6, thumb.top() - 3, 9, 9)
            painter.setPen(QPen(QColor(t.bg), 2))
            painter.setBrush(QColor(t.error))
            painter.drawEllipse(dot)

        # the right edge: lock for a call that can't be edited here, then the variant chip
        right = rect.right() - 6
        painter.setPen(Qt.PenStyle.NoPen)
        if not row.call.editable:
            painter.setFont(self._font(FONT_ICONS, 14))
            painter.setPen(QColor(t.text_4))
            painter.drawText(QRectF(right - 14, rect.top(), 15, rect.height()), Qt.AlignmentFlag.AlignCenter, "lock")
            right -= 18
        label = variant_label(row.call)
        if label:
            font = self._font(FONT_SANS, 10.5, QFont.Weight.Medium)
            width = QFontMetrics(font).horizontalAdvance(label) + 14
            chip = QRectF(right - width, rect.center().y() - 8, width, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.line))
            painter.drawRoundedRect(chip, 8, 8)
            painter.setFont(font)
            painter.setPen(QColor(t.text_2))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
            right = chip.left() - 6

        # two lines of text: the id line in mono, the title below
        left = thumb.right() + 9
        meta_font = self._font(FONT_MONO, 10.5)
        painter.setFont(meta_font)
        meta_color = view_color if current else QColor(t.text_3)
        metrics = QFontMetrics(meta_font)
        full_meta = meta_text(row, self._state.language)
        meta = metrics.elidedText(full_meta, Qt.TextElideMode.ElideRight, int(right - left))
        spans = [(meta, meta_color)]
        if row.missing_translation:
            warning = f"no {self._state.language}"
            start = full_meta.index(warning)
            if start < len(meta):
                end = start + len(warning)
                spans = [(meta[:start], meta_color), (meta[start:end], QColor(t.error)),
                         (meta[end:], meta_color)]
        meta_left = left
        for text, color in spans:
            painter.setPen(color)
            painter.drawText(QRectF(meta_left, rect.center().y() - 15, right - meta_left, 14),
                             Qt.AlignmentFlag.AlignVCenter, text)
            meta_left += metrics.horizontalAdvance(text)
        title_font = self._font(FONT_SANS, 12.5, QFont.Weight.DemiBold if current else QFont.Weight.Normal)
        title_font.setStrikeOut(row.hidden)
        painter.setFont(title_font)
        painter.setPen(QColor(t.text))
        title = QFontMetrics(title_font).elidedText(row.title, Qt.TextElideMode.ElideRight, int(right - left))
        painter.drawText(QRectF(left, rect.center().y() - 1, right - left, 17), Qt.AlignmentFlag.AlignVCenter, title)

    def _thumbnail(self, path: Optional[Path]) -> Optional[QPixmap]:
        if path is None:
            return None
        if path not in self._pixmaps:
            pixmap = QPixmap(str(path))
            self._pixmaps[path] = None if pixmap.isNull() else pixmap.scaledToWidth(
                2 * THUMB_W, Qt.TransformationMode.SmoothTransformation)
        return self._pixmaps[path]


class SlideTree(QTreeWidget):
    command = Signal(str)             # "open", "remove", "rename", "move_up", "move_down"
    moved = Signal(list, object, int)    # dragged SlideRows or [SectionRow], drop target, indicator position

    def __init__(self, theme: ThemeManager, state: WorkspaceState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.SLIDES_TREE)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformRowHeights(False)
        self.setExpandsOnDoubleClick(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.collapsed: set[str] = set()   # titles of the sections the user closed
        self._all_open = False
        self.multi = False   # more than one slide selected
        self._extends_selection = False
        self.delegate = SlideDelegate(self, theme, state)
        self.setItemDelegate(self.delegate)
        self.itemClicked.connect(self._on_clicked)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    # -- content ---------------------------------------------------------------

    def populate(self, outline: list[SectionRow], view_label: str, language: str) -> None:
        """Replace the items by `outline`; the sections in `collapsed` start closed."""
        self.clear()
        self.delegate.forget_pixmaps()
        for section in outline:
            head = QTreeWidgetItem(self)
            head.setData(0, DATA, section)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDropEnabled
            if section.chapter is not None and section.editable:
                flags |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable
            head.setFlags(flags)
            for row in section.rows:
                item = QTreeWidgetItem(head)
                item.setData(0, DATA, row)
                item.setToolTip(0, tooltip_text(row, view_label, language))
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if row.call.editable:
                    flags |= Qt.ItemFlag.ItemIsDragEnabled
                item.setFlags(flags)
        self.show_sections()

    def section_items(self) -> list[QTreeWidgetItem]:
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def slide_items(self) -> list[QTreeWidgetItem]:
        return [head.child(i) for head in self.section_items() for i in range(head.childCount())]

    @staticmethod
    def data_of(item: Optional[QTreeWidgetItem]):
        return item.data(0, DATA) if item is not None else None

    def selected_rows(self) -> list[SlideRow]:
        return [r for r in map(self.data_of, self.selectedItems()) if isinstance(r, SlideRow)]

    def show_sections(self, all_open: bool = False) -> None:
        """Open the sections that are not in `collapsed`, or every one (while a filter is on)."""
        self._all_open = all_open
        for head in self.section_items():
            head.setExpanded(all_open or self.data_of(head).title not in self.collapsed)

    def toggle_section(self, item: QTreeWidgetItem) -> None:
        if self._all_open:
            return
        title = self.data_of(item).title
        self.collapsed.symmetric_difference_update({title})
        item.setExpanded(title not in self.collapsed)

    def rename(self, item: QTreeWidgetItem) -> None:
        self.editItem(item, 0)

    # -- user input --------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self.multi = len(self.selected_rows()) > 1
        self.viewport().update()

    def mousePressEvent(self, event) -> None:
        self._extends_selection = bool(
            event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        super().mousePressEvent(event)

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """A click on a section heading opens or closes it (not when it extends a selection)."""
        if item.parent() is None and not self._extends_selection:
            self.toggle_section(item)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if event.modifiers() & Qt.KeyboardModifier.AltModifier and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.command.emit("move_up" if key == Qt.Key.Key_Up else "move_down")
        elif key == Qt.Key.Key_Delete:
            self.command.emit("remove")
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.command.emit("open")
        elif key == Qt.Key.Key_F2:
            self.command.emit("rename")
        elif key == Qt.Key.Key_Escape:
            self.clearSelection()
        else:
            super().keyPressEvent(event)

    def dropEvent(self, event) -> None:
        """Report the drop instead of letting Qt move the items: the deck file
        is what changes, and the list is rebuilt from it."""
        target = self.data_of(self.itemAt(event.position().toPoint()))
        current = self.data_of(self.currentItem())
        sources = [current] if isinstance(current, SectionRow) else self.selected_rows()
        position = int(self.dropIndicatorPosition().value)
        event.setDropAction(Qt.DropAction.IgnoreAction)   # nothing for Qt to remove from the source
        event.accept()
        if target is not None and sources:
            self.moved.emit(sources, target, position)
