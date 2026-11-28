# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Where a slide is used, and what a new version means for those decks
(v5.23.0, direct instruction).

Saving a new version of a slide freezes the old content as -vX-Y-Z and puts
the new content in -current. A deck that calls \slide{ID} follows -current,
so it moves on to the new version by itself; a deck that calls
\slideversion{ID}{X-Y-Z} stays on its pinned version. When a slide is used
in several decks (or pinned somewhere, or has a translation), the save
dialog (ui/dialogs/slide_usage_dialog.py) asks for each deck:

- Leave calls as written (the default) keeps both kinds of call unchanged.
- "current": the deck uses the new version. A pinned call
  (\slideversion, \omitslideversion) becomes \slide / \omitslide; a call
  that follows -current already does.
- "keep": the deck stays on what it uses now. A call that follows -current is
  pinned to the version that was just frozen (\slide -> \slideversion,
  \omitslide -> \omitslideversion); a pinned call is left alone.

\slidefinal, \conditionalslide and \slidestep have no pinned form, so a
deck using only those always follows -current (the dialog says so).

A linked block is one call file and one choice, shared by every deck using it.
Choices are keyed by file path; Keep pins the block file once.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import deck_editor, deck_language, languages, slide_language, slide_versioning
from .deck_scan import Deck, deck_from_text, read_deck, scan_decks
from .fileio import Edits
from .project import ProjectContext

PINNED = deck_editor.PINNED_TO_PLAIN
PINNABLE = deck_editor.PLAIN_TO_PINNED


@dataclass
class DeckUsage:
    deck: Deck
    calls: list = field(default_factory=list)       # deck_editor.SlideCall
    positions: list = field(default_factory=list)   # 1-based place of each call among the deck's slide calls
    total: int = 0                                  # the file's slide calls
    block: Optional[str] = None
    decks: list[Deck] = field(default_factory=list)  # decks reached through this block

    @property
    def pinned_versions(self) -> list[str]:
        return sorted({c.version for c in self.calls if c.macro in PINNED})

    @property
    def following(self) -> bool:
        """At least one call follows -current and can be pinned."""
        return any(c.macro in PINNABLE for c in self.calls)

    @property
    def only_unpinnable(self) -> bool:
        """Every call is of a kind that always follows -current."""
        return all(c.macro not in PINNED and c.macro not in PINNABLE for c in self.calls)

    def state_text(self) -> str:
        parts = []
        if self.pinned_versions:
            parts.append("pinned to " + ", ".join(slide_versioning.version_label(v) for v in self.pinned_versions))
        if self.following:
            parts.append("follows the current version")
        if self.only_unpinnable:
            macros = sorted({c.macro for c in self.calls})
            parts = ["always the current version (\\" + ", \\".join(macros) + ")"]
        return "; ".join(parts)


def call_text(call: deck_editor.SlideCall) -> str:
    r"""How a deck calls the slide: "\slide, follows the current version", "\slideversion,
    frozen v1.0.0", "\slidestep, steps 2"."""
    if call.macro in PINNED:
        how = "frozen " + slide_versioning.version_label(call.version)
    elif call.macro in PINNABLE:
        how = "follows the current version"
    else:
        how = f"steps {call.steps}" if call.steps else "always the current version"
    return f"\\{call.macro}, {how}"


@dataclass
class Translation:
    id_slug: str
    language: Optional[str]
    path: Path
    decks: list[str]


def _real_decks(ctx: ProjectContext, decks: Optional[list[Deck]]) -> list[Deck]:
    """The decks usage is reported for: the scan (or `decks`) without #workdeck and zzz_ decks."""
    return [d for d in (scan_decks(ctx) if decks is None else decks) if not d.name.startswith(("#", "zzz_"))]


def deck_calls(ctx: ProjectContext, decks: Optional[list[Deck]] = None) -> list[tuple[Deck, list[deck_language.ExpandedCall]]]:
    """Every real deck with its expanded calls: the one resolution behind all usage views."""
    return [(deck, deck_language.active_calls(deck)) for deck in _real_decks(ctx, decks)]


