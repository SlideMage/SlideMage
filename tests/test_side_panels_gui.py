"""The right column: the panel picker and the panels Used in decks, Slide versions and Visibility."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from slidemage import app_settings, deck_scan
from slidemage.archive import _read
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import SegmentedControl, Toast
from slidemage.ui.workspace import slide_list as slide_list_module
from slidemage.ui.workspace.panels import PANELS
from slidemage.ui.workspace.panels.base import Row
from slidemage.ui.workspace.side_panels import SETTING, SidePanels
from slidemage.ui.workspace.slide_list import SlideList
from slidemage.ui.workspace.state import WorkspaceState

from conftest import use_slides_folder

HEAD = "\\documentclass{beamer}\n\\begin{document}\n"
FRAME = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeCentre:
    """What the Slide versions panel asks of the centre column."""

    def __init__(self):
        self.restored, self.frozen = [], []

    def restore_version(self, path):
        self.restored.append(path)

    def freeze_version(self, id_slug, level):
        self.frozen.append((id_slug, level))


class FakeWindow:
    """What the panels need of the window: the slide list's edits, the rescan after one, the editor."""

    def __init__(self, state):
        self.state = state
        self.slide_list = None
        self.panels = None
        self.centre = FakeCentre()
        self.opened = []
        self.logged = []

    def after_deck_edit(self, path, summary, previous_text=None):
        self.state.set_deck(next(d for d in deck_scan.scan_decks() if d.path == path))
        self.slide_list.rebuild()
        self.slide_list.deck_edited(path, summary, previous_text)
        self.panels.refresh()

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)

    def log(self, line):
        self.logged.append(line)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Two decks and a few slides in a throwaway project; `open_deck(name)` opens one."""
    decks, slides = tmp_path / "decks", tmp_path / "slides"
    (decks / "archive").mkdir(parents=True)
    slides.mkdir()
    monkeypatch.setattr(deck_scan, "DECKS_DIR", decks)
    monkeypatch.setattr(deck_scan, "ARCHIVE_DIR", decks / "archive")
    use_slides_folder(monkeypatch, slides)
    for name in ("abc-EN-Demo", "xyz-EN-Other"):
        (slides / f"{name}-current.tex").write_text(FRAME, encoding="utf-8")
    for deck, body in {
        "course": "\\slide{xyz-EN-Other}\n\\slide{abc-EN-Demo}\n\\slidestep{abc-EN-Demo}[instructor]{2}\n",
        "talk": "\\conditionalslide[instructor,during-course]{abc-EN-Demo}\n\\slideversion{abc-EN-Demo}{1-0-0}\n",
    }.items():
        (decks / f"{deck}.tex").write_text(HEAD + body + "\\end{document}\n", encoding="utf-8", newline="")
    (slides / "abc-EN-Demo-v1-0-0.tex").write_text(FRAME, encoding="utf-8")
    monkeypatch.setattr(slide_list_module.QMessageBox, "critical", lambda *args: project.errors.append(args[2]))
    project.errors = []
    project.decks = decks
    return project


@pytest.fixture
def column(project, qapp):
    """The right column over the "course" deck, with the slide list that applies its edits."""
    state = WorkspaceState()
    window = FakeWindow(state)
    holder = QWidget()
    window.slide_list = SlideList(window, state, ThemeManager(), Toast(holder))
    window.panels = SidePanels(window, state)
    state.set_deck(next(d for d in deck_scan.scan_decks() if d.name == "course"))
    yield window.panels, state, window
    holder.deleteLater()
    window.slide_list.deleteLater()
    window.panels.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def rows(panel):
    return panel.findChildren(Row)


# -- the host ---------------------------------------------------------------------------------

def test_the_picker_names_the_panel_and_lists_all_of_them(column):
    panels, _state, _window = column
    assert [p.key for p in PANELS] == list(panels.panels)
    assert panels.picker.text() == "Used in decks"
    panels._open_menu()
    menu = next(m for m in QApplication.topLevelWidgets() if type(m).__name__ == "PopoverMenu" and m.isVisible())
    assert [(e[1], e[2], e[4]) for e in menu._entries if e[0] == "item"] == [
        ("used", "Used in decks", "check"), ("versions", "Slide versions", ""), ("visibility", "Visibility", "")]
    menu.triggered.emit("visibility")
    menu.close()
    assert panels.picker.text() == "Visibility" and app_settings.get(SETTING) == "visibility"


def test_the_chosen_panel_is_remembered_and_only_it_is_shown(column, project):
    panels, state, window = column
    panels.set_panel("versions")
    again = SidePanels(window, state)
    assert again.current == "versions"
    assert [key for key, p in again.panels.items() if not p.isHidden()] == ["versions"]
    app_settings.set(SETTING, "gone")
    assert SidePanels(window, state).current == "used"        # an unknown value falls back to the first
    again.deleteLater()


def test_panels_follow_the_focused_slide_and_say_so_without_one(column):
    panels, state, _window = column
    assert texts(panels.panels["used"]) == ["Select a slide in the list."]
    state.set_focused_slide("abc")
    assert any("abc-EN-Demo" in t or "course" in t for t in texts(panels.panels["used"]))
    state.set_focused_slide(None)
    assert texts(panels.panels["used"]) == ["Select a slide in the list."]


# -- Used in decks -------------------------------------------------------------------------------

def test_used_in_decks_lists_every_call_with_how_and_where(column):
    panels, state, _window = column
    state.set_focused_slide("abc")
    lines = texts(panels.panels["used"])
    assert lines[:6] == [
        "course", "\\slide, follows the current version · slide 2 of 3",
        "course", "\\slidestep, steps 2 · slide 3 of 3 · hidden in During course, After course",
        "talk", "\\conditionalslide, always the current version · slide 1 of 2 · hidden in After course"]
    assert "talk" in lines and "\\slideversion, frozen v1.0.0 · slide 2 of 2" in lines


def test_a_slide_no_deck_calls_says_so(column, project):
    panels, state, _window = column
    (project.decks.parent / "slides" / "new-EN-Fresh-current.tex").write_text(FRAME, encoding="utf-8")
    state.set_focused_slide("new")
    assert "No deck calls this slide." in texts(panels.panels["used"])


def test_clicking_a_call_opens_that_deck_at_that_slide(column):
    panels, state, _window = column
    state.set_focused_slide("abc")
    used = panels.panels["used"]
    talk = next(r for r in rows(used) if r.findChildren(QLabel)[0].text() == "talk")
    talk.activated.emit()
    assert state.deck.name == "talk" and state.focused_slide == "abc"
    state.set_focused_slide(None)
    state.set_focused_slide("abc")
    next(r for r in rows(panels.panels["used"]) if r.findChildren(QLabel)[0].text() == "course").activated.emit()
    assert state.deck.name == "course" and state.focused_slide == "abc"


# -- Visibility ----------------------------------------------------------------------------------

def cells(panel):
    return [b for b in panel.findChildren(QPushButton) if b.objectName() == "kitMatrixCell"]


def test_the_matrix_has_a_row_per_call_and_a_column_per_view(column):
    panels, state, _window = column
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    panel = panels.panels["visibility"]
    assert [b.isChecked() for b in cells(panel)] == [True] * 3 + [True, False, False]   # \slide, then \slidestep [instructor]
    assert "Steps 2" in texts(panel) and "Whole slide" in texts(panel)
    assert panels.suffix.text() == "Instructor highlighted"
    state.set_view("after-course")
    assert panels.suffix.text() == "After course highlighted"


def test_a_cell_writes_the_deck_and_the_list_follows(column, project):
    panels, state, window = column
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    cells(panels.panels["visibility"])[2].click()             # \slide: hide in After course
    assert "\\conditionalslide[instructor,during-course]{abc-EN-Demo}" in _read(project.decks / "course.tex")
    assert [b.isChecked() for b in cells(panels.panels["visibility"])][:3] == [True, True, False]
    state.set_view("after-course")                             # the slide list shows it hidden in that view
    assert window.slide_list.tree.data_of(window.slide_list.tree.currentItem()).hidden
    cells(panels.panels["visibility"])[4].click()              # \slidestep [instructor]: also show it to During
    assert "\\slidestep{abc-EN-Demo}[instructor,during-course]{2}" in _read(project.decks / "course.tex")
    assert window.slide_list.toast.isHidden() is False         # an edit like any other: with Undo


def test_a_slide_cannot_be_hidden_from_every_view_and_the_cell_snaps_back(column, project):
    panels, state, _window = column
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    before = _read(project.decks / "course.tex")
    cells(panels.panels["visibility"])[3].click()              # \slidestep [instructor] -> hidden from all
    assert "at least one view" in project.errors[-1]
    assert _read(project.decks / "course.tex") == before
    assert cells(panels.panels["visibility"])[3].isChecked()


def test_a_pinned_call_shows_its_state_but_cannot_be_changed(column, project):
    panels, state, _window = column
    state.set_deck(next(d for d in deck_scan.scan_decks() if d.name == "talk"))
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    panel = panels.panels["visibility"]
    pinned = cells(panel)[3:]
    assert [b.isEnabled() for b in pinned] == [False] * 3 and [b.isEnabled() for b in cells(panel)[:3]] == [True] * 3


def test_the_panel_says_when_the_open_deck_does_not_use_the_slide(column, project):
    panels, state, _window = column
    panels.set_panel("visibility")
    state.set_focused_slide("xyz")
    state.set_deck(next(d for d in deck_scan.scan_decks() if d.name == "talk"))
    state.set_focused_slide("xyz")
    assert "talk does not call this slide." in texts(panels.panels["visibility"])


# -- Slide versions ------------------------------------------------------------------------------

def buttons(widget, text):
    return [b for b in widget.findChildren(QPushButton) if b.text() == text]


def test_the_versions_panel_lists_current_and_frozen_versions_with_their_decks(column, project):
    panels, state, window = column
    panels.set_panel("versions")
    state.set_focused_slide("abc")
    panel = panels.panels["versions"]
    lines = texts(panel)
    assert lines[:4] == ["untracked", "current, the live text · used by course, talk",
                         "v1.0.0", lines[3]] and lines[3].startswith("frozen ") and lines[3].endswith("used by talk")
    assert panel.meta() == "1 frozen"
    assert len(buttons(panel, "Open")) == 2 and len(buttons(panel, "Make current")) == 1
    buttons(panel, "Open")[1].click()
    buttons(panel, "Make current")[0].click()
    slides = project.decks.parent / "slides"
    assert window.opened == [slides / "abc-EN-Demo-v1-0-0.tex"]
    assert window.centre.restored == [slides / "abc-EN-Demo-v1-0-0.tex"]


def test_a_frozen_version_that_vanished_is_reported_and_dropped_from_the_list(column, project, monkeypatch):
    panels, state, window = column
    panels.set_panel("versions")
    state.set_focused_slide("abc")
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    open_frozen = buttons(panels.panels["versions"], "Open")[1]
    (project.decks.parent / "slides" / "abc-EN-Demo-v1-0-0.tex").unlink()
    open_frozen.click()
    assert told and "no longer exists" in told[0] and window.opened == []
    assert len(buttons(panels.panels["versions"], "Open")) == 1


def test_the_pin_moves_the_open_decks_calls_to_a_version_and_back(column, project):
    panels, state, _window = column
    panels.set_panel("versions")
    state.set_focused_slide("abc")
    panel = panels.panels["versions"]
    assert buttons(panel, "current ▾")
    panel._set_pin("abc-EN-Demo", "1-0-0")
    deck = _read(project.decks / "course.tex")
    assert "\\slideversion{abc-EN-Demo}{1-0-0}" in deck
    assert "\\slidestep{abc-EN-Demo}[instructor]{2}" in deck       # a call with no pinned form stays
    assert buttons(panel, "v1.0.0 ▾")
    panel._set_pin("abc-EN-Demo", None)
    assert "\\slide{abc-EN-Demo}" in _read(project.decks / "course.tex")
    assert "slideversion" not in _read(project.decks / "course.tex")


def test_the_pin_row_says_when_there_is_nothing_to_pin(column, project):
    panels, state, _window = column
    panels.set_panel("versions")
    state.set_deck(next(d for d in deck_scan.scan_decks() if d.name == "talk"))
    state.set_focused_slide("xyz")
    assert "talk does not call this slide." in texts(panels.panels["versions"])


def test_freezing_asks_the_centre_with_the_chosen_level(column):
    panels, state, window = column
    panels.set_panel("versions")
    state.set_focused_slide("abc")
    panel = panels.panels["versions"]
    assert buttons(panel, "Freeze as v1.1.0")                      # an untracked slide is 1.0.0: a minor bump
    levels = panel.findChildren(SegmentedControl)[0]
    levels._buttons["patch"].click()
    buttons(panel, "Freeze as v1.0.1")[0].click()
    assert window.centre.frozen == [("abc-EN-Demo", "patch")]
