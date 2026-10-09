"""A slide's frozen versions in the Details view and the Source view: listing them,
opening one read-only, and making one the current version."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from slidemage import alt_images
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.centre import CentreColumn
from slidemage.ui.workspace.details_view import DetailsPane
from slidemage.ui.workspace.state import WorkspaceState

from conftest import use_slides_folder

BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeApp:
    def __init__(self):
        self.theme = ThemeManager()
        self.logged = []
        self.opened = []

    def log(self, line):
        self.logged.append(line)

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)


@pytest.fixture
def versioned_slide(tmp_path, monkeypatch):
    """A slide with two frozen versions, in a throwaway slides/ folder."""
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "abc-EN-Demo-current.tex").write_text("\\setSlideVersion{1-2-0}\n" + BODY, encoding="utf-8")
    for version in ("1-0-0", "1-1-0"):
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(
            f"\\setSlideVersion{{{version}}}\n" + BODY.replace("Text", f"Text of {version}"), encoding="utf-8")
    use_slides_folder(monkeypatch, slides)
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
    return slides


def buttons(widget, text):
    return [b for b in widget.findChildren(QPushButton) if b.text() == text]


def test_details_lists_the_frozen_versions_newest_first_and_opens_them(qapp, versioned_slide):
    opened, restored = [], []
    details = DetailsPane(FakeApp(), WorkspaceState(), lambda path: False)
    details.open_requested.connect(opened.append)
    details.restore_requested.connect(restored.append)
    details.show_slide("abc-EN-Demo", None)
    # the first is the slide's own version in the facts, then the frozen ones
    assert [label.text() for label in details.findChildren(QLabel) if label.text().startswith("v1.")] == [
        "v1.2.0", "v1.1.0", "v1.0.0"]
    open_buttons = buttons(details, "Open")
    assert len(open_buttons) == 2
    open_buttons[1].click()
    assert opened == [versioned_slide / "abc-EN-Demo-v1-0-0.tex"]
    buttons(details, "Make this the current version")[0].click()
    assert restored == [versioned_slide / "abc-EN-Demo-v1-1-0.tex"]


def test_a_frozen_version_that_vanished_is_reported(qapp, versioned_slide, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    details = DetailsPane(FakeApp(), WorkspaceState(), lambda path: False)
    details.show_slide("abc-EN-Demo", None)
    (versioned_slide / "abc-EN-Demo-v1-1-0.tex").unlink()
    details._open_version(versioned_slide / "abc-EN-Demo-v1-1-0.tex")
    assert told and "no longer exists" in told[0]
    assert len(buttons(details, "Open")) == 1       # the list was redrawn


def test_making_a_version_current_archives_the_current_one_and_reopens_it(qapp, versioned_slide, monkeypatch):
    app = FakeApp()
    centre = CentreColumn(app, WorkspaceState())
    answers = iter([QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: next(answers))
    centre.restore_version(versioned_slide / "abc-EN-Demo-v1-0-0.tex")
    current = (versioned_slide / "abc-EN-Demo-current.tex").read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-3-0}" in current          # the restored content gets a new, higher version
    assert (versioned_slide / "abc-EN-Demo-v1-2-0.tex").exists()    # what was current is archived
    assert any(line.startswith("Restored abc-EN-Demo-v1-0-0.tex") for line in app.logged)
    assert centre.source.current.path == versioned_slide / "abc-EN-Demo-current.tex"


def test_making_a_version_current_is_refused_while_the_current_slide_has_unsaved_edits(
        qapp, versioned_slide, monkeypatch):
    centre = CentreColumn(FakeApp(), WorkspaceState())
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.open_file(current)
    centre.source.current.editor.insertPlainText("x")
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("must not ask"))
    centre.restore_version(versioned_slide / "abc-EN-Demo-v1-0-0.tex")
    assert len(told) == 1 and "has unsaved changes" in told[0]
    assert "x" in centre.source.current.editor.text() and "Text of 1-0-0" not in current.read_text(encoding="utf-8")


def test_details_survive_a_slide_without_a_file_and_show_a_message_without_a_slide(qapp, versioned_slide):
    details = DetailsPane(FakeApp(), WorkspaceState(), lambda path: False)
    details.show_slide("zzz-EN-Gone", None)            # no file: the facts are empty, nothing raises
    details.show_slide("", None, "Select a slide")
    assert [label.text() for label in details.findChildren(QLabel)] == ["Select a slide"]
