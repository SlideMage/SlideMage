# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preview pane's model (ui/workspace/preview_model.py), tested without a window or a pane."""

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPixmap

from slidemage.ui.workspace import preview_model as pm


def png(width=8, height=8) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)


def idents(n, view='instructor'):
    return [((f'slide-{i}',), view, 'EN', i) for i in range(n)]


# -- ReadAhead ------------------------------------------------------------------------

def test_the_read_ahead_decodes_only_the_nearest_pages_and_asks_for_the_rest_compressed(qapp):
    ahead = pm.ReadAhead()
    order = [(f't{i}', ident) for i, ident in enumerate(idents(pm.PREFETCHED + 5))]
    reads = ahead.plan(order, now=0.0)
    assert [decode for _t, _i, decode, _held in reads] == [True] * pm.PREFETCHED + [False] * 5
    assert ahead.rank[order[0][1]] == 0 and ahead.rank[order[-1][1]] == len(order) - 1


def test_the_read_ahead_skips_what_is_held_being_read_or_known_missing_until_the_retry(qapp):
    ahead = pm.ReadAhead()
    a, b, c, d = idents(4)
    order = [('a', a), ('b', b), ('c', c), ('d', d)]
    ahead.keep_compressed(a, b'zip', 'ha')        # compressed, but decoded not yet: still wanted (decode)
    ahead.prefetching[b] = Future()               # being read
    ahead.missing[c] = 100.0                      # the store had no page
    assert [(i, decode, held) for _t, i, decode, held in ahead.plan(order, now=110.0)] == [(a, True, b'zip'), (d, True, None)]
    far = [('a', a), ('d', d)] + [(f'x{i}', ident) for i, ident in enumerate(idents(pm.PREFETCHED + 2, 'other'))]
    ahead.keep_compressed(far[-1][1], b'zip', 'hx')     # beyond the nearest PREFETCHED: compressed is enough
    assert far[-1][1] not in [i for _t, i, _d, _h in ahead.plan(far, now=110.0)]
    ahead.plan(order, now=100.0 + pm.PRELOAD_RETRY + 1)
    assert c not in ahead.missing                  # asked again after PRELOAD_RETRY


def test_the_read_ahead_never_plans_one_page_twice(qapp):
    ahead = pm.ReadAhead()
    a, = idents(1)
    assert len(ahead.plan([('a', a), ('again', a)], now=0.0)) == 1


def test_decoded_pages_are_bounded_and_the_longest_unused_gives_way(qapp):
    ahead = pm.ReadAhead()
    ids = idents(pm.PREFETCHED + 1)
    for ident in ids[:pm.PREFETCHED]:
        ahead.hold_decoded(ident, QPixmap(4, 4), 'd')
    ahead.context = ('deck', 'instructor', 'EN')
    assert ahead.page(ids[0], ahead.context, 'd') is not None      # used: the next one to go is ids[1]
    ahead.hold_decoded(ids[-1], QPixmap(4, 4), 'd')
    assert len(ahead.prefetched) == pm.PREFETCHED and ids[1] not in ahead.prefetched and ids[0] in ahead.prefetched


def test_compressed_pages_stay_within_the_byte_budget_and_the_farthest_gives_way(qapp, monkeypatch):
    monkeypatch.setattr(pm, 'PRELOAD_BYTES', 10)
    ahead = pm.ReadAhead()
    a, b, c = idents(3)
    ahead.rank = {a: 0, b: 1, c: 2}
    ahead.keep_compressed(b, b'x' * 6, 'hb')
    ahead.keep_compressed(c, b'x' * 4, 'hc')
    assert ahead.compressed_bytes == 10
    ahead.keep_compressed(a, b'x' * 6, 'ha')             # nearer: the farthest (c, then b) make room
    assert set(ahead.compressed) == {a} and ahead.compressed_bytes == 6
    ahead.keep_compressed(c, b'x' * 6, 'hc')              # farther than all held: this one is not kept
    assert set(ahead.compressed) == {a}


def test_a_page_read_ahead_is_found_only_in_its_context_and_decoded_from_its_bytes(qapp):
    ahead = pm.ReadAhead()
    ident, = idents(1)
    context = ('deck', 'instructor', 'EN')
    ahead.switch_context(context)
    ahead.keep_compressed(ident, png(), 'digest')
    assert ahead.page(ident, ('deck', 'after-course', 'EN'), 'digest') is None
    assert ahead.page(ident, context, 'other digest') is None
    pixmap, digest = ahead.page(ident, context, 'digest')
    assert (pixmap.width(), digest) == (8, 'digest') and ident in ahead.prefetched


