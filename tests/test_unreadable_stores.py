# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unreadable stores must survive project opening and save attempts."""
from __future__ import annotations

import pytest

from conftest import write_test_file
from slidemage import alt_archive, alt_images, draft_prompts, fileio, qr_code
from slidemage.alt_images import NewerStoreError, SlideNotes, UnreadableStoreError

def damage(path, text):
    return write_test_file(path, f"<<<<<<< HEAD\n{text}\n=======\n{text}\n>>>>>>> other\n")


@pytest.fixture
def damaged_store(ctx):
    data = ('{"version": %d, "images": {"media/a.png": {"role": "informative", '
            '"text": {"en": {"short": "A chart"}}}}, "slides": {}}' % alt_images.FORMAT_VERSION)
    return damage(ctx.media_dir / "alt-text.json", data)


def test_strict_json_read(tmp_path):
    path = tmp_path / "store.json"
    assert fileio.read_json_strict(path) == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert fileio.read_json_strict(path, list) == [1, 2]
    with pytest.raises(fileio.UnreadableFileError, match="not a JSON object"):
        fileio.read_json_strict(path)
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(fileio.UnreadableFileError, match="store.json cannot be read"):
        fileio.read_json_strict(path)
    path.write_bytes(b"\xff\xfe{}")
    with pytest.raises(fileio.UnreadableFileError, match="not UTF-8"):
        fileio.read_json_strict(path)
    assert fileio.read_json(path) == {}


def test_alt_text_saves_leave_the_damaged_store_intact(ctx, damaged_store):
    before = damaged_store.read_bytes()
    with pytest.raises(UnreadableStoreError) as raised:
        alt_images.update_slide_notes(ctx, lambda notes: notes.__setitem__("abc", SlideNotes("s")) or True)
    assert isinstance(raised.value, NewerStoreError) and isinstance(raised.value, ValueError)
    assert "alt-text.json cannot be read" in str(raised.value)
    assert damaged_store.read_bytes() == before
    with pytest.raises(UnreadableStoreError):
        alt_images.update_store(ctx, lambda entries: True)
    assert damaged_store.read_bytes() == before
    with pytest.raises(UnreadableStoreError):
        alt_images.check_writable(ctx)
    assert damaged_store.read_bytes() == before


def test_opening_the_project_leaves_a_damaged_store(ctx, damaged_store):
    before = damaged_store.read_bytes()
    assert alt_images.convert_store(ctx) is False
    assert damaged_store.read_bytes() == before
    assert not list(damaged_store.parent.glob("alt-text.v*.json"))


def test_a_damaged_archive_is_never_replaced(ctx):
    path = damage(alt_archive.archive_path(ctx), '{"version": 1, "images": {}, "slides": {"abc": [{"name": "x"}]}}')
    before = path.read_bytes()
    with pytest.raises(UnreadableStoreError):
        alt_archive.load(ctx)
    with pytest.raises(NewerStoreError):        # what archive_slides' callers catch
        alt_archive.archive_slides(ctx, [("abc", "abc-EN-Gone")], alt_archive.REASON_SLIDE_DELETED)
    assert path.read_bytes() == before


def test_a_damaged_prompt_store_is_not_replaced(ctx):
    path = damage(ctx.settings_dir / "draft_prompts.json", '{"long": "mine"}')
    before = path.read_bytes()
    with pytest.raises(fileio.UnreadableFileError):
        draft_prompts.set_custom_prompt(ctx, "short", "a prompt of my own", "the default")
    assert path.read_bytes() == before


def test_a_damaged_qr_store_is_refused_before_the_code_is_written(ctx):
    store = write_test_file(qr_code._store_path(ctx), "{oops")
    before = set(ctx.media_dir.iterdir())
    with pytest.raises(fileio.UnreadableFileError):
        qr_code.create(ctx, qr_code.QRSpec(qr_code.KIND_URL, {"url": "https://example.org"}), name="code")
    assert set(ctx.media_dir.iterdir()) == before
    assert store.read_text(encoding="utf-8") == "{oops"
