"""Presentation mode without windows: the PDF source, the session, the screen plan, layouts, the timer, settings
and keep-awake (docs/plans/presentation-mode.md)."""
from __future__ import annotations

from datetime import datetime, time

import pytest

from presentation_fixtures import JUMP_SPOT, URI_SPOT, make_pdf, page_color
from slidemage import app_settings
from slidemage.ui import layout_settings
from slidemage.presentation import layout
from slidemage.presentation.keep_awake import KeepAwake
from slidemage.presentation.pdf_source import NOTES, SLIDE, PresentationDeck
from slidemage.presentation.screens import ScreenInfo, choose_screens
from slidemage.presentation.session import TOOL_PEN, PresentationSession
from slidemage.presentation.settings import PresentationSettings
from slidemage.presentation.timer import PresentationTimer


# -- the PDF -----------------------------------------------------------------------------

@pytest.fixture
def deck(tmp_path, qapp):
    deck = PresentationDeck(make_pdf(tmp_path / "p.pdf"))
    yield deck
    deck.close()


def test_a_double_width_pdf_splits_into_slide_and_notes(deck):
    assert deck.two_up and deck.has_notes and deck.page_count == 6
    slide, notes = deck.slide_rect(0), deck.notes_rect(0)
    assert slide.width == pytest.approx(notes.width) and slide.x1 == pytest.approx(notes.x0)
    assert deck.aspect == pytest.approx(16 / 9, abs=0.01)


def test_slide_and_notes_render_their_own_half(deck):
    image = deck.render(2, SLIDE, 400, 400)
    colour = image.pixelColor(image.width() - 5, image.height() - 5)    # away from the text
    expected = page_color(2)
    assert colour.redF() == pytest.approx(expected[0], abs=0.02) and colour.blueF() == pytest.approx(expected[2], abs=0.02)
    notes = deck.render(2, NOTES, 400, 400)
    assert notes.pixelColor(notes.width() - 5, notes.height() - 5).lightness() > 240      # white paper
    assert deck.render(0, SLIDE, 400, 400) is deck.render(0, SLIDE, 400, 400)           # cached
    assert deck.render(99, SLIDE, 400, 400) is None


def test_links_of_the_slide_half_only_with_slide_fractions(deck):
    links = deck.links(0)
    assert sorted((link.uri is not None) for link in links) == [False, True]       # the notes link is ignored
    assert deck.link_at(0, *URI_SPOT).uri == "https://example.org/x"
    assert deck.link_at(0, *JUMP_SPOT).page == 3
    assert deck.link_at(0, 0.9, 0.9) is None and deck.links(1) == []


def test_a_plain_pdf_has_no_notes(tmp_path, qapp):
    plain = PresentationDeck(make_pdf(tmp_path / "plain.pdf", two_up=False))
    assert not plain.has_notes and plain.notes_rect(0) is None and plain.render(0, NOTES, 100, 100) is None
    assert plain.render(0, SLIDE, 200, 200) is not None
    plain.close()


# -- the session -------------------------------------------------------------------------

def test_navigation_is_clamped_and_a_link_jump_can_go_back(qapp):
    session = PresentationSession(5)
    assert not session.previous() and session.next() and session.page == 1
    session.last()
    assert session.page == 4 and not session.next()
    session.jump_to(1)
    session.jump_to(3)
    assert session.back() and session.page == 1 and session.back() and session.page == 4 and not session.back()


def test_black_ends_with_any_navigation_but_freeze_does_not(qapp):
    session = PresentationSession(6)
    session.toggle_black()
    assert session.black and session.audience_strokes() == [] and session.status() == ("PROJECTOR BLACK", "black")
    session.next()
    assert not session.black and session.status() is None
    session.toggle_freeze()
    assert session.frozen_page == 1 and session.status()[1] == "frozen"
    session.next()
    session.next()
    assert session.page == 3 and session.audience_page == 1 and session.frozen_page == 1     # navigation does not unfreeze
    session.toggle_freeze()
    assert session.audience_page == 3 and not session.frozen


