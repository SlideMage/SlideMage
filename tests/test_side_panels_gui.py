# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The right column: the panel picker and the eight panels (Used in decks, Slide versions, Visibility,
Citations, Language, Image descriptions, Transcript entry, Speaker notes)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from conftest import build_window, make_project, wait_until
from slidemage import app_settings, deck_scan, slide_snapshot
from slidemage.fileio import read_text_exact as read
from slidemage.slide_source import read_slide_source
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import SegmentedControl, Toast
from slidemage.ui.workspace import slide_list as slide_list_module
from slidemage.ui.workspace.panels import PANELS
from slidemage.project import ProjectContext
from slidemage.ui.workspace.panels.base import Row
from slidemage.ui.workspace.panels.used import UsedInDecks
from slidemage.ui.workspace.preview_view import PreviewPane
from slidemage.ui.workspace.side_panels import PANEL_MIN_HEIGHT, SETTING, SidePanels
from slidemage.ui.workspace.panels.base import PanelActions
from slidemage.ui.workspace.slide_list import SlideList
from slidemage.ui.workspace.state import WorkspaceState


HEAD = "\\documentclass{beamer}\n\\begin{document}\n"
FRAME = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


class FakeCentre:
    """What the panels ask of the centre column: versions, the Source view's buffers and its Save."""

    def __init__(self):
        self.path = None
        self.restored, self.frozen, self.saved, self.references = [], [], [], []
        self.buffers: dict = {}
        self.unsaved: set = set()
        self.source = SimpleNamespace(save=lambda: self.saved.append(True) or True, add_reference=self.references.append)

    def slide_text(self, path):
        return self.buffers[path] if path in self.buffers else read_slide_source(path)[0]

    def is_dirty(self, path):
        return path in self.unsaved

    def edit_slide_text(self, path, change, show=False):
        self.shown_for_edit = show
        self.buffers[path] = change(self.slide_text(path))
        return True

    def restore_version(self, path):
        self.restored.append(path)

    def freeze_version(self, id_slug, level):
        self.frozen.append((id_slug, level))


