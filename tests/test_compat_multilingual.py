# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_multilingual.py: \\multilingualtext{EN}{DE} and \\multilingualtext*{...} become the keyed form."""
from __future__ import annotations

from slidemage import compat, compat_multilingual as m


def test_the_two_argument_form_and_the_star_are_rewritten():
    old = ("\\begin{sectionframe}{\\multilingualtext{Trends, today}{Trends = heute}}\n"
           "\\item \\multilingualtext{A \\textbf{bold} one}\n   {Ein \\textbf{fettes}}\n"
           "Say \\multilingualtext*{EN={cheese}, FR={fromage}}.\n")
    new, lines = m.rewrite(old)
    assert new == ("\\begin{sectionframe}{\\multilingualtext{EN={Trends, today}, DE={Trends = heute}}}\n"
                   "\\item \\multilingualtext{EN={A \\textbf{bold} one}, DE={Ein \\textbf{fettes}}}\n"
                   "Say \\multilingualtext{EN={cheese}, FR={fromage}}.\n")
    assert lines == [1, 2, 4]
    assert m.rewrite(new) == (new, [])                                   # idempotent


def test_comments_and_a_blank_line_between_the_arguments_are_left_alone():
    text = "% \\multilingualtext{a}{b}\n\\multilingualtext{EN={x}}\n\n{not an argument}\n"
    assert m.rewrite(text) == (text, [])


def test_the_project_is_updated_slides_versions_archive_snippets_and_decks(tmp_path):
    files = {
        "slides/abc-mult-X-current.tex": "\\multilingualtext{Hi}{Hallo}\r\n",
        "slides/abc-mult-X-v1-0-0.tex": "\\multilingualtext{Hi}{Hallo}\n",
        "slides/archive/abd-mult-Y-v1-0-0.tex": "\\multilingualtext*{EN={Hi}}\n",
        "snippets/abc-1.tex": "\\multilingualtext{a}{b}\n",
        "decks/d.tex": "\\section{\\multilingualtext{One}{Eins}}\n",
        "decks/_slidemage_temp.tex": "\\multilingualtext{a}{b}\n",          # a compile's temporary deck: not ours
        "slides/abe-EN-Z-current.tex": "nothing\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(text.encode("utf-8"))
    assert {f.file for f in m.detect(tmp_path)} == {
        "slides/abc-mult-X-current.tex", "slides/abc-mult-X-v1-0-0.tex", "slides/archive/abd-mult-Y-v1-0-0.tex",
        "snippets/abc-1.tex", "decks/d.tex"}
    result = compat.run_update(tmp_path, [compat.Pending(m.CHANGE, m.detect(tmp_path))])
    assert not result.errors and len(result.changed) == 5
    assert (tmp_path / "slides/abc-mult-X-current.tex").read_bytes() == b"\\multilingualtext{EN={Hi}, DE={Hallo}}\r\n"
    assert (tmp_path / "decks/_slidemage_temp.tex").read_text(encoding="utf-8") == "\\multilingualtext{a}{b}\n"
    assert m.detect(tmp_path) == []


def test_the_change_is_registered_as_breaking():
    assert m.CHANGE in compat.CHANGES and m.CHANGE.severity == compat.BREAKS and m.CHANGE.migrate is not None
