"""What the Prompts tab of Settings stores: the draft prompts and the translation prompts."""
from __future__ import annotations

from slidemage import draft_prompts, project
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
    mine = tp.PromptConfig(prompt="Translate.", blank_lines=2)
    tp.set_default_prompt(mine)
    assert tp.effective_default_prompt() == mine
    assert tp.get_effective_prompt("any", "en", "de") == mine                        # no override of its own
    override = tp.PromptConfig(prompt="For this model.", blank_lines=0)
    tp.set_prompt("m", "en", "de", override)
    assert tp.get_effective_prompt("m", "en", "de") == override


def test_a_damaged_draft_prompt_file_counts_as_empty_and_is_replaced_whole(tmp_path):
    kind = draft_prompts.KIND_IMAGE_DRAFT
    path = project.transitional_context().settings_dir / "draft_prompts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for damaged in (b"\xff\xfe\x00 not utf-8", b"[1, 2]", b"not json", b'{"image_draft": 5, "other": "kept"}'):
        path.write_bytes(damaged)
        assert draft_prompts.get_custom_prompt(kind) is None
    draft_prompts.set_custom_prompt(kind, "Mine", "The default")
    assert draft_prompts.get_custom_prompt(kind) == "Mine" and path.read_text(encoding="utf-8").startswith("{")
    assert [p.name for p in path.parent.iterdir()] == [path.name]          # no temp file left behind
