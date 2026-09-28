from __future__ import annotations

import json
import threading

import pytest


def test_housekeeping_keeps_accessibility_metadata(tmp_path, monkeypatch):
    from slidemage import unused_content

    media_dir = tmp_path / "media"
    slides_dir = tmp_path / "slides"
    media_dir.mkdir()
    slides_dir.mkdir()
    (slides_dir / "used.tex").write_text(
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

    monkeypatch.setattr(unused_content, "MEDIA_DIR", media_dir)
    monkeypatch.setattr(unused_content, "SLIDES_DIR", slides_dir)

    assert unused_content.find_unused_media() == [unused]
    assert authored.is_file()
    assert generated.is_file()
    assert atomic_write.is_file()


def test_init_project_preflights_template_collisions(tmp_path, monkeypatch):
    from slidemage import project

    template = tmp_path / "template"
    (template / "decks").mkdir(parents=True)
    (template / "slides").mkdir()
    (template / "decks" / "demo.tex").write_text("template")
    (template / "slides" / "new.tex").write_text("new slide")
    latex_template = tmp_path / "latex-template"
    latex_template.mkdir()
    (latex_template / "framework.sty").write_text("framework")
    monkeypatch.setattr(
        project, "_template_dir",
        lambda name: {"example": template, "latex": latex_template}.get(name),
    )

    target = tmp_path / "existing-project"
    (target / "decks").mkdir(parents=True)
    user_file = target / "decks" / "demo.tex"
    user_file.write_text("user data")

    with pytest.raises(project.ProjectCreationError) as error:
        project.init_project(target, copy_example=True)

    assert user_file.read_text() == "user data"
    assert not (target / "slides" / "new.tex").exists()
    assert str(user_file) in str(error.value)


def test_init_project_preserves_unrelated_existing_files(tmp_path, monkeypatch):
    from slidemage import project

    template = tmp_path / "template"
    (template / "decks").mkdir(parents=True)
    (template / "decks" / "demo.tex").write_text("template")
    latex_template = tmp_path / "latex-template"
    latex_template.mkdir()
    monkeypatch.setattr(
        project, "_template_dir",
        lambda name: {"example": template, "latex": latex_template}.get(name),
    )

    target = tmp_path / "project-with-notes"
    target.mkdir()
    note = target / "keep.txt"
    note.write_text("my notes")

    project.init_project(target, copy_example=True)

    assert note.read_text() == "my notes"
    assert (target / "decks" / "demo.tex").read_text() == "template"


def test_project_picker_shows_collision_error(monkeypatch, tmp_path):
    from PySide6 import QtWidgets

    from slidemage import project

    chosen = str(tmp_path / "not-a-project")
    selections = iter([chosen, ""])

    class FakeFileDialog:
        @staticmethod
        def getExistingDirectory(*_args):
            return next(selections)

    class FakeMessageBox:
        class ButtonRole:
            AcceptRole = 1
            RejectRole = 2

        class StandardButton:
            Cancel = 3

        warnings: list[tuple[str, str]] = []

        def __init__(self, _parent):
            self.buttons = []
            self.clicked = None

        def setWindowTitle(self, _title):
            pass

        def setText(self, _text):
            pass

        def setInformativeText(self, _text):
            pass

        def addButton(self, label, _role=None):
            button = object()
            self.buttons.append((label, button))
            return button

        def setDefaultButton(self, _button):
            pass

        def exec(self):
            self.clicked = self.buttons[0][1]

        def clickedButton(self):
            return self.clicked

        @classmethod
        def warning(cls, _parent, title, message):
            cls.warnings.append((title, message))

    monkeypatch.setattr(QtWidgets, "QFileDialog", FakeFileDialog)
    monkeypatch.setattr(QtWidgets, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(project, "has_example_template", lambda: False)

    def reject_creation(path, copy_example=True):
        raise project.ProjectCreationError(path, [path / "decks" / "demo.tex"])

    monkeypatch.setattr(project, "init_project", reject_creation)

    assert project.pick_or_create_project(None, tmp_path) is None
    assert FakeMessageBox.warnings
    assert FakeMessageBox.warnings[0][0] == "Cannot create project"
    assert "demo.tex" in FakeMessageBox.warnings[0][1]


def _temporary_store(monkeypatch, tmp_path):
    from slidemage import alt_images

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    store_path = media_dir / "alt-text.json"
    csv_path = media_dir / "alt-text.csv"
    monkeypatch.setattr(alt_images, "STORE_PATH", store_path)
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", csv_path)
    return alt_images, store_path


def test_sync_store_serializes_scan_with_background_save(tmp_path, monkeypatch):
    from slidemage.alt_images import ImageEntry

    alt_images, store_path = _temporary_store(monkeypatch, tmp_path)
    alt_images.save_store({
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

    def gated_scan():
        scan_started.set()
        if not continue_scan.wait(5):
            raise AssertionError("test did not release the scan")
        return ["media/new.png"]

    monkeypatch.setattr(alt_images, "scan_images", gated_scan)
    monkeypatch.setattr(alt_images.alt_blocks, "scan_slides_raw", lambda: [])

    def sync_worker():
        try:
            alt_images.sync_store()
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
            alt_images.update_store(mutate)
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
    entries = alt_images.load_store()
    assert entries["media/existing.png"].long == "completed batch draft"
    assert "media/new.png" in entries
    assert json.loads(store_path.read_text(encoding="utf-8"))["images"]


def test_store_json_is_replaced_atomically(tmp_path, monkeypatch):
    import os

    from slidemage.alt_images import ImageEntry

    alt_images, store_path = _temporary_store(monkeypatch, tmp_path)
    alt_images.save_store({
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
            alt_images.update_store(
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
    saved = alt_images.load_store()["media/chart.png"]
    assert saved.long == "completed batch draft"


def _change_description(entries, text):
    entries["media/chart.png"].long = text
    return True
