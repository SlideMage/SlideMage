# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""\\SMReview[note]{call}: a deck marks one of its slides as under review. The wrapper is read and written by
deck_editor, does nothing in LaTeX, and the app draws its watermark over previews only."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import deck_editor, preview_target
from slidemage.deck_scan import REVIEW_TEXT_DEFAULT, deck_from_text, parse_review_text

HEAD = "\\documentclass{beamer}\n\\begin{document}\n"
TAIL = "\\end{document}\n"


def make(tmp_path, body, newline="\n"):
    text = (HEAD + body + TAIL).replace("\n", newline)
    path = tmp_path / "course.tex"
    path.write_bytes(text.encode("utf-8"))
    return deck_from_text(path, text)


def calls_of(deck):
    return deck_editor.parse_slide_calls(deck)


def reread(deck):
    return deck_from_text(deck.path, deck.path.read_bytes().decode("utf-8"))


def test_the_wrapper_is_read_around_every_kind_of_call(tmp_path):
    deck = make(tmp_path, (
        "\t\\SMReview{\\slide{aaa-EN-One}}\n"
        "\t\\SMReview[check the numbers]{\\conditionalslide[instructor]{bbb-EN-Two}} % later\n"
        "\t\\SMReview [ x ] { \\slidestep{ccc-EN-Three}[instructor]{1,2} }\n"
        "\t\\SMReview{\\slideversion{ddd-EN-Four}{1-0-0}}\n"
        "\t\\slide{eee-EN-Five}\n"))
    calls = calls_of(deck)
    assert [c.review for c in calls] == [True, True, True, True, False]
    assert [c.review_note for c in calls] == ["", "check the numbers", "x", "", ""]
    assert all(c.editable and c.indent == "\t" for c in calls)
    assert [c.macro for c in calls] == ["slide", "conditionalslide", "slidestep", "slideversion", "slide"]
    assert calls[1].conditions == ["instructor"] and calls[2].steps == "1,2" and calls[3].version == "1-0-0"
    first = calls[0]
    assert deck.text[first.outer_start:first.outer_end] == "\\SMReview{\\slide{aaa-EN-One}}"


def test_a_commented_wrapper_or_one_with_company_is_not_a_mark(tmp_path):
    deck = make(tmp_path, (
        "% \\SMReview{\\slide{aaa-EN-One}}\n"
        "\\SMReview{\\slide{bbb-EN-Two}\\slide{ccc-EN-Three}}\n"
        "\\textbf{\\slide{ddd-EN-Four}}\n"))
    calls = calls_of(deck)
    assert [c.review for c in calls] == [False, False, False, False]
    assert not any(c.editable for c in calls)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_marking_and_clearing_changes_only_the_wrapper(tmp_path, newline):
    body = "\t\\slide{aaa-EN-One}\n\t\\conditionalslide[instructor]{bbb-EN-Two} % note\n\t\\slide{ccc-EN-Three}\n"
    deck = make(tmp_path, body, newline)
    original = deck.text
    calls = calls_of(deck)
    deck_editor.set_calls_review(deck.path, deck.text, calls[:2], True)
    deck = reread(deck)
    assert deck.text == original.replace("\\slide{aaa-EN-One}", "\\SMReview{\\slide{aaa-EN-One}}").replace(
        "\\conditionalslide[instructor]{bbb-EN-Two}", "\\SMReview{\\conditionalslide[instructor]{bbb-EN-Two}}")
    calls = calls_of(deck)
    assert [c.review for c in calls] == [True, True, False]

    deck_editor.set_calls_review(deck.path, deck.text, calls[:1], True, "ask Anna")       # a note on a marked call
    deck = reread(deck)
    calls = calls_of(deck)
    assert calls[0].review_note == "ask Anna" and "\\SMReview[ask Anna]{\\slide{aaa-EN-One}}" in deck.text
    deck_editor.set_calls_review(deck.path, deck.text, calls, True)                       # marking again keeps it
    deck = reread(deck)
    calls = calls_of(deck)
    assert [c.review_note for c in calls] == ["ask Anna", "", ""] and all(c.review for c in calls)

    deck_editor.set_calls_review(deck.path, deck.text, calls, False)
    assert reread(deck).text == original


def test_a_note_is_plain_text(tmp_path):
    deck = make(tmp_path, "\\slide{aaa-EN-One}\n")
    for bad in ("50% off", "a]b", "\\textbf{x}", "a_b"):
        with pytest.raises(ValueError):
            deck_editor.set_calls_review(deck.path, deck.text, calls_of(deck), True, bad)
    assert reread(deck).text == deck.text


