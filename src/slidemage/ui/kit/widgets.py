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
from pathlib import Path

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QColor, QFont, QGuiApplication, QKeyEvent, QMouseEvent, QPixmap

try:                    # Qt 6.8 and later; older Qt has no live announcements
    from PySide6.QtGui import QAccessibleAnnouncementEvent
except ImportError:
    QAccessibleAnnouncementEvent = None
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
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


def clear_layout(layout: QLayout) -> None:
    """Remove everything from `layout` (nested layouts too); the widgets are gone now, not at the next event loop."""
    while (item := layout.takeAt(0)) is not None:
        if (widget := item.widget()) is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def announce(widget: QWidget, text: str) -> None:
    """Tell assistive technology `text` as a polite live region (it waits for what is being read); `widget` is
    what the announcement belongs to. Nothing happens where Qt cannot announce (before Qt 6.8)."""
    if QAccessibleAnnouncementEvent is None:
        return
    event = QAccessibleAnnouncementEvent(widget, text)
    event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
    QAccessible.updateAccessibility(event)


def _repolish(widget: QWidget) -> None:
    """Re-evaluate QSS after a dynamic property changed (Qt does not do it
    by itself), including descendants whose rules depend on the parent."""
    for w in (widget, *widget.findChildren(QWidget)):
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()


