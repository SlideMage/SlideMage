# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import threading
from pathlib import Path

import pytest

from slidemage import alt_images, unused_content
from slidemage.alt_images import ImageEntry


def test_archive_takes_unused_images_in_one_run_and_keeps_accessibility_metadata(ctx, tmp_path):
    media, slides, decks = (tmp_path / name for name in ("media", "slides", "decks"))
    for directory in (media, slides, decks):
        directory.mkdir()
    (decks / "deck.tex").write_text(r"\slide{abc-EN-Kept}", encoding="utf-8")
    for filename, image in (
        ("abc-EN-Kept-current.tex", "kept.png"),
        ("abc-EN-Kept-v1-0-0.tex", "old.png"),
        ("abd-EN-Gone-current.tex", "gone.png"),
    ):
        (slides / filename).write_text(rf"\includegraphics{{media/{image}}}", encoding="utf-8")
        (media / image).write_bytes(b"image")
    metadata = {
        "alt-text.json": '{"images": {"media/kept.png": {"long": "authored"}}}',
        "alt-text.csv": "image,role\n",
        ".alt-text.json.pending.tmp": '{"images": {}}',
    }
    for name, content in metadata.items():
        (media / name).write_text(content, encoding="utf-8")

    unused = unused_content.find_unused_media(ctx)
    assert [path.name for path in unused] == ["gone.png", "old.png"]
    # v5.14.2 needed a second run to archive images used only by an archived slide.
    assert unused_content.archive_files(
        ctx, unused, unused_content.find_unused_slides(ctx), lambda _line: None,
    ) == (2, 2)
    assert unused_content.find_unused_media(ctx) == []
    assert unused_content.find_unused_slides(ctx) == []
    assert (media / "kept.png").is_file()
    for name, content in metadata.items():
        assert (media / name).read_text(encoding="utf-8") == content


def test_init_project_preserves_existing_files(tmp_path, monkeypatch):
    from slidemage import project

    template = tmp_path / "template"
    (template / "decks").mkdir(parents=True)
    (template / "slides").mkdir()
    (template / "decks" / "demo.tex").write_text("template")
    (template / "slides" / "new.tex").write_text("new slide")
    generated = ("_slidemage_preview-x.tex", "_slidemage_snapshot-x.tex")
    for name in generated:
        (template / "decks" / name).write_text("generated wrapper")
    (template / "decks" / "_kept").mkdir()
    (template / "decks" / "_kept" / "_nested.tex").write_text("nested asset")
    (template / "_kept.tex").write_text("root asset")
    latex_template = tmp_path / "latex-template"
    latex_template.mkdir()
    (latex_template / "framework.sty").write_text("framework")
    monkeypatch.setattr(project, "template_dir",
                        lambda name: {"example": template, "latex": latex_template}.get(name))
    target = tmp_path / "existing-project"
    (target / "decks").mkdir(parents=True)
    note = target / "keep.txt"
    note.write_text("my notes")
    user_file = target / "decks" / "demo.tex"
    user_file.write_text("user data")
    with pytest.raises(project.ProjectCreationError) as error:
        project.init_project(target, copy_example=True)
    assert str(user_file) in str(error.value) and user_file.read_text() == "user data"
    assert not (target / "slides" / "new.tex").exists()
    assert note.read_text() == "my notes"

    user_file.unlink()
    project.init_project(target, copy_example=True)
    assert user_file.read_text() == "template"
    assert all(not (target / "decks" / name).exists() for name in generated)
    assert (target / "decks" / "_kept" / "_nested.tex").read_text() == "nested asset"
    assert (target / "_kept.tex").read_text() == "root asset"
    assert note.read_text() == "my notes"


@pytest.fixture
def store_path(ctx, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    alt_images.save_store(ctx, {"media/existing.png": ImageEntry(image="media/existing.png", long="before")})
    return media_dir / "alt-text.json"


def _change_description(entries):
    entries["media/existing.png"].long = "completed batch draft"
    return True


def test_sync_store_serializes_scan_with_background_save(ctx, store_path, monkeypatch):
    scan_started, continue_scan, update_started = (threading.Event() for _ in range(3))
    errors = []

    def gated_scan(_ctx):
        scan_started.set()
        assert continue_scan.wait(5), "test did not release the scan"
        return ["media/new.png"]

    def update():
        update_started.set()
        alt_images.update_store(ctx, _change_description)

    def run(work):
        try:
            work()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(alt_images, "scan_images", gated_scan)
    monkeypatch.setattr(alt_images.alt_blocks, "scan_slides_raw", lambda _ctx: [])
    scan = threading.Thread(target=run, args=(lambda: alt_images.sync_store(ctx),))
    save = threading.Thread(target=run, args=(update,))
    scan.start()
    try:
        assert scan_started.wait(5)
        # Probe the writer lock without timing the save thread.
        if alt_images._store_lock.acquire(blocking=False):
            alt_images._store_lock.release()
            pytest.fail("the scan did not hold the writer lock")
        save.start()
        assert update_started.wait(5)
    finally:
        continue_scan.set()
        scan.join(5)
        if save.ident is not None:
            save.join(5)

    assert not scan.is_alive() and not save.is_alive()
    assert not errors
    entries = alt_images.load_store(ctx)
    assert entries["media/existing.png"].long == "completed batch draft"
    assert "media/new.png" in entries
    assert json.loads(store_path.read_text(encoding="utf-8"))["images"]


def test_store_json_is_replaced_atomically(ctx, store_path, monkeypatch):
    old_bytes = store_path.read_bytes()
    real_replace = os.replace
    replacements = []

    def replace(source, destination):
        # A reader still sees the previous document as the writer swaps in the new one.
        assert store_path.read_bytes() == old_bytes
        assert Path(destination) == store_path
        assert Path(source) in store_path.parent.glob(".alt-text.json.*.tmp")
        assert json.loads(Path(source).read_text(encoding="utf-8"))["images"]
        replacements.append(destination)
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", replace)
    alt_images.update_store(ctx, _change_description)
    assert len(replacements) == 1
    assert alt_images.load_store(ctx)["media/existing.png"].long == "completed batch draft"
