# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A slide's frozen versions in the centre column: making one the current version, and Update
Version of the current one (the Slide versions panel is in test_side_panels_gui.py)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QLabel, QMessageBox

from slidemage import alt_images
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.centre import CentreColumn
from slidemage.ui.workspace.details_view import DetailsPane
from slidemage.ui.workspace.state import WorkspaceState


BODY = "\\begin{standardframe}{Demo}\nText\n\\end{standardframe}\n"


class FakeApp:
    def __init__(self, project):
        self.project = project
        self.theme = ThemeManager()
        self.logged = []
        self.opened = []

    def log(self, line):
        self.logged.append(line)

    def open_slide_editor(self, path, **_kwargs):
        self.opened.append(path)


@pytest.fixture
def versioned_slide(tmp_path, monkeypatch):
    """A slide with two frozen versions, in a throwaway slides/ folder."""
    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / "abc-EN-Demo-current.tex").write_text("\\setSlideVersion{1-2-0}\n" + BODY, encoding="utf-8")
    for version in ("1-0-0", "1-1-0"):
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(
            f"\\setSlideVersion{{{version}}}\n" + BODY.replace("Text", f"Text of {version}"), encoding="utf-8")
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    return slides


def test_making_a_version_current_archives_the_current_one_and_reopens_it(ctx, qapp, versioned_slide, monkeypatch):
    app = FakeApp(ctx)
    centre = CentreColumn(app, WorkspaceState(ctx))
    answers = iter([QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: next(answers))
    centre.restore_version(versioned_slide / "abc-EN-Demo-v1-0-0.tex")
    current = (versioned_slide / "abc-EN-Demo-current.tex").read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-3-0}" in current          # the restored content gets a new, higher version
    assert (versioned_slide / "abc-EN-Demo-v1-2-0.tex").exists()    # what was current is archived
    assert any(line.startswith("Restored abc-EN-Demo-v1-0-0.tex") for line in app.logged)
    assert centre.source.current.path == versioned_slide / "abc-EN-Demo-current.tex"


def test_making_a_version_current_saves_the_edits_first_and_archives_them(ctx, qapp, versioned_slide, monkeypatch):
    centre = CentreColumn(FakeApp(ctx), WorkspaceState(ctx))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.open_file(current)
    centre.source.current.editor.moveCursor(QTextCursor.MoveOperation.End)
    centre.source.current.editor.insertPlainText("x")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    centre.restore_version(versioned_slide / "abc-EN-Demo-v1-0-0.tex")
    # The edit was saved (1.2.0 frozen first), then archived as 1.2.1; the restored content is 1.3.0.
    assert (versioned_slide / "abc-EN-Demo-v1-2-0.tex").read_text(encoding="utf-8") == "\\setSlideVersion{1-2-0}\n" + BODY
    assert "standardframe}\nx" in (versioned_slide / "abc-EN-Demo-v1-2-1.tex").read_text(encoding="utf-8")
    text = current.read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-3-0}" in text and "Text of 1-0-0" in text


def test_making_a_version_current_is_refused_while_the_edits_cannot_be_saved(ctx, qapp, versioned_slide, monkeypatch):
    centre = CentreColumn(FakeApp(ctx), WorkspaceState(ctx))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.open_file(current)
    centre.source.current.editor.insertPlainText("x")
    current.write_text("\\setSlideVersion{1-2-0}\nsomeone else's\n", encoding="utf-8")
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("must not ask"))
    centre.restore_version(versioned_slide / "abc-EN-Demo-v1-0-0.tex")
    assert len(told) == 1 and "could not be saved (it changed on disk)" in told[0]
    assert "x" in centre.source.current.editor.text() and "someone else's" in current.read_text(encoding="utf-8")


def test_update_version_makes_the_current_content_a_version(ctx, qapp, versioned_slide, monkeypatch):
    app = FakeApp(ctx)
    centre = CentreColumn(app, WorkspaceState(ctx))
    changed = []
    centre.versions_changed.connect(lambda: changed.append(True))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.freeze_version("abc-EN-Demo", "minor")     # 1.2.0, saved the old way, is not frozen yet: as it is
    assert current.read_text(encoding="utf-8") == "\\setSlideVersion{1-2-0}\n" + BODY
    assert (versioned_slide / "abc-EN-Demo-v1-2-0.tex").read_text(encoding="utf-8") == "\\setSlideVersion{1-2-0}\n" + BODY
    assert app.logged == ["abc-EN-Demo is now v1.2.0, frozen as abc-EN-Demo-v1-2-0.tex"] and changed == [True]

    centre.open_file(current)
    editor = centre.source.current.editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("% more\n")
    centre.freeze_version("abc-EN-Demo", "minor")     # the edit is saved ("+"), then made 1.3.0
    text = current.read_text(encoding="utf-8")
    assert text == "\\setSlideVersion{1-3-0}\n" + BODY + "% more\n"
    assert (versioned_slide / "abc-EN-Demo-v1-3-0.tex").read_text(encoding="utf-8") == text
    assert editor.text() == text and not editor.is_modified()
    editor.undo()                                       # the buffer kept its undo history
    assert "1-3-0" not in editor.text()


