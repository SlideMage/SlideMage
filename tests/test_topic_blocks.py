# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A section becomes a block; another deck links to those exact calls."""
import pytest

from slidemage import deck_scan, fileio, topic_blocks
from slidemage.project import ProjectContext
from slidemage.fileio import read_text_exact as read
from slidemage.ui.workspace import slide_list as module
from test_slide_list_gui import choose_section, make_list  # noqa: F401 -- fixture


def test_section_becomes_a_block_and_another_deck_reuses_it(make_list, ctx, monkeypatch):
    calls = [
        r"\slide{aaa-First}", r"\slideversion{bbb-Second}{1-2-0}",
        r"\omitslide{ccc-Third}", r"\omitslideversion{ddd-Fourth}{2-0-0}",
        r"\slidefinal{eee-Fifth}", r"\conditionalslide[instructor]{fff-Sixth}",
        r"\slidestep{ggg-Seventh}[during-course]{1-2}",
    ]
    body = "\n".join("\t" + call + " % keep this comment" for call in calls) + "\n"
    slide_list, window, path = make_list("\\section{Literaturrecherche}\n% Notes\n" + body,
                                          newline="\r\n")
    ctx.decks_dir.mkdir()
    deck_path = path.rename(ctx.decks_dir / path.name)
    window.state.set_deck(deck_scan.read_deck(deck_path))
    ctx.blocks_dir.mkdir()
    collision = ctx.blocks_dir / "literaturrecherche.tex"
    collision.write_text("\\definecolor{accent}{RGB}{1,2,3}\n")
    choose_section(slide_list, "Literaturrecherche")
    before = read(deck_path)
    asked = []

    def approve(_parent, _caption, message, *_args):
        asked.append(message)
        return module.QMessageBox.StandardButton.Yes

    def title(_parent, _caption, _label, **kwargs):
        assert len(asked) == 1   # the single approval precedes the title prompt
        assert kwargs["text"] == "Literaturrecherche"
        return kwargs["text"], True

    monkeypatch.setattr(module.QMessageBox, "question", approve)
    monkeypatch.setattr(module.QInputDialog, "getText", title)
    # A prior one-file edit must not let Undo restore a deck from before the conversion.
    slide_list._undo[deck_path] = [before]
    slide_list._undo_order.append((deck_path, deck_path))
    menu = slide_list._section_menu()
    assert "Make this section a block" in [entry[2] for entry in menu._entries if entry[0] == "item"]
    menu.triggered.emit("make_block")
    assert slide_list._block_work.wait(5000)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert slide_list._block_work.wait(5000)
    QApplication.processEvents()
    block = ctx.blocks_dir / "Literaturrecherche-2.tex"
    block_before = block.read_bytes()
    assert block_before.decode() == "\r\n".join(["%% SlideMage block: Literaturrecherche", *calls, ""])
    expected = before.replace(calls[0], r"\slideblock{Literaturrecherche-2}")
    for call in calls[1:]:
        expected = expected.replace(call, "")
    assert read(deck_path) == expected
    assert str(deck_path) in asked[0] and str(ctx.blocks_dir) in asked[0]
    assert block.name in asked[0] and "cannot be undone" in asked[0]
    slide_list.undo()
    assert read(deck_path) == expected

    second = ctx.decks_dir / "second.tex"
    second.write_text("\\begin{document}\n\\section{Another title}\n% Different notes\n"
                      + "\n\n".join(calls) + "\n\\end{document}\n")
    deck = deck_scan.read_deck(second)
    assert topic_blocks.make_block(ctx, deck, deck.chapters[0], "Another title") == block
    assert "\\section{Another title}\n% Different notes\n\\slideblock{Literaturrecherche-2}" in read(second)
    assert block.read_bytes() == block_before
    assert sorted(path.name for path in ctx.blocks_dir.glob("*.tex")) == [block.name, collision.name]
    assert not make_list.errors


def test_block_commit_rolls_back_and_refuses_case_collisions(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.decks_dir.mkdir()
    deck = ctx.decks_dir / "course.tex"
    before = "\\section{Topic}\n\\slide{aaa-First}\n"
    deck.write_text(before)
    snapshot = deck_scan.read_deck(deck)
    write = fileio.write_text_exact

    def fail(path, *args, **kwargs):
        if path == deck:
            raise OSError("disk full")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(fileio, "write_text_exact", fail)
    with pytest.raises(OSError, match="Restored all files"):
        topic_blocks.make_block(ctx, snapshot, snapshot.chapters[0], "Topic")
    assert deck.read_text() == before and not list(ctx.blocks_dir.glob("*.tex"))
    target, text = topic_blocks.prepare_calls_block(ctx, [r"\slide{aaa-First}"], "Research")
    (ctx.blocks_dir / "research.tex").write_text(r"\slide{bbb-Other}")
    with pytest.raises(fileio.StaleFileError, match="collides"):
        topic_blocks.commit_block(ctx, target, text)
    target.write_text(text)
    with pytest.raises(ValueError, match="collide ignoring case"):
        topic_blocks.read_blocks(ctx)
