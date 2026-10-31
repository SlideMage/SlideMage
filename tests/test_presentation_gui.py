# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The presentation windows and their controls, offscreen (docs/plans/presentation-mode.md). Two screens are
made up from the one real offscreen screen, so the plan's placement logic runs; real monitors are for the
manual checklist in the plan."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from presentation_fixtures import JUMP_SPOT, URI_SPOT, make_pdf
from slidemage.presentation.keep_awake import KeepAwake
from slidemage.presentation.pdf_source import PresentationDeck
from slidemage.presentation.screens import ScreenInfo
from slidemage.presentation.session import TOOL_PEN
from slidemage.presentation.settings import PresentationSettings
from slidemage.ui.presentation.controller import PresentationController
from slidemage.ui.presentation.slide_canvas import SlideCanvas
from slidemage.ui.presentation.timer_widget import TimerButton
from slidemage.ui.presentation.views import AudienceView, CurrentView

LAPTOP = ScreenInfo("laptop", 0, 0, 1280, 720, primary=True)
PROJECTOR = ScreenInfo("projector", 1280, 0, 1280, 720)


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


def canvases(window, view_type):
    return [c for c in window.findChildren(SlideCanvas) if type(c.view) is view_type]


def spot(canvas, fraction):
    rect = canvas.target()
    return QPoint(int(rect.x() + fraction[0] * rect.width()), int(rect.y() + fraction[1] * rect.height()))


def press_key(controller, key, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(controller.presenter or controller.audience, key, modifier)


def test_two_screens_open_a_presenter_and_an_audience_window(make):
    controller = make()
    assert controller.dual and controller.presenter.isVisible() and controller.audience.isVisible()
    assert controller.backend.calls == ["start"]                       # the computer is kept awake
    assert controller.audience.geometry().x() == 1280                  # the audience window is on the second screen
    kinds = sorted(type(c.view).__name__ for c in controller.presenter.findChildren(SlideCanvas))
    assert kinds == ["CurrentView", "NextView", "NotesView"]
    assert len(canvases(controller.audience, AudienceView)) == 1


def test_one_screen_shows_only_the_slide_full_screen_and_freeze_is_off(make):
    controller = make(two_screens=False)
    assert not controller.dual and controller.presenter is None and controller.audience.isVisible()
    press_key(controller, Qt.Key.Key_F)
    assert not controller.session.frozen
    press_key(controller, Qt.Key.Key_B)
    assert controller.session.black


def test_the_audience_window_shows_nothing_but_the_slide(make):
    controller = make()
    audience = controller.audience
    assert not audience.findChildren(QLabel, options=Qt.FindChildOption.FindChildrenRecursively) or all(
        not label.isVisible() for label in audience.findChildren(QLabel))
    assert not audience.findChildren(TimerButton)


def test_keys_clicker_keys_digits_and_the_wheel_navigate(make):
    controller = make()
    session = controller.session
    for key, page in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_PageDown, 2), (Qt.Key.Key_Space, 3), (Qt.Key.Key_Left, 2),
                      (Qt.Key.Key_PageUp, 1), (Qt.Key.Key_Up, 0), (Qt.Key.Key_Down, 1), (Qt.Key.Key_End, 5),
                      (Qt.Key.Key_Home, 0)):
        press_key(controller, key)
        assert session.page == page, key
    press_key(controller, Qt.Key.Key_4)
    assert session.page == 0
    press_key(controller, Qt.Key.Key_Return)
    assert session.page == 3                                          # "4", Enter: slide 4
    for delta, page in ((-120, 4), (-120, 5), (120, 4), (60, 4), (60, 3)):
        controller.wheel(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
                                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                     Qt.ScrollPhase.NoScrollPhase, False))
        assert session.page == page, delta


def test_black_and_dot_alias_and_freeze_with_their_badge(make):
    controller = make()
    session = controller.session
    current = canvases(controller.presenter, CurrentView)[0]
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
    press_key(controller, Qt.Key.Key_Escape)
    assert finished == [True] and controller.presenter is None and controller.audience is None
    assert controller.backend.calls == ["start", "stop"]
    controller.end()
    assert finished == [True]


def test_closing_a_window_also_ends_it(make):
    controller = make()
    controller.presenter.close()
    assert controller.ended and controller.backend.calls == ["start", "stop"]


