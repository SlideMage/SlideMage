# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deck readers agree on linked blocks, repeated occurrences and archived decks."""
from types import SimpleNamespace

import pytest

from conftest import make_project
from slidemage import (
    batch_render, compile_progress, deck_context, deck_language,
    deck_outline, deck_scan, image_review, latex_lint, slide_add, transcript,
)
from slidemage.ai import agent_context
from slidemage.plugins.host import deck_snapshot
from slidemage.plugins.slide_reader import deck_slides
from slidemage.project import ProjectContext


@pytest.fixture(params=["block", "twice", "archive"])
def linked(request, tmp_path, monkeypatch):
    ctx = ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    ctx.blocks_dir.mkdir(exist_ok=True)
    block = ctx.blocks_dir / "topic.tex"
    calls = ("% topic\n\\slide{abc-EN-Hello}\n\\omitslide{abd-EN-Second}\n"
             "\\slidestep{abc-EN-Hello}[instructor]{2}\n")
    block.write_text(calls)
    repeat = 2 if request.param == "twice" else 1
    body = "\\section{Topic}\n" + "\\slideblock{topic}\n" * repeat
    body += "\\section{End}\n\\slide{abd-EN-Second}\n"
    text = "\\documentclass{beamer}\n\\begin{document}\n" + body + "\\end{document}\n"
    directory = ctx.archive_dir if request.param == "archive" else ctx.decks_dir
    directory.mkdir(exist_ok=True)
    path = directory / "linked.tex"
    path.write_text(text)
    deck = deck_scan.read_deck(path)
    inline = deck_scan.deck_from_text(directory / "inline.tex", text.replace("\\slideblock{topic}", calls))
    return ctx, deck, inline, repeat


def test_outline_and_frames(linked):
    ctx, deck, inline, repeat = linked
    calls = deck_language.active_calls(deck)
    assert len(calls) == 3 * repeat + 1
    assert len({c.identity for c in calls}) == len(calls)
    for occurrence in range(repeat):
        group = calls[3 * occurrence:3 * occurrence + 3]
        assert [c.index for c in group] == [0, 1, 2]
        assert all(c.source == ctx.blocks_dir / "topic.tex" and c.block == "topic" for c in group)
        assert [c.source_line for c in group] == [2, 3, 4]
        assert all(deck.text[c.call_start:c.call_end] == "\\slideblock{topic}" for c in group)
        assert all(deck.text[c.line_start:c.line_end] == "\\slideblock{topic}\n" for c in group)
    assert calls[-1].source == deck.path and calls[-1].block is None and calls[-1].index is None
    for view in ("instructor", "during-course", "after-course"):
        outline = deck_outline.resolve_outline(ctx, deck, view, "EN")
        expected = deck_outline.resolve_outline(ctx, inline, view, "EN")
        assert [(r.key, r.frame_number, r.hidden, r.deck_call.chapter.title) for r in outline.rows] == [
            (r.key, r.frame_number, r.hidden, r.deck_call.chapter.title) for r in expected.rows]
        assert outline.instructor_frames == expected.instructor_frames
        assert compile_progress.count_job_slides(ctx, deck, view, None) == compile_progress.count_job_slides(ctx, inline, view, None)
        for position in range(1, len(calls) + 1):
            assert deck_context.skeleton(ctx, deck, position, calls[position - 1].id_slug, view, "EN") == deck_context.skeleton(
                ctx, inline, position, calls[position - 1].id_slug, view, "EN")
    assert image_review.sort_order(deck) == image_review.sort_order(inline)
    assert slide_add.translation_call(deck, "abc-EN-Hello").block == "topic"
    context = SimpleNamespace(deck=deck, view="instructor", language="EN", path=None, slide_id=None)
    workspace = SimpleNamespace(root=ctx.root, project=ctx, context=lambda: context)
    message = agent_context.build_context(workspace, agent_context.SCOPE_DECK)
    assert [line for line in message.splitlines() if line.startswith("  ")] == [
        f"  {row.position}. {row.call.id} | {row.title}" for row in outline.rows]
    assert [r.target.id_slug for r in batch_render.plan_deck(ctx, deck)] == [
        r.target.id_slug for r in batch_render.plan_deck(ctx, inline)]
    resolved = deck_language.resolved_text(ctx, deck, "EN")
    assert len(deck_language.calls_in(resolved, [])) == len(calls)
    (ctx.slides_dir / "abd-EN-Second-current.tex").unlink()
    missing = [i for i in latex_lint.check_deck_job(ctx, deck, "instructor", None).issues if i.code == "slide-file"]
    assert [(i.path, i.line) for i in missing] == [(ctx.blocks_dir / "topic.tex", 3)] * repeat + [(deck.path, 5 + repeat)]


def test_transcript(linked):
    ctx, deck, inline, _ = linked
    inline.path.write_text(inline.text)
    for view in ("instructor", "during-course", "after-course"):
        assert transcript.resolve_deck(ctx, deck.path, view) == transcript.resolve_deck(ctx, inline.path, view)


def test_plugin_deck_slides(linked):
    ctx, deck, inline, repeat = linked
    for view in ("instructor", "during-course", "after-course"):
        refs = deck_slides(ctx, deck_snapshot(deck, ctx), view, "en")
        expected = deck_slides(ctx, deck_snapshot(inline, ctx), view, "en")
        assert [(r.id, r.position, r.hidden, r.section, r.path) for r in refs] == [
            (r.id, r.position, r.hidden, r.section, r.path) for r in expected]
        assert [r.block for r in refs] == ["topic"] * (3 * repeat) + [None]


@pytest.mark.parametrize("producer", ["batch", "slide", "background", "thumbnails", "outline", "usage"])
def test_expansion_is_shared_by_a_target_pass(linked, monkeypatch, producer):
    from unittest.mock import Mock
    from slidemage import background_renders, preview_target, preview_thumbnails, slide_usage

    ctx, deck, _, _ = linked
    (ctx.slides_dir / "abc-EN-Hello-current.tex").write_text(r"\tableofcontents")
    resolve = Mock(wraps=deck_language.expand_fragments)
    monkeypatch.setattr(deck_language, "expand_fragments", resolve)
    if producer == "batch":
        assert batch_render.plan_deck(ctx, deck)
    elif producer == "slide":
        assert batch_render.plan_slide(ctx, deck, ctx.slides_dir / "abc-EN-Hello-current.tex", "all", "EN")
    elif producer == "background":
        assert background_renders.deck_units(ctx, deck, "instructor", "EN", context_ready=lambda: True)
    elif producer == "thumbnails":
        outline = deck_outline.resolve_outline(ctx, deck, "instructor", "EN")
        preview_thumbnails.for_outline(ctx, deck, outline.sections, "instructor", "EN", resolver=Mock(),
                                       deck_hash=outline.deck_hash)
    elif producer == "outline":
        outline = deck_outline.resolve_outline(ctx, deck, "instructor", "EN")
        for row in outline.rows * 30:
            target = preview_target.for_call(ctx, deck, row.call, row.position, "EN", outline=outline,
                                             deck_hash=outline.deck_hash)
            if row.call.id == "abc":
                assert target.deck_hash == outline.deck_hash
    else:
        slide_usage.call_file_index(ctx, [deck])
        count = resolve.call_count
        slide_usage.call_file_index(ctx, [deck])
        assert resolve.call_count == count
        block = ctx.blocks_dir / "topic.tex"
        block.write_text(block.read_text() + "\n% external edit")
        slide_usage.call_file_index(ctx, [deck])
        assert resolve.call_count == count + 1
        return
    assert resolve.call_count == 1
