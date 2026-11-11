# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The file hash cache, the render key and the store of background renders (no TeX)."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from slidemage import compiler, dep_hash, preview_requests, render_evidence, render_key, render_store
from slidemage.project import ProjectContext
from slidemage.render_key import Freshness, Unit

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
def hashes(store):
    return dep_hash.HashCache(store.db, store.lock)


@pytest.fixture
def resolver(ctx, store, hashes):
    return render_key.Resolver(ctx, hashes, store, engine_fp=lambda: "LuaHBTeX 1.22|Windows")


def unit_for(ctx, slug="aaa-EN-One", frame=3, preamble="\\documentclass{beamer}\n\\begin{document}", view="instructor"):
    return Unit("deck1", "slide", slug, None, (), view, "EN", frame, preamble, "acme",
                ctx.slides_dir / f"{slug}-current.tex")


# -- dep_hash ---------------------------------------------------------------------------

def test_hash_is_kept_by_size_and_mtime_and_read_again_when_they_change(tmp_path, store):
    cache = dep_hash.HashCache(store.db, store.lock)
    path = write(tmp_path / "a.txt", "one")
    first = cache.hash(path)
    assert cache.hash(path) == first and cache.reads == 1
    write(tmp_path / "a.txt", "two!")
    assert cache.hash(path) != first and cache.reads == 2


# -- the key ----------------------------------------------------------------------------

def test_the_key_follows_slide_text_preamble_view_language_and_engine(ctx, resolver, store, hashes):
    slide = write(ctx.slides_dir / "aaa-EN-One-current.tex", "\\begin{frame}A\\end{frame}")
    unit = unit_for(ctx)
    key = resolver.fast_key(unit)
    assert resolver.fast_key(unit) == key
    assert resolver.fast_key(unit_for(ctx, frame=9)) == key                  # the page number is not in the key
    assert resolver.fast_key(unit_for(ctx, view="after-course")) != key
    assert resolver.fast_key(unit_for(ctx, preamble="other")) != key
    assert resolver.fast_key(Unit(**{**unit.__dict__, "language": "DE"})) != key
    other_engine = render_key.Resolver(ctx, hashes, store, engine_fp=lambda: "newer|Windows")
    assert other_engine.fast_key(unit) != key
    write(slide, "\\begin{frame}B, and longer\\end{frame}")
    assert resolver.fast_key(unit) != key



def test_the_key_ignores_the_preamble_lines_only_slidemage_reads(ctx, resolver):
    """A deck's PDF output folders, tags and open-PDF choice do not change what TeX typesets: renders stay current."""
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

