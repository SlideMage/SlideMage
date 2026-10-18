"""The centre column: which view shows what for the focused slide, the Preview's
states and renders (the renderer is faked), and unsaved edits across slides."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import alt_images, preview_target, slide_snapshot
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.ui.dialogs import transcript_preview
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view, render_check
from slidemage.ui.workspace.centre import CentreColumn
from slidemage.ui.workspace.state import WorkspaceState


FRAME = "\\begin{standardframe}{%s}\nText\n\\end{standardframe}\n"
DECK = (
    "\\documentclass{beamer}\n\\input{Slidemaster_preamble_uni-ibk}\n\\begin{document}\n"
    "\\section{Part}\n\\slide{aaa-EN-One}\n\\slideversion{bbb-EN-Two}{1-0-0}\n"
    "\\conditionalslide[instructor]{ccc-DE-Drei}\n\\end{document}\n")


class FakeApp:
    """What the centre needs of the window."""

    def __init__(self, project):
        self.project = project
        self.theme = ThemeManager()
        self.logged = []

    def log(self, line):
        self.logged.append(line)

    def open_slide_editor(self, path, on_saved=None, line=None):
        self.centre.open_file(path, on_saved, line)

    def refresh_open_deck_editors(self):
        pass


@pytest.fixture
def project(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "aaa-EN-One-current.tex").write_text("\\setSlideVersion{1-1-0}\n" + FRAME % "First", encoding="utf-8")
    (slides / "bbb-EN-Two-current.tex").write_text(FRAME % "Second now", encoding="utf-8")
    (slides / "bbb-EN-Two-v1-0-0.tex").write_text("\\setSlideVersion{1-0-0}\n" + FRAME % "Second then", encoding="utf-8")
    (slides / "ccc-DE-Drei-current.tex").write_text(FRAME % "Dritte", encoding="utf-8")
    (tmp_path / ".previews" / "slide_previews").mkdir(parents=True)
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    monkeypatch.setattr(slide_snapshot, "render_template", lambda root=None: "uni-graz")
    return slides


@pytest.fixture
def deck(tmp_path):
    return Deck(name="course", path=tmp_path / "course.tex", archived=False, text=DECK, supports_version=True,
                uses_biblatex=False, preamble_end=DECK.index("\\begin{document}") + len("\\begin{document}"),
                chapters=parse_chapters(DECK), output_folders={})


@pytest.fixture
def renders(tmp_path, monkeypatch):
    """preview_target's two renderers, replaced by recorders that write a small 16:9 PDF."""
    pdf = tmp_path / "render.pdf"
    doc = pymupdf.open()
    doc.new_page(width=320, height=180)
    doc.save(pdf)
    doc.close()
    calls = []

    def fake(kind):
        def render(target, *args, **kwargs):
            calls.append((kind, target.id_slug, args, kwargs))
            if calls[-1][3].get("fail"):
                raise RuntimeError("boom")
            return pdf
        return render

    # Exercise the prepare/publish path; GUI state tests do not need full-HD rasterization.
    monkeypatch.setattr(slide_snapshot, "FULL_SIZE", (160, 90))
    monkeypatch.setattr(slide_snapshot, "THUMB_SIZE", (80, 45))
    monkeypatch.setattr(preview_target, "render", fake("saved"))
    monkeypatch.setattr(preview_target, "render_text", fake("buffer"))
    monkeypatch.setattr(preview_view.slide_preview, "open_pdf", lambda path: calls.append(("open", path)))
    return calls


@pytest.fixture
def centre(qapp, project, deck, monkeypatch, ctx):
    monkeypatch.setattr(render_check, "confirm_render", lambda *a, **k: True)
    app = FakeApp(ctx)
    state = WorkspaceState(ctx)
    centre = CentreColumn(app, state)
    centre.preview._background_validation = False  # legacy widget tests assert synchronous state
    app.centre = centre
    state.set_deck(deck)
    return centre


def wait_idle(centre):
    deadline = time.monotonic() + 5
    while (centre.preview._busy or centre.preview._selection_pending is not None) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert not centre.preview._busy


