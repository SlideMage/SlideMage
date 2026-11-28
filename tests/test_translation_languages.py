# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation prompts, glossaries and project language settings."""
from __future__ import annotations

import json

import pytest

from slidemage import languages, project, translation_prompts as tp
from slidemage.ai import tasks as ai_tasks, translation_style
from slidemage.ai.tools import slidemage as slidemage_tools, _with_project_languages
from slidemage.project import ProjectContext


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / ".slidemage").mkdir()
    return ProjectContext.at(tmp_path)


def write_project(ctx, data):
    (ctx.root / ".slidemage" / "project.json").write_text(json.dumps(data), encoding="utf-8")


def test_default_and_custom_prompts_fill_in_the_language_pair(ctx):
    prompt = tp.get_effective_prompt(ctx, "any-model", "fr", "en").prompt
    assert "into English" in prompt and "Output only the English translation" in prompt
    assert "{target}" not in prompt and "{source}" not in prompt
    tp.set_default_prompt(ctx, tp.PromptConfig("Translate {source} to {target}."))
    assert tp.get_effective_prompt(ctx, "m", "fr", "en").prompt == "Translate French to English."


def test_the_address_key_wins_and_set_address_writes_both_keys(ctx):
    write_project(ctx, {"de_address": "du", "address": "formal"})
    assert translation_style.address(ctx) == "formal"
    translation_style.set_address(ctx, "informal")
    data = project.read_project_json(ctx.root)
    assert data["address"] == "informal" and data["de_address"] == "du"
    assert translation_style.address(ctx) == "informal" and translation_style.de_address(ctx) == "du"
    translation_style.set_address(ctx, "formal")
    assert project.read_project_json(ctx.root)["de_address"] == "Sie"


TABLE = """| EN | DE | FR |
|----|----|----|
| slide | Folie | diapositive |
| deck | Foliensatz | |
"""


def test_a_glossary_table_gives_the_rows_of_the_pair():
    assert translation_style.glossary_for(TABLE, "EN", "DE") == "slide = Folie\ndeck = Foliensatz"
    assert translation_style.glossary_for(TABLE, "de", "fr") == "Folie = diapositive"      # a row needs both terms
    assert translation_style.glossary_for(TABLE, "FR", "ES") == ""


def test_a_request_carries_only_the_glossary_rows_of_its_pair():
    request = ai_tasks.translate_request("A slide.", "EN", "FR", glossary=TABLE)
    assert "Glossary, one term per line:\nslide = diapositive\n<slide>" in request
    assert "Folie" not in request
    update = ai_tasks.update_request("Neu.", "Nouveau.", "DE", "FR", glossary=TABLE)
    assert "Folie = diapositive\n<source>" in update


def test_the_prompt_page_lists_every_ordered_pair_and_marks_those_with_a_prompt(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    tp.set_prompt(ctx, "model", "de", "fr", tp.PromptConfig("p"))
    from slidemage.ui.dialogs.settings_prompts import language_pairs

    assert language_pairs(ctx) == [("en", "de", False), ("en", "fr", False), ("de", "en", False),
                                   ("de", "fr", True), ("fr", "en", False), ("fr", "de", False)]


def test_the_language_enums_of_the_tools_follow_the_project(ctx):
    languages.set_project_languages(ctx, "fr", ["en", "es"])
    codes = [*languages.project_languages(ctx).codes, "mult"]
    for tool in (slidemage_tools.add_slide, slidemage_tools.create_slide):
        assert _with_project_languages(tool, codes).spec.schema["properties"]["language"]["enum"] == [
            "FR", "EN", "ES", "mult"]
    assert _with_project_languages(slidemage_tools.lint, codes) is slidemage_tools.lint
