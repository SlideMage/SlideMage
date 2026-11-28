# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Presentation windows and controls with simulated offscreen monitors."""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from conftest import pause
from presentation_fixtures import JUMP_SPOT, URI_SPOT, make_pdf
from slidemage.presentation import layout
from slidemage.presentation.keep_awake import KeepAwake
from slidemage.presentation.pdf_source import PresentationDeck
from slidemage.presentation.screens import ScreenInfo
from slidemage.presentation.session import TOOL_ERASER, TOOL_PEN
from slidemage.presentation.settings import PresentationSettings
from slidemage.ui.presentation.controller import PresentationController
from slidemage.ui.presentation.slide_canvas import SlideCanvas
from slidemage.ui.presentation.timer_widget import TimerButton
from slidemage.ui.presentation.views import AudienceView, CurrentView

LAPTOP = ScreenInfo("laptop", 0, 0, 1280, 720, primary=True)
PROJECTOR = ScreenInfo("projector", 1280, 0, 1280, 720)
LEFT = Qt.MouseButton.LeftButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier


class Backend:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")


@pytest.fixture
def make(tmp_path, qapp):
    made = []

    def build(*, two_screens=True, two_up=True, settings=None, **extra):
        deck = PresentationDeck(make_pdf(tmp_path / f"d{len(made)}.pdf", two_up=two_up))
        screen = qapp.primaryScreen()
        screens = [(LAPTOP, screen), (PROJECTOR, screen)] if two_screens else [(LAPTOP, screen)]
        backend = Backend()
        opened = []
        controller = PresentationController(
            deck, settings or PresentationSettings(), screens=screens, main_screen=screen,
            keep_awake=KeepAwake(backend), open_uri=opened.append, confirm=lambda _w, _u: True, **extra)
        controller.backend, controller.opened = backend, opened
        made.append(controller)
        controller.start()
        return controller

    yield build
    for controller in made:
        controller.end()


def current_canvas(controller):
    return next(canvas for canvas in controller.presenter.findChildren(SlideCanvas) if isinstance(canvas.view, CurrentView))


def spot(canvas, fraction):
    rect = canvas.target()
    return QPoint(int(rect.x() + fraction[0] * rect.width()), int(rect.y() + fraction[1] * rect.height()))


def press_key(controller, key, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(controller.presenter or controller.audience, key, modifier)


def test_keys_clicker_keys_digits_and_the_wheel_navigate(make):
    controller = make(two_up=False)
    session = controller.session
    assert any(c.empty_text.startswith("No notes") for c in controller.presenter.findChildren(SlideCanvas))
    for key, page in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_PageDown, 2), (Qt.Key.Key_Space, 3), (Qt.Key.Key_Left, 2),
                      (Qt.Key.Key_PageUp, 1), (Qt.Key.Key_Up, 0), (Qt.Key.Key_Down, 1), (Qt.Key.Key_End, 5),
                      (Qt.Key.Key_Home, 0)):
        press_key(controller, key)
        assert session.page == page, key
    press_key(controller, Qt.Key.Key_4)
    assert session.page == 0 and controller.counter_text().startswith("Go to page 4")
    press_key(controller, Qt.Key.Key_Return)
    assert session.page == 3 and controller.counter_text() == "Page 4 / 6"
    for delta, page in ((-120, 4), (-120, 5), (120, 4), (60, 4), (60, 3)):
        controller.wheel(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
                                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                     Qt.ScrollPhase.NoScrollPhase, False))
        assert session.page == page, delta


def test_black_and_dot_alias_and_freeze_with_their_badge(make):
    controller = make()
    session = controller.session
    current = current_canvas(controller)
    press_key(controller, Qt.Key.Key_B)
    assert session.black and current.view.status()[0] == "PROJECTOR BLACK"
    press_key(controller, Qt.Key.Key_Period)
    assert not session.black
    press_key(controller, Qt.Key.Key_F)
    press_key(controller, Qt.Key.Key_Right)
    assert session.frozen and session.page == 1 and session.audience_page == 0
    assert current.view.status() == ("PROJECTOR FROZEN: page 1", "frozen")
    press_key(controller, Qt.Key.Key_F)
    assert session.audience_page == 1 and current.view.status() is None