def link_german(project):
    english = project / "aaa-EN-One-current.tex"
    english.write_text("%% DE translation: ddd-DE-Eins\n" + english.read_text())
    german = project / "ddd-DE-Eins-current.tex"
    german.write_text("%% Translation of: aaa-EN-One\n\\setSlideVersion{7-0-2}\n" + FRAME % "Erste")
    return english, german


def test_language_switch_changes_editor_preview_details_and_keeps_both_buffers(centre, project):
    english, german = link_german(project)
    state = centre.state
    state.set_mode("split")
    state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("% English draft\n")
    state.set_language("DE")
    assert centre.source.current.path == german and centre.path == german
    assert centre.preview._target.id_slug == "ddd-DE-Eins"
    assert centre.preview._row.title == "Erste"
    centre.source.current.editor.insertPlainText("% Deutscher Entwurf\n")
    state.set_mode("details")
    assert centre.details._id_slug == "ddd-DE-Eins" and centre.details.current_path == german
    state.set_language("EN")
    state.set_mode("source")
    assert centre.source.current.path == english
    assert "% English draft" in centre.source.current.editor.text()
    state.set_language("DE")
    assert "% Deutscher Entwurf" in centre.source.current.editor.text()
    # Each was saved when the other language was shown.
    assert "% English draft" in english.read_text() and "% Deutscher Entwurf" in german.read_text()
    assert not centre.is_dirty(english) and not centre.is_dirty(german)


@pytest.mark.parametrize("language, id_slug, edit", [
    ("EN", "aaa-EN-One", "% saved "),
    ("DE", "ddd-DE-Eins", "% German saved edit\n"),
])
def test_saving_renders_only_the_active_language_when_the_page_is_visible(centre, project, renders, monkeypatch, language, id_slug, edit):
    english, german = link_german(project) if language == "DE" else (
        project / "aaa-EN-One-current.tex", project / "ccc-DE-Drei-current.tex")
    active, other = (english, german) if language == "EN" else (german, english)
    before = other.read_bytes()
    centre.state.set_focused_slide("aaa")
    centre.state.set_mode("split")
    centre.state.set_language(language)
    centre.source.current.editor.insertPlainText(edit)
    assert centre.source.save()
    wait_idle(centre)
    assert edit in active.read_text() and other.read_bytes() == before
    assert [c[0:2] for c in renders] == [("buffer", id_slug)] and page(centre).pixmap is not None
    centre.state.set_mode("source")  # no page to show: no render
    centre.source.current.editor.insertPlainText("% again ")
    assert centre.source.save()
    wait_idle(centre)
    assert len(renders) == 1


def page(centre):
    return centre.preview._page


def chip_texts(centre):
    layout = centre.preview._chips
    return [layout.itemAt(i).widget()._label.text() for i in range(layout.count()) if layout.itemAt(i).widget()]


def test_an_outdated_translation_shows_a_chip(centre, project, monkeypatch):
    from slidemage import slide_language

    state = centre.state
    state.set_focused_slide("bbb")
    link = slide_language.TranslationLink("bbb-DE-Zwei", "DE", project / "bbb-DE-Zwei-current.tex", False, True)
    monkeypatch.setattr(preview_view, "translation_link", lambda _ctx, id_slug: link)
    centre.preview._refresh()
    assert chip_texts(centre) == ["Deck stays on v1.0.0", "Translation outdated", "EN + DE"]
    monkeypatch.setattr(preview_view, "translation_link", lambda _ctx, id_slug: None)
    centre.preview._refresh()
    assert "Translation outdated" not in chip_texts(centre)


# -- modes and what each view shows ------------------------------------------------

def test_the_mode_decides_which_views_are_shown(centre):
    state = centre.state
    states = {}
    for mode in ("preview", "split", "source", "details"):
        state.set_mode(mode)
        states[mode] = (centre.source.isVisibleTo(centre), centre.preview.isVisibleTo(centre),
                        centre.details.isVisibleTo(centre))
    assert states == {"preview": (False, True, False), "split": (True, True, False),
                      "source": (True, False, False), "details": (False, False, True)}


def test_focusing_a_slide_shows_its_file_as_the_deck_calls_it(centre, project):
    state = centre.state
    state.set_mode("source")
    state.set_focused_slide("aaa")
    assert centre.source.current.path == project / "aaa-EN-One-current.tex"
    state.set_focused_slide("bbb")                    # the deck pins v1.0.0: that is the file it typesets
    assert centre.source.current.path == project / "bbb-EN-Two-v1-0-0.tex"
    assert centre.source.current.editor.is_read_only()
    state.set_focused_slide(None)
    assert centre.source.current is None


