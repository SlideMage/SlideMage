# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: F811 -- the fixtures of test_centre_gui are imported and used by name
"""The reveal-step bar: the widget on its own, and in the Preview (renders are faked; the PDFs are real)."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from slidemage import preview_target, render_lookup, reveal_steps, slide_snapshot
from slidemage.deck_scan import parse_chapters
from slidemage.step_renders import FOREGROUND
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.reveal_bar import RevealBar, RowSpec, StepTrack
from test_centre_gui import FRAME, centre, deck, project  # noqa: F401 -- fixtures


def plan(n, included, **kwargs):
    return reveal_steps.StepPlan(n, frozenset(included), **kwargs)


def tokens():
    return ThemeManager().tokens


def rows_of(n=4, included=(1, 3), views=("instructor", "during-course", "after-course")):
    return {view: RowSpec(view, plan(n, included)) for view in views}


def test_moving_from_a_step_the_narrowed_stops_do_not_have_goes_to_the_next_one(qapp):
    bar = RevealBar(tokens)
    bar.set_state("instructor", 2, rows_of(), False)
    bar.deck_only.setChecked(True)
    bar.move(1)
    assert bar.step == 3
    bar.set_state("instructor", 2, rows_of(), False)
    bar.move(-1)
    assert bar.step == 1
    bar.move(-1)
    assert bar.step == 1


def test_the_bar_keeps_its_room_so_the_slide_above_it_does_not_move(qapp):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    window = QWidget()
    layout = QVBoxLayout(window)
    page = QWidget()
    layout.addWidget(page, 1)
    bar = RevealBar(tokens)
    layout.addWidget(bar)
    window.resize(800, 600)
    window.show()

    def height():
        for _ in range(3):
            QApplication.processEvents()
        return page.height()

    one = {"instructor": RowSpec("instructor", plan(1, {1}, marked=False))}
    plain = {"instructor": RowSpec("instructor", plan(4, {1, 3}, marked=False))}
    collapsed = height()
    bar.set_state("instructor", 1, one, False)
    assert bar.isHidden()
    for state in (plain, rows_of(), one):
        bar.set_state("instructor", 1, state, False)
        assert height() == collapsed
    bar.show_counting()
    assert height() == collapsed
    bar.setVisible(False)                              # no slide on show
    assert height() == collapsed
    bar.set_expanded(True)
    bar.set_state("instructor", 3, rows_of(), False)
    expanded = height()
    assert expanded < collapsed
    for step in (lambda: bar.show_counting(), lambda: bar.set_state("instructor", 1, one, False),
                 lambda: bar.set_state("instructor", 3, rows_of(), False)):
        step()
        assert height() == expanded                    # also while the next slide's steps are counted
    bar.set_expanded(False)
    assert height() == collapsed
    window.close()


def test_the_slides_own_frame_spec_is_a_third_kind_of_tick(qapp):
    bar = RevealBar(tokens)
    own = {"instructor": RowSpec("instructor", plan(4, {1, 2, 3, 4}, slide_excluded=frozenset({1}), marked=True))}
    bar.set_state("instructor", 2, own, False)
    assert bar.track.state_of(1) == "slide" and bar.track.state_of(2) == "included"
    assert "left out by the slide's own frame" in bar.track.tip_for(1)
    bar.set_state("instructor", 1, own, False)
    assert bar.label.full_text().endswith("left out by the slide itself")


def test_ticks_render_to_an_image(qapp):
    bar = RevealBar(tokens)
    bar.resize(640, 40)
    bar.set_state("instructor", 2, rows_of(), True)
    bar.show()
    image = bar.grab().toImage()
    assert not image.isNull()
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


def test_expanded_rows_select_views_and_only_editable_ticks_toggle(qapp):
    bar = RevealBar(tokens)
    rows = {
        "instructor": RowSpec("instructor", plan(4, {1, 3}), editable=False, reason="A pinned version."),
        "during-course": RowSpec("during-course", plan(3, {1}), editable=True, reason="Numbered per version."),
        "after-course": RowSpec("after-course", None),
    }
    bar.set_state("instructor", 4, rows, False)
    views, toggled = [], []
    bar.view_requested.connect(views.append)
    bar.tick_toggled.connect(lambda view, step: toggled.append((view, step)))
    bar.set_expanded(True)
    bar.resize(600, 120)
    bar.show()

    note, editable = bar._rows_widgets["during-course"]
    assert editable.stops == [1, 2, 3] and editable.state_of(1) == "included"
    assert note.full_text() == "Numbered per version."
    assert bar._rows_widgets["after-course"][1].counting
    editable.selected.emit(2)
    assert views == ["during-course"] and bar.step == 2
    locked_note, locked = bar._rows_widgets["instructor"]
    assert "read-only: A pinned version." in locked_note.full_text()
    for track in (editable, locked):
        QTest.mouseClick(track, Qt.MouseButton.LeftButton, pos=QPoint(int(track._x(1)), track.height() // 2))
        assert toggled == [("during-course", 2)]
    bar.set_expanded(False)
    assert bar._rows_holder.isHidden()
    bar.hide()


COLORS = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0))


def write_steps_pdf(path, colors):
    with pymupdf.open() as doc:
        for color in colors:
            page = doc.new_page(width=320, height=180)
            page.draw_rect(page.rect, color=color, fill=color)
        doc.save(path)


@pytest.fixture
def steps_renders(tmp_path, monkeypatch):
    pdf = tmp_path / "steps.pdf"
    write_steps_pdf(pdf, COLORS)
    calls = []

    def fake(kind):
        def render(target, *args, **kwargs):
            calls.append((kind, target.id_slug, args, kwargs))
            return pdf
        return render

    monkeypatch.setattr(slide_snapshot, "FULL_SIZE", (160, 90))
    monkeypatch.setattr(preview_target, "render", fake("saved"))
    monkeypatch.setattr(preview_target, "render_text", fake("buffer"))
    monkeypatch.setattr(preview_view, "PROBE_MS", 50)
    return calls


def renders_of_first_slide(calls):
    return [call for call in calls if call[1] == "aaa-EN-One"]


def wait_for(condition, seconds=15):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert condition()


def render_slide(centre, slide="aaa"):
    preview = centre.preview
    centre.state.set_focused_slide(slide)
    preview.render_now()
    wait_for(lambda: not preview._busy and preview._reveal.isVisibleTo(preview))
    return preview._reveal


def centre_color(centre):
    pixmap = centre.preview._page.pixmap
    image = pixmap.toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return (round(color.red() / 255), round(color.green() / 255), round(color.blue() / 255))


def test_a_plain_slide_reuses_its_render_and_remembers_the_selected_step(centre, steps_renders):
    preview = centre.preview
    bar = render_slide(centre)
    assert bar.track.stops == [1, 2, 3, 4] and bar.step == 4
    assert bar.label.full_text() == "Step 4 of 4" and centre_color(centre) == COLORS[-1]
    assert bar.deck_only.isHidden() and bar.track.state_of(2) == "plain"
    bar.set_expanded(True)
    wait_for(lambda: bar._rows_widgets and all(not track.counting for _, track in bar._rows_widgets.values()))
    [render] = renders_of_first_slide(steps_renders)
    assert render[3]["all_steps"] is False
    assert not row_track(preview, "instructor").edit_mode

    left = next(shortcut for shortcut in preview.findChildren(QShortcut)
                if shortcut.key().toString() == "Alt+Left")
    left.activated.emit()
    assert bar.step == 3 and centre_color(centre) == COLORS[2]
    bar.track.selected.emit(2)
    assert centre_color(centre) == COLORS[1]
    centre.state.set_focused_slide("bbb")
    assert bar.isHidden()
    centre.state.set_focused_slide("aaa")
    assert bar.step == 2
    centre.state.set_view("during-course")
    assert bar.isHidden()


def use_steps_deck(centre, steps):
    deck = centre.state.deck
    text = (deck.text.split(r"\begin{document}")[0] + "\\begin{document}\n\\section{Part}\n"
            f"\\slidestep{{aaa-EN-One}}[instructor]{{{steps}}}\n\\end{{document}}\n")
    deck.path.write_text(text, encoding="utf-8", newline="")
    centre.state.set_deck(replace(deck, text=text, chapters=parse_chapters(text)))


def test_the_page_of_a_slidestep_call_is_the_step_not_the_decks_last_included_one(centre, steps_renders):
    use_steps_deck(centre, "1,3")
    bar = render_slide(centre)
    assert [kwargs.get("all_steps") for _kind, _id, _args, kwargs in renders_of_first_slide(steps_renders)] == [False, True]
    assert bar.step == 4 and centre_color(centre) == COLORS[3]                 # the slide's true last step
    assert [bar.track.state_of(s) for s in (1, 2, 3, 4)] == ["included", "excluded", "included", "excluded"]
    assert bar.label.full_text() == "Step 4 of 4 · not in Instructor"
    bar.deck_only.setChecked(True)
    assert bar.track.stops == [1, 3]
    bar.move(-1)
    assert bar.step == 3 and centre_color(centre) == COLORS[2]
    bar.move(-1)
    assert bar.step == 1 and bar.label.full_text() == "Step 1 of 4 · in Instructor"


def test_expanding_a_version_dependent_slide_counts_its_editable_rows(centre, steps_renders, project, deck):
    (project / "aaa-EN-One-current.tex").write_text(
        "\\setSlideVersion{1-1-0}\n" + FRAME % "First" + "\\conditionalpause\n", encoding="utf-8")
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    centre.preview.edit_deck = lambda *a, **k: True
    bar = render_slide(centre)
    bar.set_expanded(True)
    wait_for(lambda: bar._rows_widgets and all(not track.counting for _note, track in bar._rows_widgets.values()), 30)
    assert {v: t.stops for v, (_n, t) in bar._rows_widgets.items()} == {
        "instructor": [1, 2, 3, 4], "during-course": [1, 2, 3, 4], "after-course": [1, 2, 3, 4]}
    # render(target, view, ...) or render_text(target, text, view, ...): saved renders take either path
    views = [args[1] if kind == "buffer" else args[0] for kind, _i, args, _kw in renders_of_first_slide(steps_renders) if args]
    assert {"during-course", "after-course"} <= set(views)
    note, track = bar._rows_widgets["during-course"]
    assert track.edit_mode and note.full_text().startswith("Numbered per version")
    bar._rows_widgets["after-course"][1].selected.emit(2)
    assert centre.state.view == "after-course"


def test_while_idle_the_neighbouring_slides_get_their_steps_counted_too(centre, steps_renders):
    centre.state.set_focused_slide("aaa")
    preview = centre.preview
    assert preview._reveal.isHidden()
    wait_for(lambda: len(preview.model.steps.pages) == 3, 40)             # aaa and its two neighbours, bbb and ccc
    counted = sorted({call[1] for call in steps_renders})
    assert counted == ["aaa-EN-One", "bbb-EN-Two", "ccc-DE-Drei"]
    assert all(call[3].get("all_steps") for call in steps_renders)
    assert preview._reveal.step == 4
    centre.state.set_focused_slide("bbb")
    wait_for(lambda: preview._reveal.isVisibleTo(preview) and preview._reveal.track.stops == [1, 2, 3, 4], 40)


def test_a_failing_background_render_is_not_asked_for_again(centre, steps_renders, monkeypatch):
    def broken(target, *args, **kwargs):
        steps_renders.append(("broken", target.id_slug, args, kwargs))
        raise RuntimeError("no TeX")

    monkeypatch.setattr(preview_target, "render", broken)
    monkeypatch.setattr(preview_target, "render_text", broken)     # saved renders take this path too
    centre.state.set_focused_slide("aaa")
    preview = centre.preview
    wait_for(lambda: len(preview.model.steps.failed) == 3, 40)
    count = len(steps_renders)
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.02)
    assert len(steps_renders) == count and preview._reveal.isHidden()


@pytest.fixture
def editing(centre, deck, steps_renders):
    """Record what Preview would write through the deck editor."""
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    edits = []

    def fake_edit(failed, summary, change, cleanup=None):
        current = centre.state.deck
        new = change(current.path, current.text)
        edits.append((summary, new, cleanup))
        return new != current.text

    centre.preview.edit_deck = fake_edit
    render_slide(centre).set_expanded(True)
    return centre.preview, edits


def row_track(preview, view):
    return preview._reveal._rows_widgets[view][1]


def test_ticks_of_a_plain_slide_are_editable_and_a_click_rewrites_the_deck(editing):
    preview, edits = editing
    track = row_track(preview, "during-course")
    assert track.edit_mode and [track.state_of(s) for s in (1, 2, 3, 4)] == ["included"] * 4
    preview._reveal.tick_toggled.emit("during-course", 2)
    (_summary, new, cleanup), = edits
    assert "\\slidestep{aaa-EN-One}[instructor,after-course]{1-}\n" in new
    assert "\\slidestep{aaa-EN-One}[during-course]{1,3,4}\n" in new
    assert callable(cleanup)


def test_the_last_step_of_a_version_cannot_be_ticked_off(centre, steps_renders):
    use_steps_deck(centre, "2")
    told, edits = [], []
    centre.preview.app.toast = SimpleNamespace(show_message=told.append)
    centre.preview.edit_deck = lambda *args, **kwargs: edits.append(args) or True
    render_slide(centre).set_expanded(True)
    centre.preview._reveal.tick_toggled.emit("instructor", 2)
    assert edits == [] and told and "at least one step" in told[0]
    centre.preview._reveal.tick_toggled.emit("instructor", 3)             # adding a step is fine
    assert len(edits) == 1


def test_a_pinned_call_has_nothing_to_edit_and_says_why(centre, deck, steps_renders):
    deck.path.write_text(deck.text, encoding="utf-8", newline="")
    centre.preview.edit_deck = lambda *a, **k: pytest.fail("a pinned call must not be edited")
    bar = render_slide(centre, "bbb")
    bar.set_expanded(True)
    track = row_track(centre.preview, "instructor")
    assert not track.edit_mode and "pinned" in bar._rows_widgets["instructor"][0].full_text()
    bar.tick_toggled.emit("instructor", 1)                      # even a stray signal does nothing


def test_a_buffer_with_different_steps_cannot_rewrite_the_deck(editing, tmp_path, monkeypatch):
    preview, edits = editing
    pdf = tmp_path / "draft.pdf"
    write_steps_pdf(pdf, COLORS[:3])
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: pdf)
    preview.state.set_mode("split")
    preview._buffer = lambda: "% unsaved\n"
    preview.render_buffer()
    bar = preview._reveal
    wait_for(lambda: not preview._busy and bar.track.draft)
    assert bar.label.full_text() == "Step 3 of 3 · buffer"
    note, track = bar._rows_widgets["instructor"]
    assert track.draft and not track.edit_mode and "Save the slide" in note.full_text()
    bar.tick_toggled.emit("instructor", 2)
    assert edits == []
    preview._on_menu("scope:region")
    assert preview.model.adhoc.full


def png_of(color):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    image, data = QImage(16, 9, QImage.Format.Format_RGB32), QByteArray()
    image.fill(color)
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def pausing(project):
    for name in ("aaa-EN-One", "bbb-EN-Two", "ccc-DE-Drei"):
        (project / f"{name}-current.tex").write_text(FRAME % "First" + "\\pause\nMore\n", encoding="utf-8")


def test_selecting_a_b_and_c_in_a_row_counts_only_c(centre, steps_renders, pausing, monkeypatch):
    preview = centre.preview
    preview._settle.setInterval(300)
    monkeypatch.setattr(preview_view, "PROBE_MS", 60_000)
    asked = []
    request_steps = preview._request_steps

    def request(target, key, text, draft, priority):
        if priority == FOREGROUND:
            asked.append(target.id_slug)
        request_steps(target, key, text, draft, priority)

    monkeypatch.setattr(preview, "_request_steps", request)
    for slide in ("aaa", "bbb", "ccc"):
        centre.state.set_focused_slide(slide)
        if slide == "aaa":
            assert preview._reveal.isVisibleTo(preview)
        QApplication.processEvents()
        assert preview._reveal.track.counting and not asked and not steps_renders
    wait_for(lambda: asked, 40)
    assert asked == ["ccc-DE-Drei"]
    wait_for(lambda: preview._reveal.track.stops == [1, 2, 3, 4], 40)


def test_the_stored_steps_are_read_and_decoded_off_the_gui_thread(centre, steps_renders, pausing, monkeypatch):
    loads, preview = [], centre.preview

    class Counting(preview_view.QPixmap):
        def loadFromData(self, *args, **kwargs):
            loads.append(threading.current_thread() is threading.main_thread())
            return super().loadFromData(*args, **kwargs)

    monkeypatch.setattr(preview_view, "QPixmap", Counting)
    colors = [0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00]
    calls = []

    def pages(record):
        calls.append(threading.current_thread() is threading.main_thread())
        return [png_of(color) for color in colors]
    store = SimpleNamespace(pages=pages)
    resolver = SimpleNamespace(store=store)

    def select(request, *, strict=False):
        assert request["resolver"] is resolver
        if strict:
            assert request["spec"].options.all_steps
            return "current", {}
        return "missing", None

    monkeypatch.setattr(render_lookup, "select", select)
    preview.app.background = SimpleNamespace(renderer=SimpleNamespace(resolver=resolver, store=store))
    centre.state.set_focused_slide("aaa")
    bar = preview._reveal
    wait_for(lambda: bar.track.stops == [1, 2, 3, 4], 40)
    wait_for(lambda: preview._page.pixmap is not None, 40)           # no slide page: the step bar's page is shown
    assert not any(loads) and not steps_renders
    assert calls and not any(calls)
    assert centre_color(centre) == COLORS[-1]