def test_escape_ends_the_presentation_at_once_and_lets_the_computer_sleep_again(make):
    controller = make()
    finished = []
    controller.finished.connect(lambda: finished.append(True))
    press_key(controller, Qt.Key.Key_5)
    press_key(controller, Qt.Key.Key_Escape)
    assert finished == [True] and controller.presenter is None and controller.audience is None
    assert controller.backend.calls == ["start", "stop"]
    controller.end()
    assert finished == [True]


def test_a_plain_click_follows_links_but_ctrl_click_does_not(make):
    controller = make()
    current = current_canvas(controller)
    QTest.mouseClick(current, LEFT, CTRL, spot(current, JUMP_SPOT))
    assert controller.session.page == 0
    QTest.mouseClick(current, LEFT, NO_MODIFIER, spot(current, JUMP_SPOT))
    assert controller.session.page == 3
    assert controller.session.back() and controller.session.page == 0
    QTest.mouseClick(current, LEFT, NO_MODIFIER, spot(current, URI_SPOT))
    assert controller.opened == ["https://example.org/x"]


def test_external_links_require_confirmation_and_a_supported_scheme(make):
    from slidemage import qr_code
    from slidemage.qr_code import QRSpec

    controller = make()
    answers = []
    controller._confirm = lambda _w, uri: answers.append(uri) or False
    controller.session.request_link("https://example.org/a")
    assert answers == ["https://example.org/a"] and controller.opened == []

    controller._confirm = lambda _w, uri: True
    geo = qr_code.link_target(QRSpec("location", {"place": "47.0707, 15.4395", "map_link": qr_code.LINK_GEO}))
    allowed = ["mailto:a@b.org", geo, "GEO:0,0?q=Graz"]
    assert geo.startswith("geo:")
    for uri in allowed + ["file:///etc/passwd", "file:///C:/Windows/System32/calc.exe", "javascript:alert(1)",
                          "ms-settings:privacy", "geoplugin:x", "C:\\Windows\\notepad.exe", "smb://host/share"]:
        controller.session.request_link(uri)
    assert controller.opened == allowed


def test_pen_and_laser_follow_the_slide_on_both_screens(make):
    controller = make(settings=PresentationSettings(pen_color="#ffff0000", pen_width=0.08))
    controller.presenter.resize(900, 640)
    controller.audience.resize(1000, 800)
    pause(10)
    session = controller.session
    current = current_canvas(controller)
    audience = controller.audience.canvas
    assert current.target().size() != audience.target().size()
    assert all(not c.grab().isNull() for c in controller.presenter.findChildren(SlideCanvas))

    press_key(controller, Qt.Key.Key_D)
    start = spot(current, (0.2, 0.5))
    outside = spot(current, (1.0, 0.5)) + QPoint(60, 0)
    QTest.mousePress(current, LEFT, NO_MODIFIER, start)
    QTest.mouseMove(current, spot(current, (0.8, 0.5)))
    QTest.mouseMove(current, outside)
    QTest.mouseRelease(current, LEFT, NO_MODIFIER, outside)
    [stroke] = session.strokes[0]
    assert max(x for x, _ in stroke.points) == 1.0
    for canvas in (current, audience):
        image = canvas.grab().toImage()
        for fraction, drawn in (((0.5, 0.5), True), ((0.25, 0.5), True), ((0.5, 0.9), False)):
            color = image.pixelColor(spot(canvas, fraction))
            assert (color.red() > 200 and color.green() < 60) == drawn, (canvas.view, fraction)

    at = spot(current, (0.5, 0.5))
    QTest.mousePress(current, LEFT, CTRL, at)
    assert session.pointer == pytest.approx((0.5, 0.5), abs=0.02)
    assert audience.view.pointer() is not None and session.strokes[0] == [stroke]
    QTest.mouseRelease(current, LEFT, CTRL, at)
    QTest.mouseMove(current, start)
    assert session.pointer is None
    press_key(controller, Qt.Key.Key_Right)
    press_key(controller, Qt.Key.Key_Left)
    assert session.strokes[0] == [stroke]
    press_key(controller, Qt.Key.Key_Delete)
    assert 0 not in session.strokes