class FakeWindow:
    project = property(lambda self: self.state.project)
    """What the panels need of the window: the slide list's edits, the rescan after one, the editor."""

    def __init__(self, state):
        self.state = state
        self.decks = deck_scan.scan_decks(state.project)     # kept current by the window's reload_decks
        self.theme = ThemeManager()
        self.slide_list = None
        self.panels = None
        self.centre = FakeCentre()
        self.opened = []
        self.translated = []
        self.logged = []
        self.busy = None
        self.actions = PanelActions(
            slide_text=self.centre.slide_text, is_dirty=self.centre.is_dirty,
            edit_slide_text=self.centre.edit_slide_text, save_source=self.centre.source.save,
            restore_version=self.centre.restore_version, freeze_version=self.centre.freeze_version,
            edit_deck=lambda *a, **k: self.slide_list.edit(*a, **k),
            add_slide=lambda *a, **k: self.slide_list.add_slide(*a, **k), translate=lambda: self.translated.append(True),
            add_reference=self.centre.source.add_reference)

    def acquire_route_task(self, route_id, label):
        from slidemage.plugins.host import _RouteTaskLease
        self.busy = label
        return _RouteTaskLease(lambda: setattr(self, "busy", None))

    def refresh_open_deck_editors(self):
        self.refreshed = getattr(self, "refreshed", 0) + 1

    def after_deck_edit(self, path, summary, previous_text=None):
        self.state.set_deck(next(d for d in deck_scan.scan_decks(self.state.project) if d.path == path))
        self.slide_list.rebuild()
        self.slide_list.deck_edited(path, summary, previous_text)
        self.panels.refresh()

    def open_slide_editor(self, path, **kwargs):
        self.opened.append((path, kwargs) if kwargs else path)

    def log(self, line):
        self.logged.append(line)

    def open_add_slide_dialog(self, deck, insert_at, indent, **start):
        self.started = getattr(self, "started", []) + [start]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Two decks and a few slides in a throwaway project; `open_deck(name)` opens one."""
    decks, slides = tmp_path / "decks", tmp_path / "slides"
    (decks / "archive").mkdir(parents=True)
    slides.mkdir()
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
def column(project, qapp, ctx, fake_routes):
    """The right column over the "course" deck, with the slide list that applies its edits."""
    state = WorkspaceState(ctx)
    window = FakeWindow(state)
    holder = QWidget()
    window.slide_list = SlideList(window, state, ThemeManager(), Toast(holder))
    window.panels = SidePanels(window, state, window.actions)
    window.panels._defer = window.panels.refresh     # these tests are about what a panel shows; `debounced` undoes this
    state.set_deck(next(d for d in deck_scan.scan_decks(ctx) if d.name == "course"))
    yield window.panels, state, window
    holder.deleteLater()
    window.slide_list.deleteLater()
    window.panels.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def test_de_panels_use_german_content_but_visibility_uses_the_original_call(column, project):
    panels, state, window = column
    slides = project.decks.parent / "slides"
    english = slides / "abc-EN-Demo-current.tex"
    german = slides / "ddd-DE-Beispiel-current.tex"
    english.write_text("%% DE translation: ddd-DE-Beispiel\n" + FRAME)
    german.write_text("%% Translation of: abc-EN-Demo\n" + FRAME.replace("Demo", "Beispiel"))
    state.set_focused_slide("abc")
    panels.set_panel("notes")
    notes = panels.panels["notes"]
    notes._new.setPlainText("English pending note")
    state.set_language("DE")
    assert "English pending note" in window.centre.buffers[english]
    assert german not in window.centre.buffers
    assert notes.id_slug() == "ddd-DE-Beispiel" and notes.slide_path() == german
    notes._new.setPlainText("German pending note")
    notes.flush()
    assert "German pending note" in window.centre.buffers[german]
    panels.set_panel("language")
    assert panels.panels["language"].id_slug() == "ddd-DE-Beispiel"
    assert "A translation of abc-EN-Demo." in texts(panels.panels["language"])
    visibility = panels.panels["visibility"]
    assert [call.id for _, call in visibility.deck_calls()] == ["abc", "abc"]
    visibility._set(visibility.deck_calls()[0][1], "after-course", False)
    assert "\\conditionalslide[instructor,during-course]{abc-EN-Demo}" in state.deck.text
    assert not project.errors


def rows(panel):
    return panel.findChildren(Row)


# -- the host ---------------------------------------------------------------------------------

def card_heights(panels):
    return panels.card.height(), panels.assistant.height()


def test_the_cards_share_the_column_38_to_62_with_a_12_px_gap(column, qapp):
    panels, state, _window = column
    state.set_focused_slide("abc")
    panels.resize(360, 1000)
    panels.show()
    qapp.processEvents()
    top, bottom = card_heights(panels)
    assert panels.assistant.geometry().top() - panels.card.geometry().bottom() - 1 == 12
    assert top + bottom + 12 == 1000
    assert top == pytest.approx((1000 - 12) * 0.38, abs=2)


@pytest.mark.parametrize("height", [700, 600, 540])
def test_a_short_column_gives_way_in_the_side_panels_first(column, qapp, height):
    panels, state, _window = column
    state.set_focused_slide("abc")
    panels.resize(360, height)
    panels.show()
    qapp.processEvents()
    top, bottom = card_heights(panels)
    assert panels.height() == height
    assert top >= PANEL_MIN_HEIGHT and bottom >= panels.assistant.minimumHeight() == 380
    if height <= 600:
        assert bottom == pytest.approx(380, abs=2)
    assert panels.picker.isVisible() and panels.card.rect().contains(panels.picker.geometry())
    chat = panels.assistant.chat
    for control in (chat.composer, chat.mode_picker, chat.send_button):
        assert control.isVisible() and chat.rect().contains(control.geometry())


def test_focus_assistant_hides_the_side_panels_and_brings_them_back(column, qapp):
    panels, _state, _window = column
    panels.resize(360, 800)
    panels.show()
    qapp.processEvents()
    header = panels.assistant.header
    assert panels.card.isVisible() and header.focus_button.text() == "open_in_full"
    header.focus_button.click()
    qapp.processEvents()
    assert not panels.card.isVisible() and header.focus_button.text() == "close_fullscreen"
    assert panels.assistant.height() == 800
    header.focus_button.click()
    qapp.processEvents()
    assert panels.card.isVisible() and header.focus_button.text() == "open_in_full"
    assert panels.card.height() == pytest.approx((800 - 12) * 0.38, abs=2)


def test_the_picker_names_the_panel_and_lists_all_of_them(ctx, column):
    panels, _state, _window = column
    assert [p.key for p in PANELS] == list(panels.panels)
    assert panels.picker.text() == "Used in decks"
    panels._open_menu()
    menu = next(m for m in QApplication.topLevelWidgets() if type(m).__name__ == "PopoverMenu" and m.isVisible())
    assert [(e[1], e[2], e[4]) for e in menu._entries if e[0] == "item"][:3] == [
        ("used", "Used in decks", "check"), ("versions", "Slide versions", ""), ("visibility", "Visibility", "")]
    assert [e[2] for e in menu._entries if e[0] == "item"][3:] == [
        "Citations", "Language", "Image descriptions", "Transcript entry", "Speaker notes"]
    menu.triggered.emit("visibility")
    menu.close()
    assert panels.picker.text() == "Visibility" and app_settings.get(ctx, SETTING) == "visibility"


def test_the_chosen_panel_is_remembered_and_only_it_is_shown(ctx, column, project):
    panels, state, window = column
    panels.set_panel("versions")
    again = SidePanels(window, state, window.actions)
    assert again.current == "versions"
    assert [key for key, p in again.panels.items() if not p.isHidden()] == ["versions"]
    app_settings.set(ctx, SETTING, "gone")
    assert SidePanels(window, state, window.actions).current == "used"        # an unknown value falls back to the first
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
    talk.clicked.emit()
    assert state.deck.name == "talk" and state.focused_slide == "abc"
    state.set_focused_slide(None)
    state.set_focused_slide("abc")
    next(r for r in rows(panels.panels["used"]) if r.findChildren(QLabel)[0].text() == "course").clicked.emit()
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
    assert "\\conditionalslide[instructor,during-course]{abc-EN-Demo}" in read(project.decks / "course.tex")
    assert [b.isChecked() for b in cells(panels.panels["visibility"])][:3] == [True, True, False]
    state.set_view("after-course")                             # the slide list shows it hidden in that view
    assert window.slide_list.tree.data_of(window.slide_list.tree.currentItem()).hidden
    cells(panels.panels["visibility"])[4].click()              # \slidestep [instructor]: also show it to During
    assert "\\slidestep{abc-EN-Demo}[instructor,during-course]{2}" in read(project.decks / "course.tex")
    assert window.slide_list.toast.isHidden() is False         # an edit like any other: with Undo


def test_a_slide_cannot_be_hidden_from_every_view_and_the_cell_snaps_back(column, project):
    panels, state, _window = column
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    before = read(project.decks / "course.tex")
    cells(panels.panels["visibility"])[3].click()              # \slidestep [instructor] -> hidden from all
    assert "at least one view" in project.errors[-1]
    assert read(project.decks / "course.tex") == before
    assert cells(panels.panels["visibility"])[3].isChecked()


def test_a_pinned_call_shows_its_state_but_cannot_be_changed(ctx, column, project):
    panels, state, _window = column
    state.set_deck(next(d for d in deck_scan.scan_decks(ctx) if d.name == "talk"))
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    panel = panels.panels["visibility"]
    pinned = cells(panel)[3:]
    assert [b.isEnabled() for b in pinned] == [False] * 3 and [b.isEnabled() for b in cells(panel)[:3]] == [True] * 3


@pytest.mark.parametrize("key", ["visibility", "versions"])
def test_the_panel_says_when_the_open_deck_does_not_use_the_slide(ctx, column, project, key):
    panels, state, _window = column
    panels.set_panel(key)
    state.set_focused_slide("xyz")
    state.set_deck(next(d for d in deck_scan.scan_decks(ctx) if d.name == "talk"))
    state.set_focused_slide("xyz")
    assert "talk does not call this slide." in texts(panels.panels[key])


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
    deck = read(project.decks / "course.tex")
    assert "\\slideversion{abc-EN-Demo}{1-0-0}" in deck
    assert "\\slidestep{abc-EN-Demo}[instructor]{2}" in deck       # a call with no pinned form stays
    assert buttons(panel, "v1.0.0 ▾")
    panel._set_pin("abc-EN-Demo", None)
    assert "\\slide{abc-EN-Demo}" in read(project.decks / "course.tex")
    assert "slideversion" not in read(project.decks / "course.tex")


def test_freezing_asks_the_centre_with_the_chosen_level(column):
    panels, state, window = column
    current = state.project.slides_dir / "abc-EN-Demo-current.tex"
    current.write_text(current.read_text(encoding="utf-8") + "% changed\n", encoding="utf-8")
    panels.set_panel("versions")
    state.set_focused_slide("abc")
    panel = panels.panels["versions"]
    assert buttons(panel, "Update version to v1.1.0")    # untracked, and changed since v1.0.0: a minor bump
    levels = panel.findChildren(SegmentedControl)[0]
    levels._buttons["patch"].click()
    buttons(panel, "Update version to v1.0.1")[0].click()
    assert window.centre.frozen == [("abc-EN-Demo", "patch")]


# -- the panels about one slide's content ------------------------------------------------------------------

CITED = ("\\begin{standardframe}{Cited}\n\t\\footnote{\\fullcite{smith2020}} \\textcite{ghost1999}\n"
         "\t\\includegraphics{media/pic.png}\n\t\\note{First note}\n\t\\note<2>{Second note}\n\\end{standardframe}\n")


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(path=tmp_path / "slides" / "cit-EN-Cited-current.tex", bib=tmp_path / "Slidemaster.bib")


@pytest.fixture
def content(project, column, paths, tmp_path, monkeypatch):
    """The slide `cit` (citations, an image, two notes), a Slidemaster.bib and an alt-text store of its own."""

    panels, state, window = column
    paths.path.write_text(CITED, encoding="utf-8")
    bib = paths.bib
    bib.write_text("@article{smith2020,\n\tauthor = {Smith, Jane},\n\ttitle = {Findings},\n\tyear = {2020},\n"
                   "\tjournaltitle = {Journal},\n}\n", encoding="utf-8")
    state.set_focused_slide("cit")
    return panels, state, window


def shown(panels, key):
    panels.set_panel(key)
    return panels.panels[key]


def test_citations_resolve_the_keys_and_mark_the_missing_ones(content, paths):
    panels, _state, window = content
    panel = shown(panels, "citations")
    lines = texts(panel)
    assert lines[:2] == ["smith2020", "Smith (2020), “Findings”, Journal"]
    assert lines[2:4] == ["ghost1999", "Not in Slidemaster.bib"]
    assert panel.meta() == "2"
    next(r for r in rows(panel) if r.findChildren(QLabel)[0].text() == "smith2020").clicked.emit()
    assert window.opened[-1] == (paths.bib, {"line": 1})
    buttons(panel, "Add to .bib…")[0].click()
    assert window.centre.references == ["ghost1999"]


def test_a_slide_without_citations_says_so(content, paths):
    panels, _state, window = content
    window.centre.buffers[paths.path] = "\\begin{standardframe}{T}\n\\end{standardframe}\n"
    panel = shown(panels, "citations")
    assert "No citations on this slide." in texts(panel)


def test_language_shows_the_translation_and_whether_it_is_outdated(ctx, content, tmp_path):
    from slidemage import slide_source

    panels, state, _window = content
    slides = tmp_path / "slides"
    (slides / "cit-EN-Cited-current.tex").write_text("%% DE translation: ciu-DE-Zitiert\n" + CITED, encoding="utf-8")
    (slides / "ciu-DE-Zitiert-current.tex").write_text(
        "%% Translation of: cit-EN-Cited\n" + CITED.replace("Cited", "Zitiert"), encoding="utf-8")
    panel = shown(panels, "language")
    lines = texts(panel)
    assert lines[:2] == ["EN", "Cited"] and "The original." in lines and "Zitiert" in lines
    assert "Translation up to date." in lines and panel.meta() == "EN · DE"
    slide_source.save_slide_source(ctx, slides / "cit-EN-Cited-current.tex", "%% DE translation: ciu-DE-Zitiert\n" + CITED,
                                   "\n")                                              # the original is saved again
    import os
    old = 1_600_000_000
    os.utime(slides / "ciu-DE-Zitiert-current.tex", (old, old))
    state.set_focused_slide("ciu")
    state.set_focused_slide("cit")
    assert "Translation outdated: the original was saved after the translation was written." in texts(panel)
    assert panel.meta() == "EN · DE outdated"
    assert buttons(panel, "Open")


def test_translate_runs_the_assistants_translate_task(content, paths):
    panels, _state, window = content
    panel = shown(panels, "language")
    assert "No translation yet" in texts(panel)
    buttons(panel, "Translate to DE")[0].click()
    assert window.translated == [True] and not hasattr(window, "started")


def test_set_language_asks_and_goes_through_slide_rename(content, monkeypatch):
    from slidemage import slide_rename

    panels, _state, window = content
    panel = shown(panels, "language")
    calls = []
    monkeypatch.setattr(slide_rename, "count_references", lambda _ctx, id_slug: 2)
    monkeypatch.setattr(slide_rename, "set_slide_language", lambda _ctx, old, lang: calls.append((old, lang)) or "cit-DE-Cited")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    panel._set_language("cit-EN-Cited", "EN")              # already English: nothing to do
    panel._set_language("cit-EN-Cited", "DE")
    assert calls == [("cit-EN-Cited", "DE")] and window.refreshed == 1
    assert any(l.startswith("Set language of cit-EN-Cited -> cit-DE-Cited") for l in window.logged)


def test_images_show_state_and_save_drafts_and_reviews_through_the_store(ctx, content, monkeypatch):
    from slidemage import alt_images

    panels, _state, window = content
    panel = shown(panels, "images")
    form = panel._forms[0]
    assert form.reference == "media/pic.png" and form.state_chip.text() == "No description"
    assert panel.meta() == "1 image"
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: window.logged.append(args[2]))
    form.review_button.click()                               # an informative image needs a long description
    assert "long description" in window.logged[-1] and not alt_images.load_store(ctx)
    form = panel._forms[0]
    form.short_edit.setPlainText("A chart")
    form.long_edit.setPlainText("A long chart description.")
    assert panel.dirty
    form.save_button.click()
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert (entry.short, entry.long, entry.used_on["cit"].reviewed) == ("A chart", "A long chart description.", "")
    assert panels.panels["images"]._forms[0].state_chip.text() == "Draft, unreviewed" and not panel.dirty
    panel._forms[0].review_button.click()
    assert panel._forms[0].state_chip.text() == "Reviewed"
    assert alt_images.load_store(ctx)["media/pic.png"].status == "reviewed"


def test_the_images_panel_refuses_review_without_a_long_description(ctx, content, monkeypatch):
    from slidemage import alt_images

    panels, _state, _window = content
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    panel = shown(panels, "images")
    form = panel._forms[0]
    form.short_edit.setPlainText("A chart")
    form.review_button.click()
    assert len(warned) == 1 and "media/pic.png" in warned[0] and "long description" in warned[0]
    assert not alt_images.load_store(ctx) and panel.dirty and panel._forms[0] is form   # nothing stored, edit kept
    form.roles.set_current(alt_images.ROLE_DECORATIVE)
    form.review_button.click()
    assert len(warned) == 1 and alt_images.load_store(ctx)["media/pic.png"].status == "reviewed"


@pytest.mark.parametrize("save", ["draft", "review", "flush"])
def test_image_save_preserves_a_field_updated_by_a_worker(ctx, content, paths, save):
    from slidemage import alt_images

    panels, _state, _window = content
    reference = "media/pic.png"
    alt_images.save_slide_image(ctx, reference, "cit", paths.path, role="informative", short="Old short",
                                long="Old long", reviewed=True)
    panel = shown(panels, "images")
    form = panel._forms[0]
    alt_images.update_store(ctx, lambda entries: setattr(entries[reference], "long", "Worker long") or True)
    form.short_edit.setPlainText("Edited short")
    if save == "flush":
        panel.flush()
    else:
        (form.review_button if save == "review" else form.save_button).click()
    entry = alt_images.load_store(ctx)[reference]
    assert (entry.short, entry.long, entry.status) == ("Edited short", "Worker long", "reviewed")
    assert bool(entry.used_on["cit"].reviewed) == (save == "review")
    assert entry.used_on["cit"].stored_hash == alt_images.slide_context_hash(paths.path)
    assert panel._forms[0].baseline == panel._forms[0].values() and not panel.dirty


def test_a_pending_image_edit_is_saved_as_a_draft_when_the_slide_is_left(ctx, content):
    from slidemage import alt_images

    panels, state, _window = content
    panel = shown(panels, "images")
    panel._forms[0].long_edit.setPlainText("Typed, never saved.")
    assert state.dirty
    state.set_focused_slide(None)
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert entry.long == "Typed, never saved." and entry.used_on["cit"].reviewed == "" and not state.dirty


def redraft_on(monkeypatch, images, provider):
    """The active route is Local with `provider` as its provider (the backends made on it are the test's fakes)."""
    from slidemage.ai import resolver
    from slidemage.ai.ai_profile import IMAGE_DESCRIPTION, Route

    monkeypatch.setattr(images, "task_route", lambda *args: Route("fake_local", IMAGE_DESCRIPTION, "fake-1"))
    monkeypatch.setattr(resolver, "provider_for", lambda _ctx, _route: provider)


def test_redraft_fills_the_fields_from_the_model_and_stores_nothing(ctx, content, monkeypatch, paths):
    from slidemage import alt_draft, alt_images
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    drafted = []
    provider = SimpleNamespace(label="qwen3 · local")
    redraft_on(monkeypatch, images, provider)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, row, entries: [(row.images[0], paths.path)])

    class FakeBackend:
        def __init__(self, _ctx, given):
            self.provider, self.label = given, given.label

        def draft(self, resolved, context):
            drafted.append((resolved, context.image))
            return alt_draft.DraftResult(short="Drafted short", long="Drafted long", model="qwen3 · local")

    monkeypatch.setattr(alt_draft, "ModelBackend", FakeBackend)
    monkeypatch.setattr(images.background, "start_detached", lambda worker, on_done: (worker.run(), on_done()))
    form = panel._forms[0]
    form.redraft_button.click()
    assert drafted[0] == (paths.path, "media/pic.png")
    form = panel._forms[0]
    assert (form.short_edit.toPlainText(), form.long_edit.toPlainText()) == ("Drafted short", "Drafted long")
    assert "Drafted by qwen3 · local" in form.note.text() and window.busy is None
    assert panel.dirty and not alt_images.load_store(ctx)


