# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project's deck groups (docs/plans/editable-deck-tags.md): an ordered list, the deck switcher's sections
top to bottom and the order a compile run works through the decks of one version.

A deck names its groups by tag in its own file, \\decktags{course,workshops}. A group's behaviours beyond its
heading are roles: `pinned` (first in the switcher, without a heading) and `test` (no slide list, no background
previews). At most one group carries each role, and at most one is the `fallback`, the home of a deck whose tags
name no group of the list.

The manual's group (`manual`) is not part of the list: SlideMage itself needs it, so it is never offered, never
removable, and wins over every other tag (2026-10-05). In the switcher it stands before the test group, or last.

Stored in the project's .slidemage/project.json under "deck_groups", next to the shared AI policy, so the list
travels with the decks whose tags it gives meaning. No entry means DEFAULT_GROUPS; once edited, the list is written
in full, so removed groups stay removed and a later SlideMage's new default labels leave it alone.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from . import project

KEY = "deck_groups"

ROLE_PINNED = "pinned"
ROLE_TEST = "test"
ROLES = (ROLE_PINNED, ROLE_TEST)

TAG_WORK = "work"
TAG_COURSE = "course"
TAG_RESEARCH = "research"
TAG_TEST = "test"
TAG_MANUAL = "manual"
RESERVED_TAGS = (TAG_MANUAL,)

TAG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class DeckGroup:
    tag: str                                # what \decktags carries: lowercase a-z, 0-9 and "-"; unique
    label: str                              # the Tags sheet's choice, e.g. "Course deck"
    heading: str                            # the switcher's section heading ("" = no heading)
    roles: frozenset[str] = frozenset()     # ROLE_PINNED, ROLE_TEST
    fallback: bool = False                  # the home of decks whose tags name no group

    def to_json(self) -> dict:
        data = {"tag": self.tag, "label": self.label, "heading": self.heading}
        if self.roles:
            data["roles"] = [role for role in ROLES if role in self.roles] + sorted(self.roles - set(ROLES))
        if self.fallback:
            data["fallback"] = True
        return data

    @classmethod
    def from_json(cls, data: object) -> DeckGroup:
        """Raises ValueError for an entry that is not a group at all; validate() judges the list."""
        if not isinstance(data, dict):
            raise ValueError("a group is not an object")
        tag, label, heading = data.get("tag"), data.get("label", ""), data.get("heading", "")
        roles, fallback = data.get("roles", []), data.get("fallback", False)
        if not (isinstance(tag, str) and isinstance(label, str) and isinstance(heading, str)
                and isinstance(roles, list) and all(isinstance(r, str) for r in roles) and isinstance(fallback, bool)):
            raise ValueError(f"group {tag!r} has a field of the wrong type")
        return cls(tag, label, heading, frozenset(roles), fallback)


# Today's table, exactly (before the groups became editable).
DEFAULT_GROUPS: tuple[DeckGroup, ...] = (
    DeckGroup(TAG_WORK, "Workdeck (pinned to the top of the deck switcher)", "", frozenset({ROLE_PINNED})),
    DeckGroup(TAG_COURSE, "Course deck", "Course decks", fallback=True),
    DeckGroup(TAG_RESEARCH, "Research presentation", "Research presentations"),
    DeckGroup(TAG_TEST, "Test deck", "Test decks", frozenset({ROLE_TEST})),
)
MANUAL_GROUP = DeckGroup(TAG_MANUAL, "SlideMage manual", "SlideMage manual")


def validate(groups: Sequence[DeckGroup]) -> str | None:
    """Why `groups` cannot be the project's list, or None if it can."""
    seen: set[str] = set()
    for group in groups:
        if not TAG_RE.fullmatch(group.tag):
            return f"The tag {group.tag!r} may only have lowercase letters, digits and single hyphens between them."
        if group.tag in RESERVED_TAGS:
            return f"The tag {group.tag!r} is reserved for SlideMage."
        if group.tag in seen:
            return f"The tag {group.tag!r} is used by two groups."
        seen.add(group.tag)
        if not group.label.strip():
            return f"The group {group.tag!r} has no label."
        unknown = sorted(group.roles - set(ROLES))
        if unknown:
            return f"The group {group.tag!r} has an unknown role {unknown[0]!r}."
    for role in ROLES:
        carriers = [g.tag for g in groups if role in g.roles]
        if len(carriers) > 1:
            return f"Only one group can have the role {role!r}, not {', '.join(carriers)}."
    fallbacks = [g.tag for g in groups if g.fallback]
    if len(fallbacks) > 1:
        return f"Only one group can take the decks without a group, not {', '.join(fallbacks)}."
    return None


