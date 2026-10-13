"""The dialog badge, keyboard support and live region of the AI switch (workspace v6, step 7): the read-only route
badge under the title of every dialog that runs or configures AI, the keyboard paths of the switch, its popovers
and AI setup, the shared `announce` helper and the accessible names. Nothing here reaches Ollama or the cloud."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from slidemage import alt_blocks, alt_draft, deck_editor, deck_scan
from slidemage.ai import ai_profile
from slidemage.ai.ai_profile import API, CLAUDE_CODE, CLOUD, LOCAL
from slidemage.ai.providers import OllamaProvider
from slidemage.ui.dialogs import deck_settings as deck_settings_module
from slidemage.ui.dialogs.add_slide import AddSlideSheet
from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet
from slidemage.ui.dialogs.settings import SettingsSheet
from slidemage.ui.kit import widgets
from slidemage.ui.kit.widgets import ModeBadge, Popover, SegmentedControl
from slidemage.ui.pages import image_dialogs
from slidemage.ui.workspace import ai_setup, ai_switch
from conftest import qapp as qapp  # noqa: F401 -- a fixture
from test_ai_switch_gui import INSTALLED, commit_to_cloud, kind, open_setup, route, window as window  # noqa: F401
from test_deck_settings_gui import TEMPLATES, make_deck


def focus_on(window, widget):
    window.activateWindow()
    QApplication.processEvents()
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    assert QApplication.focusWidget() is widget
    return widget


def tab(times: int = 1, *, back: bool = False) -> list[QWidget]:
    """Press Tab (Shift+Tab) on the focused widget `times` times: the widgets that had the focus after each."""
    reached = []
    for _ in range(times):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Backtab if back else Qt.Key.Key_Tab,
                       Qt.KeyboardModifier.ShiftModifier if back else Qt.KeyboardModifier.NoModifier)
        reached.append(QApplication.focusWidget())
    return reached


# -- the dialog badge (section 6) -----------------------------------------------------------------------------------

def settings_sheet(window, tmp_path, monkeypatch):
    return SettingsSheet(window)


def deck_sheet(window, tmp_path, monkeypatch):
    monkeypatch.setattr(deck_settings_module.AdminSlidesTab, "start", lambda self: None)     # no network
    return DeckSettingsSheet(window, make_deck(tmp_path), TEMPLATES)


def add_slide_sheet(window, tmp_path, monkeypatch):
    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: ["qwen3"])
    deck = next(d for d in deck_scan.scan_decks(window.project) if not d.archived)
    insert_at, indent = deck_editor.append_position(deck)
    return AddSlideSheet(window, deck, insert_at, indent, is_dirty=window.centre.is_dirty)


def tuning_sheet(window, tmp_path, monkeypatch):
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, _reference: None)
    context = alt_draft.SlideContext(slide_id="one", title="T", body="", source="", image="chart.png")
    return image_dialogs.PromptTuningSheet(window, "media/chart.png", tmp_path / "chart.png", context,
                                           OllamaProvider("offline-test"), "", lambda: None)


SHEETS = {"Settings": settings_sheet, "Deck settings": deck_sheet, "Add slide": add_slide_sheet,
          "Prompt tuning": tuning_sheet}


@pytest.fixture(params=list(SHEETS))
def sheet(request, window, tmp_path, monkeypatch):
    sheet = SHEETS[request.param](window, tmp_path, monkeypatch)
    yield sheet
    if (loader := getattr(sheet, "_loader", None)) is not None:
        loader.wait()
    sheet.reject()
    sheet.deleteLater()


def badge_of(sheet) -> ModeBadge:
    return sheet._root.itemAt(1).widget()


def test_every_dialog_that_runs_ai_shows_the_route_badge_under_its_title(sheet, window):
    badge = badge_of(sheet)
    assert isinstance(badge, ModeBadge) and sheet._root.itemAt(0).widget() is sheet._title      # right under the title
    assert (badge.text(), badge.property("cloud"), badge.icon.text()) == ("Local · Ollama", False, "computer")
    assert badge.toolTip() == "Change it with the switch in the top bar"
    commit_to_cloud(window)
    assert (badge.text(), badge.property("cloud"), badge.icon.text()) == ("Cloud · Claude Code", True, "cloud")
    assert badge.toolTip() == "Change it with the switch in the top bar"
    route(window).request(CLOUD, API)
    assert badge.text() == "Cloud · Anthropic API" and badge.property("cloud") is True      # refreshed while it is open
    route(window).request(LOCAL)
    assert (badge.text(), badge.property("cloud")) == ("Local · Ollama", False)


def test_a_dialog_has_no_route_picker_of_its_own(sheet):
    pickers = [control for control in sheet.findChildren(SegmentedControl) if {LOCAL, CLOUD} & set(control._buttons)]
    assert pickers == []
    assert not any(isinstance(w, QWidget) and w.accessibleName().startswith("AI route") for w in sheet.findChildren(QWidget)
                   if w is not badge_of(sheet))


def test_the_badge_names_its_route_for_a_screen_reader(qapp):
    badge = ModeBadge()
    badge.set_route("Cloud · Claude Code", True)
    assert badge.accessibleName() == "AI route: Cloud · Claude Code" and badge.accessibleDescription() == badge.toolTip()


def test_a_sheet_without_a_window_has_no_badge(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(deck_settings_module.AdminSlidesTab, "start", lambda self: None)
    sheet = DeckSettingsSheet(None, make_deck(tmp_path), TEMPLATES)
    assert not sheet.findChildren(ModeBadge)


# -- the switch -----------------------------------------------------------------------------------------------------

def test_the_switch_has_a_group_name_and_every_icon_button_a_name(window):
    switch = window.topbar.ai_switch
    assert switch.segments.accessibleName() == "AI for all tasks" and switch.caret.accessibleName() == "AI setup"
    assert [b.accessibleName() for b in switch.segments._buttons.values()] == ["Local", "Cloud"]
    header = window.assistant.header
    assert header.focus_button.accessibleName() == "Focus assistant: hide the side panels"
    header.focus_button.click()
    assert header.focus_button.accessibleName() == "Show the side panels again"
    assert header.new_button.accessibleName() == "New conversation (this route only)"
    assert window.topbar._more.accessibleName() == "More"
    assert header.route_icon.accessibleName() == "Local"
    commit_to_cloud(window)
    assert header.route_icon.accessibleName() == "Cloud"
    assert header.scope.accessibleName() == "Scope of the assistant"


def test_the_switch_announces_a_commit_and_the_start_of_stopping(window, monkeypatch):
    told = []
    monkeypatch.setattr(ai_switch, "announce", lambda widget, text: told.append((widget, text)))
    commit_to_cloud(window)
    switch = window.topbar.ai_switch
    assert told == [(switch.segments, "All AI tasks now use Cloud")]
    route(window).request(LOCAL)
    assert told[-1] == (switch.segments, "All AI tasks now use Local")
    told.clear()
    switch.set_stopping(True)
    switch.set_stopping(True)
    assert told == [(switch.segments, ai_switch.STOPPING)]
    switch.set_stopping(False)
    assert len(told) == 1


def test_announce_is_a_polite_live_region_and_does_nothing_without_qt_support(monkeypatch, qapp):
    events = []

    class Event:
        def __init__(self, widget, text):
            self.widget, self.text, self.politeness = widget, text, None
            events.append(self)

        def setPoliteness(self, politeness):
            self.politeness = politeness

    monkeypatch.setattr(widgets, "QAccessibleAnnouncementEvent", Event)
    monkeypatch.setattr(widgets.QAccessible, "updateAccessibility", lambda event: events.append(("sent", event)))
    label = QWidget()
    widgets.announce(label, "Saved")
    event = events[0]
    assert (event.widget, event.text, event.politeness) == (label, "Saved", widgets.QAccessible.AnnouncementPoliteness.Polite)
    assert events[1] == ("sent", event)
    events.clear()
    monkeypatch.setattr(widgets, "QAccessibleAnnouncementEvent", None)           # Qt before 6.8
    widgets.announce(label, "Saved")
    assert events == []


def test_the_real_announce_runs_on_this_qt(qapp):
    widgets.announce(QWidget(), "Hello")


def test_the_keyboard_flips_the_switch_and_keeps_the_focus_on_the_selected_segment(window, qapp):
    ai_profile.set_policy(window.project, CLOUD)
    ai_profile.mark_cloud_seen(window.project)
    segments = window.topbar.ai_switch.segments
    local, cloud = segments._buttons[LOCAL], segments._buttons[CLOUD]
    focus_on(window, local)
    QTest.keyClick(local, Qt.Key.Key_Right)
    assert window.state.ai_mode == CLOUD and QApplication.focusWidget() is cloud
    assert tab()[0] is window.topbar.ai_switch.caret                    # Tab: the selected segment, then the ▾
    focus_on(window, cloud)
    assert tab(back=True)[0] is not local
    focus_on(window, cloud)
    QTest.keyClick(cloud, Qt.Key.Key_Left)
    assert window.state.ai_mode == LOCAL and QApplication.focusWidget() is local
    QTest.keyClick(local, Qt.Key.Key_Space)                              # Space and Enter activate the segment
    QTest.keyClick(local, Qt.Key.Key_Return)
    assert window.state.ai_mode == LOCAL and kind(window) == ""


def test_the_arrow_into_a_popover_moves_the_focus_there_and_escape_gives_it_back(window, qapp):
    segments = window.topbar.ai_switch.segments
    local = focus_on(window, segments._buttons[LOCAL])
    QTest.keyClick(local, Qt.Key.Key_Right)                              # the project is Local: the warning
    popover = route(window)._popover
    assert kind(window) == "policy"
    cancel, primary = popover.buttons
    link = popover.findChildren(widgets.Button)[-1]
    assert QApplication.focusWidget() is cancel                          # the safe answer has the focus
    assert tab(4) == [primary, link, cancel, primary]                    # secondary, primary, link, and round again
    assert tab(2, back=True) == [cancel, link]
    focus_on(window, cancel)
    QTest.keyClick(cancel, Qt.Key.Key_Escape)                            # Esc is the secondary button
    assert kind(window) == "" and window.state.ai_mode == LOCAL
    assert QApplication.focusWidget() is local


def test_enter_on_the_primary_button_commits_and_the_focus_is_on_the_selected_segment(window, qapp):
    segments = window.topbar.ai_switch.segments
    local = focus_on(window, segments._buttons[LOCAL])
    QTest.keyClick(local, Qt.Key.Key_Right)
    tab()                                                                # the primary button
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    assert window.state.ai_mode == CLOUD and kind(window) == ""
    assert QApplication.focusWidget() is segments._buttons[CLOUD]


def test_the_link_of_the_policy_popover_is_reachable_from_the_keyboard(window, qapp):
    local = focus_on(window, window.topbar.ai_switch.segments._buttons[LOCAL])
    QTest.keyClick(local, Qt.Key.Key_Right)
    tab(2)
    assert QApplication.focusWidget().text() == "Change the project setting…"
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Return)
    assert kind(window) == "" and window.ai_route.setup.isVisible()


def test_the_popover_replacing_its_text_keeps_the_focus_on_the_same_button(window, monkeypatch):
    from test_ai_switch_gui import Work

    work = Work(window, monkeypatch)
    route(window).request(CLOUD)
    popover = route(window)._popover
    assert kind(window) == "busy" and QApplication.focusWidget() is popover.buttons[0]      # Keep running
    popover.buttons[1].setFocus()
    work.running = False
    route(window)._on_watch()                                            # the work ended by itself
    assert kind(window) == "finished" and QApplication.focusWidget() is popover.buttons[1]


# -- AI setup -------------------------------------------------------------------------------------------------------

def test_the_arrow_keys_flip_the_cloud_connection_and_the_project_setting_like_radio_groups(window, qapp):
    setup = open_setup(window)
    for control in (setup.conn, setup.policy):
        policies = [b.focusPolicy() for b in control._buttons.values()]
        assert policies.count(Qt.FocusPolicy.TabFocus) == 1 and policies.count(Qt.FocusPolicy.NoFocus) == 1
    assert setup.conn.accessibleName() == "Cloud connection" and setup.policy.accessibleName() == "Project setting"
    focus_on(window, setup.conn._buttons[CLAUDE_CODE])
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Right)
    assert ai_profile.cloud_conn(window.project) == API


def test_tab_goes_through_ai_setup_in_reading_order_and_stays_inside(window, qapp):
    setup = open_setup(window)
    assert QApplication.focusWidget() is setup
    # reading order: Local then Cloud of each row; the Claude Code chat cell is a label, not a stop
    rows = [(setup.cells[(LOCAL, task)], setup.cells[(CLOUD, task)]) for task in ai_profile.TASKS]
    stops = [setup.cells[(LOCAL, ai_profile.CHAT)]] + [cell for pair in rows[1:] for cell in pair]
    assert tab(len(stops)) == stops
    more = tab(3)                                                  # the connection, the setting, the link
    assert more[0] in setup.conn._buttons.values() and more[1] in setup.policy._buttons.values()
    assert more[2].text() == "Settings → AI…"
    assert tab()[0] is setup.cells[(LOCAL, ai_profile.CHAT)]       # and round again: it never leaves the popover
    assert tab(back=True)[0] is more[2]


def test_escape_closes_ai_setup_and_returns_the_focus_to_the_caret(window, qapp):
    caret = focus_on(window, window.topbar.ai_switch.caret)
    QTest.keyClick(caret, Qt.Key.Key_Return)                       # Enter opens it, as Space does
    setup = window.ai_route.setup
    assert setup.isVisible()
    tab(2)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert not setup.isVisible() and QApplication.focusWidget() is caret
    QTest.keyClick(caret, Qt.Key.Key_Space)
    assert setup.isVisible()
    caret.click()                                                  # the ▾ again closes it, the focus stays on it
    assert not setup.isVisible()


def test_ai_setup_announces_the_confirmation_of_a_default(window, monkeypatch):
    told = []
    monkeypatch.setattr(ai_setup, "announce", lambda widget, text: told.append(text))
    window.local_models.fill(INSTALLED)
    setup = open_setup(window)
    image = setup.cells[(LOCAL, ai_profile.IMAGE_DESCRIPTION)]
    image.setCurrentIndex(1)
    image.activated.emit(1)
    assert told == ["Default for Local · Image descriptions: vision-model"]


def test_a_popover_keeps_tab_inside_and_gives_the_keyboard_back_when_it_closes(window, qapp):
    anchor = window.topbar.ai_switch.caret
    popover = Popover(window, inline=True)
    first, second = widgets.Button("One"), widgets.Button("Two")
    popover.body.addWidget(first)
    popover.body.addWidget(second)
    focus_on(window, anchor)
    popover.focus_target = first
    popover.popup_below(anchor)
    assert QApplication.focusWidget() is first
    assert tab(3) == [second, first, second]
    assert tab(back=True) == [first]
    popover.escape()
    assert not popover.isVisible() and QApplication.focusWidget() is anchor
    popover.deleteLater()


def test_an_enter_press_activates_kit_buttons(qapp):
    pressed = []
    for button in (widgets.Button("Go"), widgets.IconButton("add", "Add")):
        button.clicked.connect(lambda: pressed.append(True))
        QTest.keyClick(button, Qt.Key.Key_Return)
    assert pressed == [True, True]


def test_kit_buttons_and_segments_take_the_focus_from_the_keyboard_and_draw_its_ring(qapp):
    from slidemage.ui.kit.theme import ThemeManager

    theme = ThemeManager()
    theme.dark = False
    qss = theme._build_qss()
    for selector in ('QPushButton[kind]:focus', 'QPushButton[kitSegment="true"]:focus', "QToolButton#kitIconButton:focus"):
        assert selector in qss
    assert "2px solid #2563eb" in qss
    assert widgets.Button("x").focusPolicy() == Qt.FocusPolicy.TabFocus
    assert all(b.focusPolicy() == Qt.FocusPolicy.TabFocus for b in SegmentedControl([("a", "A"), ("b", "B")])._buttons.values())



# -- the ⋮ menu (step 6, checked again) -----------------------------------------------------------------------------

def test_the_more_menu_opens_from_the_keyboard_on_its_first_item_and_escape_closes_it(window, qapp):
    more = focus_on(window, window.topbar._more)
    assert more.accessibleName() == "More"
    QTest.keyClick(more, Qt.Key.Key_Return)
    menu = next(w for w in window.topbar.findChildren(widgets.PopoverMenu) if w.isVisible())
    assert menu._rows[menu._current].key == "deck_settings"            # it opens on the first item
    closed = []
    menu.closed.connect(lambda: closed.append(True))
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert closed                                                       # Qt returns the focus of a popup window itself
