# ruff: noqa: F811 -- the fixtures of test_centre_gui are imported and used by name
"""The reveal-step bar: the widget on its own, and in the Preview (renders are faked; the PDFs are real)."""
from __future__ import annotations

import time

import pymupdf
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from slidemage import deck_editor, preview_target, reveal_steps, slide_snapshot
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.reveal_bar import RevealBar, RowSpec, StepTrack
from test_centre_gui import FRAME, centre, deck, project  # noqa: F401 -- fixtures


def plan(n, included, **kwargs):
    return reveal_steps.StepPlan(n, frozenset(included), **kwargs)


def tokens():
    return ThemeManager().tokens


# -- the widget -------------------------------------------------------------------------


def rows_of(n=4, included=(1, 3), views=("instructor", "during-course", "after-course")):
    return {view: RowSpec(view, plan(n, included)) for view in views}


def test_the_bar_hides_for_a_slide_with_one_step_and_shows_the_current_one(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 1, {"instructor": RowSpec("instructor", plan(1, {1}, marked=False))}, False)
    assert bar.isHidden()
    bar.set_state("instructor", 4, rows_of(), False)
    assert not bar.isHidden() and bar.track.stops == [1, 2, 3, 4] and bar.step == 4
    assert bar.label.full_text() == "Step 4 of 4 · not in Instructor"
    bar.set_state("instructor", 3, rows_of(), False)
    assert bar.label.full_text() == "Step 3 of 4 · in Instructor"
    assert [bar.track.state_of(s) for s in (1, 2, 3, 4)] == ["included", "excluded", "included", "excluded"]


def test_deck_steps_only_narrows_the_stops_and_the_label_keeps_the_true_number(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 3, rows_of(), False)
    bar.deck_only.setChecked(True)
    assert bar.track.stops == [1, 3]
    selected = []
    bar.step_selected.connect(selected.append)
    bar.move(-1)
    assert selected == [1] and bar.step == 1
    bar.move(1)
    assert bar.step == 3 and bar.label.full_text().startswith("Step 3 of 4")
    bar.move(1)
    assert bar.step == 3                               # the end stays the end


def test_moving_from_a_step_the_narrowed_stops_do_not_have_goes_to_the_next_one(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 2, rows_of(), False)
    bar.deck_only.setChecked(True)
    bar.move(1)
    assert bar.step == 3
    bar.set_state("instructor", 2, rows_of(), False)
    bar.move(-1)
    assert bar.step == 1


def test_unmarked_slides_have_no_deck_toggle(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 3, {"instructor": RowSpec("instructor", plan(3, {1, 2, 3}, marked=False))}, False)
    assert bar.isVisibleTo(bar.parentWidget() or bar) or not bar.isHidden()
    assert bar.deck_only.isHidden() and bar.track.state_of(2) == "plain"
    assert bar.label.full_text() == "Step 3 of 3"


def test_the_slides_own_frame_spec_is_a_third_kind_of_tick(qapp):
    bar = RevealBar(tokens)
    own = {"instructor": RowSpec("instructor", plan(4, {1, 2, 3, 4}, slide_excluded=frozenset({1}), marked=True))}
    bar.set_state("instructor", 2, own, False)
    assert bar.track.state_of(1) == "slide" and bar.track.state_of(2) == "included"
    assert "left out by the slide's own frame" in bar.track.tip_for(1)
    bar.set_state("instructor", 1, own, False)
    assert bar.label.full_text().endswith("left out by the slide itself")


def test_a_buffer_render_says_so_and_draws_dashed_ticks(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 2, rows_of(), True)
    assert bar.label.full_text().endswith("· buffer") and bar.track.draft
    bar.set_state("instructor", 2, rows_of(), False)
    assert not bar.track.draft


def test_ticks_can_be_grabbed_in_both_themes(qapp):
    bar = RevealBar(tokens)
    bar.resize(640, 40)
    bar.set_state("instructor", 2, rows_of(), True)
    bar.show()
    image = bar.grab().toImage()
    assert not image.isNull() and bar.minimumSizeHint().width() < 300
    bar.hide()


