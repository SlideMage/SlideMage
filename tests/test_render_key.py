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

from slidemage import dep_hash, render_key, render_store
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
    return Unit("deck1", "slide", slug, None, (), view, "EN", frame, preamble, "uni-graz",
                ctx.slides_dir / f"{slug}-current.tex")


# -- dep_hash ---------------------------------------------------------------------------

def test_hash_is_kept_by_size_and_mtime_and_read_again_when_they_change(tmp_path, store):
    cache = dep_hash.HashCache(store.db, store.lock)
    path = write(tmp_path / "a.txt", "one")
    first = cache.hash(path)
    assert cache.hash(path) == first and cache.reads == 1
    write(tmp_path / "a.txt", "two!")
    assert cache.hash(path) != first and cache.reads == 2


def test_touching_a_file_without_changing_it_gives_the_same_hash(tmp_path, store):
    cache = dep_hash.HashCache(store.db, store.lock)
    path = write(tmp_path / "a.txt", "same")
    first = cache.hash(path)
    os.utime(path, (OLD + 50, OLD + 50))            # a sync client restoring another modification time
    assert cache.hash(path) == first and cache.reads == 2


def test_a_file_modified_a_moment_ago_is_never_trusted_or_kept(tmp_path, store):
    cache = dep_hash.HashCache(store.db, store.lock)
    path = write(tmp_path / "a.txt", "fresh", mtime=time.time())
    assert cache.is_racy(path)
    cache.hash(path)
    cache.hash(path)
    assert cache.reads == 2                          # read both times: no shortcut for a racy file
    assert store.db.execute("SELECT COUNT(*) FROM filehash").fetchone()[0] == 0


def test_a_missing_file_has_no_hash(tmp_path, store):
    assert dep_hash.HashCache(store.db, store.lock).hash(tmp_path / "nope") is None


def test_the_audit_finds_a_change_under_an_unchanged_size_and_mtime(tmp_path, store):
    cache = dep_hash.HashCache(store.db, store.lock)
    path = write(tmp_path / "a.txt", "abcd")
    cache.hash(path)
    write(path, "abce")                              # same size, same mtime
    assert cache.hash(path) is not None and cache.reads == 1      # the shortcut cannot see it
    assert cache.audit() == [dep_hash.norm(path)]


def test_a_file_that_changes_while_it_is_read_has_no_hash(tmp_path, store):
    path = write(tmp_path / "a.txt", "abcd")

    def hasher(p):
        write(p, "abcdef")                           # another writer
        return "x"

    assert dep_hash.HashCache(store.db, store.lock, hasher=hasher).hash(path) is None


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


def test_no_key_for_a_missing_or_just_written_slide(ctx, resolver):
    assert resolver.fast_key(unit_for(ctx)) is None
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "x", mtime=time.time())
    assert resolver.fast_key(unit_for(ctx)) is None


def test_unit_for_drops_the_steps(ctx):
    from slidemage import preview_target
    target = preview_target.PreviewTarget(ctx, "slidestep", "aaa-EN-One", None, ["instructor"], "1,2", 5, None)
    unit = render_key.unit_for(target, "instructor", "en", "deck1")
    assert unit.conditions == () and unit.language == "EN" and unit.frame_number == 5


# -- manifests and freshness -------------------------------------------------------------

def make_record(resolver, ctx, unit, inputs, *, origin="background", frame=None, **extra):
    manifest = resolver.build_manifest([str(p) for p in inputs])
    key = resolver.fast_key(unit)
    meta = dict(unit=unit.label, rendered_at=time.time(), manifest=manifest.entries, frame_number=unit.frame_number if frame is None else frame,
                machine=render_key.machine_id(), tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                unstable=not manifest.stable, **extra)
    return key, meta


def store_render(store, key, meta, origin="background", pages=2, decks=("deck1",)):
    pdf = write(Path(str(store.local_dir)) / f"{origin}.pdf", "%PDF")
    return store.put(key, origin, pdf, [b"\x89PNG-%d" % n for n in range(pages)], meta, decks=decks)


