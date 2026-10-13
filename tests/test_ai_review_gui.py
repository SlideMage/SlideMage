"""Review controls and text task application without a terminal socket or model."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem

from conftest import build_window
from slidemage import ai_review, slide_ids, slide_source
from slidemage.ai import claude_tasks
from slidemage.ai.providers import OllamaProvider
from slidemage.project import ProjectContext
from slidemage.ui.kit.widgets import Button, Chip
from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace
from slidemage.ui.workspace.terminal.sync import DiskSync
from slidemage.ui.workspace.terminal.tasks import TaskRunner, _Capture

SLIDE = "slides/abc-EN-Hello-current.tex"


@pytest.fixture
def window(root, monkeypatch, qapp):
    monkeypatch.setattr(OllamaProvider, "list_models", lambda *args, **kwargs: [])
    window = build_window(monkeypatch, ProjectContext.at(root))
    window.open_slide_editor(root / SLIDE)
    window.state.set_mode("source")
    return window


def mark(window, name=SLIDE):
    ai_review.mark(window.project, name, "edit", "test Claude")
    window.refresh_ai_review()


def item(window, slide_id):
    tree = window.slide_list.tree
    return next(i for i in tree.slide_items() if tree.data_of(i).call.id == slide_id)


def test_filter_details_button_and_manual_edits_keep_the_label(window, qapp):
    mark(window)
    window.state.set_mode("details")
    assert [c.text() for c in window.centre.details.findChildren(Chip)] == ["Not reviewed"]
    window.commands.run("slides:unreviewed", window)
    assert not item(window, "abc").isHidden() and item(window, "abd").isHidden()
    file = window.centre.source.file_for(window.project.root / SLIDE)
    file.editor.replace_all_text(file.editor.text() + "% user edit\n")
    assert ai_review.is_unreviewed(window.project, SLIDE)
    next(b for b in window.centre.details.findChildren(Button) if b.text() == "Mark reviewed").click()
    assert not ai_review.unreviewed(window.project)
    assert window.centre.details.findChildren(Chip) == []
    assert all(i.isHidden() for i in window.slide_list.tree.slide_items())


def test_registry_reviews_focused_and_multiple_slides(window):
    mark(window)
    mark(window, "slides/abd-EN-Second-current.tex")
    assert window.commands.run("slide:reviewed", window)
    assert not ai_review.is_unreviewed(window.project, SLIDE)
    assert ai_review.is_unreviewed(window.project, "slides/abd-EN-Second-current.tex")
    mark(window)
    tree = window.slide_list.tree
    tree.clearSelection()
    item(window, "abc").setSelected(True)
    item(window, "abd").setSelected(True)
    assert window.commands.run("slide:reviewed", window)
    assert not ai_review.unreviewed(window.project)
    assert not window.commands.run("slide:reviewed", window)


def test_standalone_focused_slide_can_be_reviewed_from_the_registry(window):
    path = window.project.slides_dir / "zzz-EN-Standalone-current.tex"
    path.write_text("standalone")
    window.open_slide_editor(path)
    mark(window, path)
    assert window.commands.run("slide:reviewed", window)
    assert not ai_review.is_unreviewed(window.project, path)


@pytest.mark.parametrize("width", [220, 520])
def test_row_chip_is_legible_and_its_button_reviews_the_slide(window, qapp, width):
    mark(window)
    slides = window.slide_list
    slides.setParent(None)
    slides.resize(width, 400)
    slides.show()
    qapp.processEvents()
    tree = slides.tree
    index = tree.indexFromItem(item(window, "abc"))
    option = QStyleOptionViewItem()
    option.rect = tree.visualItemRect(item(window, "abc"))
    pixmap = QPixmap(tree.viewport().size())
    painter = QPainter(pixmap)
    recorded = Mock(wraps=painter)
    try:
        tree.delegate.paint(recorded, option, index)
    finally:
        painter.end()
    chip = next(call.args[0] for call in recorded.drawText.call_args_list if call.args[2] == "Not reviewed")
    button = tree.delegate.review_button(option.rect)
    assert chip.right() < button.left() and chip.left() >= 0
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=button.center().toPoint())
    assert not ai_review.is_unreviewed(window.project, SLIDE)
    slides.setParent(window.centralWidget())


def test_poll_refreshes_hook_marks_even_if_slide_text_did_not_change(window):
    window.state.set_mode("details")
    sync = DiskSync(window, window.project.root)
    sync.start()
    try:
        ai_review.mark(window.project, SLIDE, "edit", "external hook")
        sync.poll()
        assert window.slide_list.tree.data_of(item(window, "abc")).unreviewed
        assert [c.text() for c in window.centre.details.findChildren(Chip)] == ["Not reviewed"]
        ai_review.mark_reviewed(window.project, [SLIDE])
        sync.poll()
        assert not window.slide_list.tree.data_of(item(window, "abc")).unreviewed
        assert window.centre.details.findChildren(Chip) == []
    finally:
        sync.stop(last_look=False)


def test_pinned_frozen_row_does_not_show_the_current_files_mark(window):
    mark(window)
    deck = window.state.deck
    deck.path.write_text(deck.text.replace("\\slide{abc-EN-Hello}", "\\slideversion{abc-EN-Hello}{1-0-0}"))
    window.after_deck_edit(deck.path, "pin")
    row = window.slide_list.tree.data_of(item(window, "abc"))
    assert not row.unreviewed
    window.state.set_mode("details")
    assert not window.centre.details.findChildren(Chip)


@pytest.mark.parametrize("task", [claude_tasks.CONCISE, claude_tasks.PROOFREAD, claude_tasks.TITLE,
                                  claude_tasks.NOTE, claude_tasks.FIX_LATEX, claude_tasks.UPDATE_TRANSLATION])
@pytest.mark.parametrize("open_buffer", [False, True])
def test_every_headless_text_task_marks_its_actual_target(window, task, open_buffer):
    workspace = GuiWorkspace(window)
    path = window.project.root / SLIDE if open_buffer else window.project.slides_dir / "abd-EN-Second-current.tex"
    before = window.centre.slide_text(path)
    capture = _Capture(task, path, path.name.removesuffix("-current.tex"), before, "", before, "", "", "\r\n", window.state.deck.path)
    runner = TaskRunner(window, workspace)
    assert runner._write(capture, before.replace("First point", "New point")) is not None
    saved = ai_review.unreviewed(window.project)[path.relative_to(window.project.root).as_posix()]
    assert saved["kind"] == ("translation" if task is claude_tasks.UPDATE_TRANSLATION else "edit")
    assert saved["source"] == task.name
    assert window.slide_list.tree.data_of(item(window, "abc" if open_buffer else "abd")).unreviewed


def test_translation_marks_both_partner_and_changed_source_and_inserted_call(window):
    workspace = GuiWorkspace(window)
    path = window.project.root / SLIDE
    before = window.centre.slide_text(path)
    body = slide_ids.body_of(before).replace("Hello", "Hallo")
    capture = _Capture(claude_tasks.TRANSLATE, path, "abc-EN-Hello", before, "", body, "", "DE", "\r\n", window.state.deck.path)
    runner = TaskRunner(window, workspace)
    assert "created" in runner._translate(capture, body)
    entries = ai_review.unreviewed(window.project)
    assert len(entries) == 2 and SLIDE in entries
    partner = next(key for key in entries if key != SLIDE)
    assert all(entry["kind"] == "translation" for entry in entries.values())
    assert entries[partner]["decks"] == ["decks/test.tex"]


def test_task_conflict_does_not_mark_and_summary_does_not_mark(window):
    workspace = GuiWorkspace(window)
    path = window.project.root / SLIDE
    before = window.centre.slide_text(path)
    capture = _Capture(claude_tasks.TITLE, path, "abc-EN-Hello", "old", "", before, "", "", "\r\n", window.state.deck.path)
    runner = TaskRunner(window, workspace)
    assert runner._write(capture, "new") is None
    capture = _Capture(claude_tasks.SUMMARISE, path, "abc", "", "", "", "", "", "", None)
    runner._apply(capture, SimpleNamespace(text="summary", elapsed_s=1))
    assert not ai_review.unreviewed(window.project)


def test_claude_syntax_fix_marks_the_buffer_but_local_fix_does_not(window):
    file = window.centre.source.file_for(window.project.root / SLIDE)
    file.fix_panel._provider = SimpleNamespace(service="Ollama")
    file.fix_panel._on_applied(SimpleNamespace(line=1))
    assert not ai_review.unreviewed(window.project)
    file.editor.replace_all_text(file.editor.text() + "% Claude fix\n")
    file.fix_panel._provider = SimpleNamespace(service="Anthropic")
    file.fix_panel._on_applied(SimpleNamespace(line=1))
    assert ai_review.is_unreviewed(window.project, file.path)
    assert "Claude fix" not in slide_source.read_slide_source(file.path)[0]