def test_a_just_saved_slide_has_a_key_without_a_hash_shortcut(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide\n", mtime=time.time())
    key = resolver.fast_key(unit)
    assert key is not None and resolver.fast_key(unit) == key
    assert resolver.hashes.reads == 2
    assert store.db.execute("SELECT COUNT(*) FROM filehash").fetchone()[0] == 0


def test_a_crlf_slide_and_its_captured_lf_text_have_the_same_key(ctx, resolver, store):
    unit = unit_for(ctx)
    unit.source_path.write_bytes("A ä\r\nB\r\n".encode("utf-8"))
    os.utime(unit.source_path, (OLD, OLD))
    revision = preview_requests.SourceRevision.capture(unit.source_path)
    assert revision.text == "A ä\nB\n"
    key = resolver.fast_key(unit)
    assert key is not None and resolver.fast_key(unit, revision.text) == key
    assert resolver.fast_key(unit, "unsaved\n") != key
    assert store.db.execute("SELECT sha256 FROM filehash WHERE path=?", (dep_hash.norm(unit.source_path),)).fetchone()[0] == revision.content_hash


# -- manifests and freshness -------------------------------------------------------------

def make_record(resolver, unit, inputs):
    manifest = resolver.build_manifest([str(p) for p in inputs])
    key = resolver.fast_key(unit)
    meta = dict(unit=unit.label, rendered_at=time.time(), manifest=manifest.entries, frame_number=unit.frame_number,
                machine=render_key.machine_id(), tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                inventory=render_evidence.inventory_state(
                    render_evidence.search_inventory(resolver.ctx.root, compiler.build_env(resolver.ctx)),
                    [unit.source_path, *[rel for _kind, rel, _sha in manifest.entries]]))
    return key, meta


def store_render(store, key, meta, pages=2, decks=("deck1",)):
    pdf = write(store.root / "render.pdf", "%PDF")
    return store.put(key, pdf, [real_png()] * pages, meta, decks=decks)


def test_a_render_is_fresh_until_a_file_it_read_changes(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    image = write(ctx.media_dir / "pic.png", "img")
    preamble = write(ctx.root / "SlideMage_template_acme.tex", "pre")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, unit, [ctx.slides_dir / "aaa-EN-One-current.tex", image, preamble])
    assert {rel for _, rel, _ in meta["manifest"]} == {"slides/aaa-EN-One-current.tex", "media/pic.png", "SlideMage_template_acme.tex"}
    assert resolver.lookup(unit).state is Freshness.MISSING
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    write(image, "other image")
    result = resolver.lookup(unit)
    assert result.state is Freshness.STALE and result.record is not None       # shown as outdated, never as fresh
    assert result.why == "file media/pic.png"
    write(image, "img")
    assert resolver.lookup(unit).state is Freshness.FRESH


def test_a_different_page_number_is_fresh_with_a_note(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx, frame=3)
    key, meta = make_record(resolver, unit, [unit.source_path])
    store_render(store, key, meta)
    moved = unit_for(ctx, frame=4)
    assert resolver.lookup(moved).state is Freshness.FRESH_NUMBERING_DIFFERS
    assert resolver.lookup(moved).usable and resolver.lookup(unit).final


def test_a_changed_tex_file_stales_a_render_made_on_this_machine_only(ctx, resolver, store, tmp_path):
    tex = write(tmp_path / "texlive" / "beamer.cls", "cls")
    unit = unit_for(ctx)
    write(unit.source_path, "s")
    key, meta = make_record(resolver, unit, [unit.source_path, tex])
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    write(tex, "a package update")
    assert resolver.lookup(unit).state is Freshness.STALE
    # the same render made on another machine is trusted on the engine and the project files
    other = unit_for(ctx, "bbb-EN-Two")
    write(other.source_path, "s2")
    key2, meta2 = make_record(resolver, other, [other.source_path, tex])
    meta2["machine"] = "elsewhere"
    store_render(store, key2, meta2)
    assert resolver.lookup(other).state is Freshness.FRESH


# -- the store --------------------------------------------------------------------------

def test_two_producers_replace_one_object_of_a_key(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    layer = write(ctx.root / "SlideMage_template_acme.tex", "v1")
    for pages in (2, 3, 1):
        if pages == 1:
            write(layer, "v2 longer")
            assert resolver.lookup(unit).state is Freshness.STALE
        key, meta = make_record(resolver, unit, [unit.source_path, layer])
        assert store_render(store, key, meta, pages=pages) == key
        found = resolver.lookup(unit)
        assert found.final and found.record["pages"] == pages
        assert store.count() == 1 and store.find(key) is not None
        assert [p.name for p in (store.root / "objects" / key[:2]).iterdir()] == [key]
        assert not store.page(found.record, pages + 1)


def test_repeated_puts_of_an_unswept_label_leave_one_object(ctx, resolver, store):
    unit = unit_for(ctx)
    for text in ("first", "edited", "edited again"):
        write(unit.source_path, text)
        key, meta = make_record(resolver, unit, [unit.source_path])
        store_render(store, key, meta)
        assert store.count() == 1 and resolver.lookup(unit).final
        assert [p.name for p in (store.root / "objects").glob("*/*")] == [key]


def test_an_old_format_object_is_never_found_or_kept(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, meta = make_record(resolver, unit, [unit.source_path])
    store_render(store, key, meta)
    folder = render_store.object_dir(store.root, key)
    old = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    old["format"] = render_store.STORE_FORMAT - 1
    (folder / "meta.json").write_text(json.dumps(old), encoding="utf-8")
    store.db.execute("UPDATE renders SET meta=?", (json.dumps(old),))
    assert not store.find(key) and store.latest_for_unit(unit.label) is None
    store.record_failure(key, render_store.DETERMINISTIC, "old failure", [])
    store.note_last_try(key)
    store.db.execute("UPDATE filehash SET sha256='old raw-byte hash'")
    store.db.execute("PRAGMA user_version=0")
    store.db.commit()
    again = render_store.RenderStore(ctx, store.root)
    try:
        hashes = dep_hash.HashCache(again.db, again.lock)
        current = render_key.Resolver(ctx, hashes, again, engine_fp=lambda: "LuaHBTeX 1.22|Windows")
        assert current.lookup(unit).state is Freshness.MISSING
        assert not again.find(key) and again.latest_for_unit(unit.label) is None
        assert not again.failures() and not again.tried_last(key)
        assert hashes.hash(unit.source_path) == preview_requests.SourceRevision.capture(unit.source_path).content_hash
        again.rescan()
        assert not folder.exists()
    finally:
        again.close()


def test_an_old_index_opens_without_losing_its_render(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, meta = make_record(resolver, unit, [unit.source_path])
    store_render(store, key, meta)
    before = store.find(key)
    store.db.executescript("""
        ALTER TABLE renders RENAME TO new_renders;
        CREATE TABLE renders (
            name TEXT PRIMARY KEY, fast_key TEXT NOT NULL, origin TEXT NOT NULL, unit TEXT NOT NULL,
            bytes INTEGER NOT NULL, rendered_at REAL NOT NULL, last_used REAL NOT NULL,
            decks TEXT NOT NULL, meta TEXT NOT NULL);
        INSERT INTO renders SELECT key, key, 'background', unit, bytes, rendered_at, last_used, decks, meta FROM new_renders;
        DROP TABLE new_renders;
        CREATE INDEX renders_key ON renders(fast_key);
        ALTER TABLE failures DROP COLUMN last_try;
        CREATE TABLE last_tries (fast_key TEXT PRIMARY KEY, tried_at REAL NOT NULL);
    """)
    folder = store.root
    upgraded = render_store.RenderStore(ctx, folder)
    try:
        assert upgraded.count() == 1 and upgraded.find(key) == before
        assert upgraded.pages(upgraded.find(key)) == [real_png()] * 2
        store_render(upgraded, key, meta, pages=1)
        assert upgraded.find(key)["pages"] == 1
    finally:
        upgraded.close()


def test_rescan_deletes_objects_the_index_does_not_know(ctx, resolver, store):
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, meta = make_record(resolver, unit, [unit.source_path])
    store_render(store, key, meta)
    folder = render_store.object_dir(store.root, key)
    store.db.execute("DELETE FROM renders")
    store.db.commit()
    store.rescan()
    assert not folder.exists() and store.count() == 0


def test_the_store_creates_nothing_in_the_project_and_removes_old_caches(ctx, tmp_path, monkeypatch):
    cache = tmp_path / "preview-cache"
    monkeypatch.setattr(render_store.project, "preview_cache_dir", lambda root: cache)
    write(cache / "render-results" / "old.pdf", "%PDF")
    page = write(cache / "page-images" / "keep.json", "pages")
    old = ctx.root / ".previews" / "render-store" / "objects" / "ab" / "cd"
    old.mkdir(parents=True)
    (old / "slide.pdf").write_bytes(b"%PDF")
    before = {p.relative_to(ctx.root).as_posix() for p in ctx.root.rglob("*") if ".previews" not in p.parts}
    local = tmp_path / "cache" / "store"
    store = render_store.RenderStore(ctx, local)
    try:
        pdf = write(tmp_path / "x.pdf", "%PDF")
        store.put("k" * 64, pdf, [real_png()], dict(unit="u", manifest=[], rendered_at=1.0), decks=["d"])
        store.touch_deck("d", opened=True)
        store.rescan()
        assert store.root == local and (local / "objects").is_dir() and store.work_dir == local / "work"
    finally:
        store.close()
    assert not (ctx.root / ".previews" / "render-store").exists()                 # the old copy is gone
    after = {p.relative_to(ctx.root).as_posix() for p in ctx.root.rglob("*") if ".previews" not in p.parts}
    assert after == before
    assert not list(ctx.root.rglob("render-store*"))
    again = render_store.RenderStore(ctx, local)
    again.close()
    assert not (cache / "render-results").exists() and page.read_text() == "pages"


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
    assert store.count() == 2 and store.find(keys["b"])                    # the least recently used unprotected went
    store.enforce_limit(1000, protected_decks={"recent"})
    assert store.count() == 1 and store.find(keys["b"])                    # one unprotected is left? no: only the protected one
    store.db.execute("UPDATE renders SET bytes=1000")
    store.enforce_limit(900, protected_decks={"recent"})
    assert store.count() == 1                                              # protected stays unless more than twice over
    store.enforce_limit(400, protected_decks={"recent"})
    assert store.count() == 0


def test_archiving_a_deck_deletes_only_what_no_other_deck_uses(ctx, resolver, store):
    solo, shared = unit_for(ctx, "aaa-EN-A"), unit_for(ctx, "bbb-EN-B")
    for u, decks in ((solo, ("old",)), (shared, ("old", "live"))):
        write(u.source_path, u.id_slug)
        key, meta = make_record(resolver, u, [u.source_path])
        store_render(store, key, meta, decks=decks)
    assert store.drop_deck("old") == 1
    assert resolver.lookup(solo).state is not Freshness.FRESH and resolver.lookup(shared).state is Freshness.FRESH


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


def test_legacy_failures_are_retried_once_without_discarding_renders(ctx, tmp_path):
    folder = tmp_path / "legacy-store"
    with_store = render_store.RenderStore(ctx, folder)
    try:
        store_render(with_store, "good", {"unit": "deck:slide:instructor:EN"})
        with_store.record_failure("bad", render_store.DETERMINISTIC, "missing setup", [])
        with_store.note_last_try("bad")
        with_store.db.execute("DELETE FROM store_flags WHERE name=?", (render_store.FAILURE_INPUTS_TRACKED,))
        with_store.db.commit()
    finally:
        with_store.close()
    upgraded = render_store.RenderStore(ctx, folder)
    try:
        assert upgraded.failures() == [] and not upgraded.tried_last("bad")
        assert upgraded.find("good")
        upgraded.record_failure("new", render_store.DETERMINISTIC, "still broken", [])
    finally:
        upgraded.close()
    reopened = render_store.RenderStore(ctx, folder)
    try:
        assert [f["key"] for f in reopened.failures()] == ["new"]
        assert reopened.find("good")
    finally:
        reopened.close()


def test_deck_usage_orders_decks_by_recency(store):
    clock = [100.0]
    store._clock = lambda: clock[0]
    for deck in ("a", "b", "c"):
        clock[0] += 1
        store.touch_deck(deck, opened=True)
    clock[0] += 1
    store.touch_deck("a", slide="xyz", view="after-course", language="DE", opened=True)
    clock[0] += 1
    store.touch_deck("b", slide="q")                       # a visit within the deck does not count as opening it
    usage = store.deck_usage()
    assert [u["deck"] for u in usage] == ["a", "c", "b"]
    assert usage[0]["open_count"] == 2 and usage[0]["last_slide"] == "xyz" and usage[2]["last_slide"] == "q"


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


# -- the small copy of the last page (2026-10-30, direct request) -------------------------

def real_png() -> bytes:
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (1920, 1080), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


def test_put_writes_a_thumbnail_of_the_last_page_within_the_preview_cache_size_and_lists_it(ctx, resolver, store):
    from PIL import Image
    from slidemage.render_evidence import THUMBNAIL_MAX
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, meta = make_record(resolver, unit, [unit.source_path])
    name = store_render(store, key, meta)
    folder = render_store.object_dir(store.root, name)
    assert store.thumbnail_path(store.find(key)) == folder / "thumb.png"
    with Image.open(folder / "thumb.png") as im:
        assert im.width == THUMBNAIL_MAX[0] and im.height <= THUMBNAIL_MAX[1]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["files"]["thumb.png"] == (folder / "thumb.png").stat().st_size
    assert meta["pages"] == 2 and store.total_bytes() == meta["bytes"] == sum(meta["files"].values())


def test_a_rescan_that_is_stopped_forgets_no_object(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, unit, [unit.source_path])
    store_render(store, key, meta)
    [folder] = [path for path in (store.root / "objects").glob("*/*") if path.is_dir()]
    shutil.rmtree(folder)                                           # gone on disk, still in the index
    store.rescan(lambda: True)
    assert store.count() == 1
    store.rescan()
    assert store.count() == 0