def test_edits_are_saved_when_another_slide_is_focused(centre, project):
    state = centre.state
    dirty = []
    state.dirty_changed.connect(dirty.append)
    state.set_mode("source")
    state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("edit ")
    assert dirty == [] and not state.dirty            # saved as you type: a pending autosave is not an unsaved edit
    state.set_focused_slide("ccc")
    assert dirty == [] and not state.dirty
    assert "edit " in (project / "aaa-EN-One-current.tex").read_text()
    state.set_focused_slide("aaa")
    assert "edit " in centre.source.current.editor.text() and not centre.source.current.dirty


def test_opening_a_file_switches_to_source_and_a_slide_of_the_project_is_focused(centre, project):
    seen = []
    centre.open_file(project / "ccc-DE-Drei-current.tex", seen.append, line=2)
    assert centre.state.mode == "source" and centre.state.focused_slide == "ccc"
    assert centre.source.current.on_saved == seen.append
    assert centre.source.current.editor.textCursor().blockNumber() == 1
    centre.state.set_mode("split")
    centre.open_file(project / "aaa-EN-One-current.tex")
    assert centre.state.mode == "split"               # Split stays Split


def test_a_deck_source_has_nothing_to_preview_and_ends_when_another_slide_is_focused(centre, deck, project):
    deck.path.write_text(DECK, encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    centre.open_file(deck.path)
    centre.state.set_mode("split")
    assert centre.source.current.path == deck.path and not centre.source.current.is_slide
    assert "not a slide" in page(centre).message
    centre.state.set_focused_slide("ccc")
    assert centre.source.current.path == project / "ccc-DE-Drei-current.tex"


def test_a_frozen_version_opened_by_itself_is_previewed_alone(centre, project):
    centre.open_file(project / "bbb-EN-Two-v1-0-0.tex")
    centre.state.set_mode("split")
    assert centre.preview._target.macro == "slideversion" and centre.preview._row.call.version == "1-0-0"
    centre.open_file(project / "bbb-EN-Two-current.tex")       # not what the deck pins: shown alone
    assert centre.preview._row is None and "Frozen" not in " ".join(chip_texts(centre))
    centre.open_file(project / "bbb-EN-Two-v1-0-0.tex")
    assert chip_texts(centre)[0] == "Deck stays on v1.0.0"


def test_a_file_that_is_renamed_meanwhile_is_forgotten(centre, project):
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    (project / "aaa-EN-One-current.tex").rename(project / "aaa-EN-Uno-current.tex")
    centre.refresh()
    assert centre.source.current is None


# -- the preview ----------------------------------------------------------------------

def test_the_chips_say_what_the_page_is_not_showing(centre):
    state = centre.state
    state.set_focused_slide("bbb")
    assert chip_texts(centre) == ["Deck stays on v1.0.0", "EN"]
    state.set_focused_slide("ccc")
    assert chip_texts(centre) == ["No EN version", "DE"]       # a German slide while editing English
    state.set_language("DE")
    assert chip_texts(centre) == ["DE"]
    state.set_view("during-course")
    assert chip_texts(centre) == ["Hidden in During course", "DE"]


def test_a_slide_the_view_does_not_typeset_says_so_and_does_not_offer_to_render(centre, renders):
    centre.state.set_view("after-course")
    centre.state.set_focused_slide("ccc")
    assert "not typeset in the After course view" in page(centre).message
    assert not page(centre).render_button.isVisibleTo(centre) and renders == []


def test_without_a_picture_the_page_offers_to_render_and_a_render_shows_the_result(centre, renders, monkeypatch):
    # This checks the view/language-specific session cache, independently of
    # the canonical instructor snapshot the accepted render also publishes.
    monkeypatch.setattr(preview_view, 'legacy_reference', lambda *args: None)
    state = centre.state
    state.set_focused_slide("aaa")
    assert "No preview" in page(centre).message and not page(centre).render_button.isHidden()
    page(centre).render_button.click()
    assert centre.preview._busy
    wait_idle(centre)
    kind, id_slug, args, kwargs = renders[0]
    assert (kind, id_slug, args[1:3]) == ("buffer", "aaa-EN-One", ("instructor", "EN"))
    assert kwargs["footer_timestamp"] is False
    assert page(centre).pixmap is not None
    assert page(centre).render_button.isHidden()
    assert 'Previous render' in centre.preview._status_chip.text()  # fake PDF has no recorder evidence
    state.set_footer_timestamp(True)
    centre.preview.render_now()
    wait_idle(centre)
    assert [c[3]["footer_timestamp"] for c in renders] == [False, True]
    state.set_view("during-course")                         # another view has no picture yet
    assert page(centre).pixmap is None and "During course" in page(centre).message
    state.set_view("instructor")
    assert page(centre).pixmap is not None                  # the first one is remembered
    state.set_language("DE")
    assert page(centre).pixmap is None


def test_a_picture_older_than_the_source_is_marked_and_a_render_makes_it_current(centre, renders, project):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_idle(centre)
    source = project / "aaa-EN-One-current.tex"
    source.write_text(source.read_text().replace('Text', 'Edited text'))
    centre.refresh()
    wait_idle(centre)
    assert page(centre).pixmap is not None
    assert 'Previous render' in centre.preview._status_chip.text()
    assert centre.preview._status_button.isVisibleTo(centre)
    centre.preview._status_button.click()
    wait_idle(centre)
    assert 'Previous render' in centre.preview._status_chip.text() and len(renders) == 2


def test_the_cached_snapshot_is_shown_for_the_instructor_view(ctx, centre, project, tmp_path):
    centre.state.set_focused_slide("aaa")
    template = centre.preview._target.template
    png = slide_snapshot.snapshot_path(ctx, "aaa", template, slide_snapshot.FULL_SIZE)
    doc = pymupdf.open()
    page_ = doc.new_page(width=320, height=180)
    png.write_bytes(page_.get_pixmap().tobytes("png"))
    doc.close()
    os.utime(png, (1, (project / "aaa-EN-One-current.tex").stat().st_mtime + 10))
    centre.refresh()
    assert page(centre).pixmap is not None
    assert 'Shared Instructor reference' in centre.preview._status_chip.text()
    centre.state.set_view("after-course")
    assert page(centre).pixmap is not None
    assert 'Instructor reference' in centre.preview._status_chip.text()


def test_a_failed_render_is_reported_and_can_be_repeated(centre, renders, monkeypatch):
    centre.state.set_focused_slide("aaa")
    original = preview_target.render_text
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom: no PDF")))
    centre.preview.render_now()
    wait_idle(centre)
    assert centre.preview._status_chip.text() == "Render failed" and "boom" in centre.preview._error_label.text()
    centre.state.set_view("during-course")                  # the failure belongs to the view it happened in
    assert not centre.preview._error
    centre.state.set_view("instructor")
    monkeypatch.setattr(preview_target, "render_text", original)
    centre.preview.render_now()
    wait_idle(centre)
    assert not centre.preview._error and page(centre).pixmap is not None


@pytest.mark.parametrize("button", ["page", "status", "footer"])
def test_the_syntax_check_can_stop_a_render_whichever_button_starts_it(centre, renders, monkeypatch, button):
    centre.state.set_focused_slide("aaa")
    asked = []
    monkeypatch.setattr(render_check, "confirm_render", lambda *args, **kw: asked.append(args[3]) or False)
    preview = centre.preview
    if button == "status":                          # shown for a picture older than its source
        preview._status_button.setVisible(True)
    {"page": page(centre).render_button, "status": preview._status_button,
     "footer": preview._render._main}[button].click()
    assert asked == ["aaa-EN-One-current.tex (saved file)"] and renders == [] and not preview._busy


def test_the_render_menu_offers_scope_reveal_step_presenter_transcript_and_the_last_pdf(centre, renders):
    centre.state.set_focused_slide("aaa")
    entries = {e[1]: e for e in centre.preview._menu._entries if e[0] == "item"}
    assert entries["scope:slide"][4] == "check" and entries["scope:region"][4] == ""
    assert not entries["open_pdf"][6]                        # nothing rendered yet
    centre.preview._on_menu("scope:element")
    entries = {e[1]: e for e in centre.preview._menu._entries if e[0] == "item"}
    assert entries["scope:element"][4] == "check" and not entries["overlay"][6]
    centre.preview._on_menu("scope:slide")
    centre.preview.render_now()
    wait_idle(centre)
    assert [e for e in centre.preview._menu._entries if e[0] == "item" and e[1] == "open_pdf"][0][6]
    centre.preview._on_menu("open_pdf")
    assert renders[-1][0] == "open"


def test_rendering_the_buffer_uses_the_unsaved_text_the_scope_and_the_reveal_step(centre, renders, monkeypatch):
    state = centre.state
    state.set_focused_slide("aaa")
    state.set_mode("split")
    editor = centre.source.current.editor
    editor.insertPlainText("% unsaved\n")
    preview = centre.preview
    preview._on_menu("scope:region")
    informed = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: informed.append(args[2]))
    preview.render_buffer()                                   # nothing selected
    assert informed and renders == []
    cursor = editor.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    monkeypatch.setattr(preview_view.QInputDialog, "getInt", lambda *a, **k: (3, True))
    preview._on_menu("overlay")
    preview.render_buffer()
    wait_idle(centre)
    kind, id_slug, args, kwargs = renders[0]
    assert kind == "buffer" and args[0] == editor.selected_text() == "unsaved"
    assert (kwargs["mode"], kwargs["overlay"], args[1]) == ("region", 3, "instructor")
    assert page(centre).pixmap is not None
    assert preview._status_chip.text() == "Render to verify current source and dependencies"
    preview._on_menu("scope:element")                         # a cropped element has no reveal steps
    preview.render_buffer()
    wait_idle(centre)
    assert renders[1][3]["overlay"] is None
    state.set_view("after-course")
    assert preview._status_chip.text() != "Rendered from the editor buffer, not the saved file"


