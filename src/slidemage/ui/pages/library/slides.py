# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation groups in a virtualised grid, with visible-row previews only."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex,
                            QRect, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QListView,
                               QScrollArea, QStyle, QStyledItemDelegate, QVBoxLayout)

from .... import (alt_blocks, deck_context, deck_editor, deck_scan, library_data, slide_language,
                  slide_usage, slide_versioning)
from ....slide_similarity import user_slides
from ...background import run_in_background
from ...kit.flow import FlowLayout
from ...kit.tokens import RADIUS_LG
from ...kit.widgets import (Button, Card, Chip, Field, ModalSheet, Surface, ToggleChip,
                            RowButton, caption, clear_layout, text_label)
from ...workspace.palette import matches, words_of
from .similar import CLASSES
from .shared import instructor_target, load_picture, resolver_of, save_library, show_picture


@dataclass
class SlideGroup:
    id: str
    slug: str
    title: str
    text: str
    badge: str
    members: list[str]
    decks: list
    blocks: list[str] = field(default_factory=list)
    block_topics: set[str] = field(default_factory=set)


def prepare_groups(ctx, usage, blocks, language):
    """Prepare the collection on the page's scan worker; no widgets or image reads."""
    links = slide_language.links_for(ctx)
    users = set(user_slides(ctx))
    groups = {}
    for bare, path in sorted(links.paths.items()):
        if path not in users:
            continue
        group = links.group(bare)
        original = slide_language.bare_id(group.original or bare)
        groups.setdefault(original, []).append(path.name[:-len(slide_language.CURRENT_SUFFIX)])
    rows = []
    for original, members in groups.items():
        slug = next((s for s in members if links.own(s) == language),
                    next((s for s in members if slide_language.bare_id(s) == original), members[0]))
        text = "\n".join(links.header(s) for s in members)
        ids = {slide_language.bare_id(s) for s in members}
        decks = {d.path: d for i in ids for d in usage.get(i, [])}
        used_in = {key: block for key, block in blocks.items() if ids.intersection(c.id for c in block.calls)}
        rows.append(SlideGroup(original, slug,
                               alt_blocks.plain_title(deck_context.frame_title(links.header(slug)) or slug),
                               text, slide_language.badge_for(ctx, slug, links=links).text(), members,
                               sorted(decks.values(), key=lambda d: d.path.stat().st_mtime_ns),
                               sorted(used_in), {t for block in used_in.values() for t in block.topics}))
    return sorted(rows, key=lambda row: (row.title.casefold(), row.id))


class SlideModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups = []
        self.rows = []
        self.set_library(library_data.LibraryData())

    def set_library(self, library):
        self.library = library
        self.pooled = library.pool | {row.id for row in self.groups if row.blocks}

    def set_groups(self, groups, library):
        self.groups = groups
        self.set_library(library)

    def in_scope(self, row, scope):
        return (scope == "all" or scope == "pool" and row.id in self.pooled
                or scope == "unused" and not row.decks and row.id not in self.pooled)

    def filter(self, scope="all", topic="", query=""):
        words = words_of(query)
        self.beginResetModel()
        self.rows = [row for row in self.groups
                     if self.in_scope(row, scope)
                     and (not topic or topic in self.library.topics.get(row.id, set()) | row.block_topics)
                     and matches(words, row.title, *row.members, row.text)]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return f"{row.title} · {row.id} {row.badge} · in {len(row.decks)} decks"
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([row.title, *row.members, *sorted(self.library.topics.get(row.id, set()))])


class SlideDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(244, 260)

    def paint(self, painter, option, index):
        view = self.parent()
        row = index.data(Qt.ItemDataRole.UserRole)
        t = view.app.theme.tokens
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 4, -4, -4)
        painter.setBrush(QColor(t.surface))
        painter.setPen(QColor(t.focus if selected else t.line))
        painter.drawRoundedRect(rect, RADIUS_LG, RADIUS_LG)
        preview = QRect(rect.x() + 8, rect.y() + 8, rect.width() - 16, 124)
        picture = view._pictures.get(row.id)
        if picture is not None and not picture.isNull():
            size = picture.size().scaled(preview.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawPixmap(QRect(preview.center().x() - size.width() // 2,
                                      preview.center().y() - size.height() // 2, size.width(), size.height()), picture)
        else:
            painter.fillRect(preview, QColor(t.bg))
            painter.setPen(QColor(t.text_2))
            painter.drawText(preview.adjusted(8, 8, -8, -8),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, row.title)
        painter.setPen(QColor(t.text))
        title = QRect(rect.x() + 10, rect.y() + 140, rect.width() - 20, 42)
        painter.drawText(title, Qt.TextFlag.TextWordWrap, row.title)
        painter.setPen(QColor(t.text_2))
        meta = f"{row.id}  {row.badge}"
        painter.drawText(QRect(rect.x() + 10, rect.y() + 186, rect.width() - 20, 20), meta)
        pooled = row.id in view.model.pooled
        painter.setPen(QColor(t.ok_fg if pooled else t.text_3))
        count = len(row.decks)
        status = "Pool · " if pooled else ""
        if row.id in view.model.library.not_reusable:
            status += "Not reusable · "
        status += f"in {count} deck{'s' if count != 1 else ''}"
        painter.drawText(QRect(rect.x() + 10, rect.y() + 210, rect.width() - 20, 24), status)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QColor(t.focus))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), RADIUS_LG, RADIUS_LG)
        painter.restore()