def test_another_deck_view_or_language_drops_everything_read_ahead(qapp):
    ahead = pm.ReadAhead()
    ident, = idents(1)
    ahead.switch_context(('deck', 'instructor', 'EN'))
    future = Future()
    ahead.prefetching[ident] = future
    ahead.keep_compressed(ident, b'zip', 'h')
    ahead.hold_decoded(ident, QPixmap(4, 4), 'h')
    ahead.switch_context(('deck', 'instructor', 'EN'))
    assert ahead.compressed and ahead.prefetched           # the same context keeps them
    ahead.switch_context(('deck', 'instructor', 'DE'))
    assert not (ahead.compressed or ahead.prefetched or ahead.prefetching or ahead.rank) and ahead.compressed_bytes == 0
    assert future.cancelled()


def test_an_arrival_for_another_context_is_ignored_a_missing_page_is_remembered(qapp):
    ahead = pm.ReadAhead()
    a, b = idents(2)
    ahead.switch_context(('deck', 'instructor', 'EN'))
    ahead.rank = {a: 0, b: pm.PREFETCHED}                    # b is beyond the nearest: compressed only
    assert not ahead.arrived(('deck', 'instructor', 'DE'), a, (b'zip', 'h', QImage()))
    assert not ahead.compressed
    assert not ahead.arrived(ahead.context, a, None) and a in ahead.missing
    image = QImage.fromData(png())
    assert not ahead.arrived(ahead.context, b, (b'zip', 'h', image)) and b in ahead.compressed and b not in ahead.prefetched
    assert ahead.arrived(ahead.context, a, (b'zip', 'h', image)) and a in ahead.prefetched


# -- StepState ------------------------------------------------------------------------

def test_step_lists_are_bounded_and_forget_that_they_came_from_the_store(qapp):
    steps = pm.StepState()
    for i in range(pm.STEP_CACHE + 1):
        steps.stored.add(('saved', i))
        steps.keep(('saved', i), [b'1'])
    assert len(steps.pages) == pm.STEP_CACHE and ('saved', 0) not in steps.pages
    assert ('saved', 0) not in steps.stored and ('saved', 1) not in steps.stored   # a list rendered here is not "stored"


def test_the_step_pick_a_failure_and_the_scans_survive_an_invalidation_the_lists_do_not(qapp):
    steps = pm.StepState()
    path, key = Path('a.tex'), ('saved', 'a', 1)
    steps.choice[path] = 2
    steps.failed.add(('saved', 'bad', 1))
    steps.scan(('a', 1), lambda: 'scan')
    steps.keep(key, [b'1', b'2'])
    steps.stored.add(key)
    steps.recheck.add(key)
    steps.count_after[key] = lambda: None
    steps.pixmap = ('digest', QPixmap(4, 4))
    steps.invalidate()
    assert not (steps.pages or steps.stored or steps.recheck or steps.count_after or steps.pixmap)
    assert steps.choice == {path: 2} and steps.failed == {('saved', 'bad', 1)} and steps.scans == {('a', 1): 'scan'}


def test_the_poll_rechecks_saved_lists_and_not_drafts(qapp):
    steps = pm.StepState()
    steps.keep(('saved', 'a', 1), [b'1'])
    steps.keep(('draft', 'a', 1), [b'1'])
    steps.recheck_saved()
    assert steps.recheck == {('saved', 'a', 1)}


def test_the_store_updates_the_result_even_when_pages_are_equal(qapp):
    steps = pm.StepState()
    key = ('saved', 'a', 1)
    current = SimpleNamespace(pages=(b'1', b'2'), status='current')
    assert steps.read(key, current)[0] and key in steps.stored
    steps.recheck.add(key)
    steps.pixmap = shown = ('digest', QPixmap(4, 4))
    previous = SimpleNamespace(pages=current.pages, status='previous')
    assert steps.read(key, previous)[0]
    assert steps.pages[key] is previous and steps.pixmap is shown and not steps.recheck


def test_a_stored_list_the_store_no_longer_has_is_dropped_a_rendered_one_stays(qapp):
    steps = pm.StepState()
    stored, rendered = ('saved', 'a', 1), ('saved', 'b', 1)
    steps.read(stored, SimpleNamespace(pages=(b'1', b'2')))
    steps.rendered(rendered, [b'1', b'2'], '')
    steps.recheck_saved()
    assert steps.read(stored, None)[0] and stored not in steps.pages
    assert not steps.read(rendered, None)[0] and rendered in steps.pages     # needs its deck: never stored
    assert not steps.read(rendered, None)[0]


