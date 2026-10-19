# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Course URLs persist in deck source without affecting LaTeX."""
from __future__ import annotations

import pytest

from slidemage import deck_editor, deck_scan


COURSE_URL = "https://online.uni-graz.at/kfu_online/wbLv.wbShowLVDetail?pStpSpNr=1002516"
OTHER_URL = "https://online.uni-graz.at/course?q=one%20two&lang=de"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_course_url_round_trip_and_rescan(tmp_path, newline):
    path = tmp_path / "course.tex"
    initial = newline.join((
        r"\documentclass{beamer}",
        r"\input{Slidemaster_preamble_uni-graz}",
        r"% This note mentions \begin{document} before the actual command.",
        r"\begin{document}",
        r"\end{document}",
        "",
    ))
    path.write_text(initial, encoding="utf-8", newline="")

    linked = deck_editor.set_course_url(path, initial, COURSE_URL)
    assert path.read_bytes().decode() == linked
    assert f"%% SlideMage course URL: {COURSE_URL}{newline}" in linked
    assert deck_scan.scan_dir(tmp_path, archived=False)[0].course_url == COURSE_URL

    changed = deck_editor.set_course_url(path, linked, OTHER_URL)
    assert changed.count("%% SlideMage course URL:") == 1
    assert deck_scan.parse_course_url(changed) == OTHER_URL

    removed = deck_editor.set_course_url(path, changed, "  ")
    assert "%% SlideMage course URL:" not in removed
    assert deck_scan.parse_course_url(removed) is None
    assert removed == initial


@pytest.mark.parametrize("bad_url", [
    "javascript:alert(1)", "file:///tmp/page", "online.uni-graz.at/course",
    "https://", "https://example.org/has space", "https://example.org:bad/path",
])
def test_invalid_course_url_does_not_modify_deck(tmp_path, bad_url):
    path = tmp_path / "course.tex"
    original = "\\documentclass{beamer}\n\\begin{document}\n"
    path.write_text(original, encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        deck_editor.set_course_url(path, original, bad_url)
    assert path.read_text() == original


def test_stale_deck_is_not_overwritten(tmp_path):
    path = tmp_path / "course.tex"
    original = "\\documentclass{beamer}\n\\begin{document}\n"
    path.write_text(original, encoding="utf-8", newline="")
    path.write_text(original + "% external change\n", encoding="utf-8", newline="")
    with pytest.raises(deck_editor.StaleFileError):
        deck_editor.set_course_url(path, original, COURSE_URL)
    assert path.read_text().endswith("% external change\n")


def test_marker_in_body_is_ignored():
    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        f"%% SlideMage course URL: {COURSE_URL}\n"
    )
    assert deck_scan.parse_course_url(text) is None
