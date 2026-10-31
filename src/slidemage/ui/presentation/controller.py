# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs a presentation: picks the screens, opens the windows, maps keys, the wheel and clicks to the session."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QLocale, QObject, QRect, QTime, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QScreen
from PySide6.QtWidgets import (QColorDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QSlider,
                               QToolButton, QWidget, QWidgetAction)

from ...presentation import layout
from ...presentation.frame_map import FrameMap
from ...presentation.keep_awake import KeepAwake
from ...presentation.pdf_source import NOTES, SLIDE, PresentationDeck
from ...presentation.screens import ScreenInfo, choose_screens
from ...presentation.session import TOOL_ERASER, TOOL_PEN, PresentationSession
from ...presentation.settings import PresentationSettings
from ...presentation.timer import PresentationTimer
from .audience_window import AudienceWindow, PresenterWindow
from .layout_view import build_layout
from .slide_canvas import SlideCanvas
from .slide_input import SlideInput
from .timer_widget import TimerButton
from .views import AudienceView, CurrentView, NextView, NotesView

WHEEL_STEP = 120
# A tool that is switched on (pen, eraser, black, freeze) is lit, so the state is clear at a glance.
ACTIVE_STYLE = "QToolButton:checked { background: #1976d2; color: #ffffff; font-weight: bold; }"
# The addresses a click on a slide opens (QDesktopServices hands them to the system's handler): web pages, mail and
# map locations (geo:, the link of a QR code for a place: qr_code.link_target; Windows opens it in Maps). Files,
# javascript: and other schemes that could start a program or read local data stay closed.
ALLOWED_SCHEMES = ("http", "https", "mailto", "geo")
Key = Qt.Key
NEXT_KEYS = {Key.Key_Right, Key.Key_Down, Key.Key_PageDown, Key.Key_Space, Key.Key_Return, Key.Key_Enter}
PREVIOUS_KEYS = {Key.Key_Left, Key.Key_Up, Key.Key_PageUp, Key.Key_Backspace}
DIGITS = {getattr(Key, f"Key_{n}"): str(n) for n in range(10)}


def screen_infos(screens: list[QScreen]) -> list[tuple[ScreenInfo, QScreen]]:
    primary = QGuiApplication.primaryScreen()
    return [(ScreenInfo(s.name(), s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height(),
                        s.serialNumber(), s is primary), s) for s in screens]


