from __future__ import annotations

import json
import threading

import pytest
from slidemage.project import ProjectContext


def test_housekeeping_keeps_accessibility_metadata(tmp_path, monkeypatch):
    from slidemage import unused_content

    media_dir = tmp_path / "media"
    slides_dir = tmp_path / "slides"
    decks_dir = tmp_path / "decks"
    media_dir.mkdir()
    slides_dir.mkdir()
    decks_dir.mkdir()
    (decks_dir / "deck.tex").write_text(r"\slide{abc-EN-Used}", encoding="utf-8")
    (slides_dir / "abc-EN-Used-current.tex").write_text(
        r"\includegraphics{media/chart.png}", encoding="utf-8"
    )
    (media_dir / "chart.png").write_bytes(b"image")
    authored = media_dir / "alt-text.json"
    authored.write_text('{"images": {"media/chart.png": {"long": "authored"}}}')
    generated = media_dir / "alt-text.csv"
    generated.write_text("image,role\n")
    atomic_write = media_dir / ".alt-text.json.pending.tmp"
    atomic_write.write_text('{"images": {}}')
    unused = media_dir / "unused.bin"
    unused.write_bytes(b"unused")

    ctx = ProjectContext.at(tmp_path)

    assert unused_content.find_unused_media(ctx) == [unused]
    assert authored.is_file()
    assert generated.is_file()
    assert atomic_write.is_file()


def test_archive_takes_the_images_of_archived_slides_in_one_run(tmp_path, monkeypatch):
    # Direct report (v5.14.2): a second click on "Archive unused content"
    # found an image that only a slide archived by the first click had used.
    from slidemage import unused_content

    media_dir = tmp_path / "media"
    slides_dir = tmp_path / "slides"
    decks_dir = tmp_path / "decks"
    for directory in (media_dir, slides_dir, decks_dir):
        directory.mkdir()
    (decks_dir / "deck.tex").write_text(r"\slide{abc-EN-Kept}", encoding="utf-8")
    (slides_dir / "abc-EN-Kept-current.tex").write_text(
        r"\includegraphics{media/kept.png}", encoding="utf-8")
    (slides_dir / "abd-EN-Gone-current.tex").write_text(
        r"\includegraphics{media/gone.png}", encoding="utf-8")
    (slides_dir / "abc-EN-Kept-v1-0-0.tex").write_text(
        r"\includegraphics{media/old.png}", encoding="utf-8")
    for name in ("kept.png", "gone.png", "old.png"):
        (media_dir / name).write_bytes(b"image")

    ctx = ProjectContext.at(tmp_path)

    assert [p.name for p in unused_content.find_unused_media(ctx)] == ["gone.png", "old.png"]
    assert unused_content.archive_files(ctx, 
        unused_content.find_unused_media(ctx), unused_content.find_unused_slides(ctx), lambda _line: None) == (2, 2)
    # a second run has nothing left to do
    assert unused_content.find_unused_media(ctx) == []
    assert unused_content.find_unused_slides(ctx) == []
    assert (media_dir / "kept.png").is_file()


@pytest.mark.parametrize("collision", [True, False])
def test_init_project_preserves_existing_files(tmp_path, monkeypatch, collision):
    """Code-review regression: preflight collisions and preserve unrelated files/assets."""
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
    if collision:
        user_file = target / "decks" / "demo.tex"
        user_file.write_text("user data")
        with pytest.raises(project.ProjectCreationError) as error:
            project.init_project(target, copy_example=True)
        assert user_file.read_text() == "user data"
        assert not (target / "slides" / "new.tex").exists()
        assert str(user_file) in str(error.value)
    else:
        project.init_project(target, copy_example=True)
        assert (target / "decks" / "demo.tex").read_text() == "template"
        assert all(not (target / "decks" / name).exists() for name in generated)
        assert (target / "decks" / "_kept" / "_nested.tex").read_text() == "nested asset"
        assert (target / "_kept.tex").read_text() == "root asset"
    assert note.read_text() == "my notes"


def _temporary_store(monkeypatch, tmp_path):
    from slidemage import alt_images

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    store_path = media_dir / "alt-text.json"
    return alt_images, store_path