def test_timer_controls_are_independent_of_the_wall_clock(make):
    controller = make(settings=PresentationSettings(clock_format="24"))
    [clock] = [label.text() for label in controller.presenter.findChildren(QLabel)
               if label.text().startswith("Current time: ")]
    assert clock.removeprefix("Current time: ").count(":") == 1
    controller.timer.set_duration(600)
    assert not controller.timer.running
    press_key(controller, Qt.Key.Key_Right)
    assert controller.timer.running
    press_key(controller, Qt.Key.Key_T)
    assert not controller.timer.running
    press_key(controller, Qt.Key.Key_T, Qt.KeyboardModifier.ShiftModifier)
    assert controller.timer.text() == "10:00"


def test_the_settings_tab_saves_each_change_and_resets(qapp):
    from slidemage.ui.presentation.settings_page import PresentationTab
    tab = PresentationTab()
    assert tab.minimumSizeHint().width() <= 700
    assert tab.eraser_size.value() == pytest.approx(2.0)
    tab.eraser_size.setValue(4.0)
    assert PresentationSettings.load().eraser_size == pytest.approx(0.04)
    tab.confirm_links.setChecked(False)
    tab.timer_minutes.setValue(30)
    tab.timer_mode.setCurrentIndex(tab.timer_mode.findData("duration"))
    tab.profile_combo.setCurrentText("Next large")
    tab.pen_width.setValue(2.0)
    saved = PresentationSettings.load()
    assert (saved.confirm_links, saved.timer_duration_minutes, saved.timer_mode, saved.profile, saved.pen_width) == (
        False, 30, "duration", "Next large", 0.02)
    assert tab.audience_screen.itemData(0) == "" and tab.audience_screen.count() >= 2
    tab._reset()
    assert PresentationSettings.load() == PresentationSettings()
    assert tab.confirm_links.isChecked() and tab.timer_minutes.value() == 45
    assert tab.eraser_size.value() == pytest.approx(2.0)


def test_a_typed_number_is_the_slide_number_when_the_nav_data_fits_else_the_page(make):
    from slidemage.presentation.frame_map import FrameMap
    controller = make(frames=FrameMap(((0, 0), (1, 3), (4, 4), (5, 5))))
    session = controller.session
    counter = [label for label in controller.presenter.findChildren(QLabel) if label.text().startswith("Slide")][0]
    assert counter.text() == "Slide 1 / 4 · step 1 / 1"
    press_key(controller, Qt.Key.Key_2)
    assert counter.text() == "Go to slide 2  (Enter)"
    press_key(controller, Qt.Key.Key_Return)
    assert session.page == 1 and counter.text() == "Slide 2 / 4 · step 1 / 3"       # the first step of slide 2
    press_key(controller, Qt.Key.Key_Right)
    assert counter.text() == "Slide 2 / 4 · step 2 / 3"
    press_key(controller, Qt.Key.Key_4)
    press_key(controller, Qt.Key.Key_Return)
    assert session.page == 5
    press_key(controller, Qt.Key.Key_9)
    press_key(controller, Qt.Key.Key_Return)
    assert session.page == 5                                               # beyond the last slide: the last one


def test_a_presentation_continued_at_a_slide_opens_there_on_both_screens(make):
    from slidemage.presentation.frame_map import FrameMap
    controller = make(frames=FrameMap(((0, 0), (1, 3), (4, 4), (5, 5))), start_page=4)
    counter = [label for label in controller.presenter.findChildren(QLabel) if label.text().startswith("Slide")][0]
    assert controller.session.page == 4 and counter.text() == "Slide 3 / 4 · step 1 / 1"


def test_changing_the_layout_leaves_no_updates_to_deleted_widgets(make, capfd):
    from PySide6.QtCore import QCoreApplication
    controller = make()
    for _ in range(3):                       # every profile change replaces the presenter's widgets
        controller.next_profile()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(4):
        controller.session.next()
        controller.session.set_tool(TOOL_PEN)
    err = capfd.readouterr().err
    assert "already deleted" not in err, err[-600:]
    counter = [label for label in controller.presenter.findChildren(QLabel) if label.text().startswith("Page")][0]
    assert counter.text() == "Page 5 / 6"


