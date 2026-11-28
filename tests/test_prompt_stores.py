# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Prompts tab of Settings stores: the draft prompts and the translation prompts."""
from __future__ import annotations

import json

import pytest

from slidemage import draft_prompts
from slidemage import translation_prompts as tp
from slidemage.fileio import UnreadableFileError


def test_a_prompt_saved_as_the_default_is_not_stored(ctx):
    kind = draft_prompts.KIND_IMAGE_DRAFT
    for reset in ("The default\n", "   "):
        draft_prompts.set_custom_prompt(ctx, kind, "  My prompt  ", "The default")
        assert draft_prompts.get_custom_prompt(ctx, kind) == "My prompt"
        draft_prompts.set_custom_prompt(ctx, kind, reset, "  The default")
        assert draft_prompts.get_custom_prompt(ctx, kind) is None


def test_translation_prompt_changes_refuse_a_conflicted_file(ctx):
    path = ctx.settings_dir / "translation_prompts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    conflicted = b'<<<<<<< HEAD\n{"default": {"prompt": "Ours"}}\n=======\n{"models": {}}\n>>>>>>> branch\n'
    path.write_bytes(conflicted)
    config = tp.PromptConfig("Pending edit", 3)
    for change in (lambda: tp.set_default_prompt(ctx, config),
                   lambda: tp.set_prompt(ctx, "m", "en", "de", config),
                   lambda: tp.delete_prompt(ctx, "m", "en", "de")):
        with pytest.raises(UnreadableFileError, match="translation_prompts.json cannot be read"):
            change()
        assert path.read_bytes() == conflicted


def test_translation_prompt_changes_preserve_unrelated_entries(ctx):
    path = ctx.settings_dir / "translation_prompts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    assert tp.get_default_prompt(ctx) is None
    old = {"prompt": "Old", "blank_lines": 1}
    expected = {
        "default": old,
        "models": {"m": {"en": {"de": old, "fr": old}, "de": {"en": old}},
                   "other": {"en": {"de": old}}},
        "note": "Keep this too",
    }
    path.write_text(json.dumps(expected), encoding="utf-8")
    tp.set_default_prompt(ctx, tp.PromptConfig("New default", 3))
    expected["default"] = {"prompt": "New default", "blank_lines": 3}
    assert tp.get_effective_prompt(ctx, "any", "en", "de") == tp.PromptConfig("New default", 3)
    assert json.loads(path.read_text(encoding="utf-8")) == expected

    tp.set_prompt(ctx, "m", "en", "de", tp.PromptConfig("New override", 0))
    expected["models"]["m"]["en"]["de"] = {"prompt": "New override", "blank_lines": 0}
    assert tp.get_effective_prompt(ctx, "m", "en", "de") == tp.PromptConfig("New override", 0)
    assert json.loads(path.read_text(encoding="utf-8")) == expected

    assert tp.delete_prompt(ctx, "m", "de", "en")
    del expected["models"]["m"]["de"]
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    before = path.read_bytes()
    assert not tp.delete_prompt(ctx, "missing", "en", "de")
    assert path.read_bytes() == before


def test_a_damaged_draft_prompt_file_counts_as_empty_and_is_replaced_whole(ctx):
    kind = draft_prompts.KIND_IMAGE_DRAFT
    path = ctx.settings_dir / "draft_prompts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for damaged in (b"\xff\xfe\x00 not utf-8", b'{"image_draft": 5}'):
        path.write_bytes(damaged)
        assert draft_prompts.get_custom_prompt(ctx, kind) is None
    draft_prompts.set_custom_prompt(ctx, kind, "Mine", "The default")
    assert draft_prompts.get_custom_prompt(ctx, kind) == "Mine" and path.read_text(encoding="utf-8").startswith("{")
    assert [p.name for p in path.parent.iterdir()] == [path.name]          # no temp file left behind
