# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Composite slide edits with fake buffers/rendering and socket-free MCP."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_fakes import FakeWorkspace, call

from slidemage import ai_review, compiler, deck_outline, preview_target, slide_snapshot
from slidemage.ai.agent_types import EDIT_ASK, EDIT_AUTO, EditApplied
from slidemage.ai.tools import build_toolbox, undo_edit
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

SLIDE = "slides/abc-EN-Hello-current.tex"
PNG = b"\x89PNG\r\n\x1a\nfake"
EDITS = [{"old": "First point", "new": "Edited point"}]


@pytest.fixture
def env(root, monkeypatch):
    project = ProjectContext.at(root)
    deck = next(d for d in scan_decks(project) if d.name == "test")
    ws = FakeWorkspace(root, WorkspaceContext(deck=deck, path=root / SLIDE))
    shown, renders, events = [], [], []
    monkeypatch.setattr(ws, "show_slide", shown.append)
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: renders.append(a) or root / "fake.pdf")
    monkeypatch.setattr(slide_snapshot, "page_png", lambda *a: PNG)
    # The render service reads the rendered PDF's images (prepare_preview_images) for saved and draft renders alike.
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda pdf, snapshots, widths: ((PNG, PNG), ()))
    (root / "fake.pdf").write_bytes(b"%PDF-1.4")
    box = build_toolbox(ws, events.append, compiler.CancelToken(), EDIT_AUTO)
    return SimpleNamespace(root=root, project=project, ws=ws, box=box, path=root / SLIDE,
                           shown=shown, renders=renders, events=events)


def modify(env, **args):
    return env.box.execute(call("modify_slide", **(dict(slide="abc", edits=EDITS) | args)))


@pytest.mark.parametrize("slide", ["abc", SLIDE])
@pytest.mark.parametrize("buffer", [False, True])
def test_ordered_edits_mark_render_show_and_support_undo(env, slide, buffer):
    before = env.path.read_text()
    if buffer:
        env.ws.open(env.path, before)
    result = modify(env, slide=slide, expected=before, edits=EDITS + [{"old": "Edited point", "new": "Final point"}])
    assert not result.is_error, result.text
    after = before.replace("First point", "Final point")
    written = after if buffer else after.replace("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-0-0+}")
    assert (env.ws.buffer_text(env.path) if buffer else env.path.read_text()) == written
    assert result.images == [PNG] and "Lint:" in result.text and "Not reviewed" in result.text
    assert env.shown == [env.path] and len(env.renders) == 1
    entry = ai_review.unreviewed(env.project)[SLIDE]
    assert entry["kind"] == "edit" and entry["source"] == "modify_slide"
    applied, = [e for e in env.events if isinstance(e, EditApplied)]
    assert applied.before == before and applied.after == written and applied.via_buffer == buffer and applied.undoable
    assert bool(list((env.project.slide_backups_dir / env.path.name).glob("*.tex"))) != buffer
    if not buffer:
        assert b"\r\n" in env.path.read_bytes()
    assert undo_edit(env.ws, applied) == ""
    assert (env.ws.buffer_text(env.path) if buffer else env.path.read_text()) == before


@pytest.mark.parametrize("old, count", [("point", 2), ("Missing point", 0)])
def test_missing_or_ambiguous_edit_is_atomic(env, old, count):
    original = env.path.read_bytes()
    result = modify(env, edits=EDITS + [{"old": old, "new": "Replacement"}])
    assert result.is_error and f"occurs {count} times" in result.text and "nothing written" in result.text
    assert env.path.read_bytes() == original and not env.events and not env.renders
    assert not ai_review.unreviewed(env.project)


def test_expected_mismatch_returns_current_excerpt_and_writes_nothing(env):
    original = env.path.read_bytes()
    result = modify(env, expected="stale text")
    assert result.is_error and "changed since" in result.text and env.path.read_text() in result.text
    assert env.path.read_bytes() == original and not env.events and not env.renders


def test_dirty_buffer_is_the_reported_base_and_disk_is_untouched(env):
    original = env.path.read_bytes()
    before = env.path.read_text().replace("First point", "User's unsaved point")
    env.ws.open(env.path, before, dirty=True)
    result = modify(env, edits=[{"old": "User's unsaved point", "new": "Edited unsaved point"}], expected=before)
    assert not result.is_error, result.text
    assert "base: editor (unsaved)" in result.text
    assert "Edited unsaved point" in env.ws.buffer_text(env.path)
    assert env.path.read_bytes() == original
    assert env.renders[0][1] == env.ws.buffer_text(env.path)


@pytest.mark.parametrize("old", ["Included in decks: test", "setSlideVersion{1-0-0}"])
def test_protected_changes_are_refused(env, old):
    original = env.path.read_bytes()
    result = modify(env, edits=[{"old": old, "new": old + "changed"}])
    assert result.is_error and "protected" in result.text
    assert env.path.read_bytes() == original and not env.events and not env.renders


