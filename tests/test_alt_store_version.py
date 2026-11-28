# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Store format compatibility and preservation of saved descriptions."""
from __future__ import annotations

import json

import pytest

from slidemage import alt_images
from slidemage.alt_images import ImageEntry, NewerStoreError

IMG = "media/photo-a.png"
NEWER = '{"version": 99, "images": {"media/photo-a.png": {"role": "informative", "text": {"fr": "x"}}}, "slides": {}}\n'


@pytest.fixture
def newer_store(ctx):
    path = ctx.media_dir / "alt-text.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NEWER, encoding="utf-8")
    return path


def test_a_newer_store_is_never_overwritten(ctx, newer_store):
    assert alt_images.load_store(ctx)[IMG].role == "informative"
    assert alt_images.load_slide_notes(ctx) == {}
    with pytest.raises(NewerStoreError):
        alt_images.save_store(ctx, {IMG: ImageEntry(image=IMG)})
    with pytest.raises(NewerStoreError):
        alt_images.update_store(ctx, lambda entries: entries.pop(IMG) is not None)
    with pytest.raises(NewerStoreError):
        alt_images.update_slide_notes(ctx, lambda notes: notes.update({"s1": alt_images.SlideNotes("x")}) or True)
    with pytest.raises(NewerStoreError):
        alt_images._save_slide_notes(ctx, {"s1": alt_images.SlideNotes("x")})
    with pytest.raises(NewerStoreError):
        alt_images.check_writable(ctx)
    (ctx.media_dir / "other.png").write_bytes(b"x")
    with pytest.raises(NewerStoreError):
        alt_images.sync_store(ctx)
    assert newer_store.read_text(encoding="utf-8") == NEWER


def test_first_summary_save_and_image_description_survive_reloads(ctx):
    path = ctx.media_dir / "alt-text.json"
    assert not path.exists()
    assert alt_images.update_slide_notes(
        ctx, lambda notes: notes.update({"s1": alt_images.SlideNotes("Summary")}) or True)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": alt_images.FORMAT_VERSION, "images": {}, "slides": {"s1": {"summary": "Summary"}}}
    assert alt_images.load_store(ctx) == {}
    assert alt_images.load_slide_notes(ctx)["s1"].summary == "Summary"

    assert alt_images.update_store(
        ctx, lambda entries: entries.update({IMG: ImageEntry(image=IMG, short="Photo description")}) or True)
    alt_images.check_writable(ctx)
    assert alt_images.load_store(ctx)[IMG].short == "Photo description"
    assert alt_images.load_slide_notes(ctx)["s1"].summary == "Summary"


def test_summary_only_versioned_store_has_no_images(ctx):
    path = ctx.media_dir / "alt-text.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": alt_images.FORMAT_VERSION,
                                "slides": {"s1": {"summary": "Summary"}}}), encoding="utf-8")
    assert alt_images.load_store(ctx) == {}
    assert alt_images.load_slide_notes(ctx)["s1"].summary == "Summary"


def test_legacy_image_map_survives_a_summary_save(ctx):
    path = ctx.media_dir / "alt-text.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({IMG: {"role": "informative", "short": "Legacy description"}}), encoding="utf-8")
    assert alt_images.load_store(ctx)[IMG].short == "Legacy description"
    assert alt_images.update_slide_notes(
        ctx, lambda notes: notes.update({"s1": alt_images.SlideNotes("Summary")}) or True)
    assert alt_images.load_store(ctx)[IMG].short == "Legacy description"
    assert alt_images.load_slide_notes(ctx)["s1"].summary == "Summary"
