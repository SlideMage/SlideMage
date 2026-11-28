# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Preview renders: the call, the deck context, the view and language."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from slidemage import batch_render, deck_editor, deck_outline, preview_target, slide_preview
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.project import ProjectContext
from conftest import EXAMPLE_PROJECT

PREAMBLE = "\\documentclass{beamer}\n\\input{SlideMage_template_acme-two}\n\\begin{document}"


def make_deck(body):
    text = PREAMBLE + "\n" + body + "\\end{document}\n"
    return Deck(name="course", path=Path("course.tex"), archived=False, text=text, supports_version=True,
                uses_biblatex=False, preamble_end=len(PREAMBLE), chapters=parse_chapters(text),
                output_folders={})


@pytest.fixture
def ctx(tmp_path):
    context = ProjectContext.at(tmp_path)
    context.slides_dir.mkdir()
    return context


@pytest.fixture
def wrappers(monkeypatch):
    result = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract', lambda ctx, wrapper, *a, **kw: result.append(wrapper))
    return result


def target_of(body, index=0):
    deck = make_deck(body)
    calls = deck_editor.parse_slide_calls(deck)
    return preview_target.for_call(EXAMPLE_PROJECT, deck, calls[index], index + 1)


def test_a_call_renders_in_its_deck_context(monkeypatch):
    calls = []
    monkeypatch.setattr(slide_preview, 'render_slide_to_pdf', lambda *args, **kw: calls.append((args, kw)))
    target = target_of("\\slide{aaa-EN-One}\n\\slidestep{bbb-EN-Two}{1,2}\n", 1)
    assert target.template == 'acme-two'
    preview_target.render(target, 'during-course', 'DE', log=print)
    (args, kwargs), = calls
    assert args[1:3] == ('slidestep', 'bbb-EN-Two')
    assert (kwargs['deck_version'], kwargs['deck_language']) == ('during-course', 'de')
    assert (kwargs['frame_number'], kwargs['steps']) == (2, '1,2')
    assert kwargs['preamble_text'] == PREAMBLE


def test_view_resolution_preserves_hidden_counters_but_skips_absent_steps(ctx):
    body = ("\\conditionalslide[instructor]{aaa-EN-One}\n"
            "\\omitslide{bbb-EN-Two}\n"
            "\\slidestep{ccc-EN-Three}[instructor]{1,2}\n"
            "\\slide{ddd-EN-Four}\n")
    deck = make_deck(body)
    resolved = batch_render.plan_slide(ctx, deck, ctx.slides_dir / 'ddd-EN-Four-current.tex', 'all', 'EN')
    assert [r.view for r in resolved] == ['instructor', 'during-course', 'after-course']
    assert [r.target.frame_number for r in resolved] == [4, 3, 3]
    hidden = batch_render.plan_slide(ctx, deck, ctx.slides_dir / 'aaa-EN-One-current.tex', 'all', 'EN')
    assert [r.target.hidden for r in hidden] == [False, True, True]
    with pytest.raises(ValueError, match='hidden'):
        preview_target.render(hidden[1].target, 'during-course', 'EN', log=print)


def test_duplicate_resolution_uses_occurrence_key_otherwise_first(ctx):
    deck = make_deck('\\slidestep{aaa-EN-One}{1}\n\\slide{bbb-EN-Two}\n\\slidestep{aaa-EN-One}{3}\n')
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    rows = deck_outline.resolve_slots(ctx, deck, 'instructor', 'EN')
    first = batch_render.plan_slide(ctx, deck, path, 'instructor', 'EN')[0].target
    last = batch_render.plan_slide(ctx, deck, path, 'instructor', 'EN', occurrence_key=rows[2].key)[0].target
    assert (first.steps, first.frame_number) == ('1', 1)
    assert (last.steps, last.frame_number) == ('3', 3)
    assert first.key != last.key
    assert replace(first, presenter_frame_number=2).key != replace(first, presenter_frame_number=3).key


def test_batch_validates_view_before_capturing_one_revision_for_all_views(ctx):
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    path.write_text('% version 1.0.0+\nOLD')
    captures = []

    def read(source):
        captures.append(source)
        return source.read_text()

    with pytest.raises(ValueError, match='Invalid preview view'):
        batch_render.plan_slide(ctx, None, path, 'student', 'EN', read_source=read)
    assert not captures
    requests = batch_render.plan_slide(ctx, None, path, 'all', 'en', read_source=read)
    assert len(captures) == 1
    assert requests[0].revision is requests[1].revision is requests[2].revision
    assert requests[0].language == 'EN'
    path.write_text('% version 1.0.0+\nNEW')
    newer = batch_render.plan_slide(ctx, None, path, None, 'EN')[0]
    assert newer.revision.content_hash != requests[0].revision.content_hash


