# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI translation between any two project languages (content languages, step 3): the prompts, the form of
address, the glossary forms, the last-resort prompt, the pairs on the Settings page, the tool enums."""
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


# -- prompts --------------------------------------------------------------------------------------------

def test_the_prompt_for_german_to_french_names_both_languages_and_the_address():
    request = ai_tasks.translate_request("Folie.", "DE", "FR", "informal")
    assert request == ("Translate this slide from German to French.\nAddress the audience informally.\n"
                       "<slide>\nFolie.\n</slide>")


def test_the_prompt_for_french_to_english_still_carries_the_address():
    request = ai_tasks.translate_request("Diapo.", "FR", "EN", "formal")
    assert request.startswith("Translate this slide from French to English.\nAddress the audience formally.\n")
    assert "French slide" in ai_tasks.proofread_request("Diapo.", "FR")


def test_the_last_resort_prompt_names_the_pair(ctx):
    for source, target, name in (("de", "fr", "French"), ("fr", "en", "English"), ("en", "de", "German")):
        prompt = tp.get_effective_prompt(ctx, "any-model", source, target).prompt
        assert f"into {name}" in prompt and f"Output only the {name} translation" in prompt
        assert "{target}" not in prompt and "{source}" not in prompt
    assert "{target}" in tp.effective_default_prompt(ctx).prompt          # the template, for the Settings page


def test_a_prompt_of_the_user_with_placeholders_is_filled_in_too(ctx):
    tp.set_default_prompt(ctx, tp.PromptConfig("Translate {source} to {target}."))
    assert tp.get_effective_prompt(ctx, "m", "fr", "en").prompt == "Translate French to English."


# -- the form of address ----------------------------------------------------------------------------------

def test_the_address_falls_back_to_the_old_german_key(ctx):
    assert translation_style.address(ctx) == "formal" and translation_style.de_address(ctx) == "Sie"
    write_project(ctx, {"de_address": "du"})
    assert translation_style.address(ctx) == "informal" and translation_style.de_address(ctx) == "du"


def test_the_address_key_wins_and_set_address_writes_both_keys(ctx):
    write_project(ctx, {"de_address": "du", "address": "formal"})
    assert translation_style.address(ctx) == "formal"
    translation_style.set_address(ctx, "informal")
    data = project.read_project_json(ctx.root)
    assert data["address"] == "informal" and data["de_address"] == "du"
    assert translation_style.address(ctx) == "informal" and translation_style.de_address(ctx) == "du"
    translation_style.set_address(ctx, "formal")
    assert project.read_project_json(ctx.root)["de_address"] == "Sie"


# -- the glossary -----------------------------------------------------------------------------------------

TABLE = """| EN | DE | FR |
|----|----|----|
| slide | Folie | diapositive |
| deck | Foliensatz | |
"""


def test_a_glossary_table_gives_the_rows_of_the_pair():
    assert translation_style.glossary_for(TABLE, "EN", "DE") == "slide = Folie\ndeck = Foliensatz"
    assert translation_style.glossary_for(TABLE, "de", "fr") == "Folie = diapositive"      # a row needs both terms
    assert translation_style.glossary_for(TABLE, "FR", "EN") == "diapositive = slide"
    assert translation_style.glossary_for(TABLE, "FR", "ES") == ""


def test_the_old_lines_are_read_for_english_and_german_as_they_are():
    old = "slide = Folie\ndeck = Foliensatz\n"
    assert translation_style.glossary_for(old, "EN", "DE") == "slide = Folie\ndeck = Foliensatz"
    assert translation_style.glossary_for(old, "DE", "EN") == "slide = Folie\ndeck = Foliensatz"
    assert translation_style.glossary_for(old, "EN", "FR") == ""
    mixed = old + "\n" + TABLE
    assert translation_style.glossary_for(mixed, "DE", "FR") == "Folie = diapositive"


def test_a_request_carries_only_the_glossary_rows_of_its_pair():
    request = ai_tasks.translate_request("A slide.", "EN", "FR", glossary=TABLE)
    assert "Glossary, one term per line:\nslide = diapositive\n<slide>" in request
    assert "Folie" not in request
    assert "Glossary" not in ai_tasks.translate_request("A slide.", "EN", "ES", glossary=TABLE)
    update = ai_tasks.update_request("Neu.", "Nouveau.", "DE", "FR", glossary=TABLE)
    assert "Folie = diapositive\n<source>" in update


# -- the Settings page and the tools ----------------------------------------------------------------------

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
    # an English and German project offers what it always did
    default = [*languages.Languages("en", ("de",)).codes, "mult"]
    assert _with_project_languages(slidemage_tools.add_slide, default).spec.schema["properties"]["language"]["enum"] == [
        "EN", "DE", "mult"]