def test_sync_store_serializes_scan_with_background_save(ctx, tmp_path, monkeypatch):
    from slidemage.alt_images import ImageEntry

    alt_images, store_path = _temporary_store(monkeypatch, tmp_path)
    alt_images.save_store(ctx, {
        "media/existing.png": ImageEntry(
            image="media/existing.png", long="before"
        ),
    })

    scan_started = threading.Event()
    continue_scan = threading.Event()
    update_started = threading.Event()
    mutation_entered = threading.Event()
    sync_done = threading.Event()
    update_done = threading.Event()
    errors: list[BaseException] = []

    def gated_scan(_ctx):
        scan_started.set()
        if not continue_scan.wait(5):
            raise AssertionError("test did not release the scan")
        return ["media/new.png"]

    monkeypatch.setattr(alt_images, "scan_images", gated_scan)
    monkeypatch.setattr(alt_images.alt_blocks, "scan_slides_raw", lambda _ctx: [])

    def sync_worker():
        try:
            alt_images.sync_store(ctx)
        except BaseException as exc:  # propagate worker failures to the test
            errors.append(exc)
        finally:
            sync_done.set()

    def update_worker():
        update_started.set()

        def mutate(entries):
            mutation_entered.set()
            entries["media/existing.png"].long = "completed batch draft"
            return True

        try:
            alt_images.update_store(ctx, mutate)
        except BaseException as exc:
            errors.append(exc)
        finally:
            update_done.set()

    sync_thread = threading.Thread(target=sync_worker)
    sync_thread.start()
    update_thread = None
    try:
        assert scan_started.wait(5)
        # The scan must hold the shared writer lock for its whole lifetime.
        # A nonblocking probe makes this assertion deterministic.
        probe_acquired = alt_images._store_lock.acquire(blocking=False)
        if probe_acquired:
            alt_images._store_lock.release()
        assert not probe_acquired

        update_thread = threading.Thread(target=update_worker)
        update_thread.start()
        assert update_started.wait(5)
    finally:
        continue_scan.set()
        sync_thread.join(5)
        if update_thread is not None:
            update_thread.join(5)

    assert sync_done.is_set()
    assert update_done.is_set()
    assert mutation_entered.is_set()
    assert not sync_thread.is_alive()
    assert not update_thread.is_alive()
    assert not errors
    entries = alt_images.load_store(ctx)
    assert entries["media/existing.png"].long == "completed batch draft"
    assert "media/new.png" in entries
    assert json.loads(store_path.read_text(encoding="utf-8"))["images"]


def test_store_json_is_replaced_atomically(ctx, tmp_path, monkeypatch):
    import os

    from slidemage.alt_images import ImageEntry

    alt_images, store_path = _temporary_store(monkeypatch, tmp_path)
    alt_images.save_store(ctx, {
        "media/chart.png": ImageEntry(image="media/chart.png", long="before"),
    })
    old_bytes = store_path.read_bytes()

    replace_started = threading.Event()
    continue_replace = threading.Event()
    update_done = threading.Event()
    errors: list[BaseException] = []
    real_replace = os.replace

    def gated_replace(source, destination):
        replace_started.set()
        if not continue_replace.wait(5):
            raise AssertionError("test did not release atomic replacement")
        real_replace(source, destination)

    monkeypatch.setattr(alt_images.os, "replace", gated_replace)

    def update_worker():
        try:
            alt_images.update_store(ctx, 
                lambda entries: _change_description(entries, "completed batch draft")
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            update_done.set()

    thread = threading.Thread(target=update_worker)
    thread.start()
    try:
        assert replace_started.wait(5)
        # A reader sees a complete previous JSON document until replacement.
        assert store_path.read_bytes() == old_bytes
        assert json.loads(store_path.read_text(encoding="utf-8"))["images"]
        assert list(store_path.parent.glob(".alt-text.json.*.tmp"))
    finally:
        continue_replace.set()
        thread.join(5)

    assert update_done.is_set()
    assert not thread.is_alive()
    assert not errors
    saved = alt_images.load_store(ctx)["media/chart.png"]
    assert saved.long == "completed batch draft"


def _change_description(entries, text):
    entries["media/chart.png"].long = text
    return True
