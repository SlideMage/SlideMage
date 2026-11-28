# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The centre column: which view shows what for the focused slide, the Preview's
states and renders (the renderer is faked), and unsaved edits across slides."""
from __future__ import annotations

from conftest import pause

import time
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from slidemage import alt_images, app_settings, deck_outline, open_path, preview_target, slide_snapshot, slide_templates
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.ui.dialogs import transcript_preview
from slidemage.ui import layout_settings
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace import preview_view, render_check, source_file
from slidemage.ui.workspace.centre import CENTRE_TABS_SETTING, CentreColumn
from slidemage.ui.workspace.state import SETTINGS_KEY, WorkspaceState


FRAME = "\\begin{standardframe}{%s}\nText\n\\end{standardframe}\n"
DECK = (
    "\\documentclass{beamer}\n\\input{SlideMage_template_acme-two}\n\\begin{document}\n"
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

    def open_slide_editor(self, path, on_saved=None, line=None, **kwargs):
        self.centre.open_file(path, on_saved, line, **kwargs)

    def after_version_updates(self, _paths):
        self.centre.refresh()

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
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    monkeypatch.setattr(slide_templates, "render_template", lambda root=None: "acme")
    return slides


@pytest.fixture
def deck(tmp_path):
    return Deck(name="course", path=tmp_path / "course.tex", archived=False, text=DECK, supports_version=True,
                uses_biblatex=False, preamble_end=DECK.index("\\begin{document}") + len("\\begin{document}"),
                chapters=parse_chapters(DECK), output_folders={})


@pytest.fixture
def renders(tmp_path, monkeypatch):
    """preview_target's two renderers, replaced by recorders that write a small 16:9 PDF."""
    pdf = tmp_path / ".temp" / "render.pdf"
    pdf.parent.mkdir(exist_ok=True)
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

    # Exercise preview rasterization; GUI state tests do not need full-HD rasterization.
    monkeypatch.setattr(slide_snapshot, "FULL_SIZE", (160, 90))
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
    app.centre = centre
    state.set_deck(deck)
    yield centre
    centre.preview._dispose()
    centre.preview._display_executor.shutdown(wait=True, cancel_futures=True)
    centre.preview._prefetch_executor.shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def held_autosave(monkeypatch):
    """An unsaved buffer must not autosave (1.5 s) while wait_idle() runs. List it before `centre`: the delay is read when a source file is made."""
    monkeypatch.setattr(source_file, "AUTOSAVE_DELAY_MS", 10 * 60 * 1000)


def wait_idle(centre):
    """Until the Preview has rendered, its render's record is written and the check after it has run."""
    preview = centre.preview

    def recording():
        done = getattr(preview._last_request, "done", None)
        return done is not None and not done.is_set()

    deadline = time.monotonic() + 5
    recorded = False
    idle_since = None                    # a render starts on a later turn of the event loop: idle must last a moment
    while time.monotonic() < deadline:
        pause(10)
        recorded = recorded or recording()
        if preview._busy or bool(preview.model.lookups.slots) or recording():
            idle_since = None
        else:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since >= 0.06:
                break
        QApplication.processEvents()
        time.sleep(0.01)
    if recorded:                         # the check runs on the next poll of _check_when_recorded (every 50 ms)
        end = time.monotonic() + 0.15
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)
    assert not preview._busy and not recording()


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


def test_saving_renders_only_the_active_language_when_the_page_is_visible_and_a_source_render_shows_it(centre, project, renders):
    english, german = link_german(project)
    before = english.read_bytes()
    centre.state.set_focused_slide("aaa")
    centre.state.set_mode("split")
    centre.state.set_language("DE")
    centre.source.current.editor.insertPlainText("% German saved edit\n")
    assert centre.source.save()
    wait_idle(centre)
    assert "% German saved edit" in german.read_text() and english.read_bytes() == before
    assert [c[0:2] for c in renders] == [("buffer", "ddd-DE-Eins")] and page(centre).pixmap is not None
    centre.state.set_mode("source")  # no page to show: no render
    centre.source.current.editor.insertPlainText("% again ")
    assert centre.source.save()
    wait_idle(centre)
    assert len(renders) == 1
    centre.source.render_requested.emit()          # a render asked from the Source view shows the page, in this language
    wait_idle(centre)
    assert centre.state.mode == "split" and renders[1][0:2] == ("buffer", "ddd-DE-Eins") and "% again" in renders[1][2][0]


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
    monkeypatch.setattr(preview_view, "translation_group", lambda _ctx, id_slug, **_kw: [link])
    centre.preview._refresh()
    assert chip_texts(centre) == ["Deck stays on v1.0.0", "Translation outdated", "EN + DE"]
    monkeypatch.setattr(preview_view, "translation_group", lambda _ctx, id_slug, **_kw: [])
    centre.preview._refresh()
    assert "Translation outdated" not in chip_texts(centre)


# -- modes and what each view shows ------------------------------------------------

def test_opening_the_focused_slide_keeps_the_occurrence_the_list_focused(centre, project, tmp_path):
    from dataclasses import replace
    from slidemage import deck_outline
    state = centre.state
    text = DECK.replace("\\slide{aaa-EN-One}\n", "\\slide{aaa-EN-One}\n\\slide{aaa-EN-One}\n")
    state.set_deck(replace(state.deck, text=text, chapters=parse_chapters(text)))
    slots = [r for r in deck_outline.resolve_slots(state.project, state.deck, state.view, state.language)
             if r.slot.matches("aaa")]
    assert len(slots) == 2 and slots[0].frame_number != slots[1].frame_number
    state.set_mode("preview")
    shown, emitted = [], []
    real = centre.preview.show_slide
    centre.preview.show_slide = lambda target, *args: (shown.append(target), real(target, *args))[1]
    state.focused_slide_changed.connect(emitted.append)
    state.set_focused_slide("aaa", occurrence_key=slots[1].key)      # the press
    centre.open_file(project / "aaa-EN-One-current.tex", keep_mode=True)      # the release
    assert state.focused_occurrence == slots[1].key and state.mode == "preview"
    assert emitted == ["aaa"]
    assert {t.frame_number for t in shown} == {slots[1].frame_number}
    assert centre._focused_row().frame_number == slots[1].frame_number
    centre.open_file(project / "aaa-EN-One-current.tex")                      # Enter: Source of that occurrence
    assert state.mode == "source" and state.focused_occurrence == slots[1].key and emitted == ["aaa"]
    centre.open_file(project / "ccc-DE-Drei-current.tex")                     # another slide is focused as before
    assert state.focused_slide == "ccc" and state.focused_occurrence is None


def test_a_file_that_is_renamed_meanwhile_is_forgotten(centre, project):
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    (project / "aaa-EN-One-current.tex").rename(project / "aaa-EN-Uno-current.tex")
    centre.refresh()
    assert centre.source.current is None


# -- the preview ----------------------------------------------------------------------

def test_the_chips_say_what_the_page_is_not_showing(centre, renders):
    state = centre.state
    state.set_focused_slide("bbb")
    assert chip_texts(centre) == ["Deck stays on v1.0.0", "EN"]
    state.set_focused_slide("ccc")
    assert chip_texts(centre) == ["No EN version", "DE"]       # a German slide while editing English
    state.set_language("DE")
    assert chip_texts(centre) == ["DE"]
    state.set_view("during-course")
    assert chip_texts(centre) == ["Hidden in During course", "DE"]
    state.set_view("after-course")                    # a slide the view does not typeset says so and offers no render
    assert "not typeset in the After course view" in page(centre).message
    assert not page(centre).render_button.isVisibleTo(centre) and renders == []


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


def test_the_render_menu_offers_open_and_render_entries_and_the_last_pdf(centre, renders):
    centre.state.set_focused_slide("aaa")
    entries = {e[1]: e for e in centre.preview._menu._entries if e[0] == "item"}
    assert list(entries) == ["open_pdf", "presenter", "buffer", "all_buffer", "all_saved", "transcript", "force"]
    assert [e[1] for e in centre.preview._menu._entries if e[0] == "header"] == ["Open", "Render"]
    assert not entries["open_pdf"][6]                        # nothing rendered yet
    centre.preview.render_now()
    wait_idle(centre)
    assert [e for e in centre.preview._menu._entries if e[0] == "item" and e[1] == "open_pdf"][0][6]
    centre.preview._on_menu("open_pdf")
    wait_idle(centre)
    assert renders[-1][0] == "open"