def test_a_render_is_fresh_until_a_file_it_read_changes(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    image = write(ctx.media_dir / "pic.png", "img")
    preamble = write(ctx.root / "SlideMage_template_uni-graz.tex", "pre")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [ctx.slides_dir / "aaa-EN-One-current.tex", image, preamble])
    assert {rel for _, rel, _ in meta["manifest"]} == {"slides/aaa-EN-One-current.tex", "media/pic.png", "SlideMage_template_uni-graz.tex"}
    assert resolver.lookup(unit).state is Freshness.MISSING
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    write(image, "other image")
    result = resolver.lookup(unit)
    assert result.state is Freshness.STALE and result.record is not None       # shown as outdated, never as fresh
    write(image, "img")
    assert resolver.lookup(unit).state is Freshness.FRESH


def test_a_preamble_layer_change_stales_every_render_that_read_it(ctx, resolver, store):
    layer = write(ctx.root / "SlideMage_template_uni-graz.tex", "v1")
    units = [unit_for(ctx, slug) for slug in ("aaa-EN-One", "bbb-EN-Two")]
    for u in units:
        write(u.source_path, f"text {u.id_slug}")
        key, meta = make_record(resolver, ctx, u, [u.source_path, layer])
        store_render(store, key, meta)
    assert all(resolver.lookup(u).state is Freshness.FRESH for u in units)
    write(layer, "v2 longer")
    assert all(resolver.lookup(u).state is Freshness.STALE for u in units)


def test_a_new_render_of_a_stale_slide_takes_the_place_of_the_old_one_under_the_same_key(ctx, resolver, store):
    # v8.37.0 changed a framework file, which is in the manifest and not in the key: the new render of an unchanged
    # slide has the old render's key, and put kept the old object, so the sweep rendered the same slides again and
    # again (the dial rose and fell back to 0 % at every replan).
    layer = write(ctx.root / "SlideMage_template_uni-graz.tex", "v1")
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, old = make_record(resolver, ctx, unit, [unit.source_path, layer])
    store_render(store, key, old)
    write(layer, "v2 longer")
    assert resolver.lookup(unit).state is Freshness.STALE
    same_key, new = make_record(resolver, ctx, unit, [unit.source_path, layer])
    assert same_key == key
    store_render(store, key, new)
    found = resolver.lookup(unit)
    assert found.state is Freshness.FRESH and found.final
    assert store.count() == 1


def test_a_reveal_render_is_kept_when_the_background_render_of_its_key_is_stale(ctx, resolver, store):
    layer = write(ctx.root / "SlideMage_template_uni-graz.tex", "v1")
    unit = unit_for(ctx)
    write(unit.source_path, "slide")
    key, old = make_record(resolver, ctx, unit, [unit.source_path, layer])
    store_render(store, key, old, origin="background")
    write(layer, "v2 longer")
    _key, new = make_record(resolver, ctx, unit, [unit.source_path, layer])
    assert store_render(store, key, new, origin="reveal") == key
    found = resolver.lookup(unit)
    assert found.state is Freshness.FRESH and found.record["origin"] == "reveal"


def test_a_different_page_number_is_fresh_with_a_note(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx, frame=3)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    store_render(store, key, meta)
    moved = unit_for(ctx, frame=4)
    assert resolver.lookup(moved).state is Freshness.FRESH_NUMBERING_DIFFERS
    assert resolver.lookup(moved).usable and resolver.lookup(unit).final


def test_a_render_made_while_a_file_was_written_is_not_trusted(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    busy = write(ctx.media_dir / "pic.png", "being written", mtime=time.time())
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path, busy])
    assert meta["unstable"]
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is not Freshness.FRESH


def test_files_of_tex_and_the_build_are_not_in_the_manifest(ctx, resolver, tmp_path):
    tex = write(tmp_path / "texlive" / "beamer.cls", "cls")
    built = write(ctx.root / ".build" / "x.aux", "aux")
    slide = write(ctx.slides_dir / "aaa-EN-One-current.tex", "s")
    manifest = resolver.build_manifest([str(tex), str(built), str(slide)])
    assert [rel for _, rel, _ in manifest.entries] == ["slides/aaa-EN-One-current.tex"]
    assert manifest.tex_files and manifest.tex_digest