class SlidesView(Surface):
    library_changed = Signal(object)
    scope_changed = Signal(str, str)
    block_requested = Signal(str)
    new_block_requested = Signal(object)
    add_to_block_requested = Signal(object)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._scope, self._topic = "all", ""
        self._detail = self._thumbs = self._write = self._render = None
        self._current = None
        self._pictures, self._visible = {}, ()
        self._clusters = []
        self.model = SlideModel(self)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        column = QVBoxLayout()
        self.heading = text_label("All slides", "title")
        column.addWidget(self.heading)
        column.addWidget(caption("One card per slide and its translations. Mark reusable slides to build your pool."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find by title, ID or text")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        column.addWidget(self.search)
        self.topic_chips = FlowLayout()
        column.addLayout(self.topic_chips)
        self.actions = Card()
        actions = FlowLayout()
        self.actions.layout().addLayout(actions)
        self.selection_count = caption()
        actions.addWidget(self.selection_count)
        for title, action in (("Add to pool", lambda: self.update_library("pool")),
                              ("Not reusable", lambda: self.update_library("not_reusable")),
                              ("Add topic", self._add_topic),
                              ("Add to block…", lambda: self.add_to_block_requested.emit(
                                  [i.data(Qt.ItemDataRole.UserRole).slug for i in self.grid.selectedIndexes()])),
                              ("New block from selection", lambda: self.new_block_requested.emit(
                                  [i.data(Qt.ItemDataRole.UserRole).slug for i in self.grid.selectedIndexes()])),
                              ("Clear", lambda: self.grid.clearSelection())):
            button = Button(title)
            button.clicked.connect(action)
            actions.addWidget(button)
        column.addWidget(self.actions)
        self.actions.hide()
        self.status = caption("Loading slides…")
        column.addWidget(self.status)
        self.grid = QListView()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setUniformItemSizes(True)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(SlideDelegate(self))
        self.grid.selectionModel().selectionChanged.connect(self._selection_changed)
        self.grid.selectionModel().currentChanged.connect(self._show_details)
        self._viewport = self.grid.viewport()
        self._viewport.installEventFilter(self)
        self.grid.verticalScrollBar().valueChanged.connect(self._queue_pictures)
        self._picture_timer = QTimer(self)
        self._picture_timer.setSingleShot(True)
        self._picture_timer.timeout.connect(self._load_visible)
        column.addWidget(self.grid, 1)
        outer.addLayout(column, 1)
        self.details = QScrollArea()
        self.details.setWidgetResizable(True)
        self.details.setFixedWidth(328)
        self.details.setFrameShape(QScrollArea.Shape.NoFrame)
        panel = Card()
        self.details.setWidget(panel)
        detail = panel.layout()
        self.preview = text_label("Select a slide", "secondary")
        self.preview.setFixedSize(280, 158)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        detail.addWidget(self.preview)
        self.render_button = Button("Render")
        self.render_button.clicked.connect(self._render_current)
        detail.addWidget(self.render_button)
        self.detail_title = text_label("", "heading")
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        detail.addWidget(self.detail_title)
        self.versions = caption()
        self.versions.setTextFormat(Qt.TextFormat.PlainText)
        self.versions.setWordWrap(True)
        detail.addWidget(self.versions)
        self.pool_switch = ToggleChip("In the pool", "instructor")
        self.pool_switch.clicked.connect(lambda checked: self.update_library("pool", checked, detail=True))
        detail.addWidget(self.pool_switch)
        self.pool_reason = caption()
        self.pool_reason.setWordWrap(True)
        detail.addWidget(self.pool_reason)
        self.block_chips = FlowLayout()
        detail.addLayout(self.block_chips)
        detail.addWidget(text_label("Topics", "heading"))
        self.topics = FlowLayout()
        detail.addLayout(self.topics)
        add_topic = Button("+ Topic", "ghost")
        add_topic.clicked.connect(lambda: self._add_topic(detail=True))
        detail.addWidget(add_topic)
        detail.addWidget(text_label("Used in", "heading"))
        self.used_in = QVBoxLayout()
        detail.addLayout(self.used_in)
        detail.addWidget(text_label("Similar", "heading"))
        self.similar = QVBoxLayout()
        detail.addLayout(self.similar)
        self.open_source = Button("Open in Source")
        self.open_source.clicked.connect(lambda: self.app.open_slide_editor(
            self.app.project.slides_dir / slide_language.current_name(self._current.slug), tab=True))
        detail.addWidget(self.open_source)
        self.show_deck = Button("Show in deck")
        self.show_deck.clicked.connect(lambda: self._open_deck(self._current.decks[-1]))
        detail.addWidget(self.show_deck)
        self.detail_status = caption()
        self.detail_status.setWordWrap(True)
        detail.addWidget(self.detail_status)
        detail.addStretch(1)
        outer.addWidget(self.details)
        self.details.hide()
        remove_listener = app.theme.add_listener(self._style)
        self.destroyed.connect(lambda: remove_listener())
        self._style()

    def _style(self):
        t = self.app.theme.tokens
        self.grid.setStyleSheet(f"QListView {{ background: {t.bg}; border: none; }}")
        self.grid.viewport().update()

    def set_groups(self, groups, library, clusters):
        if self._thumbs is not None:
            self._thumbs.stop(wait_ms=0)
        self._thumbs = None
        self._pictures, self._visible = {}, ()
        self._clusters = clusters
        self.model.set_groups(groups, library)
        self._rebuild_topics()
        self._filter()

    def set_scope(self, scope, topic=""):
        self._scope, self._topic = scope, topic
        self.heading.setText(topic or {"pool": "Pool", "all": "All slides", "unused": "Not in any deck"}[scope])
        self._rebuild_topics()
        self._filter()
        self.scope_changed.emit(scope, topic)

    def _rebuild_topics(self):
        clear_layout(self.topic_chips)
        for topic in ["", *sorted({t for row in self.model.groups
                                  for t in self.model.library.topics.get(row.id, set()) | row.block_topics}, key=str.casefold)]:
            chip = ToggleChip(topic or "All topics")
            chip.setChecked(topic == self._topic)
            chip.clicked.connect(lambda _checked=False, topic=topic: self.set_scope(self._scope, topic))
            self.topic_chips.addWidget(chip)

    def _filter(self):
        selected = {i.data(Qt.ItemDataRole.UserRole).id for i in self.grid.selectedIndexes()}
        current = self._current.id if self._current else None
        self.model.filter(self._scope, self._topic, self.search.text())
        selection = self.grid.selectionModel()
        for n, row in enumerate(self.model.rows):
            index = self.model.index(n)
            if row.id in selected:
                selection.select(index, QItemSelectionModel.SelectionFlag.Select)
            if row.id == current:
                selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        if current not in {row.id for row in self.model.rows}:
            self._current = None
            self.details.hide()
        self.status.setText("No slides match." if not self.model.rows else "")
        self.status.setVisible(not self.model.rows)
        self._selection_changed()
        self._visible = ()
        self._queue_pictures()

    def _selection_changed(self):
        count = len(self.grid.selectedIndexes())
        self.actions.setVisible(bool(count))
        self.selection_count.setText(f"{count} selected")

    def eventFilter(self, watched, event):
        if watched is self._viewport and event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Show):
            self._queue_pictures()
        return super().eventFilter(watched, event)

    def _queue_pictures(self):
        if not self._picture_timer.isActive():
            self._picture_timer.start(0)

    def _load_visible(self):
        if not self.isVisible():
            return
        viewport = self.grid.viewport().rect()
        rows = [row for n, row in enumerate(self.model.rows)
                if self.grid.visualRect(self.model.index(n)).intersects(viewport)]
        visible = tuple(row.id for row in rows)
        if visible == self._visible:
            return
        self._visible = visible
        self._pictures = {k: v for k, v in self._pictures.items() if k in visible}
        if self._thumbs:
            self._thumbs.stop(wait_ms=0)
        ctx, language = self.app.project, self.app.state.language
        resolver = resolver_of(self.app)

        def load(cancel):
            pictures = {}
            for row in rows:
                if cancel.is_set():
                    break
                pictures[row.id] = load_picture(ctx, row.slug, row.decks, resolver, language)
            return pictures

        def done(pictures, error):
            self._thumbs = None
            if error is None:
                self._pictures = {key: QPixmap.fromImage(value) for key, value in pictures.items()}
                self.grid.viewport().update()

        self._thumbs = run_in_background(load, done, parent=self)

    def _show_details(self, index, _previous=QModelIndex()):
        row = index.data(Qt.ItemDataRole.UserRole)
        if row is None:
            return
        self._current = row
        self.details.show()
        self.detail_title.setText(row.title)
        self.preview.clear()
        self.preview.setText(row.title)
        self.render_button.show()
        self.render_button.setEnabled(self._render is None)
        self.versions.setText("Loading versions and languages…")
        self.pool_switch.setChecked(row.id in self.model.pooled)
        self.pool_switch.setEnabled(self._write is None and not row.blocks)
        self.pool_switch.setToolTip("In the pool through block " + ", ".join(row.blocks) if row.blocks else "")
        self.pool_reason.setText("In the pool through block " + ", ".join(row.blocks) if row.blocks else "")
        self.pool_reason.setVisible(bool(row.blocks))
        clear_layout(self.block_chips)
        for key in row.blocks:
            chip = Chip(key, pressable=True)
            chip.clicked.connect(lambda key=key: self.block_requested.emit(key))
            self.block_chips.addWidget(chip)
        self.open_source.setEnabled(True)
        self.show_deck.setEnabled(bool(row.decks))
        self.detail_status.setText("")
        clear_layout(self.topics)
        for topic in sorted(self.model.library.topics.get(row.id, set())):
            chip = Chip(topic + " ×", pressable=True)
            chip.setToolTip("Remove topic " + topic)
            chip.clicked.connect(lambda topic=topic: self.update_library("remove_topic", topic, detail=True))
            self.topics.addWidget(chip)
        for topic in sorted(row.block_topics - self.model.library.topics.get(row.id, set())):
            chip = Chip(topic)
            chip.setToolTip("Inherited from a topic block")
            self.topics.addWidget(chip)
        clear_layout(self.used_in)
        clear_layout(self.similar)
        related = {}
        members = {slide_language.bare_id(s) for s in row.members}
        for cluster in self._clusters:
            if members.intersection(cluster.ids):
                for other in cluster.ids:
                    if other not in members:
                        related.setdefault(other, cluster.kind)
        for other, kind in list(related.items())[:5]:
            button = Button(f"{other} · {CLASSES[kind]}", "ghost")
            button.clicked.connect(lambda _checked=False, other=other: self._select_group(other))
            self.similar.addWidget(button)
        if not related:
            self.similar.addWidget(caption("No similar slides."))
        if self._detail:
            return
        ctx, language = self.app.project, self.app.state.language
        resolver = resolver_of(self.app)

        def load():
            decks = deck_scan.scan_decks(ctx)
            usages, versions = [], []
            for slug in row.members:
                usages.extend(slide_usage.find_usage(ctx, slug, decks))
                path = ctx.slides_dir / slide_language.current_name(slug)
                current = slide_versioning.version_text(path.read_text(encoding="utf-8", errors="replace"))
                frozen = [slide_versioning.version_label(v) for v in deck_editor.available_versions(ctx, slug)]
                versions.append(f"{slug}\nCurrent: {current or 'unversioned'}" +
                                (" · Saved: " + ", ".join(frozen) if frozen else ""))
            return usages, "\n\n".join(versions), load_picture(ctx, row.slug, row.decks, resolver, language, large=True)

        def done(result, error):
            self._detail = None
            if self._current is not row:
                if self._current in self.model.rows:
                    self._show_details(self.model.index(self.model.rows.index(self._current)))
                return
            if error is not None:
                self.detail_status.setText(f"Could not load details: {error}")
                return
            usages, versions, picture = result
            self.versions.setText(f"ID: {row.id}  {row.badge}\n\n{versions}")
            if show_picture(self.preview, picture):
                self.render_button.hide()
            for usage in usages:
                for deck in usage.decks if usage.block else [usage.deck]:
                    button = RowButton(None, deck.name, usage.state_text() + (
                        f" · via block {usage.block}" if usage.block else ""), elide_title=True)
                    button.clicked.connect(lambda _checked=False, deck=deck, block=usage.block: self._open_deck(deck, block))
                    self.used_in.addWidget(button)
                if usage.block and not usage.decks:
                    button = Button(f"Block {usage.block} · in no deck · Open in Source", "ghost")
                    button.clicked.connect(lambda _checked=False, path=usage.deck.path: self.app.open_slide_editor(path, tab=True))
                    self.used_in.addWidget(button)
            if not usages:
                self.used_in.addWidget(caption("In no deck", "warning"))

        self._detail = run_in_background(load, done, parent=self)

    def _select_group(self, bare):
        row = next((r for r in self.model.groups if any(slide_language.bare_id(s) == bare for s in r.members)), None)
        if row is not None:
            self.search.clear()
            self.set_scope("all")
            index = self.model.index(self.model.rows.index(row))
            self.grid.setCurrentIndex(index)
            self.grid.scrollTo(index)

    def _open_deck(self, deck, block=None):
        row = self._current
        self.app.stack.setCurrentWidget(self.app.centre)
        self.app.state.set_deck(deck_scan.read_deck(deck.path))
        self.app.slide_list.focus(block, {slide_language.bare_id(s) for s in row.members})
        self.app.state.set_mode("preview")

    def _add_topic(self, _checked=False, *, detail=False):
        sheet = ModalSheet("Add topic", self, width=420)
        name = QLineEdit()
        sheet.add_tab("", Field("Topic", name))
        sheet.add_button("Cancel", role="reject")
        sheet.add_button("Add topic", kind="primary", role="accept")
        try:
            if sheet.exec() and name.text().strip():
                self.update_library("topic", name.text().strip(), detail=detail)
        finally:
            sheet.deleteLater()

    def update_library(self, action, value=True, *, detail=False):
        if self._write is not None:
            return
        rows = [self._current] if detail and self._current else [i.data(Qt.ItemDataRole.UserRole)
                                                               for i in self.grid.selectedIndexes()]
        ids = {row.id for row in rows}
        if not ids:
            return
        self.actions.setEnabled(False)
        self.pool_switch.setEnabled(False)

        def done(library):
            self._write = None
            self.actions.setEnabled(True)
            self.pool_switch.setEnabled(not (self._current and self._current.blocks))
            if library is None:
                if self._current:
                    self.pool_switch.setChecked(self._current.id in self.model.pooled)
                return
            self.model.set_library(library)
            self._rebuild_topics()
            self._filter()
            self.library_changed.emit(library)

        self._write = save_library(self, lambda data: library_data.change_members(data, ids, action, value), done)

    def _render_current(self):
        if self._render is not None or self._current is None:
            return
        row, ctx = self._current, self.app.project
        language = self.app.state.language
        service = self.app.centre.preview._renders
        self.render_button.setEnabled(False)
        self.detail_status.setText("Rendering…")

        def render(cancel):
            path = ctx.slides_dir / slide_language.current_name(row.slug)
            target, own = instructor_target(ctx, row.slug, row.decks, language)
            request = service.request(target, path.read_text(encoding="utf-8"), "instructor", own, self.app.log,
                                      saved=True, all_steps=True)
            request.wait(cancel)

        def done(_result, error):
            self._render = None
            self._visible = ()
            self._queue_pictures()
            if self._current is row:
                if error is not None:
                    self.detail_status.setText(f"Could not render: {error}")
                    self.render_button.setEnabled(True)
                else:
                    self._show_details(self.grid.currentIndex())

        self._render = run_in_background(render, done, parent=self)

    def shutdown(self):
        if self._viewport is not None:
            self._viewport.removeEventFilter(self)
            self._viewport = None
        self._picture_timer.stop()
        for name in ("_thumbs", "_detail", "_write", "_render"):
            handle = getattr(self, name)
            if handle is not None:
                handle.stop(wait_ms=0)
                setattr(self, name, None)
        self._visible, self._pictures = (), {}