def test_a_presenter_render_opens_the_viewer_instead_of_the_page(centre, renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_buffer(presenter=True)
    wait_idle(centre)
    assert renders[0][3]["presenter"] and renders[1][0] == "open"
    assert page(centre).pixmap is None


def test_the_preview_never_renders_the_buffer_of_another_slide(centre, renders):
    """Source view on slide aaa, then Preview mode on another slide: Render must use that slide's file."""
    state = centre.state
    state.set_mode("split")
    state.set_focused_slide("aaa")
    state.set_mode("preview")
    state.set_focused_slide("ddd")
    assert centre.source.current is not None                     # still the earlier slide
    assert centre._preview_buffer() is None
    assert not centre.preview._status_draft


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
        "Select a slide in the list. Click it to open its source."]


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


def test_duplicate_rename_and_delete_go_through_the_slide_sheets_and_slide_rename(centre, project, monkeypatch):
    from slidemage import slide_rename
    from slidemage.ui.workspace import details_view

    calls = []
    monkeypatch.setattr(slide_rename, "count_references", lambda _ctx, id_slug: 2)
    monkeypatch.setattr(slide_rename, "deck_names_referencing", lambda _ctx, id_slug: ["course"])
    monkeypatch.setattr(slide_rename, "rename_slide_slug", lambda _ctx, old, slug, _warnings=None: calls.append(("slug", old, slug)) or "ccc-DE-Drie")
    monkeypatch.setattr(slide_rename, "delete_slide_id",
                        lambda _ctx, id_slug, warnings=None: calls.append(("delete", id_slug)) or {"files_removed": 1, "deck_references_removed": 2})
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(details_view.QInputDialog, "getText", lambda *a, **k: ("Drie", True))
    refreshed = []
    centre.app.refresh_open_deck_editors = lambda: refreshed.append(True)
    centre.state.set_mode("details")
    centre.state.set_focused_slide("ccc")
    details = centre.details
    requested = []
    centre.duplicate_requested.connect(requested.append)
    details._duplicate()                                        # opens the add-slide sheet on the slide
    assert requested == ["ccc-DE-Drei"]
    details._rename()
    details._delete()
    assert calls == [("slug", "ccc-DE-Drei", "Drie"), ("delete", "ccc-DE-Drei")]
    assert refreshed == [True] * 2 and centre.state.focused_slide is None


def test_a_lint_issue_opens_its_file_at_its_line(centre, project):
    from slidemage import latex_lint

    issue = latex_lint.LintIssue(latex_lint.CHECKS[0][0], "m", 3, "ccc-DE-Drei-current.tex", project / "ccc-DE-Drei-current.tex")
    render_check.open_issue_in_editor(centre.app, issue)
    assert centre.source.current.path == issue.path
    assert centre.source.current.editor.textCursor().blockNumber() == 2


def test_an_unsaved_draft_offers_to_render_the_buffer_not_the_saved_file(held_autosave, centre, renders):
    """Regression: a further edit to an already dirty rendered draft must mark its preview stale."""
    centre.state.set_focused_slide('aaa')
    centre.state.set_mode('split')
    centre.source.current.editor.insertPlainText('% a draft, never saved\n')
    pause(300)
    wait_idle(centre)
    preview = centre.preview
    assert 'Unsaved edits' in preview._status_chip.text()
    assert preview._status_button.text().startswith('Render draft')
    assert not preview._status_button.isHidden()
    assert not renders  # noticing a draft never compiles
    preview._status_button.click()
    wait_idle(centre)
    assert preview._record is not None and not preview._status_draft
    assert len(renders) == 1 and 'a draft, never saved' in str(renders[0])
    assert centre.source.current.dirty
    centre.source.current.editor.insertPlainText('% a second edit while still dirty\n')
    pause(200)
    wait_idle(centre)
    assert preview._status_draft
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
    assert chip.text() == "EN + DE" and chip.focusPolicy() == Qt.FocusPolicy.TabFocus
    centre.preview.show()
    chip.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(chip, Qt.Key.Key_Return)                         # a keyboard button
    assert state.language == "EN" and state.mode == "preview"       # one slide: the top bar and the mode stay
    assert centre.path == german and state.focused_slide == "ddd"
    assert centre.preview._target.id_slug == "ddd-DE-Eins" and centre.preview._target.frame_number == 1
    assert centre.preview.language == "DE" and centre.preview._row.call.id_slug == "aaa-EN-One"
    assert centre.preview._target.preamble_text == centre.state.deck.preamble_text      # in the deck's theme, not alone
    back = language_chip(centre)
    assert back.text() == "DE + EN"
    centre.preview.render_now()
    wait_idle(centre)
    assert renders[-1][1] == "ddd-DE-Eins" and renders[-1][2][1:3] == ("instructor", "DE")
    back.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(back, Qt.Key.Key_Space)
    assert centre.path == english and state.focused_slide == "aaa" and state.language == "EN"
    assert centre.preview._target.id_slug == "aaa-EN-One" and centre.preview.language == "EN"


def test_the_language_chip_works_for_a_slide_outside_the_deck(centre, project):
    english, german = link_german(project)
    deck = centre.state.deck
    centre.state.set_deck(None)
    centre.open_file(english, keep_mode=True)
    assert language_chip(centre).text() == "EN + DE"
    language_chip(centre).clicked.emit()
    assert centre.path == german and centre.preview._row is None and centre.preview._target.id_slug == "ddd-DE-Eins"
    assert language_chip(centre).text() == "DE + EN"
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
    monkeypatch.setattr(centre, "revise", lambda action, paths: updated.extend(paths))
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


def test_leaving_an_edited_slide_asks_about_update_version_before_the_new_slide_is_shown(centre, project, asked, monkeypatch):
    from slidemage.ui.workspace import centre as centre_module

    ask_on_leave(centre)
    seen = []

    def ask(_parent, slide_id, version):
        seen.append((slide_id, version, centre.state.focused_slide, centre.path))   # what is on show while the question is up
        return True, False

    monkeypatch.setattr(centre_module, "ask_update_on_leave", ask)
    leave_after_editing(centre)
    assert "1-1-0+" in (project / "aaa-EN-One-current.tex").read_text()
    assert seen == [("aaa", (1, 1, 0), "aaa", project / "aaa-EN-One-current.tex")]    # still the slide being left
    assert centre.state.focused_slide == "ccc"                         # shown after the answer
    assert asked.updated == [project / "aaa-EN-One-current.tex"]       # the version itself follows the switch


def test_leaving_asks_only_after_edits_with_the_setting_on_and_dont_ask_again_turns_it_off(centre, asked):
    from slidemage import app_settings, slide_versioning

    leave_after_editing(centre)                            # off by default
    assert asked.calls == []
    ask_on_leave(centre)
    leave_after_editing(centre, edit=False)                # only looked at: its "+" is from before
    assert asked.calls == []
    leave_after_editing(centre)                            # edited: asked, "Not now"
    leave_after_editing(centre, edit=False)                # not asked again for that visit's edits
    assert len(asked.calls) == 1 and asked.updated == []
    asked.answer["stop"] = True                            # "Don't ask again" turns the setting off
    leave_after_editing(centre)
    assert len(asked.calls) == 2
    assert app_settings.get(centre.state.project, slide_versioning.ASK_ON_LEAVE_SETTING_KEY) is False
    leave_after_editing(centre)
    assert len(asked.calls) == 2


def test_closing_asks_about_the_slide_still_on_show_and_those_left_before_only_with_the_setting(centre, project, asked):
    state = centre.state
    state.set_mode("source")
    state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("edit ")
    centre.source.flush_all()                              # the close saves first
    centre.offer_versions_on_close()                       # off by default: nothing asked
    assert asked.calls == []
    ask_on_leave(centre)
    centre.source.current.editor.insertPlainText("more ")
    centre.source.flush_all()
    asked.answer["update"] = True
    centre.offer_versions_on_close()                       # aaa is still on show, and is asked about
    assert asked.calls == [("aaa", (1, 1, 0))] and asked.updated == [project / "aaa-EN-One-current.tex"]
    centre.offer_versions_on_close()                       # once per visit
    assert len(asked.calls) == 1


def click(centre, project, slide, name, **kwargs):
    """The slide list's click: the press focuses the row, the release opens its file (keeping the mode)."""
    centre.state.set_focused_slide(slide)
    centre.open_file(project / name, keep_mode=True, **kwargs)


def count_shows(centre):
    shown = []
    real = centre.preview.show_slide
    centre.preview.show_slide = lambda *args: (shown.append(args[0]), real(*args))[1]
    return shown


