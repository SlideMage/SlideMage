"""The left column of the Images page: which slides to look at.

Every slide that shows at least one image, filtered (image_review.FILTERS), ordered by the open
deck or by file, found by id, with its review state as a marker. The column only lists and reports
the user's choices as signals; the page decides what they mean (it keeps the slide views and the
store entries and hands them in).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem

from ... import alt_images, image_review, slide_language
from ..kit import kit_qss as q
from ..kit.tokens import Tokens
from ..kit.widgets import Card, DropdownButton, IconButton, PopoverMenu, SegmentedControl, caption
from ..text import plural

ORDERS = (("deck", "Deck order"), ("files", "File order"))
MARKER = 14


def marker(state: str, tokens: Tokens) -> QIcon:
    """Fill says how complete a description is, color how far to trust it: empty (nothing there),
    half (written, nobody has checked it / checked, then changed), full (checked and current)."""
    color = QColor({alt_images.STATE_NONE: tokens.error, alt_images.STATE_DRAFT: tokens.info,
                    alt_images.STATE_STALE: tokens.warning, alt_images.STATE_REVIEWED: tokens.ok}[state])
    pixmap = QPixmap(MARKER, MARKER)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 2, MARKER - 4, MARKER - 4)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    if state == alt_images.STATE_REVIEWED:
        painter.drawEllipse(2, 2, MARKER - 4, MARKER - 4)
    elif state in (alt_images.STATE_DRAFT, alt_images.STATE_STALE):
        painter.drawPie(2, 2, MARKER - 4, MARKER - 4, 90 * 16, 180 * 16)
    painter.end()
    return QIcon(pixmap)


class SlideNav(Card):
    selected = Signal(object)     # the SlideView the user chose (None: the list is empty)
    find_entered = Signal(str)    # an id or id-slug typed or picked
    view_changed = Signal()       # the user chose another filter or order
    rescan_clicked = Signal()
    back_clicked = Signal()

    def __init__(self, theme) -> None:
        super().__init__()
        self._theme = theme
        self.filter_index = 0
        self.shown: list[image_review.SlideView] = []
        self._counts: list[int] = [0] * len(image_review.FILTERS)
        self.setFixedWidth(340)
        layout = self.layout()
        layout.setSpacing(10)

        head = QHBoxLayout()
        back = IconButton("arrow_back", "Back to the slides", size=20)
        back.clicked.connect(self.back_clicked)
        title = QLabel("Image descriptions")
        title.setObjectName(q.DETAILS_TITLE)
        rescan = IconButton("refresh", "Rescan the slides for images")
        rescan.clicked.connect(self.rescan_clicked)
        head.addWidget(back)
        head.addWidget(title, 1)
        head.addWidget(rescan)
        layout.addLayout(head)
        self.summary = caption("")
        layout.addWidget(self.summary)

        self.filter_button = DropdownButton(q.PANEL_PICKER)
        self.filter_button.clicked.connect(self._open_filters)
        picker = QHBoxLayout()
        picker.addWidget(QLabel("Show"))
        picker.addWidget(self.filter_button, 1)
        layout.addLayout(picker)
        self.orders = SegmentedControl(ORDERS)
        self.orders.changed.connect(lambda _order: self.view_changed.emit())
        order_line = QHBoxLayout()
        order_line.addWidget(QLabel("Order"))
        order_line.addWidget(self.orders, 1)
        layout.addLayout(order_line)

        self.find = QLineEdit()
        self.find.setObjectName(q.SLIDES_FIND)
        self.find.setPlaceholderText("Find slide by id or id-slug")
        self.find.setToolTip("Jump to a slide with images by its id, whatever the filter shows.")
        self._names = QStringListModel(self)
        completer = QCompleter(self._names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._on_completed)
        self.find.setCompleter(completer)
        self.find.returnPressed.connect(self._on_return)
        layout.addWidget(self.find)

        self.slide_list = QListWidget()
        self.slide_list.setObjectName(q.IMAGE_LIST)
        self.slide_list.currentRowChanged.connect(self._on_row)
        layout.addWidget(self.slide_list, 1)
        self._icons: dict[str, QIcon] = {}

    @property
    def order(self) -> str:
        return self.orders.current() or ORDERS[0][0]

    # -- showing ----------------------------------------------------------------------------------

    def populate(self, views: list[image_review.SlideView], entries, order: dict[str, int], *,
                 preserve=None, row: int = 0) -> Optional[image_review.SlideView]:
        """List the slides of the filter; the one at path `preserve` is current, else the one now at
        `row` (the nearest). Returns it without announcing it."""
        self.shown = image_review.visible_views(views, entries, self.filter_index, order=order)
        self._counts = image_review.filter_counts(views, entries)
        self._show_filter()
        self.summary.setText(image_review.summary_text(views))
        self._names.setStringList(sorted(view.row.path.name.removesuffix(slide_language.CURRENT_SUFFIX) for view in views))
        self._icons = {state: marker(state, self._theme.tokens) for state in alt_images.STATE_LABELS}
        self.slide_list.blockSignals(True)
        self.slide_list.clear()
        for view in self.shown:
            self.slide_list.addItem(self._item(view))
        index = next((i for i, view in enumerate(self.shown) if view.row.path == preserve),
                     min(row, len(self.shown) - 1))
        self.slide_list.setCurrentRow(index)
        self.slide_list.blockSignals(False)
        return self.shown[index] if index >= 0 else None

    def refresh_items(self, views: list[image_review.SlideView], entries) -> None:
        """New states for the rows; the list is not filtered again, so that no row vanishes under the cursor."""
        for index, view in enumerate(self.shown):
            self._item(view, self.slide_list.item(index))
        self._counts = image_review.filter_counts(views, entries)
        self.summary.setText(image_review.summary_text(views))
        self._show_filter()

    def select(self, view: Optional[image_review.SlideView]) -> None:
        """Make `view` (in the list) current without announcing it."""
        index = next((i for i, shown in enumerate(self.shown) if shown is view), -1)
        self.slide_list.blockSignals(True)
        self.slide_list.setCurrentRow(index)
        self.slide_list.blockSignals(False)

    def current_row(self) -> int:
        return self.slide_list.currentRow()

    def set_filter(self, index: int) -> None:
        self.filter_index = index
        self._show_filter()

    def _item(self, view: image_review.SlideView, item: Optional[QListWidgetItem] = None) -> QListWidgetItem:
        item = item or QListWidgetItem()
        row = view.row
        item.setIcon(self._icons[view.state])
        item.setText(f"{row.slide_id}   {row.title}")
        item.setToolTip(f"{alt_images.STATE_LABELS[view.state]}\n{row.path.name}\n" + "\n".join(row.images))
        return item

    def _show_filter(self) -> None:
        label = image_review.FILTERS[self.filter_index][0]
        self.filter_button.set_text(f"{label} · {plural(self._counts[self.filter_index], 'slide')}")

    # -- the user's choices -----------------------------------------------------------------------

    def _open_filters(self) -> None:
        menu = PopoverMenu(self, min_width=300)
        for index, (label, _wanted) in enumerate(image_review.FILTERS):
            menu.add_item(str(index), label, meta=str(self._counts[index]),
                          icon="check" if index == self.filter_index else "")
        menu.triggered.connect(self._on_filter)
        menu.closed.connect(lambda: self.filter_button.set_active(False))
        menu.closed.connect(menu.deleteLater)
        self.filter_button.set_active(True)
        menu.popup_below(self.filter_button)

    def _on_filter(self, key: str) -> None:
        if int(key) != self.filter_index:
            self.set_filter(int(key))
            self.view_changed.emit()

    def _on_row(self, row: int) -> None:
        self.selected.emit(self.shown[row] if 0 <= row < len(self.shown) else None)

    def _on_completed(self, text: str) -> None:
        """A suggestion was picked. The line edit puts the completion into itself after this slot ran,
        so it is cleared on the next turn of the event loop."""
        if text.strip():
            self.find_entered.emit(text)
        QTimer.singleShot(0, self.find.clear)

    def _on_return(self) -> None:
        text = self.find.text().strip()
        self.find.clear()
        if text:
            self.find_entered.emit(text)
