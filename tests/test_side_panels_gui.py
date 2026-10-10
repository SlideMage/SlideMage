"""The right column: the panel picker and the eight panels (Used in decks, Slide versions, Visibility,
Citations, Language, Image descriptions, Transcript entry, Speaker notes)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from slidemage import app_settings, deck_scan
from slidemage.archive import _read
from slidemage.slide_source import read_slide_source
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
    """What the panels ask of the centre column: versions, the Source view's buffers and its Save."""

    def __init__(self):
        self.restored, self.frozen, self.saved, self.references = [], [], [], []
        self.buffers: dict = {}
        self.unsaved: set = set()
        self.source = SimpleNamespace(save=lambda: self.saved.append(True) or True, add_reference=self.references.append)

    def slide_text(self, path):
        return self.buffers[path] if path in self.buffers else read_slide_source(path)[0]

    def is_dirty(self, path):
        return path in self.unsaved

    def edit_slide_text(self, path, change):
        self.buffers[path] = change(self.slide_text(path))
        return True

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
        self.busy = None

    def try_start_ollama_task(self, label, provider=None):
        self.busy = label
        return True

    def end_ollama_task(self, provider=None):
        self.busy = None

    def refresh_open_deck_editors(self):
        self.refreshed = getattr(self, "refreshed", 0) + 1

    def after_deck_edit(self, path, summary, previous_text=None):
        self.state.set_deck(next(d for d in deck_scan.scan_decks() if d.path == path))
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
    assert [(e[1], e[2], e[4]) for e in menu._entries if e[0] == "item"][:3] == [
        ("used", "Used in decks", "check"), ("versions", "Slide versions", ""), ("visibility", "Visibility", "")]
    assert [e[2] for e in menu._entries if e[0] == "item"][3:] == [
        "Citations", "Language", "Image descriptions", "Transcript entry", "Speaker notes"]
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


# -- the panels about one slide's content ------------------------------------------------------------------

CITED = ("\\begin{standardframe}{Cited}\n\t\\footnote{\\fullcite{smith2020}} \\textcite{ghost1999}\n"
         "\t\\includegraphics{media/pic.png}\n\t\\note{First note}\n\t\\note<2>{Second note}\n\\end{standardframe}\n")


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(path=tmp_path / "slides" / "cit-EN-Cited-current.tex", bib=tmp_path / "Slidemaster.bib")


@pytest.fixture
def content(project, column, paths, tmp_path, monkeypatch):
    """The slide `cit` (citations, an image, two notes), a Slidemaster.bib and an alt-text store of its own."""
    from slidemage import alt_images, bibliography

    panels, state, window = column
    paths.path.write_text(CITED, encoding="utf-8")
    bib = paths.bib
    bib.write_text("@article{smith2020,\n\tauthor = {Smith, Jane},\n\ttitle = {Findings},\n\tyear = {2020},\n"
                   "\tjournaltitle = {Journal},\n}\n", encoding="utf-8")
    monkeypatch.setattr(bibliography, "DEFAULT_BIB", bib)
    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")
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
    assert next(l for l in panel.findChildren(QLabel) if l.text() == "Not in Slidemaster.bib").objectName() == "kitPanelMissing"
    next(r for r in rows(panel) if r.findChildren(QLabel)[0].text() == "smith2020").clicked.emit()
    assert window.opened[-1] == (paths.bib, {"line": 1})
    buttons(panel, "Add to .bib…")[0].click()
    assert window.centre.references == ["ghost1999"]


def test_a_slide_without_citations_says_so(content, paths):
    panels, _state, window = content
    window.centre.buffers[paths.path] = "\\begin{standardframe}{T}\n\\end{standardframe}\n"
    panel = shown(panels, "citations")
    assert "No citations on this slide." in texts(panel)