class PresentationController(QObject):
    finished = Signal()
    typing_changed = Signal()      # the number being typed for "go to slide" changed

    def __init__(self, deck: PresentationDeck, settings: PresentationSettings, *,
                 screens: Optional[list[tuple[ScreenInfo, Optional[QScreen]]]] = None,
                 main_screen: Optional[QScreen] = None, start_page: int = 0, frames: Optional[FrameMap] = None,
                 keep_awake: Optional[KeepAwake] = None, timer: Optional[PresentationTimer] = None,
                 save_settings: Optional[Callable[[PresentationSettings], None]] = None,
                 confirm: Optional[Callable[[QWidget, str], bool]] = None,
                 open_uri: Callable[[str], None] = lambda uri: QDesktopServices.openUrl(QUrl(uri))) -> None:
        super().__init__()
        self.deck, self.settings, self.frames = deck, settings, frames
        # What is saved: the pen set in the presenter window changes `settings` for this presentation only.
        self._stored = replace(settings)
        self.session = PresentationSession(deck.page_count, start_page, self)
        self.timer = timer or PresentationTimer()
        self.keep_awake = keep_awake if keep_awake is not None else KeepAwake()
        self._save_settings, self._confirm, self._open_uri = save_settings, confirm or self._ask, open_uri
        self._screens = screens if screens is not None else screen_infos(QGuiApplication.screens())
        self._main_screen = main_screen
        self.presenter: Optional[PresenterWindow] = None
        self.audience: Optional[AudienceWindow] = None
        self.plan = None
        self.profile = layout.profile_named(settings.profile)
        self.ended = False
        self._digits = ""
        self._wheel = 0
        self.session.page_changed.connect(self._page_changed)
        self.session.link_requested.connect(self._link)

    # -- opening and closing ----------------------------------------------------------

    @property
    def dual(self) -> bool:
        return self.plan is not None and self.plan.audience is not None

    def start(self) -> None:
        infos = [info for info, _screen in self._screens]
        main = next((i for i, (_info, screen) in enumerate(self._screens)
                     if screen is not None and screen is self._main_screen), -1)
        self.plan = choose_screens(infos, main, self.settings.audience_screen)
        self.keep_awake.start()
        audience_info, audience_screen = self._screens[self.plan.audience if self.dual else self.plan.presenter]
        self.audience = AudienceWindow(self, self._canvas(AudienceView(self.session), SLIDE, interactive=not self.dual),
                                       interactive=not self.dual)
        if self.dual:
            presenter_info, presenter_screen = self._screens[self.plan.presenter]
            self.presenter = PresenterWindow(self, self._build_profile)
            self.presenter.apply_profile(self.profile)
            self._place(self.presenter, presenter_info, presenter_screen, fullscreen=False)
        self._place(self.audience, audience_info, audience_screen, fullscreen=True)
        if not self.dual:
            self.audience.show_toast("Only one screen: showing the slide full-screen. Esc ends the presentation.")
        (self.presenter if self.dual else self.audience).setFocus()

    @staticmethod
    def _place(window: QWidget, info: ScreenInfo, screen: Optional[QScreen], fullscreen: bool) -> None:
        window.setGeometry(QRect(*info.geometry))
        window.create()
        if screen is not None and window.windowHandle() is not None:
            window.windowHandle().setScreen(screen)    # Wayland honours this one, not a position
        window.showFullScreen() if fullscreen else window.showMaximized()
        window.activateWindow()

    def end(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.keep_awake.stop()
        self.session.set_pointer(None)
        for window in (self.presenter, self.audience):
            if window is not None:
                window.close()
                window.deleteLater()
        self.presenter = self.audience = None
        self.deck.close()
        self.finished.emit()

    # -- the widgets ------------------------------------------------------------------

    def _canvas(self, view, part: str, *, interactive: bool = False, background: str = "#000000",
                empty_text: str = "", top: bool = False) -> SlideCanvas:
        slide_input = SlideInput(self.session, self.deck, self.settings) if interactive else None
        canvas = SlideCanvas(self.deck, view, part=part, laser_color=self.settings.laser_color,
                             laser_size=self.settings.laser_size, background=background, empty_text=empty_text, top=top, slide_input=slide_input)
        self.session.changed.connect(canvas.update)
        return canvas

    def _build_profile(self, profile: layout.Profile) -> QWidget:
        return build_layout(profile, self._element)

    def _element(self, name: str) -> QWidget:
        session = self.session
        if name == "current":
            return self._canvas(CurrentView(session), SLIDE, interactive=True, background="#101010")
        if name == "next":
            return self._canvas(NextView(session), SLIDE, background="#101010", empty_text="End of presentation")
        if name == "notes":
            return self._canvas(NotesView(session), NOTES, background="#ffffff", top=True,
                                empty_text="" if self.deck.has_notes else "No notes in this PDF.\nCompile the Presenter version to see notes.")
        if name == "counter":
            label = QLabel()
            session.changed.connect(lambda: label.setText(self.counter_text()))
            self.typing_changed.connect(lambda: label.setText(self.counter_text()))
            label.setText(self.counter_text())
            return label
        if name == "clock":
            label = QLabel()
            tick = QTimer(label)
            tick.timeout.connect(lambda: label.setText(self._clock_text()))
            tick.start(1000)
            label.setText(self._clock_text())
            return label
        if name == "timer":
            return TimerButton(self.timer, self.settings)
        return self._toolbar()

    def counter_text(self) -> str:
        """"Slide n / N · step k / K" (from the .nav file), else "Page n / N"; the number being typed instead
        while there is one."""
        if self._digits:
            return f"Go to {self.number_word()} {self._digits}  (Enter)"
        if self.frames is None:
            return f"Page {self.session.page + 1} / {self.session.page_count}"
        slide, step, steps = self.frames.frame_of(self.session.page)
        return f"Slide {slide} / {self.frames.count} · step {step} / {steps}"

    def number_word(self) -> str:
        """What a typed number means: the slide number printed in the footer, or (no .nav data) the PDF page."""
        return "slide" if self.frames is not None else "page"

    def _set_digits(self, digits: str) -> None:
        if digits != self._digits:
            self._digits = digits
            self.typing_changed.emit()

    def _clock_text(self) -> str:
        fmt = self.settings.clock_format
        if fmt == "system":
            return QLocale().toString(QTime.currentTime(), QLocale.FormatType.ShortFormat)
        return datetime.now().strftime("%I:%M %p").lstrip("0") if fmt == "12" else datetime.now().strftime("%H:%M")

    def _toolbar(self) -> QWidget:
        session = self.session
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        bar.setStyleSheet(ACTIVE_STYLE)

        def button(text: str, tip: str, action: Callable[[], None],
                   checked: Optional[Callable[[], bool]] = None) -> QToolButton:
            tool = QToolButton()
            tool.setText(text)
            tool.setToolTip(tip)
            tool.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            def clicked() -> None:
                action()
                if checked is not None:
                    tool.setChecked(checked())      # a click must not flip the lit state on its own
            tool.clicked.connect(clicked)
            if checked is not None:
                tool.setCheckable(True)
                tool.setChecked(checked())
                session.changed.connect(lambda: tool.setChecked(checked()))
            row.addWidget(tool)
            return tool

        def pen_clicked() -> None:
            session.set_tool(TOOL_PEN)
            self._pen_menu(pen).popup(pen.mapToGlobal(pen.rect().bottomLeft()))

        pen = button("Pen", "Draw (D); opens the pen's colour and width for this presentation",
                     pen_clicked, lambda: session.tool == TOOL_PEN)
        button("Eraser", "Erase strokes (E)", lambda: session.set_tool(TOOL_ERASER), lambda: session.tool == TOOL_ERASER)
        button("Clear", "Clear the drawings of this page (Delete; Shift: all pages)", self.clear_drawings)
        button("Black", "Black out the projector (B)", session.toggle_black, lambda: session.black)
        button("Freeze", "Freeze the projector on this slide (F)", self.toggle_freeze, lambda: session.frozen)
        button("Profile", "Next layout (P)", self.next_profile)
        button("End", "End the presentation (Esc)", self.end)
        return bar

    def _pen_menu(self, parent: QWidget) -> QMenu:
        """Colour and width of the pen. They change the settings of this presentation only; the saved ones (the
        Settings sheet) are not touched."""
        menu = QMenu(parent)
        panel = QWidget()
        column = QHBoxLayout(panel)
        column.addWidget(QLabel("Pen"))
        swatch = QPushButton("Colour")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(2, 50)                                     # tenths of a percent of the slide height
        slider.setValue(round(self.settings.pen_width * 1000))
        slider.setFixedWidth(140)
        size = QLabel()

        def paint() -> None:
            color = QColor(self.settings.pen_color)
            swatch.setStyleSheet(f"border-left: 22px solid {color.name()}; padding: 3px 8px;")
            size.setText(f"{slider.value() / 10:g} %")

        def pick() -> None:
            color = QColorDialog.getColor(QColor(self.settings.pen_color), panel, "Pen colour",
                                          QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if color.isValid():
                self.settings.pen_color = color.name(QColor.NameFormat.HexArgb)
                paint()

        def resize(value: int) -> None:
            self.settings.pen_width = value / 1000
            paint()
        swatch.clicked.connect(pick)
        slider.valueChanged.connect(resize)
        for widget in (swatch, slider, size):
            column.addWidget(widget)
        paint()
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        menu.setToolTipsVisible(True)
        menu.setToolTip("For this presentation only; the Settings sheet keeps its own pen.")
        return menu

    # -- actions ----------------------------------------------------------------------

    def clear_drawings(self, everything: Optional[bool] = None) -> None:
        shift = bool(QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        (self.session.clear_all if (shift if everything is None else everything) else self.session.clear_page)()

    def toggle_freeze(self) -> None:
        if not self.dual:
            return self._toast("Freeze needs a second screen: the projector and your view are the same here.")
        self.session.toggle_freeze()

    def next_profile(self) -> None:
        if not self.dual:
            return
        names = [p.name for p in layout.BUILTINS]
        position = names.index(self.profile.name) if self.profile.name in names else -1
        self.profile = layout.BUILTINS[(position + 1) % len(layout.BUILTINS)]
        self.settings.profile = self._stored.profile = self.profile.name
        self.presenter.apply_profile(self.profile)
        if self._save_settings is not None:
            self._save_settings(self._stored)

    def _toast(self, text: str, milliseconds: int = 4000) -> None:
        window = self.presenter or self.audience
        if window is not None:
            window.show_toast(text, milliseconds)

    def _page_changed(self, page: int) -> None:
        if (self.settings.timer_start_on_navigation and self.timer.mode == "duration" and not self.timer.running
                and self.timer.remaining() is not None and page > 0):
            self.timer.start()

    def _ask(self, parent: QWidget, uri: str) -> bool:
        return QMessageBox.question(parent, "Open link", f"Open this address?\n\n{uri}") == QMessageBox.StandardButton.Yes

    def _link(self, uri: str) -> None:
        scheme = uri.split(":", 1)[0].lower()
        if scheme not in ALLOWED_SCHEMES:
            return self._toast(f"Links to {scheme or 'files'} are not opened from a presentation.")
        if self.settings.confirm_links and not self._confirm(self.presenter or self.audience, uri):
            return
        self._open_uri(uri)

    # -- input ------------------------------------------------------------------------

    def key_press(self, event) -> bool:
        key, mods, session = event.key(), event.modifiers(), self.session
        ctrl, shift, alt = (bool(mods & m) for m in (Qt.KeyboardModifier.ControlModifier,
                                                      Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier))
        if key in DIGITS and not (ctrl or alt):
            self._set_digits((self._digits + DIGITS[key])[-4:])
            self._toast(f"Go to {self.number_word()} {self._digits}  (Enter)", 1500)
            return True
        if key in (Key.Key_Return, Key.Key_Enter) and self._digits:
            number = int(self._digits)
            self._set_digits("")
            session.goto(self.frames.first_page(number) if self.frames is not None else number - 1)
            return True
        self._set_digits("")
        if key == Key.Key_Escape:
            self.end()
        elif key == Key.Key_Left and alt:
            session.back()
        elif key in NEXT_KEYS:
            session.next()
        elif key in PREVIOUS_KEYS:
            session.previous()
        elif key == Key.Key_Home:
            session.first()
        elif key == Key.Key_End:
            session.last()
        elif key in (Key.Key_B, Key.Key_Period):
            session.toggle_black()
        elif key == Key.Key_F:
            self.toggle_freeze()
        elif key == Key.Key_D:
            session.set_tool(TOOL_PEN)
        elif key == Key.Key_E:
            session.set_tool(TOOL_ERASER)
        elif key == Key.Key_Delete:
            self.clear_drawings(shift)
        elif key == Key.Key_Z and ctrl:
            session.undo_stroke()
        elif key == Key.Key_T:
            self.timer.reset() if shift else self.timer.toggle()
        elif key == Key.Key_P:
            self.next_profile()
        else:
            return False
        return True

    def wheel(self, event) -> None:
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= WHEEL_STEP:
            if self._wheel > 0:       # wheel up: back
                self.session.previous()
                self._wheel -= WHEEL_STEP
            else:
                self.session.next()
                self._wheel += WHEEL_STEP
