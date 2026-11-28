# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import shutil

import pytest

from slidemage import languages, project
from slidemage.project import ProjectContext

pytestmark = pytest.mark.infer_languages


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


def slide(ctx, name: str) -> None:
    ctx.slides_dir.mkdir(parents=True, exist_ok=True)
    (ctx.slides_dir / name).write_text("x\n", encoding="utf-8")


@pytest.mark.parametrize("where", ["slide", "frozen slide", "deck", "archived deck", "description", "takeaway", "address"])
def test_german_anywhere_in_a_project_without_the_key_makes_german_a_secondary_language(tmp_path, where):
    ctx = ProjectContext.at(tmp_path / "proj")
    slide(ctx, "1aa-EN-One-current.tex")
    deck = "\\documentclass{beamer}\n\\decklanguage[DE]\n"
    match where:
        case "slide":
            slide(ctx, "1ab-DE-Eins-current.tex")
        case "frozen slide":
            slide(ctx, "1ab-DE-Eins-v1-0-0.tex")
        case "deck":
            ctx.decks_dir.mkdir()
            (ctx.decks_dir / "d.tex").write_text(deck, encoding="utf-8")
        case "archived deck":
            ctx.archive_dir.mkdir(parents=True)
            (ctx.archive_dir / "d.tex").write_text(deck, encoding="utf-8")
        case "description":
            ctx.media_dir.mkdir()
            (ctx.media_dir / "alt-text.json").write_text(
                json.dumps({"images": {"media/a.png": {"short": "x", "short_de": "y"}}}), encoding="utf-8")
        case "takeaway":
            ctx.media_dir.mkdir()
            (ctx.media_dir / "alt-text.json").write_text(
                json.dumps({"images": {"media/a.png": {"used_on": {"1aa": {"takeaway_de": "y"}}}}}), encoding="utf-8")
        case "address":
            write_json(ctx, {"de_address": "du"})
    assert languages.project_languages(ctx) == languages.Languages("en", ("de",))


def test_english_decks_and_descriptions_do_not_make_german_a_language(ctx):
    slide(ctx, "1aa-EN-One-current.tex")
    ctx.decks_dir.mkdir()
    (ctx.decks_dir / "d.tex").write_text("\\decklanguage[en]\n\\decklanguage[\\decklanguageoverride]\n", encoding="utf-8")
    ctx.media_dir.mkdir()
    (ctx.media_dir / "alt-text.json").write_text(
        json.dumps({"images": {"media/a.png": {"short": "x", "short_de": "", "used_on": {"1aa": {"takeaway": "t"}}}}}),
        encoding="utf-8")
    assert languages.project_languages(ctx).codes == ("EN",)
    assert not (ctx.root / project.PROJECT_INFO_PATH).exists()


def test_a_project_that_cannot_be_written_keeps_the_inferred_languages(ctx, monkeypatch):
    slide(ctx, "1ab-DE-Eins-current.tex")
    def refuse(root, data):
        raise PermissionError("read-only")
    monkeypatch.setattr(project, "write_project_json", refuse)
    languages.migrate(ctx)
    assert languages.project_languages(ctx) == languages.Languages("en", ("de",))
    assert not (ctx.root / project.PROJECT_INFO_PATH).exists()


def test_a_snapshot_is_not_migrated(tmp_path):
    from slidemage import cli
    snapshot = tmp_path / "snapshot"
    write_json(ProjectContext.at(snapshot), {"format": 1, "snapshot": {"of": "decks/x.tex"}})
    assert cli.check_project_format(snapshot, "v0.13.25")
    assert "languages" not in project.read_project_json(snapshot)


def test_a_new_project_states_its_languages(tmp_path, monkeypatch):
    example = tmp_path / "example"           # an example that was open in the app, with French as its main language
    template_dir = project.template_dir
    shutil.copytree(template_dir("example"), example, ignore=shutil.ignore_patterns(".build", ".previews"))
    (example / project.PROJECT_INFO_PATH).parent.mkdir(exist_ok=True)
    (example / project.PROJECT_INFO_PATH).write_text('{"languages": {"main": "fr", "secondary": ["en"]}}', encoding="utf-8")
    monkeypatch.setattr(project, "template_dir", lambda name: example if name == "example" else template_dir(name))
    empty = tmp_path / "empty"
    project.init_project(empty, copy_example=False)
    assert project.read_project_json(empty)["languages"] == {"main": "en", "secondary": []}
    with_manual = tmp_path / "manual"
    project.init_project(with_manual, copy_example=True)
    assert project.read_project_json(with_manual)["languages"] == {"main": "en", "secondary": ["de"]}


@pytest.mark.parametrize("value", [
    "fr", {"secondary": ["de"]}, {"main": "FR"}, {"main": 3}, {"main": "fr", "secondary": "de"},
])
def test_a_malformed_key_reads_like_a_missing_one(ctx, value):
    slide(ctx, "1ab-DE-Eins-current.tex")
    write_json(ctx, {"languages": value})
    assert languages.project_languages(ctx) == languages.Languages("en", ("de",))


def test_bad_and_repeated_secondary_codes_are_dropped(ctx):
    write_json(ctx, {"languages": {"main": "fr", "secondary": ["de", "fr", "de", "X1", 5, "it"]}})
    found = languages.project_languages(ctx)
    assert found.codes == ("FR", "DE", "IT") and found.lower == ("fr", "de", "it")


def test_writing_languages_keeps_other_keys_and_supports_one_language(ctx):
    write_json(ctx, {"format": 1, "de_address": "du"})
    languages.set_project_languages(ctx, "fr", ["en", "de"])
    assert project.read_project_json(ctx.root) == {
        "format": 1, "de_address": "du", "languages": {"main": "fr", "secondary": ["en", "de"]}}
    assert languages.project_languages(ctx).codes == ("FR", "EN", "DE")

    languages.set_project_languages(ctx, "fr", [])
    assert project.read_project_json(ctx.root) == {
        "format": 1, "de_address": "du", "languages": {"main": "fr", "secondary": []}}
    assert languages.project_languages(ctx).codes == ("FR",)


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
    assert languages.project_languages(first).main == "fr" and languages.project_languages(second).main == "en"
