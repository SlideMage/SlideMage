# Plan: deck groups the user can edit

Status: proposal, decisions taken (2026-10-22), not started. Asked for: "develop a plan to allow the user to edit the
tags that SlideMage offers." Decided: the groups belong to the project; built-in groups can be removed; a deck can
be in several groups.

## Today

A deck's group is a tag in its own file, `\decktags{course}`, which LaTeX ignores. `\decktags` already takes a
comma-separated list, but only the first known group tag counts. The set of groups is fixed in code:

| Tag | Shown as (switcher heading / Tags sheet) | Behaviour beyond the heading |
|---|---|---|
| `work` | none, pinned on top / "Workdeck (pinned to the top…)" | first in the switcher, no heading |
| `course` | "Course decks" / "Course deck" | the fallback: a deck without a known group tag is a course deck |
| `research` | "Research presentations" / "Research presentation" | none |
| `manual` | "SlideMage manual" / never offered | wins over every other tag; not selectable |
| `test` | "Test decks" / "Test deck" | `Deck.is_test_deck`: no slide list, skipped by background previews |

Where this is spread:

- `deck_scan.py`: `TAG_*`, `GROUP_TAGS` (precedence), `SELECTABLE_GROUP_TAGS`, `GROUP_ORDER`, `Deck.group` (property).
- `ui/dialogs/deck_group.py`: `GROUP_LABELS` for the Tags…, Duplicate deck… and New deck… sheets (one choice).
- `ui/workspace/menus.py`: `GROUP_HEADINGS`, the deck switcher and Deck → Switch deck.
- `compiler.order_jobs`: `GROUP_ORDER` decides the order a run works through decks.
- `deck_actions.tags_with_group`: replaces the group tag, keeps other tags.
- `background_renders.py`: `is_test_deck`.
- The manual (slide 1d8) and README list the four groups.

## Goal

The user can add groups of their own (say "Workshops", "Guest lectures"), rename how any group is shown, change the
order of the switcher's sections, remove any group (built-in ones too), and put a deck into several groups. Nothing
changes for a project that never edits its groups.

## Design

### 1. Groups are data; behaviours are roles a group may carry

A new module `deck_groups.py` holds the project's ordered list of groups:

```python
@dataclass(frozen=True)
class DeckGroup:
    tag: str          # what \decktags carries: lowercase a-z, 0-9, "-"; unique
    label: str        # the Tags sheet's choice, e.g. "Course deck"
    heading: str      # the switcher's section heading, e.g. "Course decks" ("" = no heading)
    roles: frozenset[str] = frozenset()   # "pinned", "test"
```

The behaviours hang on roles, not on tags:

- `pinned`: the group's decks come first in the switcher, without a heading.
- `test`: the group's decks have no slide list and get no background previews.

Any group may carry either role, and at most one group carries each. Removing the group that carries a role removes
the behaviour: a project without a `test` group simply has no test decks.

Two things stay outside the editable list because SlideMage itself needs them:

- **The manual's group** (`manual`): the SlideMage manual keeps its own section, never offered, never removable,
  as decided on 2026-10-05.
- **Ungrouped decks**: a deck whose tags name no group of the list. Today these become course decks because
  `course` is the fallback. With removable groups there is no guaranteed fallback group, so they get a section
  of their own, "Other decks", shown only when there is one. The list may name a group as the home of ungrouped
  decks instead (a `fallback` flag on one group); the defaults set it on `course`, so nothing moves.

The defaults reproduce today's table exactly: `work` (pinned), `course` (fallback), `research`, `test` (test).

### 2. Stored with the project

`.slidemage/project.json` under `"deck_groups"`, the file that already holds the project's shared AI policy. The
tags are written into the deck files, so the list that gives them meaning travels with the decks: a collaborator,
or the same user on another computer, sees the same groups. No entry means the defaults. Once the user edits the
list, it is written in full (removals have to be recorded too); a later SlideMage that changes a default label
does not touch a project that has its own list.

### 3. A deck in several groups

`\decktags{course,workshops}` puts a deck into both groups.

- **Deck switcher and Deck → Switch deck**: the deck is listed under each of its groups. The entry under the
  first group in switcher order is the main one; the others are marked as the same deck, e.g. by a small "also in
  Course decks" note, so that the list does not read as two decks.
