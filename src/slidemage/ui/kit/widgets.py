"""Reusable widgets of the redesigned UI (UI_REDESIGN_PLAN.md, step 1).

All colors, radii and fonts come from kit_qss.py (driven by the tokens), so a
widget here only sets object names and dynamic properties and never
hard-codes a color. APIs are small and signal-based: widgets report what the
user did, callers decide what it means.

Icons are Material Icons ligatures: an icon is the font's text, e.g.
IconLabel("expand_more"); fonts.load_fonts() must have run first.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import kit_qss as q
from .tokens import FONT_ICONS, SHADOWS


def icon_font(px: int) -> QFont:
    font = QFont(FONT_ICONS)
    font.setPixelSize(px)
    return font


def apply_shadow(widget: QWidget, name: str = "raised") -> None:
    """Drop shadow from the SHADOWS tokens. A graphics effect re-renders the
    widget's children through it, so use it on small or static widgets (toast,
    raised card), not on large scrolling content."""
    shadow = SHADOWS[name]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(shadow.blur)
    effect.setOffset(0, shadow.dy)
    effect.setColor(QColor(0, 0, 0, shadow.alpha))
    widget.setGraphicsEffect(effect)


def _repolish(widget: QWidget) -> None:
    """Re-evaluate QSS after a dynamic property changed (Qt does not do it
    by itself), including descendants whose rules depend on the parent."""
    for w in (widget, *widget.findChildren(QWidget)):
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()


def _set_property(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    _repolish(widget)


class IconLabel(QLabel):
    """A Material icon drawn as text, by name ("more_vert", "lock", ...)."""

    def __init__(self, name: str, size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self.setObjectName(q.ICON)
        self.setFont(icon_font(size))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(size + 2, size + 2)

    def set_icon(self, name: str) -> None:
        self.setText(name)


class IconButton(QToolButton):
    """Flat icon-only button (30 px for the prototype's 18 px icon). `clicked`
    is the plain QAbstractButton signal; `set_active(True)` keeps the hover
    wash while the menu it opened is showing."""

    def __init__(self, name: str, tooltip: str = "", size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.ICON_BUTTON)
        self.setText(name)
        self.setFont(icon_font(size))
        self.setToolTip(tooltip)
        self.setFixedSize(size + 12, size + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def set_icon(self, name: str) -> None:
        self.setText(name)

    def set_active(self, active: bool) -> None:
        _set_property(self, "active", active)


class Button(QPushButton):
    """Text button. kind: "primary" (inverse fill), "secondary" (bordered),
    "ghost" (flat). `compact` is the smaller padding of toolbars."""

    def __init__(self, text: str, kind: str = "secondary", parent: QWidget | None = None, *,
                 compact: bool = False) -> None:
        super().__init__(text, parent)
        self.setProperty("kind", kind)
        self.setProperty("compact", compact)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Surface(QFrame):
    """A transparent container for content on a white card. A plain QWidget
    or QFrame would take the app-wide page color (theme.py), not the card's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.SURFACE)


class Card(QFrame):
    """White rounded panel on the grey page. Add content through `layout()`
    (a QVBoxLayout with the prototype's 12 px padding). `raised` adds the
    Material shadow; leave it off for big panels (see apply_shadow)."""

    def __init__(self, *, raised: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        if raised:
            apply_shadow(self, "raised")


class SegmentedControl(QFrame):
    """Exclusive pill switch such as View as [Instructor|During|After].

    items: (key, label) pairs. `tones` maps a key to "instructor", "during"
    or "after" so that segment is filled with that view color when active.
    `mono` uses the small monospace style of the EN/DE switch. `changed` is
    emitted with the key only for user clicks, not for set_current()."""

    changed = Signal(str)

    def __init__(
        self,
        items: Sequence[tuple[str, str]],
        *,
        current: str | None = None,
        tones: Mapping[str, str] | None = None,
        mono: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(q.SEGMENTED)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}
        for key, label in items:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kitSegment", True)
            button.setProperty("mono", mono)
            if tones and key in tones:
                button.setProperty("tone", tones[key])
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.changed.emit(k))
            button.installEventFilter(self)
            badge = QLabel(button)
            badge.setObjectName(q.SEGMENT_BADGE)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.hide()
            self._badges[key] = badge
            self._group.addButton(button)
            layout.addWidget(button)
            self._buttons[key] = button
        self.set_current(current if current is not None else (items[0][0] if items else None))

    def current(self) -> str | None:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return None

    def set_current(self, key: str | None) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def set_badge(self, key: str, count: int) -> None:
        """A small red count on a segment ("2" lint errors); 0 hides it."""
        badge, button = self._badges[key], self._buttons[key]
        badge.setText("99+" if count > 99 else str(count))
        button.setProperty("badge", count > 0)   # the segment makes room for it
        _repolish(button)
        badge.setVisible(count > 0)
        badge.adjustSize()
        self._place_badge(key)
        badge.raise_()

    def _place_badge(self, key: str) -> None:
        badge, button = self._badges[key], self._buttons[key]
        badge.move(max(0, button.width() - badge.width() - 4), 3)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:   # the segment grew to make room for its badge
            for key, button in self._buttons.items():
                if obj is button:
                    self._place_badge(key)
        return super().eventFilter(obj, event)


class Chip(QFrame):
    """Small pill with an optional icon, e.g. "pinned 1-0-0" or "outdated".
    tone: neutral, muted, info, warning, error, ok. Emits `clicked`."""

    clicked = Signal()

    def __init__(self, text: str, tone: str = "neutral", icon: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.CHIP)
        self.setProperty("tone", tone)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 9, 2)
        layout.setSpacing(4)
        self._icon = IconLabel(icon or "", 14)
        self._icon.setVisible(bool(icon))
        self._label = QLabel(text)
        layout.addWidget(self._icon)
        layout.addWidget(self._label)

    def text(self) -> str:
        return self._label.text()

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_tone(self, tone: str) -> None:
        _set_property(self, "tone", tone)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _MenuRow(QWidget):
    activated = Signal(str)
    hovered = Signal(object)

    def __init__(self, key: str, text: str, meta: str, icon: str, tone: str, show_icon_slot: bool,
                 swatch: str) -> None:
        super().__init__()
        self.key = key
        self.setObjectName(q.MENU_ROW)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("tone", tone)
        self.setProperty("current", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(8)
        if show_icon_slot:
            layout.addWidget(IconLabel(icon, 18))
        if swatch:
            chip = QFrame()
            chip.setObjectName(q.MENU_SWATCH)
            chip.setFixedSize(14, 14)
            chip.setStyleSheet(f"background-color: {swatch};")   # the one thing a theme can't tell
            layout.addWidget(chip)
        label = QLabel(text)
        label.setObjectName(q.MENU_TEXT)
        layout.addWidget(label, 1)
        if meta:
            meta_label = QLabel(meta)
            meta_label.setObjectName(q.MENU_META)
            layout.addWidget(meta_label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event: QEvent) -> None:
        self.hovered.emit(self)
        super().enterEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.key)
        super().mouseReleaseEvent(event)