def test_language_shows_the_translation_and_whether_it_is_outdated(content, tmp_path):
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
    slide_source.save_slide_source(slides / "cit-EN-Cited-current.tex", "%% DE translation: ciu-DE-Zitiert\n" + CITED,
                                   "\n")                                              # the original is saved again
    import os
    old = 1_600_000_000
    os.utime(slides / "ciu-DE-Zitiert-current.tex", (old, old))
    state.set_focused_slide("ciu")
    state.set_focused_slide("cit")
    assert "Translation outdated: the original was saved after the translation was written." in texts(panel)
    assert panel.meta() == "EN · DE outdated"
    assert buttons(panel, "Open")


def test_translate_opens_the_add_slide_sheet_on_a_translation(content, paths):
    panels, _state, window = content
    panel = shown(panels, "language")
    assert "No translation yet" in texts(panel)
    buttons(panel, "Translate to DE…")[0].click()
    assert window.started == [{"where": "at the end of the deck", "source": "translate", "slide": "cit-EN-Cited",
                               "target": "DE"}]


def test_set_language_asks_and_goes_through_slide_rename(content, monkeypatch):
    from slidemage import slide_rename

    panels, _state, window = content
    panel = shown(panels, "language")
    calls = []
    monkeypatch.setattr(slide_rename, "count_references", lambda id_slug: 2)
    monkeypatch.setattr(slide_rename, "set_slide_language", lambda old, lang: calls.append((old, lang)) or "cit-DE-Cited")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    panel._set_language("cit-EN-Cited", "EN")              # already English: nothing to do
    panel._set_language("cit-EN-Cited", "DE")
    assert calls == [("cit-EN-Cited", "DE")] and window.refreshed == 1
    assert any(l.startswith("Set language of cit-EN-Cited -> cit-DE-Cited") for l in window.logged)


def test_images_show_state_and_save_drafts_and_reviews_through_the_store(content, monkeypatch):
    from slidemage import alt_images

    panels, _state, window = content
    panel = shown(panels, "images")
    form = panel._forms[0]
    assert form.reference == "media/pic.png" and form.state_chip.text() == "No description"
    assert panel.meta() == "1 image"
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: window.logged.append(args[2]))
    form.review_button.click()                               # an informative image needs a long description
    assert "long description" in window.logged[-1] and not alt_images.load_store()
    form = panel._forms[0]
    form.short_edit.setPlainText("A chart")
    form.long_edit.setPlainText("A long chart description.")
    assert panel.dirty
    form.save_button.click()
    entry = alt_images.load_store()["media/pic.png"]
    assert (entry.short, entry.long, entry.used_on["cit"].reviewed) == ("A chart", "A long chart description.", "")
    assert panels.panels["images"]._forms[0].state_chip.text() == "Draft, unreviewed" and not panel.dirty
    panel._forms[0].review_button.click()
    assert panel._forms[0].state_chip.text() == "Reviewed"
    assert alt_images.load_store()["media/pic.png"].status == "reviewed"


def test_a_pending_image_edit_is_saved_as_a_draft_when_the_slide_is_left(content):
    from slidemage import alt_images

    panels, state, _window = content
    panel = shown(panels, "images")
    panel._forms[0].long_edit.setPlainText("Typed, never saved.")
    assert state.dirty
    state.set_focused_slide(None)
    entry = alt_images.load_store()["media/pic.png"]
    assert entry.long == "Typed, never saved." and entry.used_on["cit"].reviewed == "" and not state.dirty


def test_redraft_fills_the_fields_from_the_model_and_stores_nothing(content, monkeypatch, paths):
    from slidemage import alt_draft, alt_images
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    drafted = []
    provider = SimpleNamespace(label="qwen3 · local")
    monkeypatch.setattr(images, "provider_for_task", lambda parent, task, what: drafted.append((task, what)) or provider)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda row, entries: [(row.images[0], paths.path)])

    class FakeBackend:
        def __init__(self, given):
            self.given = given

        def draft(self, resolved, context):
            drafted.append((resolved, context.image))
            return alt_draft.DraftResult(short="Drafted short", long="Drafted long", model="qwen3 · local")

    class Now:
        def __init__(self, target, args, daemon):
            self.run = lambda: target(*args)

        def start(self):
            self.run()

    monkeypatch.setattr(alt_draft, "ModelBackend", FakeBackend)
    monkeypatch.setattr(images.threading, "Thread", Now)
    form = panel._forms[0]
    form.redraft_button.click()
    assert drafted[0][0] == "image_description" and drafted[1] == (paths.path, "media/pic.png")
    form = panel._forms[0]
    assert (form.short_edit.toPlainText(), form.long_edit.toPlainText()) == ("Drafted short", "Drafted long")
    assert "Drafted by qwen3 · local" in form.note.text() and window.busy is None
    assert panel.dirty and not alt_images.load_store()