def test_opening_in_preview_with_a_line_or_a_callback_still_builds_the_editor(centre, project, tmp_path):
    centre.state.set_mode("preview")
    centre.open_file(project / "ccc-DE-Drei-current.tex", keep_mode=True, line=2)
    file = centre.source.file_for(project / "ccc-DE-Drei-current.tex")
    assert file is not None and file.editor.textCursor().blockNumber() == 1 and centre.state.mode == "preview"
    saved = []
    centre.open_file(project / "aaa-EN-One-current.tex", saved.append, keep_mode=True)
    file = centre.source.file_for(project / "aaa-EN-One-current.tex")
    assert file is not None and file.on_saved == saved.append and centre.state.mode == "preview"
    file.editor.insertPlainText("x ")
    assert file.write_now()
    assert len(saved) == 1 and saved[0][0].startswith("\\setSlideVersion")      # the previous text


def test_edits_pending_in_the_source_view_are_written_to_their_slide_by_a_preview_click(centre, project, asked):
    ask_on_leave(centre)
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("edit ")           # waiting for its autosave
    centre.state.set_mode("preview")
    ccc_before = (project / "ccc-DE-Drei-current.tex").read_text()
    shown = count_shows(centre)
    click(centre, project, "ccc", "ccc-DE-Drei-current.tex")
    assert len(shown) == 1 and shown[0].id_slug == "ccc-DE-Drei" and centre.state.mode == "preview"   # shown once
    assert "edit " in (project / "aaa-EN-One-current.tex").read_text()      # written, not lost
    assert (project / "ccc-DE-Drei-current.tex").read_text() == ccc_before   # and not to the new slide
    assert centre.source.file_for(project / "ccc-DE-Drei-current.tex") is None
    QApplication.processEvents()
    assert asked.calls == [("aaa", (1, 1, 0))]                      # the Update Version offer still runs
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    assert "edit " in centre.source.current.editor.text() and not centre.source.current.dirty


def resolved(centre):
    """What the slide list does after a rebuild: publish the deck's resolved outline on the state."""
    state = centre.state
    state.outline = deck_outline.resolve_outline(state.project, state.deck, state.view, state.language)
    return state.outline


def test_selection_in_the_centre_reuses_the_resolved_outline(centre, resolutions):
    state = centre.state
    state.set_mode("preview")
    outline = resolved(centre)
    state.set_focused_slide("aaa", occurrence_key=outline.rows[0].key)
    resolutions.reset()
    for row in outline.rows[1:]:
        state.set_focused_slide(row.call.id, occurrence_key=row.key)
        assert centre._focused_row() is row and centre.preview._row is row
        assert centre.preview._target.occurrence_key == row.key
        assert centre.preview._target.presenter_frame_number == outline.instructor_frames[row.key]
    assert centre._neighbour_targets()
    assert (resolutions.slots, resolutions.outlines, resolutions.scans) == (0, 0, 0)


def test_the_neighbours_of_a_german_slide_resolve_the_deck_once_not_on_every_refresh(centre, resolutions):
    # Profiled in the app (v8.52.0): in German every Preview refresh resolved every slot of the deck six times on
    # the GUI thread, for the Instructor frame numbers of the neighbours.
    state = centre.state
    state.set_mode("preview")
    state.set_language("DE")
    outline = resolved(centre)
    state.set_focused_slide(outline.rows[0].call.id, occurrence_key=outline.rows[0].key)
    resolutions.reset()
    first = centre._neighbour_targets()
    assert first and resolutions.slots <= 1
    for _ in range(5):
        assert centre._neighbour_targets() is first
    state.set_focused_slide(outline.rows[1].call.id, occurrence_key=outline.rows[1].key)
    assert centre._neighbour_targets() and resolutions.slots <= 1      # another slide: the English frames are kept


def test_a_deck_edit_is_seen_by_the_centre(centre, deck):
    from dataclasses import replace

    state = centre.state
    state.set_mode("preview")
    resolved(centre)
    state.set_focused_slide("aaa")
    assert centre.preview._target.position == 1
    text = deck.text.replace("\\section{Part}\n", "\\section{Part}\n\\slide{ccc-DE-Drei}\n")
    state.set_deck(replace(deck, text=text, chapters=parse_chapters(text)))      # a rescan of the open deck: no signal
    assert state.current_outline() is None
    centre.refresh()
    assert centre.preview._target.position == 2


def test_a_saved_title_or_translation_header_is_seen_by_the_centre_at_once(centre, project):
    state = centre.state
    state.set_mode("split")
    state.set_focused_slide("aaa")
    resolved(centre)
    assert centre.preview._row.title == "First" and state.current_outline() is not None
    editor = centre.source.current.editor
    editor.replace_all_text(editor.text().replace("First", "Retitled"))
    assert centre.source.current.write_now()                      # the autosave: the list's rebuild comes later
    assert state.current_outline() is None
    centre.refresh()
    assert centre.preview._row.title == "Retitled"
    resolved(centre)
    german = project / "ddd-DE-Eins-current.tex"
    german.write_text("%% Translation of: aaa-EN-One\n" + FRAME % "Erste")
    editor.replace_all_text("%% DE translation: ddd-DE-Eins\n" + editor.text())
    assert centre.source.current.write_now()
    state.set_language("DE")
    assert centre.preview._target.id_slug == "ddd-DE-Eins" and centre.preview._row.title == "Erste"


def panel_edit(text):
    return text + "% from a panel\n"


def test_a_panel_edit_of_the_slide_left_is_written_and_the_source_view_stays_on_the_new_slide(centre, project):
    aaa, ccc = project / "aaa-EN-One-current.tex", project / "ccc-DE-Drei-current.tex"
    centre.state.set_mode("preview")
    centre.state.set_focused_slide("aaa")
    ccc_before = ccc.read_text()
    centre.state.set_focused_slide("ccc")                                # the focus has left aaa already
    assert centre.edit_slide_text(aaa, panel_edit)
    assert "% from a panel" in aaa.read_text() and ccc.read_text() == ccc_before   # aaa is written, ccc is not
    assert centre.source.file_for(aaa) is None and centre.source.file_for(ccc) is None   # no editor stays behind
    assert centre.source.current is None and not centre.state.dirty
    centre.state.set_mode("source")
    shown = centre.source.current
    assert shown.path == ccc and "Dritte" in shown.editor.text()
    assert centre.edit_slide_text(aaa, panel_edit)                      # again, with the new slide's editor on show
    assert centre.source.current is shown


def test_a_panel_edit_stays_in_its_buffer_when_the_file_cannot_be_written(centre, project):
    aaa = project / "aaa-EN-One-current.tex"
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    centre.source.current.editor.insertPlainText("typed ")
    aaa.write_text(aaa.read_text(encoding="utf-8") + "% elsewhere\n", encoding="utf-8")      # a change on disk: a conflict
    centre.state.set_focused_slide("ccc")                                # aaa stays open: its edit cannot be written
    centre.state.set_mode("preview")
    centre.state.set_focused_slide("bbb")
    assert centre.edit_slide_text(aaa, panel_edit)
    file = centre.source.file_for(aaa)
    assert file is not None and file.conflicted and "% from a panel" in file.editor.text()   # kept, not lost
    assert "% from a panel" not in aaa.read_text() and centre.is_blocked(aaa) and centre.state.dirty
    assert centre.source.current.path == project / "ccc-DE-Drei-current.tex"


def test_a_panel_edit_of_a_frozen_version_is_refused_and_leaves_nothing_open(centre, project):
    frozen = project / "bbb-EN-Two-v1-0-0.tex"
    before = frozen.read_text()
    centre.state.set_mode("preview")
    centre.state.set_focused_slide("ccc")
    assert not centre.edit_slide_text(frozen, panel_edit)
    assert frozen.read_text() == before and centre.source.file_for(frozen) is None


def test_a_panel_edit_of_the_slide_in_the_source_view_is_left_to_its_autosave(centre, project):
    aaa = project / "aaa-EN-One-current.tex"
    centre.state.set_mode("source")
    centre.state.set_focused_slide("aaa")
    assert centre.edit_slide_text(aaa, panel_edit)
    file = centre.source.current
    assert file.path == aaa and file.dirty and "% from a panel" in file.editor.text()
    assert "% from a panel" not in aaa.read_text()                      # as before: the autosave writes it
    assert file.write_now() and "% from a panel" in aaa.read_text()


