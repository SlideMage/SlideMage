# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library metadata follows IDs and unions sync conflict copies."""
import json
import logging

from slidemage import library_data, slide_rename, unused_content
from slidemage.project import ProjectContext


def test_rename_updates_library_file(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    (ctx.root / "slide_ids.csv").write_text('"id"\n', encoding="utf-8")
    for slide_id in ("abc", "def"):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text("Demo", encoding="utf-8")
    def seed(data):
        data.pool.add("abc")
        data.not_reusable.add("abc")
        data.topics["abc"] = {"Topic"}
        data.different_on_purpose.add((frozenset({"abc", "def"}), "fingerprint"))

    library_data.update(ctx, seed)

    slide_rename.rename_slide_id(ctx, "abc", "xyz")

    raw = json.loads((ctx.settings_dir / "library.json").read_text(encoding="utf-8"))
    assert raw == {"pool": ["xyz"], "not_reusable": ["xyz"], "topics": {"xyz": ["Topic"]},
                   "different_on_purpose": [{"ids": ["def", "xyz"], "fingerprint": "fingerprint"}]}
    assert [p.name for p in unused_content.find_unused_slides(ctx)] == ["def-EN-Demo-current.tex"]
    slide_rename.delete_slide_id(ctx, "xyz-EN-Demo")
    assert library_data.read(ctx) == library_data.LibraryData()
    assert json.loads((ctx.settings_dir / "library.json").read_text(encoding="utf-8")) == {
        "pool": [], "not_reusable": [], "topics": {}, "different_on_purpose": []}


def test_conflict_copy_merges_by_union(tmp_path, caplog):
    ctx = ProjectContext.at(tmp_path)
    assert library_data.read(ctx) == library_data.LibraryData()
    ctx.slides_dir.mkdir()
    for slug, text in (("abc-EN-Demo", "%% DE translation: def-DE-Demo\n\\includegraphics{media/pool.png}"),
                       ("def-DE-Demo", "%% Translation of: abc-EN-Demo\n"),
                       ("ghi-EN-Other", "Other")):
        (ctx.slides_dir / f"{slug}-current.tex").write_text(text, encoding="utf-8")
    ctx.media_dir.mkdir()
    (ctx.media_dir / "pool.png").touch()
    ctx.settings_dir.mkdir()
    base = {"pool": ["abc", "gone"], "not_reusable": ["abc"],
            "topics": {"abc": ["Zebra"], "gone": ["Unknown"]},
            "different_on_purpose": [{"ids": ["abc", "ghi"], "fingerprint": "first"}]}
    conflict = {"pool": ["def"], "not_reusable": ["ghi"], "topics": {"def": ["Alpha", "Zebra"]},
                "different_on_purpose": [{"ids": ["def", "ghi"], "fingerprint": "second"}]}
    path = ctx.settings_dir / "library.json"
    copy = ctx.settings_dir / "library (conflict 2026-11-15).json"
    path.write_text(json.dumps(base), encoding="utf-8")
    copy.write_text(json.dumps(conflict), encoding="utf-8")
    second = ctx.settings_dir / "library (conflict other).json"
    second.write_text(json.dumps(conflict), encoding="utf-8")
    merged = library_data.read(ctx)
    assert merged == library_data.LibraryData(
        pool={"abc"}, not_reusable={"abc", "ghi"}, topics={"abc": {"Alpha", "Zebra"}},
        different_on_purpose={(frozenset({"abc", "ghi"}), f) for f in ("first", "second")})
    assert {p.name for p in unused_content.find_unused_slides(ctx)} == {"ghi-EN-Other-current.tex"}
    assert unused_content.find_unused_media(ctx) == []
    with caplog.at_level(logging.DEBUG, logger="slidemage.library_data"):
        library_data.update(ctx, lambda _data: None)
    text = path.read_text(encoding="utf-8")
    assert "gone" not in text and "def" not in text
    assert json.loads(text)["topics"] == {"abc": ["Alpha", "Zebra"]}
    assert not copy.exists() and not second.exists()
    assert copy.name in caplog.text and second.name in caplog.text
    library_data.update(ctx, lambda data: data.topics["abc"].discard("Alpha"))
    assert library_data.read(ctx).topics["abc"] == {"Zebra"}


def test_updates_reapply_to_fresh_data_under_lock(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    for slide_id in ("abc", "def"):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").touch()
    barrier = Barrier(2)

    def add(slide_id):
        barrier.wait(timeout=5)
        library_data.update(ctx, lambda data: data.pool.add(slide_id))

    with ThreadPoolExecutor(2) as workers:
        list(workers.map(add, ("abc", "def")))
    assert library_data.read(ctx).pool == {"abc", "def"}

    library_data.update(ctx, lambda data: data.pool.clear())
    write = library_data._write
    changed = False

    def sync_arrives(ctx, data, before):
        nonlocal changed
        if not changed:
            changed = True
            (ctx.settings_dir / "library.json").write_text(json.dumps({"pool": ["def"]}))
        return write(ctx, data, before)

    monkeypatch.setattr(library_data, "_write", sync_arrives)
    library_data.update(ctx, lambda data: data.pool.add("abc"))
    assert library_data.read(ctx).pool == {"abc", "def"}