def test_redraft_stops_when_there_is_no_model_or_it_fails(content, monkeypatch, paths):
    from slidemage import alt_draft
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    monkeypatch.setattr(alt_draft, "draftable_images", lambda row, entries: [(row.images[0], paths.path)])
    monkeypatch.setattr(images, "provider_for_task", lambda *args: None)           # declined, or no model
    panel._forms[0].redraft_button.click()
    assert window.busy is None
    panel._on_drafted("media/pic.png", None, alt_draft.DraftResult(error="timed out"))
    assert "The draft failed: timed out" in panel._forms[0].note.text()
    panel._on_drafted("media/gone.png", None, alt_draft.DraftResult(short="x", long="y"))   # the slide changed meanwhile


def test_redraft_that_raises_still_ends_with_an_error_and_gives_back_its_slot(content, monkeypatch, paths):
    from slidemage import alt_draft
    from slidemage.ui.workspace.panels import images

    panels, _state, window = content
    panel = shown(panels, "images")
    provider = SimpleNamespace(label="qwen3 · local")
    monkeypatch.setattr(images, "provider_for_task", lambda *args: provider)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda row, entries: [(row.images[0], paths.path)])

    class Failing:
        def __init__(self, given):
            pass

        def draft(self, resolved, context):
            raise ValueError("boom")

    class Now:
        def __init__(self, target, args, daemon):
            self.run = lambda: target(*args)

        def start(self):
            self.run()

    ended = []
    monkeypatch.setattr(window, "end_ollama_task", ended.append)
    monkeypatch.setattr(alt_draft, "ModelBackend", Failing)
    monkeypatch.setattr(images.threading, "Thread", Now)
    panel._forms[0].redraft_button.click()
    assert ended == [provider] and "The draft failed: boom" in panel._forms[0].note.text()


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
                        lambda mutate: mutate(notes := {}) and saved.update({k: v.summary for k, v in notes.items()}))
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
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


def test_a_frozen_versions_notes_are_read_only(content, project, paths):
    panels, state, _window = content
    frozen = paths.path.parent / "cit-EN-Cited-v1-0-0.tex"
    frozen.write_text(CITED, encoding="utf-8")
    (project.decks / "course.tex").write_text(
        HEAD + "\\slideversion{cit-EN-Cited}{1-0-0}\n\\end{document}\n", encoding="utf-8")
    state.set_deck(next(d for d in deck_scan.scan_decks() if d.name == "course"))
    state.set_focused_slide("cit")
    panel = shown(panels, "notes")
    assert all(e.isReadOnly() for e in panel._edits) and not buttons(panel, "Save notes")
    assert "This is a frozen version: its notes are read-only." in texts(panel)


def test_side_panels_can_take_more_than_the_first_three_panels():
    assert [p.key for p in PANELS] == ["used", "versions", "visibility", "citations", "language", "images",
                                       "transcript", "notes"]


def test_the_reference_form_can_start_from_a_missing_key(qapp, project, monkeypatch):
    from slidemage.ai.providers import OllamaProvider
    from slidemage.ui.dialogs.citation import CitationDialog

    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: ["qwen3"])
    parent = QWidget()
    dialog = CitationDialog(parent, "ghost1999")
    dialog.author_entry.setText("Smith, Jane")
    dialog.year_entry.setText("2020")
    assert dialog.key_entry.text() == "ghost1999"                  # not replaced by the suggestion smith2020
    dialog.deleteLater()
    parent.deleteLater()
