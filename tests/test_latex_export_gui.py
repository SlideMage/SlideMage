# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""LaTeX export and confirmation before replacing an existing folder."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from conftest import build_window, wait_until
from slidemage.ui.workspace import compile_actions


@pytest.fixture
def window(qapp, monkeypatch):
    window = build_window(monkeypatch)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "slidemage-manual-copy"))
    return window


@pytest.fixture
def dialogs(monkeypatch, tmp_path):
    state = type("Dialogs", (), {"asked": [], "answer": QMessageBox.StandardButton.Yes, "folder": str(tmp_path)})()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: state.folder)
    monkeypatch.setattr(QMessageBox, "question", lambda _parent, title, text, *a: state.asked.append((title, text)) or state.answer)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: state.asked.append(("critical", args[2])))
    return state


def test_the_command_exports_the_deck_into_the_picked_folder_and_the_toast_offers_to_open_it(window, dialogs, tmp_path):
    folder_choice, dialogs.folder = dialogs.folder, ""
    compile_actions.export_latex(window, window.state.deck)
    assert not list(tmp_path.iterdir()) and not dialogs.asked
    dialogs.folder = folder_choice
    assert window.commands.run("export_latex", window)
    wait_until(window.toast.isVisible)
    folder = tmp_path / "slidemage-manual-copy-latex"
    assert (folder / "slidemage-manual-copy.tex").is_file() and (folder / "slides").is_dir()
    assert dialogs.asked == []
    toast = window.toast
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
    wait_until(window.toast.isVisible)
    assert len(dialogs.asked) == 2 and not (folder / "old.txt").exists() and (folder / "slidemage-manual-copy.tex").is_file()


def test_the_toast_action_opens_the_exported_folder(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(compile_actions.open_path, "open_in_default_app", opened.append)
    compile_actions.on_toast_action("undo")
    compile_actions.on_toast_action(compile_actions.OPEN_FOLDER + str(tmp_path))
    assert opened == [str(tmp_path)]
