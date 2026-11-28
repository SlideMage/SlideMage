# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide list thumbnails use verified renders and select the right reveal step."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

from slidemage import dep_hash, preview_target, render_evidence, render_key, render_store
from test_slide_list_gui import item_of, make_list  # noqa: F401 -- fixture


@pytest.fixture
def thumbnails(make_list, tmp_path):  # noqa: F811 -- fixture
    (tmp_path / 'slides').mkdir()
    store = None

    def open_list(name, text, deck):
        nonlocal store
        (tmp_path / 'slides' / f'abc-EN-{name}-current.tex').write_text(text, encoding='utf-8')
        listing, window, _ = make_list(deck)
        ctx = window.project
        store = render_store.RenderStore(ctx, tmp_path / '.build/store')
        resolver = render_key.Resolver(ctx, dep_hash.HashCache(store.db, store.lock), store, engine_fp=lambda: 'engine')
        window.background = SimpleNamespace(renderer=SimpleNamespace(resolver=resolver))
        return listing, resolver

    yield open_list
    if store is not None:
        store.close()


def publish(listing, resolver, row, colours):
    ctx, store = resolver.ctx, resolver.store
    target = preview_target.for_call(ctx, listing.deck, row.call, row.position, frame_number=row.frame_number)
    unit = render_key.unit_for(target, listing.state.view, listing.state.language)
    source = unit.source_path
    manifest = resolver.build_manifest([str(source)])
    inventory = render_evidence.search_inventory(ctx.root, {})
    meta = dict(unit=unit.label, template=unit.template, manifest=manifest.entries, frame_number=unit.frame_number,
                inventory=render_evidence.inventory_state(inventory, [source]))
    pdf = store.root / 'input.pdf'
    pdf.write_bytes(b'%PDF test')
    pages = []
    for colour in colours:
        png = BytesIO()
        Image.new('RGB', (1920, 1080), colour).save(png, format='PNG')
        pages.append(png.getvalue())
    key = resolver.fast_key(unit)
    store.put(key, pdf, pages, meta)
    return key


def test_slide_list_shows_a_just_saved_slides_verified_thumbnail(thumbnails):
    listing, resolver = thumbnails('One', 'Before save', '\\slide{abc-EN-One}\n')
    source = resolver.ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('Just saved', encoding='utf-8')
    key = publish(listing, resolver, listing._outline[0].rows[0], ['blue'])
    listing.preview_source_changed(source)
    listing._refresh_preview_rows()
    shown = listing.tree.data_of(item_of(listing, 'abc'))
    assert shown.thumbnail_verified and not shown.stale_preview
    assert shown.thumbnail == resolver.store.thumbnail_path(resolver.store.find(key))


def test_a_slide_that_needs_its_deck_says_why_it_has_no_thumbnail(thumbnails):
    listing, _ = thumbnails('Agenda', r'\begin{standardframe}{Agenda}\tableofcontents\end{standardframe}',
                            '\\slide{abc-EN-Agenda}\n')
    listing._refresh_preview_rows()
    shown = listing.tree.data_of(item_of(listing, 'abc'))
    assert shown.thumbnail is None and 'table of contents or agenda' in shown.thumbnail_note


def test_a_slidestep_row_shows_the_page_of_its_last_step_from_the_whole_slides_render(thumbnails):
    calls = '\\slidestep{abc-EN-One}[instructor]{2}\n\\slidestep{abc-EN-One}[instructor]{3}\n'
    listing, resolver = thumbnails('One', 'Steps', calls)
    for row in (listing.tree.data_of(item_of(listing, 'abc', nth)) for nth in (0, 1)):
        publish(listing, resolver, row, ['red', 'green', 'blue'])
    listing._refresh_preview_rows()
    step2, step3 = (listing.tree.data_of(item_of(listing, 'abc', nth)) for nth in (0, 1))
    assert step2.thumbnail is not None and step2.thumbnail.name.endswith('-002.webp')
    assert step3.thumbnail is not None and step3.thumbnail.name == 'thumb.webp'
    assert 'step 2 of 3' in step2.thumbnail_note and 'step 3 of 3' in step3.thumbnail_note
    with Image.open(step2.thumbnail) as shown:
        red, green, _ = shown.convert('RGB').getpixel((shown.width // 2, shown.height // 2))
        assert green > 100 > red
