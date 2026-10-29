# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from slidemage.project import ProjectContext


@pytest.mark.parametrize(
    ("takeaway", "german_long", "german_takeaway", "translated_takeaway", "edited"),
    [
        ("", "", "Old German takeaway", "", False),
        ("t1", "", "", "t1-de", False),
        ("t1", "", "", "t1-de", True),
        ("English takeaway", "Previous German", "Previous takeaway", "", True),
    ],
    ids=["clear-empty-takeaway", "fresh", "stale-empty-german", "stale-existing-german"],
)
def test_applying_translation_checks_source_hash_and_updates_german(
    tmp_path, monkeypatch, takeaway, german_long, german_takeaway, translated_takeaway, edited
):
    """A Translate all snapshot must not overwrite German after the English changes."""
    from slidemage import alt_draft, alt_images

    ctx = ProjectContext.at(tmp_path)
    entry = alt_images.ImageEntry(
        image="media/chart.png", short="English short", long="Original English",
        takeaway_default=takeaway, long_de=german_long, takeaway_default_de=german_takeaway,
    )
    source_hash = alt_images.en_text_hash(entry)
    alt_images.save_store(ctx, {entry.image: entry})
    if edited:
        # The batch took its source hash before this edit (regression: 34cdbd7).
        alt_images.update_store(ctx, lambda entries: setattr(entries[entry.image], "long", "Edited English") or True)
    result = alt_draft.TranslationResult(
        short_de="Kurzer Text", long_de="translated text", takeaway_de=translated_takeaway,
        model="test", source_hash=source_hash,
    )
    written = alt_draft.apply_one_translation(ctx, entry.image, result, "test model")
    current = alt_images.load_store(ctx)[entry.image]
    assert written is (not edited)
    if edited:
        assert current.long_de == german_long
        assert current.takeaway_default_de == german_takeaway
        assert current.translated_from_hash == ""
    else:
        assert current.long_de == "translated text"
        assert current.takeaway_default_de == translated_takeaway
        assert current.translated_from_hash == source_hash
        assert alt_images.translation_state(current) == alt_images.STATE_REVIEWED


def test_draft_prompt_is_customizable_and_persists(ctx):
    """2026-09-23 review finding: alt_draft.py's image-description prompt
    was a hardcoded SYSTEM_PROMPT constant -- unlike translation_prompts.py's
    already-customizable prompts, there was no way to tune it without
    editing source."""
    from slidemage import alt_draft, draft_prompts
    from fake_routes import FakeProvider


    assert alt_draft.effective_system_prompt(ctx) == alt_draft.SYSTEM_PROMPT

    draft_prompts.set_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT, "Custom draft prompt.")
    assert alt_draft.effective_system_prompt(ctx) == "Custom draft prompt."

    # A freshly constructed backend with no explicit system_prompt picks
    # up the current custom default; an explicit one still overrides it.
    provider = FakeProvider("m")
    assert alt_draft.ModelBackend(ctx, provider).system_prompt == "Custom draft prompt."
    assert alt_draft.ModelBackend(ctx, provider, system_prompt="one-off").system_prompt == "one-off"

    # Clearing (empty string) reverts to the hardcoded default.
    draft_prompts.set_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT, "")
    assert alt_draft.effective_system_prompt(ctx) == alt_draft.SYSTEM_PROMPT
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None
