"""Opt-in checks against real models: SLIDEMAGE_LIVE_AI=1 (Ollama must be
running with at least one model; the Claude check also needs
ANTHROPIC_API_KEY). Never part of the normal run."""
from __future__ import annotations

import os

import pytest

from slidemage.ai.providers import AnthropicProvider, OllamaProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("SLIDEMAGE_LIVE_AI") != "1", reason="set SLIDEMAGE_LIVE_AI=1 to run")

MESSAGES = [{"role": "user", "content": "Reply with the single word: pong"}]


def test_live_ollama():
    models = OllamaProvider().list_models()
    assert models, "Ollama has no models"
    reply = OllamaProvider(models[0]).chat(MESSAGES, max_tokens=64, timeout=120)
    assert reply.text.strip() or reply.thinking.strip()


def test_live_claude():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    provider = AnthropicProvider()
    assert provider.list_models()
    assert "pong" in provider.chat(MESSAGES, max_tokens=16, timeout=60).text.lower()
