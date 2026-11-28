# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The file hash cache, the render key and the store of background renders (no TeX)."""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from slidemage import compiler, dep_hash, preview_requests, render_evidence, render_key, render_store
from slidemage.project import ProjectContext
from slidemage.render_key import Freshness, Unit
from slidemage.render_evidence import THUMBNAIL_MAX

OLD = time.time() - 3600


def write(path: Path, text: str, mtime: float = OLD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "proj"
    for name in ("slides", "decks", "media", "snippets"):
        (root / name).mkdir(parents=True)
    return ProjectContext.at(root)


@pytest.fixture
def store(ctx, tmp_path):
    s = render_store.RenderStore(ctx, tmp_path / "local")
    yield s
    s.close()


@pytest.fixture
def resolver(ctx, store):
    hashes = dep_hash.HashCache(store.db, store.lock)
    return render_key.Resolver(ctx, hashes, store, engine_fp=lambda: "LuaHBTeX 1.22|Windows")


def unit_for(ctx, slug="aaa-EN-One", frame=3, preamble="\\documentclass{beamer}\n\\begin{document}", view="instructor"):
    return Unit("deck1", "slide", slug, None, (), view, "EN", frame, preamble, "acme",
                ctx.slides_dir / f"{slug}-current.tex")


# -- the key ----------------------------------------------------------------------------

def test_the_key_follows_slide_text_preamble_view_language_and_engine(ctx, resolver, store):
    unit = unit_for(ctx)
    slide = write(unit.source_path, "\\begin{frame}A\\end{frame}")
    key = resolver.fast_key(unit)
    assert resolver.fast_key(unit) == key
    assert resolver.fast_key(unit_for(ctx, frame=9)) == key                  # the page number is not in the key
    assert resolver.fast_key(unit_for(ctx, view="after-course")) != key
    assert resolver.fast_key(unit_for(ctx, preamble="other")) != key
    assert resolver.fast_key(replace(unit, language="DE")) != key
    other_engine = render_key.Resolver(ctx, resolver.hashes, store, engine_fp=lambda: "newer|Windows")
    assert other_engine.fast_key(unit) != key
    write(slide, "\\begin{frame}B, and longer\\end{frame}")
    assert resolver.fast_key(unit) != key


def test_the_key_ignores_the_preamble_lines_only_slidemage_reads(ctx, resolver):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "\\begin{frame}A\\end{frame}")
    plain = "\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n\\begin{document}"
    key = resolver.fast_key(unit_for(ctx, preamble=plain))
    settings = ("\\documentclass{beamer}\n%% SlideMage open PDF: instructor\n\\input{SlideMage_template_acme}\n"
                "\\deckoutputfolder{../pdf}\n  \\deckoutputfolder[after-course]{../out} \n\\decktags{course}\n"
                "\\begin{document}")
    assert resolver.fast_key(unit_for(ctx, preamble=settings)) == key
    assert resolver.fast_key(unit_for(ctx, preamble=plain.replace("acme", "other"))) != key
    shared = "\\documentclass{beamer}\n\\input{SlideMage_template_acme}\\deckoutputfolder{../pdf}\n\\begin{document}"
    assert resolver.fast_key(unit_for(ctx, preamble=shared)) != key      # a line with TeX on it is kept whole


def test_crlf_and_lf_share_a_key_and_recent_edits_bypass_the_hash_cache(ctx, resolver, store):
    unit = unit_for(ctx)
    slide = unit.source_path
    slide.write_bytes("A ä\r\nB\r\n".encode("utf-8"))
    os.utime(slide, (OLD, OLD))
    revision = preview_requests.SourceRevision.capture(slide)
    assert revision.text == "A ä\nB\n"
    key = resolver.fast_key(unit)
    assert key is not None and resolver.fast_key(unit, revision.text) == key
    assert resolver.fast_key(unit, "unsaved\n") != key
    assert resolver.fast_key(unit) == key and resolver.hashes.reads == 1
    sql = "SELECT sha256 FROM filehash WHERE path=?"
    assert store.db.execute(sql, (dep_hash.norm(slide),)).fetchone()[0] == revision.content_hash
    write(slide, "saved edit\n", mtime=time.time())
    for reads in (2, 3):
        assert resolver.fast_key(unit) not in (None, key) and resolver.hashes.reads == reads
    assert store.db.execute(sql, (dep_hash.norm(slide),)).fetchone()[0] == revision.content_hash


