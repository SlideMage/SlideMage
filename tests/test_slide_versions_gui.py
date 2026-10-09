"""A slide's frozen versions in the centre column: making one the current version, and freezing
the current one (the Slide versions panel is in test_side_panels_gui.py)."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

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


def test_freezing_keeps_the_current_content_as_a_version_and_moves_the_slide_on(qapp, versioned_slide, monkeypatch):
    app = FakeApp()
    centre = CentreColumn(app, WorkspaceState())
    changed = []
    centre.versions_changed.connect(lambda: changed.append(True))
    centre.freeze_version("abc-EN-Demo", "minor")
    current = (versioned_slide / "abc-EN-Demo-current.tex").read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-3-0}" in current and "Text" in current       # the content is as it was
    assert "\\setSlideVersion{1-2-0}" in (versioned_slide / "abc-EN-Demo-v1-2-0.tex").read_text(encoding="utf-8")
    assert app.logged == ["Froze abc-EN-Demo as abc-EN-Demo-v1-2-0.tex: now v1.3.0"] and changed == [True]


def test_freezing_asks_what_the_decks_do_and_cancelling_changes_nothing(qapp, versioned_slide, monkeypatch):
    from slidemage.ui.dialogs.slide_usage_dialog import DeckVersions
    from slidemage.ui.workspace import centre as centre_module

    app = FakeApp()
    centre = CentreColumn(app, WorkspaceState())
    before = (versioned_slide / "abc-EN-Demo-current.tex").read_bytes()
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *args: None)
    centre.freeze_version("abc-EN-Demo", "patch")
    assert (versioned_slide / "abc-EN-Demo-current.tex").read_bytes() == before and app.logged == []

    applied = []
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *args: DeckVersions({"course": "keep"}, None))
    monkeypatch.setattr(centre_module, "apply_deck_versions", lambda *args: applied.append(args[1:]))
    centre.freeze_version("abc-EN-Demo", "patch")
    assert applied == [("abc-EN-Demo", {"course": "keep"}, (1, 2, 0))]   # "keep" pins the version just frozen


def test_freezing_is_refused_while_the_slide_has_unsaved_edits_or_the_version_exists(qapp, versioned_slide, monkeypatch):
    centre = CentreColumn(FakeApp(), WorkspaceState())
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.open_file(current)
    centre.source.current.editor.insertPlainText("x")
    centre.freeze_version("abc-EN-Demo", "minor")
    assert "has unsaved changes" in told[-1]
    centre.source.current.editor.undo()
    centre.source.current.reload()
    (versioned_slide / "abc-EN-Demo-v1-2-0.tex").write_text("taken", encoding="utf-8")
    centre.freeze_version("abc-EN-Demo", "minor")
    assert "already frozen" in told[-1] and "1-3-0" not in current.read_text(encoding="utf-8")


def test_details_survive_a_slide_without_a_file_and_show_a_message_without_a_slide(qapp, versioned_slide):
    details = DetailsPane(FakeApp(), WorkspaceState(), lambda path: False)
    details.show_slide("zzz-EN-Gone", None)            # no file: the facts are empty, nothing raises
    details.show_slide("", None, "Select a slide")
    assert [label.text() for label in details.findChildren(QLabel)] == ["Select a slide"]