def test_frozen_is_refused_before_language_resolution(env):
    path = env.root / "slides/abc-EN-Hello-v1-0-0.tex"
    original = path.read_bytes()
    env.ws._context = replace(env.ws.context(), language="DE")
    result = modify(env, slide=str(path))
    assert result.is_error and "frozen version" in result.text
    assert path.read_bytes() == original and not env.events and not env.renders


@pytest.mark.parametrize("problem, message", [("A & B", "ampersand"), ("\\begin{frame}X\\end{frame}", "exactly one frame")])
def test_lint_and_structure_failures_do_not_write(env, problem, message):
    original = env.path.read_bytes()
    result = env.box.execute(call("modify_slide", slide="abc", body=env.path.read_text() + problem))
    assert result.is_error and message in result.text
    assert env.path.read_bytes() == original and not env.events and not env.renders


def test_full_text_and_lint_warnings(env):
    result = env.box.execute(call("modify_slide", slide="abc", body=env.path.read_text().replace("First point", "5% growth")))
    assert not result.is_error, result.text
    assert "[warning]" in result.text and "percent" in result.text and len(env.renders) == 1


@pytest.mark.parametrize("buffer", [False, True])
def test_text_changed_during_confirmation_is_preserved(env, buffer):
    before = env.path.read_text()
    env.box.ctx.mode = EDIT_ASK
    newer = before + "% user typed\n"
    if buffer:
        env.ws.open(env.path, before)
        env.ws.before_confirm = lambda: env.ws.buffers.update({env.path: newer})
    else:
        env.ws.before_confirm = lambda: env.path.write_text(newer)
    result = modify(env)
    assert result.is_error and "was not changed" in result.text
    assert (env.ws.buffer_text(env.path) if buffer else env.path.read_text()) == newer
    assert not env.renders and not ai_review.unreviewed(env.project)


def test_render_failure_keeps_change_and_review_mark(env, monkeypatch):
    def fail(*a, **k):
        env.renders.append(a)
        raise RuntimeError("! Undefined control sequence.\nl.4 \\unknown")
    monkeypatch.setattr(preview_target, "render_text", fail)
    result = modify(env)
    assert result.is_error and "Undefined control sequence" in result.text and "did not compile" in result.text
    assert "The slide stays in place; edit this file to fix it." in result.text
    assert SLIDE in result.text and "Edited point" in env.path.read_text()
    assert env.shown == [env.path] and len(env.renders) == 1
    assert ai_review.is_unreviewed(env.project, env.path)


def test_explicit_german_edit_and_following_preview_use_same_source(env):
    original = env.path.read_text()
    translated = env.root / "slides/xyz-DE-Hallo-current.tex"
    translated.write_text(original.replace("%% Included in decks: test", "%% Translation of: abc-EN-Hello"))
    env.path.write_text(original.replace("%% Included in decks: test", "%% DE translation: xyz-DE-Hallo"))
    result = modify(env, slide=str(translated))
    assert not result.is_error, result.text
    assert env.renders[0][0].source_path == translated and env.renders[0][3] == "DE"
    env.ws._context = replace(env.ws.context(), language="DE")
    preview = env.box.execute(call("render_preview", slide=str(translated)))
    assert not preview.is_error, preview.text
    assert result.images == preview.images == [PNG]


def test_hidden_edit_does_not_show_or_render(env):
    deck = env.ws.context().deck.path
    deck.write_text(deck.read_text().replace(r'\slide{abc-EN-Hello}',
                                             r'\conditionalslide[during-course]{abc-EN-Hello}'))
    result = modify(env)
    assert not result.is_error and "hidden" in result.text and not result.images
    assert not env.shown and not env.renders


@pytest.mark.parametrize("focused", [True, False])
def test_show_uses_prepared_occurrence_before_focus_changes(env, monkeypatch, focused):
    deck_path = env.ws.context().deck.path
    deck_path.write_text(deck_path.read_text().replace(r'\slide{abc-EN-Hello}',
        '\\slidestep{abc-EN-Hello}{1}\n\\slidestep{abc-EN-Hello}{3}'))
    deck = next(d for d in scan_decks(env.project) if d.name == "test")
    rows = [row for row in deck_outline.resolve_slots(env.project, deck, 'instructor', 'EN') if row.slot.call.id == 'abc']
    env.ws._context = replace(env.ws.context(), deck=deck, slide_id='abc' if focused else 'abd',
                              occurrence_key=rows[-1].key)
    order = []
    def show(path):
        order.append('show')
        env.ws._context = replace(env.ws.context(), occurrence_key=None)
    publish = env.ws.publish_preview_result
    monkeypatch.setattr(env.ws, 'show_slide', show)
    monkeypatch.setattr(env.ws, 'publish_preview_result', lambda result, ticket:
                        order.append('publish') or publish(result, ticket))
    result = modify(env)
    assert not result.is_error, result.text
    assert env.renders[0][0].occurrence_key == rows[-1 if focused else 0].key
    assert order == ['show', 'publish']


