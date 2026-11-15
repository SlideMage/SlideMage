# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library grid's grouping and persistent pool switch."""
import json
from threading import get_ident
from types import SimpleNamespace

from PySide6.QtCore import Qt

from slidemage import bundled_copies, deck_language, deck_scan, library_data
from slidemage.project import ProjectContext
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import RowButton
from slidemage.ui.pages.library.page import LibraryPage
from slidemage.ui.pages.library.slides import SlideModel, prepare_groups
from slidemage.ui.workspace.state import WorkspaceState


def test_model_groups_translations_and_excludes_manual_and_test(qapp, tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    for slug, text in (("abc-EN-Original", "%% DE translation: def-DE-Partner\n"),
                       ("def-DE-Partner", "%% Translation of: abc-EN-Original\n"),
                       ("ghi-EN-Other", ""), ("man-EN-Manual", ""), ("ZZ1-EN-Test", "")):
        (ctx.slides_dir / f"{slug}-current.tex").write_text(
            text + "\\begin{standardframe}{A title}\nBody\n\\end{standardframe}", encoding="utf-8")
    bundled_copies.write_manifest(ctx.root, {"manual": {"files": {"slides/man-EN-Manual-current.tex": "hash"}}})

    model = SlideModel()
    model.set_groups(prepare_groups(ctx, {}, {}, "EN"), library_data.LibraryData())

    assert model.rowCount() == 2
    rows = [model.index(n).data(Qt.ItemDataRole.UserRole) for n in range(model.rowCount())]
    assert {r.id for r in rows} == {"abc", "ghi"}
    assert next(r for r in rows if r.id == "abc").members == ["abc-EN-Original", "def-DE-Partner"]
    assert all(r.blocks == [] for r in rows)
    model.filter(query="DEF title")  # Palette matching: all words, across title and member IDs.
    assert model.rowCount() == 1
    assert model.index(0).data(Qt.ItemDataRole.UserRole).id == "abc"


def test_pool_switch_writes_library(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    (ctx.slides_dir / "abc-EN-Demo-current.tex").write_text(
        "\\begin{standardframe}{Demo}\nBody\n\\end{standardframe}", encoding="utf-8")
    ctx.blocks_dir.mkdir()
    (ctx.blocks_dir / "Topic.tex").write_text("%% Topics: Research\n\\slide{missing-Slide}\n")
    library_data.update(ctx, lambda data: data.topics.update({"abc": {"Research"}}))
    app = SimpleNamespace(project=ctx, theme=ThemeManager(dark=False), state=WorkspaceState(ctx),
                          background=SimpleNamespace(renderer=None))
    page = LibraryPage(app)
    page.resize(1280, 900)
    page.show()
    gui_thread = get_ident()
    update = library_data.update

    def worker_write(*args):
        assert get_ident() != gui_thread
        return update(*args)

    monkeypatch.setattr(library_data, "update", worker_write)
    try:
        page.ensure_loaded()
        first_scan = page._scan
        page.ensure_loaded()
        page.ensure_loaded()
        assert page._scan is first_scan  # Rapid refreshes keep one active worker.
        assert first_scan.wait(5000)
        qapp.processEvents()
        assert page._scan is not first_scan
        assert page._scan.wait(5000)
        qapp.processEvents()
        assert not page.block_rows["Topic"].isHidden()
        assert not page.topic_rows["Research"].isHidden()
        page.rows["all"].clicked.emit()
        view = page.slides_view
        view.grid.setCurrentIndex(view.model.index(0))
        detail = view._detail
        view._show_details(view.model.index(0))
        assert view._detail is detail
        assert detail.wait(5000)
        qapp.processEvents()
        assert view.pool_switch.isEnabled() and not view.pool_switch.isChecked()
        app.theme.set_dark(True)
        view.pool_switch.click()
        assert view._write.wait(5000)
        qapp.processEvents()
        path = ctx.settings_dir / "library.json"
        assert json.loads(path.read_text(encoding="utf-8"))["pool"] == ["abc"]
        assert page.rows["pool"].chip.text() == "1"
        page.rows["pool"].clicked.emit()
        assert view.model.rowCount() == 1
        view.pool_switch.click()
        assert view._write.wait(5000)
        qapp.processEvents()
        assert json.loads(path.read_text(encoding="utf-8"))["pool"] == []
        assert page.rows["pool"].chip.text() == "0"
        assert view.model.rowCount() == 0
        if page._scan is not None:
            assert page._scan.wait(5000)
            qapp.processEvents()
            if page._scan is not None:
                assert page._scan.wait(5000)
                qapp.processEvents()

        # A block usage opens its consuming deck and focuses that occurrence,
        # even when the same slide is called directly earlier in the deck.
        (ctx.blocks_dir / "Topic.tex").write_text("\\slide{abc-EN-Demo}\n")
        ctx.decks_dir.mkdir()
        path = ctx.decks_dir / "course.tex"
        path.write_text("\\documentclass{beamer}\n\\begin{document}\n"
                        "\\slide{abc-EN-Demo}\n\\slideblock{Topic}\n\\end{document}\n")
        deck = deck_scan.read_deck(path)
        calls = deck_language.active_calls(deck)
        app.slide_list = SimpleNamespace(rows=lambda: [
            SimpleNamespace(call=c, deck_call=c, related_ids=(), key=(n,)) for n, c in enumerate(calls)])
        app.centre = object()
        app.stack = SimpleNamespace(setCurrentWidget=lambda widget: None)
        page.ensure_loaded()
        assert page._scan.wait(5000)
        qapp.processEvents()
        page.rows["all"].clicked.emit()
        view.grid.setCurrentIndex(view.model.index(0))
        assert view._detail.wait(5000)
        qapp.processEvents()
        used = next(view.used_in.itemAt(n).widget() for n in range(view.used_in.count())
                    if isinstance(view.used_in.itemAt(n).widget(), RowButton)
                    and "via block Topic" in view.used_in.itemAt(n).widget().sub.text())
        used.clicked.emit()
        assert app.state.deck.path == path
        assert app.state.focused_occurrence == (1,)
    finally:
        page.shutdown()
        assert page.slides_view._viewport is None
        page.close()
        page.deleteLater()