def test_redraft_is_ignored_after_switching_to_a_slide_with_the_same_image(ctx, content, monkeypatch, paths):
    from slidemage import alt_draft, alt_images
    from slidemage.ui.workspace.panels import images

    panels, state, window = content
    (paths.path.parent / "abc-EN-Demo-current.tex").write_text(CITED, encoding="utf-8")
    panel = shown(panels, "images")
    provider = SimpleNamespace(label="qwen3 · local")
    redraft_on(monkeypatch, images, provider)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, row, entries: [(row.images[0], paths.path)])
    monkeypatch.setattr(alt_draft, "ModelBackend", lambda _ctx, given: SimpleNamespace(
        provider=given, label=given.label,
        draft=lambda *args: alt_draft.DraftResult(short="Slide A short", long="Slide A long", model=given.label)))
    pending = []

    monkeypatch.setattr(images.background, "start_detached",
                        lambda worker, on_done: pending.append(lambda: (worker.run(), on_done())))
    panel._forms[0].redraft_button.click()
    assert window.busy == "drafting a description"
    state.set_focused_slide("abc")
    form = panel._forms[0]
    assert form.reference == "media/pic.png" and panel._slide[0] == "abc"
    before = form.values(), form.note.text()
    pending[0]()
    assert (form.values(), form.note.text()) == before
    assert form.redraft_button.isEnabled() and not panel.dirty
    assert window.busy is None and not alt_images.load_store(ctx)


