# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The store chooser's display precedence and shared Instructor reference filter."""
from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest

from slidemage import dep_hash, preview_requests, preview_target, render_evidence, render_key, render_lookup, render_store
from slidemage.project import ProjectContext


@pytest.fixture
def lookup_request(tmp_path):
    root = tmp_path / "project"
    for name in ("slides", "decks", "media", "snippets"):
        (root / name).mkdir(parents=True)
    ctx = ProjectContext.at(root)
    target = preview_target.PreviewTarget(ctx, "slide", "aaa-EN-One", None, None, None, 3, "preamble")
    target.source_path.write_text("slide", encoding="utf-8")
    spec = preview_requests.PreviewRequest(target, preview_requests.SourceRevision.capture(target.source_path), "instructor", "EN")
    store = render_store.RenderStore(ctx, tmp_path / "store")
    resolver = render_key.Resolver(ctx, dep_hash.HashCache(store.db, store.lock), store, engine_fp=lambda: "engine")
    yield dict(resolver=resolver, unit=render_key.unit_for(target, "instructor", "EN", "deck"), spec=spec)
    store.close()


def publish(request, rendered_at=1):
    resolver, unit = request["resolver"], request["unit"]
    manifest = resolver.build_manifest([str(unit.source_path)])
    inventory = render_evidence.search_inventory(resolver.ctx.root, {})
    meta = dict(unit=unit.label, template=unit.template, rendered_at=rendered_at, manifest=manifest.entries,
                inventory=render_evidence.inventory_state(inventory, [unit.source_path]), frame_number=unit.frame_number)
    pdf = resolver.store.root / "input.pdf"
    pdf.write_bytes(b"%PDF test")
    png = BytesIO()
    Image.new("RGB", (1920, 1080), "red").save(png, format="PNG")
    key = resolver.fast_key(unit)
    resolver.store.put(key, "background", pdf, [png.getvalue()] * 2, meta)
    return key


def test_a_slide_moves_through_current_previous_reference_and_missing(lookup_request):
    request = lookup_request
    resolver, unit = request["resolver"], request["unit"]
    store = resolver.store
    key = publish(request)
    request["unit"] = replace(unit, frame_number=9)
    state, record = render_lookup.select(request, strict=True)
    assert state == "current" and record["key"] == key
    assert render_lookup.select(dict(resolver=resolver, unit=request["unit"])) == ("current", record)
    pages = store.pages(record)
    assert len(pages) == 2 and pages[-1] == store.page(record, record["pages"])
    assert store.thumbnail_path(record).name == "thumb.png"

    unit.source_path.write_text("edited slide", encoding="utf-8")
    request["spec"] = replace(request["spec"], revision=preview_requests.SourceRevision.capture(unit.source_path))
    state, previous = render_lookup.select(request, strict=True)
    assert state == "previous" and previous == record

    unit.source_path.write_text("slide", encoding="utf-8")
    request["spec"] = replace(request["spec"], revision=preview_requests.SourceRevision.capture(unit.source_path))
    request["unit"] = replace(unit, deck="another", preamble_text="another preamble")
    state, reference = render_lookup.select(request, strict=True)
    assert state == "reference" and reference == record
    with store.pdf_copy(reference) as pdf:
        store.clear()
        assert pdf.read_bytes() == b"%PDF test" and not pdf.is_relative_to(store.root)
    assert not pdf.exists()
    assert render_lookup.select(request, strict=True) == ("missing", None)


def test_the_newest_eligible_instructor_reference_is_chosen(lookup_request):
    request = lookup_request
    unit = request["unit"]
    publish(request, rendered_at=1)
    request["unit"] = replace(unit, deck="newer", preamble_text="newer")
    newest = publish(request, rendered_at=2)
    request["unit"] = replace(unit, deck="wrong-template", preamble_text="wrong", template="other")
    publish(request, rendered_at=3)
    unit.source_path.write_text("old source", encoding="utf-8")
    request["unit"] = replace(unit, deck="wrong-source", preamble_text="old source")
    publish(request, rendered_at=4)
    unit.source_path.write_text("slide", encoding="utf-8")
    request["unit"] = replace(unit, deck="requested", view="after-course", preamble_text="requested")
    state, reference = render_lookup.select(request)
    assert state == "reference" and reference["key"] == newest
