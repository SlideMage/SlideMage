# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A store a newer SlideMage wrote (a higher "version") is read but never written: an older SlideMage would
drop the fields it does not know."""
from __future__ import annotations

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


def test_a_newer_store_can_be_read(ctx, newer_store):
    assert alt_images.load_store(ctx)[IMG].role == "informative"
    assert alt_images.load_slide_notes(ctx) == {}


def test_a_newer_store_is_never_overwritten(ctx, newer_store):
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
    assert newer_store.read_text(encoding="utf-8") == NEWER


def test_sync_store_leaves_a_newer_store_alone(ctx, newer_store):
    (ctx.media_dir / "other.png").write_bytes(b"x")
    with pytest.raises(NewerStoreError):
        alt_images.sync_store(ctx)
    assert newer_store.read_text(encoding="utf-8") == NEWER


def test_the_current_version_is_written(ctx):
    alt_images.save_store(ctx, {IMG: ImageEntry(image=IMG)})
    alt_images.check_writable(ctx)
    assert IMG in alt_images.load_store(ctx)