def test_redraft_stops_when_there_is_no_model_or_it_fails(content, monkeypatch, paths):
    from slidemage import alt_draft
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, row, entries: [(row.images[0], paths.path)])
    monkeypatch.setattr(images, "task_route", lambda *args: None)                 # declined, or no model
    panel._forms[0].redraft_button.click()
    assert window.busy is None
    panel._on_drafted("cit", "media/pic.png", None, alt_draft.DraftResult(error="timed out"))
    assert "The draft failed: timed out" in panel._forms[0].note.text()
    panel._on_drafted("cit", "media/gone.png", None, alt_draft.DraftResult(short="x", long="y"))   # the slide changed meanwhile


def test_redraft_that_raises_still_ends_with_an_error_and_gives_back_its_slot(content, monkeypatch, paths):
    from slidemage import alt_draft
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    provider = SimpleNamespace(label="qwen3 · local", is_local=True)
    redraft_on(monkeypatch, images, provider)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda _ctx, row, entries: [(row.images[0], paths.path)])

    class Failing:
        def __init__(self, _ctx, given):
            self.provider, self.label = given, given.label

        def draft(self, resolved, context):
            raise ValueError("boom")

    monkeypatch.setattr(alt_draft, "ModelBackend", Failing)
    panel._forms[0].redraft_button.click()
    wait_until(lambda: window.busy is None)
    assert "The draft failed: boom" in panel._forms[0].note.text()



