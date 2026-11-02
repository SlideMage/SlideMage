# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation groups: the slides of one original in any of the project's languages, as a star.

The fixture project (tests/fixtures/project_de_en_fr) has German as its main language, English and French as
secondary ones: aaa-DE-Eins is the original of bbb-EN-One and ccc-FR-Un."""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from slidemage import (
    background_renders, compiler, deck_language, deck_outline, deck_scan, slide_add, slide_language, slide_rename,
)
from slidemage.project import ProjectContext

FIXTURE = Path(__file__).parent / "fixtures" / "project_de_en_fr"
CODES = ("DE", "EN", "FR")
AAA, BBB, CCC, DDD = "aaa-DE-Eins", "bbb-EN-One", "ccc-FR-Un", "ddd-DE-Zwei"


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    return ProjectContext.at(root)


def slide_text(ctx, id_slug) -> str:
    return (ctx.slides_dir / slide_language.current_name(id_slug)).read_text(encoding="utf-8")


def write_slide(ctx, id_slug, header="", body="Text") -> None:
    (ctx.slides_dir / slide_language.current_name(id_slug)).write_text(
        header + f"\\begin{{standardframe}}{{T}}{body}\\end{{standardframe}}\n", encoding="utf-8")


def named(ctx, id_slug) -> list[str]:
    """What the "Translation of:" lines of a slide name."""
    return slide_language.TRANSLATION_OF_RE.findall(slide_text(ctx, id_slug))


def listed(ctx, id_slug) -> list[tuple[str, str]]:
    """The "<LANG> translation:" lines of a slide: (language, id-slug)."""
    return slide_language.LANG_TRANSLATION_RE.findall(slide_text(ctx, id_slug))


def deck(ctx, body, language="de"):
    path = ctx.decks_dir / "tmp.tex"
    path.write_text(f"\\documentclass{{beamer}}\n\\decklanguage[{language}]\n\\begin{{document}}\n{body}\\end{{document}}\n",
                    encoding="utf-8")
    return next(d for d in deck_scan.scan_dir(ctx.decks_dir, False) if d.path == path)


def slots(ctx, d, language):
    return deck_language.deck_slots(ctx, d, language)


# -- languages in a slide's name --------------------------------------------------------------------

def test_only_the_listed_codes_and_mult_are_a_language():
    assert slide_language.own_language("x7k-FR-Titre", CODES) == "FR"
    assert slide_language.own_language("x7k-FR-Titre", ("EN", "DE")) is None
    assert slide_language.own_language("x7k-mult-All", ("EN", "DE")) == "mult"
    assert slide_language.own_language("x7k-IT-Governance", CODES) is None
    assert slide_language.own_language("x7k-fr-Titre", CODES) is None
    assert slide_language.LANG_TRANSLATION_RE.findall("%% FR translation: a-FR-B\n%% mult translation: c-mult-D\n") == [
        ("FR", "a-FR-B"), ("mult", "c-mult-D")]


# -- the groups -------------------------------------------------------------------------------------

def test_a_group_is_the_original_and_its_translations(ctx):
    links = slide_language.links_for(ctx)
    assert links.codes == CODES
    for id_slug in (AAA, BBB, CCC):
        group = links.group(id_slug)
        assert (group.original, group.members, group.valid) == (AAA, {"DE": AAA, "EN": BBB, "FR": CCC}, True)
    assert links.group(DDD) == slide_language.Group(DDD, {"DE": DDD}, True)
    assert links.group("eee-mult-All").members == {}
    assert links.find(BBB, "FR") == CCC and links.find(AAA, "EN") == BBB and links.find(CCC, "DE") == AAA
    assert links.find(AAA, "DE") is None and links.find(DDD, "EN") is None and links.find("eee-mult-All", "EN") is None


def test_a_translation_is_found_from_either_side(ctx):
    write_slide(ctx, AAA)                                     # the original no longer names its translations
    write_slide(ctx, CCC, "%% Translation of: aaa-DE-Eins\n")
    links = slide_language.links_for(ctx)
    assert links.group(AAA).members == {"DE": AAA, "EN": BBB, "FR": CCC}
    write_slide(ctx, BBB)                                     # a link on one side only, from the original
    write_slide(ctx, AAA, "%% EN translation: bbb-EN-One\n")
    assert slide_language.links_for(ctx).group(BBB).original == AAA


def test_the_badge_lists_the_other_languages_of_the_group(ctx):
    links = slide_language.links_for(ctx)
    badges = {id_slug: slide_language.badge_for(ctx, id_slug, links=links) for id_slug in (AAA, BBB, CCC, DDD)}
    assert [b.text() for b in badges.values()] == ["[DE + EN FR]", "[EN + DE FR]", "[FR + DE EN]", "[DE]"]
    assert badges[AAA].languages == ("EN", "FR") and badges[AAA].both and not badges[DDD].both
    assert slide_language.translated_languages(ctx, CCC, links=links) == ("DE", "EN")
    assert slide_language.LanguageBadge("DE", ("EN", "FR", "ES")).text() == "[DE +3]"
    assert slide_language.LanguageBadge(None, ()).text() == "" and slide_language.badge_for(ctx, "x-Plain").text() == ""


def test_translation_group_links_each_other_member_and_measures_outdated_against_the_original(ctx):
    old = datetime(2026, 1, 1).timestamp()
    for id_slug in (AAA, BBB, CCC):
        os.utime(ctx.slides_dir / slide_language.current_name(id_slug), (old, old))
    backup = ctx.slides_dir / ".backups" / slide_language.current_name(AAA)
    backup.mkdir(parents=True)
    (backup / "20260301-090000.tex").write_text("old", encoding="utf-8")     # the original was saved in March
    from_english = slide_language.translation_group(ctx, BBB)
    assert [(l.language, l.partner, l.is_translation, l.is_original, l.outdated) for l in from_english] == [
        ("DE", AAA, True, False, True), ("FR", CCC, False, False, True)]
    from_original = slide_language.translation_group(ctx, AAA)
    assert [(l.language, l.is_translation, l.is_original, l.outdated) for l in from_original] == [
        ("EN", False, True, True), ("FR", False, True, True)]
    (ctx.slides_dir / ".backups" / slide_language.current_name(CCC)).mkdir()
    (ctx.slides_dir / ".backups" / slide_language.current_name(CCC) / "20260401-090000.tex").write_text("x", encoding="utf-8")
    assert [(l.language, l.outdated) for l in slide_language.translation_group(ctx, AAA)] == [("EN", True), ("FR", False)]
    assert slide_language.translation_group(ctx, DDD) == [] and slide_language.translation_group(ctx, "eee-mult-All") == []


def test_two_slides_in_one_language_pick_none(ctx):
    write_slide(ctx, "fff-FR-Autre", "%% Translation of: aaa-DE-Eins\n")
    links = slide_language.links_for(ctx)
    group = links.group(AAA)
    assert group.original == AAA and group.members == {"DE": AAA, "EN": BBB} and not group.valid
    assert links.find(AAA, "FR") is None and links.find(BBB, "FR") is None
    assert slide_language.translated_languages(ctx, AAA) == ("EN",)


# -- the slots of a deck ----------------------------------------------------------------------------

def test_a_deck_that_calls_the_original_and_a_translation_has_one_slot_at_the_original(ctx):
    d = deck(ctx, f"\\slide{{{DDD}}}\n\\slide{{{CCC}}}\n\\slide{{{AAA}}}\n")
    german = slots(ctx, d, "DE")
    assert [(s.original.id_slug, s.call.id_slug) for s in german] == [(DDD, DDD), (AAA, AAA)]
    assert [c.id_slug for c in german[1].folded] == [CCC]
    assert set(german[1].related_ids) == {"bbb", "ccc"}
    assert german[1].matches("bbb") and german[1].matches("ccc")
    assert [s.call.id_slug for s in slots(ctx, d, "FR")] == [DDD, CCC]               # shows the French file
    assert [s.call.id_slug for s in slots(ctx, d, "EN")] == [DDD, BBB]


def test_a_deck_that_calls_two_translations_has_one_slot_at_the_earlier_call(ctx):
    d = deck(ctx, f"\\slide{{{DDD}}}\n\\slide{{{CCC}}}\n\\slide{{{BBB}}}\n")
    found = slots(ctx, d, "DE")
    assert [(s.original.id_slug, s.call.id_slug) for s in found] == [(DDD, DDD), (CCC, AAA)]
    assert [c.id_slug for c in found[1].folded] == [BBB]
    assert [s.call.id_slug for s in slots(ctx, d, "EN")] == [DDD, BBB]
    outline = deck_outline.build_outline(ctx, d, "instructor", "FR")
    assert [row.badge for section in outline for row in section.rows] == ["[DE]", "[FR + DE EN]"]


def test_repeated_calls_of_the_original_keep_their_slots(ctx):
    d = deck(ctx, f"\\slide{{{AAA}}}\n\\slide{{{CCC}}}\n\\slide{{{AAA}}}\n")
    found = slots(ctx, d, "DE")
    assert [s.original.id_slug for s in found] == [AAA, AAA]
    assert all([c.id_slug for c in s.folded] == [CCC] for s in found)


def test_a_cycle_has_no_original_and_each_call_stays_its_own_slot(ctx):
    write_slide(ctx, BBB, "%% Translation of: ccc-FR-Un\n")
    write_slide(ctx, CCC, "%% Translation of: bbb-EN-One\n")
    write_slide(ctx, AAA)
    links = slide_language.links_for(ctx)
    group = links.group(BBB)
    assert group.original is None and not group.valid and group.members == {"EN": BBB, "FR": CCC}
    d = deck(ctx, f"\\slide{{{BBB}}}\n\\slide{{{CCC}}}\n")
    assert [s.original.id_slug for s in slots(ctx, d, "EN")] == [BBB, CCC]
    assert slide_language.translation_group(ctx, BBB)[0].outdated is False


# -- the links --------------------------------------------------------------------------------------

def test_a_chain_is_rewritten_as_a_star(ctx):
    write_slide(ctx, AAA, "%% EN translation: bbb-EN-One\n")
    write_slide(ctx, BBB, "%% Translation of: aaa-DE-Eins\n%% FR translation: ccc-FR-Un\n")
    write_slide(ctx, CCC, "%% Translation of: bbb-EN-One\n")
    group = slide_language.links_for(ctx).group(CCC)
    assert (group.original, group.valid) == (AAA, False)                    # the chain still resolves
    assert slide_language.links_for(ctx).find(CCC, "DE") == AAA
    changed, report = slide_rename.regenerate_translation_links(ctx)
    assert (changed, report) == (3, [])
    assert listed(ctx, AAA) == [("EN", BBB), ("FR", CCC)] and named(ctx, AAA) == []
    assert named(ctx, BBB) == [AAA] and listed(ctx, BBB) == []
    assert named(ctx, CCC) == [AAA] and listed(ctx, CCC) == []
    assert slide_language.links_for(ctx).group(CCC).valid
    assert slide_rename.regenerate_translation_links(ctx) == (0, [])


def test_regenerating_a_star_that_stands_changes_nothing(ctx):
    before = {p.name: p.read_bytes() for p in ctx.slides_dir.glob("*.tex")}
    assert slide_rename.regenerate_translation_links(ctx) == (0, [])
    assert {p.name: p.read_bytes() for p in ctx.slides_dir.glob("*.tex")} == before


def test_the_original_gets_a_line_per_translation_also_when_it_never_named_them(ctx):
    write_slide(ctx, AAA)
    assert slide_rename.regenerate_translation_links(ctx) == (1, [])
    assert listed(ctx, AAA) == [("EN", BBB), ("FR", CCC)]


def test_a_cycle_is_reported_and_left_as_it_is(ctx):
    write_slide(ctx, BBB, "%% Translation of: ccc-FR-Un\n")
    write_slide(ctx, CCC, "%% Translation of: bbb-EN-One\n")
    before = slide_text(ctx, BBB), slide_text(ctx, CCC)
    changed, report = slide_rename.regenerate_translation_links(ctx)
    assert changed == 0 and len(report) == 1 and BBB in report[0] and CCC in report[0] and "no original" in report[0]
    assert (slide_text(ctx, BBB), slide_text(ctx, CCC)) == before


def test_a_link_to_a_gone_slide_is_still_reported(ctx):
    (ctx.slides_dir / slide_language.current_name(CCC)).unlink()
    changed, report = slide_rename.regenerate_translation_links(ctx)
    assert changed == 0 and len(report) == 1 and "ccc-FR-Un" in report[0]


# -- make original ----------------------------------------------------------------------------------

def test_making_a_translation_the_original(ctx):
    write_slide(ctx, "hhh-ES-Tres", "%% Translation of: aaa-DE-Eins\n")                    # Spanish is not a project language
    slide_rename.make_original(ctx, CCC)
    assert named(ctx, CCC) == [] and [lang for lang, _ in listed(ctx, CCC)] == ["DE", "EN"]
    assert named(ctx, AAA) == [CCC] and listed(ctx, AAA) == []
    assert named(ctx, BBB) == [CCC] and listed(ctx, BBB) == []
    group = slide_language.links_for(ctx).group(AAA)
    assert (group.original, group.valid, group.members) == (CCC, True, {"DE": AAA, "EN": BBB, "FR": CCC})
    assert not any(link.outdated for id_slug in (AAA, BBB, CCC) for link in slide_language.translation_group(ctx, id_slug))
    assert slide_rename.regenerate_translation_links(ctx) == (0, [])


def test_making_the_english_translation_the_original(ctx):
    slide_rename.make_original(ctx, BBB)
    assert (slide_language.links_for(ctx).group(AAA).original, named(ctx, CCC), named(ctx, BBB)) == (BBB, [BBB], [])
    assert [lang for lang, _ in listed(ctx, BBB)] == ["DE", "FR"]


def test_the_slot_moves_to_the_new_original_s_call(ctx):
    d = deck(ctx, f"\\slide{{{AAA}}}\n\\slide{{{CCC}}}\n")
    assert [s.original.id_slug for s in slots(ctx, d, "DE")] == [AAA]
    slide_rename.make_original(ctx, CCC)
    d = deck(ctx, f"\\slide{{{AAA}}}\n\\slide{{{CCC}}}\n")
    found = slots(ctx, d, "DE")
    assert [(s.original.id_slug, s.call.id_slug) for s in found] == [(CCC, AAA)]
    assert [c.id_slug for c in found[0].folded] == [AAA]


def test_make_original_refuses_a_slide_of_no_language_and_leaves_an_original_as_it_is(ctx):
    with pytest.raises(ValueError):
        slide_rename.make_original(ctx, "eee-mult-All")
    before = {p.name: p.read_bytes() for p in ctx.slides_dir.glob("*.tex")}
    slide_rename.make_original(ctx, AAA)
    slide_rename.make_original(ctx, DDD)
    assert {p.name: p.read_bytes() for p in ctx.slides_dir.glob("*.tex")} == before


# -- what follows from the project's languages ------------------------------------------------------

def test_a_new_slide_is_tagged_with_a_project_language(ctx):
    created = slide_add.create_new(ctx, "Neu", "FR")
    assert created.id_slug.endswith("-FR-Neu")
    with pytest.raises(ValueError):
        slide_add.create_new(ctx, "Neu", "ES")


def test_the_languages_a_slide_can_be_translated_into(ctx):
    assert slide_add.other_languages(ctx, AAA) == ["EN", "FR", "mult"]
    assert slide_add.other_languages(ctx, CCC) == ["DE", "EN", "mult"]
    assert slide_add.slug_of(ctx, CCC) == "Un" and slide_add.slug_of(ctx, "ggg-ES-Tres") == "ES-Tres"


def test_a_model_is_offered_every_pair_of_project_languages(ctx):
    assert slide_add.can_machine_translate(ctx, AAA, "FR") and slide_add.can_machine_translate(ctx, CCC, "DE")
    assert not slide_add.can_machine_translate(ctx, CCC, "ES") and not slide_add.can_machine_translate(ctx, CCC, "FR")
    assert not slide_add.can_machine_translate(ctx, "eee-mult-All", "DE")


def test_the_pdfs_of_every_project_language_are_found(ctx):
    d = deck(ctx, f"\\slide{{{AAA}}}\n")
    (ctx.root / "pdf").mkdir()
    for name in ("tmp", "tmp-en", "tmp-fr", "tmp-es"):
        (ctx.root / "pdf" / f"{name}.pdf").write_bytes(b"%PDF-1.4\n")
    labels = {p.label for p in compiler.deck_pdfs(ctx, d)}
    assert labels == {"Instructor", "Instructor · EN", "Instructor · FR"}                   # not Spanish, not a language


def test_background_previews_start_from_the_decks_language(ctx, monkeypatch):
    d = deck(ctx, f"\\slide{{{AAA}}}\n", "fr")
    me = SimpleNamespace(ctx=ctx)
    monkeypatch.setattr(background_renders, "setting", lambda _ctx, key, default: False)
    assert background_renders.BackgroundRenderer.languages_for(me, d) == ["FR"]
    monkeypatch.setattr(background_renders, "setting", lambda _ctx, key, default: True)
    assert background_renders.BackgroundRenderer.languages_for(me, d) == ["FR", "DE", "EN"]
    assert background_renders.BackgroundRenderer.languages_for(me, deck(ctx, "", "es")) == ["ES", "DE", "EN", "FR"]


def test_the_unused_content_and_header_scans_follow_every_language(ctx):
    from slidemage import deck_headers, unused_content

    d = deck(ctx, f"\\slide{{{CCC}}}\n")
    used = unused_content.slide_filenames_in(ctx, d.text)
    assert {slide_language.current_name(s) for s in (AAA, BBB, CCC)} <= used
    memberships, _paths = deck_headers._deck_membership(ctx)
    assert {"aaa", "bbb", "ccc"} <= set(memberships)