def test_a_lookup_that_found_nothing_hands_back_the_render_to_queue_once(qapp):
    steps = pm.StepState()
    key, asked = ('saved', 'a', 1), []
    steps.count_after[key] = lambda: asked.append(1)
    changed, render = steps.read(key, None)
    assert not changed
    render()
    assert asked == [1] and key not in steps.count_after
    steps.count_after[key] = lambda: asked.append(2)
    assert steps.read(key, SimpleNamespace(pages=(b'1',)))[1] is None and not steps.count_after   # found: no render wanted


def test_a_failed_count_is_remembered_until_the_list_arrives(qapp):
    steps = pm.StepState()
    key = ('saved', 'a', 1)
    assert not steps.rendered(key, [], 'TeX error') and key in steps.failed
    assert steps.rendered(key, [b'1'], '') and key not in steps.failed and key in steps.pages


def test_the_scan_cache_is_bounded(qapp):
    steps = pm.StepState()
    for i in range(pm.SCAN_CACHE + 1):
        steps.scan(('a', i), lambda i=i: i)
    assert len(steps.scans) == pm.SCAN_CACHE and ('a', 0) not in steps.scans
    assert steps.scan(('a', 1), lambda: pytest.fail('held')) == 1


# -- Lookups, AdhocBuffer, PreviewModel ---------------------------------------------------

def test_one_lookup_per_slot_a_newer_replaces_it_and_the_same_is_not_started_twice(qapp):
    lookups = pm.Lookups()
    first, second = Future(), Future()
    assert lookups.begin('page', (1, 'a'))
    lookups.add('page', (1, 'a'), first)
    assert not lookups.begin('page', (1, 'a'))
    assert lookups.begin('page', (1, 'b')) and first.cancelled()
    lookups.add('page', (1, 'b'), second)
    assert 'page' in lookups and not lookups.arrive('page', (1, 'a'))      # the replaced one's answer is not wanted
    assert lookups.arrive('page', (1, 'b')) and 'page' not in lookups
    assert not lookups.arrive('page', (1, 'b'))


def test_cancelling_all_lookups_drops_the_slots_but_not_the_others_answers_elsewhere(qapp):
    lookups = pm.Lookups()
    futures = [Future(), Future()]
    lookups.add('page', (1, 'a'), futures[0])
    lookups.add(('steps', 'k'), (1, 'k'), futures[1])
    lookups.cancel_all()
    assert not lookups.slots and all(f.cancelled() for f in futures)
    assert not lookups.arrive('page', (1, 'a'))


def test_the_adhoc_page_is_held_by_key_and_forgotten_with_the_slide(qapp):
    adhoc = pm.AdhocBuffer()
    key = ('slide', 'instructor', 'EN')
    result = SimpleNamespace(key=key, request='spec')
    adhoc.hold(result, 'text', 'note', full=True)
    assert adhoc.holds(key) and not adhoc.holds(('other', 'instructor', 'EN')) and adhoc.full
    adhoc.hold(result, 'saved text')
    assert adhoc.value is result and not adhoc.full and adhoc.text == 'saved text'
    adhoc.forget()
    assert adhoc.value is None and adhoc.spec is None


def test_invalidating_the_selection_keeps_what_a_return_visit_needs(qapp):
    model = pm.PreviewModel()
    key = ('slide', 'instructor', 'EN')
    model.pixmaps.put(key, QPixmap(4, 4), 1, 'h', 'd')
    model.adhoc.hold(SimpleNamespace(key=key), 'text')
    model.steps.choice[Path('a.tex')] = 3
    model.steps.keep(('saved', 'a', 1), [b'1'])
    future = Future()
    model.lookups.add('page', (1, 'a'), future)
    model.lookups.stored = ('ident',)
    model.invalidate_selection()
    assert future.cancelled() and not model.lookups.slots and model.lookups.stored is None
    assert not model.steps.pages
    assert key in model.pixmaps and model.adhoc.value is not None and model.steps.choice
    model.invalidate_slide()
    assert model.adhoc.value is None


def test_closing_lets_go_of_everything_held(qapp):
    model = pm.PreviewModel()
    key = ('slide', 'instructor', 'EN')
    model.pixmaps.put(key, QPixmap(4, 4), 1, 'h', 'd')
    model.ahead.keep_compressed(idents(1)[0], b'zip', 'h')
    model.lookups.stored = ('ident',)
    model.steps.pixmap = (key, 1, QPixmap(4, 4))
    model.close()
    assert not model.pixmaps and not model.ahead.compressed and model.lookups.stored is None and model.steps.pixmap is None