def set_property(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    _repolish(widget)


class ClickFrame(QFrame):
    """A frame that emits `clicked` when the left button is released over it: the base of the kit's
    clickable rows, chips and tiles."""

    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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

    def set_tone(self, tone: str) -> None:
        """"error", "ok", "warning", "strong" or "muted" colors the icon; "" is the default grey."""
        set_property(self, "tone", tone)


class ElidedLabel(QLabel):
    """One line of text, cut with … to the width it gets (it never asks for more); the whole text is the tooltip
    and `full_text()`."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))


class _EnterPresses:
    """Mixin for a button: Enter presses it like Space does (Qt does it only for the default button of a dialog)."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)


class IconButton(_EnterPresses, QToolButton):
    """Flat icon-only button (30 px for the prototype's 18 px icon). `clicked`
    is the plain QAbstractButton signal; `set_active(True)` keeps the hover
    wash while the menu it opened is showing. Its tooltip is also its accessible name (the text is the icon's
    ligature, which a screen reader would spell out)."""

    def __init__(self, name: str, tooltip: str = "", size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.ICON_BUTTON)
        self.setText(name)
        self.setFont(icon_font(size))
        self.setToolTip(tooltip)
        self.setFixedSize(size + 12, size + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self.setAccessibleName(tip)

    def set_icon(self, name: str) -> None:
        self.setText(name)

    def set_active(self, active: bool) -> None:
        set_property(self, "active", active)


class DropdownButton(ClickFrame):
    """A label with a chevron that opens a menu: the deck switcher, the side panel picker.
    `name` is the object name its QSS rules are written for; `clicked` is emitted on
    release, `set_active` shows the menu is open."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 4, 5)
        layout.setSpacing(6)
        self._label = QLabel()
        layout.addWidget(self._label)
        layout.addWidget(IconLabel("expand_more", 20))

    def text(self) -> str:
        return self._label.text()

    def set_text(self, text: str, *, max_width: int | None = None) -> None:
        """Optionally elide the label to fit the whole button within `max_width`."""
        if max_width is not None:
            self._label.ensurePolished()
            layout = self.layout()
            margins = layout.contentsMargins()
            overhead = margins.left() + margins.right() + layout.spacing() + layout.itemAt(1).sizeHint().width()
            text = self._label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight,
                                                       max(0, max_width - overhead))
        self._label.setText(text)

    def set_active(self, active: bool) -> None:
        set_property(self, "active", active)

    def event(self, event: QEvent) -> bool:
        # The :hover rule needs a repolish of this frame, not just of the label under the pointer.
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            _repolish(self)
        return super().event(event)


def caption(text: str = "", tone: str = "") -> QLabel:
    """A wrapping line of small grey text under a control; tone "error" turns it red."""
    label = QLabel(text)
    label.setObjectName(q.PANEL_CAPTION)
    label.setWordWrap(True)
    if tone:
        label.setProperty("tone", tone)
    return label


def row(*widgets: QWidget, stretch: int = 0) -> QWidget:
    """`widgets` side by side; the `stretch`-th one takes the spare width."""
    box = Surface()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == stretch else 0)
    return box


def columns(*widgets: QWidget) -> QWidget:
    """`widgets` side by side, as wide as each other and level at the top: two form fields in a
    line."""
    box = Surface()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget, 1, Qt.AlignmentFlag.AlignTop)
    return box


class Button(_EnterPresses, QPushButton):
    """Text button. kind: "primary" (inverse fill), "secondary" (bordered),
    "ghost" (flat). `compact` is the smaller padding of toolbars. It takes the focus from the Tab key only, so the
    focus ring is a keyboard ring (a click does not draw it)."""

    def __init__(self, text: str, kind: str = "secondary", parent: QWidget | None = None, *,
                 compact: bool = False) -> None:
        super().__init__(text, parent)
        self.setProperty("kind", kind)
        self.setProperty("compact", compact)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)


class Surface(QFrame):
    """A transparent container for content on a white card. A plain QWidget
    or QFrame would take the app-wide page color (theme.py), not the card's."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.SURFACE)


class Page(Surface):
    """The content of a sheet tab (or of one step of it): a column of widgets, added through
    `body`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)


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
    emitted with the key only for user clicks, not for set_current().

    `icons` maps a key to a Material icon shown before its label. `roving` makes it a radio group for the
    keyboard (the AI switch): only the current segment is in the tab order, ←/→ ask for the neighbouring
    segment (`changed`, like a click) and Enter clicks. Any segment that has the focus shows the ring. Whoever owns
    the control decides what a request means and calls set_current() to settle it."""

    changed = Signal(str)

    def __init__(
        self,
        items: Sequence[tuple[str, str]],
        *,
        current: str | None = None,
        tones: Mapping[str, str] | None = None,
        mono: bool = False,
        icons: Mapping[str, str] | None = None,
        roving: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(q.SEGMENTED)
        self._roving = roving
        self._icons: dict[str, IconLabel] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}
        self._compact = False
        for key, label in items:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kitSegment", True)
            button.setAccessibleName(label)
            button.setProperty("mono", mono)
            if tones and key in tones:
                button.setProperty("tone", tones[key])
            if icons and key in icons:
                button.setProperty("withIcon", True)   # the segment makes room for it
                self._icons[key] = IconLabel(icons[key], 17, button)
                self._icons[key].setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self._icons[key].move(9, 6)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)      # the ring shows for the keyboard, not for a click
            button.clicked.connect(lambda _checked=False, k=key: self._on_clicked(k))
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

    def _on_clicked(self, key: str) -> None:
        self._settle()
        self.changed.emit(key)

    def current(self) -> str | None:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return None

    def set_current(self, key: str | None) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
        self._settle()

    def _settle(self) -> None:
        """What follows the current segment: its icon's color, and the segment that is in the tab order."""
        current = self.current()
        for key, button in self._buttons.items():
            if key in self._icons:
                set_property(self._icons[key], "segment", "off" if key != current else button.property("tone") or "on")
            if self._roving:
                button.setFocusPolicy(Qt.FocusPolicy.TabFocus if key == current else Qt.FocusPolicy.NoFocus)

    def current_button(self) -> QPushButton | None:
        key = self.current()
        return None if key is None else self._buttons[key]

    def focus_current(self) -> None:
        if (button := self.current_button()) is not None:
            button.setFocus(Qt.FocusReason.TabFocusReason)

    def set_labels(self, labels: Mapping[str, str], *, tooltips: Mapping[str, str] | None = None,
                   compact: bool = False) -> None:
        """Relabel existing segments, preserving selection, signals and badges.

        `compact` also drops the native style's minimum text-button width.
        """
        self._compact = compact
        for key, label in labels.items():
            self._buttons[key].setText(label)
            self._buttons[key].setToolTip(tooltips.get(key, "") if tooltips else "")
            self._buttons[key].setAccessibleName(label or (tooltips.get(key, "") if tooltips else ""))
            self._fit_button(key)

    def _fit_button(self, key: str) -> None:
        button = self._buttons[key]
        width = 16777215   # Qt's default maximum widget width
        if self._compact:
            button.ensurePolished()
            option = QStyleOptionButton()
            button.initStyleOption(option)
            option.text = ""   # keep the style's padding, without its minimum for text buttons
            contents = button.fontMetrics().size(Qt.TextFlag.TextSingleLine, button.text())
            if button.property("badge"):
                contents.setWidth(contents.width() + self._badges[key].sizeHint().width() + 4)
            width = button.style().sizeFromContents(QStyle.ContentsType.CT_PushButton,
                                                   option, contents, button).width()
        button.setMaximumWidth(width)

    def set_badge(self, key: str, count: int) -> None:
        """A small red count on a segment ("2" lint errors); 0 hides it."""
        badge, button = self._badges[key], self._buttons[key]
        badge.setText("99+" if count > 99 else str(count))
        button.setProperty("badge", count > 0)   # the segment makes room for it
        _repolish(button)
        self._fit_button(key)
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
        elif self._roving and event.type() == QEvent.Type.KeyPress and obj in self._buttons.values():
            keys = list(self._buttons)
            step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(event.key())
            if step is not None:
                self._buttons[keys[(keys.index(self._key_of(obj)) + step) % len(keys)]].click()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                obj.click()
                return True
        return super().eventFilter(obj, event)

    def _key_of(self, button: QObject) -> str:
        return next(key for key, b in self._buttons.items() if b is button)


class Chip(ClickFrame):
    """Small pill with an optional icon, e.g. "pinned 1-0-0" or "outdated".
    tone: neutral, muted, info, warning, error, ok. Emits `clicked`."""

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
        set_property(self, "tone", tone)


class ToggleChip(QPushButton):
    """A pill that switches on and off, e.g. one of the views a slide "Appears in". `tone` is a view
    ("instructor", "during", "after"): on, the chip takes that view's colors. It is a checkable
    button: `isChecked`, `setChecked` and `toggled` as usual."""

    def __init__(self, text: str, tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(q.TOGGLE_CHIP)
        self.setProperty("tone", tone)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class RowButton(ClickFrame):
    """A clickable row for a choice with a name and a second line: a project of the picker, an action
    of the "No decks" page. Emits `clicked` unless disabled; `chip` is (text, tone) or empty."""

    def __init__(self, icon: str, title: str, sub: str = "", *, mono_sub: bool = False,
                 chip: tuple[str, str] = ("", ""), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.ROW_BUTTON)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(12)
        layout.addWidget(IconLabel(icon, 22))
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QLabel(title)
        name.setObjectName(q.ROW_NAME)
        texts.addWidget(name)
        self.sub = QLabel(sub)
        self.sub.setObjectName(q.PANEL_MONO if mono_sub else q.PANEL_CAPTION)
        self.sub.setWordWrap(True)
        texts.addWidget(self.sub)
        layout.addLayout(texts, 1)
        self.chip = Chip(*chip) if chip[0] else None
        if self.chip is not None:
            layout.addWidget(self.chip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Field(Surface):
    """A control under its label: the form row of sheets ("Title", "Load as")."""

    def __init__(self, label: str, control: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel(label)
        self.label.setObjectName(q.FIELD_LABEL)
        layout.addWidget(self.label)
        layout.addWidget(control)


class ThumbnailGrid(Surface):
    """Exclusive choice among pictures with a caption, e.g. the frame gallery.

    items: (key, caption, image file) triples; a file that is missing leaves the
    picture empty. `chosen` is emitted with the key for user clicks only, like
    SegmentedControl.changed."""

    chosen = Signal(str)
    PICTURE = (112, 63)   # 16:9

    def __init__(self, items: Sequence[tuple[str, str, Path]], *, columns: int = 5, current: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._tiles: dict[str, ClickFrame] = {}
        for index, (key, caption, image) in enumerate(items):
            tile = ClickFrame()
            tile.setObjectName(q.THUMB)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolTip(caption)
            tile.clicked.connect(lambda k=key: self._on_click(k))
            layout = QVBoxLayout(tile)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(4)
            picture = QLabel()
            picture.setFixedSize(*self.PICTURE)
            picture.setScaledContents(True)
            picture.setPixmap(QPixmap(str(image)))
            layout.addWidget(picture)
            name = QLabel(caption)
            name.setObjectName(q.THUMB_CAPTION)
            layout.addWidget(name)
            grid.addWidget(tile, index // columns, index % columns)
            self._tiles[key] = tile
        self.set_current(current if current is not None else (items[0][0] if items else None))

    def _on_clicked(self, key: str) -> None:
        self._settle()
        self.changed.emit(key)

    def current(self) -> str | None:
        return next((key for key, tile in self._tiles.items() if tile.property("current")), None)

    def set_current(self, key: str | None) -> None:
        for name, tile in self._tiles.items():
            set_property(tile, "current", name == key)

    def _on_click(self, key: str) -> None:
        self.set_current(key)
        self.chosen.emit(key)


class MenuRow(QWidget):
    """One row of a menu or of the command palette: icon, text (with a muted second line `detail`)
    and a metadata column. `activated(key)` on click; the owner marks the current row."""

    activated = Signal(str)
    hovered = Signal(object)

    def __init__(self, key: str, text: str, meta: str, icon: str, tone: str, show_icon_slot: bool,
                 swatch: str, detail: str = "") -> None:
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
        if detail:
            lines = QVBoxLayout()
            lines.setSpacing(1)
            lines.addWidget(label)
            second = QLabel(detail)
            second.setObjectName(q.MENU_META)
            second.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # clipped, not widening
            lines.addWidget(second)
            layout.addLayout(lines, 1)
        else:
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
    widget in `focus_target` (else the popover itself) gets the keyboard.

    `inline` makes it a child of its parent's window instead of a popup window: it stays where the compositor
    cannot move it, and a QComboBox inside it works like anywhere. Then the click outside and Esc are watched
    here: a click outside calls `dismiss()` unless `dismiss_outside` is False (a click on the anchor is left to
    the anchor), and Esc calls `escape()`; both close it by default. The Tab key stays inside it, and a close by
    Esc or by one of its buttons (`close_and_return`) gives the keyboard back to `focus_return`, else to the widget
    that had it when the popover opened, else to the anchor."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 220, inline: bool = False,
                 dismiss_outside: bool = True) -> None:
        if inline:
            super().__init__(parent.window() if parent is not None else None)
        else:
            super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName(q.MENU)
        self.setMinimumWidth(min_width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(4, 4, 4, 4)
        self.body.setSpacing(0)
        self.focus_target: QWidget | None = None
        self.focus_return: QWidget | None = None     # where the keyboard goes back to when it closes by Esc or a button
        self._inline, self._dismiss_outside = inline, dismiss_outside
        self._anchor: QWidget | None = None
        self._came_from: QWidget | None = None
        if inline:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.hide()

    def _prepare(self) -> None:
        """Called before the popup is positioned: build what is shown."""

    def popup_at(self, global_pos: QPoint) -> None:
        self._prepare()
        self._show_at(global_pos)

    def _show_at(self, global_pos: QPoint) -> None:
        self.adjustSize()
        if self._inline:
            window = self.parentWidget()
            point = window.mapFromGlobal(global_pos)
            self.move(max(0, min(point.x(), window.width() - self.width())), point.y())
            self.raise_()
            if not self.isVisible():
                self._came_from = QApplication.focusWidget()
            QApplication.instance().installEventFilter(self)
        else:
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
        self._anchor = anchor
        self._prepare()
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(anchor.width() - self.width() if align_right else 0, anchor.height() + 4))
        self._show_at(point)

    def dismiss(self) -> None:
        """A click outside an inline popover."""
        self.close()

    def escape(self) -> None:
        """Esc in an inline popover."""
        self.close_and_return()

    def close_and_return(self) -> None:
        """Close, and give the keyboard back to where it was."""
        self.close()
        for target in (self.focus_return, self._came_from, self._anchor):
            if target is not None and target.isVisible() and target.focusPolicy() != Qt.FocusPolicy.NoFocus:
                target.setFocus(Qt.FocusReason.OtherFocusReason)
                return

    def focusNextPrevChild(self, next: bool) -> bool:
        """Tab and Shift+Tab go round the widgets of an inline popover instead of leaving it."""
        focus = QApplication.focusWidget()
        if not (self._inline and self.isVisible() and focus is not None and (focus is self or self.isAncestorOf(focus))):
            return super().focusNextPrevChild(next)
        step = QWidget.nextInFocusChain if next else QWidget.previousInFocusChain
        candidate = step(focus)
        while candidate is not focus:
            if (candidate is not self and self.isAncestorOf(candidate) and candidate.isVisible() and candidate.isEnabled()
                    and candidate.focusPolicy() & Qt.FocusPolicy.TabFocus):
                candidate.setFocus(Qt.FocusReason.TabFocusReason if next else Qt.FocusReason.BacktabFocusReason)
                break
            candidate = step(candidate)
        return True

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """The click outside and Esc of an inline popover, seen by the whole application."""
        if event.type() == QEvent.Type.MouseButtonPress and self._dismiss_outside and isinstance(obj, QWidget):
            inside = obj is self or self.isAncestorOf(obj) or (
                self._anchor is not None and (obj is self._anchor or self._anchor.isAncestorOf(obj)))
            if not inside and obj.window() is self.window():
                self.dismiss()
        elif (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
              and QApplication.activePopupWidget() is None and obj.window() is self.window()):
            self.escape()
            return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._inline:
            QApplication.instance().removeEventFilter(self)
        self.closed.emit()


class PopoverMenu(Popover):
    """Popup list of actions with an optional right-hand metadata column
    (shortcut, count, date). `triggered(key)` fires on click or Enter, then
    the menu closes. Rows are added with add_item/add_header/add_separator
    before popup_below()/popup_at().

    add_column() starts a further column and add_footer() a footer row below the columns (items and a
    right-hand add_note()); then the menu is the compact columns layout, ↑/↓ move within a column or the
    footer and ←/→ switch between them. `focus_first` opens it with the first enabled item current."""

    triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 220, focus_first: bool = False) -> None:
        super().__init__(parent, min_width=min_width)
        self._layout = self.body
        self._rows: list[MenuRow] = []
        self._row_group: list[int] = []   # the column (the footer last) of each row
        self._current = -1
        self._focus_first = focus_first
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

    def add_column(self) -> None:
        self._entries.append(("column",))

    def add_footer(self) -> None:
        self._entries.append(("footer",))

    def add_note(self, text: str) -> None:
        """A caption at the right end of the footer."""
        self._entries.append(("note", text))

    def _build(self) -> None:
        clear_layout(self._layout)
        self._rows.clear()
        self._row_group.clear()
        self._current = -1
        columns = any(e[0] in ("column", "footer") for e in self._entries)
        set_property(self, "columns", columns)
        margin = 6 if columns else 4
        self._layout.setContentsMargins(margin, margin, margin, margin)
        # An icon slot is reserved for every row once any row has an icon.
        slot = any(e[0] == "item" and e[4] for e in self._entries)
        group, target, across, boxes = 0, self._layout, QHBoxLayout(), []
        if columns:
            across.setSpacing(4)
            self._layout.addLayout(across)
            target = self._add_box(across, QVBoxLayout, q.MENU_COLUMN, divided=False)
            boxes.append(target)
        for entry in self._entries:
            if entry[0] == "column":
                group += 1
                target = self._add_box(across, QVBoxLayout, q.MENU_COLUMN, divided=True)
                boxes.append(target)
            elif entry[0] == "footer":
                group += 1
                target = self._add_box(self._layout, QHBoxLayout, q.MENU_FOOTER)
            elif entry[0] == "header":
                header = QLabel(entry[1])
                header.setObjectName(q.MENU_HEADER)
                header.setIndent(0)   # the QSS padding is the whole inset, so the text lines up with the rows
                target.addWidget(header)
            elif entry[0] == "note":
                note = QLabel(entry[1])
                note.setObjectName(q.MENU_NOTE)
                target.addStretch(1)
                target.addWidget(note)
            elif entry[0] == "sep":
                sep = QFrame()
                sep.setObjectName(q.MENU_SEPARATOR)
                sep.setFixedHeight(1)
                target.addSpacing(5)
                target.addWidget(sep)
                target.addSpacing(5)
            else:
                _, key, text, meta, icon, tone, enabled, swatch = entry
                row = MenuRow(key, text, meta, icon, tone, slot, swatch)
                row.setEnabled(enabled)
                row.setProperty("off", not enabled)
                row.activated.connect(self._on_activated)
                row.hovered.connect(lambda r: self._set_current(self._rows.index(r)))
                target.addWidget(row)
                self._rows.append(row)
                self._row_group.append(group)
        for box in boxes:
            box.addStretch(1)   # the rows stay at the top of a column the other one makes taller

    @staticmethod
    def _add_box(parent: QLayout, kind: type, name: str, **properties: object) -> QLayout:
        """A framed column (in the row `parent`) or the footer (below it); returns its layout."""
        frame = QFrame()
        frame.setObjectName(name)
        for key, value in properties.items():
            set_property(frame, key, value)
        box = kind(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        parent.addWidget(frame, 1 if kind is QVBoxLayout else 0)
        return box

    def _on_activated(self, key: str) -> None:
        self.close()
        self.triggered.emit(key)

    def _set_current(self, index: int) -> None:
        if 0 <= self._current < len(self._rows):
            set_property(self._rows[self._current], "current", False)
        self._current = index
        if 0 <= index < len(self._rows):
            set_property(self._rows[index], "current", True)

    def _enabled(self) -> list[int]:
        return [i for i, r in enumerate(self._rows) if r.isEnabled()]

    def _step(self, delta: int) -> None:
        """The next enabled row in the current column, wrapping round; the first or last if none is current."""
        enabled = self._enabled()
        if 0 <= self._current < len(self._rows):
            enabled = [i for i in enabled if self._row_group[i] == self._row_group[self._current]]
        if not enabled:
            return
        later = [i for i in enabled if (i - self._current) * delta > 0]
        target = (later[0] if delta > 0 else later[-1]) if later else (enabled[0] if delta > 0 else enabled[-1])
        self._set_current(target)

    def _switch_column(self, delta: int) -> None:
        """The same position in the next (previous) column that has an enabled row, wrapping round."""
        if not 0 <= self._current < len(self._rows):
            return
        enabled = self._enabled()
        groups = sorted({self._row_group[i] for i in enabled})
        group = self._row_group[self._current]
        if len(groups) < 2 or group not in groups:
            return
        own = [i for i in enabled if self._row_group[i] == group]
        there = [i for i in enabled if self._row_group[i] == groups[(groups.index(group) + delta) % len(groups)]]
        self._set_current(there[min(own.index(self._current) if self._current in own else 0, len(there) - 1)])

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._step(1)
        elif key == Qt.Key.Key_Up:
            self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._switch_column(1)
        elif key == Qt.Key.Key_Left:
            self._switch_column(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and 0 <= self._current < len(self._rows):
            self._on_activated(self._rows[self._current].key)
        else:
            super().keyPressEvent(event)

    def _prepare(self) -> None:
        self._build()
        if self._focus_first:
            self._step(1)


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
        if self._menu is not None and shiboken6.isValid(self._menu):
            self._menu.closed.disconnect(self._on_menu_closed)
        self._menu = menu
        menu.closed.connect(self._on_menu_closed)

    def _on_menu_closed(self) -> None:
        self._caret.setText("expand_more")

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
        clear_layout(self._layout)
        self._layout.addWidget(QLabel(text))
        for key, label in actions:
            button = QPushButton(label)
            button.setObjectName(q.TOAST_ACTION)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, k=key: self._on_action(k))
            self._layout.addWidget(button)
        set_property(self, "error", error)
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


class ModeBadge(QFrame):
    """The read-only route pill under a dialog's title (workspace v6 handoff, section 6): an icon and "Local ·
    Ollama" or "Cloud · Claude Code", amber on Cloud. The dialog has no route picker of its own: the switch in the
    top bar is the one place to change it, and the tooltip says so."""

    TIP = "Change it with the switch in the top bar"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(q.MODE_BADGE)
        self.setToolTip(self.TIP)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(5)
        self.icon = IconLabel("computer", 14)
        layout.addWidget(self.icon)
        self.label = QLabel()
        self.label.setObjectName(q.MODE_BADGE_TEXT)
        layout.addWidget(self.label)

    def set_route(self, name: str, cloud: bool) -> None:
        self.icon.set_icon("cloud" if cloud else "computer")
        self.label.setText(name)
        self.setAccessibleName(f"AI route: {name}")
        self.setAccessibleDescription(self.TIP)
        set_property(self, "cloud", cloud)

    def text(self) -> str:
        return self.label.text()


class ModalSheet(QDialog):
    """Modal dialog with a title, optional tabs and a button row.

    add_tab(label, widget) fills the body; with a single tab the tab bar is
    hidden. add_button(text, kind=..., role="accept"|"reject") appends to the
    footer; roles close the dialog with accept()/reject(). A plain QDialog
    frame is used (no custom frameless chrome): the window manager draws the
    shadow, which is reliable on every platform. `tab_changed` carries the new tab's index."""

    tab_changed = Signal(int)

    def __init__(self, title: str, parent: QWidget | None = None, *, width: int = 640) -> None:
        super().__init__(parent)
        self.setObjectName(q.SHEET)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self._root = root = QVBoxLayout(self)
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
        self._tabs.currentChanged.connect(self.tab_changed)

    def set_title(self, title: str) -> None:
        self._title.setText(title)
        self.setWindowTitle(title)

    def add_under_title(self, widget: QWidget) -> None:
        """A small widget (a badge) on its own line under the title, at the left."""
        self._root.insertWidget(1, widget, 0, Qt.AlignmentFlag.AlignLeft)

    def add_tab(self, label: str, widget: QWidget) -> int:
        self._tabs.addTab(label)
        index = self._stack.addWidget(widget)
        self._tabs.setVisible(self._tabs.count() > 1)
        return index

    def set_current_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    def current_tab(self) -> int:
        return self._tabs.currentIndex()

    def add_footer_note(self, widget: QWidget) -> None:
        """A widget at the left of the footer, in the room the buttons leave (a summary of
        what the primary button will do)."""
        self._footer.insertWidget(0, widget, 100)

    def add_button(self, text: str, *, kind: str = "secondary", role: str | None = None) -> Button:
        button = Button(text, kind)
        if role == "accept":
            button.clicked.connect(self.accept)
        elif role == "reject":
            button.clicked.connect(self.reject)
        self._footer.addWidget(button)
        return button