def test_a_changed_tex_file_stales_a_render_made_on_this_machine_only(ctx, resolver, store, tmp_path):
    tex = write(tmp_path / "texlive" / "beamer.cls", "cls")
    unit = unit_for(ctx)
    write(unit.source_path, "s")
    key, meta = make_record(resolver, ctx, unit, [unit.source_path, tex])
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    resolver._tex_memo.clear()
    write(tex, "a package update")
    assert resolver.lookup(unit).state is Freshness.STALE
    # the same render made on another machine is trusted on the engine and the project files
    other = unit_for(ctx, "bbb-EN-Two")
    write(other.source_path, "s2")
    key2, meta2 = make_record(resolver, ctx, other, [other.source_path, tex])
    meta2["machine"] = "elsewhere"
    store_render(store, key2, meta2)
    assert resolver.lookup(other).state is Freshness.FRESH


def test_a_framework_file_is_found_again_through_the_framework_folders(ctx, resolver, store, monkeypatch, tmp_path):
    framework = tmp_path / "fw"
    base = write(framework / "SlideMage_base.tex", "base")
    monkeypatch.setattr(render_key.slide_snapshot, "framework_dirs", lambda root: [framework])
    unit = unit_for(ctx)
    write(unit.source_path, "s")
    key, meta = make_record(resolver, ctx, unit, [unit.source_path, base])
    assert ["framework", "SlideMage_base.tex"] in [e[:2] for e in meta["manifest"]]
    store_render(store, key, meta)
    assert resolver.lookup(unit).state is Freshness.FRESH
    write(base, "base changed")
    assert resolver.lookup(unit).state is Freshness.STALE


# -- the store --------------------------------------------------------------------------