def test_the_big_clock_reads_hh_mm_and_its_font_grows_with_its_area(qapp):
    from datetime import datetime
    from slidemage.ui.presentation.big_clock import BigClock, clock_text
    assert clock_text(datetime(2026, 11, 6, 7, 5, 59)) == "07:05"
    assert clock_text(datetime(2026, 11, 6, 23, 59, 0)) == "23:59"
    clock = BigClock(now=lambda: datetime(2026, 11, 6, 9, 3, 30))
    assert clock.text() == "09:03"
    clock.show()                                                              # a hidden widget is not laid out
    clock.resize(300, 150)
    small = clock.font().pixelSize()
    clock.resize(900, 450)
    large = clock.font().pixelSize()
    assert large > 2 * small >= 16
    clock.resize(900, 100)                                                    # a flat area: the height limits it
    assert clock.font().pixelSize() < large
    assert clock._timer.isActive() and clock._timer.interval() <= 31_000      # wakes up for the next minute
    clock.close()


def test_the_profile_menu_applies_and_saves_layouts_with_different_canvases(make):
    from slidemage.ui.presentation.big_clock import BigClock

    saved = []
    controller = make(save_settings=lambda s: saved.append(s.profile))
    audience, presenter = controller.audience, controller.presenter
    assert controller.dual and presenter.isVisible() and audience.isVisible()
    assert audience.geometry().x() == PROJECTOR.x
    assert isinstance(audience.canvas.view, AudienceView) and not audience.canvas.name
    assert not audience.findChildren(TimerButton)
    assert all(not label.isVisible() for label in audience.findChildren(QLabel))
    current_layout = presenter.findChildren(SlideCanvas)
    assert sorted(type(c.view).__name__ for c in current_layout) == ["CurrentView", "NextView", "NotesView"]
    assert sorted(c.name for c in current_layout if c.name) == ["Current", "Next"]

    def actions():
        return controller._profile_menu(presenter).actions()

    assert [a.text() for a in actions()] == ["Current large", "Next large", "Mirror and clock"]
    assert [a.isChecked() for a in actions()] == [True, False, False]
    actions()[1].trigger()
    assert controller.profile.name == controller.settings.profile == "Next large"
    assert len(presenter.findChildren(SlideCanvas)) == 3
    assert [a.isChecked() for a in actions()] == [False, True, False]
    press_key(controller, Qt.Key.Key_P)
    assert controller.profile.name == "Mirror and clock"
    mirror_layout = presenter.findChildren(SlideCanvas)
    assert sorted(type(c.view).__name__ for c in mirror_layout) == ["NextView", "NotesView"]
    assert len(presenter.findChildren(BigClock)) == 1
    press_key(controller, Qt.Key.Key_Right)
    assert controller.session.page == 1
    press_key(controller, Qt.Key.Key_P)
    assert controller.profile.name == "Current large"
    assert saved == ["Next large", "Mirror and clock", "Current large"]
    presenter.close()
    assert controller.ended and controller.backend.calls == ["start", "stop"]


def test_the_projector_takes_the_mouse_while_the_layout_has_no_current_slide(make):
    controller = make()
    audience = controller.audience
    session = controller.session
    assert audience.canvas.input is None and audience.cursor().shape() == Qt.CursorShape.BlankCursor
    controller.set_profile(layout.NEXT_LARGE_CLOCK)
    assert audience.canvas.input is not None and audience.cursor().shape() != Qt.CursorShape.BlankCursor
    canvas = audience.canvas
    press_key(controller, Qt.Key.Key_D)
    start, end = spot(canvas, (0.3, 0.3)), spot(canvas, (0.6, 0.6))
    QTest.mousePress(canvas, LEFT, NO_MODIFIER, start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, LEFT, NO_MODIFIER, end)
    assert len(session.strokes[0]) == 1 and len(session.strokes[0][0].points) >= 2
    QTest.mousePress(canvas, LEFT, CTRL, start)
    assert session.pointer is not None
    QTest.mouseRelease(canvas, LEFT, CTRL, start)
    assert session.pointer is None
    controller.set_profile(layout.CURRENT_LARGE)                          # a current slide again: back to the blank cursor
    assert audience.canvas.input is None and audience.cursor().shape() == Qt.CursorShape.BlankCursor
    assert current_canvas(controller).input is not None
    n = len(session.strokes[0])
    QTest.mousePress(canvas, LEFT, NO_MODIFIER, start)
    QTest.mouseRelease(canvas, LEFT, NO_MODIFIER, end)
    assert len(session.strokes[0]) == n                                   # the projector no longer draws
    press_key(controller, Qt.Key.Key_P)
    press_key(controller, Qt.Key.Key_P)                                   # Next large, then Mirror and clock
    assert audience.canvas.input is not None


