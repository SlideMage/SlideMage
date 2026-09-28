import pytest

from slidemage import deck_editor, deck_scan
from slidemage.deck_scan import Deck


def _deck(path, text):
    path.write_bytes(text.encode("utf-8"))
    begin = text.find("\\begin{document}")
    return Deck(
        name=path.stem, path=path, archived=False, text=text, supports_version=False,
        uses_biblatex=False,
        preamble_end=begin + len("\\begin{document}") if begin != -1 else None,
        chapters=deck_scan._parse_chapters(text), output_folders={}, tags=[],
    )


def test_add_and_rename_section_preserve_crlf_and_validate_title(tmp_path):
    text = "\\begin{document}\r\n\\slide{aaa-EN-First}\r\n\\end{document}\r\n"
    deck = _deck(tmp_path / "deck.tex", text)
    inserted = deck_editor.add_section(deck.path, text, "  Start here  ", text.find("\\slide"))
    assert inserted == text.replace("\\slide", "\\section{Start here}\r\n\\slide")
    assert b"\r\n" in deck.path.read_bytes()

    chapter = _deck(deck.path, inserted).chapters[0]
    renamed = deck_editor.rename_section(deck.path, inserted, chapter, "Renamed")
    assert "\\section{Renamed}\r\n" in renamed
    for bad_title in ("", " braces {", "comment %", "two\nlines"):
        with pytest.raises(ValueError):
            deck_editor.add_section(deck.path, renamed, bad_title, 0)


def test_rename_preserves_existing_section_title_whitespace(tmp_path):
    text = "\\begin{document}\n  \\section{  Intro  }  % note\n\\end{document}\n"
    deck = _deck(tmp_path / "deck.tex", text)
    renamed = deck_editor.rename_section(deck.path, text, deck.chapters[0], "Updated")
    assert renamed == "\\begin{document}\n  \\section{Updated}  % note\n\\end{document}\n"


def test_move_section_keeps_marker_indentation_with_its_block(tmp_path):
    text = "\\begin{document}\n  \\section{One}\n  one\n\t\\section{Two}\n\ttwo\n\\end{document}\n"
    deck = _deck(tmp_path / "deck.tex", text)
    moved = deck_editor.move_section(deck.path, text, deck.chapters[0], deck.chapters[1])
    assert moved == "\\begin{document}\n\t\\section{Two}\n\ttwo\n  \\section{One}\n  one\n\\end{document}\n"


