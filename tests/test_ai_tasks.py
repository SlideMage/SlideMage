"""Each AI task runs on any ChatProvider: these use a fake one (no HTTP) and
check that the prompt/verification logic of the task modules is unchanged
by which provider answers."""
from __future__ import annotations

import pytest

from slidemage import ai_draft, alt_draft, alt_images, syntax_check, translation_prompts
from slidemage.ai.providers import Cancelled, ChatReply, ProviderError

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"


class FakeProvider:
    """Answers with queued replies (or raises queued errors) and records calls."""

    is_local = True
    model = "fake"
    label = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.aborted = False

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, ChatReply) else ChatReply(text=reply)

    def list_models(self):
        return ["fake"]

    def abort(self):
        self.aborted = True


# -- AI draft (slide rewrite) ------------------------------------------------

SLIDE = "% header\n\\setSlideVersion{1.0}\nBody text\n"


def test_rewrite_masks_protected_regions_and_restores_them():
    provider = FakeProvider(
        "```\n%%%PROTECTED_0%%%\nNew body\n```")
    proposal = ai_draft.SlideDrafter(provider).draft(SLIDE, "change it")
    sent = provider.calls[0]["messages"][0]["content"]
    assert "%%%PROTECTED_0%%%" in sent and "setSlideVersion" not in sent
    assert provider.calls[0]["system"] == ai_draft.effective_system_prompt()
    assert proposal.ok
    assert proposal.proposed_text == "% header\n\\setSlideVersion{1.0}\nNew body"
    assert proposal.model == "fake"


def test_rewrite_refuses_a_proposal_that_loses_a_protected_block():
    proposal = ai_draft.SlideDrafter(FakeProvider("New body only")).draft(SLIDE, "x")
    assert not proposal.ok
    assert "Refused this draft" in proposal.error


def test_rewrite_reports_provider_errors_and_empty_replies():
    assert ai_draft.SlideDrafter(
        FakeProvider(ProviderError("Ollama unreachable: x"))).draft(SLIDE, "x").error == \
        "Ollama unreachable: x"
    assert ai_draft.SlideDrafter(FakeProvider("")).draft(SLIDE, "x").error == \
        "Model returned an empty response"


# -- syntax check ------------------------------------------------------------

ISSUES = ('{"issues": [{"line": 2, "problem": "unbalanced", '
          '"original": "\\\\textbf{a", "suggested_fix": "\\\\textbf{a}"}]}')


def test_syntax_check_parses_issues_and_verifies_fixes_against_the_buffer():
    provider = FakeProvider("Here you go:\n```json\n" + ISSUES + "\n```")
    result = syntax_check.SyntaxChecker(provider).check("ok\n\\textbf{a\nend")
    assert provider.calls[0]["schema"] == syntax_check.RESPONSE_SCHEMA
    assert "2: \\textbf{a" in provider.calls[0]["messages"][0]["content"]
    assert result.ok and len(result.issues) == 1
    issue = result.issues[0]
    assert issue.fix_is_safe(["ok", "\\textbf{a", "end"])
    assert not issue.fix_is_safe(["ok", "something else", "end"])  # buffer moved on


def test_syntax_check_error_paths():
    assert not syntax_check.SyntaxChecker(FakeProvider("no json")).check("x").ok
    assert syntax_check.SyntaxChecker(FakeProvider("")).check("x").error == \
        "Model returned an empty response"
    failed = syntax_check.SyntaxChecker(FakeProvider(ProviderError("boom"))).check("x")
    assert failed.error == "boom" and not failed.cancelled
    cancelled = syntax_check.SyntaxChecker(FakeProvider(Cancelled("Aborted."))).check("x")
    assert cancelled.cancelled


def test_syntax_checker_abort_reaches_the_provider():
    provider = FakeProvider()
    syntax_check.SyntaxChecker(provider).abort()
    assert provider.aborted


# -- image description -------------------------------------------------------

DESCRIPTION = ('{"short": " A bar chart ", "long": "Three bars.", "takeaway": "Up.", '
               '"role_suggestion": "informative"}')


@pytest.fixture
def context():
    return alt_draft.SlideContext(
        slide_id="abc", title="Title", body="Body", source="", image="media/x.png")


def test_image_description_sends_the_image_and_schema(tmp_path, context):
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    provider = FakeProvider(DESCRIPTION)
    result = alt_draft.ModelBackend(provider).draft(image, context)
    call = provider.calls[0]
    assert call["images"] == [PNG]
    assert call["schema"] == alt_draft.RESPONSE_SCHEMA
    assert result.ok and result.short == "A bar chart" and result.long == "Three bars."
    assert result.model == "fake"


def test_image_description_retries_once_when_thinking_ate_the_budget(tmp_path, context):
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    provider = FakeProvider(
        ChatReply(text="", thinking="still reasoning", truncated=True), DESCRIPTION)
    result = alt_draft.ModelBackend(provider).draft(image, context)
    assert result.ok
    assert [c["max_tokens"] for c in provider.calls] == [2048, alt_draft.MAX_TOKENS_RETRY]


def test_image_description_errors_stay_errors(tmp_path, context):
    image = tmp_path / "x.png"
    image.write_bytes(PNG)
    assert alt_draft.ModelBackend(FakeProvider(ProviderError("down"))).draft(
        image, context).error == "down"
    assert "non-JSON" in alt_draft.ModelBackend(FakeProvider("prose")).draft(
        image, context).error


# -- translation -------------------------------------------------------------

def test_translation_translates_each_field_through_the_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(translation_prompts, "STORE_PATH", tmp_path / "tp.json")
    provider = FakeProvider("kurz", "lang", "fazit")
    entry = alt_images.ImageEntry(
        image="media/x.png", short="short", long="long", takeaway_default="take")
    result = alt_draft.ModelTranslationBackend(provider).translate(entry)
    assert (result.short_de, result.long_de, result.takeaway_de) == ("kurz", "lang", "fazit")
    assert result.error is None and result.source_hash == alt_images.en_text_hash(entry)
    assert all(call["messages"][0]["role"] == "user" and "system" not in call
               for call in provider.calls)


def test_translation_reports_provider_errors_per_field(tmp_path, monkeypatch):
    monkeypatch.setattr(translation_prompts, "STORE_PATH", tmp_path / "tp.json")
    backend = alt_draft.ModelTranslationBackend(FakeProvider(ProviderError("rate limited")))
    assert backend.translate_text("hello") == ("", "rate limited")
    assert backend.translate_text("  ") == ("", None)  # nothing to send, no call made
