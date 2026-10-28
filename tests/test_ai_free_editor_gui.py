# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The editor's manual workflows remain usable without an AI plugin."""
from slidemage import alt_blocks, alt_images, deck_editor, deck_scan
from slidemage.ai import routes
from slidemage.ui.dialogs.add_slide import AddSlideSheet
from conftest import build_window, make_project
from slidemage.project import ProjectContext


def test_no_routes_still_allows_a_linked_manual_translation(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    window = build_window(monkeypatch, ctx)
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "test")
    position, indent = deck_editor.append_position(deck)
    sheet = AddSlideSheet(window, deck, position, indent, where="at the end", is_dirty=window.centre.unsaved,
                          source="translate", slide="abc-EN-Hello", target="DE")
    sheet.show()
    qapp.processEvents()
    assert not routes.all() and sheet.machine.isHidden() and not sheet.wants_translation()
    sheet.ok.click()
    created = next(ctx.slides_dir.glob("*-DE-Hello-current.tex"))
    assert "Translation of: abc-EN-Hello" in created.read_text()
    assert "First point" in created.read_text()
    assert created.name[:3] in deck.path.read_text()
    sheet.close()


def test_no_routes_hides_ai_controls_but_keeps_image_fields(qapp, tmp_path, monkeypatch):
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
    assert all(not command.visible(window) for command in window.commands
               if command.id.startswith(("ai:", "task:", "selection:")))
    window._toggle_images()
    page = window.images_page
    page.ensure_loaded()
    qapp.processEvents()
    assert window.assistant.isHidden() and window.commands["images"].visible(window)
    assert not next(a for a in window.menuBar().actions() if a.text().replace("&", "") == "AI").isVisible()
    assert all(widget.isHidden() for widget in (page.draft_field, page.translate_field, page.draft_note,
                                                page.translate_note, page.draft_button, page.draft_all_button,
                                                page.translate_all_button))
    form = page._forms[0]
    assert form.translate_button.isHidden() and form.save_translate_button.isHidden()
    form.fields["short"].setPlainText("A hand-written description")
    form.fields["short_de"].setPlainText("Eine Beschreibung")
    assert page._save(reviewed=False)
    saved = alt_images.load_store(ctx)["media/pic.png"]
    assert saved.short == "A hand-written description"
    assert saved.short_de == "Eine Beschreibung"


def test_settings_opens_without_an_ai_tab(qapp, tmp_path, monkeypatch):
    from slidemage.ui.dialogs.settings import AI, PLUGINS, SettingsSheet

    ctx = ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    window = build_window(monkeypatch, ctx)
    sheet = SettingsSheet(window, tab=PLUGINS)
    assert sheet.ai is None and sheet.current_tab() == PLUGINS
    assert "AI" not in [sheet._tabs.tabText(i) for i in range(sheet._tabs.count())]
    sheet.set_current_tab(AI)
    assert sheet.current_tab() != AI
    sheet.close()
