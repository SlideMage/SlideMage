# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""deck_groups: the project's list of deck groups, its defaults, storage in project.json and validation."""
from __future__ import annotations

import json

import pytest

from slidemage import deck_groups, deck_scan, project
from slidemage.deck_groups import DEFAULT_GROUPS, ROLE_PINNED, ROLE_TEST, DeckGroup


def ctx_at(tmp_path) -> project.ProjectContext:
    (tmp_path / ".slidemage").mkdir()
    return project.ProjectContext.at(tmp_path)


def test_defaults_are_the_table_of_before():
    assert [(g.tag, g.label, g.heading, g.roles, g.fallback) for g in DEFAULT_GROUPS] == [
        ("work", "Workdeck (pinned to the top of the deck switcher)", "", frozenset({ROLE_PINNED}), False),
        ("course", "Course deck", "Course decks", frozenset(), True),
        ("research", "Research presentation", "Research presentations", frozenset(), False),
        ("test", "Test deck", "Test decks", frozenset({ROLE_TEST}), False),
    ]
    assert deck_groups.validate(DEFAULT_GROUPS) is None
    assert deck_groups.switcher_order() == ("work", "course", "research", "manual", "test")
    assert deck_groups.group_tags() == ("manual", "work", "course", "research", "test")
    assert deck_groups.selectable_tags() == ("work", "course", "research", "test")
    assert deck_groups.headings() == {"work": "", "course": "Course decks", "research": "Research presentations",
                                      "test": "Test decks", "manual": "SlideMage manual"}


@pytest.mark.parametrize("tags, groups, roles", [
    ([], ("course",), set()),                        # no group tag: the fallback
    (["intro", "course"], ("course",), set()),       # other tags are not groups
    (["research", "work"], ("work", "research"), {ROLE_PINNED}),   # switcher order, not file order
    (["test"], ("test",), {ROLE_TEST}),
    (["test", "manual"], ("manual",), set()),        # the manual wins
])
def test_a_decks_groups_and_roles(tags, groups, roles):
    assert deck_groups.groups_of(tags) == groups
    assert deck_groups.roles_of(groups) == roles


def test_no_project_entry_means_the_defaults(tmp_path):
    assert deck_groups.load(ctx_at(tmp_path)) == DEFAULT_GROUPS


def test_a_saved_list_round_trips_and_keeps_the_other_keys(tmp_path):
    ctx = ctx_at(tmp_path)
    project.write_project_json(ctx.root, {"ai": {"policy": "local"}})
    groups = (DeckGroup("guest-lectures", "Guest lecture", "Guest lectures", fallback=True),
              DeckGroup("work", "Workdeck", "", frozenset({ROLE_PINNED})),
              DeckGroup("lab", "Lab deck", "Labs", frozenset({ROLE_TEST})))
    deck_groups.save(ctx, groups)
    assert deck_groups.load(ctx) == groups
    data = project.read_project_json(ctx.root)
    assert data["ai"] == {"policy": "local"}
    assert data["deck_groups"][0] == {"tag": "guest-lectures", "label": "Guest lecture", "heading": "Guest lectures",
                                      "fallback": True}


def test_an_empty_list_is_kept(tmp_path):
    ctx = ctx_at(tmp_path)
    deck_groups.save(ctx, ())
    assert deck_groups.load(ctx) == ()
    assert deck_groups.groups_of(["course"], ()) == ()
    assert deck_groups.switcher_order(()) == ("manual",)


@pytest.mark.parametrize("groups, reason", [
    ([DeckGroup("Guest", "G", "G")], "lowercase letters"),
    ([DeckGroup("guest lectures", "G", "G")], "lowercase letters"),
    ([DeckGroup("guest-", "G", "G")], "lowercase letters"),
    ([DeckGroup("", "G", "G")], "lowercase letters"),
    ([DeckGroup("manual", "M", "M")], "reserved"),
    ([DeckGroup("a", "A", "A"), DeckGroup("a", "B", "B")], "two groups"),
    ([DeckGroup("a", " ", "A")], "no label"),
    ([DeckGroup("a", "A", "A", frozenset({"hidden"}))], "unknown role"),
    ([DeckGroup("a", "A", "A", frozenset({ROLE_TEST})), DeckGroup("b", "B", "B", frozenset({ROLE_TEST}))],
     "Only one group can have the role 'test'"),
    ([DeckGroup("a", "A", "A", fallback=True), DeckGroup("b", "B", "B", fallback=True)], "decks without a group"),
])
def test_an_invalid_list_is_refused_with_a_reason(tmp_path, groups, reason):
    assert reason in deck_groups.validate(groups)
    ctx = ctx_at(tmp_path)
    with pytest.raises(ValueError, match=reason):
        deck_groups.save(ctx, groups)
    assert "deck_groups" not in project.read_project_json(ctx.root)
    with pytest.raises(ValueError, match=reason):
        deck_groups.from_json(deck_groups.to_json(groups))


@pytest.mark.parametrize("stored", [
    "work", [{"tag": "a"}, "b"], [{"tag": 1, "label": "A", "heading": "A"}],
    [{"tag": "a", "label": "A", "heading": "A", "roles": "test"}],
    [{"tag": "a", "label": "A", "heading": "A"}, {"tag": "a", "label": "B", "heading": "B"}],
])
def test_a_stored_list_that_cannot_be_used_reads_as_the_defaults(tmp_path, stored):
    ctx = ctx_at(tmp_path)
    (tmp_path / project.PROJECT_INFO_PATH).write_text(json.dumps({"deck_groups": stored}), encoding="utf-8")
    assert deck_groups.load(ctx) == DEFAULT_GROUPS


def test_tag_from_label():
    assert deck_groups.tag_from_label("Guest lectures") == "guest-lectures"
    assert deck_groups.tag_from_label("  Ökonomie 2: Übungen ") == "konomie-2-bungen"
    assert deck_groups.tag_from_label("!!") == ""


def test_scan_takes_groups_and_roles_from_the_projects_list(tmp_path):
    ctx = ctx_at(tmp_path)
    ctx.decks_dir.mkdir()
    for name, tags in [("a", "workshops"), ("b", "course"), ("c", ""), ("d", "lab,course")]:
        (ctx.decks_dir / f"{name}.tex").write_text(
            f"\\documentclass{{beamer}}\n\\decktags{{{tags}}}\n\\begin{{document}}\n\\end{{document}}\n",
            encoding="utf-8")
    deck_groups.save(ctx, (DeckGroup("lab", "Lab deck", "Labs", frozenset({ROLE_TEST})),
                           DeckGroup("workshops", "Workshop", "Workshops", fallback=True),
                           DeckGroup("course", "Course deck", "Course decks")))
    decks = {d.name: d for d in deck_scan.scan_decks(ctx)}
    assert decks["a"].groups == ("workshops",) and decks["a"].group == "workshops"
    assert decks["b"].groups == ("course",) and not decks["b"].is_test_deck
    assert decks["c"].groups == ("workshops",)                        # the fallback
    assert decks["d"].groups == ("lab", "course") and decks["d"].group == "lab" and decks["d"].is_test_deck