- **Roles**: a deck is pinned if any of its groups is `pinned`, a test deck if any is `test`. A pinned deck is
  still listed under its other groups too.
- **Compile order**: by the deck's first group in switcher order, so a deck is compiled once.
- **Tags…, Duplicate deck…, New deck…**: the single choice becomes a list of checkboxes, one per group; at least
  none (an ungrouped deck is allowed). `tags_with_group` becomes `tags_with_groups`: it sets exactly the chosen
  group tags, in switcher order, and keeps every tag that is not a group's.
- **Collapsed sections** (`collapsed_deck_groups_active`) stay per group, as now.

`Deck.group` (one value) becomes `Deck.groups` (a tuple, in switcher order), set at scan time; `Deck.group` stays
as the first of them for the places that need one (compile order, the main entry).

### 4. Who reads the list

- `scan_decks(ctx)` loads the groups once and gives every `Deck` its `groups` and roles (fields set at scan time
  instead of the `group` property, which cannot see the project). `is_test_deck` reads the role.
- The deck switcher, Deck → Switch deck and the compile order take headings, order and roles from the list.
- The Tags…, Duplicate deck… and New deck… sheets offer every group of the list (never `manual`).

### 5. Editing: Settings → Project → Deck groups

A list of the groups in switcher order, each row: heading, label, tag (read-only), its roles as notes ("pinned on
top", "no slide list", "decks without a group go here"), and how many decks are in it. Buttons:

- **Add group…**: heading and label; the tag is proposed from the label (`Guest lectures` → `guest-lectures`) and
  can be edited until saved; refused if it is taken or reserved (`manual`).
- **Edit…**: heading, label and roles of any group, built-in ones too (moving a role moves it off the group that
  had it, after asking). The tag never changes: decks name it in their files.
- **Move up / Move down**: the switcher's section order and the compile order.
- **Remove**: any group. If decks carry its tag, the sheet says how many and offers: move them to another group
  (rewriting each `\decktags` with the stale-checked `deck_editor.set_deck_tags`, one undo step per deck as today),
  or take the tag off them (a deck left without a group goes to the fallback group, or to Other decks), or leave
  the tag in the files (it then names no group; the decks behave as if it were not there, and the tag shows under
  "Found in decks", below).
- **Restore the default groups**: the four groups of today, with their roles; groups of the user's own stay.

The same section is reachable from Deck → Tags… ("Edit groups…" under the checkboxes), where the need arises.

### 6. Tags the list does not know

A deck may carry a tag that is no group's (copied from another project, typed by hand, or left after a removal).
Settings → Deck groups shows such tags under "Found in decks", with the number of decks and an **Add as group**
button, so nothing is lost and nothing changes until the user decides. Tags that are not meant as groups stay
untouched in the files either way.

## Steps

1. `deck_groups.py`: the dataclass, defaults, load/save from project.json, validation (tag syntax, unique tags,
   each role on at most one group, at most one fallback). Tests: defaults equal today's table; a saved list
   round-trips; invalid lists are refused with a reason.
2. `deck_scan` and its users: `Deck.groups` and roles from the list, `Deck.group` the first; `GROUP_TAGS`,
   `GROUP_ORDER`, `SELECTABLE_GROUP_TAGS`, `GROUP_HEADINGS`, `GROUP_LABELS` become functions of the list; compile
   order and background previews follow. With the defaults and one group per deck the full suite must pass
   unchanged (the behaviour is identical).
3. Several groups per deck: the switcher's entries under each group with the "also in" note, Other decks, the
   checkbox sheets and `tags_with_groups`. Tests for a deck in two groups (both entries, one compile, roles).
4. Settings → Project → Deck groups: add, edit, reorder, remove with its three answers, restore defaults, "Found in
   decks". GUI tests for each, and for the Tags sheet offering a new group.
5. Deck → Tags… links to it.
6. Manual (slide 1d8, and the Settings list in 1r8), README, changelog with "Manual updated through …".

Steps 1 and 2 are a refactor with no visible change and can ship on their own; 3 to 6 are the feature.
