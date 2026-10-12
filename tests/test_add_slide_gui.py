"""The Add slide sheet: each source, the ways of loading a slide, the presets the other parts of the
window start it with, its checks, and a translation that runs while the sheet is open. No LaTeX and no
model: the files are a throwaway project's and the provider is a fake."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QWidget

from slidemage.project import ProjectContext
from slidemage import deck_editor, deck_scan, slide_add
from slidemage.ai.providers import Cancelled, ChatReply, OllamaProvider
from slidemage.ui.dialogs import add_slide
from slidemage.ui.dialogs.add_slide import AddSlideSheet

from conftest import use_new_slide_files, wait_until

FRAME = "\\begin{standardframe}{%s}\r\nText\r\n\\end{standardframe}\r\n"
HEAD = "\\documentclass{beamer}\n\\begin{document}\n"


class FakeWindow(QWidget):
    """What the sheet asks of the main window."""

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.dirty: set = set()
        self.edits, self.opened, self.slots = [], [], []
        self.centre = SimpleNamespace(is_dirty=lambda path: path in self.dirty)

    def after_deck_edit(self, path, summary, previous_text=None):
        self.edits.append((path, summary, previous_text))

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)

    def try_start_ollama_task(self, label, provider=None):
        self.slots.append(("start", label))
        return True

    def end_ollama_task(self, provider=None):
        self.slots.append(("end",))


class Translator:
    """A model that translates "Text" at once, or only when `release` is set."""

    is_local = True
    model = "fake"
    label = "fake"

    def __init__(self, reply="Text auf Deutsch", hold=None):
        self.reply, self.hold, self.aborted = reply, hold, threading.Event()

    def chat(self, messages, **kwargs):
        if self.hold is not None:
            self.hold.set()
            if self.aborted.wait(5):
                raise Cancelled("Aborted.")
        if isinstance(self.reply, Exception):
            raise self.reply
        return ChatReply(text=self.reply)

    def abort(self):
        self.aborted.set()


@pytest.fixture
def project(tmp_path, monkeypatch, qapp):
    """A deck with two slides, a project with four, one of them frozen and one German."""
    decks, slides = tmp_path / "decks", tmp_path / "slides"
    (decks / "archive").mkdir(parents=True)
    use_new_slide_files(monkeypatch, tmp_path)
    for name, title in (("abc-EN-Demo", "Demo"), ("xyz-EN-Other", "Other"), ("ccc-DE-Drei", "Dritte")):
        (slides / f"{name}-current.tex").write_bytes((FRAME % title).encode("utf-8"))
    (slides / "abc-EN-Demo-v1-0-0.tex").write_bytes((FRAME % "Old").encode("utf-8"))
    (decks / "course.tex").write_bytes(
        (HEAD + "\\slide{xyz-EN-Other}\n\\slide{abc-EN-Demo}\n\\end{document}\n").encode("utf-8"))
    monkeypatch.setattr(OllamaProvider, "list_models", lambda self, vision_only=False: ["qwen3"])
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: project.errors.append(args[2]))
    project.errors = []
    project.slides, project.deck_path = slides, decks / "course.tex"
    return project


@pytest.fixture
def make(project, qapp):
    keep = []

    def make(**start):
        window = FakeWindow(ProjectContext.at(project.slides.parent))
        deck = next(d for d in deck_scan.scan_decks(window.project) if d.name == "course")
        insert_at, indent = deck_editor.append_position(deck)
        sheet = AddSlideSheet(window, deck, insert_at, indent, where="at the end of the deck", is_dirty=window.centre.is_dirty, **start)
        keep.append((window, sheet))
        sheet.show()
        return sheet, window

    yield make
    for window, sheet in keep:
        sheet.close()
        window.deleteLater()
        sheet.deleteLater()
    QCoreApplication.sendPostedEvents(None, 0)


def deck_text(project):
    return project.deck_path.read_bytes().decode("utf-8")


def pick(sheet, id_slug):
    sheet.search.setText("")
    sheet._select(id_slug)
    assert sheet.picked() == id_slug


def use_provider(monkeypatch, provider):
    asked = []
    monkeypatch.setattr(add_slide, "provider_from_combo", lambda parent, project, combo, what: asked.append(what) or provider)
    return asked


# -- New ---------------------------------------------------------------------------------------

def test_a_new_slide_takes_its_slug_from_the_title_and_goes_into_the_deck(make, project):
    sheet, window = make()
    assert sheet.current_source() == "new" and sheet.picker.isHidden() and not sheet.new.isHidden()
    assert not sheet.ok.isEnabled() and sheet.status.text() == "Give the slide a title or a slug."
    QTest.keyClicks(sheet.title_edit, "Growth of R&D")
    assert sheet.slug_edit.text() == "Growth-of-R-D" and sheet.ok.isEnabled()
    sheet.frames._on_click("quoteframe")
    sheet.language.set_current("DE")
    sheet._sync()
    assert sheet.call_preview.text() == "\\slide{the new slide}"
    sheet.ok.click()
    created = next(p for p in project.slides.glob("*-DE-Growth-of-R-D-current.tex"))
    assert "\\quoteframe{" in created.read_text() and f"\\slide{{{created.name[:-len('-current.tex')]}}}" in deck_text(project)
    assert window.opened == [created] and window.edits[0][1].startswith("Added \\slide{")
    assert window.edits[0][2] == HEAD + "\\slide{xyz-EN-Other}\n\\slide{abc-EN-Demo}\n\\end{document}\n"
    assert sheet.result() == sheet.DialogCode.Accepted


def test_a_slug_you_typed_is_not_overwritten_and_must_be_valid(make, project):
    sheet, window = make()
    QTest.keyClicks(sheet.slug_edit, "my slug")
    QTest.keyClicks(sheet.title_edit, "Something else")
    assert sheet.slug_edit.text() == "my slug" and not sheet.ok.isEnabled()
    assert "letters and digits" in sheet.status.text()
    sheet.ok.click()
    assert list(project.slides.glob("*my*")) == [] and window.edits == []


def test_the_gallery_lists_the_frames_and_warns_about_pictures(make):
    sheet, _window = make()
    assert sheet.frames.current() == "standardframe" and sheet.frame_note.isHidden()
    sheet.frames._on_click("sideimageframe")
    sheet._sync()
    assert not sheet.frame_note.isHidden() and "picture" in sheet.frame_note.text()
    assert list(sheet.frames._tiles) == list(slide_add.FRAMES)


# -- Existing ----------------------------------------------------------------------------------

def test_an_existing_slide_is_found_by_id_or_title_and_added_live(make, project):
    sheet, window = make(source="existing")
    assert sheet.picker.label.text() == "Slide" and sheet.listbox.count() == 3 and not sheet.ok.isEnabled()
    sheet.search.setText("dritt")
    assert sheet.listbox.count() == 1
    sheet.search.setText("XYZ")
    assert [sheet.listbox.item(i).data(Qt.ItemDataRole.UserRole) for i in range(sheet.listbox.count())] == ["xyz-EN-Other"]
    sheet.listbox.setCurrentRow(0)
    assert sheet.ok.isEnabled() and sheet.call_preview.text() == "\\slide{xyz-EN-Other}"
    sheet.ok.click()
    assert deck_text(project).endswith("\\slide{abc-EN-Demo}\n\\slide{xyz-EN-Other}\n\\end{document}\n")
    assert window.opened == [] and window.edits[0][1] == "Added \\slide{xyz-EN-Other} to course"


def test_a_frozen_version_is_added_pinned_and_has_no_views_to_choose(make, project):
    sheet, _window = make(source="existing")
    pick(sheet, "abc-EN-Demo")
    sheet.load.set_current("frozen")
    sheet._sync()
    assert not sheet.version_field.isHidden() and sheet.version.currentData() == "1-0-0"
    assert all(not box.isEnabled() for box in sheet.views.values())
    assert sheet.call_preview.text() == "\\slideversion{abc-EN-Demo}{1-0-0}"
    sheet.ok.click()
    assert "\\slideversion{abc-EN-Demo}{1-0-0}\n\\end{document}" in deck_text(project)
    other, _ = make(source="existing")
    pick(other, "xyz-EN-Other")
    other.load.set_current("frozen")
    other._sync()
    assert other.status.text() == "This slide has no frozen version." and not other.ok.isEnabled()


def test_one_reveal_step_is_added_as_a_slidestep(make, project):
    sheet, _window = make(source="existing")
    pick(sheet, "abc-EN-Demo")
    sheet.load.set_current("step")
    sheet.steps.setText("1-2,4")
    assert not sheet.steps_field.isHidden()
    assert sheet.call_preview.text() == "\\slidestep{abc-EN-Demo}[instructor,during-course,after-course]{1-2,4}"
    sheet.steps.setText("two")
    assert not sheet.ok.isEnabled() and "not a valid step list" in sheet.status.text()
    sheet.steps.setText("2")
    sheet.ok.click()
    assert "\\slidestep{abc-EN-Demo}[instructor,during-course,after-course]{2}\n" in deck_text(project)


def test_unticking_a_view_makes_a_conditional_slide_and_one_view_is_needed(make, project):
    sheet, _window = make(source="existing")
    pick(sheet, "abc-EN-Demo")
    sheet.views["during-course"].setChecked(False)
    assert sheet.call_preview.text() == "\\conditionalslide[instructor,after-course]{abc-EN-Demo}"
    sheet.views["instructor"].setChecked(False)
    sheet.views["after-course"].setChecked(False)
    assert not sheet.ok.isEnabled() and "at least one" in sheet.status.text()
    sheet.views["after-course"].setChecked(True)
    sheet.ok.click()
    assert "\\conditionalslide[after-course]{abc-EN-Demo}" in deck_text(project)


# -- Duplicate and Translate -------------------------------------------------------------------

@pytest.mark.parametrize("preset, id_slug, title", [
    ("abc-EN-Demo", "abc-EN-Demo", "Demo"),
    (None, "ccc-DE-Drei", "Dritte"),
])
def test_duplicate_adds_an_independent_copy(make, project, preset, id_slug, title):
    sheet, window = make(source="duplicate", slide=preset)
    assert sheet.picker.label.text() == "Slide to duplicate" and sheet.picked() == preset
    assert sheet.translation.isHidden()
    if preset is None:
        assert not sheet.ok.isEnabled()
        pick(sheet, id_slug)
    language, slug = id_slug.split("-", 2)[1:]
    assert sheet.copy_slug.text() == f"{slug}-Copy"
    sheet.ok.click()
    created = next(project.slides.glob(f"*-{language}-{slug}-Copy-current.tex"))
    assert created.read_bytes().decode().endswith(FRAME % title) and "Translation of" not in created.read_text()
    assert "translation" not in (project.slides / f"{id_slug}-current.tex").read_text()
    assert window.opened == [created] and created.name[:3] in deck_text(project)


def test_a_copy_needs_the_saved_file_and_a_good_slug(make, project):
    sheet, window = make(source="duplicate", slide="abc-EN-Demo")
    window.dirty.add(project.slides / "abc-EN-Demo-current.tex")
    sheet._sync()
    assert "unsaved changes" in sheet.status.text() and not sheet.ok.isEnabled()
    window.dirty.clear()
    sheet.copy_slug.setText("two words")
    sheet._sync()
    assert "letters and digits" in sheet.status.text() and not sheet.ok.isEnabled()


def test_translate_into_german_runs_the_model_and_links_the_translation(make, project, monkeypatch):
    asked = use_provider(monkeypatch, Translator())
    sheet, window = make(source="translate", slide="abc-EN-Demo", target="DE")
    assert sheet.chosen_target() == "DE" and sheet.copy_slug.text() == "Demo"
    assert sheet.machine.isEnabled() and sheet.machine.isChecked() and not sheet.machine_box.isHidden()
    sheet.ok.click()
    assert sheet._worker is not None and not sheet.ok.isEnabled() and "Translating with fake" in sheet.status.text()
    wait_until(lambda: sheet._worker is None)
    created = next(project.slides.glob("*-DE-Demo-current.tex"))
    text = created.read_bytes().decode()
    assert "%% Translation of: abc-EN-Demo" in text and text.endswith("Text auf Deutsch")
    assert f"%% DE translation: {created.name[:-len('-current.tex')]}" in (project.slides / "abc-EN-Demo-current.tex").read_text()
    assert window.slots == [("start", "translating a slide"), ("end",)] and asked == ["the slide's LaTeX body"]
    assert window.opened == [created] and created.name[:3] in deck_text(project)


def test_a_failed_translation_is_shown_and_nothing_is_made(make, project, monkeypatch):
    from slidemage.ai.providers import ProviderError

    use_provider(monkeypatch, Translator(ProviderError("rate limited")))
    sheet, window = make(source="translate", slide="abc-EN-Demo", target="DE")
    before = sorted(project.slides.iterdir())
    sheet.ok.click()
    wait_until(lambda: sheet._worker is None)
    assert "Translation failed: rate limited" in sheet.status.text() and sheet.ok.isEnabled()
    assert sorted(project.slides.iterdir()) == before and window.edits == [] and window.slots[-1] == ("end",)
    sheet.machine.setChecked(False)
    sheet.ok.click()
    created = next(project.slides.glob("*-DE-Demo-current.tex"))
    assert created.read_bytes().decode().endswith(FRAME % "Demo")      # the copy as it is, still linked
    assert "Translation of: abc-EN-Demo" in created.read_text()


def test_declining_the_cloud_or_having_no_model_starts_nothing(make, project, monkeypatch):
    use_provider(monkeypatch, None)
    sheet, window = make(source="translate", slide="abc-EN-Demo", target="DE")
    sheet.ok.click()
    assert sheet._worker is None and window.slots == [] and window.edits == [] and sheet.ok.isEnabled()


def test_only_english_to_german_can_be_machine_translated(make, project, monkeypatch):
    use_provider(monkeypatch, pytest.fail)
    sheet, window = make(source="translate", slide="ccc-DE-Drei")
    assert [sheet.target.itemData(i) for i in range(sheet.target.count())] == ["EN", "mult"]
    assert not sheet.machine.isEnabled() and not sheet.machine.isChecked() and sheet.machine_box.isHidden()
    sheet.ok.click()
    created = next(project.slides.glob("*-EN-Drei-current.tex"))
    assert "Translation of: ccc-DE-Drei" in created.read_text() and window.slots == []
    english, _ = make(source="translate", slide="abc-EN-Demo")
    assert english.chosen_target() == "DE" and english.machine.isEnabled()
    english.target.setCurrentIndex(1)
    assert english.chosen_target() == "mult" and not english.machine.isEnabled()


def test_closing_the_sheet_ends_a_running_translation(make, project, monkeypatch):
    started = threading.Event()
    model = Translator(hold=started)
    use_provider(monkeypatch, model)
    sheet, window = make(source="translate", slide="abc-EN-Demo", target="DE")
    sheet.ok.click()
    assert started.wait(5)
    worker = sheet._worker
    sheet.reject()
    assert model.aborted.is_set() and sheet._worker is None and worker.isFinished()
    QCoreApplication.processEvents()
    assert window.slots == [("start", "translating a slide"), ("end",)] and window.edits == []
    assert not list(project.slides.glob("*-DE-Demo-current.tex"))


# -- Cancel and failures -----------------------------------------------------------------------

def test_cancel_changes_nothing(make, project):
    sheet, window = make()
    sheet.slug_edit.setText("Wanted")
    sheet._sync()
    before = (sorted(project.slides.iterdir()), deck_text(project))
    sheet.cancel_button.click()
    assert (sorted(project.slides.iterdir()), deck_text(project)) == before and window.edits == []
    assert sheet.result() == sheet.DialogCode.Rejected


def test_a_deck_that_changed_on_disk_is_reported_and_keeps_the_sheet_open(make, project):
    sheet, window = make(source="existing")
    pick(sheet, "xyz-EN-Other")
    project.deck_path.write_bytes((HEAD + "\\end{document}\n").encode())
    sheet.ok.click()
    assert project.errors and "changed on disk" in project.errors[0] and window.edits == []
    assert sheet.result() != sheet.DialogCode.Accepted


def test_a_new_slide_that_cannot_be_written_is_reported_in_the_sheet(make, project, monkeypatch):
    sheet, window = make()
    sheet.slug_edit.setText("Fine")
    monkeypatch.setattr(slide_add.slide_ids, "create_slide_file",
                        lambda *a, **k: (_ for _ in ()).throw(FileExistsError("slides/x.tex already exists")))
    sheet.ok.click()
    assert sheet.status.text() == "slides/x.tex already exists" and window.edits == []


# -- presets ------------------------------------------------------------------------------------

def test_the_sources_show_their_own_controls(make):
    sheet, _window = make(source="existing")
    shown = lambda: (not sheet.picker.isHidden(), not sheet.existing.isHidden(), not sheet.new.isHidden(),  # noqa: E731
                     not sheet.copy.isHidden(), not sheet.translation.isHidden())
    assert shown() == (True, True, False, False, False)
    sheet.source.set_current("new")
    sheet._on_source("new")
    assert shown() == (False, False, True, False, False)
    sheet._on_source("duplicate")
    assert shown() == (True, False, False, True, False)
    sheet._on_source("translate")
    assert shown() == (True, False, False, True, True)
