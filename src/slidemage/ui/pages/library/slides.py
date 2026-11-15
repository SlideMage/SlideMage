# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation groups in a virtualised grid, with visible-row previews only."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import (QAbstractListModel, QEvent, QItemSelectionModel, QModelIndex,
                            QRect, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QListView,
                               QScrollArea, QStyle, QStyledItemDelegate, QVBoxLayout)

from .... import (alt_blocks, bundled_copies, deck_context, deck_editor, deck_scan, languages,
                  library_data, preview_target, render_key, render_lookup, slide_language,
                  slide_usage, slide_versioning, unused_content)
from ...background import run_in_background
from ...kit.flow import FlowLayout
from ...kit.tokens import RADIUS_LG, SPACE
from ...kit.widgets import (Button, Card, Chip, Field, ModalSheet, Surface, ToggleChip,
                            RowButton, caption, clear_layout, text_label)
from ...workspace.palette import matches, words_of
from .similar import CLASSES


@dataclass
class SlideGroup:
    id: str
    slug: str
    title: str
    text: str
    badge: str
    members: list[str]
    decks: list
    unused: bool
    # Populated by the topic-block branch after it is merged.
    blocks: list[str] = field(default_factory=list)


def prepare_groups(ctx, usage, language):
    """Prepare the collection on the page's scan worker; no widgets or image reads."""
    links = slide_language.links_for(ctx)
    bundled = bundled_copies.read_manifest(ctx.root).get("manual", {}).get("files", {})
    unused = {p.name for p in unused_content.find_unused_slides(ctx)}
    groups = {}
    for bare, path in sorted(links.paths.items()):
        if path.name.startswith("ZZ") or path.relative_to(ctx.root).as_posix() in bundled:
            continue
        group = links.group(bare)
        original = slide_language.bare_id(group.original or bare)
        groups.setdefault(original, []).append(path.name[:-len(slide_language.CURRENT_SUFFIX)])
    rows = []
    for original, members in groups.items():
        slug = next((s for s in members if links.own(s) == language),
                    next((s for s in members if slide_language.bare_id(s) == original), members[0]))
        text = "\n".join(links.header(s) for s in members)
        decks = {d.path: d for s in members for d in usage.get(slide_language.bare_id(s), [])
                 if d.path.parent != ctx.root / "blocks"}
        rows.append(SlideGroup(original, slug,
                               alt_blocks.plain_title(deck_context.frame_title(links.header(slug)) or slug),
                               text, slide_language.badge_for(ctx, slug, links=links).text(), members,
                               sorted(decks.values(), key=lambda d: d.path.stat().st_mtime_ns),
                               all(slide_language.current_name(s) in unused for s in members)))
    return sorted(rows, key=lambda row: (row.title.casefold(), row.id))


