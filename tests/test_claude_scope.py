"""The Slide / Deck scope of the embedded Claude Code: the focus file, the context block of
every prompt, and the edit guard of the hook."""
from __future__ import annotations

import io
import json

from slidemage.ai import claude_hook, claude_scope


def publish(tmp_path, scope, slide="slides/1aa-EN-One-current.tex", dirty=False):
    file = tmp_path / "focus.json"
    claude_scope.publish(file, scope, tmp_path, "1aa", tmp_path / slide if slide else None,
                         tmp_path / "decks" / "course.tex", "instructor", "EN", dirty)
    return file


def test_slide_scope_names_the_file_and_forbids_exploring(tmp_path):
    data = claude_scope.load(publish(tmp_path, "slide", dirty=True))
    text = claude_scope.prompt_context(data)
    assert "THIS SLIDE" in text and "slides/1aa-EN-One-current.tex" in text
    assert "read_buffer" in text and "do not explore" in text


def test_deck_scope_allows_the_deck(tmp_path):
    text = claude_scope.prompt_context(claude_scope.load(publish(tmp_path, "deck")))
    assert "WHOLE DECK" in text and "decks/course.tex" in text and "do not explore" not in text


def test_no_slide_in_focus(tmp_path):
    text = claude_scope.prompt_context(claude_scope.load(publish(tmp_path, "slide", slide=None)))
    assert "No slide is in focus" in text


def test_edit_guard_only_in_slide_scope(tmp_path):
    other = tmp_path / "slides" / "2bb-EN-Two-current.tex"
    own = tmp_path / "slides" / "1aa-EN-One-current.tex"
    slide = claude_scope.load(publish(tmp_path, "slide"))
    deck = claude_scope.load(publish(tmp_path, "deck"))
    assert "outside it" in claude_scope.edit_problem(slide, tmp_path, other)
    assert claude_scope.edit_problem(slide, tmp_path, tmp_path / "decks" / "course.tex")
    assert claude_scope.edit_problem(slide, tmp_path, own) is None
    assert claude_scope.edit_problem(slide, tmp_path, tmp_path / "Slidemaster.bib") is None
    assert claude_scope.edit_problem(deck, tmp_path, other) is None
    assert claude_scope.edit_problem(None, tmp_path, other) is None


def test_hook_prints_the_context_for_a_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(claude_scope.FOCUS_ENV, str(publish(tmp_path, "slide")))
    event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "make it shorter"})
    monkeypatch.setattr("sys.stdin", type("S", (), {"buffer": io.BytesIO(event.encode())})())
    assert claude_hook.main() == 0
    assert "THIS SLIDE" in capsys.readouterr().out


def test_failed_focus_publish_is_retried_without_a_focus_change(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from slidemage.project import ProjectContext
    from slidemage.ui.workspace.terminal.session import ClaudeCodeSession

    window = SimpleNamespace(
        project=ProjectContext.at(tmp_path),
        state=SimpleNamespace(deck=None, focused_slide="abc", view="instructor", language="EN"),
        centre=SimpleNamespace(path=tmp_path / "slides/abc-EN-Hello-current.tex", is_dirty=lambda path: False))
    session = ClaudeCodeSession(window, tmp_path / "fake-claude")
    session._focus_file = tmp_path / "focus.json"
    changed, attempts = [], []
    session.focus_changed.connect(lambda: changed.append(True))
    publish = claude_scope.publish

    def fail_once(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("write failed")
        publish(*args)

    monkeypatch.setattr(claude_scope, "publish", fail_once)
    try:
        session.publish_focus()
        assert session._published is None and not changed and not session._focus_file.exists()
        session.publish_focus()
        assert session._published is not None and changed == [True] and len(attempts) == 2
        assert claude_scope.load(session._focus_file)["slide_id"] == "abc"
        session.publish_focus()
        assert len(attempts) == 2 and changed == [True]
    finally:
        session.shutdown()