def decks_by(scanned: list[tuple[Deck, list]], field: str) -> dict:
    """The decks whose calls have each value of `field`: a slide ("id"), a block ("block") or the
    file a call is written in ("source"). A deck is never listed for its own file."""
    users = defaultdict(list)
    for deck, calls in scanned:
        for value in dict.fromkeys(getattr(call, field) for call in calls):
            if value not in (None, deck.path):
                users[value].append(deck)
    return users


def find_usage(ctx: ProjectContext, id_slug: str, decks: Optional[list[Deck]] = None, *, language: Optional[str] = None) -> list[DeckUsage]:
    """Files holding calls of this slide, with the decks reached through each block.

    `decks` reuses an existing scan. With `language` the usage is as shown in the UI: one entry per
    real deck, its calls resolved to that language and numbered among the slides it shows. Without,
    the calls are as written in each physical file, and a block or fragment is an entry of its own.
    """
    if language is not None:
        links = slide_language.links_for(ctx)
        files = [(deck, [s.call for s in deck_language.deck_slots(ctx, deck, language, links=links)], None, [])
                 for deck in _real_decks(ctx, decks)]
        return usages_in(files, id_slug)
    scanned = deck_calls(ctx, decks)
    blocks = (read_deck(p) for p in deck_language.block_files(ctx))
    return usages_in(physical_files(ctx, scanned, blocks), id_slug)


def physical_files(ctx, scanned, blocks):
    users = decks_by(scanned, "source")
    files = {deck.path: deck for deck, _ in scanned}
    for _, calls in scanned:
        for call in calls:
            if call.source not in files:
                files[call.source] = deck_from_text(call.source, call.source_text)
    for block in blocks:
        files.setdefault(block.path, block)
    return [(deck, deck_language.calls_in(deck.text, deck.chapters, comments=True),
             path.stem if path.parent == ctx.blocks_dir or path in users else None, users.get(path, []))
            for path, deck in files.items()]


def revision_usages(scanned, id_slug: str) -> list[DeckUsage]:
    """Map only this slide's captured occurrences to physical rewrite targets."""
    sources = {deck.path: deck for deck, _ in scanned}
    offsets = defaultdict(set)
    matches = defaultdict(list)
    users = defaultdict(dict)
    for deck, calls in scanned:
        for call in calls:
            offsets[call.source].add(call.source_start)
            if call.id_slug == id_slug:
                matches[call.source].append(call)
                users[call.source][deck.path] = deck

    usages = []
    for path, calls in matches.items():
        source = sources.get(path) or deck_from_text(path, calls[0].source_text)
        physical = sorted(deck_language.source_calls(source, calls), key=lambda c: c.call_start)
        positions = {offset: i for i, offset in enumerate(sorted(offsets[path]), 1)}
        decks = list(users[path].values())
        shared = path not in sources or len(decks) > 1
        usages.append(DeckUsage(source, physical, [positions[c.call_start] for c in physical], len(positions),
                                path.stem if shared else None, decks))
    return usages


def revision_outcomes(proposal: slide_versioning.Proposal, current: Path, *,
                      pin: str | None = None) -> list[tuple[Path, str]]:
    """One outcome per captured call to `current`, in deck order, including repeated includes."""
    slug = current.name.removesuffix(slide_language.CURRENT_SUFFIX)
    rewritten = {}
    outcomes = []
    for deck, original in proposal.occurrences:
        if original.id_slug != slug or (pin is not None and original.version != pin):
            continue
        call = original
        source = call.source
        if source in proposal.edits:
            if source not in rewritten:
                before, after = proposal.edits[source]
                old_calls = deck_editor.calls_in_text(deck_language.masked(before))
                new_calls = deck_editor.calls_in_text(deck_language.masked(after))
                # Revision edits preserve call order, but changing one call can shift later offsets.
                rewritten[source] = {old.call_start: new for old, new in zip(old_calls, new_calls)}
            call = rewritten[source][original.source_start]
        if call.id_slug != slug:
            outcome = f"switches to new slide {call.id_slug}"
        elif call.version is not None:
            path = current.with_name(slide_language.frozen_name(slug, call.version))
            before, after = proposal.edits.get(path, (None, None))
            version = slide_versioning.version_label(call.version)
            outcome = (f"keeps {version}: content replaced" if before != after
                       else f"keeps {version} (unchanged)")
        elif proposal.created is not None:
            version = slide_versioning.version_text(proposal.edits[current][1])
            outcome = f"keeps v{version} (unchanged)"
        else:
            outcome = "follows the edited current slide"
        outcomes.append((deck, outcome))
    return outcomes