def test_transcript_entry_renders_student_versions_only(content):
    panels, state, _window = content
    panel = shown(panels, "transcript")
    assert any("Transcripts are made for During course and After course only" in t for t in texts(panel))
    assert panels.suffix.text() == "in Instructor"
    state.set_view("during-course")
    lines = texts(panel)
    assert "Slide cit · During course · EN" in lines and "Cited" in lines
    assert any(line.startswith("Image media/pic.png: no description") for line in lines)
    assert any("Some images have no description yet" in line for line in texts(panels))
    assert panels.suffix.text() == "in During course"


@pytest.fixture
def saved_summaries(monkeypatch):
    from slidemage import alt_images

    saved = {}
    monkeypatch.setattr(alt_images, "update_slide_notes",
                        lambda _ctx, mutate: mutate(notes := {}) and saved.update({k: v.summary for k, v in notes.items()}))
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    return saved


def test_a_pending_summary_counts_as_unsaved_until_it_is_saved(content, saved_summaries):
    panels, state, _window = content
    panel = shown(panels, "transcript")
    states = []
    state.dirty_changed.connect(states.append)
    panel._summary.setPlainText("A note.")
    assert state.dirty and panel.dirty and states == [True]
    panel._save.click()
    assert saved_summaries == {"cit": "A note."} and not state.dirty and states == [True, False]


def test_a_pending_summary_is_saved_when_the_slide_the_panel_or_the_deck_is_left(content, saved_summaries):
    panels, state, _window = content
    panel = shown(panels, "transcript")
    panel._summary.setPlainText("  First.  ")
    state.set_focused_slide("abc")
    assert saved_summaries == {"cit": "First."} and not state.dirty
    panel._summary.setPlainText("Second.")
    panels.set_panel("used")                                 # another panel is picked
    assert saved_summaries == {"cit": "First.", "abc": "Second."}
    shown(panels, "transcript")._summary.setPlainText("Third.")
    state.set_deck(None)
    assert saved_summaries["abc"] == "Third." and not state.dirty


def test_speaker_notes_are_listed_and_edited_in_the_source_buffer(content, paths):
    panels, state, window = content
    panel = shown(panels, "notes")
    assert texts(panel)[:3] == ["Note 1", "Note 2 · <2>", "New note"] and panels.suffix.text() == "instructor only"
    assert [e.toPlainText() for e in panel._edits] == ["First note", "Second note"] and panel.meta() == "2"
    panel._edits[0].setPlainText("First, revised")
    panel._edits[1].setPlainText("")
    panel._new.setPlainText("A third")
    assert panel.dirty and state.dirty
    buttons(panel, "Save notes")[0].click()
    assert read_slide_source(paths.path)[0] == CITED.replace("\n", "\n")     # the file itself is not written here
    buffer = window.centre.buffers[paths.path]
    assert "\\note{First, revised}" in buffer and "Second note" not in buffer and "\t\\note{A third}\n\\end" in buffer
    assert window.centre.saved == [True] and not state.dirty
    assert [e.toPlainText() for e in panel._edits] == ["First, revised", "A third"]


def test_pending_notes_go_to_the_buffer_unsaved_when_the_slide_is_left(content, paths):
    panels, state, window = content
    panel = shown(panels, "notes")
    panel._edits[0].setPlainText("Changed")
    state.set_focused_slide("abc")
    assert "\\note{Changed}" in window.centre.buffers[paths.path] and window.centre.saved == []
    assert not panel.dirty


def test_notes_edited_in_the_source_view_meanwhile_are_not_overwritten(content, paths):
    panels, _state, window = content
    panel = shown(panels, "notes")
    panel._edits[0].setPlainText("Changed")
    window.centre.buffers[paths.path] = CITED.replace("First note", "Edited in the Source view")
    buttons(panel, "Save notes")[0].click()
    assert "Edited in the Source view" in window.centre.buffers[paths.path]
    assert window.centre.saved == [] and any("changed in the Source view" in line for line in window.logged)