def test_ctrl_and_the_left_button_shows_the_laser_on_both_screens_until_release(make):
    controller = make()
    current = canvases(controller.presenter, CurrentView)[0]
    audience = canvases(controller.audience, AudienceView)[0]
    at = spot(current, (0.5, 0.5))
    QTest.mousePress(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, at)
    assert controller.session.pointer == pytest.approx((0.5, 0.5), abs=0.02)
    assert audience.view.pointer() is not None
    QTest.mouseRelease(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, at)
    assert controller.session.pointer is None
    QTest.mouseMove(current, at)                     # no laser without a button
    assert controller.session.pointer is None


def test_a_plain_click_follows_links_but_ctrl_click_does_not(make):
    controller = make()
    current = canvases(controller.presenter, CurrentView)[0]
    QTest.mouseClick(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, spot(current, JUMP_SPOT))
    assert controller.session.page == 0
    QTest.mouseClick(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot(current, JUMP_SPOT))
    assert controller.session.page == 3
    assert controller.session.back() and controller.session.page == 0
    QTest.mouseClick(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot(current, URI_SPOT))
    assert controller.opened == ["https://example.org/x"]


def test_links_ask_first_and_only_web_and_mail_addresses_open(make):
    answers = []
    controller = make()
    controller._confirm = lambda _w, uri: answers.append(uri) or False
    controller.session.request_link("https://example.org/a")
    assert answers == ["https://example.org/a"] and controller.opened == []
    controller._confirm = lambda _w, uri: True
    controller.session.request_link("file:///etc/passwd")
    assert controller.opened == []
    controller.session.request_link("mailto:a@b.org")
    assert controller.opened == ["mailto:a@b.org"]


def test_a_map_location_link_opens_and_dangerous_schemes_stay_closed(make):
    # A QR code for a place links with a geo: URI (qr_code.link_target): a click opens the system's map app.
    from slidemage import qr_code
    from slidemage.qr_code import QRSpec
    controller = make()
    controller._confirm = lambda _w, uri: True
    geo = qr_code.link_target(QRSpec("location", {"place": "47.0707, 15.4395", "map_link": qr_code.LINK_GEO}))
    assert geo.startswith("geo:")
    controller.session.request_link(geo)
    controller.session.request_link("GEO:0,0?q=Graz")
    assert controller.opened == [geo, "GEO:0,0?q=Graz"]
    for uri in ("file:///C:/Windows/System32/calc.exe", "javascript:alert(1)", "ms-settings:privacy",
                "geoplugin:x", "C:\\Windows\\notepad.exe", "smb://host/share"):
        controller.session.request_link(uri)
    assert controller.opened == [geo, "GEO:0,0?q=Graz"]


