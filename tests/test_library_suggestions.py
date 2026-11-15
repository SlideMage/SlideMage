# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real decks share one maximal run and a single, without structural slides."""
import pytest

from slidemage import deck_language, deck_scan, library_data, topic_blocks
from slidemage.fileio import StaleFileError, read_text_exact
from slidemage.project import ProjectContext


def test_shared_run_and_single(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    slugs = {i: f"{i}-EN-Demo" for i in ("tit", "aaa", "bbb", "ccc", "ddd", "one", "xxx")}
    for bare, slug in slugs.items():
        (ctx.slides_dir / f"{slug}-current.tex").write_text(
            r"\titleframe" if bare == "tit" else
            "% \\titleframe\n\\begin{standardframe}{Demo}\nContent\n\\end{standardframe}", encoding="utf-8")
    body = ("\\documentclass{beamer}\n\\begin{document}\n\\slide{tit-EN-Demo}\n"
            "\\section{Shared topic}\n% Keep these notes\n" +
            "\n".join(f"\\slide{{{slugs[i]}}}" for i in ("aaa", "bbb", "ccc", "ddd")) +
            "\n\\section{Other}\n\\slide{one-EN-Demo}\n\\end{document}\n")
    first, second = ctx.decks_dir / "first.tex", ctx.decks_dir / "second.tex"
    first.write_text(body.replace(r"\end{document}", "\\slide{xxx-EN-Demo}\n\\end{document}"), encoding="utf-8")
    second.write_text(body.replace("Shared topic", "Another heading"), encoding="utf-8")
    # These files cannot turn xxx into a suggestion, even though first calls it.
    for tag in ("test", "manual"):
        (ctx.decks_dir / f"{tag}.tex").write_text(
            "\\documentclass{beamer}\n\\decktags{" + tag + "}\n\\begin{document}\n"
            "\\slide{xxx-EN-Demo}\n\\end{document}", encoding="utf-8")
    ctx.archive_dir.mkdir()
    (ctx.archive_dir / "old.tex").write_text(body.replace("one-EN-Demo", "xxx-EN-Demo"), encoding="utf-8")
    ctx.blocks_dir.mkdir()
    (ctx.blocks_dir / "unused.tex").write_text(r"\slide{aaa-EN-Demo}", encoding="utf-8")

    found = library_data.suggestions(ctx)
    assert [(s.kind, s.ids) for s in found] == [("run", ("aaa", "bbb", "ccc", "ddd")), ("single", ("one",))]
    run = found[0]
    assert {d.name for d, _calls in run.occurrences} == {"first", "second"}
    assert {calls[0].chapter.title for _d, calls in run.occurrences} == {"Shared topic", "Another heading"}
    proposal = topic_blocks.prepare_run_block(ctx, run.occurrences, run.title)
    before = first.read_bytes()
    second_before = second.read_bytes()
    second.write_bytes(second_before.replace(b"\\slide{bbb", b"\\omitslide{bbb"))
    changed = deck_scan.read_deck(second)
    with pytest.raises(ValueError, match="do not match exactly"):
        topic_blocks.prepare_run_block(ctx, [run.occurrences[0],
            (changed, [c for c in deck_language.expanded_calls(ctx, changed)
                       if c.id in run.ids])], run.title)
    with pytest.raises(StaleFileError):
        topic_blocks.make_run_block(ctx, run.occurrences, run.title, proposal)
    assert first.read_bytes() == before and not proposal[0].exists()
    second.write_bytes(second_before)

    block = topic_blocks.make_run_block(ctx, run.occurrences, run.title, proposal)
    assert block.read_text().count(r"\slide{") == 4
    for path in (first, second):
        text = read_text_exact(path)
        assert f"\\slideblock{{{block.stem}}}" in text and "% Keep these notes" in text
        assert r"\slide{one-EN-Demo}" in text
    assert [(s.kind, s.ids) for s in library_data.suggestions(ctx)] == [("single", ("one",))]
    # The same raw run reuses the block, with no second block file.
    assert topic_blocks.prepare_run_block(ctx, run.occurrences, "Other title")[0] == block
    first.write_bytes(before)
    mixed = next(s for s in library_data.suggestions(ctx) if s.kind == "run")
    proposal = topic_blocks.prepare_run_block(ctx, mixed.occurrences, mixed.title)
    assert proposal[0] == block
    linked_before = second.read_bytes()
    topic_blocks.make_run_block(ctx, mixed.occurrences, mixed.title, proposal)
    assert second.read_bytes() == linked_before
    assert [(s.kind, s.ids) for s in library_data.suggestions(ctx)] == [("single", ("one",))]
