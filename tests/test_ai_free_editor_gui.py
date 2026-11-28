# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The editor's manual workflows remain usable without an AI plugin."""
from slidemage import alt_blocks, alt_images, deck_editor, deck_scan
from slidemage.ui.dialogs.add_slide import AddSlideSheet
from conftest import build_window, make_project, wait_until
from slidemage.project import ProjectContext


def test_without_ai_the_editor_saves_source_descriptions_and_manual_translations(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    slide = ctx.slides_dir / "abc-EN-Hello-current.tex"
    row = alt_blocks.SlideRow(slide, "abc", "Hello", ["media/pic.png"])
    monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda _ctx: [row])
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, _ref: None)
    monkeypatch.setattr(alt_images, "sync_store", lambda _ctx: alt_images.SyncReport())
    window = build_window(monkeypatch, ctx)
    window.show()
    window.open_slide_editor(slide)
    source = window.centre.source.current
    assert source.ask_ai_button.isHidden()
    source.editor.insertPlainText("% manual edit\n")
    assert source.write_now() and "% manual edit" in slide.read_text()
    window._toggle_images()
    page = window.images_page
    page.ensure_loaded()
    qapp.processEvents()
    assert page.draft_button.isHidden() and page.translate_all_button.isHidden()
    form = page._forms[0]
    assert form.translate_button.isHidden() and form.save_translate_button.isHidden()
    form.fields["short"].setPlainText("A hand-written description")
    form.fields["short_tr"].setPlainText("Eine Beschreibung")
    assert page._save(reviewed=False)
    saved = alt_images.load_store(ctx)["media/pic.png"]
    assert saved.short == "A hand-written description"
    assert saved.short_de == "Eine Beschreibung"

    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "test")
    position, indent = deck_editor.append_position(deck)
    sheet = AddSlideSheet(window, deck, position, indent, where="at the end", is_dirty=window.centre.unsaved,
                          source="translate", slide="abc-EN-Hello", target="DE")
    sheet.show()
    wait_until(lambda: sheet.picked() == "abc-EN-Hello")
    assert sheet.machine.isHidden() and not sheet.wants_translation()
    sheet.ok.click()
    created, = ctx.slides_dir.glob("*-DE-Hello-current.tex")
    assert "Translation of: abc-EN-Hello" in created.read_text() and "First point" in created.read_text()
    assert created.name[:3] in deck.path.read_text()
    sheet.close()
