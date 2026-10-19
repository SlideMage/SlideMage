# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Insert menu's forms and the "Cite" popover, and the lint status line of the Source view."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from slidemage import latex_edit
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.insert_popovers import CitationPopover, CodeFilePopover
from slidemage.ui.workspace.source_view import SourcePane


class FakeApp:
    def __init__(self, project):
        self.project = project
        self.theme = ThemeManager()
        self.logged = []

    def log(self, line):
        self.logged.append(line)

    def open_slide_editor(self, path, **_kwargs):
        pass

    def refresh_open_deck_editors(self):
        pass


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A slides/ folder with one slide, a snippets/ folder and a bibliography."""
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "abc-EN-Demo-current.tex").write_text(
        "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n", encoding="utf-8")
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "abc-1.tex").write_text("\\slide{x}", encoding="utf-8")
    bib = tmp_path / "Slidemaster.bib"
    bib.write_text(
        "@article{markowitz1952,\n  author = {Markowitz, H.},\n  title = {Portfolio Selection},\n"
        "  year = {1952},\n  journaltitle = {Journal of Finance}}\n\n"
        "@book{sharpe1964,\n  author = {Sharpe, W.},\n  title = {Capital Asset Prices},\n  year = {1964}}\n",
        encoding="utf-8")
    return tmp_path


@pytest.fixture
def pane(ctx, qapp, project):
    pane = SourcePane(FakeApp(ctx))
    pane.show_path(project / "slides" / "abc-EN-Demo-current.tex")
    return pane


def open_popover(kind):
    found = [w for w in QApplication.topLevelWidgets() if isinstance(w, kind) and w.isVisible()]
    assert len(found) == 1
    return found[0]


# -- the Insert menu -----------------------------------------------------------------

def test_the_insert_menu_offers_hyperlink_code_file_lists_blocks_and_both_languages(pane):
    seen = {}
    pane._popup = lambda menu, anchor: seen.update(
        entries=[(e[2], e[3]) for e in menu._entries if e[0] == "item"],
        headers=[e[1] for e in menu._entries if e[0] == "header"])
    pane._open_insert_menu()
    labels = dict(seen["entries"])
    assert seen["headers"] == ["Lists", "Blocks", "Commands"]
    assert [label for label, _hint in seen["entries"]][:2] == ["Hyperlink…", "Code file…"]
    assert labels["Bulleted list"] == "\\begin{itemize}" and labels["Definition block"] == "\\begin{definitionblock}"
    assert labels["Both languages"] == "\\multilingualtext{EN}{DE}"
    assert labels["Hyperlink…"] and labels["Code file…"] == "\\SMCodeFile{snippets/…}"


def test_a_menu_choice_without_a_form_inserts_at_once(pane):
    editor = pane.current.editor
    pane._on_insert_chosen("block:4")            # Definition block
    assert editor.text().startswith("\\begin{definitionblock}{}")
    pane._on_insert_chosen("cmd:7")              # Both languages
    assert "\\multilingualtext{}{}" in editor.text()


def test_the_code_file_form_lists_the_snippets_and_suggests_the_slides_next_name(pane, project):
    pane._on_insert_chosen("cmd:1")
    popover = open_popover(CodeFilePopover)
    assert [popover.path.itemText(i) for i in range(popover.path.count())] == ["snippets/abc-1.tex"]
    assert popover.path.currentText() == "snippets/abc-2.tex"
    assert popover.create.isChecked() and "does not exist" in popover.note.text()
    popover.keys.setText("firstline=2")
    popover._on_insert()
    assert pane.current.editor.text().startswith("\\SMCodeFile[firstline=2]{snippets/abc-2.tex}")
    assert (project / "snippets" / "abc-2.tex").is_file()       # created, as asked


def test_an_existing_snippet_is_not_created_again_and_one_outside_snippets_is_refused(pane, project):
    pane._on_insert_chosen("cmd:1")
    popover = open_popover(CodeFilePopover)
    popover.path.setEditText("snippets/abc-1.tex")
    assert not popover.create.isEnabled() and popover.note.text() == ""
    popover.path.setEditText("slides/abc-EN-Demo-current.tex")
    popover._on_insert()
    assert popover.isVisible() and "snippets" in popover.note.text()
    assert not (project / "snippets" / "abc-EN-Demo-current.tex").exists()
    popover.path.setEditText("snippets/abc-1.tex")
    popover._on_insert()
    assert pane.current.editor.text().startswith("\\SMCodeFile{snippets/abc-1.tex}")


# -- the citation popover ---------------------------------------------------------------

def test_citing_searches_the_bibliography_and_inserts_the_style_chosen(pane):
    pane._open_citation_popover()
    popover = open_popover(CitationPopover)
    assert popover.results.count() == 2 and "2 matches" in popover.count.text()
    QTest.keyClicks(popover.search, "sharpe")
    assert popover.results.count() == 1
    QTest.keyClick(popover.search, Qt.Key.Key_Return)             # the default style
    assert pane.current.editor.text().startswith("\\fullcite{sharpe1964}")
    assert not popover.isVisible()


def test_arrow_keys_pick_the_entry_and_the_style_buttons_change_the_macro(pane):
    pane._open_citation_popover()
    popover = open_popover(CitationPopover)
    QTest.keyClick(popover.search, Qt.Key.Key_Down)
    assert popover.results.currentItem().data(Qt.ItemDataRole.UserRole) == "sharpe1964"
    QTest.keyClick(popover.search, Qt.Key.Key_Up)
    QTest.keyClick(popover.search, Qt.Key.Key_Up)                 # stays on the first
    assert popover.results.currentItem().data(Qt.ItemDataRole.UserRole) == "markowitz1952"
    popover.styles._buttons["textcite"].click()
    QTest.keyClick(popover.search, Qt.Key.Key_Return)
    assert pane.current.editor.text().startswith("\\textcite{markowitz1952}")


def test_the_bare_key_style_and_escape(pane):
    pane._open_citation_popover()
    popover = open_popover(CitationPopover)
    popover.styles._buttons["key"].click()
    popover._insert_current()
    assert pane.current.editor.text().startswith("markowitz1952")
    pane._open_citation_popover()
    popover = open_popover(CitationPopover)
    QTest.keyClick(popover.search, Qt.Key.Key_Escape)
    assert not popover.isVisible()


def test_the_footer_opens_add_reference_and_a_search_without_hits_inserts_nothing(pane, monkeypatch):
    asked = []
    monkeypatch.setattr(pane, "add_reference", lambda: asked.append(True))
    pane._open_citation_popover()
    popover = open_popover(CitationPopover)
    QTest.keyClicks(popover.search, "nobody")
    assert popover.results.count() == 0 and popover.count.text() == "0 matches"
    QTest.keyClick(popover.search, Qt.Key.Key_Return)
    assert popover.isVisible() and pane.current.editor.text().startswith("\\begin")
    popover._add_reference()
    assert asked == [True] and not popover.isVisible()


def test_nothing_is_inserted_into_a_frozen_version(pane, project):
    frozen = project / "slides" / "abc-EN-Demo-v1-0-0.tex"
    frozen.write_text("old", encoding="utf-8")
    pane.show_path(frozen)
    pane._open_citation_popover()
    pane.insert(next(i for i in latex_edit.INSERT_COMMANDS if i.kind == "hyperlink"))
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, (CitationPopover,)) and w.isVisible()]
