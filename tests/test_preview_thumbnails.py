# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A just-saved slide immediately uses the store's list thumbnail."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from slidemage import dep_hash, preview_target, render_evidence, render_key, render_store
from test_slide_list_gui import item_of, make_list  # noqa: F401 -- fixture


def test_slide_list_shows_a_just_saved_slides_thumbnail_from_the_store(make_list, tmp_path):  # noqa: F811 -- fixture
    (tmp_path / 'slides').mkdir()
    (tmp_path / 'slides/abc-EN-One-current.tex').write_text('Before save', encoding='utf-8')
    listing, window, _ = make_list('\\slide{abc-EN-One}\n')
    ctx = window.project
    source = ctx.slides_dir / 'abc-EN-One-current.tex'
    source.write_text('Just saved', encoding='utf-8')
    store = render_store.RenderStore(ctx, tmp_path / '.build/store')
    try:
        resolver = render_key.Resolver(ctx, dep_hash.HashCache(store.db, store.lock), store, engine_fp=lambda: 'engine')
        window.background = SimpleNamespace(renderer=SimpleNamespace(resolver=resolver))
        row = listing._outline[0].rows[0]
        target = preview_target.for_call(ctx, listing.deck, row.call, row.position, frame_number=row.frame_number)
        unit = render_key.unit_for(target, listing.state.view, listing.state.language)
        manifest = resolver.build_manifest([str(source)])
        inventory = render_evidence.search_inventory(ctx.root, {})
        meta = dict(unit=unit.label, template=unit.template, manifest=manifest.entries, frame_number=unit.frame_number,
                    inventory=render_evidence.inventory_state(inventory, [source]))
        pdf = store.root / 'input.pdf'
        pdf.write_bytes(b'%PDF test')
        png = BytesIO()
        Image.new('RGB', (1920, 1080), 'blue').save(png, format='PNG')
        key = resolver.fast_key(unit)
        store.put(key, 'foreground', pdf, [png.getvalue()], meta)
        listing.preview_source_changed(source)
        listing._refresh_preview_rows()
        shown = listing.tree.data_of(item_of(listing, 'abc'))
        assert shown.thumbnail_verified and not shown.stale_preview
        assert shown.thumbnail == store.thumbnail_path(store.find(key))
        assert shown.thumbnail.name == 'thumb.png'
    finally:
        store.close()