def test_other_edits_keep_the_mark(tmp_path):
    deck = make(tmp_path, "\\SMReview[n]{\\slide{aaa-EN-One}}\n\\slide{bbb-EN-Two}\n")
    first = calls_of(deck)[0]
    deck_editor.change_slide_call_variant(deck.path, deck.text, first, "omitslide")
    deck = reread(deck)
    assert "\\SMReview[n]{\\omitslide{aaa-EN-One}}\n" in deck.text
    first, second = calls_of(deck)
    deck_editor.set_calls_visibility(deck.path, deck.text, [first], "after-course", True)
    deck = reread(deck)
    first, second = calls_of(deck)
    assert first.review and first.macro == "conditionalslide"
    deck_editor.move_slide_call(deck.path, deck.text, first, second)                     # the line moves as one
    deck = reread(deck)
    moved = calls_of(deck)
    assert [c.id for c in moved] == ["bbb", "aaa"] and [c.review for c in moved] == [False, True]
    deck_editor.remove_slide_calls(deck.path, deck.text, [moved[1]])
    assert "SMReview" not in reread(deck).text


def test_the_decks_watermark_text(tmp_path):
    assert parse_review_text(HEAD) == REVIEW_TEXT_DEFAULT
    assert parse_review_text("\\SMReviewText{TO CHECK}\n" + HEAD) == "TO CHECK"
    assert parse_review_text("% \\SMReviewText{OLD}\n\\SMReviewText{ }\n" + HEAD) == REVIEW_TEXT_DEFAULT
    deck = make(tmp_path, "\\slide{aaa-EN-One}\n")
    assert deck.review_text == REVIEW_TEXT_DEFAULT
    # a deck's review settings leave its slides' renders current
    assert preview_target.preamble_sha("\\SMReviewText{TO CHECK}\n" + HEAD) == preview_target.preamble_sha(HEAD)


def test_the_framework_defines_the_wrapper_as_a_no_op():
    base = (Path(__file__).resolve().parents[1] / "latex" / "SlideMage_base.tex").read_text(encoding="utf-8")
    assert "\\NewDocumentCommand{\\SMReview}{O{} m}{#2}" in base
    assert "\\NewDocumentCommand{\\SMReviewText}{m}{}" in base


def test_the_mark_is_painted_inside_the_page(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from slidemage.ui.kit.review_mark import paint_review_mark

    def painted(text, note=""):
        image = QImage(400, 300, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        paint_review_mark(painter, QRectF(40, 40, 320, 180), text, note)
        painter.end()
        return {(x, y) for x in range(400) for y in range(300) if image.pixelColor(x, y) != QColor("white")}

    assert not painted("")
    marked = painted("REVIEW")
    assert marked and all(40 <= x < 360 and 40 <= y < 220 for x, y in marked)
    assert len(painted("REVIEW", "ask Anna")) > len(marked)


def test_a_long_note_wraps_first_and_only_then_gets_smaller(qapp):
    from PySide6.QtGui import QFont, QFontMetricsF
    from slidemage.ui.kit.review_mark import NOTE_LINES, NOTE_MIN_SIZE, note_font_size, note_lines

    font = QFont()
    font.setPixelSize(20)
    width = 12.5 * QFontMetricsF(font).horizontalAdvance("word ")
    counts = {n: note_lines(font, "word " * n, width, 20) for n in range(1, 120)}
    assert counts[1] == 1 and sorted(set(counts.values()))[:NOTE_LINES] == list(range(1, NOTE_LINES + 1))
    for wanted in range(1, NOTE_LINES + 1):                    # up to three lines: wrapped, the type stays
        note = "word " * max(n for n, count in counts.items() if count == wanted)
        assert note_font_size(font, note, width, 20) == 20
    long = "word " * (2 * max(n for n, count in counts.items() if count == NOTE_LINES))
    size = note_font_size(font, long, width, 20)               # more: the largest type that fits on three
    assert NOTE_MIN_SIZE < size < 20
    assert note_lines(font, long, width, size) <= NOTE_LINES < note_lines(font, long, width, size + 1)
    assert note_font_size(font, "word " * 2000, width, 20) == NOTE_MIN_SIZE
    assert note_font_size(font, "w" * 40, width / 4, 20) < 20  # one word wider than the box gets smaller too


def test_the_preview_page_draws_the_mark_over_the_slide(qapp):
    from PySide6.QtGui import QColor, QPixmap
    from slidemage.ui.kit.tokens import LIGHT
    from slidemage.ui.workspace.preview_view import PageView

    page = PageView(lambda: LIGHT)
    page.resize(640, 400)
    pixmap = QPixmap(320, 180)
    pixmap.fill(QColor("white"))
    page.show_image(pixmap)
    plain = page.grab().toImage()
    page.set_review("REVIEW", "ask Anna")
    marked = page.grab().toImage()
    assert marked != plain
    page.set_review("")
    assert page.grab().toImage() == plain
    page.deleteLater()
