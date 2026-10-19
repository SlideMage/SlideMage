# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The citation of an image in both views, the Images page's form and the side panel's Image descriptions:
the same field and review state, one store, each showing what the other saved when it is next shown."""
from __future__ import annotations

import pytest
from conftest import build_window

from slidemage import alt_blocks, alt_images, image_review
from slidemage.alt_images import SOURCE_REVIEWED, SOURCE_TO_REVIEW, ImageEntry
from slidemage.project import ProjectContext
from slidemage.ui.pages import image_form

IMG = "media/pic.png"
SLIDE = "slides/abc-EN-Hello-current.tex"


def stored(ctx) -> ImageEntry:
    return alt_images.load_store(ctx)[IMG]


@pytest.fixture
def window(root, qapp, monkeypatch):
    """The window over the throwaway project, on the slide abc that shows media/pic.png, with a stored citation."""
    ctx = ProjectContext.at(root)
    path = root / SLIDE
    path.write_bytes(path.read_bytes().replace(b"\\item First point", b"\\includegraphics{media/pic.png}"))
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, _reference: None)
    alt_images.update_store(ctx, lambda entries: entries.update({IMG: ImageEntry(
        image=IMG, short="s", long="l", source="Own illustration", source_de="Eigene Grafik")}) or True)
    window = build_window(monkeypatch, ctx)
    window.state.set_deck(next(d for d in window.decks if d.name == "test"))
    window.state.set_focused_slide("abc")
    window.side_panels.set_panel("images")
    return window


def panel_form(window):
    return window.side_panels.panels["images"]._forms[0]


def page_form(window):
    return window.images_page._forms[0]


def open_images(window):
    window.stack.setCurrentWidget(window.images_page)
    window.images_page.show_slide("abc")


def test_the_page_form_shows_the_citation_state_and_marks_it_reviewed(window):
    open_images(window)
    form = page_form(window)
    statuses = form._source_status
    assert len(statuses) == 2                                        # under the English and the German field
    assert [s.chip.text() for s in statuses] == ["Reviewed", "Reviewed"] and not any(s.button.isVisible() for s in statuses)
    form.fields["source_de"].setPlainText("Foto: Smith")
    assert [s.chip.text() for s in statuses] == ["To review", "To review"]
    assert not any(s.button.isEnabled() for s in statuses)           # save the change first
    window.images_page._save(reviewed=False)
    ctx = window.project
    assert (stored(ctx).source_de, stored(ctx).source_status) == ("Foto: Smith", SOURCE_TO_REVIEW)
    form = page_form(window)
    assert all(s.button.isEnabled() for s in form._source_status)
    form._source_status[0].button.click()
    assert stored(ctx).source_status == SOURCE_REVIEWED
    assert [s.chip.text() for s in form._source_status] == ["Reviewed", "Reviewed"]
    assert stored(ctx).status == alt_images.STATUS_AUTO              # the description was not marked reviewed


def test_the_page_form_uses_the_same_field_as_the_panel(window):
    open_images(window)
    form = page_form(window)
    for key in ("source", "source_de"):
        spec = image_form.SOURCE_SPECS[key]
        field = form.fields[key].parentWidget()
        assert (field.label.text(), form.fields[key].placeholderText()) == (spec[1], spec[4])
    assert panel_form(window).source_edit.parentWidget().label.text() == image_form.SOURCE_SPECS["source"][1]


def test_a_citation_saved_in_the_panel_shows_on_the_page_and_back(window):
    ctx = window.project
    panel_form(window).source_edit.setPlainText("Photo: Smith")      # pending in the panel, not saved
    open_images(window)                                              # opening the page saves it first
    assert (stored(ctx).source, stored(ctx).source_status) == ("Photo: Smith", SOURCE_TO_REVIEW)
    form = page_form(window)
    assert form.fields["source"].toPlainText() == "Photo: Smith"
    assert form._source_status[0].chip.text() == "To review"
    form._source_status[0].button.click()
    form.fields["source"].setPlainText("Photo: Smith, CC BY")         # saved when the page is left
    window.stack.setCurrentWidget(window.centre)
    assert (stored(ctx).source, stored(ctx).source_status) == ("Photo: Smith, CC BY", SOURCE_TO_REVIEW)
    shown = panel_form(window)
    assert shown.source_edit.toPlainText() == "Photo: Smith, CC BY" and shown.source_status.chip.text() == "To review"
    shown.source_status.button.click()
    open_images(window)
    form = page_form(window)
    assert [s.chip.text() for s in form._source_status] == ["Reviewed", "Reviewed"]


def test_the_page_keeps_an_unsaved_edit_when_the_panel_saved_another_citation(window):
    ctx = window.project
    open_images(window)
    form = page_form(window)
    form.fields["source"].setPlainText("Typed on the page")
    alt_images.save_source(ctx, IMG, source_de="Elsewhere")          # another writer, meanwhile
    window.images_page.ensure_loaded()                               # shown again: reads the store
    form = page_form(window)
    assert form.fields["source"].toPlainText() == "Typed on the page" and window.images_page.dirty
    window.images_page._save(reviewed=False)
    entry = stored(ctx)
    assert (entry.source, entry.source_de, entry.source_status) == ("Typed on the page", "Elsewhere", SOURCE_TO_REVIEW)


def test_a_citation_changed_by_an_agent_shows_to_review_in_both_views(window):
    ctx = window.project
    alt_images.save_source(ctx, IMG, source="Changed by an agent")   # what every non-user writer ends in
    open_images(window)
    assert [s.chip.text() for s in page_form(window)._source_status] == ["To review", "To review"]
    window.stack.setCurrentWidget(window.centre)
    assert panel_form(window).source_status.chip.text() == "To review"


def test_source_to_review_does_not_change_the_slides_review_state(window):
    ctx = window.project
    open_images(window)
    page = window.images_page
    before = page._current.state
    alt_images.save_source(ctx, IMG, source="Changed")
    page.ensure_loaded()
    assert page._current.state == before
    labels = [label for label, _ in image_review.FILTERS]
    assert page.nav._counts[labels.index("Source to review")] == 1