def test_update_version_asks_what_the_decks_do_and_cancelling_changes_nothing(ctx, qapp, versioned_slide, monkeypatch):
    from slidemage.ui.dialogs.slide_usage_dialog import DeckVersions
    from slidemage.ui.workspace import centre as centre_module

    app = FakeApp(ctx)
    centre = CentreColumn(app, WorkspaceState(ctx))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    (versioned_slide / "abc-EN-Demo-v1-2-0.tex").write_text("\\setSlideVersion{1-2-0}\n" + BODY, encoding="utf-8")
    current.write_text("\\setSlideVersion{1-2-0+}\n" + BODY + "% changed\n", encoding="utf-8")
    before = current.read_bytes()
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *args: None)
    centre.freeze_version("abc-EN-Demo", "patch")
    assert current.read_bytes() == before and app.logged == []

    applied = []
    monkeypatch.setattr(centre_module, "ask_deck_versions", lambda *args: DeckVersions({"course": "keep"}, None))
    monkeypatch.setattr(centre_module, "apply_deck_versions", lambda *args: applied.append(args[1:]))
    centre.freeze_version("abc-EN-Demo", "patch")
    assert applied == [("abc-EN-Demo", {"course": "keep"}, (1, 2, 0))]   # "keep" pins the version moved on from
    assert (versioned_slide / "abc-EN-Demo-v1-2-1.tex").exists()


def test_update_version_is_refused_without_a_change_or_when_the_version_exists(ctx, qapp, versioned_slide, monkeypatch):
    centre = CentreColumn(FakeApp(ctx), WorkspaceState(ctx))
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.freeze_version("abc-EN-Demo", "minor")
    centre.freeze_version("abc-EN-Demo", "minor")
    assert "has not changed since v1.2.0" in told[-1]
    current.write_text("\\setSlideVersion{1-2-0+}\nchanged\n", encoding="utf-8")
    (versioned_slide / "abc-EN-Demo-v1-3-0.tex").write_text("taken", encoding="utf-8")
    centre.freeze_version("abc-EN-Demo", "minor")
    assert "frozen already" in told[-1] and "1-3-0" not in current.read_text(encoding="utf-8")


def test_details_survive_a_slide_without_a_file_and_show_a_message_without_a_slide(ctx, qapp, versioned_slide):
    details = DetailsPane(FakeApp(ctx), WorkspaceState(ctx), lambda path: False)
    details.show_slide("zzz-EN-Gone", None)            # no file: the facts are empty, nothing raises
    details.show_slide("", None, "Select a slide")
    assert [label.text() for label in details.findChildren(QLabel)] == ["Select a slide"]


@pytest.mark.parametrize("level,version", [("patch", "1-2-1"), ("minor", "1-3-0"), ("major", "2-0-0"),
                                          (None, "1-2-0+")])
def test_selected_versions_share_one_choice_and_leave_other_slides_alone(ctx, qapp, tmp_path, monkeypatch,
                                                                         level, version):
    from types import SimpleNamespace
    from slidemage.ui.workspace import centre as module

    slides = tmp_path / "slides"
    slides.mkdir()
    original = "\\setSlideVersion{1-2-0+}\n" + BODY
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

    monkeypatch.setattr(module, "QMessageBox", Choice)
    centre.update_selected_versions()
    assert len(prompts) == 1 and "2 slide(s) selected" in prompts[0].text()
    for slug in slugs[:2]:
        assert f"\\setSlideVersion{{{version}}}" in (slides / f"{slug}-current.tex").read_text()
        assert (slides / f"{slug}-v{version}.tex").exists() == (level is not None)
    assert (slides / f"{slugs[2]}-current.tex").read_text() == original
    assert len(updated) == (2 if level is not None else 0)
    centre.deleteLater()


# -- Update version → New slide… (v8.58.0) ---------------------------------------------------------------------

class BranchApp(FakeApp):
    def __init__(self, project):
        super().__init__(project)
        self.refreshed = []

    def after_version_updates(self, paths):
        self.refreshed.append(("versions", [p.name for p in paths]))

    def after_deck_edit(self, path, summary, previous_text=None):
        self.refreshed.append(("deck", path.name))

    def refresh_open_deck_editors(self):
        self.refreshed.append(("decks",))