def test_background_version_replaces_the_provisional_reveal_render_and_is_not_replaced_back(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    store_render(store, key, meta, origin="reveal")
    found = resolver.lookup(unit)
    assert found.state is Freshness.FRESH and not found.final           # the sweep still renders it
    store_render(store, key, meta, origin="background")
    found = resolver.lookup(unit)
    assert found.final and found.record["origin"] == "background"
    assert not (render_store.object_dir(store.root, key)).exists()      # the provisional object is gone
    assert store_render(store, key, meta, origin="reveal").endswith(".bg")   # a late reveal render is dropped
    assert store.count() == 1


def test_objects_survive_the_loss_of_the_index_and_are_adopted_by_rescan(ctx, resolver, store, tmp_path):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    store_render(store, key, meta)
    local = store.local_dir
    store.close()
    (local / "index.sqlite").unlink()
    again_store = render_store.RenderStore(ctx, local)
    try:
        assert again_store.count() == 0 and again_store.rescan() == 1
        again = render_key.Resolver(ctx, dep_hash.HashCache(again_store.db, again_store.lock), again_store,
                                    engine_fp=lambda: "LuaHBTeX 1.22|Windows")
        assert again.lookup(unit).state is Freshness.FRESH
        assert again_store.page(again.lookup(unit).record, 1).startswith(b"\x89PNG")
    finally:
        again_store.close()


def test_the_store_creates_nothing_in_the_project_and_removes_an_earlier_copy_there(ctx, tmp_path):
    old = ctx.root / ".previews" / "render-store" / "objects" / "ab" / "cd"
    old.mkdir(parents=True)
    (old / "slide.pdf").write_bytes(b"%PDF")
    before = {p.relative_to(ctx.root).as_posix() for p in ctx.root.rglob("*") if ".previews" not in p.parts}
    local = tmp_path / "cache" / "store"
    store = render_store.RenderStore(ctx, local)
    try:
        pdf = write(tmp_path / "x.pdf", "%PDF")
        store.put("k" * 64, "background", pdf, [b"\x89PNG1"], dict(unit="u", manifest=[], rendered_at=1.0), decks=["d"])
        store.touch_deck("d", opened=True)
        store.rescan()
        assert store.root == local and (local / "objects").is_dir() and store.work_dir == local / "work"
    finally:
        store.close()
    assert not (ctx.root / ".previews" / "render-store").exists()                 # the old copy is gone
    after = {p.relative_to(ctx.root).as_posix() for p in ctx.root.rglob("*") if ".previews" not in p.parts}
    assert after == before
    assert not list(ctx.root.rglob("render-store*"))


def test_an_incomplete_object_is_ignored_until_it_is_complete(ctx, store, tmp_path):
    folder = render_store.object_dir(store.root, "ab" + "0" * 62)
    folder.mkdir(parents=True)
    (folder / "slide.pdf").write_bytes(b"%PDF")
    assert store.rescan() == 0                                                  # no meta.json yet
    meta = {"format": 1, "key": "ab" + "0" * 62, "origin": "background", "unit": "u", "files": {"slide.pdf": 99}, "bytes": 99, "decks": []}
    (folder / "meta.json").write_text(json.dumps(meta))
    assert store.rescan() == 0                                                  # size does not match yet
    meta["files"]["slide.pdf"] = 4
    (folder / "meta.json").write_text(json.dumps(meta))
    assert store.rescan() == 1


def test_eviction_order_and_protection(ctx, resolver, store):
    clock = [1000.0]
    store._clock = lambda: clock[0]
    keys = {}
    for name, deck in (("a", "old"), ("b", "recent"), ("c", "old")):
        unit = unit_for(ctx, f"{name * 3}-EN-{name}")
        write(unit.source_path, name)
        key, meta = make_record(resolver, ctx, unit, [unit.source_path])
        clock[0] += 10
        store_render(store, key, meta, decks=(deck,))
        keys[name] = key
    store.db.execute("UPDATE renders SET bytes=1000")
    assert store.total_bytes() == 3000
    store.enforce_limit(2000, protected_decks={"recent"}, keep_days=3650)
    assert store.count() == 2 and store.find(keys["b"])                    # the least recently used unprotected went
    store.enforce_limit(1000, protected_decks={"recent"}, keep_days=3650)
    assert store.count() == 1 and store.find(keys["b"])                    # one unprotected is left? no: only the protected one
    store.db.execute("UPDATE renders SET bytes=1000")
    store.enforce_limit(900, protected_decks={"recent"}, keep_days=3650)
    assert store.count() == 1                                              # protected stays unless more than twice over
    store.enforce_limit(400, protected_decks={"recent"}, keep_days=3650)
    assert store.count() == 0


def test_archiving_a_deck_deletes_only_what_no_other_deck_uses(ctx, resolver, store):
    solo, shared = unit_for(ctx, "aaa-EN-A"), unit_for(ctx, "bbb-EN-B")
    for u, decks in ((solo, ("old",)), (shared, ("old", "live"))):
        write(u.source_path, u.id_slug)
        key, meta = make_record(resolver, ctx, u, [u.source_path])
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
    assert resolver.manifest_current(entries)
    write(csv_path, header + "media/a.png,informative,auto,A,,auto,,\nmedia/b.png,informative,auto,B changed,,auto,,\n"
          "media/c.png,informative,auto,C new,,auto,,\n", OLD + 10)
    write(json_path, json.dumps({"version": 2, "images": {"media/a.png": {"short": "A"},
                                                         "media/c.png": {"short": "C"}}}), OLD + 10)
    assert resolver.manifest_current(entries)                 # another picture's alt text: still current
    write(csv_path, header + "media/a.png,informative,auto,A changed,,auto,,\n", OLD + 20)
    assert not resolver.manifest_current(entries)             # its own picture's alt text: out of date
    write(csv_path, header + "media/a.png,informative,auto,A,,auto,,\n", OLD + 30)
    write(json_path, json.dumps({"version": 2, "images": {"MEDIA/A.PNG": {"short": "A, longer"}}}), OLD + 30)
    assert not resolver.manifest_current(entries)             # matched by file name, whatever the case and folder


def test_a_rescan_that_is_stopped_forgets_no_object(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    store_render(store, key, meta)
    [folder] = [path for path in (store.root / "objects").glob("*/*") if path.is_dir()]
    shutil.rmtree(folder)                                           # gone on disk, still in the index
    assert store.rescan(lambda: True) == 0 and store.count() == 1
    assert store.rescan() == 0 and store.count() == 0


# -- the small copy of the last page (2026-10-30, direct request) -------------------------

def real_png(width=1920, height=1080, color=(200, 30, 30)) -> bytes:
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def put_real(store, ctx, resolver, pages=2):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    name = store.put(key, "background", None, [real_png() for _ in range(pages)], meta, decks=["deck1"])
    return unit, key, name


def test_put_writes_a_thumbnail_of_the_last_page_within_the_preview_cache_size_and_lists_it(ctx, resolver, store):
    from PIL import Image
    from slidemage.preview_cache import THUMBNAIL_MAX
    _unit, key, name = put_real(store, ctx, resolver)
    folder = render_store.object_dir(store.root, name)
    with Image.open(folder / "thumb.png") as im:
        assert im.width == THUMBNAIL_MAX[0] and im.height <= THUMBNAIL_MAX[1]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["files"]["thumb.png"] == (folder / "thumb.png").stat().st_size
    assert meta["pages"] == 2 and store.total_bytes() == meta["bytes"] == sum(meta["files"].values())


def test_thumbnail_path_returns_the_stored_thumbnail(ctx, resolver, store):
    _unit, key, name = put_real(store, ctx, resolver)
    record = store.find(key)[0]
    assert store.thumbnail_path(record) == render_store.object_dir(store.root, name) / "thumb.png"


def strip_thumbnail(store, name):
    """Make the object look like one stored before thumbnails: no thumb.png, not listed, not in the index's meta."""
    folder = render_store.object_dir(store.root, name)
    (folder / "thumb.png").unlink()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta["files"].pop("thumb.png")
    meta["bytes"] = sum(meta["files"].values())
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with store._lock:
        store.db.execute("UPDATE renders SET meta=?, bytes=? WHERE name=?", (json.dumps(meta), meta["bytes"], name))
        store.db.commit()
    return folder


def test_an_object_stored_before_thumbnails_gets_one_when_it_is_first_shown(ctx, resolver, store):
    _unit, key, name = put_real(store, ctx, resolver)
    folder = strip_thumbnail(store, name)
    before = store.total_bytes()
    path = store.thumbnail_path(store.find(key)[0])
    assert path == folder / "thumb.png" and path.is_file()
    assert store.total_bytes() == before + path.stat().st_size                   # counted once, for the disk limit
    assert store.thumbnail_path(store.find(key)[0]) == path and store.total_bytes() == before + path.stat().st_size
    assert not [p for p in folder.iterdir() if p.name not in ("meta.json", "p001.png", "p002.png", "thumb.png")]


def test_a_rescan_keeps_objects_with_and_without_a_listed_thumbnail(ctx, resolver, store):
    _unit, key, name = put_real(store, ctx, resolver)
    folder = strip_thumbnail(store, name)
    store.thumbnail_path(store.find(key)[0])              # made lazily, not listed in meta.json
    assert (folder / "thumb.png").is_file()
    assert store.rescan() == 0 and store.count() == 1 and store.find(key)
    local = store.local_dir
    store.close()
    (local / "index.sqlite").unlink()
    again = render_store.RenderStore(ctx, local)
    try:
        assert again.rescan() == 1 and again.count() == 1       # the unlisted file does not disturb the size check
    finally:
        again.close()


def test_a_page_that_cannot_be_scaled_has_no_thumbnail_and_nothing_breaks(ctx, resolver, store):
    write(ctx.slides_dir / "aaa-EN-One-current.tex", "slide")
    unit = unit_for(ctx)
    key, meta = make_record(resolver, ctx, unit, [unit.source_path])
    store_render(store, key, meta)                         # fake PNG bytes
    record = store.find(key)[0]
    assert not (Path(record["dir"]) / "thumb.png").exists() and store.thumbnail_path(record) is None
