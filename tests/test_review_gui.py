"""Focused offscreen regressions for GUI data-loss cases from the 2026-09 review."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QPlainTextEdit, QWidget

from slidemage import alt_blocks, alt_draft, alt_images, app_settings, qt_ai_draft_dialog, qt_gui, qt_slide_source_tab, qt_transcript_tab
from slidemage.ai_draft import DraftProposal
from slidemage.alt_blocks import SlideRow
from slidemage.qt_theme import ThemeManager


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _mock_ollama_lists(monkeypatch) -> None:
    monkeypatch.setattr(alt_draft, "list_vision_models", lambda: [])
    monkeypatch.setattr(alt_draft, "list_all_models", lambda: [])


def _make_window(monkeypatch, qapp):
    _mock_ollama_lists(monkeypatch)
    return qt_gui.SlideMageWindow(ThemeManager())


def _write_slide(path: Path, text: str = "\\slide{abc-EN-Test}\nBODY\n") -> Path:
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _open_dirty_source(window, path: Path, monkeypatch):
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
    window.open_slide_editor(path)
    tab = window._slide_source_tabs[path]
    cursor = tab.widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("\n% unsaved edit")
    tab.widget.setTextCursor(cursor)
    assert tab._dirty
    return tab


def test_main_window_cancel_keeps_dirty_source_open(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    tab = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    save_called = False
    tab._on_save = lambda: save_called  # must not run after Cancel
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert window.close() is False
    assert tab._dirty
    assert not save_called


def test_main_window_saves_dirty_source_before_close(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    tab = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    calls = []

    def save_without_disk_write():
        calls.append(tab.path)
        tab._set_dirty(False)
        return True

    tab._on_save = save_without_disk_write
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert window.close() is True
    assert calls == [tab.path]
    assert not tab._dirty


def test_main_window_stays_open_when_source_save_is_cancelled(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    tab = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    tab._on_save = lambda: False

    assert window.close() is False
    assert tab._dirty


def test_open_project_resolves_dirty_source_before_relaunch(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    tab = _open_dirty_source(window, _write_slide(tmp_path / "abc-EN-Test-current.tex"), monkeypatch)
    chosen = tmp_path / "another-project"
    monkeypatch.setattr(qt_gui.project, "pick_or_create_project", lambda *args: chosen)
    relaunched = []
    monkeypatch.setattr(qt_gui.project, "relaunch_with_project", relaunched.append)
    replies = iter((QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No))
    titles = []

    def answer(_parent, title, *_args, **_kwargs):
        titles.append(title)
        return next(replies)

    monkeypatch.setattr(QMessageBox, "question", answer)
    window._on_open_project()

    assert titles == ["Open project", "Unsaved source edits"]
    assert relaunched == [chosen]
    assert tab._dirty  # the explicit Discard choice applies to this relaunch
    assert window.isHidden()


def test_main_window_prompts_for_dirty_image_edits(monkeypatch, qapp):
    window = _make_window(monkeypatch, qapp)
    monkeypatch.setattr(window.transcript_tab, "_any_editor_dirty", lambda: True)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert window.close() is False


def _make_transcript_tab(monkeypatch, qapp, tmp_path, *, image_refs=None):
    _mock_ollama_lists(monkeypatch)
    image_refs = image_refs or ["media/chart.png"]
    first = SlideRow(tmp_path / "one.tex", "one", "First", list(image_refs))
    second = SlideRow(tmp_path / "two.tex", "two", "Second", [image_refs[0]])
    store = {
        reference: alt_images.ImageEntry(image=reference)
        for reference in image_refs
    }
    sync_calls = []
    monkeypatch.setattr(qt_transcript_tab, "scan_decks", lambda: [])
    monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda: [first, second])
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _reference: None)
    monkeypatch.setattr(alt_draft, "draftable_images", lambda *_args: [])
    monkeypatch.setattr(alt_images, "sync_store", lambda: (sync_calls.append(True), alt_images.SyncReport())[1])
    monkeypatch.setattr(alt_images, "load_store", lambda: deepcopy(store))

    def update_store(mutate):
        latest = deepcopy(store)
        changed = mutate(latest)
        if changed:
            store.clear()
            store.update(latest)
        return changed

    monkeypatch.setattr(alt_images, "update_store", update_store)
    monkeypatch.setattr(alt_images, "slide_context_hash", lambda _path: "slide-hash")
    app = SimpleNamespace(
        log=lambda _line: None,
        end_ollama_task=lambda: None,
        try_start_ollama_task=lambda _label: True,
    )
    tab = qt_transcript_tab.TranscriptTab(app)
    tab.reload()
    return tab, sync_calls, store


@pytest.mark.parametrize(
    ("completion", "summary"),
    [
        ("_on_drafts_ready", alt_draft.BatchSummary),
        ("_on_translations_ready", alt_draft.TranslationBatchSummary),
    ],
)
def test_batch_completion_preserves_dirty_image_editor(
    completion, summary, monkeypatch, qapp, tmp_path
):
    tab, sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor.fields["long"].setPlainText("UNSAVED HUMAN EDIT")
    assert editor.dirty

    getattr(tab, completion)(summary())

    assert tab._editors[0] is editor
    assert editor.fields["long"].toPlainText() == "UNSAVED HUMAN EDIT"
    assert len(sync_calls) == 1  # completion deferred its reload


def test_save_merges_human_edit_with_worker_updates_across_visible_images(
    monkeypatch, qapp, tmp_path
):
    chart_ref = "media/chart.png"
    second_ref = "media/second.png"
    tab, _sync_calls, store = _make_transcript_tab(
        monkeypatch, qapp, tmp_path, image_refs=[chart_ref, second_ref]
    )
    chart = store[chart_ref]
    chart.short = "worker's latest English short"
    chart.takeaway_default = "worker's latest English takeaway"
    chart.used_on["one"] = alt_images.SlideUse(
        takeaway="worker's latest slide override",
        takeaway_de="worker's latest German override",
    )
    chart.short_de = "worker short DE"
    chart.long_de = "worker long DE"
    chart.takeaway_default_de = "worker default DE"
    chart.translated_from_hash = alt_images.en_text_hash(chart)

    other = store[second_ref]
    other.long = "worker's latest second-image description"
    other.drafted_by = "offline-worker"
    other.hint = "latest worker hint"
    other.short_de = "second short DE"
    other.long_de = "second long DE"
    other.takeaway_default = "second EN takeaway"
    other.takeaway_default_de = "second DE takeaway"
    other.translated_from_hash = alt_images.en_text_hash(other)

    editor = tab._editors[0]
    editor.fields["long"].setPlainText("HUMAN ENGLISH EDIT")
    tab._on_translations_ready(alt_draft.TranslationBatchSummary(written=2))

    assert tab._editors[0] is editor  # dirty completion deferred the reload
    tab._save(mark_reviewed=False)

    saved_chart = store[chart_ref]
    assert saved_chart.long == "HUMAN ENGLISH EDIT"
    assert saved_chart.short == "worker's latest English short"
    assert saved_chart.takeaway_default == "worker's latest English takeaway"
    assert saved_chart.takeaway_for("one") == "worker's latest slide override"
    assert saved_chart.takeaway_default_de == "worker default DE"
    assert saved_chart.takeaway_for_de("one") == "worker's latest German override"
    assert saved_chart.short_de == "worker short DE"
    assert saved_chart.long_de == "worker long DE"
    assert saved_chart.translated_from_hash == alt_images.en_text_hash(chart)
    assert alt_images.translation_state(saved_chart) == alt_images.STATE_STALE

    saved_other = store[second_ref]
    assert saved_other.long == "worker's latest second-image description"
    assert saved_other.drafted_by == "offline-worker"
    assert saved_other.hint == "latest worker hint"
    assert saved_other.short_de == "second short DE"
    assert saved_other.long_de == "second long DE"
    assert saved_other.takeaway_default == "second EN takeaway"
    assert saved_other.takeaway_default_de == "second DE takeaway"
    assert saved_other.translated_from_hash == alt_images.en_text_hash(saved_other)


def test_set_default_keeps_worker_fields_and_invalidates_stale_human_translation(
    monkeypatch, qapp, tmp_path
):
    reference = "media/chart.png"
    tab, _sync_calls, store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    entry = store[reference]
    entry.short = "worker's new English short"
    entry.long = "worker's new English long"
    entry.short_de = "worker short DE"
    entry.long_de = "worker long DE"
    entry.translated_from_hash = alt_images.en_text_hash(entry)

    editor = tab._editors[0]
    editor.fields["takeaway"].setPlainText("human's chosen default")
    editor._on_set_default()
    editor.fields["short_de"].setPlainText("human German edit based on old form")
    tab._save(mark_reviewed=False)

    saved = store[reference]
    assert saved.short == "worker's new English short"
    assert saved.long == "worker's new English long"
    assert saved.takeaway_default == "human's chosen default"
    assert saved.long_de == "worker long DE"
    assert saved.short_de == "human German edit based on old form"
    assert saved.translated_from_hash == ""
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_rescan_cancel_and_slide_switch_cancel_keep_dirty_fields(monkeypatch, qapp, tmp_path):
    tab, sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor.fields["long"].setPlainText("UNSAVED HUMAN EDIT")
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    assert tab.reload() is False
    assert len(sync_calls) == 1
    tab.slide_list.setCurrentRow(1)

    assert tab.slide_list.currentRow() == 0
    assert tab._current.row.slide_id == "one"
    assert tab._editors[0] is editor
    assert editor.fields["long"].toPlainText() == "UNSAVED HUMAN EDIT"


def _patch_translate_dialog_and_thread(monkeypatch, *, run_inline):
    jobs = []

    class FakeMessageBox:
        StandardButton = QMessageBox.StandardButton
        ButtonRole = QMessageBox.ButtonRole

        def __init__(self, *_args):
            self.buttons = []

        def setWindowTitle(self, _title):
            pass

        def setText(self, _text):
            pass

        def addButton(self, *_args):
            button = object()
            self.buttons.append(button)
            return button

        def setDefaultButton(self, _button):
            pass

        def exec(self):
            pass

        def clickedButton(self):
            return self.buttons[0]  # choose "Unsaved draft"

    class ControlledThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            jobs.append((self.target, self.args))
            if run_inline:
                self.target(*self.args)

    monkeypatch.setattr(qt_transcript_tab, "QMessageBox", FakeMessageBox)
    monkeypatch.setattr(qt_transcript_tab.threading, "Thread", ControlledThread)
    return jobs


def _translation_result_for(entry):
    return alt_draft.TranslationResult(
        short_de="translated short",
        long_de="translated long",
        takeaway_de="translated takeaway",
        source_hash=alt_images.en_text_hash(entry),
    )


def test_unsaved_english_translation_stays_current_after_save(
    monkeypatch, qapp, tmp_path
):
    tab, _sync_calls, store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor.fields["long"].setPlainText("UNSAVED ENGLISH TO TRANSLATE")
    _patch_translate_dialog_and_thread(monkeypatch, run_inline=True)

    class FakeBackend:
        def __init__(self, **_kwargs):
            pass

        def translate(self, entry):
            return _translation_result_for(entry)

    monkeypatch.setattr(alt_draft, "OllamaTranslationBackend", FakeBackend)
    editor._on_translate()

    assert "matches current English text" in editor.translation_state_label.text()
    translated_hash = editor._translation_provenance["source_hash"]
    tab._save(mark_reviewed=False)

    saved = store["media/chart.png"]
    assert saved.long == "UNSAVED ENGLISH TO TRANSLATE"
    assert saved.translated_from_hash == translated_hash
    assert alt_images.translation_state(saved) == alt_images.STATE_REVIEWED


def test_translation_completion_keeps_newer_english_and_human_german_stale(
    monkeypatch, qapp, tmp_path
):
    tab, _sync_calls, store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor.fields["long"].setPlainText("ENGLISH AT REQUEST TIME")
    jobs = _patch_translate_dialog_and_thread(monkeypatch, run_inline=False)
    editor._on_translate()
    live_entry = jobs[0][1][1]

    editor.fields["long"].setPlainText("NEWER ENGLISH AFTER REQUEST")
    editor.fields["short_de"].setPlainText("HUMAN GERMAN EDIT DURING REQUEST")
    editor._on_translation_done(_translation_result_for(live_entry))
    assert editor.fields["short_de"].toPlainText() == "HUMAN GERMAN EDIT DURING REQUEST"
    tab._save(mark_reviewed=False)

    saved = store["media/chart.png"]
    assert saved.long == "NEWER ENGLISH AFTER REQUEST"
    assert saved.short_de == "HUMAN GERMAN EDIT DURING REQUEST"
    assert saved.translated_from_hash == ""
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_edit_after_translation_completion_invalidates_saved_provenance(
    monkeypatch, qapp, tmp_path
):
    tab, _sync_calls, store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor.fields["long"].setPlainText("UNSAVED ENGLISH TO TRANSLATE")
    _patch_translate_dialog_and_thread(monkeypatch, run_inline=True)

    class FakeBackend:
        def __init__(self, **_kwargs):
            pass

        def translate(self, entry):
            return _translation_result_for(entry)

    monkeypatch.setattr(alt_draft, "OllamaTranslationBackend", FakeBackend)
    editor._on_translate()
    editor.fields["long_de"].setPlainText("HUMAN GERMAN EDIT AFTER TRANSLATION")
    tab._save(mark_reviewed=False)

    saved = store["media/chart.png"]
    assert saved.long_de == "HUMAN GERMAN EDIT AFTER TRANSLATION"
    assert saved.translated_from_hash == ""
    assert alt_images.translation_state(saved) == alt_images.STATE_STALE


def test_individual_translation_keeps_fields_typed_after_request(monkeypatch, qapp, tmp_path):
    tab, _sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    editor = tab._editors[0]
    editor._translation_field_baseline = {
        key: editor.fields[key].toPlainText()
        for key in ("short_de", "long_de", "takeaway_de")
    }
    editor._translation_source_baseline = (
        editor.short, editor.long, editor.takeaway_text
    )
    editor.fields["long_de"].setPlainText("NEW HUMAN GERMAN TEXT")

    editor._on_translation_done(alt_draft.TranslationResult(
        short_de="translated short",
        long_de="translated long",
        takeaway_de="translated takeaway",
    ))

    assert editor.fields["short_de"].toPlainText() == "translated short"
    assert editor.fields["long_de"].toPlainText() == "NEW HUMAN GERMAN TEXT"
    assert editor.fields["takeaway_de"].toPlainText() == "translated takeaway"


def test_stale_ai_proposal_is_refused_after_source_edit(monkeypatch, qapp):
    _mock_ollama_lists(monkeypatch)
    monkeypatch.setattr(alt_draft, "list_all_models", lambda: ["offline-test"])
    monkeypatch.setattr(app_settings, "get", lambda _key: None)

    class SourceTab(QWidget):
        def __init__(self):
            super().__init__()
            self.app = SimpleNamespace(
                try_start_ollama_task=lambda _label: True,
                end_ollama_task=lambda: None,
                log=lambda _line: None,
            )
            self.widget = QPlainTextEdit("original source", self)

    class FakeDrafter:
        def __init__(self, **_kwargs):
            pass

        def draft(self, current_text, _prompt):
            return DraftProposal(
                proposed_text=current_text + "\nAI proposal",
                model="offline-test",
                elapsed_s=0.1,
            )

    monkeypatch.setattr(qt_ai_draft_dialog.ai_draft, "OllamaSlideDrafter", FakeDrafter)
    source_tab = SourceTab()
    dialog = qt_ai_draft_dialog.AiDraftDialog(source_tab, "test.tex")
    dialog.prompt_edit.setPlainText("add a line")
    dialog._on_generate()
    assert dialog._proposal_baseline == "original source"
    source_tab.widget.setPlainText("original source\nmanual edit")

    dialog._on_accept()

    assert source_tab.widget.toPlainText() == "original source\nmanual edit"
    assert not dialog.accept_button.isEnabled()
    assert "source changed" in dialog.status_label.text().lower()


def test_minimal_replacement_uses_utf16_offsets_and_keeps_cursor(monkeypatch, qapp, tmp_path):
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
    path = _write_slide(
        tmp_path / "abc-EN-Emoji-current.tex",
        "😀\n\\setSlideVersion{1.0.0}\nBODY",
    )
    app = SimpleNamespace(theme=ThemeManager(), log=lambda _line: None)
    tab = qt_slide_source_tab.SlideSourceTab(app, path)
    old = tab.widget.toPlainText()
    new = old.replace("1.0.0", "12.0.1")
    cursor = tab.widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    tab.widget.setTextCursor(cursor)

    tab._apply_minimal_text_replace(old, new)

    assert tab.widget.toPlainText() == new
    assert tab.widget.textCursor().position() == len(new.encode("utf-16-le")) // 2


def test_temp_cleanup_removes_only_helper_returned_build_items(monkeypatch, qapp, tmp_path):
    window = _make_window(monkeypatch, qapp)
    build_root = tmp_path / "build"
    build_root.mkdir()
    old_file = build_root / "legacy.log"
    old_file.write_text("old", encoding="utf-8")
    old_run = build_root / "old-run"
    old_run.mkdir()
    (old_run / "output.pdf").write_bytes(b"old")
    monkeypatch.setattr(qt_gui.compiler, "removable_build_entries", lambda: [old_file, old_run])
    monkeypatch.setattr(qt_gui, "DECKS_DIR", tmp_path / "decks")
    monkeypatch.setattr(qt_gui, "TEMP_DIR", tmp_path / ".temp")
    qt_gui.DECKS_DIR.mkdir()
    qt_gui.TEMP_DIR.mkdir()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window._remove_temp_files()

    assert not old_file.exists()
    assert not old_run.exists()
    assert "2 build item(s)" in window.log_text.toPlainText()


def _click_row(tab, row):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    rect = tab.slide_list.visualItemRect(tab.slide_list.item(row))
    QTest.mouseClick(tab.slide_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())


@pytest.mark.parametrize("reason", ["translation", "unsaved"])
def test_declining_the_switch_keeps_the_slide_and_its_selection(
    reason, monkeypatch, qapp, tmp_path
):
    # direct report 2026-10-09: "I attempted to switch to another slide ... selected No
    # in response to 'Switch anyway' ... SlideMage still made the switch"
    tab, _sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    tab.resize(900, 600)
    tab.show()
    qapp.processEvents()
    shown = tab._current.row.path
    editor = tab._editors[0]
    if reason == "translation":
        editor.translating = True
    else:
        editor.fields["long"].setPlainText("UNSAVED HUMAN EDIT")
        assert editor.dirty
    asked = []

    def decline(*args, **kwargs):
        asked.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)
    other = 1 if tab.slide_list.currentRow() == 0 else 0

    _click_row(tab, other)
    qapp.processEvents()

    assert len(asked) == 1
    assert tab._current.row.path == shown
    assert tab._editors[0] is editor
    assert tab.slide_list.currentRow() == tab._current_row_index
    assert [tab.slide_list.row(item) for item in tab.slide_list.selectedItems()] == [
        tab._current_row_index
    ]
    tab.hide()


def test_changing_show_filter_keeps_the_slide_on_show_and_its_translation(
    monkeypatch, qapp, tmp_path
):
    # direct report 2026-10-11: choosing another view in "Show:" jumped to a different slide,
    # translation or not
    tab, _sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    tab.resize(900, 600)
    tab.show()
    qapp.processEvents()
    tab.slide_list.setCurrentRow(1)
    qapp.processEvents()
    shown = tab._current.row.path
    editor = tab._editors[0]
    editor.translating = True
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: asked.append(args) or QMessageBox.StandardButton.No,
    )

    tab.filter_combo.setCurrentIndex(1)  # "All slides with images": both slides still listed
    qapp.processEvents()

    assert asked == []
    assert tab._current.row.path == shown
    assert tab._editors[0] is editor
    assert tab.slide_list.currentRow() == tab._current_row_index
    assert tab.slide_list.item(tab.slide_list.currentRow()).data(0x0100) == shown
    tab.hide()


def test_show_filter_that_drops_the_slide_asks_during_a_translation(
    monkeypatch, qapp, tmp_path
):
    tab, _sync_calls, _store = _make_transcript_tab(monkeypatch, qapp, tmp_path)
    tab.resize(900, 600)
    tab.show()
    qapp.processEvents()
    shown = tab._current.row.path
    editor = tab._editors[0]
    editor.translating = True
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    asked = []

    def answer(*args, **kwargs):
        asked.append(args[1])
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "question", answer)
    reviewed = 5  # "Reviewed": neither fixture slide is in it

    tab.filter_combo.setCurrentIndex(reviewed)
    qapp.processEvents()

    assert asked == ["Translation in progress"]
    assert tab.filter_combo.currentIndex() == 0
    assert tab._current.row.path == shown
    assert tab._editors[0] is editor

    tab.filter_combo.setCurrentIndex(reviewed)  # now confirmed
    qapp.processEvents()

    assert asked == ["Translation in progress", "Translation in progress"]
    assert tab.filter_combo.currentIndex() == reviewed
    assert tab.slide_list.count() == 0
    tab.hide()