class Popover(QFrame):
    """A frameless popup under a button, closing on a click elsewhere or Esc;
    `closed` fires whenever it hides. Fill its `body` (a QVBoxLayout) and show it with popup_below()/popup_at(); the
    widget in `focus_target` (else the popover itself) gets the keyboard."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 220) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName(q.MENU)
        self.setMinimumWidth(min_width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(4, 4, 4, 4)
        self.body.setSpacing(0)
        self.focus_target: QWidget | None = None

    def _prepare(self) -> None:
        """Called before the popup is positioned: build what is shown."""

    def popup_at(self, global_pos: QPoint) -> None:
        self._prepare()
        self._show_at(global_pos)

    def _show_at(self, global_pos: QPoint) -> None:
        self.adjustSize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(global_pos.x(), area.right() - self.width())
            y = min(global_pos.y(), area.bottom() - self.height())
            global_pos = QPoint(max(area.left(), x), max(area.top(), y))
        self.move(global_pos)
        self.show()
        (self.focus_target or self).setFocus()

    def popup_below(self, anchor: QWidget, *, align_right: bool = False) -> None:
        self._prepare()
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(anchor.width() - self.width() if align_right else 0, anchor.height() + 4))
        self._show_at(point)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()


class PopoverMenu(Popover):
    """Popup list of actions with an optional right-hand metadata column
    (shortcut, count, date). `triggered(key)` fires on click or Enter, then
    the menu closes. Rows are added with add_item/add_header/add_separator
    before popup_below()/popup_at()."""

    triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 220) -> None:
        super().__init__(parent, min_width=min_width)
        self._layout = self.body
        self._rows: list[_MenuRow] = []
        self._current = -1
        self._entries: list[tuple] = []  # queued by add_*, built on popup

    def add_item(self, key: str, text: str, *, meta: str = "", icon: str = "",
                 tone: str = "", enabled: bool = True, swatch: str = "") -> None:
        """tone "danger" colors the text as an error; `swatch` is a color ("#rrggbb")
        shown as a small square before the text."""
        self._entries.append(("item", key, text, meta, icon, tone, enabled, swatch))

    def add_header(self, text: str) -> None:
        self._entries.append(("header", text))

    def add_separator(self) -> None:
        self._entries.append(("sep",))

    def _build(self) -> None:
        while (item := self._layout.takeAt(0)) is not None:
            if item.widget() is not None:
                item.widget().setParent(None)  # gone now, not at the next event loop
        self._rows.clear()
        self._current = -1
        # An icon slot is reserved for every row once any row has an icon.
        slot = any(e[0] == "item" and e[4] for e in self._entries)
        for entry in self._entries:
            if entry[0] == "header":
                header = QLabel(entry[1])
                header.setObjectName(q.MENU_HEADER)
                self._layout.addWidget(header)
            elif entry[0] == "sep":
                sep = QFrame()
                sep.setObjectName(q.MENU_SEPARATOR)
                sep.setFixedHeight(1)
                self._layout.addSpacing(4)
                self._layout.addWidget(sep)
                self._layout.addSpacing(4)
            else:
                _, key, text, meta, icon, tone, enabled, swatch = entry
                row = _MenuRow(key, text, meta, icon, tone, slot, swatch)
                row.setEnabled(enabled)
                row.setProperty("off", not enabled)
                row.activated.connect(self._on_activated)
                row.hovered.connect(lambda r: self._set_current(self._rows.index(r)))
                self._layout.addWidget(row)
                self._rows.append(row)

    def _on_activated(self, key: str) -> None:
        self.close()
        self.triggered.emit(key)

    def _set_current(self, index: int) -> None:
        if 0 <= self._current < len(self._rows):
            _set_property(self._rows[self._current], "current", False)
        self._current = index
        if 0 <= index < len(self._rows):
            _set_property(self._rows[index], "current", True)

    def _step(self, delta: int) -> None:
        enabled = [i for i, r in enumerate(self._rows) if r.isEnabled()]
        if not enabled:
            return
        later = [i for i in enabled if (i - self._current) * delta > 0]
        target = (later[0] if delta > 0 else later[-1]) if later else (enabled[0] if delta > 0 else enabled[-1])
        self._set_current(target)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._step(1)
        elif key == Qt.Key.Key_Up:
            self._step(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and 0 <= self._current < len(self._rows):
            self._on_activated(self._rows[self._current].key)
        else:
            super().keyPressEvent(event)

    def _prepare(self) -> None:
        self._build()


class SplitButton(QFrame):
    """Inverse-filled main button plus a caret that opens a PopoverMenu
    (the "Compile PDF · Instructor ▾" control). `clicked` is the main action;
    the caret shows the menu given to set_menu()."""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.SPLIT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._main = QPushButton(text)
        self._main.setCursor(Qt.CursorShape.PointingHandCursor)
        self._main.clicked.connect(self.clicked)
        divider = QFrame()
        divider.setObjectName(q.SPLIT_DIVIDER)
        divider.setFixedWidth(1)
        self._caret = QPushButton("expand_more")
        self._caret.setObjectName(q.SPLIT_CARET)
        self._caret.setFont(icon_font(18))
        self._caret.setCursor(Qt.CursorShape.PointingHandCursor)
        self._caret.clicked.connect(self._open_menu)
        layout.addWidget(self._main)
        layout.addWidget(divider)
        layout.addWidget(self._caret)
        self._menu: PopoverMenu | None = None

    def text(self) -> str:
        return self._main.text()

    def set_text(self, text: str) -> None:
        self._main.setText(text)

    def set_menu(self, menu: PopoverMenu) -> None:
        self._menu = menu
        menu.closed.connect(lambda: self._caret.setText("expand_more"))

    def _open_menu(self) -> None:
        if self._menu is not None:
            self._caret.setText("expand_less")
            self._menu.popup_below(self, align_right=True)


class Toast(QFrame):
    """Transient message pinned to the bottom centre of its parent, with
    optional action buttons ("Undo", "Open in Source"). Messages with actions
    stay 7 s, plain ones 2.6 s (the prototype's timings). `action_triggered`
    carries the action key; the toast hides itself after an action."""

    action_triggered = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName(q.TOAST)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 10, 14, 10)
        self._layout.setSpacing(14)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        apply_shadow(self, "toast")
        parent.installEventFilter(self)
        self.hide()

    def show_message(self, text: str, actions: Sequence[tuple[str, str]] = (), *,
                     error: bool = False, timeout_ms: int | None = None) -> None:
        """actions: (key, label) pairs."""
        while (item := self._layout.takeAt(0)) is not None:
            if item.widget() is not None:
                item.widget().setParent(None)
        self._layout.addWidget(QLabel(text))
        for key, label in actions:
            button = QPushButton(label)
            button.setObjectName(q.TOAST_ACTION)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, k=key: self._on_action(k))
            self._layout.addWidget(button)
        _set_property(self, "error", error)
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(timeout_ms if timeout_ms is not None else (7000 if actions else 2600))

    def _on_action(self, key: str) -> None:
        self.hide()
        self.action_triggered.emit(key)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 20)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._reposition()
        return super().eventFilter(obj, event)


class ModalSheet(QDialog):
    """Modal dialog with a title, optional tabs and a button row.

    add_tab(label, widget) fills the body; with a single tab the tab bar is
    hidden. add_button(text, kind=..., role="accept"|"reject") appends to the
    footer; roles close the dialog with accept()/reject(). A plain QDialog
    frame is used (no custom frameless chrome): the window manager draws the
    shadow, which is reliable on every platform."""

    def __init__(self, title: str, parent: QWidget | None = None, *, width: int = 640) -> None:
        super().__init__(parent)
        self.setObjectName(q.SHEET)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(12)
        self._title = QLabel(title)
        self._title.setObjectName(q.SHEET_TITLE)
        self._tabs = QTabBar()
        self._tabs.setObjectName(q.SHEET_TABS)
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tabs.hide()
        self._stack = QStackedWidget()
        self._footer = QHBoxLayout()
        self._footer.setSpacing(8)
        self._footer.addStretch(1)
        root.addWidget(self._title)
        root.addWidget(self._tabs)
        root.addWidget(self._stack, 1)
        root.addLayout(self._footer)
        self._tabs.currentChanged.connect(self._stack.setCurrentIndex)

    def add_tab(self, label: str, widget: QWidget) -> int:
        self._tabs.addTab(label)
        index = self._stack.addWidget(widget)
        self._tabs.setVisible(self._tabs.count() > 1)
        return index

    def set_current_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    def add_button(self, text: str, *, kind: str = "secondary", role: str | None = None) -> Button:
        button = Button(text, kind)
        if role == "accept":
            button.clicked.connect(self.accept)
        elif role == "reject":
            button.clicked.connect(self.reject)
        self._footer.addWidget(button)
        return button