def test_a_presenter_render_opens_the_viewer_instead_of_the_page(centre, renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_buffer(presenter=True)
    wait_idle(centre)
    assert renders[0][3]["presenter"] and renders[1][0] == "open"
    assert page(centre).pixmap is None


@pytest.mark.parametrize("language, mode, id_slug, draft", [
    ("EN", "source", "aaa-EN-One", ""),
    ("DE", "split", "ddd-DE-Eins", "% German buffer\n"),
])
def test_rendering_the_source_buffer_shows_the_page_in_the_active_language(centre, project, renders, language, mode, id_slug, draft):
    if language == "DE":
        link_german(project)
    state = centre.state
    state.set_mode(mode)
    state.set_focused_slide("aaa")
    state.set_language(language)
    if draft:
        centre.source.current.editor.insertPlainText(draft)
    centre.source.show()
    centre.source.current.editor.setFocus()
    centre.source.render_requested.emit()
    wait_idle(centre)
    assert state.mode == "split" and renders[0][0:2] == ("buffer", id_slug)
    if draft:
        assert draft in renders[0][2][0]


def test_the_preview_never_renders_the_buffer_of_another_slide(centre, renders):
    """Source view on slide aaa, then Preview mode on another slide: Render must use that slide's file."""
    state = centre.state
    state.set_mode("split")
    state.set_focused_slide("aaa")
    state.set_mode("preview")
    state.set_focused_slide("ddd")
    assert centre.source.current is not None                     # still the earlier slide
    assert centre._preview_buffer() is None
    assert centre.preview._is_draft(centre.preview._target) is False


def test_a_source_with_errors_is_not_rendered_after_a_save(centre, renders, monkeypatch, project):
    centre.state.set_mode("split")
    centre.state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("\\begin{standardframe}{x}{oops")
    assert centre.source.save()
    wait_idle(centre)
    assert renders == []


def test_the_transcript_of_the_buffer_opens_in_a_preview_sheet(centre, monkeypatch):
    centre.state.set_focused_slide("aaa")
    asked = []

    def generate(ctx, text, bare, view, language):
        asked.append((bare, view, language))
        return SimpleNamespace(undescribed=True)

    monkeypatch.setattr(transcript_preview.transcript, "generate_single_slide", generate)
    monkeypatch.setattr(transcript_preview.transcript, "to_html", lambda result, title: f"<h1>{title}</h1>")
    shown = []

    class Sheet:
        def __init__(self, parent, title, html):
            shown.append((title, html))

        def exec(self):
            shown.append("exec")

    monkeypatch.setattr(transcript_preview, "TranscriptPreviewSheet", Sheet)
    centre.preview.render_transcript()
    assert asked == [("aaa", centre.state.view, "en")]
    assert shown == [("Transcript: aaa-EN-One", "<h1>Transcript preview: aaa-EN-One</h1>"), "exec"]
    assert any("undescribed image" in line for line in centre.app.logged)


# -- details ----------------------------------------------------------------------------

def test_details_follow_the_focused_slide(centre):
    from PySide6.QtWidgets import QLabel

    state = centre.state
    state.set_mode("details")
    state.set_focused_slide("ccc")
    texts = [label.text() for label in centre.details.findChildren(QLabel)]
    assert "Dritte" in texts and "ccc-DE-Drei-current.tex" in texts and "standardframe" in texts
    assert "Visibility in this deck" not in texts and "Versions" not in texts   # side panels now
    state.set_focused_slide(None)
    assert [label.text() for label in centre.details.findChildren(QLabel)] == [
        "Select a slide in the list. Double-click it to open its source."]
    centre.state.deck.path.write_text(DECK, encoding="utf-8")
    centre.open_file(centre.state.deck.path)
    state.set_mode("details")
    assert "not a slide" in centre.details.findChildren(QLabel)[0].text()


def test_moving_a_slide_with_edits_that_cannot_be_saved_is_refused(centre, project, monkeypatch):
    state = centre.state
    state.set_mode("source")
    state.set_focused_slide("ccc")
    centre.source.current.editor.insertPlainText("edit ")
    path = project / "ccc-DE-Drei-current.tex"
    path.write_text(path.read_text(encoding="utf-8") + "% elsewhere\n", encoding="utf-8")   # so the edit is in conflict
    state.set_mode("details")
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("must not ask"))
    details = centre.details
    details._rename()
    details._delete()
    assert len(told) == 2 and (project / "ccc-DE-Drei-current.tex").exists()