def test_black_while_frozen_returns_to_the_frozen_slide(qapp):
    session = PresentationSession(6)
    session.toggle_freeze()                     # frozen on page 0
    session.next()
    session.toggle_black()
    assert session.status() == ("PROJECTOR BLACK · PROJECTOR FROZEN: page 1", "both")
    session.next()                              # navigation ends the black, never the freeze
    assert not session.black and session.audience_page == 0 and session.page == 2
    session.toggle_black()
    session.toggle_black()                      # B again also shows the frozen slide
    assert session.audience_page == 0
    session.toggle_black()
    session.toggle_freeze()                     # unfreeze while black: stays black, then shows the current page
    assert session.black and session.audience_page == 2


def test_freezing_while_black_freezes_the_slide_the_projector_had(qapp):
    session = PresentationSession(6)
    session.toggle_black()
    session.toggle_freeze()
    assert session.frozen_page == 0 and session.black


def test_drawings_stay_per_page_and_the_frozen_projector_keeps_its_snapshot(qapp):
    session = PresentationSession(4)
    session.begin_stroke("#ff0000", 0.01, (0.1, 0.1))
    session.extend_stroke((0.2, 0.2))
    session.end_stroke()
    session.toggle_freeze()                     # the projector keeps this one stroke
    session.begin_stroke("#00ff00", 0.01, (0.5, 0.5))
    session.end_stroke()
    assert len(session.strokes[0]) == 2 and len(session.audience_strokes()) == 1
    session.set_pointer((0.3, 0.3))
    assert session.audience_pointer() is None and session.pointer == (0.3, 0.3)       # the laser is not mirrored
    session.next()
    assert session.strokes.get(1) is None
    session.previous()
    assert len(session.strokes[0]) == 2                                              # back again: still there
    session.toggle_freeze()
    session.set_pointer((0.3, 0.3))
    assert len(session.audience_strokes()) == 2 and session.audience_pointer() == (0.3, 0.3)


def test_clearing_and_erasing(qapp):
    session = PresentationSession(3)
    for page in (0, 1):
        session.goto(page)
        session.begin_stroke("#fff", 0.01, (0.5, 0.5))
        session.end_stroke()
    session.erase_at((0.51, 0.5))
    assert session.strokes[1] == []
    session.undo_stroke()
    session.goto(0)
    session.clear_page()
    assert 0 not in session.strokes
    session.goto(1)
    session.begin_stroke("#fff", 0.01, (0.1, 0.1))
    session.clear_all()
    assert session.strokes == {}
    session.set_tool(TOOL_PEN)
    assert session.tool == TOOL_PEN
    session.set_tool(TOOL_PEN)
    assert session.tool == "none"


# -- screens -----------------------------------------------------------------------------

LAPTOP = ScreenInfo("laptop", 0, 0, 1920, 1080, primary=True)
PROJECTOR = ScreenInfo("projector", 1920, 0, 1280, 720, serial="P1")
SIDE = ScreenInfo("side", -1920, 0, 1920, 1080)


def test_one_screen_or_a_mirror_means_audience_only():
    assert choose_screens([LAPTOP]).audience is None
    mirror = ScreenInfo("copy", 0, 0, 1920, 1080)
    assert choose_screens([LAPTOP, mirror]).audience is None


def test_two_screens_put_the_presenter_on_the_main_one_and_the_audience_on_the_other():
    plan = choose_screens([LAPTOP, PROJECTOR], main=0)
    assert (plan.presenter, plan.audience) == (0, 1)
    plan = choose_screens([LAPTOP, PROJECTOR], main=1)
    assert (plan.presenter, plan.audience) == (1, 0)
    assert choose_screens([PROJECTOR, LAPTOP]).presenter == 1       # no main window: the primary screen


def test_the_preferred_audience_screen_wins_and_a_missing_one_falls_back():
    screens = [LAPTOP, SIDE, PROJECTOR]
    assert choose_screens(screens, 0, PROJECTOR.key).audience == 2
    assert choose_screens(screens, 0, "gone").audience == 1
    with pytest.raises(ValueError):
        choose_screens([])