def test_a_frozen_versions_notes_are_read_only(ctx, content, project, paths):
    panels, state, _window = content
    frozen = paths.path.parent / "cit-EN-Cited-v1-0-0.tex"
    frozen.write_text(CITED, encoding="utf-8")
    (project.decks / "course.tex").write_text(
        HEAD + "\\slideversion{cit-EN-Cited}{1-0-0}\n\\end{document}\n", encoding="utf-8")
    state.set_deck(next(d for d in deck_scan.scan_decks(ctx) if d.name == "course"))
    state.set_focused_slide("cit")
    panel = shown(panels, "notes")
    assert all(e.isReadOnly() for e in panel._edits) and not buttons(panel, "Save notes")
    assert "This is a frozen version: its notes are read-only." in texts(panel)


def test_the_reference_form_can_start_from_a_missing_key(ctx, qapp, project, monkeypatch):
    from slidemage.ui.dialogs.citation import CitationDialog
    parent = QWidget()
    parent.project = ctx
    dialog = CitationDialog(parent, "ghost1999")
    dialog.author_entry.setText("Smith, Jane")
    dialog.year_entry.setText("2020")
    assert dialog.key_entry.text() == "ghost1999"                  # not replaced by the suggestion smith2020
    dialog.deleteLater()
    parent.deleteLater()


# -- the Reference / citation of an image ------------------------------------------------------------------


def test_the_images_panel_edits_the_source_like_the_full_editor(ctx, content):
    from slidemage import alt_images
    from slidemage.ui.pages import image_form

    panels, _state, _window = content
    panel = shown(panels, "images")
    form = panel._forms[0]
    field = form.source_edit.parentWidget()
    assert field.label.text() == image_form.SOURCE_SPECS["source"][1] == "Source (citation or attribution)"
    assert form.source_edit.placeholderText() == image_form.SOURCE_SPECS["source"][4]
    assert form.source_status.isHidden()                                  # no source: nothing to review
    form.source_edit.setPlainText("Photo: Smith")
    assert panel.dirty and form.source_status.chip.text() == "To review" and not form.source_status.button.isEnabled()
    form.save_button.click()                                              # saved with the description, as a draft
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert (entry.source, entry.source_de, entry.source_status) == ("Photo: Smith", "", alt_images.SOURCE_TO_REVIEW)
    form = panel._forms[0]
    assert form.source_edit.toPlainText() == "Photo: Smith" and not panel.dirty
    assert form.source_status.chip.text() == "To review" and form.source_status.button.isEnabled()
    form.source_status.button.click()                                     # stored at once, apart from Save
    assert alt_images.load_store(ctx)["media/pic.png"].source_status == alt_images.SOURCE_REVIEWED
    assert form.source_status.chip.text() == "Reviewed" and not form.source_status.button.isVisible()
    assert alt_images.load_store(ctx)["media/pic.png"].status == alt_images.STATUS_AUTO   # the description is untouched


def test_the_source_is_to_review_after_any_edit_and_saving_the_description_reviewed_does_not_confirm_it(ctx, content):
    from slidemage import alt_images

    panels, _state, _window = content
    alt_images.update_store(ctx, lambda entries: entries.update({"media/pic.png": alt_images.ImageEntry(
        image="media/pic.png", source="Own illustration", short="s", long="l")}) or True)
    panel = shown(panels, "images")
    form = panel._forms[0]
    assert form.source_status.chip.text() == "Reviewed"                   # an existing citation is not flooded
    form.source_edit.setPlainText("Own illustration, 2026")
    form.long_edit.setPlainText("A longer description.")
    form.review_button.click()                                            # the description reviewed, the source changed
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert (entry.status, entry.source_status) == ("reviewed", alt_images.SOURCE_TO_REVIEW)
    assert panel._forms[0].state_chip.text() == "Reviewed" and panel._forms[0].source_status.chip.text() == "To review"


def test_the_source_of_the_panels_language_is_shown_and_saved(ctx, content):
    from slidemage import alt_images
    from slidemage.ui.pages import image_form

    panels, state, _window = content
    alt_images.update_store(ctx, lambda entries: entries.update({"media/pic.png": alt_images.ImageEntry(
        image="media/pic.png", source="Own illustration", source_de="Eigene Grafik")}) or True)
    panel = shown(panels, "images")
    assert panel._forms[0].source_edit.toPlainText() == "Own illustration"
    state.set_language("DE")
    form = panel._forms[0]
    assert form.source_edit.toPlainText() == "Eigene Grafik"
    assert form.source_edit.parentWidget().label.text() == image_form.SOURCE_SPECS["source_de"][1]
    form.source_edit.setPlainText("Foto: Smith")
    panel.flush()                                                         # a pending edit is saved as a draft
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert (entry.source, entry.source_de, entry.source_status) == ("Own illustration", "Foto: Smith", alt_images.SOURCE_TO_REVIEW)
    assert not panel.dirty


def test_a_source_the_panel_did_not_edit_keeps_what_another_writer_stored(ctx, content):
    from slidemage import alt_images

    panels, _state, _window = content
    alt_images.update_store(ctx, lambda entries: entries.update({"media/pic.png": alt_images.ImageEntry(
        image="media/pic.png", source="Own illustration")}) or True)
    panel = shown(panels, "images")
    form = panel._forms[0]
    alt_images.save_source(ctx, "media/pic.png", source="Elsewhere")      # another view or an agent changed it
    form.short_edit.setPlainText("Edited short")
    form.save_button.click()
    entry = alt_images.load_store(ctx)["media/pic.png"]
    assert (entry.short, entry.source, entry.source_status) == ("Edited short", "Elsewhere", alt_images.SOURCE_TO_REVIEW)


# -- a panel shows the focused occurrence, resolved once per refresh (v8.39.6) -------------------------------