def test_duplicate_opens_the_add_slide_sheet_on_the_slide(centre):
    centre.state.set_mode("details")
    centre.state.set_focused_slide("ccc")
    requested = []
    centre.duplicate_requested.connect(requested.append)
    centre.details._duplicate()
    assert requested == ["ccc-DE-Drei"]


def test_rename_and_delete_go_through_slide_rename(centre, project, monkeypatch):
    from slidemage import slide_rename
    from slidemage.ui.workspace import details_view

    calls = []
    monkeypatch.setattr(slide_rename, "count_references", lambda _ctx, id_slug: 2)
    monkeypatch.setattr(slide_rename, "deck_names_referencing", lambda _ctx, id_slug: ["course"])
    monkeypatch.setattr(slide_rename, "rename_slide_slug", lambda _ctx, old, slug: calls.append(("slug", old, slug)) or "ccc-DE-Drie")
    monkeypatch.setattr(slide_rename, "delete_slide_id",
                        lambda _ctx, id_slug: calls.append(("delete", id_slug)) or {"files_removed": 1, "deck_references_removed": 2})
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(details_view.QInputDialog, "getText", lambda *a, **k: ("Drie", True))
    refreshed = []
    centre.app.refresh_open_deck_editors = lambda: refreshed.append(True)
    centre.state.set_mode("details")
    centre.state.set_focused_slide("ccc")
    details = centre.details
    details._rename()
    details._delete()
    assert calls == [("slug", "ccc-DE-Drei", "Drie"), ("delete", "ccc-DE-Drei")]
    assert refreshed == [True] * 2 and centre.state.focused_slide is None


