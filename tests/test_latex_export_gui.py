# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export LaTeX… command: folder picker, the question about an existing export, the toast, the ⋮ menu's
Export flyout and the palette entry. The picker and every message box are replaced: a real one would wait for a click."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton

from conftest import build_window
from slidemage.ui.workspace import compile_actions


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "slidemage-manual-copy"))
    return window


@pytest.fixture
def dialogs(monkeypatch, tmp_path):
    """The picker returns tmp_path; `asked` collects the questions, `answer` is what they are answered with."""
    state = type("Dialogs", (), {"asked": [], "answer": QMessageBox.StandardButton.Yes, "folder": str(tmp_path)})()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: state.folder)
    monkeypatch.setattr(QMessageBox, "question", lambda _parent, title, text, *a: state.asked.append((title, text)) or state.answer)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: state.asked.append(("critical", args[2])))
    return state


def test_the_command_exports_the_deck_into_the_picked_folder_and_the_toast_offers_to_open_it(window, dialogs, tmp_path):
    assert window.commands.run("export_latex", window)
    folder = tmp_path / "slidemage-manual-copy-latex"
    assert (folder / "slidemage-manual-copy.tex").is_file() and (folder / "slides").is_dir()
    assert dialogs.asked == []
    toast = window.toast
    assert toast.isVisible() and toast.findChild(QLabel).text() == f"Exported to {folder}"
    assert [b.text() for b in toast.findChildren(QPushButton)] == ["Open folder"]


def test_an_existing_export_is_replaced_only_when_the_user_says_yes(window, dialogs, tmp_path):
    folder = tmp_path / "slidemage-manual-copy-latex"
    folder.mkdir()
    (folder / "old.txt").write_text("old", encoding="utf-8")
    dialogs.answer = QMessageBox.StandardButton.No
    compile_actions.export_latex(window, window.state.deck)
    assert [t for t, _ in dialogs.asked] == ["Replace folder"] and (folder / "old.txt").exists()
    assert not (folder / "slidemage-manual-copy.tex").exists()
    dialogs.answer = QMessageBox.StandardButton.Yes
    compile_actions.export_latex(window, window.state.deck)
    assert len(dialogs.asked) == 2 and not (folder / "old.txt").exists() and (folder / "slidemage-manual-copy.tex").is_file()


def test_cancelling_the_picker_does_nothing(window, dialogs, tmp_path):
    dialogs.folder = ""
    compile_actions.export_latex(window, window.state.deck)
    assert list(tmp_path.iterdir()) == [] and dialogs.asked == []


def test_the_toast_action_opens_the_exported_folder(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(compile_actions.open_path, "open_in_default_app", opened.append)
    compile_actions.on_toast_action("undo")
    compile_actions.on_toast_action(compile_actions.OPEN_FOLDER + str(tmp_path))
    assert opened == [str(tmp_path)]


def test_the_command_is_in_the_export_flyout_and_the_palette(window):
    from conftest import filled_menu, menu_actions
    from slidemage.ui.workspace.palette import command_entries

    export = menu_actions(filled_menu(window, "Deck"))["submenu:export"].menu()
    assert [a.objectName() for a in export.actions()] == ["export_pptx", "export_latex"]
    command = window.commands["export_latex"]
    assert command.title(window) == "Export LaTeX…" and command.info(window) == "self-contained · with media folder"
    assert [e.label for e in command_entries(window, ["export", "latex"])] == ["Export LaTeX…"]