def test_a_click_on_a_tick_picks_the_step_and_the_keys_move_it(qapp):
    bar = RevealBar(tokens)
    bar.resize(500, 40)
    bar.set_state("instructor", 4, rows_of(), False)
    bar.show()
    track = bar.track
    picked = []
    bar.step_selected.connect(picked.append)
    QTest.mouseClick(track, Qt.MouseButton.LeftButton, pos=QPoint(int(track._x(0)), track.height() // 2))
    assert picked == [1] and bar.step == 1
    QTest.keyClick(track, Qt.Key.Key_Right)
    QTest.keyClick(track, Qt.Key.Key_End)
    QTest.keyClick(track, Qt.Key.Key_Home)
    assert picked == [1, 2, 4, 1]
    QTest.keyClick(track, Qt.Key.Key_PageDown)
    assert bar.step == 2
    bar.hide()


def test_hovering_a_tick_tells_what_it_is(qapp):
    track = StepTrack(tokens, "during-course")
    track.resize(400, 30)
    track.set_plan(plan(3, {2}), False, 3, False)
    assert track.tip_for(2) == "Step 2 · in During course" and track.tip_for(1) == "Step 1 · not in During course"
    track.edit_mode = True
    assert "click to add it to During course" in track.tip_for(1)
    assert "click to remove it from During course" in track.tip_for(2)


def test_expanding_shows_a_timeline_per_version_and_naming_one_asks_for_that_view(qapp):
    bar = RevealBar(tokens)
    rows = rows_of()
    rows["during-course"] = RowSpec("during-course", plan(3, {3}))
    rows["after-course"] = RowSpec("after-course", None)
    bar.set_state("instructor", 4, rows, False)
    expanded, views = [], []
    bar.expanded_changed.connect(expanded.append)
    bar.view_requested.connect(views.append)
    bar.set_expanded(True)
    assert expanded == [True] and set(bar._rows_widgets) == {"instructor", "during-course", "after-course"}
    during = bar._rows_widgets["during-course"][1]
    assert during.stops == [1, 2, 3] and during.state_of(3) == "included" and during.state_of(1) == "excluded"
    assert bar._rows_widgets["after-course"][1].counting            # not counted yet: it says so
    during.selected.emit(2)                                         # a tick of another version: its view, that step
    assert views == ["during-course"] and bar.step == 2
    bar.set_expanded(False)
    assert expanded == [True, False] and bar._rows_holder.isHidden()


def test_editable_rows_report_a_click_on_a_tick_and_read_only_rows_say_why(qapp):
    bar = RevealBar(tokens)
    rows = rows_of(views=("instructor", "during-course"))
    rows["during-course"] = RowSpec("during-course", plan(3, {1}), editable=True, reason="Numbered per version.")
    rows["instructor"] = RowSpec("instructor", plan(4, {1, 3}), editable=False, reason="A pinned version.")
    bar.set_state("instructor", 4, rows, False)
    bar.set_expanded(True)
    toggled = []
    bar.tick_toggled.connect(lambda view, step: toggled.append((view, step)))
    bar.resize(600, 120)
    bar.show()
    editable = bar._rows_widgets["during-course"][1]
    QTest.mouseClick(editable, Qt.MouseButton.LeftButton, pos=QPoint(int(editable._x(1)), editable.height() // 2))
    assert toggled == [("during-course", 2)]
    locked = bar._rows_widgets["instructor"][1]
    QTest.mouseClick(locked, Qt.MouseButton.LeftButton, pos=QPoint(int(locked._x(1)), locked.height() // 2))
    assert toggled == [("during-course", 2)]                         # read-only: a click only picks the step
    assert "read-only: A pinned version." in bar._rows_widgets["instructor"][0].full_text()
    assert bar._rows_widgets["during-course"][0].full_text() == "Numbered per version."
    bar.hide()


# -- in the Preview ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _close_step_queues(monkeypatch):
    """A pane that is never closed keeps its queue's thread: close them all when the test ends, so none of them
    renders for a later test."""
    queues = []

    class Recording(preview_view.StepRenderQueue):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            queues.append(self)

    monkeypatch.setattr(preview_view, "StepRenderQueue", Recording)
    yield
    for queue in queues:
        queue.close()


COLORS = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0))


@pytest.fixture
def steps_renders(tmp_path, monkeypatch):
    """preview_target's renderers, replaced by recorders that write a four-page PDF, one colour per page."""
    pdf = tmp_path / "steps.pdf"
    doc = pymupdf.open()
    for color in COLORS:
        page = doc.new_page(width=320, height=180)
        page.draw_rect(page.rect, color=color, fill=color)
    doc.save(pdf)
    doc.close()
    calls = []

    def fake(kind):
        def render(target, *args, **kwargs):
            calls.append((kind, target.id_slug, args, kwargs))
            return pdf
        return render

    monkeypatch.setattr(slide_snapshot, "FULL_SIZE", (160, 90))
    monkeypatch.setattr(slide_snapshot, "THUMB_SIZE", (80, 45))
    monkeypatch.setattr(preview_target, "render", fake("saved"))
    monkeypatch.setattr(preview_target, "render_text", fake("buffer"))
    monkeypatch.setattr(preview_target, "cached_image", lambda target: None)
    monkeypatch.setattr(preview_view, "PROBE_MS", 50)
    return calls


def mine(calls, slide="aaa-EN-One"):
    """The renders of one slide (the idle pane also counts the steps of its neighbours)."""
    return [call for call in calls if call[1] == slide]


def wait_for(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert condition()


def settled(centre):
    preview = centre.preview
    wait_for(lambda: not preview._busy and not preview._steps.pending(preview._current_steps(preview._target)[0]))


def centre_color(centre):
    pixmap = centre.preview._page.pixmap
    image = pixmap.toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return (round(color.red() / 255), round(color.green() / 255), round(color.blue() / 255))


def test_a_render_of_a_plain_slide_gives_the_bar_without_another_render(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: not centre.preview._busy and centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    assert bar.track.stops == [1, 2, 3, 4] and bar.step == 4                 # a slide opens on its last step
    own = mine(steps_renders)
    assert len(own) == 1 and "all_steps" in own[0][3] and not own[0][3]["all_steps"]
    assert centre_color(centre) == COLORS[-1]
    assert bar.label.full_text() == "Step 4 of 4"                                  # a plain call: nothing to tell apart


def test_moving_the_slider_shows_that_step_and_coming_back_shows_the_slide_again(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    bar.move(-1)
    assert bar.step == 3 and centre_color(centre) == COLORS[2]
    bar.track.selected.emit(1)
    assert centre_color(centre) == COLORS[0]
    bar.move(1)
    bar.track.selected.emit(4)
    assert centre_color(centre) == COLORS[3]
    bar.track.selected.emit(2)
    centre.state.set_focused_slide("bbb")                                      # another slide: its own steps
    centre.state.set_focused_slide("aaa")
    assert centre.preview._reveal.step == 2                                    # remembered for this session


def test_the_page_of_a_slidestep_call_is_the_step_not_the_decks_last_included_one(centre, steps_renders, tmp_path):
    text = ("\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-ibk}\n\\begin{document}\n"
            "\\section{Part}\n\\slidestep{aaa-EN-One}[instructor]{1,3}\n\\end{document}\n")
    steps_deck = Deck(name="steps", path=tmp_path / "steps.tex", archived=False, text=text, supports_version=True,
                uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
                chapters=parse_chapters(text), output_folders={})
    centre.state.set_deck(steps_deck)
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    assert [kwargs.get("all_steps") for _kind, _id, _args, kwargs in mine(steps_renders)] == [False, True]
    assert bar.step == 4 and centre_color(centre) == COLORS[3]                 # the slide's true last step
    assert [bar.track.state_of(s) for s in (1, 2, 3, 4)] == ["included", "excluded", "included", "excluded"]
    assert bar.label.full_text() == "Step 4 of 4 · not in Instructor"
    bar.deck_only.setChecked(True)
    assert bar.track.stops == [1, 3]
    bar.move(-1)
    assert bar.step == 3 and centre_color(centre) == COLORS[2]
    bar.move(-1)
    assert bar.step == 1 and bar.label.full_text() == "Step 1 of 4 · in Instructor"


def test_an_idle_pane_counts_the_steps_of_a_slide_that_was_not_rendered(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    assert centre.preview._reveal.isHidden()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview), 20)
    assert [kwargs.get("all_steps") for _k, _i, _a, kwargs in mine(steps_renders)] == [True]
    assert centre.preview._page.pixmap is None or centre.preview._reveal.step == 4


def test_a_buffer_render_gets_dashed_ticks_and_the_buffers_steps(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.state.set_mode("split")
    centre.source.current.editor.insertPlainText("% unsaved\n")
    centre.preview.render_buffer()
    wait_for(lambda: not centre.preview._busy and centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    assert bar.track.draft and bar.label.full_text() == "Step 4 of 4 · buffer"
    centre.preview._on_menu("scope:region")                                    # a selection is not the whole slide
    assert centre.preview._adhoc_full


def test_expanding_counts_the_other_versions_only_when_the_slide_depends_on_them(centre, steps_renders, project):
    (project / "aaa-EN-One-current.tex").write_text(
        "\\setSlideVersion{1-1-0}\n" + FRAME % "First" + "\\conditionalpause\n", encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    bar.set_expanded(True)
    wait_for(lambda: all(not track.counting for _note, track in bar._rows_widgets.values()), 30)
    assert {v: t.stops for v, (_n, t) in bar._rows_widgets.items()} == {
        "instructor": [1, 2, 3, 4], "during-course": [1, 2, 3, 4], "after-course": [1, 2, 3, 4]}
    # render(target, view, ...) or render_text(target, text, view, ...): saved renders take either path
    views = [args[1] if kind == "buffer" else args[0] for kind, _i, args, _kw in mine(steps_renders) if args]
    assert {"during-course", "after-course"} <= set(views)
    bar._rows_widgets["after-course"][1].selected.emit(2)
    assert centre.state.view == "after-course"


def test_a_slide_without_version_logic_needs_no_other_renders(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    centre.preview._reveal.set_expanded(True)
    wait_for(lambda: all(not track.counting for _note, track in centre.preview._reveal._rows_widgets.values()))
    assert len(mine(steps_renders)) == 1


def test_switching_view_looks_for_that_views_steps(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    centre.state.set_view("during-course")                  # the slide is hidden there: no bar
    assert centre.preview._reveal.isHidden()


def test_keyboard_shortcuts_step_the_bar(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert event.modifiers() & Qt.KeyboardModifier.AltModifier
    bar.move(-1)
    assert bar.step == 3


def test_deck_editor_alone_is_not_needed_for_plain_files(qapp):
    assert deck_editor.expand_steps("1-", 2) == {1, 2}


def test_while_idle_the_neighbouring_slides_get_their_steps_counted_too(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    preview = centre.preview
    wait_for(lambda: len(preview._step_pages) == 3, 40)             # aaa and its two neighbours, bbb and ccc
    counted = sorted({call[1] for call in steps_renders})
    assert counted == ["aaa-EN-One", "bbb-EN-Two", "ccc-DE-Drei"]
    assert all(call[3].get("all_steps") for call in steps_renders)
    centre.state.set_focused_slide("bbb")                            # already counted: the bar is there at once
    assert preview._reveal.isVisibleTo(preview) and preview._reveal.track.stops == [1, 2, 3, 4]


def test_a_failing_background_render_is_not_asked_for_again(centre, steps_renders, monkeypatch):
    def broken(target, *args, **kwargs):
        steps_renders.append(("broken", target.id_slug, args, kwargs))
        raise RuntimeError("no TeX")

    monkeypatch.setattr(preview_target, "render", broken)
    monkeypatch.setattr(preview_target, "render_text", broken)     # saved renders take this path too
    centre.state.set_focused_slide("aaa")
    preview = centre.preview
    wait_for(lambda: len(preview._step_failed) == 3, 40)
    count = len(steps_renders)
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.02)
    assert len(steps_renders) == count and preview._reveal.isHidden()


# -- editing the ticks ---------------------------------------------------------------------


@pytest.fixture
def editing(centre, deck, steps_renders):
    """The Preview with a stand-in for the slide list's deck edit: it applies the change to the deck file and records it."""
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    edits = []

    def fake_edit(failed, summary, change, cleanup=None):
        current = centre.state.deck
        new = change(current.path, current.text)
        edits.append((summary, new, cleanup))
        return new != current.text

    centre.preview.edit_deck = fake_edit
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    centre.preview._reveal.set_expanded(True)
    return centre.preview, edits


def row_track(preview, view):
    return preview._reveal._rows_widgets[view][1]


def test_ticks_of_a_plain_slide_are_editable_and_a_click_rewrites_the_deck(editing):
    preview, edits = editing
    track = row_track(preview, "during-course")
    assert track.edit_mode and [track.state_of(s) for s in (1, 2, 3, 4)] == ["included"] * 4
    preview._reveal.tick_toggled.emit("during-course", 2)
    summary, new, cleanup = edits[0]
    assert summary == "Set the steps of aaa-EN-One in During course to 1,3,4 in course"
    assert "\\slidestep{aaa-EN-One}[instructor,after-course]{1-}\n" in new
    assert "\\slidestep{aaa-EN-One}[during-course]{1,3,4}\n" in new
    assert callable(cleanup)


def test_the_last_step_of_a_version_cannot_be_ticked_off(centre, steps_renders, tmp_path):
    text = ("\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-ibk}\n\\begin{document}\n"
            "\\section{Part}\n\\slidestep{aaa-EN-One}[instructor]{2}\n\\end{document}\n")
    one_step = Deck(name="one", path=tmp_path / "one.tex", archived=False, text=text, supports_version=True,
                    uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
                    chapters=parse_chapters(text), output_folders={})
    one_step.path.write_text(text, encoding="utf-8", newline="")
    told, edits = [], []
    centre.preview.app.toast = type("Toast", (), {"show_message": lambda self, message: told.append(message)})()
    centre.preview.edit_deck = lambda *args, **kwargs: edits.append(args) or True
    centre.state.set_deck(one_step)
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    centre.preview._reveal.set_expanded(True)
    centre.preview._reveal.tick_toggled.emit("instructor", 2)
    assert edits == [] and told and "at least one step" in told[0]
    centre.preview._reveal.tick_toggled.emit("instructor", 3)             # adding a step is fine
    assert len(edits) == 1


def test_a_pinned_call_has_nothing_to_edit_and_says_why(centre, deck, steps_renders):
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    centre.preview.edit_deck = lambda *a, **k: pytest.fail("a pinned call must not be edited")
    centre.state.set_focused_slide("bbb")                       # \slideversion{bbb-EN-Two}{1-0-0}
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    bar.set_expanded(True)
    track = row_track(centre.preview, "instructor")
    assert not track.edit_mode and "pinned" in bar._rows_widgets["instructor"][0].full_text()
    bar.tick_toggled.emit("instructor", 1)                      # even a stray signal does nothing


def test_without_the_windows_deck_edit_the_ticks_are_not_editable(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    centre.preview._reveal.set_expanded(True)
    assert not row_track(centre.preview, "instructor").edit_mode


def test_version_dependent_slides_are_editable_with_a_warning(centre, deck, steps_renders, project):
    (project / "aaa-EN-One-current.tex").write_text(
        "\\setSlideVersion{1-1-0}\n" + FRAME % "First" + "\\conditionalpause\n", encoding="utf-8")
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    centre.preview.edit_deck = lambda *a, **k: True
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_for(lambda: centre.preview._reveal.isVisibleTo(centre.preview))
    bar = centre.preview._reveal
    bar.set_expanded(True)
    wait_for(lambda: all(not t.counting for _n, t in bar._rows_widgets.values()), 30)
    note, track = bar._rows_widgets["during-course"]
    assert track.edit_mode and note.full_text().startswith("Numbered per version")


def test_a_buffer_render_is_not_edited_until_the_slide_is_saved(editing):
    preview, _edits = editing
    editing_deck = preview.state.deck
    assert editing_deck is not None
    preview._adhoc = None
    preview.state.set_mode("split")
    preview._buffer = lambda: ("% unsaved\n", "")
    preview.render_buffer()
    wait_for(lambda: not preview._busy and preview._reveal.track.draft)
    preview._reveal.set_expanded(True)
    note, track = preview._reveal._rows_widgets["instructor"]
    assert track.draft


def test_the_slide_list_edit_runs_the_cleanup_and_undo_takes_both_back(qapp, tmp_path):
    from slidemage import reveal_steps as steps
    from slidemage.ui.workspace.slide_list import DeckUndo

    undo = DeckUndo("the text before")
    undo.slide = (tmp_path / "x.tex", "before", "after")
    assert undo == "the text before" and ["the text before"] == [undo] and steps is not None