def test_a_deck_source_has_a_save_button_while_autosave_is_off(centre, project, deck):
    deck.path.write_text(DECK, encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    centre.open_file(deck.path)
    save = centre.source._save_button
    assert save.isHidden()                                              # AutoSave on: it saves by itself
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    centre.source.autosave_changed()
    assert not save.isHidden() and not save.isEnabled()                 # nothing to save yet
    centre.source.current.editor.insertPlainText("% mine\n")
    assert save.isEnabled()
    save.click()
    assert "% mine" in deck.path.read_text(encoding="utf-8") and not save.isEnabled()
    centre.open_file(project / "aaa-EN-One-current.tex")
    assert save.isHidden()                                              # a slide: its own toolbar, Ctrl+S


def test_with_autosave_on_closing_saves_without_asking(centre, project, deck, monkeypatch):
    deck.path.write_text(DECK, encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    centre.open_file(deck.path)
    centre.source.current.editor.insertPlainText("% quick\n")       # its autosave has not run yet
    monkeypatch.setattr(centre, "_ask_save", lambda _name: pytest.fail("asked"))
    assert centre.close_tab(centre.tabs.active) and "% quick" in deck.path.read_text(encoding="utf-8")


@pytest.fixture
def files(centre, deck, project):
    """A deck's source and the .bib on disk; the slide `aaa` focused, the Preview on show."""
    deck.path.write_text(DECK, encoding="utf-8")
    bib = centre.state.project.bibliography_path
    bib.write_text("@book{a, title={A}}\n", encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    centre.resize(900, 600)
    centre.show()
    return SimpleNamespace(deck=deck.path, bib=bib, aaa=project / "aaa-EN-One-current.tex",
                           ccc=project / "ccc-DE-Drei-current.tex")


def test_a_file_opens_in_a_tab_of_its_own_and_opening_it_again_shows_that_tab(centre, files):
    centre.open_file(files.deck)
    centre.open_file(files.bib)
    assert [t.path for t in centre.tabs.tabs] == [None, files.deck, files.bib] and centre.tabs.active.path == files.bib
    centre.open_file(files.deck)
    assert len(centre.tabs.tabs) == 3 and centre.tabs.active.path == files.deck and centre.path == files.deck
    buttons = centre.tab_strip.tab_buttons()
    assert [b.label.full_text() for b in buttons[1:]] == ["course.tex", "SlideMage.bib"]
    assert not buttons[0].close_button.isVisibleTo(buttons[0]) and buttons[1].close_button.isVisibleTo(buttons[1])   # the last working tab has no "x"
    assert [b.property("active") for b in buttons] == [False, True, False]


def test_clicking_a_tab_shows_it_and_the_x_and_the_middle_button_close_it(centre, files):
    centre.open_file(files.deck)
    centre.open_file(files.bib)
    deck_button, bib_button = centre.tab_strip.tab_buttons()[1:]
    QTest.mouseClick(deck_button, Qt.MouseButton.LeftButton)
    assert centre.path == files.deck
    QTest.mouseClick(centre.tab_strip.tab_buttons()[0], Qt.MouseButton.LeftButton)
    assert centre.tabs.active is centre.tabs.slide_tab and centre.state.mode == "preview"
    QTest.mouseClick(bib_button, Qt.MouseButton.MiddleButton)                    # middle button: closes
    assert centre.tabs.tab_for(files.bib) is None and len(centre.tab_strip.tab_buttons()) == 2
    QTest.mouseClick(centre.tab_strip.tab_buttons()[0], Qt.MouseButton.MiddleButton)     # the slide tab has no close
    assert len(centre.tabs.tabs) == 2
    QTest.mouseClick(centre.tab_strip.tab_buttons()[1].close_button, Qt.MouseButton.LeftButton)
    assert [t.kind for t in centre.tabs.tabs] == ["deck"] and centre.source.file_for(files.deck) is None


def test_a_slide_focused_from_a_file_tab_shows_the_slide_tab_and_leaves_the_file_open(centre, files):
    state = centre.state
    state.set_mode("split")
    centre.open_file(files.deck)
    state.set_focused_slide("ccc")                      # the slide list's press ...
    assert centre.tabs.active is centre.tabs.slide_tab and state.mode == "split"
    centre.open_file(files.ccc, keep_mode=True)         # ... and its release
    assert centre.path == files.ccc and centre.tabs.tab_for(files.deck) is not None
    assert centre.source.file_for(files.deck) is not None       # held: its buffer is still there
    centre.open_file(files.deck)
    centre.open_file(files.ccc, keep_mode=True)         # a click on the slide that is focused already
    assert centre.tabs.active is centre.tabs.slide_tab and centre.path == files.ccc and state.mode == "split"


def test_a_slide_the_focus_leaves_from_a_file_tab_is_dropped_as_usual(centre, files):
    centre.state.set_mode("source")
    centre.open_file(files.bib)
    assert centre.source.is_held(files.aaa)
    centre.state.set_focused_slide("bbb")
    assert centre.tabs.active is centre.tabs.slide_tab
    assert not centre.source.is_held(files.aaa) and centre.source.file_for(files.aaa) is None


def test_closing_a_tab_of_the_file_the_slide_tab_shows_asks_nothing_and_keeps_the_edits(centre, files, monkeypatch):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    monkeypatch.setattr(centre, "_ask_save", lambda name: pytest.fail("the slide tab still shows the edits"))
    centre.state.set_mode("source")
    centre.open_file(files.aaa, tab=True)
    file = centre.source.current
    file.editor.insertPlainText("% kept" + chr(10))
    assert centre.close_tab(centre.tabs.active)
    assert centre.tabs.active is centre.tabs.slide_tab and centre.source.current is file
    assert "% kept" in file.editor.text() and file.dirty


def test_the_chip_of_edits_elsewhere_selects_the_tab_of_a_slide_that_has_one(centre, files):
    centre.open_file(files.ccc, tab=True)
    tab = centre.tabs.active
    centre.tabs.activate(centre.tabs.slide_tab)
    focused = centre.state.focused_slide
    centre.source.file_requested.emit(files.ccc)
    assert centre.tabs.active is tab and centre.state.focused_slide == focused


@pytest.mark.parametrize("answer, kept, on_disk", [
    ("save", False, True), ("discard", False, False), (None, True, False)])
def test_closing_a_tab_with_edits_that_were_not_saved_asks_save_discard_or_cancel(
        centre, files, monkeypatch, answer, kept, on_disk):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    centre.open_file(files.deck)
    tab = centre.tabs.active
    centre.source.current.editor.insertPlainText("% mine\n")
    asked = []
    monkeypatch.setattr(centre, "_ask_save", lambda name: asked.append(name) or answer)
    assert centre.close_tab(tab) is not kept
    assert asked == ["course.tex"] and (centre.tabs.tab_for(files.deck) is tab) is kept
    assert ("% mine" in files.deck.read_text(encoding="utf-8")) is on_disk
    assert (centre.source.file_for(files.deck) is not None) is kept
    if kept:
        assert centre.path == files.deck and centre.state.mode == "source"
    else:
        assert centre.path == files.aaa


def test_closing_returns_to_the_most_recently_used_tab_in_the_mode_it_was_shown_in(centre, files):
    state = centre.state
    state.set_mode("split")
    centre.open_file(files.deck)
    centre.open_file(files.bib)
    deck_tab, bib_tab = centre.tabs.tab_for(files.deck), centre.tabs.tab_for(files.bib)
    centre.tabs.activate(deck_tab)                                          # used last: deck, bib, slide
    centre.close_tab(deck_tab)
    assert centre.tabs.active is bib_tab and centre.path == files.bib and state.mode == "source"
    centre.close_tab(bib_tab)
    assert centre.tabs.active is centre.tabs.slide_tab and state.mode == "split" and centre.path == files.aaa


def test_a_file_changed_on_disk_in_the_background_is_read_when_its_tab_comes_back_unless_it_has_edits(centre, files):
    centre.open_file(files.bib)
    bib_file = centre.source.current
    centre.show_slide_tab()
    files.bib.write_text("@book{a, title={Changed}}\n", encoding="utf-8")
    centre.tabs.activate(centre.tabs.tab_for(files.bib))
    assert "Changed" in centre.source.current.editor.text() and centre.source.current is bib_file
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    centre.source.current.editor.insertPlainText("% mine\n")
    centre.show_slide_tab()
    files.bib.write_text("@book{a, title={Elsewhere}}\n", encoding="utf-8")
    centre.tabs.activate(centre.tabs.tab_for(files.bib))
    file = centre.source.current
    assert file.dirty and "% mine" in file.editor.text()                # coming back never reloads over edits
    assert not file.write_now(force=True) and file.conflicted           # the save finds the change: the notice asks
    assert "Elsewhere" in files.bib.read_text(encoding="utf-8")


def test_the_save_hook_of_a_deck_source_survives_switching_tabs(centre, files):
    before = files.deck.read_bytes().decode()
    seen = []
    centre.open_file(files.deck, seen.append)
    file = centre.source.current
    centre.show_slide_tab()
    centre.open_file(files.bib)
    centre.open_file(files.deck)                                       # shown again without a hook
    file.editor.insertPlainText("% hand edit\n")
    assert file.write_now() and seen == [(before, files.deck.read_bytes().decode())]
    later = []
    centre.open_file(files.deck, later.append)                         # a newer hook replaces it
    file.editor.insertPlainText("% another\n")
    assert file.write_now() and len(later) == 1 and len(seen) == 1


def test_a_file_that_is_no_slide_has_the_source_view_alone_and_stays_open_when_another_slide_is_focused(centre, files, monkeypatch):
    state = centre.state
    only = []
    centre.source_only_changed.connect(only.append)
    rendered = []
    monkeypatch.setattr(centre.preview, "render_buffer", lambda: rendered.append(True))
    centre.open_file(files.deck)
    assert centre.source_only and only == [True]
    for mode in ("preview", "split", "details"):
        state.set_mode(mode)
        assert state.mode == "source" and centre.source.isVisibleTo(centre) and not centre.preview.isVisibleTo(centre)
    centre.render_buffer()
    assert rendered == []
    assert not centre.source.current.is_slide and centre.source.file_for(files.deck) is not None
    state.set_focused_slide("ccc")                      # the slide tab comes back, in the mode it had; the deck's tab stays
    assert centre.path == files.ccc and state.mode == "preview" and centre.tabs.active is centre.tabs.slide_tab
    assert only == [True, False] and not centre.source_only and centre.tabs.tab_for(files.deck) is not None
    centre.render_buffer()
    assert rendered == [True]


def test_a_tab_whose_file_is_gone_is_closed_without_asking(centre, files, monkeypatch):
    monkeypatch.setattr(centre, "_ask_save", lambda _name: pytest.fail("asked"))
    centre.open_file(files.deck)
    centre.open_file(files.bib)
    centre.open_file(files.ccc, tab=True)
    files.bib.unlink()
    files.ccc.unlink()
    centre.refresh()
    assert centre.tabs.tab_for(files.bib) is None and centre.tabs.tab_for(files.ccc) is None
    assert centre.tabs.active.path == files.deck
    files.deck.unlink()
    centre.refresh()
    assert centre.tabs.active is centre.tabs.slide_tab and centre.path == files.aaa


def test_another_deck_gets_a_working_tab_of_its_own_and_the_first_decks_tabs_stay(centre, files, deck):
    from dataclasses import replace
    centre.open_file(files.deck)
    first = centre.tabs.slide_tab
    other = replace(deck, name="other", path=deck.path.with_name("other.tex"))
    centre.app.decks = [deck, other]
    centre.state.set_deck(other)                                    # O1: opened from anywhere, its working tab is shown
    second = centre.tabs.working_tab(other.path)
    assert centre.tabs.active is second and centre.tabs.working_tabs == [first, second]
    assert centre.tabs.tab_for(files.deck) is not None and centre.source.file_for(files.deck) is not None
    assert [t.context for t in centre.tabs.tabs] == [deck.path, deck.path, other.path]   # a deck's tabs stay together
    assert centre.path is None and centre.tabs.slide_tab.closable and second.closable
    centre.tabs.activate(first)                                     # back to the first deck: it is the one on show again
    assert centre.state.deck.path == deck.path


def test_the_slide_tab_is_named_after_the_slide_and_follows_the_focus(centre, files):
    first = centre.tab_strip.tab_buttons()[0]
    centre.state.set_focused_slide("ccc")
    assert "Dritte" in first.label.full_text()
    centre.state.set_focused_slide(None)
    assert first.label.full_text() == "course"          # no slide chosen: the deck's name


def test_showing_a_file_tab_and_coming_back_is_not_leaving_the_slide(centre, files, asked):
    ask_on_leave(centre)
    centre.state.set_mode("source")
    centre.source.current.editor.insertPlainText("edit ")
    centre.open_file(files.deck)
    centre.show_slide_tab()
    QApplication.processEvents()
    assert asked.calls == []                                   # only a change of the slide asks
    centre.state.set_focused_slide("ccc")
    QApplication.processEvents()
    assert asked.calls == [("aaa", (1, 1, 0))]


def test_unsaved_edits_of_a_tab_out_of_view_are_counted_and_its_tab_is_shown_for_them(centre, files):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    centre.open_file(files.bib)
    centre.source.current.editor.insertPlainText("% mine\n")
    centre.show_slide_tab()
    centre.open_file(files.deck)
    assert centre.state.dirty and [f.path for f in centre.source.blocked_files()] == [files.bib]
    centre.source._show_other_dirty()                          # the "1 more not saved" chip
    assert centre.path == files.bib
    centre.source.current.write_now(explicit=True)
    assert not centre.state.dirty


def test_ctrl_tab_cycles_in_most_recently_used_order_and_ctrl_pgdown_in_strip_order(centre, files):
    centre.open_file(files.deck)
    centre.open_file(files.bib)                              # bib, deck, slide
    slide, deck_tab, bib_tab = centre.tabs.slide_tab, centre.tabs.tab_for(files.deck), centre.tabs.tab_for(files.bib)
    centre.cycle_tabs(1)
    assert centre.tabs.active is deck_tab and centre.path == files.deck
    centre.cycle_tabs(1)
    assert centre.tabs.active is slide and centre.state.mode == "preview"
    centre.cycle_tabs(-1)
    assert centre.tabs.active is deck_tab
    centre.end_tab_cycle()
    assert centre.tabs.mru[0] is deck_tab
    centre.cycle_tabs(1)
    centre.end_tab_cycle()
    assert centre.tabs.active is bib_tab
    centre.step_tab(1)                                       # Ctrl+PgDown and PgUp: strip order, wrapping
    assert centre.tabs.active is slide and centre.state.mode == "preview"      # past the end of the strip
    centre.step_tab(-1)
    assert centre.tabs.active is bib_tab                                       # past the start
    centre.step_tab(-1)
    assert centre.tabs.active is deck_tab


def _row_key(centre, slide_id):
    return deck_outline.slide_row(centre.state.project, centre.state.deck, slide_id, centre.state.view,
                                  centre.state.language).key


def test_a_slide_opened_in_a_tab_is_a_tab_of_its_own_and_the_focus_stays(centre, files, project):
    state = centre.state
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    tab = centre.tabs.active
    assert tab.kind == "file" and tab.slide and not tab.source_only and not centre.source_only
    assert centre.path == files.ccc and state.focused_slide == "aaa"          # the focused slide stays
    assert centre.tabs.slide_tab.path is None and centre._slide_path == files.aaa
    button = centre.tab_strip.tab_buttons()[1]
    assert button.label.full_text() == "ccc · Dritte" and button.label.toolTip() == str(files.ccc)
    assert state.mode == "preview"                                           # the mode of the tab it came from
    centre.open_file(files.ccc, tab=True)
    assert len(centre.tabs.tabs) == 2                                        # never doubled
    centre.open_file(files.ccc, line=1, tab=True)
    assert state.mode == "source" and tab.mode == "source"                   # a line to go to needs the Source view


def test_a_hit_in_a_file_that_has_a_tab_selects_it_and_goes_to_the_line(centre, files):
    centre.open_file(files.ccc, tab=True)
    centre.show_slide_tab()
    centre.state.set_mode("details")
    centre.open_file(files.ccc, line=3, tab=True)
    assert centre.tabs.active.path == files.ccc and len(centre.tabs.tabs) == 2
    assert centre.state.mode == "source" and centre.source.current.editor.textCursor().blockNumber() == 2
    files.bib.write_text("@book{a, title={A}}\n@book{b, title={B}}\n@book{c, title={C}}\n", encoding="utf-8")
    centre.open_file(files.bib)
    centre.show_slide_tab()
    centre.open_file(files.bib, line=2)
    assert centre.tabs.active.path == files.bib and len(centre.tabs.tabs) == 3
    assert centre.source.current.editor.textCursor().blockNumber() == 1


def test_two_slide_tabs_preview_each_their_own_slide_as_the_deck_calls_it_or_alone(centre, files, project):
    state = centre.state
    frozen = project / "bbb-EN-Two-v1-0-0.tex"
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    centre.open_file(frozen, tab=True)
    assert state.mode == "source"                                            # a frozen version starts in the Source view
    state.set_mode("preview")
    target, row, _title, _language = centre._preview_context()
    assert centre.preview.target_path == frozen and row is None and target.source_path == frozen      # alone
    centre.tabs.activate(centre.tabs.tab_for(files.ccc))
    assert centre.preview.target_path == files.ccc
    _target, row, title, _language = centre._preview_context()
    assert row is not None and row.call.id == "ccc" and title                  # as the deck calls it
    centre.tabs.activate(centre.tabs.slide_tab)
    assert centre.preview.target_path == files.aaa and state.focused_slide == "aaa"
    centre.tabs.activate(centre.tabs.tab_for(frozen))
    assert centre.preview.target_path == frozen
    assert [b.label.full_text() for b in centre.tab_strip.tab_buttons()[1:]] == ["ccc · Dritte", "bbb v1.0.0"]


def test_a_slide_tab_previews_the_occurrence_it_was_opened_from_and_alone_when_the_deck_stops_using_it(centre, files, deck):
    from dataclasses import replace
    twice = DECK.replace("\\end{document}", "\\slide{ccc-DE-Drei}\n\\end{document}")
    centre.state.set_deck(replace(deck, text=twice, chapters=parse_chapters(twice)))
    rows = [r for r in deck_outline.outline_rows(centre.state.project, centre.state.deck, centre.state.view,
                                                  centre.state.language) if r.call.id == "ccc"]
    assert len(rows) == 2 and rows[0].key != rows[1].key
    centre.open_file(files.ccc, tab=True, occurrence=rows[1].key)
    assert centre._shown_row().key == rows[1].key and centre.shown_slide == ("ccc", rows[1].key)
    text = DECK.replace("\\conditionalslide[instructor]{ccc-DE-Drei}\n", "")
    centre.state.set_deck(replace(deck, text=text, chapters=parse_chapters(text)))
    assert centre.tabs.tab_for(files.ccc) in centre.tabs.tabs               # the tab stays
    centre.tabs.activate(centre.tabs.tab_for(files.ccc))
    target, row, _title, _language = centre._preview_context()
    assert row is None and target.source_path == files.ccc and centre.preview.target_path == files.ccc
    assert centre.shown_slide == ("ccc", None)


def test_each_slide_tab_remembers_its_mode_and_showing_it_does_not_focus_its_slide(centre, files):
    state = centre.state
    focused = []
    state.focused_slide_changed.connect(focused.append)
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    state.set_mode("split")
    assert centre.preview.isVisibleTo(centre) and centre.source.isVisibleTo(centre)
    state.set_mode("details")
    assert centre.details._id_slug == "ccc-DE-Drei" and state.focused_slide == "aaa"     # Details follows the tab
    centre.tabs.activate(centre.tabs.slide_tab)
    assert state.mode == "preview" and centre.preview.target_path == files.aaa
    centre.tabs.activate(centre.tabs.tab_for(files.ccc))
    assert state.mode == "details" and focused == [] and state.focused_slide == "aaa"
    state.set_focused_slide("bbb")                                           # a click in the slide list
    assert centre.tabs.active is centre.tabs.slide_tab and centre.tabs.tab_for(files.ccc) is not None
    centre.tabs.activate(centre.tabs.tab_for(files.ccc))
    bbb = files.aaa.parent / "bbb-EN-Two-current.tex"
    centre.open_file(bbb, keep_mode=True)                                    # the click's release: the slide tab
    assert centre.tabs.active is centre.tabs.slide_tab and centre.path == bbb
    assert centre.tabs.tab_for(files.ccc) is not None


def test_the_neighbours_and_the_wheel_are_those_of_the_slide_on_show_and_do_not_move_the_focus_from_a_slide_tab(centre, files):
    state = centre.state
    on_slide_tab = [row.call.id for _target, row in centre._neighbour_targets()]
    assert on_slide_tab[0] == "bbb"                                          # after aaa
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    tab = centre.tabs.active
    shown = [row.call.id for _target, row in centre._neighbour_targets()]
    assert shown[0] == "bbb" and "aaa" in shown and shown != on_slide_tab    # before ccc, then aaa
    centre._go_adjacent(-1)
    centre._go_adjacent(1)
    assert centre.tabs.active is tab and state.focused_slide == "aaa"
    frozen = files.aaa.parent / "bbb-EN-Two-v1-0-0.tex"
    centre.open_file(frozen, tab=True)
    assert centre._neighbour_targets() == []                                 # alone: no deck neighbours
    centre.tabs.activate(centre.tabs.slide_tab)
    centre._go_adjacent(1)                                                   # the slide tab does move the focus
    assert state.focused_slide == "bbb"


def test_the_language_chip_of_a_slide_tab_opens_the_partner_in_a_tab_of_its_own(centre, files, project):
    partner = project / "ccc-EN-Three-current.tex"
    partner.write_text(FRAME % "Third", encoding="utf-8")
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    centre.preview.partner_requested.emit(partner)
    assert centre.tabs.active.path == partner and centre.tabs.tab_for(files.ccc) is not None
    assert centre._slide_path == files.aaa and centre.state.focused_slide == "aaa"
    centre.tabs.activate(centre.tabs.slide_tab)
    other = project / "aaa-DE-Eins-current.tex"
    other.write_text(FRAME % "Eins", encoding="utf-8")
    centre.preview.partner_requested.emit(other)                             # the slide tab swaps its file, as before
    assert len(centre.tabs.tabs) == 3 and centre._slide_path == other


def test_the_slide_tab_and_a_file_tab_of_the_same_file_share_one_editor(centre, files):
    centre.state.set_mode("source")
    shared = centre.source.current
    assert shared.path == files.aaa
    shared.editor.insertPlainText("% shared\n")
    centre.open_file(files.aaa, tab=True)
    tab = centre.tabs.active
    assert tab.kind == "file" and centre.source.current is shared and "% shared" in shared.editor.text()
    shared.editor.undo()
    assert "% shared" not in shared.editor.text()                           # the undo history is the same one
    centre.open_file(files.aaa, tab=True)
    assert len(centre.tabs.tabs) == 2
    assert centre.close_tab(tab)
    assert centre.source.file_for(files.aaa) is shared and centre.source.current is shared
    assert centre.source.is_held(files.aaa)                                  # the slide tab's hold remains


def test_a_covering_tab_and_another_tab_of_the_same_path_hold_the_file_twice(centre, files):
    centre.state.set_mode("source")
    shared = centre.source.current
    centre.open_file(files.aaa, tab=True)
    centre.open_file(files.bib)                                              # a file tab covers the slide tab
    tab = centre.tabs.tab_for(files.aaa)
    assert centre.close_tab(tab)
    assert centre.source.file_for(files.aaa) is shared                       # the slide tab still has it
    centre.tabs.activate(centre.tabs.slide_tab)
    assert centre.source.current is shared


def test_closing_a_changed_slide_tab_asks_unless_the_slide_tab_shows_that_file(centre, files, asked):
    ask_on_leave(centre)
    centre.state.set_mode("source")
    centre.open_file(files.aaa, tab=True)                                    # the slide tab shows aaa too
    centre.source.current.editor.insertPlainText("edit ")
    assert centre.close_tab(centre.tabs.active)
    QApplication.processEvents()
    assert asked.calls == []
    centre.open_file(files.aaa, tab=True)
    centre.state.set_focused_slide("bbb")                                    # now aaa is only in the file tab
    QApplication.processEvents()
    assert asked.calls == []                                                 # switching away is not leaving
    centre.tabs.activate(centre.tabs.tab_for(files.aaa))
    centre.source.current.editor.insertPlainText("again ")
    centre.source.current.write_now()
    assert centre.close_tab(centre.tabs.active)
    QApplication.processEvents()
    assert asked.calls == [("aaa", (1, 1, 0))]


def test_a_frozen_version_from_details_gets_a_read_only_tab_and_restoring_shows_the_slide_tab(
        centre, files, project, monkeypatch):
    frozen = project / "bbb-EN-Two-v1-0-0.tex"
    current = project / "bbb-EN-Two-current.tex"
    centre.details.open_requested.emit(frozen)
    tab = centre.tabs.active
    assert tab.slide and tab.path == frozen and centre.state.mode == "source"
    assert centre.source.current.editor.is_read_only() and centre.source._frozen_bar.isVisibleTo(centre)
    assert centre.state.focused_slide == "aaa"
    centre.source._unlock_button.click()                                     # Unlock editing works in the tab
    assert not centre.source.current.editor.is_read_only()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    current.write_text(r"\setSlideVersion{1-1-0}" + "\n" + FRAME % "Second now")
    centre.source.restore_requested.emit(frozen)                             # "Make this the current version"
    assert centre.tabs.active is centre.tabs.slide_tab and centre.path == current
    assert tab in centre.tabs.tabs and centre.tabs.tab_for(frozen) is tab    # the version's tab stays
    other = project / "aaa-DE-Eins-current.tex"                              # the other language from Details: no tab
    other.write_text(FRAME % "Eins", encoding="utf-8")
    count = len(centre.tabs.tabs)
    centre.details.open_requested.emit(other)
    assert len(centre.tabs.tabs) == count and centre.path == other


def test_save_and_render_work_on_a_slide_tab(centre, files, renders):
    state = centre.state
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    state.set_mode("source")
    centre.source.current.editor.insertPlainText("% mine\n")
    assert centre.save() and "% mine" in files.ccc.read_text(encoding="utf-8")
    centre.render_buffer()                                                   # Ctrl+R: source becomes split
    assert state.mode == "split"
    wait_idle(centre)
    assert [c for c in renders if c[0] == "buffer" and c[1] == "ccc-DE-Drei"]
    state.set_mode("preview")
    centre.source.current.editor.insertPlainText("% more\n")                 # the editor is still there, hidden
    assert centre.save() and "% more" in files.ccc.read_text(encoding="utf-8")     # Ctrl+S needs no Source view on show


def test_a_save_in_a_background_tab_renders_only_the_slide_on_show(centre, files, monkeypatch):
    done = []
    monkeypatch.setattr(centre.preview, "render_after_save", lambda: done.append(centre.preview.target_path))
    centre.open_file(files.ccc, tab=True)
    centre._on_saved(files.aaa)                                              # aaa is not on show
    assert done == []
    centre._on_saved(files.ccc)
    assert done == [files.ccc]
    files.aaa.write_text(FRAME % "Changed", encoding="utf-8")
    centre.file_written(files.aaa)                                           # the chat wrote the slide of the slide tab
    assert done == [files.ccc]


def test_the_chat_the_tasks_and_the_panels_act_on_the_slide_file_tab_on_show_and_on_the_focus_elsewhere(centre, files):
    assert centre.tab_slide() is None and centre.shown_slide[0] == "aaa" and not centre.slide_file_shown   # the slide tab
    centre.open_file(files.ccc, tab=True, occurrence=_row_key(centre, "ccc"))
    path, row, deck = centre.tab_slide()
    assert deck is centre.state.deck
    assert path == files.ccc and row is not None and row.call.id_slug == "ccc-DE-Drei"
    assert centre.slide_file_shown and centre.shown_slide == ("ccc", _row_key(centre, "ccc"))
    assert centre.shown_occurrence == _row_key(centre, "ccc")
    centre.open_file(files.bib)
    assert centre.tab_slide() is None and centre.shown_slide[0] == "aaa" and not centre.slide_file_shown   # no slide
    centre.show_slide_tab()
    frozen = files.aaa.with_name("bbb-EN-Two-v1-0-0.tex")
    centre.open_file(frozen, tab=True)
    assert centre.tab_slide() == (frozen, None, centre.state.deck)                               # a frozen version previews alone


def test_save_notes_on_a_slide_file_tab_stays_on_that_tab(centre, files):
    centre.open_file(files.ccc, tab=True)
    tab = centre.tabs.active
    assert centre.edit_slide_text(files.ccc, lambda text: text + "% from a panel\n", show=True)
    assert centre.tabs.active is tab and centre.source.current.path == files.ccc
    assert centre._slide_path == files.aaa                                    # the slide tab keeps its slide
    assert "% from a panel" in centre.source.current.editor.text()
    assert centre.edit_slide_text(files.aaa, lambda text: text + "% other\n", show=True)
    assert centre.tabs.active is centre.tabs.slide_tab                         # another file: the slide tab's, as before


def test_restoring_a_version_from_a_slide_file_tab_shows_that_files_tab(centre, files, project, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    current, frozen = project / "bbb-EN-Two-current.tex", project / "bbb-EN-Two-v1-0-0.tex"
    current.write_text("\\setSlideVersion{1-1-0}\n" + FRAME % "Second now", encoding="utf-8")
    centre.open_file(current, tab=True)
    tab = centre.tabs.active
    centre.open_file(files.bib)
    centre.tabs.activate(tab)
    centre.revise("restore", [frozen])                                             # the Versions panel's Make current
    assert centre.tabs.active is tab and centre.state.focused_slide == "aaa"
    assert "Second then" in current.read_text(encoding="utf-8")


def test_a_renamed_slide_keeps_its_tab_and_its_hold(centre, files, project):
    centre.open_file(files.ccc, tab=True)
    tab = centre.tabs.active
    new = project / "ccc-DE-Vier-current.tex"
    files.ccc.rename(new)
    centre.retarget_slide("ccc-DE-Drei", "ccc-DE-Vier")
    centre.refresh()                                                           # would close a tab whose file is gone
    assert tab in centre.tabs.tabs and centre.tabs.active is tab and tab.path == new and centre.path == new
    assert centre.source.is_held(new) and not centre.source.is_held(files.ccc)
    assert centre.tab_strip.tab_buttons()[1].label.toolTip() == str(new)


def test_rename_in_details_on_a_slide_file_tab_keeps_the_tab(centre, files, project, monkeypatch):
    from slidemage import slide_rename
    from slidemage.ui.workspace import details_view

    frozen = project / "ccc-DE-Drei-v1-0-0.tex"
    frozen.write_text(FRAME % "Dritte damals", encoding="utf-8")

    def rename(_ctx, old, slug, _warnings=None):
        for path in (files.ccc, frozen):
            path.rename(path.with_name(path.name.replace("Drei", slug)))
        return f"ccc-DE-{slug}"

    monkeypatch.setattr(slide_rename, "count_references", lambda _ctx, id_slug: 1)
    monkeypatch.setattr(slide_rename, "rename_slide_slug", rename)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(details_view.QInputDialog, "getText", lambda *a, **k: ("Vier", True))
    centre.open_file(frozen, tab=True)
    frozen_tab = centre.tabs.active
    centre.open_file(files.ccc, tab=True)
    tab = centre.tabs.active
    centre.app.refresh_open_deck_editors = centre.refresh
    centre.state.set_mode("details")
    centre.details._rename()
    assert centre.tabs.tabs == [centre.tabs.slide_tab, frozen_tab, tab] and centre.tabs.active is tab
    assert tab.path == project / "ccc-DE-Vier-current.tex" and frozen_tab.path == project / "ccc-DE-Vier-v1-0-0.tex"
    assert centre.state.focused_slide == "aaa"


def _entry(menu, key):
    return next(e for e in menu._entries if e[0] == "item" and e[1] == key)


def test_the_context_menu_closes_the_other_tabs_or_those_to_the_right(centre, files):
    centre.open_file(files.deck)
    centre.open_file(files.bib)
    deck_tab = centre.tabs.tab_for(files.deck)
    centre.tab_strip.tab_buttons()[1]._menu().triggered.emit("close_others")
    assert centre.tabs.tabs == [centre.tabs.slide_tab, deck_tab] and centre.tabs.active is deck_tab
    centre.open_file(files.bib)
    centre.tab_strip.tab_buttons()[0]._menu().triggered.emit("close_right")
    assert centre.tabs.tabs == [centre.tabs.slide_tab]                  # the slide tab is always first in the strip


def test_reveal_in_explorer_opens_the_folder_of_the_tabs_file_and_reports_a_failure(centre, files, monkeypatch):
    opened, told = [], []
    monkeypatch.setattr(open_path, "open_in_default_app", lambda path: opened.append(path))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    centre.open_file(files.deck)
    buttons = centre.tab_strip.tab_buttons()
    buttons[1]._menu().triggered.emit("reveal")
    buttons[0]._menu().triggered.emit("reveal")                        # the slide tab: the focused slide's folder
    assert opened == [files.deck.parent, files.aaa.parent] and not told
    monkeypatch.setattr(open_path, "open_in_default_app", lambda path: (_ for _ in ()).throw(OSError("nope")))
    buttons[1]._menu().triggered.emit("reveal")
    assert told and "nope" in told[0]


def test_showing_a_file_tab_does_not_clobber_the_decks_remembered_mode(centre, files, deck):
    state = centre.state
    state.set_mode("split")                                     # the slide tab's own mode, remembered for the deck
    centre.open_file(files.ccc, line=2, tab=True)                # a slide file tab opened at a line starts in Source
    assert state.mode == "source" and centre.tabs.active.slide
    assert app_settings.get(state.project, SETTINGS_KEY)[str(deck.path)]["mode"] == "split"
    centre.show_slide_tab()
    assert state.mode == "split"                                 # the slide tab's own mode is unaffected


def _reopened(ctx, deck, monkeypatch):
    """A fresh CentreColumn over the same project, as if the project were opened again."""
    monkeypatch.setattr(render_check, "confirm_render", lambda *a, **k: True)
    app = FakeApp(ctx)
    state = WorkspaceState(ctx)
    other = CentreColumn(app, state)
    app.centre = other
    state.set_deck(deck)
    return other


def test_file_tabs_are_saved_and_restored_per_project_in_their_own_mode(centre, files, ctx, deck, monkeypatch):
    centre.open_file(files.deck)
    centre.open_file(files.ccc, tab=True)
    centre.state.set_mode("preview")                          # the slide file tab's own mode (D2)
    centre.tabs.activate(centre.tabs.tab_for(files.deck))     # the deck source tab is active when the project closes
    centre.save_tabs()
    saved = app_settings.get(ctx, CENTRE_TABS_SETTING)
    deck_rel = deck.path.relative_to(ctx.root).as_posix()
    working = saved["tabs"][0]
    assert {k: working[k] for k in ("kind", "deck", "mode", "color")} == {"kind": "deck", "deck": deck_rel, "mode": centre.tabs.slide_tab.mode, "color": 0}
    saved["tabs"][0] = {"kind": "deck", "deck": deck_rel, "mode": working["mode"]}
    assert saved == {"v": 2, "active": 1,
                     "tabs": [{"kind": "deck", "deck": deck_rel, "mode": centre.tabs.slide_tab.mode},
                              {"kind": "file", "deck": deck_rel, "mode": "source", "path": "course.tex"},
                              {"kind": "file", "deck": deck_rel, "mode": "preview", "path": "slides/ccc-DE-Drei-current.tex"}]}

    reopened = _reopened(ctx, deck, monkeypatch)
    reopened.restore_tabs()
    assert [t.path for t in reopened.tabs.tabs if t.kind == "file"] == [files.deck, files.ccc]
    assert reopened.tabs.tab_for(files.deck).mode == "source"            # a deck source stays Source-only
    assert reopened.tabs.tab_for(files.ccc).mode == "preview"
    assert reopened.tabs.active is reopened.tabs.tab_for(files.deck)


def test_restoring_tabs_skips_a_file_that_no_longer_exists(centre, files, ctx, deck, monkeypatch):
    centre.open_file(files.bib)
    centre.open_file(files.deck)                              # the active tab when the project closes
    centre.save_tabs()
    files.deck.unlink()                                       # gone since this project was last open

    reopened = _reopened(ctx, deck, monkeypatch)
    reopened.restore_tabs()
    assert [t.path for t in reopened.tabs.tabs if t.kind == "file"] == [files.bib]
    assert reopened.tabs.active is reopened.tabs.slide_tab    # the remembered active tab's file was gone too


def test_a_frozen_tabs_details_show_the_frozen_file_with_its_chip_and_no_changing_actions(centre, project):
    from PySide6.QtWidgets import QLabel

    from slidemage.ui.kit.widgets import Button, Chip
    frozen, current = project / "bbb-EN-Two-v1-0-0.tex", project / "bbb-EN-Two-current.tex"
    current.write_text("\\setSlideVersion{1-0-1}\n" + FRAME % "Second now", encoding="utf-8")
    details = centre.details

    def facts():
        texts = [label.text() for label in details.findChildren(QLabel)]
        buttons = [b.text() for b in details.findChildren(Button)]
        return texts, buttons, [c.text() for c in details.findChildren(Chip)]

    centre.open_file(current, tab=True)                                       # the live slide's own Details
    centre.state.set_mode("details")
    texts, buttons, chips = facts()
    assert "bbb-EN-Two-current.tex" in texts and "v1.0.1" in texts and chips == []
    assert {"Rename…", "Duplicate slide…", "Delete slide…"} <= set(buttons)
    centre.open_file(frozen, tab=True)                                        # the frozen version's
    centre.state.set_mode("details")
    texts, buttons, chips = facts()
    assert "bbb-EN-Two-v1-0-0.tex" in texts and "v1.0.0" in texts and "v1.0.1" not in texts
    assert "EN" in texts and "Two" in texts and chips == ["Frozen v1.0.0"]
    assert "Current" in texts and "bbb-EN-Two-current.tex" in texts          # the live version is one to open
    assert not {"Rename…", "Duplicate slide…", "Delete slide…"} & set(buttons) and "Open" in buttons
    centre.details.open_requested.emit(current)                               # opening the live one: the slide's tab
    assert centre.path == current and centre.tabs.tab_for(frozen) is not None    # the frozen tab stays


def test_a_file_that_is_no_slide_and_no_deck_has_no_context_and_the_list_shows_a_placeholder(centre, files):
    seen = []
    centre.context_changed.connect(seen.append)
    centre.open_file(files.bib)
    bib = centre.tabs.tab_for(files.bib)
    assert bib.context is None
    assert centre.tab_deck(bib) is None
    placeholder = centre.list_placeholder()
    assert "SlideMage.bib" in placeholder.text and placeholder.back == "Back to course"
    assert seen[-1] is bib
    centre.open_file(files.deck)                                # a deck's source belongs to its deck (O7)
    assert centre.tabs.tab_for(files.deck).context == centre.state.deck.path and centre.list_placeholder() is None
    centre.open_file(files.ccc, tab=True)                       # so does a slide
    assert centre.tabs.tab_for(files.ccc).context == centre.state.deck.path and centre.list_placeholder() is None
    centre.show_slide_tab()
    assert centre.list_placeholder() is None


def _other_deck(centre, tmp_path, name, body):
    text = DECK.replace("\\slide{aaa-EN-One}", body)
    return Deck(name=name, path=tmp_path / f"{name}.tex", archived=False, text=text, supports_version=True,
                uses_biblatex=False, preamble_end=text.index("\\begin{document}") + len("\\begin{document}"),
                chapters=parse_chapters(text), output_folders={})


def test_a_slide_outside_the_deck_has_no_context_its_placeholder_offers_the_decks_that_use_it_and_open_in_deck_adopts_one(
        centre, files, project, tmp_path):
    ddd = project / "ddd-EN-Four-current.tex"
    ddd.write_text(FRAME % "Four", encoding="utf-8")
    other = _other_deck(centre, tmp_path, "lecture", "\\slide{ddd-EN-Four}")
    other.path.write_text(other.text, encoding="utf-8")
    centre.app.decks = [centre.state.deck, other]
    centre.open_file(files.ccc, tab=True)                    # the deck uses it
    assert centre.tabs.tab_for(files.ccc).context == centre.state.deck.path and centre.list_placeholder() is None
    centre.open_file(ddd, tab=True)                          # it does not
    tab = centre.tabs.tab_for(ddd)
    assert tab.context is None and centre.tab_slide()[2] is None
    placeholder = centre.list_placeholder()
    assert "ddd" in placeholder.text and "not in an open deck" in placeholder.text
    assert [d.name for d in placeholder.decks] == ["lecture"] and placeholder.note == ""
    centre.app.decks = [centre.state.deck]
    assert centre.list_placeholder().note == "No deck uses this slide yet."
    centre.open_file(files.bib)                              # a frozen version has its opener's context
    frozen = files.aaa.with_name("bbb-EN-Two-v1-0-0.tex")
    centre.open_file(frozen, tab=True)
    assert centre.tabs.tab_for(frozen).context is None
    centre.app.decks = [centre.state.deck, other]            # "Open in deck": the tab gets that deck and stays
    centre.tabs.activate(tab)
    seen = []
    centre.context_changed.connect(seen.append)
    centre.adopt_deck(other)
    assert centre.state.deck.path == other.path
    assert tab.context == other.path and centre.tabs.active is tab           # the tab stays on show, with its file
    assert centre.tab_deck(tab) is centre.state.deck and centre.list_placeholder() is None
    assert seen and seen[-1] is tab
    assert centre.tab_slide()[1] is not None                                 # it previews as the deck calls the slide


def test_a_bib_tab_and_a_slide_tab_with_no_deck_are_restored_with_none(centre, files, project, ctx, deck, monkeypatch):
    ddd = project / "ddd-EN-Four-current.tex"
    ddd.write_text(FRAME % "Four", encoding="utf-8")
    centre.open_file(files.bib)
    centre.open_file(ddd, tab=True)
    centre.save_tabs()
    assert app_settings.get(ctx, CENTRE_TABS_SETTING)["tabs"][1]["deck"] is None
    reopened = _reopened(ctx, deck, monkeypatch)
    reopened.restore_tabs()
    assert reopened.tabs.tab_for(files.bib).context is None and reopened.tabs.tab_for(ddd).context is None

