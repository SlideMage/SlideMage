# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from slidemage import deck_editor, deck_scan


def _deck(path, text):
    path.write_bytes(text.encode("utf-8"))
    return deck_scan.read_deck(path)


def test_add_and_rename_section_preserve_crlf_and_validate_title(tmp_path):
    text = "\\begin{document}\r\n\\slide{aaa-EN-First}\r\n\\end{document}\r\n"
    path = _deck(tmp_path / "deck.tex", text).path
    inserted = deck_editor.add_section(path, text, "  Start here  ", text.index("\\slide"))
    assert inserted == text.replace("\\slide", "\\section{Start here}\r\n\\slide")
    padded = inserted.replace("\\section{Start here}", "  \\section{  Start here  }  % note")
    chapter, = _deck(path, padded).chapters
    renamed = deck_editor.rename_section(path, padded, chapter, "Renamed")
    assert path.read_bytes().decode("utf-8") == renamed == padded.replace("{  Start here  }", "{Renamed}")
    for bad_title in ("", " braces {", "comment %", "two\nlines"):
        with pytest.raises(ValueError):
            deck_editor.add_section(path, renamed, bad_title, 0)


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
    assert deck.path.read_text() == "outside change\n"


def test_move_section_swaps_whole_adjacent_sections_including_empty_section(tmp_path):
    text = (
        "PREAMBLE\n\\begin{document}\nfront matter\n"
        "  \\section{One}\n\\slide{aaa-EN-First}\n"
        "\t\\section{Empty}\n"
        "\\section{Three}\n\\slide{ccc-EN-Third}\n\\end{document}\nTRAILER\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    moved = deck_editor.move_section(deck.path, text, deck.chapters[0], deck.chapters[1])
    assert moved == (
        "PREAMBLE\n\\begin{document}\nfront matter\n"
        "\t\\section{Empty}\n  \\section{One}\n\\slide{aaa-EN-First}\n"
        "\\section{Three}\n\\slide{ccc-EN-Third}\n\\end{document}\nTRAILER\n"
    )
    deck = _deck(deck.path, moved)
    with pytest.raises(ValueError):
        deck_editor.move_section(deck.path, moved, deck.chapters[0], deck.chapters[2])


def test_multiline_slide_can_cross_a_section_marker_in_either_direction(tmp_path):
    source = "\\slide\r\n\t{aaa-EN-First}"
    text = (
        f"\\begin{{document}}\r\n\\section{{One}}\r\n{source}\r\n"
        "% boundary note\r\n\r\n\\section{Two}\r\n\\slide{bbb-EN-Second}\r\n\\end{document}\r\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_past_section(deck.path, text, calls[0], deck.chapters[1])
    assert f"\\section{{One}}\r\n\\section{{Two}}\r\n% boundary note\r\n\r\n{source}\r\n" in moved

    deck = _deck(deck.path, moved)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_past_section(deck.path, moved, calls[0], deck.chapters[1])
    assert f"\\section{{One}}\r\n{source}\r\n% boundary note\r\n\r\n\\section{{Two}}\r\n" in moved


def test_section_operations_refuse_inline_or_commented_marker_lines(tmp_path):
    inline = "\\begin{document}\n\\slide{aaa-EN-First}\ntext \\section{Inline}\n"
    deck = _deck(tmp_path / "deck.tex", inline)
    assert deck_editor.section_append_point(deck, None) == inline.index("text ")
    assert not deck_editor.section_editable(inline, deck.chapters[0])
    with pytest.raises(ValueError):
        deck_editor.remove_section(deck.path, inline, deck.chapters[0])

    commented = "\\begin{document}\n% \\section{Commented}\n\\slide{aaa-EN-First}\n"
    _deck(deck.path, commented)
    fake = deck_scan.Chapter(order=1, title="Commented", slug="Commented", start=22, end=len(commented))
    with pytest.raises(ValueError):
        deck_editor.remove_section(deck.path, commented, fake)


def test_slide_boundary_move_refuses_nonadjacent_lines(tmp_path):
    text = "\\section{One}\n\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n\\section{Two}\n"
    deck = _deck(tmp_path / "deck.tex", text)
    call = deck_editor.parse_slide_calls(deck)[0]
    with pytest.raises(ValueError):
        deck_editor.move_slide_past_section(deck.path, text, call, deck.chapters[1])


def test_move_slide_calls_last_unterminated_line_keeps_crlf(tmp_path):
    text = "\\begin{document}\r\n\\slide{aaa-A}\r\n\\slide{bbb-B}"
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    moved = deck_editor.move_slide_calls(deck.path, text, [calls[0]], calls[1].line_end)
    assert moved == "\\begin{document}\r\n\\slide{bbb-B}\r\n\\slide{aaa-A}\r\n"


def test_move_slide_calls_moves_several_slides_in_deck_order(tmp_path):
    text = (
        "\\begin{document}\n\\section{One}\n\\slide{aaa-A}\n\\slide{bbb-B}\n\\slide{ccc-C}\n"
        "\\section{Two}\n\\slide{ddd-D}\n\\section{Empty}\n\\end{document}\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    calls = deck_editor.parse_slide_calls(deck)
    assert deck_editor.section_append_point(deck, deck.chapters[0]) == calls[2].line_end
    end = deck_editor.section_append_point(deck, deck.chapters[2])
    assert end == text.index(r"\end{document}")
    moved = deck_editor.move_slide_calls(deck.path, text, [calls[2], calls[0]], end)
    assert moved == (
        "\\begin{document}\n\\section{One}\n\\slide{bbb-B}\n"
        "\\section{Two}\n\\slide{ddd-D}\n\\section{Empty}\n\\slide{aaa-A}\n\\slide{ccc-C}\n\\end{document}\n"
    )
    locked = text.replace("\\slide{bbb-B}", "\\slide{bbb-B} \\slide{eee-E}")
    locked_deck = _deck(tmp_path / "locked.tex", locked)
    with pytest.raises(ValueError, match="can't move"):
        deck_editor.move_slide_calls(locked_deck.path, locked, deck_editor.parse_slide_calls(locked_deck), 0)
    assert locked_deck.path.read_bytes().decode("utf-8") == locked


def test_move_section_to_reorders_whole_blocks_in_one_edit(tmp_path):
    text = (
        "\\begin{document}\n\\section{One}\n\\slide{aaa-A}\n\\section{Two}\n\\slide{bbb-B}\n"
        "\\section{Three}\n\\slide{ccc-C}\n\\end{document}\n"
    )
    deck = _deck(tmp_path / "deck.tex", text)
    one, two, three = deck.chapters
    moved = deck_editor.move_section_to(deck.path, text, one, 2)
    assert moved == (
        "\\begin{document}\n\\section{Two}\n\\slide{bbb-B}\n\\section{Three}\n\\slide{ccc-C}\n"
        "\\section{One}\n\\slide{aaa-A}\n\\end{document}\n"
    )
    back = deck_editor.move_section_to(deck.path, moved, _deck(deck.path, moved).chapters[2], 0)
    assert back == text
    with pytest.raises(ValueError):
        deck_editor.move_section_to(deck.path, text, two, 3)


# Each macro once; the gaps rotate so every gap is seen too.
_GAPS = ["", " ", "\t", "\n", "\r\n\t "]
_CALL_FORMS = [
    ("slide", "{abc-EN-X}", None, None, None),
    ("slidefinal", "{abc-EN-X}", None, None, None),
    ("omitslide", "{abc-EN-X}", None, None, None),
    ("slideversion", "{abc-EN-X}{2-3-4}", "2-3-4", None, None),
    ("omitslideversion", "{abc-EN-X}{2-3-4}", "2-3-4", None, None),
    ("conditionalslide", "[ instructor, after-course ]{abc-EN-X}", None,
     ["instructor", "after-course"], None),
    ("conditionalslide", "{abc-EN-X}", None, deck_editor.DEFAULT_CONDITIONS, None),
    ("conditionalslide", "[]{abc-EN-X}", None, [], None),
    ("slidestep", "{abc-EN-X}[ instructor, after-course ]{ 1,2 }", None,
     ["instructor", "after-course"], "1,2"),
    ("slidestep", "{abc-EN-X}{1,2}", None, deck_editor.DEFAULT_CONDITIONS, "1,2"),
    ("slidestep", "{abc-EN-X}[]{1,2}", None, [], "1,2"),
]


@pytest.mark.parametrize("gap,macro,args,version,conditions,steps", [
    (_GAPS[i % len(_GAPS)], *form) for i, form in enumerate(_CALL_FORMS)])
def test_slide_call_whitespace_preserves_arguments_and_exact_span(
        tmp_path, gap, macro, args, version, conditions, steps):
    source = "\\" + macro + args.replace("{", gap + "{").replace("[", gap + "[")
    prefix = "\\begin{document}\n  "
    suffix = " \t% keep comment\n\\end{document}\n"
    text = prefix + source + suffix
    deck = _deck(tmp_path / "deck.tex", text)
    call, = deck_editor.parse_slide_calls(deck)
    assert (call.macro, call.id, call.slug, call.version, call.conditions, call.steps) == (
        macro, "abc", "EN-X", version, conditions, steps)
    assert (call.call_start, call.call_end) == (len(prefix), len(prefix) + len(source))
    assert call.editable
    assert deck_editor.change_slide_call_variant(deck.path, text, call, "omitslide") == (
        prefix + r"\omitslide{abc-EN-X}" + suffix)

    inline = _deck(tmp_path / "inline.tex", prefix + source + " \t{not-an-argument}\n")
    call, = deck_editor.parse_slide_calls(inline)
    assert not call.editable


def test_slide_call_does_not_match_a_longer_control_word(tmp_path):
    deck = _deck(tmp_path / "deck.tex", "\\slideextra \n{abc-EN-X}\n")
    assert not deck_editor.parse_slide_calls(deck)


@pytest.mark.parametrize("source,views", [
    (r"\slide{aaa-A}", (True, True, True)),
    (r"\omitslideversion{aaa-A}{1-0-0}", (True, False, False)),
    (r"\conditionalslide[instructor,after-course]{aaa-A}", (True, False, True)),
    (r"\conditionalslide[]{aaa-A}", (False, False, False)),
    (r"\slidestep{aaa-A}[during-course]{1,2}", (False, True, False)),
    (r"\slidestep{aaa-A}{1,2}", (True, True, True)),
])
def test_slide_call_included_in(tmp_path, source, views):
    call, = deck_editor.parse_slide_calls(_deck(tmp_path / "deck.tex", source + "\n"))
    assert tuple(call.included_in(view) for view in deck_editor.DEFAULT_CONDITIONS) == views
    assert call.included_in(None) is call.included_in("presenter") is views[0]


def test_set_calls_visibility_rewrites_the_call_per_view(tmp_path):
    def set_visibility(text, which, view, visible):
        deck = _deck(tmp_path / "deck.tex", text)
        calls = deck_editor.parse_slide_calls(deck)
        return deck_editor.set_calls_visibility(
            deck.path, text, [calls[i] for i in which], view, visible)

    text = (
        "\\begin{document}\n\\slide{aaa-A}\n\\omitslide{bbb-B}\n\\slidestep{ccc-C}[instructor]{1,2}\n"
        "\\slidefinal{ddd-D}\n\\end{document}\n"
    )
    hidden = set_visibility(text, [0, 2], "during-course", False)
    assert "\\conditionalslide[instructor,after-course]{aaa-A}" in hidden
    assert "\\slidestep{ccc-C}[instructor]{1,2}" in hidden
    shown = set_visibility(text, [1, 2], "during-course", True)
    assert "\\conditionalslide[instructor,during-course]{bbb-B}" in shown
    assert "\\slidestep{ccc-C}[instructor,during-course]{1,2}" in shown
    assert "\\slide{aaa-A}" in set_visibility(hidden, [0], "during-course", True)
    with pytest.raises(ValueError, match="slidefinal"):
        set_visibility(text, [3], "after-course", False)
    only_after = text.replace("[instructor]", "[after-course]")
    with pytest.raises(ValueError, match="at least one view"):
        set_visibility(only_after, [2], "after-course", False)


def test_a_section_goes_with_its_slide_calls_and_its_other_lines_stay(tmp_path):
    text = ("\\begin{document}\n\\section{One}\n\\slide{aaa-EN-First}\n% a note\n\\slide{bbb-EN-Second}\n"
            "\\section{Two}\n\\slide{ccc-EN-Third}\n\\end{document}\n")
    deck = _deck(tmp_path / "deck.tex", text)
    calls = [c for c in deck_editor.parse_slide_calls(deck) if c.id_slug in ("aaa-EN-First", "bbb-EN-Second")]
    removed = deck_editor.remove_section_and_calls(deck.path, text, deck.chapters[0], calls)
    assert removed == "\\begin{document}\n% a note\n\\section{Two}\n\\slide{ccc-EN-Third}\n\\end{document}\n"
    assert deck.path.read_text(encoding="utf-8") == removed


def test_all_sections_go_and_every_slide_stays_or_nothing_changes(tmp_path):
    text = ("\\begin{document}\n\\section{One}\n\\slide{aaa-EN-First}\n  \\section{Two}  % second\n"
            "\\slide{bbb-EN-Second}\n\\end{document}\n")
    deck = _deck(tmp_path / "deck.tex", text)
    removed = deck_editor.remove_all_sections(deck.path, text, deck.chapters)
    assert removed == "\\begin{document}\n\\slide{aaa-EN-First}\n\\slide{bbb-EN-Second}\n\\end{document}\n"
    inline = "\\begin{document}\n\\section{One}\n\\slide{aaa-EN-First}\n\\slide{x} \\section{Two}\n\\end{document}\n"
    deck = _deck(tmp_path / "inline.tex", inline)
    with pytest.raises(ValueError):
        deck_editor.remove_all_sections(deck.path, inline, deck.chapters)
    assert deck.path.read_bytes().decode("utf-8") == inline