def load_picture(ctx, row, resolver, language, *, large=False):
    """The same Instructor-reference route as Similar; decode off the GUI thread."""
    if resolver is None:
        return QImage()
    try:
        own = slide_language.own_language(row.slug, languages.project_languages(ctx).codes)
        target = preview_target.PreviewTarget(ctx, "slide", row.slug, None, None, None, None,
                                              row.decks[-1].preamble_text if row.decks else None)
        unit = render_key.unit_for(target, "instructor", own if own not in (None, "mult") else language)
        record = render_lookup.instructor_reference(dict(resolver=resolver, unit=unit), strict=True)
        if record is None:
            return QImage()
        if large:
            data = resolver.store.page(record, record["pages"])
        else:
            path = resolver.store.thumbnail_path(record)
            data = path.read_bytes() if path is not None else None
        image = QImage.fromData(data) if data else QImage()
        return image if image.isNull() else image.scaled(
            608 if large else 256, 342 if large else 144,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception:  # Rendering can be disabled; publications can disappear during a read.
        return QImage()


class SlideModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups = []
        self.rows = []
        self.library = library_data.LibraryData()

    def set_groups(self, groups, library):
        self.groups, self.library = groups, library
        self.filter()

    def filter(self, scope="all", topic="", query=""):
        words = words_of(query)
        self.beginResetModel()
        self.rows = [row for row in self.groups
                     if (scope != "pool" or row.id in self.library.pool or row.blocks)
                     and (scope != "unused" or row.unused)
                     and (not topic or topic in self.library.topics.get(row.id, set()))
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
        pooled = row.id in view.model.library.pool or bool(row.blocks)
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
                              ("Add topic", self._add_topic), ("Clear", lambda: self.grid.clearSelection())):
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
        self.grid.viewport().installEventFilter(self)
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
        for handle in (self._thumbs, self._detail):
            if handle is not None:
                handle.stop(wait_ms=0)
        self._thumbs = self._detail = None
        self._pictures, self._visible = {}, ()
        self._current = None
        self.details.hide()
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
                                  for t in self.model.library.topics.get(row.id, set())}, key=str.casefold)]:
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
            if self._detail:
                self._detail.stop(wait_ms=0)
                self._detail = None
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
        if watched is self.grid.viewport() and event.type() in (QEvent.Type.Paint, QEvent.Type.Resize, QEvent.Type.Show):
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
        resolver = getattr(self.app.background.renderer, "resolver", None)

        def load(cancel):
            pictures = {}
            for row in rows:
                if cancel.is_set():
                    break
                pictures[row.id] = load_picture(ctx, row, resolver, language)
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
        if self._detail:
            self._detail.stop(wait_ms=0)
        self.details.show()
        self.detail_title.setText(row.title)
        self.preview.clear()
        self.preview.setText(row.title)
        self.render_button.show()
        self.render_button.setEnabled(self._render is None)
        self.versions.setText("Loading versions and languages…")
        self.pool_switch.setChecked(row.id in self.model.library.pool or bool(row.blocks))
        self.pool_switch.setEnabled(self._write is None)
        self.open_source.setEnabled(True)
        self.show_deck.setEnabled(bool(row.decks))
        self.detail_status.setText("")
        clear_layout(self.topics)
        for topic in sorted(self.model.library.topics.get(row.id, set())):
            chip = Chip(topic + " ×", pressable=True)
            chip.setToolTip("Remove topic " + topic)
            chip.clicked.connect(lambda topic=topic: self.update_library("remove_topic", topic, detail=True))
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
        ctx, language = self.app.project, self.app.state.language
        resolver = getattr(self.app.background.renderer, "resolver", None)

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
            return usages, "\n\n".join(versions), load_picture(ctx, row, resolver, language, large=True)

        def done(result, error):
            self._detail = None
            if error is not None:
                self.detail_status.setText(f"Could not load details: {error}")
                return
            usages, versions, picture = result
            self.versions.setText(f"ID: {row.id}  {row.badge}\n\n{versions}")
            if not picture.isNull():
                self.preview.setPixmap(QPixmap.fromImage(picture).scaled(
                    self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.render_button.hide()
            for usage in usages:
                button = RowButton(None, usage.deck.name, usage.state_text(), elide_title=True)
                button.clicked.connect(lambda _checked=False, deck=usage.deck: self._open_deck(deck))
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

    def _open_deck(self, deck):
        row = self._current
        self.app.stack.setCurrentWidget(self.app.centre)
        self.app.state.set_deck(deck)
        ids = {slide_language.bare_id(s) for s in row.members}
        target = next((r for r in self.app.slide_list.rows()
                       if r.call.id in ids or r.deck_call.id in ids or ids.intersection(r.related_ids)), None)
        if target is not None:
            self.app.state.set_focused_slide(target.call.id, occurrence_key=target.key)
        self.app.state.set_mode("preview")

    def _add_topic(self, _checked=False, *, detail=False):
        sheet = ModalSheet("Add topic", self, width=420)
        name = QLineEdit()
        sheet.add_tab("", Field("Topic", name))
        sheet.add_button("Cancel", role="reject")
        sheet.add_button("Add topic", kind="primary", role="accept")
        if sheet.exec() and name.text().strip():
            self.update_library("topic", name.text().strip(), detail=detail)

    def update_library(self, action, value=True, *, detail=False):
        if self._write is not None:
            return
        rows = [self._current] if detail and self._current else [i.data(Qt.ItemDataRole.UserRole)
                                                               for i in self.grid.selectedIndexes()]
        ids = {row.id for row in rows}
        if not ids:
            return
        ctx = self.app.project
        self.actions.setEnabled(False)
        self.pool_switch.setEnabled(False)

        def write():
            data = library_data.read(ctx)
            if action == "pool":
                if value:
                    data.pool.update(ids)
                    data.not_reusable.difference_update(ids)
                else:
                    data.pool.difference_update(ids)
            elif action == "not_reusable":
                data.not_reusable.update(ids)
                data.pool.difference_update(ids)
            else:
                for bare in ids:
                    topics = data.topics.setdefault(bare, set())
                    topics.discard(value) if action == "remove_topic" else topics.add(value)
            library_data.write(ctx, data)
            unused = {p.name for p in unused_content.find_unused_slides(ctx)}
            return data, unused

        def done(result, error):
            self._write = None
            self.actions.setEnabled(True)
            self.pool_switch.setEnabled(True)
            if error is not None:
                self.status.setText(f"Could not save library: {error}")
                self.status.show()
                if self._current:
                    self.pool_switch.setChecked(self._current.id in self.model.library.pool)
                return
            self.model.library, unused = result
            for row in self.model.groups:
                row.unused = all(slide_language.current_name(s) in unused for s in row.members)
            self._rebuild_topics()
            self._filter()
            self.library_changed.emit(self.model.library)

        self._write = run_in_background(write, done, parent=self)

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
            target = preview_target.PreviewTarget(ctx, "slide", row.slug, None, None, None, None,
                                                  row.decks[-1].preamble_text if row.decks else None)
            own = slide_language.own_language(row.slug, slide_language.links_for(ctx).codes)
            request = service.request(target, path.read_text(encoding="utf-8"), "instructor",
                                      own if own not in (None, "mult") else language, self.app.log,
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
        self._picture_timer.stop()
        for name in ("_thumbs", "_detail", "_write", "_render"):
            handle = getattr(self, name)
            if handle is not None:
                handle.stop(wait_ms=0)
                setattr(self, name, None)
        self._visible, self._pictures = (), {}