def from_json(data: object) -> tuple[DeckGroup, ...]:
    """The list stored as `data`; ValueError with the reason if it is not a valid list."""
    if not isinstance(data, list):
        raise ValueError("the deck groups are not a list")
    groups = tuple(DeckGroup.from_json(item) for item in data)
    reason = validate(groups)
    if reason is not None:
        raise ValueError(reason)
    return groups


def to_json(groups: Sequence[DeckGroup]) -> list[dict]:
    return [group.to_json() for group in groups]


def load(ctx: project.ProjectContext) -> tuple[DeckGroup, ...]:
    """The project's groups: DEFAULT_GROUPS without an entry, and also for an entry this SlideMage cannot use
    (written by hand, or by a newer SlideMage), which stays in the file until the user saves a list."""
    data = project.read_project_json(ctx.root).get(KEY)
    if data is None:
        return DEFAULT_GROUPS
    try:
        return from_json(data)
    except ValueError:
        return DEFAULT_GROUPS


def save(ctx: project.ProjectContext, groups: Sequence[DeckGroup]) -> None:
    """Writes `groups` in full; ValueError with the reason if they are not a valid list."""
    reason = validate(groups)
    if reason is not None:
        raise ValueError(reason)
    data = project.read_project_json(ctx.root)
    data[KEY] = to_json(groups)
    project.write_project_json(ctx.root, data)


def tag_from_label(label: str) -> str:
    """A tag proposed for a new group's label: "Guest lectures" -> "guest-lectures" ("" if nothing is left)."""
    return "-".join(re.findall(r"[a-z0-9]+", label.lower()))


# -- what the list means for a deck and for the switcher --------------------------------------------------------------

def groups_of(tags: Iterable[str], groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> tuple[str, ...]:
    """The groups a deck with `tags` is in, in switcher order: ("manual",) for the manual whatever else it
    carries, else every group of the list it names, else the fallback group, else none."""
    tags = set(tags)
    if TAG_MANUAL in tags:
        return (TAG_MANUAL,)
    named = tuple(g.tag for g in groups if g.tag in tags)
    if named:
        return named
    fallback = fallback_tag(groups)
    return (fallback,) if fallback else ()


def roles_of(group_tags: Iterable[str], groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> frozenset[str]:
    """The roles of a deck in `group_tags`: those of any of its groups."""
    group_tags = set(group_tags)
    return frozenset(role for g in groups if g.tag in group_tags for role in g.roles)


def fallback_tag(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> str | None:
    return next((g.tag for g in groups if g.fallback), None)


def tag_with_role(role: str, groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> str | None:
    return next((g.tag for g in groups if role in g.roles), None)


def switcher_order(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> tuple[str, ...]:
    """Every group's tag top to bottom, the manual's included: the list's order, the manual before the test
    group (or last). Also the order a compile run works through the decks of one version."""
    tags = [g.tag for g in groups]
    test = tag_with_role(ROLE_TEST, groups)
    tags.insert(tags.index(test) if test else len(tags), TAG_MANUAL)
    return tuple(tags)


def group_tags(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> tuple[str, ...]:
    """Every tag that names a group, the manual's first: a deck's other tags are not groups."""
    return (TAG_MANUAL,) + tuple(g.tag for g in groups)


def selectable_tags(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> tuple[str, ...]:
    """The groups a user can choose for a deck (Tags…, Duplicate deck…, New deck…): never the manual's."""
    return tuple(g.tag for g in groups)


def headings(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> dict[str, str]:
    """Each group's switcher heading by tag, the manual's included ("" = none)."""
    return {g.tag: g.heading for g in (*groups, MANUAL_GROUP)}


def labels(groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> dict[str, str]:
    """Each selectable group's label by tag, in the list's order."""
    return {g.tag: g.label for g in groups}
