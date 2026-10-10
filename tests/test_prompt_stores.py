"""What the Prompts tab of Settings stores: the draft prompts and the translation prompts."""
from __future__ import annotations

from slidemage import draft_prompts
from slidemage import translation_prompts as tp


def test_a_prompt_saved_as_the_default_is_not_stored():
    kind = draft_prompts.KIND_IMAGE_DRAFT
    draft_prompts.set_custom_prompt(kind, "  My prompt  ", "The default")
    assert draft_prompts.get_custom_prompt(kind) == "My prompt"
    draft_prompts.set_custom_prompt(kind, "The default\n", "  The default")        # the stock text: a reset
    assert draft_prompts.get_custom_prompt(kind) is None
    draft_prompts.set_custom_prompt(kind, "My prompt", "The default")
    draft_prompts.set_custom_prompt(kind, "   ", "The default")                      # empty: a reset too
    assert draft_prompts.get_custom_prompt(kind) is None


def test_the_default_translation_prompt_falls_back_when_none_is_saved():
    assert tp.get_default_prompt() is None
    assert tp.effective_default_prompt() is tp._FALLBACK_DEFAULT
    mine = tp.PromptConfig(prompt="Translate.", blank_lines=2)
    tp.set_default_prompt(mine)
    assert tp.effective_default_prompt() == mine
    assert tp.get_effective_prompt("any", "en", "de") == mine                        # no override of its own
    override = tp.PromptConfig(prompt="For this model.", blank_lines=0)
    tp.set_prompt("m", "en", "de", override)
    assert tp.get_effective_prompt("m", "en", "de") == override