def test_keys_in_the_source_view_do_not_leak_into_other_views(centre):
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    editor = centre.source.current.editor
    centre.source.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_X)
    assert centre.source.current.dirty


def test_a_lint_issue_opens_its_file_at_its_line(centre, project):
    from slidemage import latex_lint

    issue = latex_lint.LintIssue(latex_lint.CHECKS[0][0], "m", 3, "ccc-DE-Drei-current.tex", project / "ccc-DE-Drei-current.tex")
    render_check.open_issue_in_editor(centre.app, issue)
    assert centre.source.current.path == issue.path
    assert centre.source.current.editor.textCursor().blockNumber() == 2


def test_an_unsaved_draft_offers_to_render_the_buffer_not_the_saved_file(centre, renders):
    """Regression: a further edit to an already dirty rendered draft must mark its preview stale."""
    centre.state.set_focused_slide('aaa')
    centre.state.set_mode('split')
    centre.source.current.editor.insertPlainText('% a draft, never saved\n')
    QTest.qWait(300)
    preview = centre.preview
    assert 'Unsaved edits' in preview._status_chip.text()
    assert preview._status_button.text().startswith('Render draft')
    assert not preview._status_button.isHidden()
    assert not renders  # noticing a draft never compiles
    preview._status_button.click()
    wait_idle(centre)
    assert 'Previous render' in preview._status_chip.text()  # unverified stand-in renderer
    assert not preview._status_draft  # the remaining button asks to verify dependencies
    assert len(renders) == 1 and 'a draft, never saved' in str(renders[0])
    assert centre.source.current.dirty
    centre.source.current.editor.insertPlainText('% a second edit while still dirty\n')
    QTest.qWait(200)
    assert 'Previous render' in preview._status_chip.text() and preview._status_draft
    assert len(renders) == 1  # status refresh never compiles on a keystroke