@pytest.mark.parametrize("reverse_only", [False, True])
def test_switch_resolves_translation_partner_and_marks_translation(env, reverse_only):
    original = env.path.read_text()
    translated = env.root / "slides/xyz-DE-Hallo-current.tex"
    translated.write_text(original.replace("%% Included in decks: test", "%% Translation of: abc-EN-Hello"))
    if not reverse_only:
        env.path.write_text(original.replace("%% Included in decks: test", "%% DE translation: xyz-DE-Hallo"))
    original_bytes = env.path.read_bytes()
    env.ws._context = replace(env.ws.context(), language="DE")
    result = modify(env, slide="abc", expected=translated.read_text())
    assert not result.is_error, result.text
    assert "abc in DE is its partner xyz-DE-Hallo" in result.text
    assert "Edited point" in translated.read_text() and env.path.read_bytes() == original_bytes
    assert env.shown == [translated] and env.renders[0][3] == "DE"
    assert ai_review.unreviewed(env.project)[translated.relative_to(env.root).as_posix()]["kind"] == "translation"


@pytest.mark.parametrize("language, slide, target_language", [
    ("EN", "slides/xyz-DE-Hallo-current.tex", "DE"),
    ("EN", SLIDE, "EN"),
    ("DE", SLIDE, "EN"),
    ("DE", "slides/xyz-DE-Hallo-current.tex", "DE"),
])
@pytest.mark.parametrize("absolute", [False, True])
def test_explicit_path_edits_that_file_and_checks_its_expected_text(env, language, slide, target_language, absolute):
    original = env.path.read_text()
    translated = env.root / "slides/xyz-DE-Hallo-current.tex"
    translated.write_text(original.replace("%% Included in decks: test", "%% Translation of: abc-EN-Hello")
                          .replace("First point", "Erster Punkt"))
    env.path.write_text(original.replace("%% Included in decks: test", "%% DE translation: xyz-DE-Hallo"))
    target = env.root / slide
    other = translated if target == env.path else env.path
    other_before = other.read_bytes()
    before = target.read_text()
    old = "Erster Punkt" if target == translated else "First point"
    env.ws._context = replace(env.ws.context(), language=language)
    result = modify(env, slide=str(target) if absolute else slide, expected=before,
                    edits=[{"old": old, "new": "Edited point"}])
    assert not result.is_error, result.text
    assert "Edited point" in target.read_text() and other.read_bytes() == other_before
    assert env.shown == [target] and env.renders[0][3] == target_language
    assert "is its partner" not in result.text


@pytest.mark.parametrize("args", [dict(), dict(edits=[], body="text"), dict(edits=[]), dict(edits=[None]),
                                  dict(edits=[{"old": "", "new": "x"}]), dict(edits=[{"old": "First", "new": 1}]),
                                  dict(edits=[{"old": "First"}]), dict(edits=[{"old": "First", "new": "x", "extra": 1}])])
def test_invalid_inputs_do_not_write(env, args):
    original = env.path.read_bytes()
    result = env.box.execute(call("modify_slide", slide="abc", **args))
    assert result.is_error and "unexpectedly" not in result.text
    assert env.path.read_bytes() == original and not env.events and not env.renders


@pytest.mark.parametrize("slide", ["SlideMage.bib", "decks/test.tex", "slides/missing-current.tex", "../outside.tex"])
def test_non_live_slides_are_refused(env, slide):
    result = modify(env, slide=slide)
    assert result.is_error and not env.events and not env.renders




# -- optional timing (SLIDEMAGE_TIMING=1) ---------------------------------------------------------------

def _timeline(env):
    log = env.project.settings_dir / "timing.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_timing_is_silent_when_off(env, monkeypatch):
    monkeypatch.delenv("SLIDEMAGE_TIMING", raising=False)
    assert not modify(env).is_error
    assert _timeline(env) == []


def test_timing_records_the_request_in_order(env, monkeypatch):
    monkeypatch.setenv("SLIDEMAGE_TIMING", "1")
    monkeypatch.setenv("SLIDEMAGE_PROJECT", str(env.root))
    from slidemage import timing
    timing.event(env.root, "prompt")
    assert not modify(env).is_error
    events = _timeline(env)
    assert [e["event"] for e in events] == ["prompt", "tool_start", "slide_written", "render_done", "tool_end"]
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)
    assert events[1]["tool"] == events[4]["tool"] == "modify_slide"
    spec = importlib.util.spec_from_file_location("timing_summary", Path(__file__).parents[1] / "tools" / "timing_summary.py")
    timing_summary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timing_summary)
    lines = timing_summary.summarize([json.dumps(e) for e in [{"t": 1, "event": "prompt"}, *events]])
    assert lines[0].endswith("prompt") and "tool=modify_slide" in lines[1] and len(lines) == 5
