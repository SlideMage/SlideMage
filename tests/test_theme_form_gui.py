# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme form beside a theme's source (ui/workspace/theme_form.py; docs/plans/theme-editor.md, stage C1b): it edits
the editor's buffer as one undo step per change, follows typing in the source after a pause, rebuilds its columns when
the modes change, and a theme file's SourceFile shows it while other files do not."""
from pathlib import Path

from PySide6.QtWidgets import QLabel

from conftest import EXAMPLE_PROJECT
from slidemage.theme_fields import setup_file
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Badge, Chip
from slidemage.ui.workspace import source_file
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.source_file import SourceFile
from slidemage.ui.workspace import theme_workspace
from slidemage.ui.workspace.theme_form import ThemeForm, _Cell, theme_key

ROOT = Path(__file__).resolve().parents[1]
MODESHAPE = ROOT / "tests" / "fixtures" / "theme_files" / "SlideMage_template_modeshape.tex"
CONDSHAPE = ROOT / "tests" / "fixtures" / "theme_files" / "SlideMage_template_condshape.tex"
SETUP = ROOT / "latex" / "SlideMage_setup.tex"


def make_form(path: Path, text: str | None = None):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(text if text is not None else path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    form = ThemeForm(editor, path, ROOT / "example", SETUP)
    return editor, form


def cell_for(form: ThemeForm, key: str, mode: str) -> _Cell:
    """The cell that reads `key` (a palette colour or a role) in `mode`: its reader's bound defaults."""
    for cell in form._cells:
        if (cell.read.__defaults__ or ()) == (key, mode):
            return cell
    raise AssertionError(f"no cell for {key} in {mode!r}")


def test_theme_key():
    assert theme_key(Path("SlideMage_template_my-look.tex")) == "my-look"
    assert theme_key(Path("deck.tex")) == "" and theme_key(Path("SlideMage_template_x.bib")) == ""


def test_a_palette_edit_is_one_line_and_one_undo_step(qapp):
    editor, form = make_form(MODESHAPE)
    before = editor.text()
    cell = cell_for(form, "c_primary_highlight", "light")
    assert cell.edit.text() == "#e0a000"
    cell.edit.setText("#ff0000")
    cell._commit()
    after = editor.text()
    assert "\\definecolor{c_primary_highlight}{HTML}{ff0000}" in after
    assert len([a for a, b in zip(before.split("\n"), after.split("\n")) if a != b]) == 1
    assert editor.is_modified()
    editor.undo()
    assert editor.text() == before


def test_a_dark_value_and_follow(qapp):
    editor, form = make_form(MODESHAPE)
    form.set_mode("dark")                 # the form shows one mode at a time: the mode bar's pick
    cell = cell_for(form, "c_custom_red", "dark")
    assert cell.tag.text() == "set here" and not cell.reset.isHidden()
    assert cell.edit.text() == "#ff6b6b"
    cell.edit.setText("")
    cell._commit()                     # empty: the line goes, the base colour applies
    assert "\\SMSetColor{c_custom_red}" not in editor.text()
    cell.update_value()
    assert cell.edit.text() == "" and cell.edit.placeholderText() == "#b00000"
    assert cell.tag.text() == "from Light" and cell.reset.isHidden()


def test_role_cells_offer_the_palette_and_write_per_mode(qapp):
    editor, form = make_form(MODESHAPE)
    form.set_mode("dark")
    cell = cell_for(form, "title_fill", "dark")
    assert cell.combo is not None and cell.combo.findText("c_test_dark_canvas") > 0
    cell.combo.setCurrentText("c_test_dark_canvas")
    cell._commit()
    assert "\\SMSetRole{title_fill}{dark}{c_test_dark_canvas}" in editor.text()


def test_typing_in_the_source_shows_in_the_form_after_a_pause(qapp):
    editor, form = make_form(MODESHAPE)
    editor.patch_text(editor.text().replace("{HTML}{e0a000}", "{HTML}{00ff00}"))
    assert form._timer.isActive()
    form._timer.stop()
    form._from_source()
    assert cell_for(form, "c_primary_highlight", "light").edit.text() == "#00ff00"


def test_adding_a_mode_and_picking_it(qapp, monkeypatch):
    editor, form = make_form(CONDSHAPE)
    assert [m.id for m in form.model.modes()] == [""] and form.mode == ""
    told = []
    form.on_structure = lambda: told.append(form.mode)
    form.apply(lambda: form.model.add_mode("dark", "dark", "Dark slides"))
    assert "% SlideMage modes: light, dark=Dark slides" in editor.text()
    assert form.mode == "light" and told        # the base mode is picked; the mode bar is told
    form.set_mode("dark")
    assert cell_for(form, "c_primary_highlight", "dark").tag.text() == "from Light"
    banner = [c for c in form.findChildren(Chip) if c.text().startswith("Contrast in Dark slides")]
    assert banner
    form._toggle_checks()
    badges = form.findChildren(Badge)
    assert len(badges) == 16 and all(b.text() for b in badges)


def test_a_file_the_form_cannot_read_says_so(qapp):
    editor, form = make_form(MODESHAPE, "\\documentclass{beamer}\n")
    texts = " ".join(label.text() for label in form.findChildren(QLabel))
    assert "no theme the form can read" in texts
    assert form._cells == []


def test_a_read_only_buffer_is_not_edited(qapp):
    editor, form = make_form(MODESHAPE)
    editor.set_read_only(True)
    before = editor.text()
    form.apply(lambda: form.model.set_name("x"))
    assert editor.text() == before


def test_a_theme_file_shows_the_form_and_a_deck_does_not(qapp, tmp_path, monkeypatch):
    shown = {}
    monkeypatch.setattr(source_file.layout_settings, "get", lambda key, default=None: shown.get(key, default))
    monkeypatch.setattr(source_file.layout_settings, "set", lambda key, value: shown.__setitem__(key, value))
    app = type("App", (), {"theme": ThemeManager(), "project": EXAMPLE_PROJECT})()
    theme = tmp_path / "SlideMage_template_probe.tex"
    theme.write_text(MODESHAPE.read_text(encoding="utf-8"), encoding="utf-8")
    deck = tmp_path / "deck.tex"
    deck.write_text("\\documentclass{beamer}\n", encoding="utf-8")
    monkeypatch.setattr(theme_workspace.layout_settings, "get", lambda key, default=None: shown.get(key, default))
    monkeypatch.setattr(theme_workspace.layout_settings, "set", lambda key, value: shown.__setitem__(key, value))
    with_form = SourceFile(app, theme)
    side = with_form.theme_side
    assert with_form.theme_form is side.form and with_form.theme_sample is side.sample
    assert with_form.theme_sample.key == "probe" and side.view == "form"
    assert side.form.isVisibleTo(side) and side.sample.isVisibleTo(side) and not with_form.editor.isVisibleTo(side)
    assert list(side.mode_bar.buttons) == ["light", "dark"] and side.mode_bar.buttons["light"].isChecked()
    side.pick_mode("dark")
    assert side.form.mode == "dark" and side.sample.mode == "dark" and side.mode_bar.buttons["dark"].isChecked()
    side.set_view("split")
    assert with_form.editor.isVisibleTo(side) and not side.sample.isVisibleTo(side)
    side.set_view("source")
    assert not side.form.isVisibleTo(side) and shown[theme_workspace.VIEW_KEY] == "source"
    assert SourceFile(app, deck).theme_form is None
    assert setup_file(EXAMPLE_PROJECT.root) is not None