@pytest.fixture
def branchable(ctx, versioned_slide):
    """abc is edited since 1.2.0 (frozen), and the deck talk follows it."""
    (versioned_slide / "abc-EN-Demo-v1-2-0.tex").write_text("\setSlideVersion{1-2-0}\n" + BODY, encoding="utf-8")
    (versioned_slide / "abc-EN-Demo-current.tex").write_text("\setSlideVersion{1-2-0+}\n" + BODY + "% changed\n",
                                                            encoding="utf-8")
    (ctx.root / "slide_ids.csv").write_text('"id"\r\n"abc"\r\n', encoding="utf-8", newline="")
    ctx.decks_dir.mkdir()
    (ctx.decks_dir / "talk.tex").write_text(
        "\documentclass{beamer}\n\begin{document}\n\slide{abc-EN-Demo}\n\end{document}\n", encoding="utf-8")
    return versioned_slide


def test_update_version_can_save_the_changes_as_a_new_slide(ctx, qapp, branchable, monkeypatch):
    from slidemage.ui.workspace import centre as centre_module

    app = BranchApp(ctx)
    centre = CentreColumn(app, WorkspaceState(ctx))
    offered = []

    class Sheet:
        def __init__(self, parent, id_slug, version, slug, decks, edited):
            offered.append((id_slug, version, slug, decks, edited))
            self.slug, self.decks = "Demo-revised", ["talk"]

        def exec(self):
            return True

    monkeypatch.setattr(centre_module, "prompt_version_level", lambda *a: centre_module.NEW_SLIDE)
    monkeypatch.setattr(centre_module, "NewSlideVersionSheet", Sheet)
    centre.update_version("abc-EN-Demo")
    assert offered == [("abc-EN-Demo", (1, 2, 0), "Demo", [("talk", 1)], None)]
    new = next(p for p in branchable.glob("*-EN-Demo-revised-current.tex"))
    assert "% changed" in new.read_text(encoding="utf-8")
    assert "% changed" not in (branchable / "abc-EN-Demo-current.tex").read_text(encoding="utf-8")
    assert f"\slide{{{new.name[:-len('-current.tex')]}}}" in (ctx.decks_dir / "talk.tex").read_text(encoding="utf-8")
    assert centre.source.current.path == new                                   # the new slide is opened
    assert ("decks",) in app.refreshed and any(line.startswith("    talk: 1 call(s)") for line in app.logged)


def test_the_new_slide_sheet_ticks_the_edited_deck_and_checks_the_name(qapp):
    from slidemage.ui.dialogs.new_slide_version import NewSlideVersionSheet

    sheet = NewSlideVersionSheet(None, "abc-EN-Demo", (1, 2, 0), "Demo", [("talk", 1), ("course", 2)], "talk")
    assert [box.isChecked() for box in sheet._boxes.values()] == [True, False]
    sheet.name_edit.setText("two words")
    sheet._on_ok()
    assert sheet.problem.isVisibleTo(sheet) and not sheet.slug
    sheet.name_edit.setText("Demo-2")
    sheet._on_ok()
    assert sheet.slug == "Demo-2" and sheet.decks == ["talk"]


def test_update_version_can_overwrite_the_version_the_changes_were_made_to(ctx, qapp, versioned_slide, monkeypatch):
    from slidemage.ui.workspace import centre as centre_module

    app = FakeApp(ctx)
    centre = CentreColumn(app, WorkspaceState(ctx))
    current = versioned_slide / "abc-EN-Demo-current.tex"
    centre.freeze_version("abc-EN-Demo", "minor")      # 1.2.0 frozen as it is
    centre.open_file(current)
    editor = centre.source.current.editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("% a typo fixed\n")
    asked = []
    monkeypatch.setattr(centre_module, "prompt_version_level", lambda _parent, base: asked.append(base) or "overwrite")
    centre.update_version("abc-EN-Demo")
    expected = "\\setSlideVersion{1-2-0}\n" + BODY + "% a typo fixed\n"
    assert asked == [(1, 2, 0)] and current.read_text(encoding="utf-8") == expected            # no "+"
    assert (versioned_slide / "abc-EN-Demo-v1-2-0.tex").read_text(encoding="utf-8") == expected   # same number
    assert not (versioned_slide / "abc-EN-Demo-v1-2-1.tex").exists() and not editor.is_modified()
    assert app.logged[-1] == "Overwrote v1.2.0 of abc-EN-Demo with its current content"
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    centre.update_version("abc-EN-Demo")                 # nothing changed since: nothing to overwrite
    assert told and "has not changed since v1.2.0" in told[0] and len(asked) == 1