def test_pinned_and_standalone_resolution_with_translation_folding(ctx):
    en = ctx.slides_dir / 'aaa-EN-One-current.tex'
    de = ctx.slides_dir / 'bbb-DE-Eins-current.tex'
    en.write_text('%% Language: EN\n%% DE translation: bbb-DE-Eins\nEN CURRENT')
    de.write_text('%% Language: DE\n%% Translation of: aaa-EN-One\nDE CURRENT')
    pinned = ctx.slides_dir / 'aaa-EN-One-v1-0-0.tex'
    pinned.write_text('EN PINNED')
    deck = make_deck('\\slideversion{aaa-EN-One}{1-0-0}\n\\slide{bbb-DE-Eins}\n\\slide{ccc-EN-Three}\n')
    english = batch_render.plan_slide(ctx, deck, en, 'instructor', 'EN')[0]
    assert english.target.version == '1-0-0' and not english.target.is_frozen_alone
    assert english.revision.text == 'EN PINNED'
    german = batch_render.plan_slide(ctx, deck, en, 'all', 'DE')
    assert all(r.target.id_slug == 'bbb-DE-Eins' and r.target.version is None for r in german)
    assert all(r.revision.text.endswith('DE CURRENT') for r in german)
    next_target = batch_render.plan_slide(ctx, deck, ctx.slides_dir / 'ccc-EN-Three-current.tex', 'instructor', 'DE')[0].target
    assert next_target.frame_number == 2
    frozen_path = pinned.with_name('aaa-EN-One-v2-0-0.tex')
    frozen = batch_render.plan_slide(ctx, deck, frozen_path, 'instructor', 'EN')[0].target
    assert (frozen.macro, frozen.version, frozen.preamble_text) == ('slideversion', '2-0-0', None)
    assert frozen.source_path == frozen_path and frozen.is_frozen_alone
    current = preview_target.for_path(ctx, en)
    assert (current.macro, current.version, current.preamble_text) == ('slide', None, None)
    assert preview_target.for_path(ctx, ctx.slides_dir / 'deck.tex') is None


def test_buffer_wrappers_preserve_steps_pinned_omit_state_and_slidefinal(wrappers):
    step = target_of('\\slidestep{aaa-EN-One}[instructor]{2,4}\n')
    preview_target.render_text(step, 'BODY', 'instructor', 'EN', log=print)
    assert r'\gdef\SMSlideSteps{2,4}' in wrappers[-1]
    pinned = target_of('\\omitslideversion{aaa-EN-One}{1-0-0}\n')
    preview_target.render_text(pinned, 'PINNED BODY', 'instructor', 'EN', log=print)
    assert r'\setSlideVersion{1-0-0}' in wrappers[-1]
    assert r'\global\SMOmittedSlidetrue' in wrappers[-1]
    final = target_of('\\slidefinal{aaa-EN-One}\n')
    preview_target.render_text(final, 'BODY', 'instructor', 'EN', log=print)
    assert r'\renewcommand{\conditionalpause}[1][instructor]{}' in wrappers[-1]


def test_presenter_of_hidden_student_target_uses_instructor_frame_number(ctx, wrappers):
    deck = make_deck('\\slidestep{bbb-EN-Two}[instructor]{1}\n\\omitslide{aaa-EN-One}\n')
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    target = batch_render.plan_slide(ctx, deck, path, 'after-course', 'EN')[0].target
    assert target.hidden and target.frame_number == 1
    preview_target.render_text(target, 'BODY', 'after-course', 'EN', presenter=True, log=print)
    assert r'\setcounter{framenumber}{1}' in wrappers[0]  # Beamer increments before printing frame 2.


@pytest.mark.parametrize("view, language", [("instructor", "EN"), ("during-course", "DE")])
def test_for_call_with_the_resolved_outline_builds_the_target_the_resolver_does(ctx, view, language, resolutions):
    (ctx.slides_dir / 'aaa-EN-One-current.tex').write_text('%% DE translation: ddd-DE-Vier\nbody')
    (ctx.slides_dir / 'ddd-DE-Vier-current.tex').write_text('%% Translation of: aaa-EN-One\nbody')
    deck = make_deck('\\slide{aaa-EN-One}\n\\conditionalslide[instructor]{bbb-EN-Two}\n\\slidestep{ccc-EN-Three}[instructor]{1}\n'
                     '\\slidestep{ccc-EN-Three}[during-course]{1}\n\\slide{ddd-DE-Vier}\n\\slide{aaa-EN-One}\n')
    deck.path = ctx.decks_dir / "course.tex"
    outline = deck_outline.resolve_outline(ctx, deck, view, language)
    assert any(r.hidden for r in outline.rows)
    for row in outline.rows:
        args = (ctx, deck, row.call, row.position, language)
        kwargs = dict(frame_number=row.frame_number, occurrence_key=row.key, hidden=row.hidden)
        old = preview_target.for_call(*args, **kwargs)
        resolutions.reset()
        new = preview_target.for_call(*args, **kwargs, outline=outline)
        assert (resolutions.slots, resolutions.scans) == (0, 0)
        assert new == old and new.key == old.key and new.presenter_frame_number == old.presenter_frame_number
        assert new.presenter_frame_number == outline.instructor_frames[row.key]
    # Another language needs its own resolution.
    resolutions.reset()
    other = 'DE' if language == 'EN' else 'EN'
    preview_target.for_call(ctx, deck, outline.rows[0].call, 1, other, occurrence_key=outline.rows[0].key, outline=outline)
    assert resolutions.slots == 1 and resolutions.scans == 2