def test_split_divider_share_is_remembered_and_double_click_resets_it(centre):
    from slidemage.ui import layout_settings
    from slidemage.ui.workspace import centre as centre_mod

    centre.resize(1600, 700)
    centre.show()
    centre.state.set_mode("split")
    split = centre._split
    split.setSizes([900, 600])
    split.splitterMoved.emit(900, 1)
    assert layout_settings.get(centre_mod.SPLIT_SETTING) == pytest.approx(0.6, abs=0.02)

    centre.state.set_mode("preview")
    centre.state.set_mode("split")   # entering Split again keeps the dragged share
    source, preview = split.sizes()
    assert source / (source + preview) == pytest.approx(0.6, abs=0.02)

    split.reset_requested.emit()
    source, preview = split.sizes()
    assert source / (source + preview) < 0.59   # back towards half (the views' minimum widths may hold it a little)
    assert layout_settings.get(centre_mod.SPLIT_SETTING) == 0.5


# -- the language chip jumps to the translation partner ------------------------------

def language_chip(centre):
    layout = centre.preview._chips
    return next(w for w in (layout.itemAt(i).widget() for i in range(layout.count()))
                if w is not None and w._icon.text() == "language")


def test_the_language_chip_shows_the_german_version_and_back_without_touching_the_top_bar(centre, project, renders):
    english, german = link_german(project)
    state = centre.state
    state.set_mode("preview")
    state.set_focused_slide("aaa")
    chip = language_chip(centre)
    assert chip.text() == "EN + DE" and chip.toolTip() == "Go to the German version"
    assert chip.accessibleName() == "Go to the German version" and chip.focusPolicy() == Qt.FocusPolicy.TabFocus
    chip.clicked.emit()
    assert state.language == "EN" and state.mode == "preview"       # one slide: the top bar and the mode stay
    assert centre.path == german and state.focused_slide == "ddd"
    assert centre.preview._target.id_slug == "ddd-DE-Eins" and centre.preview._target.frame_number == 1
    assert centre.preview.language == "DE" and centre.preview._row.call.id_slug == "aaa-EN-One"
    assert centre.preview._target.preamble_text == centre.state.deck.preamble_text      # in the deck's theme, not alone
    back = language_chip(centre)
    assert back.text() == "DE + EN" and back.toolTip() == "Go to the English original"
    centre.preview.render_now()
    wait_idle(centre)
    assert renders[-1][1] == "ddd-DE-Eins" and renders[-1][2][1:3] == ("instructor", "DE")
    back.clicked.emit()
    assert centre.path == english and state.focused_slide == "aaa" and state.language == "EN"
    assert centre.preview._target.id_slug == "aaa-EN-One" and centre.preview.language == "EN"