@pytest.fixture
def twice(project, column):
    """The deck "pins" calls abc as the current file and again as the frozen v1.0.0."""
    (project.decks / "pins.tex").write_text(
        HEAD + "\\slide{abc-EN-Demo}\n\\slide{xyz-EN-Other}\n\\slideversion{abc-EN-Demo}{1-0-0}\n\\end{document}\n",
        encoding="utf-8", newline="")
    panels, state, window = column
    state.set_deck(next(d for d in deck_scan.scan_decks(state.project) if d.name == "pins"))
    first, second = [r for r in state.outline.rows if r.call.id == "abc"]
    return panels, state, first, second


def test_a_panel_shows_the_focused_occurrence_not_the_first(twice, project):
    panels, state, first, second = twice
    slides = project.decks.parent / "slides"
    panels.set_panel("notes")
    notes = panels.panels["notes"]
    state.set_focused_slide("abc", occurrence_key=first.key)
    assert notes.slide_path() == slides / "abc-EN-Demo-current.tex" and notes._path == notes.slide_path()
    state.set_focused_slide("abc", occurrence_key=second.key)
    assert notes.slide_path() == slides / "abc-EN-Demo-v1-0-0.tex" and notes._path == notes.slide_path()
    assert notes.id_slug() == "abc-EN-Demo"
    panels.set_panel("visibility")
    assert [position for position, _call in panels.panels["visibility"].deck_calls()] == [1, 3]   # every call of the slide


def test_a_panel_resolves_its_row_once_per_refresh_and_none_while_the_outline_is_current(twice, resolutions):
    panels, state, _first, second = twice
    panels.set_panel("notes")
    state.set_focused_slide("abc", occurrence_key=second.key)
    resolutions.reset()
    panels.refresh()
    assert (resolutions.slots, resolutions.outlines, resolutions.scans) == (0, 0, 0)
    state.drop_outline()                      # a slide file was written, the list has not rebuilt yet
    panels.refresh()
    assert (resolutions.slots, resolutions.outlines, resolutions.scans) == (1, 0, 1)
    assert panels.panels["notes"]._path.name == "abc-EN-Demo-v1-0-0.tex"


def test_used_in_decks_still_opens_another_deck_at_the_slide_with_the_outline(twice, resolutions):
    panels, state, _first, _second = twice
    state.set_focused_slide("abc")
    panels.set_panel("used")
    course = next(r for r in rows(panels.panels["used"]) if r.findChildren(QLabel)[0].text() == "course")
    course.clicked.emit()
    assert state.deck.name == "course" and state.focused_slide == "abc" and state.current_outline() is not None
    assert state.current_outline().deck_path == state.deck.path


# -- the rebuild waits for the selection to rest (v8.39.9) ---------------------------------------------------

@pytest.fixture
def debounced(column, project):
    """The column as the window has it: a change of slide, view or language rebuilds the shown panel after a pause."""
    panels, state, window = column
    del panels._defer
    (project.decks.parent / "slides" / "new-EN-Fresh-current.tex").write_text(FRAME, encoding="utf-8")
    builds = []
    real = UsedInDecks.build
    UsedInDecks.build = lambda self, id_slug: (builds.append(id_slug), real(self, id_slug))[1]
    yield panels, state, window, builds
    UsedInDecks.build = real


def rested(panels):
    wait_until(lambda: not panels._rebuild.isActive())


def test_quick_focus_changes_rebuild_the_shown_panel_once_for_the_last_slide(debounced):
    panels, state, _window, builds = debounced
    for slide in ("abc", "xyz", "new"):
        state.set_focused_slide(slide)
    assert builds == [] and panels._rebuild.isActive()                   # nothing is rebuilt per row
    rested(panels)
    assert builds == ["new-EN-Fresh"] and "No deck calls this slide." in texts(panels.panels["used"])


def test_the_old_contents_stop_answering_at_once_and_the_new_ones_follow(debounced):
    panels, state, _window, builds = debounced
    panels.show()                                                        # hit-testing needs widgets on show
    state.set_focused_slide("abc")
    rested(panels)
    used = panels.panels["used"]
    talk = next(r for r in rows(used) if r.findChildren(QLabel)[0].text() == "talk")
    state.set_focused_slide("xyz")
    hit = used.childAt(talk.mapTo(used, talk.rect().center()))           # what a click there reaches
    assert hit is panels._shield and used.isEnabled()                    # covered, not greyed out
    QTest.mouseClick(hit, Qt.MouseButton.LeftButton)                     # on the row of the slide that was left
    assert state.deck.name == "course"                                   # opened no deck
    rested(panels)
    assert panels._shield.isHidden() and builds == ["abc-EN-Demo", "xyz-EN-Other"]
    assert all(r.findChildren(QLabel)[0].text() == "course" for r in rows(used))


def test_a_pending_edit_is_saved_against_the_old_slide_at_once(debounced, paths):
    panels, state, window, _builds = debounced
    paths.path.write_text(CITED, encoding="utf-8")
    state.set_focused_slide("cit")
    rested(panels)
    panels.set_panel("notes")
    notes = panels.panels["notes"]
    notes._edits[0].setPlainText("Changed")
    state.set_focused_slide("abc")
    assert "\\note{Changed}" in window.centre.buffers[paths.path] and not notes.dirty and not state.dirty
    assert notes._path == paths.path                                # the panel itself still shows the old slide
    rested(panels)
    assert notes._path.name == "abc-EN-Demo-current.tex"


def test_a_hidden_panel_and_a_hidden_card_do_no_rebuild(debounced, monkeypatch):
    panels, state, window, builds = debounced
    panels.set_panel("visibility")
    state.set_focused_slide("abc")
    rested(panels)
    assert builds == []                                                  # Used in decks is not shown
    panels.set_panel("used")
    assert builds == ["abc-EN-Demo"]                                     # choosing a panel rebuilds at once
    panels.assistant.header.toggle_focus()                               # Focus assistant: the panels' card is hidden
    state.set_focused_slide("xyz")
    rested(panels)
    assert builds == ["abc-EN-Demo"]
    panels.assistant.header.toggle_focus()                               # ... and comes back up to date
    assert builds == ["abc-EN-Demo", "xyz-EN-Other"]