# -- layouts -----------------------------------------------------------------------------

def test_the_built_in_profiles_are_valid_and_the_owners_has_the_current_slide_large():
    for profile in layout.BUILTINS:
        assert layout.problems(profile) == []
        assert sorted(layout.elements_of(profile.tree)) == sorted(
            ["current", "next", "notes", "counter", "clock", "timer", "toolbar"])
    tree = layout.CURRENT_LARGE.tree.a
    assert tree.a.elements == ("current",) and tree.b.a.elements == ("next",) and tree.b.b.elements == ("notes",)
    assert layout.NEXT_LARGE.tree.a.a.elements == ("next",)


def test_a_profile_survives_json_and_bad_ones_are_refused():
    data = layout.profile_to_dict(layout.CURRENT_LARGE)
    again = layout.profile_from_dict(data)
    assert again.tree == layout.CURRENT_LARGE.tree and again.name == "Current large"
    with pytest.raises(ValueError):
        layout.profile_from_dict({"name": "x", "tree": {"leaf": "next"}})                  # no current slide
    with pytest.raises(ValueError):
        layout.profile_from_dict({"name": "x", "tree": {"split": "h", "a": {"leaf": "current"}, "b": {"leaf": "current"}}})
    with pytest.raises(ValueError):
        layout.profile_from_dict({"name": "x", "tree": {"leaf": ["current", "clock"]}})   # big element not alone
    with pytest.raises(ValueError):
        layout.parse_node({"leaf": "weather"})
    clamped = layout.parse_node({"split": "h", "ratio": 5, "a": {"leaf": "current"}, "b": {"leaf": "next"}})
    assert clamped.ratio == layout.MAX_RATIO
    assert layout.profile_named("nope").name == "Current large"


# -- the timer ---------------------------------------------------------------------------

class Clock:
    def __init__(self, start=datetime(2026, 10, 18, 10, 0, 0)):
        self.monotonic, self.wall = 0.0, start

    def advance(self, seconds):
        from datetime import timedelta
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)


def timer_with(clock):
    return PresentationTimer(clock=lambda: clock.monotonic, now=lambda: clock.wall)


def test_an_end_time_counts_down_to_the_time_of_day_and_rejects_a_past_time():
    clock = Clock()
    timer = timer_with(clock)
    assert timer.remaining() is None and timer.level() == "off" and timer.text() == ""
    assert not timer.set_end_time(time(9, 30)) and not timer.is_set
    assert timer.set_end_time(time(10, 30))
    assert timer.text() == "30:00" and timer.target_text() == "until 10:30" and timer.level() == "ok"
    clock.advance(25 * 60 + 1)
    assert timer.level() == "warn" and timer.text() == "04:59"
    clock.advance(5 * 60)
    assert timer.level() == "over" and timer.text() == "+00:01"


def test_a_duration_starts_on_demand_pauses_and_resets():
    clock = Clock()
    timer = timer_with(clock)
    timer.set_duration(600)
    assert not timer.running and timer.text() == "10:00"
    clock.advance(30)
    assert timer.text() == "10:00"                  # not started: nothing runs
    timer.toggle()
    clock.advance(60)
    assert timer.text() == "09:00"
    timer.toggle()
    clock.advance(500)
    assert timer.text() == "09:00" and not timer.running
    timer.toggle()
    clock.advance(540)
    assert timer.remaining() == pytest.approx(0) and timer.level() == "over"
    timer.reset()
    assert timer.text() == "10:00" and not timer.running
    timer.clear()
    assert not timer.is_set and timer.remaining() is None


