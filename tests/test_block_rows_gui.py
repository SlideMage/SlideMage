# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Linked rows edit the block, and cannot cross its boundary."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from slidemage import deck_scan
from slidemage.fileio import read_text_exact as read
from slidemage.ui.workspace.slide_list import ABOVE_ITEM, BELOW_ITEM
from slidemage.ui.workspace.slide_tree import BLOCK
from test_slide_list_gui import make_list, ids, item_of  # noqa: F401 -- fixture


@pytest.fixture
def block_list(make_list, ctx):
    slide_list, window, path = make_list(
        "\\section{Linked}\n\\slideblock{topic}\n"
        "\\section{Ordinary}\n\\slide{ccc-Plain}\n")
    ctx.decks_dir.mkdir(exist_ok=True)
    deck = path.rename(ctx.decks_dir / path.name)
    ctx.blocks_dir.mkdir(exist_ok=True)
    block = ctx.blocks_dir / "topic.tex"
    block.write_text("%% SlideMage block: Shared topic\n\\slide{aaa-First}\n\\slide{bbb-Second}\n")
    window.state.set_deck(deck_scan.read_deck(deck))
    yield slide_list, window, deck, block


def test_reorder_writes_only_the_block_and_ctrl_z_restores_it(block_list, qapp, make_list):
    slide_list, window, deck, block = block_list
    before, block_before = read(deck), read(block)
    header = slide_list.tree.section_items()[0]
    assert header.data(0, BLOCK).title == "Shared topic"
    assert header.childCount() == 2
    assert slide_list.blocks[block] == "Shared topic"
    first, second = [slide_list.tree.data_of(item_of(slide_list, slide_id)) for slide_id in ("aaa", "bbb")]
    slide_list.tree.moved.emit([second], first, ABOVE_ITEM)
    qapp.processEvents()
    assert read(deck) == before
    assert read(block) == block_before.replace("\\slide{aaa-First}\n\\slide{bbb-Second}",
                                               "\\slide{bbb-Second}\n\\slide{aaa-First}")
    assert ids(slide_list) == ["bbb", "aaa", "ccc"]
    slide_list.show()
    slide_list.activateWindow()
    slide_list.tree.setFocus()
    qapp.processEvents()
    QTest.keyClick(slide_list.tree, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert read(block) == block_before
    assert read(deck) == before
    assert ids(slide_list) == ["aaa", "bbb", "ccc"]
    assert not make_list.errors
    from slidemage.ui.workspace.panels.versions import SlideVersions
    panel = SimpleNamespace(_pinnable=lambda: [slide_list.rows()[0].deck_call], state=window.state,
                            actions=SimpleNamespace(edit_deck=slide_list.edit))
    SlideVersions._set_pin(panel, "aaa-First", "1-0-0")
    assert "\\slideversion{aaa-First}{1-0-0}" in read(block)
    assert read(deck) == before
    SlideVersions._set_pin(panel, "aaa-First", None)
    assert read(block) == block_before


def test_drag_across_the_block_edge_changes_nothing(block_list, qapp):
    slide_list, window, deck, block = block_list
    before = read(deck), read(block)
    slide_list.toast.show_message = Mock()
    first, plain = [slide_list.tree.data_of(item_of(slide_list, slide_id)) for slide_id in ("aaa", "ccc")]
    section = slide_list.tree.data_of(slide_list.tree.section_items()[0])
    for sources, target in (([first], plain), ([plain], first),
                            ([first], section)):
        slide_list.tree.moved.emit(sources, target, BELOW_ITEM)
        qapp.processEvents()
        assert (read(deck), read(block)) == before
        slide_list.toast.show_message.assert_called_with(
            "Moving a slide out of a topic block is refused. Unlink the block first.")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("marker", [r"\slideblock{topic}", r"\input{blocks/topic}", r"\include{blocks/topic.tex}"])
def test_unlink_then_undo_restores_exact_deck_text(block_list, make_list, monkeypatch, newline, marker):
    slide_list, window, deck, block = block_list
    before = read(deck).replace("\\slideblock{topic}", "\t" + marker).replace("\n", newline)
    deck.write_bytes(before.encode())
    window.state.set_deck(deck_scan.read_deck(deck))
    slide_list.rebuild()
    block_before = block.read_bytes()
    menus = []
    monkeypatch.setattr(slide_list, "_popup", lambda menu, *_args: menus.append(menu))
    header = slide_list.tree.section_items()[0]
    slide_list.tree.block_menu.emit(header.data(0, BLOCK), QPoint())
    menu = menus[0]
    assert [entry[2] for entry in menu._entries if entry[0] == "item"] == [
        "Unlink", "Remove from deck", "Show in Library"]
    menu.triggered.emit("unlink")
    body = newline.join("\t" + line for line in block_before.decode().splitlines()
                       if not line.startswith("%%")) + newline
    assert read(deck) == before.replace("\t" + marker + newline,
                                        "\t% from block topic" + newline + body)
    assert ids(slide_list) == ["aaa", "bbb", "ccc"]
    assert block.read_bytes() == block_before
    slide_list.undo()
    assert deck.read_bytes() == before.encode()
    assert block.read_bytes() == block_before
    assert slide_list.tree.section_items()[0].data(0, BLOCK) is not None
    assert not make_list.errors


@pytest.mark.parametrize("source", ["block", "deck"])
def test_stale_repeated_rows_refuse_edits(block_list, make_list, source, monkeypatch):  # noqa: F811 -- fixture
    from slidemage import deck_editor, deck_language

    listing, window, deck, block = block_list
    path = block if source == "block" else deck
    original = "\\slideversion{aaa-First}{1-0-0}\n\\slideversion{aaa-First}{2-0-0}\n"
    if source == "deck":
        original = "\\begin{document}\n" + original + "\\end{document}\n"
    path.write_text(original)
    window.state.set_deck(deck_scan.read_deck(deck))
    listing.rebuild()
    rows = [r.deck_call for r in listing.rows() if r.call.id == "aaa"]
    parse = Mock(wraps=deck_language.calls_in)
    monkeypatch.setattr(deck_language, "calls_in", parse)
    physical = deck_language.source_calls(deck_scan.read_deck(path), rows)
    assert parse.call_count == 1
    assert [c.version for c in physical] == ["1-0-0", "2-0-0"]
    changed = "% Nextcloud insertion\n" + original
    path.write_text(changed)
    assert not listing.edit_calls("Remove failed", "Removed", [rows[1]], deck_editor.remove_slide_calls)
    assert read(path) == changed
    assert ("Refresh the slide list" if source == "block" else "reload the deck") in make_list.errors[-1]