def make_record(resolver, unit, inputs):
    manifest = resolver.build_manifest([str(p) for p in inputs])
    key = resolver.fast_key(unit)
    meta = dict(unit=unit.label, rendered_at=time.time(), manifest=manifest.entries, frame_number=unit.frame_number,
                machine=render_key.machine_id(), tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                inventory=render_evidence.inventory_state(
                    render_evidence.search_inventory(resolver.ctx.root, compiler.build_env(resolver.ctx)),
                    [unit.source_path, *[rel for _kind, rel, _sha in manifest.entries]]))
    return key, meta


def png(size=(4, 4), color=(200, 30, 30)):
    out = BytesIO()
    Image.new("RGBA" if len(color) == 4 else "RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def store_render(store, key, meta, pages=2, decks=("deck1",)):
    pdf = write(store.root / "render.pdf", "%PDF")
    return store.put(key, pdf, [png()] * pages, meta, decks=decks)


def test_a_render_ignores_page_number_changes_but_explains_stale_inputs(ctx, resolver, store):
    unit = unit_for(ctx)
    slide = write(unit.source_path, "slide")
    image = write(ctx.media_dir / "pic.png", "img")
    key, meta = make_record(resolver, unit, [slide, image])
    assert {rel for _, rel, _ in meta["manifest"]} == {"slides/aaa-EN-One-current.tex", "media/pic.png"}
    assert resolver.lookup(unit).state is Freshness.MISSING
    store_render(store, key, meta)
    assert resolver.lookup(unit).final
    moved = resolver.lookup(replace(unit, frame_number=4))
    assert moved.state is Freshness.FRESH_NUMBERING_DIFFERS and moved.usable

    write(image, "other image")
    stale = resolver.lookup(unit)
    assert stale.state is Freshness.STALE and stale.record and stale.why == "file media/pic.png"
    write(image, "img")
    assert resolver.lookup(unit).state is Freshness.FRESH

    write(image, "other image")
    write(ctx.root / "SlideMage_project_macros.tex", "new macros")
    assert resolver.lookup(unit).why == "file media/pic.png"
    write(image, "img")
    assert resolver.lookup(unit).why == "inventory"


def test_a_changed_tex_file_stales_a_render_made_on_this_machine_only(ctx, resolver, store, tmp_path):
    unit = unit_for(ctx)
    slide = write(unit.source_path, "slide")
    tex = write(tmp_path / "texlive/beamer.cls", "cls")
    key, meta = make_record(resolver, unit, [slide, tex])
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    write(tex, "a package update")
    assert resolver.lookup(unit).state is Freshness.STALE
    store_render(store, key, dict(meta, machine="elsewhere"))
    assert resolver.lookup(unit).state is Freshness.FRESH


def test_put_replaces_the_previous_object_for_the_same_unit(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    layer = write(ctx.root / "SlideMage_template_acme.tex", "v1")
    def put(pages):
        key, meta = make_record(resolver, unit, [unit.source_path, layer])
        assert store_render(store, key, meta, pages=pages) == key
        found = resolver.lookup(unit)
        assert found.final and found.record["pages"] == pages
        assert [p.name for p in (store.root / "objects").glob("*/*")] == [key]
        assert store.count() == 1 and not store.page(found.record, pages + 1)
        return key

    original = put(2)
    assert put(3) == original
    write(layer, "v2 longer")
    assert resolver.lookup(unit).state is Freshness.STALE and put(1) == original
    write(unit.source_path, "edited slide")
    assert put(4) != original


def test_rescan_repairs_the_index_and_removes_orphaned_objects_and_trash(store):
    missing = _put(store, "ab" + "0" * 62)
    orphan = _put(store, "cd" + "1" * 62)
    shutil.rmtree(render_store.object_dir(store.root, missing))
    orphan_dir = render_store.object_dir(store.root, orphan)
    store.db.execute("DELETE FROM renders WHERE key=?", (orphan,))
    store.db.commit()
    leftover = store.root / "trash-deadbeef" / "objects"
    leftover.mkdir(parents=True)

    store.rescan(lambda: True)
    assert store.count() == 1
    store.rescan()
    assert store.count() == 0 and not orphan_dir.exists() and not leftover.parent.exists()


def test_the_store_creates_nothing_in_the_project_and_removes_old_caches(ctx, tmp_path):
    old = ctx.root / ".previews/render-store"
    (old / "objects").mkdir(parents=True)
    write(old / "objects/slide.pdf", "%PDF")

    def project_files():
        return {p for p in ctx.root.rglob("*") if ".previews" not in p.parts}

    before = project_files()
    local = tmp_path / "cache/store"
    store = render_store.RenderStore(ctx, local)
    try:
        _put(store, "ab" + "0" * 62)
        store.touch_deck("d", opened=True)
        store.rescan()
        assert store.root == local and store.work_dir == local / "work"
        assert (local / "objects").is_dir()
    finally:
        store.close()
    assert project_files() == before and not list(ctx.root.rglob("render-store*"))


def test_eviction_order_and_protection(ctx, resolver, store):
    clock = [1000.0]
    store._clock = lambda: clock[0]
    keys = {}
    for name, deck in (("a", "old"), ("b", "recent"), ("c", "old")):
        unit = unit_for(ctx, f"{name * 3}-EN-{name}")
        write(unit.source_path, name)
        key, meta = make_record(resolver, unit, [unit.source_path])
        clock[0] += 10
        store_render(store, key, meta, decks=(deck,))
        keys[name] = key
    store.db.execute("UPDATE renders SET bytes=1000")
    assert store.total_bytes() == 3000
    clock[0] += 31 * 86400
    assert store.enforce_limit(10 * 1024 ** 3, protected_decks={"recent"}) == 0
    assert store.count() == 3                             # age alone never evicts an unprotected render
    store.enforce_limit(2000, protected_decks={"recent"})
    assert store.count() == 2 and not store.find(keys["a"]) and store.find(keys["b"])
    store.enforce_limit(1000, protected_decks={"recent"})
    assert store.count() == 1 and store.find(keys["b"])
    store.db.execute("UPDATE renders SET bytes=1000")
    store.enforce_limit(900, protected_decks={"recent"})
    assert store.count() == 1                                              # protected stays unless more than twice over
    store.enforce_limit(400, protected_decks={"recent"})
    assert store.count() == 0


def _put(store, key):
    return store_render(store, key, dict(unit=f"unit-{key}", rendered_at=time.time()))


def test_clear_moves_old_objects_to_trash_and_purge_keeps_new_objects(store):
    old = _put(store, "ab" + "0" * 62)
    store.clear()
    assert store.count() == 0 and not store.find(old)
    [trash] = store.root.glob("trash-*")
    assert (trash / "objects").is_dir()
    new = _put(store, "cd" + "1" * 62)
    store.purge_trash()
    assert not trash.exists() and store.find(new) and store.count() == 1


def test_archiving_a_deck_trashes_the_renders_only_it_used(store):
    solo = store_render(store, "ab" + "0" * 62, dict(unit="solo", rendered_at=time.time()), decks=("old",))
    shared = store_render(store, "cd" + "1" * 62, dict(unit="shared", rendered_at=time.time()), decks=("old", "live"))
    assert store.drop_deck("old") == 1 and store.find(shared) and not store.find(solo)
    assert len(list(store.root.glob("trash-*"))) == 1


def test_failures_are_remembered_for_the_input_state_and_backed_off(ctx, resolver, store):
    clock = [5000.0]
    store._clock = lambda: clock[0]
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "broken")
    unit = unit_for(ctx)
    key = resolver.fast_key(unit)
    manifest = resolver.build_manifest([str(unit.source_path)]).entries
    store.record_failure(key, render_store.DETERMINISTIC, "! Undefined control sequence", manifest)
    found = resolver.lookup(unit)
    assert found.state is Freshness.FAILED and found.final and not store.may_retry(found.failure)
    write(unit.source_path, "fixed")                                          # the user fixed the slide: new key, no failure
    assert resolver.lookup(unit).state is Freshness.MISSING
    # a transient failure is retried after the backoff, three times at most
    other = unit_for(ctx, "bbb-EN-Two")
    write(other.source_path, "x")
    k2 = resolver.fast_key(other)
    m2 = resolver.build_manifest([str(other.source_path)]).entries
    store.record_failure(k2, render_store.TRANSIENT, "timeout", m2)
    assert not store.may_retry(store.failure(k2))
    clock[0] += 301
    assert store.may_retry(store.failure(k2))
    store.record_failure(k2, render_store.TRANSIENT, "timeout", m2)
    store.record_failure(k2, render_store.TRANSIENT, "timeout", m2)
    clock[0] += 10 * 3600
    assert not store.may_retry(store.failure(k2))


def test_a_render_depends_only_on_the_alt_texts_of_the_pictures_it_read(ctx, resolver):
    # A new alt text for one picture made every preview out of date: the alt-text files are read by every render
    # (v8.69.0).
    header = "image,role,status_en,short_alt_en,source_en,status_de,short_alt_de,source_de\n"
    csv_path = write(ctx.root / "media" / "alt-text.csv", header + "media/a.png,informative,auto,A,,auto,,\n"
                     "media/b.png,informative,auto,B,,auto,,\n")
    json_path = write(ctx.root / "media" / "alt-text.json", json.dumps(
        {"version": 2, "images": {"media/a.png": {"short": "A"}, "media/b.png": {"short": "B"}}}))
    slide = write(ctx.slides_dir / "aaa-EN-One-current.tex", "\\includegraphics{media/a}\n")
    picture = write(ctx.root / "media" / "a.png", "png")
    entries = resolver.build_manifest([str(p) for p in (slide, picture, csv_path, json_path)]).entries
    assert {kind for kind, rel, _sha in entries if "alt-text" in rel} == {render_key.KIND_ALT_TEXT}
    assert resolver.manifest_current(entries) is None
    write(csv_path, header + "media/a.png,informative,auto,A,,auto,,\nmedia/b.png,informative,auto,B changed,,auto,,\n"
          "media/c.png,informative,auto,C new,,auto,,\n", OLD + 10)
    write(json_path, json.dumps({"version": 2, "images": {"media/a.png": {"short": "A"},
                                                         "media/c.png": {"short": "C"}}}), OLD + 10)
    assert resolver.manifest_current(entries) is None         # another picture's alt text: still current
    write(csv_path, header + "media/a.png,informative,auto,A changed,,auto,,\n", OLD + 20)
    assert resolver.manifest_current(entries) is not None     # its own picture's alt text: out of date
    write(csv_path, header + "media/a.png,informative,auto,A,,auto,,\n", OLD + 30)
    write(json_path, json.dumps({"version": 2, "images": {"MEDIA/A.PNG": {"short": "A, longer"}}}), OLD + 30)
    assert resolver.manifest_current(entries) is not None     # matched by file name, whatever the case and folder


def test_put_writes_a_thumbnail_of_the_last_page_within_the_preview_cache_size_and_lists_it(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, meta = make_record(resolver, unit, [unit.source_path])
    originals = [png((2, 1), (21, 54, 89, 0)), png((1920, 1080))]
    store.put(key, write(store.root / "render.pdf", "%PDF"), originals, meta)
    record = store.find(key)
    folder = Path(record["dir"])
    assert set(record["files"]) == {"slide.pdf", "p001.webp", "p002.webp", "thumb.webp"}
    pages = store.pages(record)
    for number, (original_png, webp) in enumerate(zip(originals, pages, strict=True), start=1):
        assert webp[8:12] == b"WEBP" and store.page(record, number) == webp
        with Image.open(BytesIO(original_png)) as original, Image.open(BytesIO(webp)) as stored:
            assert stored.size == original.size
            assert stored.convert(original.mode).tobytes() == original.tobytes()
    assert store.thumbnail_path(record) == folder / "thumb.webp"
    with Image.open(folder / "thumb.webp") as thumbnail, Image.open(BytesIO(originals[-1])) as original:
        original.thumbnail(THUMBNAIL_MAX, Image.Resampling.LANCZOS)
        assert thumbnail.format == "WEBP" and thumbnail.size == original.size
        assert thumbnail.tobytes() == original.tobytes()
    assert record["files"]["thumb.webp"] == (folder / "thumb.webp").stat().st_size
    assert record["pages"] == 2 and store.total_bytes() == record["bytes"] == sum(record["files"].values())