def test_time_up_flashes_for_ten_seconds_then_stays_red_and_flashing_can_be_off():
    clock = Clock()
    timer = timer_with(clock)
    timer.set_duration(60)
    timer.start()
    clock.advance(60.1)
    assert timer.flash_on() is True
    clock.advance(0.5)
    assert timer.flash_on() is False
    clock.advance(0.5)
    assert timer.flash_on() is True
    assert timer.flash_on(flash=False) is True and (clock.advance(0.5) or timer.flash_on(flash=False)) is True
    clock.advance(20)
    assert timer.flash_on() is True and timer.text().startswith("+")
    assert PresentationTimer().flash_on() is False


# -- settings and keep-awake -----------------------------------------------------------------

def test_settings_have_defaults_survive_the_store_and_ignore_bad_values(ctx):
    assert PresentationSettings.load() == PresentationSettings()
    changed = PresentationSettings(laser_color="#00ff00", timer_duration_minutes=20, confirm_links=False)
    changed.save()
    assert PresentationSettings.load() == changed
    assert app_settings.get(ctx, "presentation") is None            # per user, not in the project
    layout_settings.set("presentation", {"laser_color": 5, "pen_width": "wide", "confirm_links": False})
    loaded = PresentationSettings.load()
    assert loaded.laser_color == "#ff2020" and loaded.pen_width == 0.012 and loaded.confirm_links is False


class FakeBackend:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def start(self):
        self.calls.append("start")
        if self.fail:
            raise OSError("no bus")

    def stop(self):
        self.calls.append("stop")


def test_keep_awake_starts_and_stops_once_and_never_fails_the_show():
    backend = FakeBackend()
    awake = KeepAwake(backend)
    awake.start()
    awake.start()
    assert awake.active
    awake.stop()
    awake.stop()
    assert backend.calls == ["start", "stop"] and not awake.active
    broken = KeepAwake(FakeBackend(fail=True))
    broken.start()
    assert not broken.active
    broken.stop()


# -- frames from the .nav file ---------------------------------------------------------------

NAV = "\n".join([r"\headcommand {\slideentry {0}{0}{1}{1/1}{}{0}}"] + [
    rf"\headcommand {{\beamer@framepages {{{first}}}{{{last}}}}}" for first, last in ((1, 1), (2, 4), (5, 5), (6, 6))])


def test_the_nav_file_groups_pages_into_slides_with_steps():
    from slidemage.presentation.frames import parse_nav
    frames = parse_nav(NAV, 6)
    assert frames.count == 4 and frames.frames == ((0, 0), (1, 3), (4, 4), (5, 5))
    assert frames.frame_of(0) == (1, 1, 1) and frames.frame_of(2) == (2, 2, 3) and frames.frame_of(5) == (4, 1, 1)
    assert frames.first_page(2) == 1 and frames.first_page(3) == 4
    assert frames.first_page(0) == 0 and frames.first_page(99) == 5          # clamped to the existing slides


def test_a_nav_file_that_does_not_fit_the_pdf_is_not_used():
    from slidemage.presentation.frames import parse_nav
    assert parse_nav(NAV, 7) is None and parse_nav(NAV, 5) is None and parse_nav("", 6) is None
    assert parse_nav(r"\beamer@framepages {1}{3}" + "\n" + r"\beamer@framepages {2}{6}", 6) is None   # overlapping frames
    assert parse_nav(r"\beamer@framepages {2}{6}", 6) is None                                       # not from page 1


def test_the_kept_nav_of_the_presenter_compile_is_found_and_checked_against_the_pdf(ctx, tmp_path):
    from types import SimpleNamespace

    from slidemage import compile_records
    from slidemage.presentation import frames as frames_mod
    deck = SimpleNamespace(name="talk", supports_version=False, text=r"\decklanguage[en]" + "\n")
    pdf = tmp_path / "talk-presenter.pdf"
    kept = compile_records.aux_dir(ctx.build_dir, "talk-presenter")
    kept.mkdir(parents=True)
    (kept / "talk-presenter.nav").write_text(NAV, encoding="utf-8")
    assert frames_mod.load_for(ctx, deck, pdf, 6).count == 4
    assert frames_mod.load_for(ctx, deck, pdf, 9) is None                  # another PDF: fall back to page numbers
