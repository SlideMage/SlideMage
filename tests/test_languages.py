# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The language table and the project's languages (languages.py): reading and writing the key, and its cache."""
from __future__ import annotations

import json

import pytest

from slidemage import languages, project
from slidemage.project import ProjectContext


@pytest.fixture
def ctx(tmp_path):
    return ProjectContext.at(tmp_path / "proj")


def write_json(ctx, data) -> None:
    path = ctx.root / project.PROJECT_INFO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_table_has_unique_two_letter_lower_case_codes_and_a_tag_each():
    codes = [language.code for language in languages.TABLE]
    assert len(codes) == len(set(codes)) >= 40
    assert all(len(code) == 2 and code.islower() for code in codes)
    assert all(language.english and language.native and "-" in language.pdf_tag for language in languages.TABLE)


def test_names_and_tags_by_code_in_any_case_and_an_unknown_code_is_its_own():
    assert languages.name("fr") == "French" and languages.name("FR") == "French"
    assert languages.pdf_tag("fr") == "fr-FR" and languages.pdf_tag("en") == "en-US" and languages.pdf_tag("de") == "de-DE"
    assert languages.name("xx") == "xx" and languages.pdf_tag("xx") == "xx"
    assert languages.get("xx") is None and languages.get("DE").native == "Deutsch"


def test_a_project_without_the_key_has_english_and_german_and_nothing_is_written(ctx):
    found = languages.project_languages(ctx)
    assert found == languages.DEFAULT and found.codes == ("EN", "DE") and found.lower == ("en", "de")
    assert languages.is_default(ctx)
    assert not (ctx.root / project.PROJECT_INFO_PATH).exists()
    write_json(ctx, {"format": 1})
    assert languages.is_default(ctx)


def test_the_key_is_read_main_first(ctx):
    write_json(ctx, {"languages": {"main": "de", "secondary": ["en", "fr"]}})
    found = languages.project_languages(ctx)
    assert (found.main, found.secondary) == ("de", ("en", "fr"))
    assert found.codes == ("DE", "EN", "FR") and found.lower == ("de", "en", "fr")
    assert not languages.is_default(ctx)


@pytest.mark.parametrize("value", [
    "fr", [], {"secondary": ["de"]}, {"main": "FR"}, {"main": "fra"}, {"main": 3}, {"main": "fr", "secondary": "de"}])
def test_a_malformed_key_reads_as_the_default(ctx, value):
    write_json(ctx, {"languages": value})
    assert languages.project_languages(ctx) == languages.DEFAULT


def test_bad_and_repeated_secondary_codes_are_dropped(ctx):
    write_json(ctx, {"languages": {"main": "fr", "secondary": ["de", "fr", "de", "X1", 5, "it"]}})
    assert languages.project_languages(ctx).secondary == ("de", "it")


def test_a_project_with_the_default_languages_written_out_counts_as_default(ctx):
    languages.set_project_languages(ctx, "en", ["de"])
    assert languages.is_default(ctx)
    assert project.read_project_json(ctx.root)["languages"] == {"main": "en", "secondary": ["de"]}


def test_writing_keeps_the_other_keys_and_is_read_back(ctx):
    write_json(ctx, {"format": 1, "de_address": "du"})
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    assert project.read_project_json(ctx.root) == {
        "format": 1, "de_address": "du", "languages": {"main": "fr", "secondary": ["en", "de"]}}
    assert languages.project_languages(ctx).codes == ("FR", "EN", "DE")


def test_writing_a_bad_main_language_raises_and_writes_nothing(ctx):
    with pytest.raises(ValueError):
        languages.set_project_languages(ctx, "French", ["de"])
    assert not (ctx.root / project.PROJECT_INFO_PATH).exists()


def test_the_file_is_read_again_only_when_it_has_changed(ctx, monkeypatch):
    write_json(ctx, {"languages": {"main": "de", "secondary": ["en"]}})
    reads = []
    real = project.read_project_json
    monkeypatch.setattr(project, "read_project_json", lambda root: reads.append(root) or real(root))
    for _ in range(3):
        assert languages.project_languages(ctx).main == "de"
    assert len(reads) == 1
    write_json(ctx, {"languages": {"main": "fr", "secondary": ["en", "de"]}})     # another size: a change
    assert languages.project_languages(ctx).main == "fr" and len(reads) == 2
    languages.set_project_languages(ctx, "it", ["en"])
    assert languages.project_languages(ctx).main == "it"


def test_two_projects_do_not_share_a_cache_entry(tmp_path):
    first, second = ProjectContext.at(tmp_path / "a"), ProjectContext.at(tmp_path / "b")
    languages.set_project_languages(first, "fr", ["en"])
    assert languages.project_languages(first).main == "fr" and languages.is_default(second)
