# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Library grid's grouping and persistent pool switch."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from conftest import wait_until
from slidemage import bundled_copies, library_data
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
    model.filter()

    assert model.rowCount() == 2
    rows = [model.index(n).data(Qt.ItemDataRole.UserRole) for n in range(model.rowCount())]
    assert {r.id for r in rows} == {"abc", "ghi"}
    assert next(r for r in rows if r.id == "abc").members == ["abc-EN-Original", "def-DE-Partner"]
    assert all(r.blocks == [] for r in rows)
    model.filter(query="DEF title")  # Palette matching: all words, across title and member IDs.
    assert model.rowCount() == 1
    assert model.index(0).data(Qt.ItemDataRole.UserRole).id == "abc"


@pytest.fixture
def library(qapp, tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    (ctx.slides_dir / "abc-EN-Demo-current.tex").write_text(
        "\\begin{standardframe}{Demo}\nBody\n\\end{standardframe}", encoding="utf-8")
    ctx.blocks_dir.mkdir()
    app = SimpleNamespace(project=ctx, theme=ThemeManager(dark=False), state=WorkspaceState(ctx),
                          background=SimpleNamespace(renderer=None))
    page = LibraryPage(app)
    page.resize(1280, 900)
    page.show()
    yield ctx, app, page
    page.shutdown()
    page.close()
    page.deleteLater()


def test_pool_on_off_writes_library_and_updates_the_rail(library):
    ctx, app, page = library
    (ctx.blocks_dir / "Topic.tex").write_text("%% Topics: Research\n\\slide{missing-Slide}\n")
    library_data.update(ctx, lambda data: data.topics.update({"abc": {"Research"}}))
    view = page.slides_view
    before = view.model.groups
    page.ensure_loaded()
    wait_until(lambda: view.model.groups is not before)
    assert not page.block_rows["Topic"].isHidden()
    assert not page.topic_rows["Research"].isHidden()
    page.rows["all"].clicked.emit()
    view.grid.setCurrentIndex(view.model.index(0))
    assert view.pool_switch.isEnabled() and not view.pool_switch.isChecked()

    app.theme.set_dark(True)
    before = view.model.groups
    view.pool_switch.click()
    wait_until(lambda: view.model.groups is not before)  # the write, then the rescan it triggers
    path = ctx.settings_dir / "library.json"
    assert json.loads(path.read_text(encoding="utf-8"))["pool"] == ["abc"]
    assert page.rows["pool"].chip.text() == "1"
    assert view.details.isVisible() and view._current.id == "abc"  # the rescan keeps the details open

    page.rows["pool"].clicked.emit()
    assert view.model.rowCount() == 1
    before = view.model.groups
    view.pool_switch.click()
    wait_until(lambda: view.model.groups is not before)
    assert json.loads(path.read_text(encoding="utf-8"))["pool"] == []
    assert page.rows["pool"].chip.text() == "0"
    assert view.model.rowCount() == 0


def test_used_in_via_block_opens_the_deck(library):
    ctx, app, page = library
    (ctx.blocks_dir / "Topic.tex").write_text("\\slide{abc-EN-Demo}\n")
    ctx.decks_dir.mkdir()
    path = ctx.decks_dir / "course.tex"
    # A block usage opens its consuming deck and focuses that occurrence,
    # even when the same slide is called directly earlier in the deck.
    path.write_text("\\documentclass{beamer}\n\\begin{document}\n"
                    "\\slide{abc-EN-Demo}\n\\slideblock{Topic}\n\\end{document}\n")
    focused = []
    app.slide_list = SimpleNamespace(focus=lambda block, slide_ids: focused.append((block, slide_ids)))
    app.centre = object()
    app.stack = SimpleNamespace(setCurrentWidget=lambda widget: None)
    view = page.slides_view
    before = view.model.groups
    page.ensure_loaded()
    wait_until(lambda: view.model.groups is not before)
    page.rows["all"].clicked.emit()
    view.grid.setCurrentIndex(view.model.index(0))

    def block_usage():
        widgets = (view.used_in.itemAt(n).widget() for n in range(view.used_in.count()))
        return [w for w in widgets if isinstance(w, RowButton) and "via block Topic" in w.sub.text()]

    wait_until(block_usage)
    block_usage()[0].clicked.emit()
    assert app.state.deck.path == path
    assert focused == [("Topic", {"abc"})]
