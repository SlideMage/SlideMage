"""Slide blocks (blocks.py): curated slide groups stamped into decks.

Everything here runs against temporary directories -- blocks.BLOCKS_DIR and
friends are monkeypatched, so nothing is ever written into example/.
"""
import pytest

from slidemage import blocks, deck_editor, slide_rename, unused_content
from slidemage.deck_scan import Deck

DECK_TEXT = (
    "\\documentclass{beamer}\r\n\\begin{document}\r\n"
    "\t\\slide{aaa-EN-First}\r\n\t\\slide{bbb-EN-Second}\r\n"
    "\\end{document}\r\n"
)


def _deck(path, text):
    path.write_bytes(text.encode("utf-8"))
    begin = text.find("\\begin{document}")
    return Deck(
        name=path.stem, path=path, archived=False, text=text, supports_version=False,
        uses_biblatex=False,
        preamble_end=begin + len("\\begin{document}") if begin != -1 else None,
        chapters=[], output_folders={}, tags=[],
    )


@pytest.fixture
def blocks_dir(tmp_path, monkeypatch):
    blocks_dir = tmp_path / "blocks"
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    monkeypatch.setattr(blocks, "BLOCKS_DIR", blocks_dir)
    monkeypatch.setattr(blocks, "DECKS_DIR", decks_dir)
    monkeypatch.setattr(blocks, "ARCHIVE_DIR", decks_dir / "archive")
    return blocks_dir


def test_create_scan_and_validate_names(blocks_dir):
    assert blocks.scan_blocks() == []
    blocks.create_block("sampling-methods")
    assert [b.name for b in blocks.scan_blocks()] == ["sampling-methods"]
    assert blocks.scan_blocks()[0].call_count == 0

    assert blocks.name_problem("sampling-methods")  # exists already
    for bad in ("", "-leading-hyphen", "has space", "slash/name", "back\\slash"):
        assert blocks.name_problem(bad), bad
    with pytest.raises(ValueError):
        blocks.create_block("has space")


def test_stamp_then_find_span_round_trips(blocks_dir, tmp_path):
    blocks.write_block("about-me", ["\\slide{ccc-EN-Me}", "\\slide{ddd-EN-Work}"])
    block = blocks.read_block(blocks.block_path("about-me"))
    deck = _deck(tmp_path / "decks" / "course.tex", DECK_TEXT)

    insert_at, indent = deck_editor.append_position(deck)
    new_text = deck_editor.insert_text(
        deck.path, deck.text, insert_at, blocks.stamp_text(block, indent, "\r\n")
    )

    assert "\t%% Block: about-me\r\n\t%%\r\n\t\\slide{ccc-EN-Me}\r\n" in new_text
    assert "\t%% End block: about-me\r\n\t%%\r\n\\end{document}" in new_text
    assert b"\r\n" in deck.path.read_bytes() and b"\n\n" not in deck.path.read_bytes()

    spans = blocks.find_spans(new_text)
    assert [s.name for s in spans] == ["about-me"]
    assert blocks.span_lines(new_text, spans[0]) == ["\\slide{ccc-EN-Me}", "\\slide{ddd-EN-Work}"]
    # The markers are plain comments: exactly the two stamped calls were added.
    stamped = _deck(deck.path, new_text)
    assert [c.id_slug for c in deck_editor.parse_slide_calls(stamped)] == [
        "aaa-EN-First", "bbb-EN-Second", "ccc-EN-Me", "ddd-EN-Work",
    ]


def test_insert_positions_never_nest_inside_a_copy(blocks_dir, tmp_path):
    blocks.write_block("about-me", ["\\slide{ccc-EN-Me}", "\\slide{ddd-EN-Work}"])
    block = blocks.read_block(blocks.block_path("about-me"))
    deck = _deck(tmp_path / "decks" / "course.tex", DECK_TEXT)
    first = deck_editor.parse_slide_calls(deck)[0]
    text = deck_editor.insert_text(
        deck.path, deck.text, first.line_end, blocks.stamp_text(block, "\t", "\r\n")
    )
    deck = _deck(deck.path, text)

    positions = blocks.insert_positions(deck)
    assert [p.label for p in positions] == [
        "At the beginning", "After 1. aaa-EN-First", "After block about-me", "After 4. bbb-EN-Second",
    ]
    span = blocks.find_spans(text)[0]
    for position in positions:
        assert not (span.start < position.insert_at < span.end), position.label


def test_insert_positions_for_empty_deck_and_empty_block(blocks_dir, tmp_path):
    empty_deck_text = "\\documentclass{beamer}\n\\begin{document}\n\\end{document}\n"
    deck = _deck(tmp_path / "decks" / "empty.tex", empty_deck_text)
    [position] = blocks.insert_positions(deck)
    assert position.insert_at == empty_deck_text.index("\\end{document}")

    # A block file has no \end{document}: its first call goes at the end.
    blocks.create_block("new-block")
    assert deck_editor.append_position(blocks.scan_blocks()[0].as_deck()) == (0, "")


