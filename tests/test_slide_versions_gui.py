# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A slide's frozen versions in the centre column: making one the current version, and Update
Version of the current one (the Slide versions panel is in test_side_panels_gui.py)."""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QWidget

from slidemage import alt_images, fileio, slide_branch, slide_versioning
from slidemage.ui import layout_settings
from slidemage.ui.dialogs.new_slide_version import NewSlideVersionSheet
from slidemage.ui.dialogs.slide_usage_dialog import DeckVersions, SlideUsageDialog, revision_summary
from slidemage.ui.workspace import centre as centre_module, source_file
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.centre import CentreColumn
from slidemage.ui.workspace.details_view import DetailsPane
from slidemage.ui.workspace.state import WorkspaceState


SLUG = "abc-EN-Demo"
CURRENT = f"{SLUG}-current.tex"
FROZEN = f"{SLUG}-v1-2-0.tex"
SELECTED = f"{SLUG}-v1-0-0.tex"
BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"
MARKED = "\\setSlideVersion{1-2-0}\n" + BODY
EDITED = "\\setSlideVersion{1-2-0+}\n" + BODY
DECK = "\\documentclass{beamer}\n\\begin{document}\n\\slide{abc-EN-Demo}\n\\end{document}\n"


class FakeApp:
    def __init__(self, project):
        self.project = project
        self.theme = ThemeManager()
        self.logged = []

    def log(self, line):
        self.logged.append(line)

    def after_version_updates(self, _paths):
        pass

    def open_slide_editor(self, _path, **_kwargs):
        pass


@pytest.fixture
def versioned_slide(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / CURRENT).write_text(MARKED, encoding="utf-8")
    for version in ("1-0-0", "1-1-0"):
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(
            f"\\setSlideVersion{{{version}}}\n" + BODY.replace("Text", f"Text of {version}"), encoding="utf-8")
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    return slides


def snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def edit_and_save(centre, text):
    editor = centre.source.current.editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText(text)
    assert centre.save()


@pytest.fixture
def centre(ctx, qapp):
    return CentreColumn(FakeApp(ctx), WorkspaceState(ctx))


def test_making_a_version_current_archives_the_current_one_and_reopens_it(centre, versioned_slide, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    centre.revise("restore", [versioned_slide / SELECTED])
    current = (versioned_slide / CURRENT).read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-3-0}" in current          # the restored content gets a new, higher version
    assert (versioned_slide / FROZEN).exists()    # what was current is archived
    assert centre.source.current.path == versioned_slide / CURRENT


def test_restore_requires_the_author_to_save_edits_first(centre, versioned_slide, monkeypatch):
    current = versioned_slide / CURRENT
    centre.open_file(current)
    centre.source.current.editor.moveCursor(QTextCursor.MoveOperation.End)
    centre.source.current.editor.insertPlainText("x")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    before = snapshot(versioned_slide)
    centre.revise("restore", [versioned_slide / SELECTED])
    assert warned and current.name in warned[0]
    assert before == snapshot(versioned_slide)
    assert centre.source.current.dirty and centre.source.current.editor.text().endswith("x")


def test_making_a_version_current_is_refused_while_the_edits_cannot_be_saved(centre, versioned_slide, monkeypatch):
    current = versioned_slide / CURRENT
    centre.open_file(current)
    centre.source.current.editor.insertPlainText("x")
    current.write_text("\\setSlideVersion{1-2-0}\nsomeone else's\n", encoding="utf-8")
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("must not ask"))
    centre.revise("restore", [versioned_slide / SELECTED])
    assert len(told) == 1 and current.name in told[0]
    assert "x" in centre.source.current.editor.text() and "someone else's" in current.read_text(encoding="utf-8")


def test_update_version_makes_the_current_content_a_version(centre, versioned_slide):
    changed = []
    centre.versions_changed.connect(lambda: changed.append(True))
    current = versioned_slide / CURRENT
    centre.revise("minor", [current])     # 1.2.0, saved the old way, is not frozen yet: as it is
    assert current.read_text(encoding="utf-8") == MARKED
    assert (versioned_slide / FROZEN).read_text(encoding="utf-8") == MARKED
    assert changed == [True]

    centre.open_file(current)
    editor = centre.source.current.editor
    edit_and_save(centre, "% more\n")
    centre.revise("minor", [current])
    text = current.read_text(encoding="utf-8")
    assert text == "\\setSlideVersion{1-3-0}\n" + BODY + "% more\n"
    assert (versioned_slide / "abc-EN-Demo-v1-3-0.tex").read_text(encoding="utf-8") == text
    assert editor.text() == text and not editor.is_modified()
    editor.undo()                                       # the buffer kept its undo history
    assert "1-3-0" not in editor.text()


def test_update_version_can_keep_a_deck_on_the_previous_version(ctx, centre, branchable, monkeypatch):
    current = branchable / CURRENT
    deck = ctx.decks_dir / "talk.tex"
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *args: DeckVersions({deck: "keep"}, None))
    centre.app.adopt_deck_revisions = lambda edits: None
    assert centre.revise("patch", [current])
    assert r"\slideversion{abc-EN-Demo}{1-2-0}" in deck.read_text()
    assert (branchable / "abc-EN-Demo-v1-2-1.tex").exists()


def test_update_version_is_refused_without_a_change_or_when_the_version_exists(centre, versioned_slide, monkeypatch):
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    current = versioned_slide / CURRENT
    centre.revise("minor", [current])
    centre.revise("minor", [current])
    assert "has not changed since v1.2.0" in told[-1]
    current.write_text("\\setSlideVersion{1-2-0+}\nchanged\n", encoding="utf-8")
    (versioned_slide / "abc-EN-Demo-v1-3-0.tex").write_text("taken", encoding="utf-8")
    centre.revise("minor", [current])
    assert "frozen already" in told[-1] and "1-3-0" not in current.read_text(encoding="utf-8")


def test_details_handle_a_missing_slide_file_and_no_selection(ctx, qapp):
    details = DetailsPane(FakeApp(ctx), WorkspaceState(ctx), lambda path: False)
    details.show_slide("zzz-EN-Gone", None)            # no file: the facts are empty, nothing raises
    details.show_slide("", None, "Select a slide")
    assert [label.text() for label in details.findChildren(QLabel)] == ["Select a slide"]


@pytest.mark.parametrize("level,version", [("patch", "1-2-1"), ("minor", "1-3-0"), ("major", "2-0-0"),
                                          (None, "1-2-0+")])
def test_selected_versions_share_one_choice_and_leave_other_slides_alone(ctx, qapp, tmp_path, monkeypatch,
                                                                         level, version):

    slides = tmp_path / "slides"
    slides.mkdir()
    original = EDITED
    slugs = ["abc-EN-Demo", "def-DE-Beispiel", "ghi-EN-Unselected"]
    for slug in slugs:
        (slides / f"{slug}-current.tex").write_text(original, encoding="utf-8")
    app = FakeApp(ctx)
    app.slide_list = SimpleNamespace(targets=lambda: [SimpleNamespace(call=SimpleNamespace(id_slug=slug))
                                                     for slug in [slugs[0], slugs[1], slugs[0]]])
    updated = []
    app.after_version_updates = lambda paths: updated.extend(paths)
    centre = CentreColumn(app, WorkspaceState(ctx))
    prompts = []

    class Choice(QMessageBox):
        def __init__(self, _parent):
            super().__init__()
            prompts.append(self)

        def exec(self):
            if level is not None:
                next(button for button in self.buttons() if button.text() == level.capitalize()).click()

    monkeypatch.setattr(centre_module, "QMessageBox", Choice)
    centre.update_selected_versions()
    assert len(prompts) == 1
    for slug in slugs[:2]:
        assert f"\\setSlideVersion{{{version}}}" in (slides / f"{slug}-current.tex").read_text()
        assert (slides / f"{slug}-v{version}.tex").exists() == (level is not None)
    assert (slides / f"{slugs[2]}-current.tex").read_text() == original
    assert len(updated) == (2 if level is not None else 0)
    centre.deleteLater()


class BranchApp(FakeApp):
    def __init__(self, project):
        super().__init__(project)
        self.refreshed = []
        self.messages = []
        self.toast = SimpleNamespace(show_message=self.messages.append)
        self.undo = []
        self.slide_list = SimpleNamespace(deck_edited=lambda *args: self.undo.append(args))

    def after_version_updates(self, paths):
        self.refreshed.append(("versions", [p.name for p in paths]))

    def adopt_deck_revisions(self, edits):
        self.refreshed.append(("decks", *edits))

    def refresh_open_deck_editors(self):
        self.refreshed.append(("decks",))


@pytest.fixture
def branchable(ctx, versioned_slide):
    (versioned_slide / FROZEN).write_text(MARKED, encoding="utf-8")
    (versioned_slide / CURRENT).write_text(EDITED + "% changed\n", encoding="utf-8")
    (ctx.root / "slide_ids.csv").write_text('"id"\r\n"abc"\r\n', encoding="utf-8", newline="")
    ctx.decks_dir.mkdir()
    (ctx.decks_dir / "talk.tex").write_text(DECK, encoding="utf-8")
    return versioned_slide


@pytest.fixture
def second_deck(ctx, branchable):
    (ctx.decks_dir / "other.tex").write_text(DECK)
    return branchable


@pytest.fixture
def branch_centre(ctx, qapp):
    return CentreColumn(BranchApp(ctx), WorkspaceState(ctx))


@pytest.mark.parametrize("switch", [True, False])
def test_update_version_can_save_the_changes_as_a_new_slide(ctx, branch_centre, branchable, monkeypatch, switch):
    centre = branch_centre
    app = centre.app
    current = branchable / CURRENT
    offered = []

    class Sheet:
        def __init__(self, parent, id_slug, version, slug, sources, edited, root, preview):
            offered.append((id_slug, version, slug, list(sources), edited))
            self.slug, self.sources = "Demo-revised", [ctx.decks_dir / "talk.tex"] if switch else []

        def exec(self):
            return True

    monkeypatch.setattr(centre_module, "prompt_version_level", lambda *a: centre_module.NEW_SLIDE)
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", Sheet)
    centre.revise("update", [current])
    assert offered == [("abc-EN-Demo", (1, 2, 0), "Demo", [ctx.decks_dir / "talk.tex"], None)]
    new = next(p for p in branchable.glob("*-EN-Demo-revised-current.tex"))
    assert "% changed" in new.read_text(encoding="utf-8")
    assert "% changed" not in (branchable / CURRENT).read_text(encoding="utf-8")
    assert (rf"\slide{{{new.name.removesuffix('-current.tex')}}}" in (ctx.decks_dir / "talk.tex").read_text()) is switch
    assert centre.source.current.path == new                                   # the new slide is opened
    if switch:
        assert app.undo[0][2].label == "Undo switched calls" and "1 deck switched" in app.logged[-1]
        assert list(app.undo[0][2].edits) == [ctx.decks_dir / "talk.tex"]
    else:
        assert not app.undo and "0 decks switched" in app.messages[-1]


@pytest.mark.parametrize("external", [False, True])
def test_preview_save_as_new_waits_for_dirty_edits(branch_centre, branchable, monkeypatch, external):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)

    centre = branch_centre
    current = branchable / CURRENT
    centre.open_file(current)
    editor = centre.source.current.editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("% unsaved edit\n")
    if external:
        current.write_bytes(current.read_bytes() + b"% external edit\n")
    on_disk = current.read_bytes()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, _message: warned.append(title))
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", lambda *a: pytest.fail("Offered to branch stale content"))

    centre.state.set_mode("preview")
    centre.preview._versions._new.click()

    assert warned == ["Edits not saved"]
    assert current.read_bytes() == on_disk and "% unsaved edit" in editor.text()


def test_the_new_slide_sheet_ticks_the_edited_deck_and_checks_the_name(ctx, qapp, branchable):
    talk = ctx.decks_dir / "talk.tex"
    block = ctx.blocks_dir / "talk.tex"
    ctx.blocks_dir.mkdir()
    block.write_text(r"\slide{abc-EN-Demo}")
    talk.write_text(talk.read_text().replace(r"\end{document}", r"\slideblock{talk}" + "\n" + r"\end{document}"))
    (ctx.decks_dir / "archive").mkdir()
    archived = ctx.decks_dir / "archive/talk.tex"
    archived.write_text(talk.read_text().replace(r"\slide{abc-EN-Demo}", ""))
    current = branchable / CURRENT
    cap = slide_versioning.capture(ctx, "new_slide", [current])
    sources = slide_branch.switch_sources(cap, "abc-EN-Demo")
    def preview(name, selected):
        proposal = slide_branch.branch(cap, current, ctx.slide_ids_csv, name, selected)
        return revision_summary(proposal, current, ctx.root)

    sheet = NewSlideVersionSheet(None, "abc-EN-Demo", (1, 2, 0), "Demo", sources, talk, ctx.root, preview)
    assert list(sheet._boxes) == [talk, block]
    assert "Used by decks/archive/talk.tex, decks/talk.tex" in [label.text() for label in sheet.findChildren(QLabel)]
    assert [box.isChecked() for box in sheet._boxes.values()] == [True, False]
    new_id = cap.created.id_slug.removesuffix("-Demo") + "-Demo-2"
    sheet.name_edit.setText("two words")
    sheet._on_ok()
    assert sheet.problem.isVisibleTo(sheet) and not sheet.slug
    sheet.name_edit.setText("Demo-2")
    assert any(f"decks/talk.tex — switches to new slide {new_id}" in label.text() for label in sheet.findChildren(QLabel))
    sheet._boxes[talk].setChecked(False)
    assert not any("switches to new slide" in label.text() for label in sheet.findChildren(QLabel))
    sheet._on_ok()
    assert sheet.slug == "Demo-2" and sheet.sources == [] and sheet.result() == sheet.DialogCode.Accepted


@pytest.fixture
def dialog_centre(ctx, qapp):
    class DialogApp(FakeApp, QWidget):
        def __init__(self):
            QWidget.__init__(self)
            FakeApp.__init__(self, ctx)

    return CentreColumn(DialogApp(), WorkspaceState(ctx))


def test_revision_dialog_shows_conditional_hints(ctx, dialog_centre, second_deck, monkeypatch):
    current = second_deck / CURRENT
    partner = second_deck / "def-DE-Demo-current.tex"
    partner.write_text("%% Translation of: abc-EN-Demo\n" + BODY)
    shown = []

    def inspect(dialog):
        shown.append("\n".join(label.text() for label in dialog.findChildren(QLabel)))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SlideUsageDialog, "exec", inspect)
    assert not dialog_centre.revise("patch", [current])
    partner.unlink()
    assert not dialog_centre.revise("patch", [current])
    current.write_text(current.read_text().replace("1-2-0+", "1-2-0"))
    assert not dialog_centre.revise("patch", [current])
    translation_hint = "Another language may load a matching translation instead."
    compile_hint = "A compile may use the last frozen version; Compile with edits uses the current text."
    assert [translation_hint in text for text in shown] == [True, False, False]
    assert [compile_hint in text for text in shown] == [True, True, False]


def test_single_deck_save_as_new_keeps_the_short_form(ctx, dialog_centre, branchable, monkeypatch):
    def inspect(sheet):
        talk = ctx.decks_dir / "talk.tex"
        sheet._boxes[talk].setChecked(True)
        text = "\n".join(label.text() for label in sheet.findChildren(QLabel))
        assert "switches to new slide" not in text
        assert "A compile may use the last frozen version" in text
        return False

    monkeypatch.setattr(NewSlideVersionSheet, "exec", inspect)
    assert not dialog_centre.revise("new_slide", [branchable / CURRENT])


def test_update_version_can_overwrite_the_edited_version(ctx, dialog_centre, branchable, monkeypatch):
    centre = dialog_centre
    current, frozen = branchable / CURRENT, branchable / FROZEN
    current.write_text(MARKED, encoding="utf-8")
    ctx.archive_dir.mkdir()
    pin = r"\slideversion{abc-EN-Demo}{1-2-0}"
    for path, call in [(ctx.archive_dir / "pinned.tex", f"{pin}\n{pin}"),
                       (ctx.decks_dir / "older.tex", r"\slideversion{abc-EN-Demo}{1-1-0}")]:
        path.write_text(f"\\documentclass{{beamer}}\n\\begin{{document}}\n{call}\n\\end{{document}}\n", encoding="utf-8")
    centre.open_file(current)
    editor = centre.source.current.editor
    edit_and_save(centre, "% a typo fixed\n")
    asked, confirmations = [], []
    monkeypatch.setattr(centre_module, "prompt_version_level", lambda _parent, base: asked.append(base) or "overwrite")
    answers = iter([QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted])

    def confirm(dialog):
        confirmations.append("\n".join(label.text() for label in dialog.findChildren(QLabel)))
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
        assert not dialog.choices()
        return next(answers)

    monkeypatch.setattr(SlideUsageDialog, "exec", confirm)
    before = snapshot(ctx.root)
    centre.revise("update", [current])
    assert len(confirmations) == 1 and "v1.2.0" in confirmations[0]
    assert confirmations[0].count("pinned.tex — keeps v1.2.0: content replaced") == 2
    assert "older.tex" not in confirmations[0]
    assert snapshot(ctx.root) == before
    assert "% a typo fixed" in editor.text() and not editor.is_modified()

    centre.revise("update", [current])
    expected = MARKED + "% a typo fixed\n"
    assert asked == [(1, 2, 0)] * 2 and current.read_text(encoding="utf-8") == expected       # no "+"
    assert frozen.read_text(encoding="utf-8") == expected                                     # same number
    assert not (branchable / "abc-EN-Demo-v1-2-1.tex").exists() and not editor.is_modified()
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    centre.revise("update", [current])                 # nothing changed since: nothing to overwrite
    assert told and "has not changed since v1.2.0" in told[0] and len(asked) == 2


def test_preview_only_reverts_the_selected_slide_in_one_undo_step(centre, branchable, monkeypatch):
    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    selected = branchable / CURRENT
    other = branchable / "other-EN-Example-current.tex"
    other.write_text("other slide")
    centre.open_file(selected)
    centre.state.set_mode("preview")
    centre.source.show_path(other)
    before = selected.read_text()
    monkeypatch.setattr(QMessageBox, "exec", lambda box: next(b for b in box.buttons() if b.text().startswith("Revert")).click())
    centre.preview._versions._revert.click()
    file = centre.source.file_for(selected)
    assert file.dirty and file.editor.text() == (branchable / FROZEN).read_text()
    assert selected.read_text() == before and centre.source.current.editor.text() == "other slide"
    file.editor.undo()
    assert file.editor.text() == before


def test_a_failed_archive_leaves_restore_and_the_editor_untouched(centre, versioned_slide, monkeypatch):
    current = versioned_slide / CURRENT
    selected = versioned_slide / SELECTED
    centre.open_file(current)
    before = current.read_text()
    warned = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    def fail(source, destination):
        raise OSError(f"archive failed: {destination.name}")
    monkeypatch.setattr(fileio.os, "link", fail)
    assert not centre.revise("restore", [selected])
    assert "abc-EN-Demo-v1-2-0.tex" in warned[0]
    assert current.read_text() == centre.source.current.editor.text() == before
    assert not (versioned_slide / FROZEN).exists()


def test_assistant_edits_a_deck_while_the_revision_dialog_is_open(ctx, qapp, second_deck, monkeypatch):
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace

    layout_settings.set(source_file.AUTOSAVE_KEY, False)
    app = BranchApp(ctx)
    app.centre = centre = CentreColumn(app, WorkspaceState(ctx))
    workspace = GuiWorkspace(app)
    current = second_deck / CURRENT
    before = current.read_bytes()
    deck = ctx.decks_dir / "talk.tex"
    centre.open_file(deck)
    raw = deck.read_text()
    def confirm(*_args):
        assert workspace.apply_to_buffer(deck, raw, raw + "% assistant edit") is None
        return True
    warned = []
    monkeypatch.setattr(centre_module, "ask_overwrite", confirm)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    assert not centre.revise("overwrite", [current])
    assert deck.name in warned[0] and deck.read_text() == raw
    assert centre.source.file_for(deck).editor.text() == raw + "% assistant edit"
    assert current.read_bytes() == before


@pytest.mark.parametrize("action", ["patch", "overwrite", "restore", "revert", "new_slide", "batch"])
def test_cancel_preserves_every_file_and_open_buffer(ctx, branch_centre, second_deck, monkeypatch, action):
    centre = branch_centre
    current, selected = second_deck / CURRENT, second_deck / SELECTED
    centre.open_file(current)
    before = snapshot(ctx.root)
    file = centre.source.current
    editor_before = file.editor.text(), file.dirty
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *a: None)
    monkeypatch.setattr(centre_module, "ask_overwrite", lambda *a: False)
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", lambda *a: SimpleNamespace(exec=lambda: False))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: 0)
    assert not centre.revise(action, [selected if action == "restore" else current])
    assert before == snapshot(ctx.root)
    assert centre.source.current is file and (file.editor.text(), file.dirty) == editor_before


@pytest.mark.parametrize("change", ["preferred include", "repeat block"])
def test_stale_approval_of_an_include_is_refused(ctx, centre, branchable, monkeypatch, change):
    current = branchable / CURRENT
    deck = ctx.decks_dir / "talk.tex"
    deck.write_text(deck.read_text().replace(r"\slide{abc-EN-Demo}", r"\input{fragment}" + "\n" + r"\input{fragment}"))
    fragment = ctx.root / "fragment.tex"
    empty = ctx.root / "empty.tex"
    empty.write_bytes(b"% no calls\r\n")
    ctx.blocks_dir.mkdir()
    block = ctx.blocks_dir / "topic.tex"
    block.write_text(r"\slide{abc-EN-Demo}")
    fragment.write_text(r"\slideblock{topic}" + "\n" + r"\input{empty}")
    cap = slide_versioning.capture(ctx, "patch", [current])
    assert [(d, c.source, c.source_start) for d, c in cap.occurrences] == [(deck, block, 0)] * 2
    preferred = ctx.decks_dir / fragment.name
    assert cap.inputs[preferred] is None and cap.inputs[empty] == "% no calls\r\n"
    def confirm(*args):
        if change == "preferred include":
            preferred.write_bytes(fragment.read_bytes())
        else:
            fragment.write_text(fragment.read_text() + "\n" + r"\slideblock{topic}")
        return DeckVersions({block: "keep"}, None)
    asked = []
    monkeypatch.setattr(centre_module, "ask_deck_versions", confirm)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or QMessageBox.StandardButton.Cancel)
    assert not centre.revise("patch", [current])
    assert "Reopen" in asked[0] and not (branchable / "abc-EN-Demo-v1-2-1.tex").exists()
    assert r"\slide{abc-EN-Demo}" in block.read_text()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    empty.write_bytes(b"% invalid \xff")
    assert not centre.revise("patch", [current])
    assert str(empty) in warned[0] and "UTF-8" in warned[0]


def test_partial_branch_reports_the_library_slide_and_switched_file(ctx, branch_centre, branchable, monkeypatch):
    centre = branch_centre
    current = branchable / CURRENT
    deck = ctx.decks_dir / "talk.tex"
    later = ctx.decks_dir / "tutorial.tex"
    before = deck.read_bytes()
    later.write_bytes(before)
    replace = fileio.os.replace
    def fail(source, target):
        if target == ctx.slide_ids_csv:
            deck.write_bytes(deck.read_bytes() + b"% outside edit")
            raise OSError("registry unavailable")
        return replace(source, target)
    warned = []
    monkeypatch.setattr(fileio.os, "replace", fail)
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", lambda *a: SimpleNamespace(exec=lambda: True, slug="Copy", sources=[deck, later]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    assert not centre.revise("new_slide", [current])
    new, = branchable.glob("*-EN-Copy-current.tex")
    assert all(str(p) in warned[0] for p in (new, current, deck))
    assert str(later) not in warned[0] and later.read_bytes() == before
    assert deck.read_text().endswith("% outside edit") and new.name.removesuffix("-current.tex") in deck.read_text()
    assert "% changed" in new.read_text() and "% changed" not in current.read_text()
    assert not centre.revise("new_slide", [current])
    assert "has not changed since" in warned[-1] and list(branchable.glob("*-EN-Copy-current.tex")) == [new]


@pytest.mark.parametrize("block_only, outside_edit", [(False, False), (True, False), (False, True)])
def test_undo_switched_calls_from_the_result(ctx, qapp, branchable, monkeypatch, block_only, outside_edit):
    from PySide6.QtWidgets import QPushButton
    from slidemage.ui.kit.widgets import Toast
    from slidemage.ui.workspace.slide_list import SlideList

    deck = ctx.decks_dir / "talk.tex"
    block = ctx.blocks_dir / "talk.tex"
    ctx.blocks_dir.mkdir()
    block.write_bytes(b"\\slide {abc-EN-Demo}\r\n")
    (ctx.root / "nested.tex").write_text(r"\slideblock{talk}" + "\n" + r"\slideblock{talk}")
    extra = "\n".join([r"\slideversion{abc-EN-Demo}{1-2-0}", r"\input{nested}", r"\end{document}"])
    deck.write_text(deck.read_text().replace(r"\end{document}", extra))
    before = {p: p.read_bytes() for p in (deck, block)}
    selected = [block] if block_only else [deck, block]
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", lambda *a: SimpleNamespace(exec=lambda: True, slug="Copy",
                                                                                   sources=selected))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a[2]))
    app = BranchApp(ctx)
    state = WorkspaceState(ctx)
    app.centre = CentreColumn(app, state)
    app.toast = Toast(app.centre)
    app.slide_list = SlideList(app, state, app.theme, app.toast)
    app.after_deck_edit = lambda path, message: app.slide_list.deck_edited(path, message, None)
    current = branchable / CURRENT
    assert app.centre.revise("new_slide", [current])
    new, = branchable.glob("*-EN-Copy-current.tex")
    new_slug = new.name.removesuffix("-current.tex").encode()
    assert block.read_bytes() == before[block].replace(b"abc-EN-Demo", new_slug)
    assert deck.read_bytes() == (before[deck] if block_only else before[deck].replace(b"abc-EN-Demo", new_slug, 1))
    assert "1 deck switched" in app.logged[-1]
    if outside_edit:
        deck.write_bytes(deck.read_bytes() + b"% outside edit")
    switched = {p: p.read_bytes() for p in before}
    undo, = app.toast.findChildren(QPushButton)
    assert undo.text() == "Undo switched calls"
    undo.click()
    assert {p: p.read_bytes() for p in before} == (switched if outside_edit else before)
    assert bool(errors) == outside_edit
    assert "% changed" in new.read_text() and "% changed" not in current.read_text()
    assert new_slug.split(b"-")[0] in ctx.slide_ids_csv.read_bytes()
    app.slide_list.deleteLater()
    app.centre.deleteLater()


def test_overwrite_and_patch_skip_confirmation_for_one_deck(centre, branchable, monkeypatch):
    current = branchable / CURRENT
    centre.app.adopt_deck_revisions = lambda edits: None
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("no question expected"))
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("no question expected"))
    assert centre.revise("overwrite", [current])
    assert current.read_text(encoding="utf-8") == MARKED + "% changed\n"
    current.write_text(EDITED + "% more\n", encoding="utf-8")
    assert centre.revise("patch", [current])
    assert (branchable / "abc-EN-Demo-v1-2-1.tex").exists()