def test_remove_section_keeps_its_slides_and_stale_text_is_refused(tmp_path):
    text = (
        "\\begin{document}\n\\section{One}\n\\slide{aaa-EN-First}\n"
        "\\section{Two}\n\\slide{bbb-EN-Second}\n\\end{document}\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    removed = deck_editor.remove_section(deck.path, text, deck.chapters[0])
    assert "\\section{One}" not in removed
    assert "\\slide{aaa-EN-First}" in removed

    deck.path.write_text("outside change\n", encoding="utf-8")
    with pytest.raises(deck_editor.StaleFileError):
        deck_editor.remove_section(deck.path, removed, deck.chapters[0])


def test_move_section_swaps_whole_adjacent_sections_including_empty_section(tmp_path):
    text = (
        "PREAMBLE\n\\begin{document}\nfront matter\n"
        "\\section{One}\n\\slide{aaa-EN-First}\n"
        "\\section{Empty}\n"
        "\\section{Three}\n\\slide{ccc-EN-Third}\n\\end{document}\nTRAILER\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    moved = deck_editor.move_section(deck.path, text, deck.chapters[0], deck.chapters[1])
    assert moved == (
        "PREAMBLE\n\\begin{document}\nfront matter\n"
        "\\section{Empty}\n\\section{One}\n\\slide{aaa-EN-First}\n"
        "\\section{Three}\n\\slide{ccc-EN-Third}\n\\end{document}\nTRAILER\n"
    )
    deck = _deck(deck.path, moved)
    with pytest.raises(ValueError):
        deck_editor.move_section(deck.path, moved, deck.chapters[0], deck.chapters[2])


def test_slide_can_cross_an_adjacent_section_marker_in_either_direction(tmp_path):
    text = (
        "\\begin{document}\r\n\\section{One}\r\n\\slide{aaa-EN-First}\r\n"
        "% boundary note\r\n\r\n\\section{Two}\r\n\\slide{bbb-EN-Second}\r\n\\end{document}\r\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_past_section(deck.path, text, calls[0], deck.chapters[1])
    assert "\\section{One}\r\n\\section{Two}\r\n% boundary note\r\n\r\n\\slide{aaa-EN-First}\r\n" in moved

    deck = _deck(deck.path, moved)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_past_section(deck.path, moved, calls[0], deck.chapters[1])
    assert "\\section{One}\r\n\\slide{aaa-EN-First}\r\n% boundary note\r\n\r\n\\section{Two}\r\n" in moved


def test_section_operations_refuse_inline_or_commented_marker_lines(tmp_path):
    inline = "\\begin{document}\ntext \\section{Inline}\n\\slide{aaa-EN-First}\n"
    deck = _deck(tmp_path / "deck.tex", inline)
    with pytest.raises(ValueError):
        deck_editor.remove_section(deck.path, inline, deck.chapters[0])

    commented = "\\begin{document}\n% \\section{Commented}\n\\slide{aaa-EN-First}\n"
    deck.path.write_bytes(commented.encode("utf-8"))  # bytes, like _deck(): keeps LF on Windows
    fake = deck_scan.Chapter(order=1, title="Commented", slug="Commented", start=22, end=len(commented))
    with pytest.raises(ValueError):
        deck_editor.remove_section(deck.path, commented, fake)


def test_slide_boundary_move_refuses_nonadjacent_lines(tmp_path):
    text = "\\section{One}\n\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n\\section{Two}\n"
    deck = _deck(tmp_path / "deck.tex", text)
    call = deck_editor.parse_slide_calls(deck)[0]
    with pytest.raises(ValueError):
        deck_editor.move_slide_past_section(deck.path, text, call, deck.chapters[1])


def test_move_section_ignores_commented_document_end_marker(tmp_path):
    text = "\\begin{document}\n% \\end{document}\n\\section{A}\nA\n\\section{B}\nB\n\\end{document}\n"
    deck = _deck(tmp_path / "deck.tex", text)


def test_legacy_block_comments_do_not_prevent_section_move(tmp_path):
    text = (
        "\\begin{document}\n\\section{Before}\n"
        "%% Block: old-copy\n%%\n\\slide{aaa-EN-First}\n"
        "%% End block: old-copy\n%%\n\\section{After}\n"
        "\\end{document}\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    call = deck_editor.parse_slide_calls(deck)[0]
    moved = deck_editor.move_slide_past_section(deck.path, text, call, deck.chapters[1])
    assert moved.index("\\section{After}") < moved.index("\\slide{aaa-EN-First}")


def test_move_slide_to_shifts_slides_in_between_and_changes_section(tmp_path):
    text = (
        "\\begin{document}\n\\slide{aaa-A}\n\\section{S}\n\\slide{bbb-B}\n"
        "  \\slide{ccc-C}\n\\slide{ddd-D}\n\\end{document}\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    up = deck_editor.move_slide_to(deck.path, text, calls[3], calls[0])
    assert up == (
        "\\begin{document}\n\\slide{ddd-D}\n\\slide{aaa-A}\n\\section{S}\n\\slide{bbb-B}\n"
        "  \\slide{ccc-C}\n\\end{document}\n"
    )
    calls = deck_editor.parse_slide_calls(_deck(deck.path, up))
    down = deck_editor.move_slide_to(deck.path, up, calls[1], calls[3])
    assert down == deck.path.read_text() == (
        "\\begin{document}\n\\slide{ddd-D}\n\\section{S}\n\\slide{bbb-B}\n"
        "  \\slide{ccc-C}\n\\slide{aaa-A}\n\\end{document}\n"
    )


def test_move_slide_to_last_unterminated_line_keeps_crlf(tmp_path):
    text = "\\begin{document}\r\n\\slide{aaa-A}\r\n\\slide{bbb-B}"
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_to(deck.path, text, calls[0], calls[1])
    assert moved == "\\begin{document}\r\n\\slide{bbb-B}\r\n\\slide{aaa-A}\r\n"