# Eraser size and circle

def test_eraser_slider_changes_what_a_press_erases_for_this_session(make):
    from PySide6.QtWidgets import QPushButton, QSlider

    controller = make(settings=PresentationSettings(eraser_size=0.02))
    session, canvas = controller.session, current_canvas(controller)
    menu = controller._eraser_menu(controller.presenter)
    assert menu.findChild(QPushButton) is None
    slider = menu.findChild(QSlider)
    assert slider.value() == 20
    session.begin_stroke("#fff", 0.01, (0.5, 0.5))
    session.end_stroke()
    press_key(controller, Qt.Key.Key_E)
    at = spot(canvas, (0.54, 0.5))
    QTest.mouseClick(canvas, LEFT, NO_MODIFIER, at)
    assert len(session.strokes[0]) == 1
    slider.setValue(100)
    assert controller.settings.eraser_size == pytest.approx(0.10)
    QTest.mouseClick(canvas, LEFT, NO_MODIFIER, at)
    assert session.strokes[0] == []
    assert PresentationSettings.load().eraser_size == PresentationSettings().eraser_size


def settled(controller, *canvases_, seconds=5.0):
    """Wait for the windows to appear and the canvas geometry to settle."""
    for window in (controller.presenter, controller.audience):
        if window is not None:
            assert QTest.qWaitForWindowExposed(window, int(seconds * 1000))
    deadline = time.monotonic() + seconds
    sizes, steady = None, 0
    while steady < 5:
        QApplication.processEvents()
        now = [c.size() for c in canvases_]
        steady = steady + 1 if now == sizes else 0
        sizes = now
        assert time.monotonic() < deadline, "the canvases kept changing size"
        time.sleep(0.005)


def hover(canvas, fraction, until, seconds=5.0):
    """Retry mouse moves until Qt delivers the hover event."""
    deadline = time.monotonic() + seconds
    while True:
        QTest.mouseMove(canvas, spot(canvas, fraction))
        QApplication.processEvents()
        if until():
            return
        assert time.monotonic() < deadline, f"the mouse did not get to {fraction}"
        pause(10)


def hovering_at(canvas, fraction):
    return lambda: canvas._hover is not None and canvas._hover.toPoint() == spot(canvas, fraction)


def test_a_circle_of_the_erasers_size_follows_the_mouse_on_that_canvas_only_while_the_eraser_is_on(make):
    controller = make(settings=PresentationSettings(eraser_size=0.05))
    current = current_canvas(controller)
    audience = controller.audience.canvas
    settled(controller, current, audience)
    QTest.mouseMove(current, spot(current, (0.1, 0.1)))               # the first move only enters the widget
    hover(current, (0.5, 0.5), hovering_at(current, (0.5, 0.5)))
    assert current._eraser_circle() is None                           # not the eraser
    press_key(controller, Qt.Key.Key_E)
    assert controller.session.tool == TOOL_ERASER
    circle = current._eraser_circle()
    assert circle is not None and circle.height() == pytest.approx(2 * 0.05 * current.target().height())
    assert circle.center().toPoint() == spot(current, (0.5, 0.5))
    hover(current, (0.25, 0.5), hovering_at(current, (0.25, 0.5)))
    assert current._eraser_circle().center().toPoint() == spot(current, (0.25, 0.5))      # it follows
    assert audience._eraser_circle() is None                          # the projector takes no input here
    shown = current.grab().toImage()
    controller.session.set_tool(TOOL_PEN)
    assert shown != current.grab().toImage()                          # the ring is painted only with the eraser
    controller.session.set_tool(TOOL_ERASER)
    hover(current, (0.5, 0.5), hovering_at(current, (0.5, 0.5)))
    current.leaveEvent(QEvent(QEvent.Type.Leave))
    assert current._eraser_circle() is None                           # gone when the mouse leaves


def test_single_screen_keeps_slide_input_and_disables_freeze(make):
    controller = make(two_screens=False)
    audience = controller.audience
    assert not controller.dual and controller.presenter is None and audience.isVisible()
    controller.next_profile()
    controller.set_profile(layout.NEXT_LARGE_CLOCK)
    assert audience.canvas.input is not None
    press_key(controller, Qt.Key.Key_F)
    assert not controller.session.frozen
    press_key(controller, Qt.Key.Key_B)
    assert controller.session.black
    settled(controller, audience.canvas)
    press_key(controller, Qt.Key.Key_E)
    assert controller.session.tool == TOOL_ERASER
    hover(audience.canvas, (0.4, 0.4), lambda: audience.canvas._eraser_circle() is not None)