def test_the_pen_draws_without_ctrl_and_ctrl_still_lases_and_clear_empties_the_page(make):
    controller = make()
    session = controller.session
    current = canvases(controller.presenter, CurrentView)[0]
    press_key(controller, Qt.Key.Key_D)
    start, end = spot(current, (0.3, 0.3)), spot(current, (0.6, 0.6))
    QTest.mousePress(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(current, end)
    QTest.mouseRelease(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert len(session.strokes[0]) == 1 and len(session.strokes[0][0].points) >= 2
    QTest.mousePress(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, start)
    assert session.pointer is not None and len(session.strokes[0]) == 1
    QTest.mouseRelease(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, start)
    press_key(controller, Qt.Key.Key_Right)
    press_key(controller, Qt.Key.Key_Left)
    assert len(session.strokes[0]) == 1                          # still there after navigating away and back
    press_key(controller, Qt.Key.Key_Delete)
    assert 0 not in session.strokes


def test_the_presenter_window_draws_the_slide_notes_and_drawing(make):
    controller = make()
    controller.session.begin_stroke("#ff0000", 0.05, (0.5, 0.5))
    controller.session.extend_stroke((0.9, 0.5))
    controller.presenter.resize(1200, 700)
    for canvas in controller.presenter.findChildren(SlideCanvas):
        assert not canvas.grab().isNull()
    audience = canvases(controller.audience, AudienceView)[0]
    image = audience.grab().toImage()
    centre = audience.target().center()
    assert image.pixelColor(centre.x(), centre.y()).red() > 200      # the stroke is drawn on the projector too


def test_a_plain_pdf_presents_with_a_notes_hint(make):
    controller = make(two_up=False)
    notes = [c for c in controller.presenter.findChildren(SlideCanvas) if c.empty_text.startswith("No notes")]
    assert len(notes) == 1


def test_switching_the_layout_profile_rebuilds_the_presenter_and_is_saved(make):
    saved = []
    controller = make(save_settings=lambda s: saved.append(s.profile))
    press_key(controller, Qt.Key.Key_P)
    assert controller.profile.name == "Next large" and saved == ["Next large"]
    assert len(controller.presenter.findChildren(SlideCanvas)) == 3
    press_key(controller, Qt.Key.Key_P)
    assert controller.profile.name == "Current large"


def test_a_duration_timer_starts_on_the_first_slide_change_and_t_toggles_it(make):
    controller = make()
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


def test_a_drawing_lands_on_the_same_spot_of_the_slide_on_screens_of_different_size_and_shape(make):
    settings = PresentationSettings(pen_color="#ffff0000", pen_width=0.08)
    controller = make(settings=settings)
    controller.presenter.resize(900, 640)
    controller.audience.resize(1000, 800)               # taller than 16:9: the slide is letterboxed top and bottom
    qapp_events = QTest.qWait
    qapp_events(10)
    current = canvases(controller.presenter, CurrentView)[0]
    audience = canvases(controller.audience, AudienceView)[0]
    assert current.target().size() != audience.target().size()
    press_key(controller, Qt.Key.Key_D)
    QTest.mousePress(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot(current, (0.2, 0.5)))
    QTest.mouseMove(current, spot(current, (0.8, 0.5)))
    QTest.mouseMove(current, spot(current, (1.0, 0.5)) + QPoint(60, 0))      # the margin beside the slide
    QTest.mouseRelease(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot(current, (0.8, 0.5)))
    assert max(x for x, _y in controller.session.strokes[0][0].points) == 1.0     # clamped to the slide's edge
    for canvas in (current, audience):
        image = canvas.grab().toImage()
        for fraction, drawn in (((0.5, 0.5), True), ((0.25, 0.5), True), ((0.5, 0.9), False), ((0.5, 0.1), False)):
            at = spot(canvas, fraction)
            colour = image.pixelColor(at.x(), at.y())
            assert (colour.red() > 200 and colour.green() < 60) == drawn, (canvas.view, fraction)


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


def test_without_nav_data_the_typed_number_is_a_page_and_the_indicator_says_so(make):
    controller = make()
    counter = [label for label in controller.presenter.findChildren(QLabel) if label.text().startswith("Page")][0]
    press_key(controller, Qt.Key.Key_3)
    assert counter.text() == "Go to page 3  (Enter)"
    press_key(controller, Qt.Key.Key_Return)
    assert controller.session.page == 2 and counter.text() == "Page 3 / 6"
    press_key(controller, Qt.Key.Key_5)
    press_key(controller, Qt.Key.Key_Escape)                                # anything else drops the typed number
    assert controller.ended


def test_a_presentation_continued_at_a_slide_opens_there_on_both_screens(make):
    from slidemage.presentation.frame_map import FrameMap
    controller = make(frames=FrameMap(((0, 0), (1, 3), (4, 4), (5, 5))), start_page=4)
    counter = [label for label in controller.presenter.findChildren(QLabel) if label.text().startswith("Slide")][0]
    assert controller.session.page == 4 and counter.text() == "Slide 3 / 4 · step 1 / 1"


def test_changing_the_layout_leaves_no_updates_to_deleted_widgets(make, capfd):
    from PySide6.QtCore import QCoreApplication, QEvent
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


def test_the_laser_menu_changes_colour_and_size_for_this_presentation_only(make):
    from PySide6.QtWidgets import QSlider, QToolButton
    saved = PresentationSettings()
    controller = make(settings=saved)
    assert any(tool.text() == "Laser" for tool in controller.presenter.findChildren(QToolButton))
    menu = controller._laser_menu(controller.presenter)
    menu.findChildren(QSlider)[0].setValue(40)
    assert controller.settings.laser_size == pytest.approx(0.04)
    canvases = controller.audience.findChildren(SlideCanvas) + controller.presenter.findChildren(SlideCanvas)
    assert canvases and all(canvas.settings is controller.settings for canvas in canvases)   # drawn from it live
    assert PresentationSettings.load().laser_size == PresentationSettings().laser_size       # nothing saved