def usages_in(files, id_slug: str) -> list[DeckUsage]:
    usages = []
    for deck, calls, block, users in files:
        places = [(c, i) for i, c in enumerate(calls, 1) if c.id_slug == id_slug]
        if places:
            usages.append(DeckUsage(deck, [c for c, _ in places], [i for _, i in places], len(calls), block, users))
    return usages


def find_translations(ctx: ProjectContext, id_slug: str, text: str, decks: Optional[list[Deck]] = None, *,
                      files=None, codes=None) -> list[Translation]:
    """The slide's translation partners, named by its own header comment
    ("%% Translation of:" / "%% <LANG> translation:"), with the decks that use
    each. A partner whose file is gone is left out."""
    partners = []
    m = slide_language.TRANSLATION_OF_RE.search(text)
    if m:
        partners.append(slide_language.bare_id(m.group(1)))
    partners += [slide_language.bare_id(x.group(2))
                 for x in slide_language.LANG_TRANSLATION_RE.finditer(text)]
    out = []
    codes = codes or languages.project_languages(ctx).codes
    for bare in dict.fromkeys(partners):
        path = slide_language.current_path_for_bare_id(ctx, bare)
        if path is None:
            continue
        partner = path.name.removesuffix(slide_language.CURRENT_SUFFIX)
        if partner == id_slug:
            continue
        usages = find_usage(ctx, partner, decks) if files is None else usages_in(files, partner)
        used = list(dict.fromkeys(d.name for u in usages
                                  for d in (u.decks if u.block else [u.deck])))
        out.append(Translation(partner, slide_language.own_language(partner, codes), path, used))
    return out


def needs_dialog(usages: list[DeckUsage], translations: list[Translation]) -> bool:
    """More than one deck, a pinned call anywhere, or a translation."""
    decks = {d.path for u in usages for d in (u.decks if u.block else [u.deck])}
    return len(decks) > 1 or any(u.pinned_versions for u in usages) or bool(translations)


def set_pin(deck_path: Path, expected_text: str, calls: list[deck_editor.SlideCall],
            version: Optional[str]) -> str:
    """Make `calls` of one slide use the frozen `version` ("1-0-0"), or follow the
    current version again (None). \\slide / \\omitslide become \\slideversion /
    \\omitslideversion and back; a call that is pinned already moves to another
    version. A call of a kind with no pinned form is left alone. As one edit,
    through the deck editor's stale-checked rewrite; returns the new deck text."""
    deck = deck_from_text(deck_path, expected_text)
    physical = deck_language.source_calls(deck, calls)
    return deck_editor.apply(deck_path, expected_text, lambda raw: deck_editor.pinned_text(raw, physical, version))


def choice_edits(usages, choices: dict[Path, str], frozen_version: str | None) -> Edits:
    edits = {}
    for usage in usages:
        choice = choices.get(usage.deck.path)
        if choice == "current":
            version, wanted = None, PINNED
        elif choice == "keep" and frozen_version:
            version, wanted = frozen_version, PINNABLE
        else:
            continue
        calls = [c for c in usage.calls if c.macro in wanted]
        if calls:
            raw = usage.deck.text
            edits[usage.deck.path] = (raw, deck_editor.pinned_text(raw, calls, version))
    return edits
