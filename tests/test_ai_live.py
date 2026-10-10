"""Opt-in checks against real models: SLIDEMAGE_LIVE_AI=1 (Ollama must be
running with at least one model; the Claude checks also need
ANTHROPIC_API_KEY). Never part of the normal run."""
from __future__ import annotations

import os

import pytest
from conftest import SLIDE_TEXT, make_project

from slidemage.ai import resolver
from slidemage.ai.agent import Agent
from slidemage.ai.agent_types import EDIT_AUTO, Done, EditApplied
from slidemage.ai.providers import AnthropicProvider, OllamaProvider
from slidemage.ai.workspace import Workspace, WorkspaceContext

# Read now: the autouse fixture in conftest.py removes the variable from the environment of every test.
LIVE_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

pytestmark = pytest.mark.skipif(
    os.environ.get("SLIDEMAGE_LIVE_AI") != "1", reason="set SLIDEMAGE_LIVE_AI=1 to run")

MESSAGES = [{"role": "user", "content": "Reply with the single word: pong"}]


def test_live_ollama():
    models = OllamaProvider().list_models()
    assert models, "Ollama has no models"
    reply = OllamaProvider(models[0]).chat(MESSAGES, max_tokens=64, timeout=120)
    assert reply.text.strip() or reply.thinking.strip()


def test_live_claude():
    if not LIVE_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")
    provider = AnthropicProvider(api_key=LIVE_KEY)
    assert provider.list_models()
    assert "pong" in provider.chat(MESSAGES, max_tokens=16, timeout=60).text.lower()


def test_live_claude_agent_changes_a_slide_with_its_tools(tmp_path, monkeypatch):
    """The whole loop on the real API: the model reads the slide, edits it through edit_file
    (the protected lines stay), and says it is done."""
    if not LIVE_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")
    root = make_project(monkeypatch, tmp_path / "project")
    slide = root / "slides" / "abc-EN-Hello-current.tex"
    resolver.record_cloud_consent()
    events = []
    agent = Agent(AnthropicProvider(api_key=LIVE_KEY), Workspace(root, WorkspaceContext(slide_id="abc", path=slide)),
                  on_event=events.append, mode=EDIT_AUTO, max_turns=8)
    done = agent.run([], "Change the frame title of this slide from 'Hello' to 'Hello, world', "
                         "then check it with lint. Do nothing else.")
    assert isinstance(events[-1], Done) and done.reason == "end_turn", done.message
    assert any(isinstance(e, EditApplied) for e in events)
    text = slide.read_bytes().decode()
    assert "{Hello, world}" in text
    for protected in ("%% Included in decks: test", "\\setSlideVersion{1-0-0}", "\\vbox to 0pt{\\vss\\hbox{overlay}}"):
        assert protected in text
    assert text.replace("Hello, world", "Hello") == SLIDE_TEXT
    assert done.usage["output"] > 0
