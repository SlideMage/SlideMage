# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Characterization of the Preview pane's caching and lookup state (review item D1).

These tests pin the transitions that once caused flicker, "Counting…" and stale steps. They read the pane's state
only through `Probe`, so they stay valid while that state moves out of the widget into preview_model."""

import gc
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QPixmap

from slidemage import preview_target
from slidemage.fileio import text_sha256
from slidemage.project import ProjectContext
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view
from slidemage.ui.workspace.state import WorkspaceState


class Probe:
    """The one place that knows where the pane keeps its state."""

    def __init__(self, view):
        self.view = view

    @property
    def lookups(self):
        return self.view.model.lookups.slots

    @property
    def step_pages(self):
        return self.view.model.steps.pages

    @property
    def step_choice(self):
        return self.view.model.steps.choice

    @property
    def step_recheck(self):
        return self.view.model.steps.recheck

    @property
    def adhoc(self):
        return self.view.model.adhoc.value

    def hold_page(self, key, pixmap, mtime, text):
        self.view.model.pixmaps.put(key, pixmap, mtime, text_sha256(text), 'digest')

    def held_page(self, key):
        return self.view.model.pixmaps.get(key)

    def set_adhoc(self, target, pixmap, text):
        spec = preview_view.PreviewRequest(target, preview_view.SourceRevision.capture(target.source_path, text),
                                           self.view.state.view, self.view.language)
        result = preview_view._PageResult(self.view._generation, spec, 'rendered',
                                          decoded=(0, str(pixmap.cacheKey()), pixmap))
        self.view.model.adhoc.hold(result, text)


@pytest.fixture(autouse=True)
def collect_garbage_first():
    gc.collect()


@pytest.fixture
def pane(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    app = SimpleNamespace(theme=ThemeManager(), log=lambda *_: None, project=ctx)
    monkeypatch.setattr(preview_view, "Thread", lambda **kw: SimpleNamespace(start=lambda: None))
    buffer = ["BODY"]
    view = preview_view.PreviewPane(app, WorkspaceState(ctx), lambda: buffer[0])
    folder = tmp_path / "slides"
    folder.mkdir()
    targets = []
    for name in ("abc-EN-One-current.tex", "def-EN-Two-current.tex"):
        (folder / name).write_text("BODY")
        targets.append(preview_target.for_path(ctx, folder / name))
    view.show_slide(targets[0], None, "One", "")
    view.buffer = buffer
    yield view, targets, Probe(view)
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    view._dispose()
    view.model.pixmaps.clear()
    view.model.adhoc.value = None
    view._page.pixmap = None
    if isValid(view):
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def key_of(view, target):
    return (target.key, view.state.view, view.language)


def test_a_selection_change_drops_the_pending_lookups(pane, qapp):
    view, (one, two), probe = pane
    gate, arrived = threading.Event(), []
    view._look_up('page', ('ident',), lambda: gate.wait(5) and 'found', arrived.append)
    view._look_up(('steps', 'k'), 'k', lambda: 'steps', arrived.append)
    assert 'page' in probe.lookups and ('steps', 'k') in probe.lookups
    view.show_slide(two, None, "Two", "")
    assert ('steps', 'k') not in probe.lookups    # dropped with the selection ...
    identity = probe.lookups['page'][0][1]        # ... the one now out is the new slide's own check
    assert identity[0] == two.key and identity[4] != ('ident',)
    gate.set()
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert arrived == []                          # and nothing they found is shown for the new slide


def test_a_lookup_for_the_same_slot_and_identity_is_not_started_twice_and_a_newer_one_replaces_it(pane):
    view, (one, _two), probe = pane
    gate, ran = threading.Event(), []
    view._look_up('page', 'a', lambda: ran.append('a') or gate.wait(5), lambda found: None)
    first = probe.lookups['page']
    view._look_up('page', 'a', lambda: ran.append('again'), lambda found: None)
    assert probe.lookups['page'] is first
    view._look_up('page', 'b', lambda: ran.append('b'), lambda found: None)
    assert probe.lookups['page'] is not first and probe.lookups['page'][0][1] == 'b'
    gate.set()


def step_result(view, target, *pages):
    spec = preview_view.PreviewRequest(target, preview_view.SourceRevision.capture(target.source_path),
                                       view.state.view, view.language, preview_view.RenderOptions(all_steps=True))
    return preview_view._PageResult(view._generation, spec, 'current' if pages else 'missing', pages=pages)


def test_a_picked_step_survives_scrolling_to_the_next_slide_and_back(pane):
    view, (one, two), probe = pane
    view.set_step_choice(one.source_path, 2)
    key = view._current_steps(one)[0]
    view._steps_found(key, step_result(view, one, b'1', b'2', b'3'))
    assert key in probe.step_pages
    view.show_slide(two, None, "Two", "")
    assert not probe.step_pages                   # the page lists belong to the selection ...
    view.show_slide(one, None, "One", "")
    assert probe.step_choice == {one.source_path: 2}   # ... the pick belongs to the slide
    view.set_step_choice(one.source_path, None)
    assert probe.step_choice == {}


def test_counting_is_not_shown_while_the_saved_step_lists_are_rechecked(pane, qapp, monkeypatch):
    view, (one, _two), probe = pane
    view.buffer[0] = None
    one.source_path.write_text('\\onslide<2>{x} BODY')
    view.show_slide(one, None, "One", "")
    key = view._current_steps(one)[0]
    monkeypatch.setattr(view, '_adopt_stored_steps', lambda *a, **kw: None)     # the store answers later
    view._steps_found(key, step_result(view, one, b'1', b'2'))
    view.show()
    view._poll_selection()
    assert key in probe.step_recheck and key in probe.step_pages
    assert not view._reveal.track.counting        # the lists stay on show until the store answers
    view._steps_found(key, step_result(view, one))                  # the store no longer has them as current
    assert key not in probe.step_pages


def test_the_adhoc_render_is_dropped_with_the_slide_and_kept_for_the_poll(pane):
    view, (one, two), probe = pane
    probe.set_adhoc(one, QPixmap(8, 8), 'BODY')
    view._poll_selection()
    assert probe.adhoc is not None
    view.show_slide(two, None, "Two", "")
    assert probe.adhoc is None


def test_a_view_change_drops_lookups_and_step_lists_but_keeps_held_pages(pane):
    view, (one, _two), probe = pane
    key = key_of(view, one)
    probe.hold_page(key, QPixmap(8, 8), preview_view._mtime(one.source_path), 'BODY')
    view._steps_found(view._current_steps(one)[0], step_result(view, one, b'1', b'2'))
    view._look_up('page', 'x', lambda: None, lambda found: None)
    view.state.set_view('after-course')
    assert not probe.step_pages
    assert probe.lookups['page'][0][1][1] == 'after-course'    # the old check is gone: this is the new view's own
    assert probe.held_page(key) is not None       # kept for a return visit