# Color picking

def open_pen_dialog(controller):
    from PySide6.QtWidgets import QPushButton
    menu = controller._pen_menu(controller.presenter)
    menu.findChildren(QPushButton)[0].click()
    return controller._color_dialog


def test_pen_color_escape_restores_and_clicking_the_slide_accepts_without_saving(make):
    saved = PresentationSettings.load()
    controller = make()
    dialog = open_pen_dialog(controller)
    dialog.setCurrentColor(QColor("#123456"))
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert controller.settings.pen_color == saved.pen_color and not controller.ended
    assert controller._color_dialog is None

    dialog = open_pen_dialog(controller)
    assert dialog is not None and not dialog.isModal() and dialog.isVisible()
    dialog.setCurrentColor(QColor("#00aa00"))
    assert controller.settings.pen_color == "#ff00aa00"               # no OK pressed
    press_key(controller, Qt.Key.Key_D)
    current = current_canvas(controller)
    QTest.mousePress(current, LEFT, NO_MODIFIER, spot(current, (0.3, 0.3)))
    QTest.mouseRelease(current, LEFT, NO_MODIFIER, spot(current, (0.3, 0.3)))
    assert controller._color_dialog is None and not dialog.isVisible()
    assert controller.session.strokes[0][0].color == controller.settings.pen_color == "#ff00aa00"
    assert PresentationSettings.load() == saved


def test_laser_menu_edits_stay_local_and_dialog_keys_do_not_control_presentation(make):
    from PySide6.QtWidgets import QPushButton, QSlider

    saved = PresentationSettings.load()
    controller = make()
    menu = controller._laser_menu(controller.presenter)
    menu.findChild(QSlider).setValue(40)
    assert controller.settings.laser_size == pytest.approx(0.04)
    swatch = menu.findChild(QPushButton)
    swatch.click()
    dialog = controller._color_dialog
    dialog.setCurrentColor(QColor("#0000ff"))
    assert controller.settings.laser_color == "#0000ff" and "#0000ff" in swatch.styleSheet()
    for key in (Qt.Key.Key_Right, Qt.Key.Key_B, Qt.Key.Key_D):
        QTest.keyClick(dialog, key)
    session = controller.session
    assert session.page == 0 and not session.black and session.tool != TOOL_PEN
    controller.accept_color()
    assert controller.settings.laser_color == "#0000ff"
    swatch.click()
    dialog = controller._color_dialog
    controller.end()
    assert controller._color_dialog is None and not dialog.isVisible()
    assert PresentationSettings.load() == saved


@pytest.mark.parametrize("key", ["laser_color", "pen_color"])
def test_settings_swatch_picker_saves_valid_colors_and_cancel_keeps_them(qapp, monkeypatch, key):
    from PySide6.QtWidgets import QColorDialog
    from slidemage.ui.presentation.settings_page import PresentationTab

    tab = PresentationTab()
    button = tab.laser_button if key == "laser_color" else tab.pen_button
    chosen = QColor("#8055aaff") if key == "pen_color" else QColor("#55aaff")

    def get_color(start, parent, title, options):
        assert parent is tab
        assert bool(options & QColorDialog.ColorDialogOption.ShowAlphaChannel) == (key == "pen_color")
        return chosen

    monkeypatch.setattr(QColorDialog, "getColor", get_color)
    button.click()
    expected = chosen.name(QColor.NameFormat.HexArgb if key == "pen_color" else QColor.NameFormat.HexRgb)
    assert getattr(PresentationSettings.load(), key) == expected
    assert button.text() == expected and "#55aaff" in button.styleSheet()
    chosen = QColor()  # Cancel returns an invalid color.
    button.click()
    assert getattr(PresentationSettings.load(), key) == expected and button.text() == expected
    tab._reset()
    assert getattr(PresentationSettings.load(), key) == getattr(PresentationSettings(), key)
    assert button.text() == QColor(getattr(PresentationSettings(), key)).name()