def test_append_after_a_trailing_copy_lands_outside_it(blocks_dir, tmp_path):
    """Regression: append_position() used to return the last call's own
    line_end even when that call sat inside a stamped copy -- a second
    stamped block then nested inside the first (and slide_import.py's
    appended slides would have landed inside a copy too)."""
    blocks.write_block("first", ["\\slide{ccc-EN-Me}"])
    blocks.write_block("second", ["\\slide{ddd-EN-Work}"])
    deck_path = tmp_path / "decks" / "course.tex"
    text = DECK_TEXT
    for name in ("first", "second"):
        block = blocks.read_block(blocks.block_path(name))
        at, indent = deck_editor.append_position(_deck(deck_path, text))
        text = deck_editor.insert_text(deck_path, text, at, blocks.stamp_text(block, indent, "\r\n"))

    first, second = blocks.find_spans(text)
    assert (first.name, second.name) == ("first", "second")
    assert first.end <= second.start  # siblings, not nested


def test_update_from_span_rewrites_master_only(blocks_dir, tmp_path):
    blocks.write_block("about-me", ["\\slide{ccc-EN-Me}", "\\slide{ddd-EN-Work}"])
    block = blocks.read_block(blocks.block_path("about-me"))
    deck = _deck(tmp_path / "decks" / "course.tex", DECK_TEXT)
    at, indent = deck_editor.append_position(deck)
    text = deck_editor.insert_text(deck.path, deck.text, at, blocks.stamp_text(block, indent, "\r\n"))

    # A local edit in the deck's copy, then pushed back to the master.
    edited = text.replace("\t\\slide{ddd-EN-Work}\r\n", "")
    blocks.write_block("about-me", blocks.span_lines(edited, blocks.find_spans(edited)[0]))

    assert blocks.block_path("about-me").read_bytes() == b"\\slide{ccc-EN-Me}\r\n"
    assert deck.path.read_bytes().decode() == text  # the deck itself is untouched


def test_rename_block_rewrites_markers_of_that_block_only(blocks_dir, tmp_path):
    blocks.write_block("about-me", ["\\slide{ccc-EN-Me}"])
    blocks.write_block("about-me-2", ["\\slide{ddd-EN-Work}"])
    deck_path = tmp_path / "decks" / "course.tex"
    text = DECK_TEXT
    for name in ("about-me", "about-me-2"):
        block = blocks.read_block(blocks.block_path(name))
        at, indent = deck_editor.append_position(_deck(deck_path, text))
        text = deck_editor.insert_text(deck_path, text, at, blocks.stamp_text(block, indent, "\r\n"))

    assert blocks.rename_block("about-me", "intro") == 1
    names = [s.name for s in blocks.find_spans(deck_path.read_bytes().decode())]
    assert names == ["intro", "about-me-2"]
    assert sorted(b.name for b in blocks.scan_blocks()) == ["about-me-2", "intro"]


def test_splice_terminates_an_unterminated_last_line(tmp_path):
    deck = _deck(tmp_path / "deck.tex", "\\slide{aaa-EN-First}")  # no final newline
    new_text = deck_editor.insert_slide_call(
        deck.path, deck.text, len(deck.text), "", "slide", "bbb-EN-Second"
    )
    assert new_text == "\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n"


def test_housekeeping_keeps_slides_used_only_by_a_block(tmp_path, monkeypatch):
    # ZZI-EN-empty is in no example deck -- unused until a block references it.
    assert "ZZI-EN-empty-current.tex" in {p.name for p in unused_content.find_unused_slides()}
    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    (block_dir / "intro.tex").write_text("\\slide{ZZI-EN-empty}\r\n", encoding="utf-8")
    monkeypatch.setattr(unused_content, "BLOCKS_DIR", block_dir)
    assert "ZZI-EN-empty-current.tex" not in {p.name for p in unused_content.find_unused_slides()}


def test_slide_references_include_blocks(tmp_path, monkeypatch):
    assert blocks.BLOCKS_DIR in slide_rename._REFERENCE_DIRS
    block_dir = tmp_path / "blocks"
    block_dir.mkdir()
    (block_dir / "intro.tex").write_text("\\slide{abc-EN-Only-In-Block}\r\n", encoding="utf-8")
    monkeypatch.setattr(slide_rename, "_REFERENCE_DIRS", (block_dir,))
    monkeypatch.setattr(slide_rename, "BLOCKS_DIR", block_dir)
    assert slide_rename.count_references("abc-EN-Only-In-Block") == 1
    assert slide_rename.deck_names_referencing("abc-EN-Only-In-Block") == ["intro (block)"]


def test_editor_block_mode_and_deck_span_header(blocks_dir, tmp_path):
    from PySide6.QtWidgets import QApplication, QPushButton

    from slidemage import qt_gui
    from slidemage.qt_deck_editor_tab import DeckEditorTab

    app = QApplication.instance() or QApplication([])
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())

    blocks.create_block("empty-block")
    block_tab = DeckEditorTab(window, blocks.scan_blocks()[0].as_deck())
    labels = {b.text() for b in block_tab.findChildren(QPushButton)}
    assert block_tab.is_block
    assert "Add first slide…" in labels
    assert not labels & {"Transcript", "Insert block…", "Preview"}

    blocks.write_block("about-me", ["\\slide{ZZZ-EN-Standard-content}"])
    block = blocks.read_block(blocks.block_path("about-me"))
    deck = _deck(tmp_path / "decks" / "course.tex", DECK_TEXT)
    at, indent = deck_editor.append_position(deck)
    text = deck_editor.insert_text(deck.path, deck.text, at, blocks.stamp_text(block, indent, "\r\n"))
    deck_tab = DeckEditorTab(window, _deck(deck.path, text))
    labels = {b.text() for b in deck_tab.findChildren(QPushButton)}
    assert not deck_tab.is_block
    assert {"Update block from here", "Insert block…", "Transcript"} <= labels
    window.close()