def test_the_language_chip_is_a_keyboard_button(centre, project):
    _english, german = link_german(project)
    centre.state.set_focused_slide("aaa")
    chip = language_chip(centre)
    centre.preview.show()
    chip.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(chip, Qt.Key.Key_Return)
    assert centre.path == german
    chip = language_chip(centre)
    chip.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(chip, Qt.Key.Key_Space)
    assert centre.path.name == "aaa-EN-One-current.tex"


def test_a_slide_without_a_partner_has_a_plain_language_chip(centre):
    centre.state.set_focused_slide("aaa")
    chip = language_chip(centre)
    assert chip.text() == "EN" and chip.focusPolicy() == Qt.FocusPolicy.NoFocus and chip.accessibleName() == ""
    centre.state.set_mode("preview")
    chip.clicked.emit()
    assert centre.state.focused_slide == "aaa"


def test_the_language_chip_works_for_a_slide_outside_the_deck(centre, project):
    english, german = link_german(project)
    deck = centre.state.deck
    centre.state.set_deck(None)
    centre.open_file(english, keep_mode=True)
    assert language_chip(centre).text() == "EN + DE"
    language_chip(centre).clicked.emit()
    assert centre.path == german and centre.preview._row is None and centre.preview._target.id_slug == "ddd-DE-Eins"
    assert language_chip(centre).toolTip() == "Go to the English original"
    centre.state.set_deck(deck)


def test_a_partner_that_is_gone_is_said_so(centre, project):
    english, german = link_german(project)
    centre.state.set_focused_slide("aaa")
    messages = []
    centre.app.toast = SimpleNamespace(show_message=messages.append)
    german.unlink()
    centre.preview._show_partner(german)
    assert len(messages) == 1 and "ddd-DE-Eins-current.tex is missing" in messages[0]
    assert centre.path == english


# -- leaving a changed slide (v8.22.0) -------------------------------------------------------------

@pytest.fixture
def asked(centre, monkeypatch):
    """The questions asked when leaving a changed slide; `answer` is what each one returns."""
    from slidemage.ui.workspace import centre as centre_module

    calls, updated = [], []
    answer = {"update": False, "stop": False}

    def ask(_parent, slide_id, version):
        calls.append((slide_id, version))
        return answer["update"], answer["stop"]

    monkeypatch.setattr(centre_module, "ask_update_on_leave", ask)
    monkeypatch.setattr(centre, "update_version", updated.append)
    return SimpleNamespace(calls=calls, updated=updated, answer=answer)


def leave_after_editing(centre, slide="aaa", to="ccc", edit=True):
    state = centre.state
    state.set_mode("source")
    state.set_focused_slide(slide)
    if edit:
        centre.source.current.editor.insertPlainText("edit ")
    state.set_focused_slide(to)
    QApplication.processEvents()


def ask_on_leave(centre, on=True):
    from slidemage import app_settings, slide_versioning
    app_settings.set(centre.state.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY, on)


def test_leaving_an_edited_slide_asks_about_update_version_when_the_setting_is_on(centre, project, asked):
    ask_on_leave(centre)
    asked.answer["update"] = True
    leave_after_editing(centre)
    assert "1-1-0+" in (project / "aaa-EN-One-current.tex").read_text()
    assert asked.calls == [("aaa", (1, 1, 0))]
    assert asked.updated == ["aaa-EN-One"]                 # the slide's own Update Version
    assert centre.state.focused_slide == "ccc"            # the switch itself happened


def test_leaving_asks_nothing_when_off_without_edits_or_once_not_now_was_answered(centre, asked):
    leave_after_editing(centre)                            # off by default
    assert asked.calls == []
    ask_on_leave(centre)
    leave_after_editing(centre, edit=False)                # only looked at: its "+" is from before
    assert asked.calls == []
    leave_after_editing(centre)                            # edited: asked, "Not now"
    leave_after_editing(centre, edit=False)                # not asked again for that visit's edits
    assert len(asked.calls) == 1 and asked.updated == []


def test_dont_ask_again_turns_the_setting_off(centre, asked):
    from slidemage import app_settings, slide_versioning

    ask_on_leave(centre)
    asked.answer["stop"] = True
    leave_after_editing(centre)
    assert len(asked.calls) == 1
    assert app_settings.get(centre.state.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY) is False
    leave_after_editing(centre)
    assert len(asked.calls) == 1