def test_a_deck_change_rebuilds_at_once(debounced):
    panels, state, _window, builds = debounced
    state.set_focused_slide("abc")
    rested(panels)
    assert "course" in texts(panels.panels["used"])
    state.set_deck(next(d for d in deck_scan.scan_decks(state.project) if d.name == "talk"))
    assert texts(panels.panels["used"]) == ["Select a slide in the list."]       # no wait for the pause
    # ... and the focus it resets right after asks for no second rebuild: no shield takes the next click
    assert panels._shield.isHidden() and not panels._rebuild.isActive()


def test_coming_back_to_the_shown_slide_before_the_pause_needs_no_rebuild(debounced):
    panels, state, _window, builds = debounced
    state.set_focused_slide("abc")
    rested(panels)
    state.set_focused_slide("xyz")
    state.set_focused_slide("abc")
    rested(panels)
    assert builds == ["abc-EN-Demo"] and panels._shield.isHidden()


# -- Used in decks: the decks the window knows, the occurrence that was clicked ---------------------------------

def test_a_focus_change_scans_no_decks_and_one_translation_scan_serves_the_query(column, monkeypatch):
    from slidemage import slide_language, slide_usage

    panels, state, window = column
    scans, folder = [], []

    class Counting(slide_language.TranslationLinks):
        def __init__(self, *args, **kwargs):
            scans.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(slide_language, "TranslationLinks", Counting)
    monkeypatch.setattr(slide_usage, "scan_decks", lambda _ctx: folder.append(1) or [])
    state.set_focused_slide("abc")
    assert folder == []                                                  # the decks are the window's, not the folder's
    scans.clear()
    panels.panels["used"].build("abc-EN-Demo")                           # the query alone: two decks, one scan
    assert scans == [1]
    assert texts(panels.panels["used"])[:2] == ["course", "\\slide, follows the current version · slide 2 of 3"]


def test_archived_decks_are_listed_from_the_decks_the_window_knows(column, project):
    panels, state, window = column
    (project.decks / "archive" / "old.tex").write_text(HEAD + "\\slide{abc-EN-Demo}\n\\end{document}\n", encoding="utf-8")
    window.decks = deck_scan.scan_decks(state.project)
    state.set_focused_slide("abc")
    assert "old (archived)" in texts(panels.panels["used"])


def test_clicking_the_second_use_of_a_slide_in_another_deck_focuses_that_occurrence(twice, project):
    panels, state, first, second = twice
    used = panels.panels["used"]
    used.app.decks = deck_scan.scan_decks(state.project)                 # the window rescans after a new deck, too
    state.set_deck(next(d for d in used.app.decks if d.name == "course"))
    state.set_focused_slide("abc")
    panels.set_panel("used")
    pins = [r for r in rows(panels.panels["used"]) if r.findChildren(QLabel)[0].text() == "pins"]
    assert len(pins) == 2
    pins[1].clicked.emit()
    assert state.deck.name == "pins" and state.focused_slide == "abc" and state.focused_occurrence == second.key
    state.set_deck(next(d for d in deck_scan.scan_decks(state.project) if d.name == "course"))
    state.set_focused_slide("abc")
    next(r for r in rows(panels.panels["used"]) if r.findChildren(QLabel)[0].text() == "pins").clicked.emit()
    assert state.focused_occurrence == first.key


# -- a pending notes edit with the Preview on show (a real window) -----------------------------------------------

@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    root = make_project(monkeypatch, tmp_path / "project")
    monkeypatch.setattr(slide_snapshot, "render_template", lambda root=None: "uni-graz")
    monkeypatch.setattr(PreviewPane, "render_after_save", lambda self: None)
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.show()
    window.state.set_mode("preview")
    window.state.set_deck(next(d for d in deck_scan.scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    window.side_panels.set_panel("notes")
    window.root = root
    return window


def click_slide(window, slide, name):
    """The slide list's click: the press focuses the row, the release opens its file (keeping the mode)."""
    window.state.set_focused_slide(slide)
    window.centre.open_file(window.root / "slides" / name, keep_mode=True)


def test_a_pending_note_is_written_to_its_slide_and_the_source_view_stays_on_the_new_one(window):
    abc, abd = (window.root / "slides" / f"{n}-current.tex" for n in ("abc-EN-Hello", "abd-EN-Second"))
    abd_before = abd.read_bytes()
    notes = window.side_panels.panels["notes"]
    notes._new.setPlainText("Panel note")
    assert window.state.dirty
    click_slide(window, "abd", "abd-EN-Second-current.tex")
    assert "\\note{Panel note}" in abc.read_text(encoding="utf-8") and abd.read_bytes() == abd_before
    centre = window.centre
    assert centre.source.file_for(abc) is None and centre.source.current is None     # no editor of the old slide
    assert not window.state.dirty and window.state.focused_slide == "abd"
    window.state.set_mode("source")
    assert centre.source.current.path == abd and "Second" in centre.source.current.editor.text()
    wait_until(lambda: not window.side_panels._rebuild.isActive())
    assert window.side_panels.panels["notes"]._path == abd


def test_a_pending_note_of_a_file_in_conflict_is_not_lost(window):
    abc = window.root / "slides" / "abc-EN-Hello-current.tex"
    window.state.set_mode("source")
    window.centre.source.current.editor.insertPlainText("typed ")
    abc.write_bytes(abc.read_bytes() + b"% elsewhere\r\n")                # a change on disk: the buffer is in conflict
    window.state.set_mode("preview")
    notes = window.side_panels.panels["notes"]
    wait_until(lambda: not window.side_panels._rebuild.isActive())
    notes._new.setPlainText("Panel note")
    click_slide(window, "abd", "abd-EN-Second-current.tex")
    file = window.centre.source.file_for(abc)
    assert file is not None and file.conflicted and "\\note{Panel note}" in file.editor.text()
    assert "Panel note" not in abc.read_text(encoding="utf-8") and window.state.dirty    # kept, and reported
