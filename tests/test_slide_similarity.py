# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json

import pytest

from slidemage.project import ProjectContext
from slidemage.slide_similarity import find_clusters, normalise, tokens


@pytest.mark.parametrize("language, other", [("EN", "DE"), ("DE", "EN")])
def test_clusters(tmp_path, language, other):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.settings_dir.mkdir()
    (ctx.settings_dir / "project.json").write_text(
        json.dumps({"languages": {"main": "en", "secondary": ["de"]}}))
    exact = "An exact copy has several distinctive words."
    same = r"Markup preserves these words with $x = 42$ and \includegraphics{media/a-b.png}"
    similar = "One two three four five six seven eight nine ten eleven twelve "
    slides = {
        "a": exact, "b": "% a comment\n%% metadata\n\\setSlideVersion{2-0-0}\n" + exact,
        "c": same, "d": r"\textbf{" + same + "}",
        "e": similar + "apple", "f": similar + "orange",
        "g": "A translation uses completely separate vocabulary for this example",
        "h": "%% Translation of: g-" + language + "-Demo\n"
             "A translation uses completely separate vocabulary for this example",
        "i": r"\titleframe " + similar + "apple",
        "j": r"\begin{sectionframe}" + similar + r"apple\end{sectionframe}",
        "k": r"\tableofcontents " + similar + "apple",
        "l": r"\insertsection " + similar + "apple",
        "m": "tiny", "n": r"\textbf{tiny}",
        "ZZ1": exact, "manual": exact,
    }
    for slide_id, text in slides.items():
        code = other if slide_id == "h" else language
        (ctx.slides_dir / f"{slide_id}-{code}-Demo-current.tex").write_text(text, encoding="utf-8")
    (ctx.slides_dir / f"old-{language}-Demo-v1-0-0.tex").write_text(exact)
    (ctx.settings_dir / "bundled_copies.json").write_text(json.dumps({"manual": {"files": {
        f"slides/manual-{language}-Demo-current.tex": "hash"}}}))
    # A real collection is large enough that a shared triple is below the 5% boilerplate cutoff.
    for i in range(50):
        (ctx.slides_dir / f"z{i}-{language}-Filler-current.tex").write_text(f"unique{i}")

    clusters = find_clusters(ctx)
    assert [(c.kind, c.ids) for c in clusters] == [
        ("exact", ["a", "b"]), ("same_words", ["c", "d"]), ("similar", ["e", "f"])]
    assert [c.overlap for c in clusters] == [1.0, 1.0, pytest.approx(10 / 12)]
    assert all(c.sequence_deck is None for c in clusters)
    assert clusters[0].fingerprint == hashlib.sha256(
        json.dumps([normalise(exact)] * 2, ensure_ascii=False).encode()).hexdigest()
    assert tokens(same) == ["markup", "preserves", "these", "words", "with", "x", "=", "42",
                            "and", "media/a-b.png"]
    assert normalise(slides["b"]) == exact
    (ctx.slides_dir / f"a-{language}-Demo-current.tex").write_text("%% changed header\n" + exact)
    assert find_clusters(ctx)[0].fingerprint == clusters[0].fingerprint


def test_sequence_deck(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    blocks = ctx.root / "blocks"
    blocks.mkdir()
    for ids, text in (("ab", "same"), ("cd", "block"), ("ef", "separate"), ("gh", "expanded")):
        for slide_id in ids:
            (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(text)
    deck = ctx.decks_dir / "course.tex"
    deck.write_text("\\documentclass{beamer}\n\\begin{document}\n"
                    "\\slide{a-EN-Demo}\n\\slide{b-EN-Demo}\n\\slide{e-EN-Demo}\n"
                    "\\input{blocks/linked}\n\\input{blocks/second}\n"
                    "% \\slide{f-EN-Demo}\n\\end{document}")
    (ctx.decks_dir / "other.tex").write_text("\\documentclass{beamer}\n\\begin{document}\n"
                                             "\\slide{a-EN-Demo}\n\\slide{f-EN-Demo}\n\\end{document}")
    block = blocks / "topic.tex"
    block.write_text("\\slide{c-EN-Demo}\n\\slide{d-EN-Demo}")
    (blocks / "linked.tex").write_text("\\slide{g-EN-Demo}")
    (blocks / "second.tex").write_text("\\slide{h-EN-Demo}")
    assert [(c.ids, c.sequence_deck) for c in find_clusters(ctx)] == [
        (["a", "b"], deck), (["c", "d"], block), (["e", "f"], None), (["g", "h"], deck)]
