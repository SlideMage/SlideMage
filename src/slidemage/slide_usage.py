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

- "current" (the default): the deck uses the new version. A pinned call
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import deck_editor, languages, slide_language, slide_versioning
from .deck_scan import Deck, deck_from_text, read_deck, scan_decks
from .project import ProjectContext, call_files

PINNED = {"slideversion": "slide", "omitslideversion": "omitslide"}
PINNABLE = {"slide": "slideversion", "omitslide": "omitslideversion"}


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


def _skipped(deck: Deck) -> bool:
    return deck.name.startswith(("#", "zzz_"))


_index_cache = None


def call_file_index(ctx: ProjectContext, decks: list[Deck] | None = None):
    """Physical call files and their consuming decks, cached against dependency revisions."""
    from . import deck_language

    global _index_cache
    previous = _index_cache if _index_cache and _index_cache[0] == ctx.root else None
    paths = {p for folder in (*ctx.deck_folders, ctx.blocks_dir) for p in folder.glob("*.tex")}
    if previous:
        paths.update(previous[2])

    def revision(path):
        try:
            stat = path.stat()
            return path, stat.st_mtime_ns, stat.st_size
        except OSError:
            return path, None, None

    def signature():
        return (tuple(revision(p) for p in sorted(paths)),
                None if decks is None else tuple((d.path, d.text) for d in decks))

    key = signature()
    if previous and previous[1] == key:
        return previous[3]
    files = {d.path: d for d in (scan_decks(ctx) if decks is None else decks) if not _skipped(d)}
    users: dict[Path, list[Deck]] = {}
    for deck in list(files.values()):
        resolution = deck_language.resolve(deck)
        paths.update(resolution.dependencies)
        for call in resolution.calls:
            if call.source != deck.path:
                if call.source not in files:
                    files[call.source] = deck_from_text(call.source, call.source_text)
                consumers = users.setdefault(call.source, [])
                if deck not in consumers:
                    consumers.append(deck)
    for path in call_files(ctx):
        if path.parent == ctx.blocks_dir and path not in files:
            files[path] = read_deck(path)
    result = files, users
    _index_cache = ctx.root, signature(), paths, result
    return result


def find_usage(ctx: ProjectContext, id_slug: str, decks: Optional[list[Deck]] = None, *, language: Optional[str] = None) -> list[DeckUsage]:
    """Files holding calls of this slide, with the decks reached through each block.

    `decks` reuses an existing scan; `language` resolves the calls as shown in the UI.
    Calls used for edits (without `language`) retain their physical file offsets.
    """
    from . import deck_language

    files, users = call_file_index(ctx, decks)
    usages = []
    links = slide_language.links_for(ctx) if language is not None else None
    for path, deck in files.items():
        if language is not None:
            every = [slot.call for slot in deck_language.slots(
                ctx, deck_language.calls_in(deck_language.masked(deck.text), deck.chapters), language, links=links)]
        else:
            every = deck_language.calls_in(deck.text, deck.chapters, comments=True)
        places = [(c, i) for i, c in enumerate(every, start=1)
                  if c.id_slug == id_slug]
        if places:
            block = path.stem if path.parent == ctx.blocks_dir or path in users else None
            usages.append(DeckUsage(deck, [c for c, _ in places], [i for _, i in places], len(every),
                                    block, users.get(path, []) if block else []))
    return usages


def find_translations(ctx: ProjectContext, id_slug: str, text: str, decks: Optional[list[Deck]] = None) -> list[Translation]:
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
    codes = languages.project_languages(ctx).codes
    for bare in dict.fromkeys(partners):
        partner = slide_language.current_id_slug_for_bare_id(ctx, bare)
        path = slide_language.current_path_for_bare_id(ctx, bare)
        if partner is None or path is None or partner == id_slug:
            continue
        used = list(dict.fromkeys(d.name for u in find_usage(ctx, partner, decks)
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
    from . import deck_language

    if any((call.source or deck_path) != deck_path for call in calls):
        raise ValueError("Pin the call in its source file; a per-deck choice needs Unlink first.")
    deck = deck_from_text(deck_path, expected_text)
    calls = deck_language.source_calls(deck, calls)
    text = expected_text
    for call in sorted(calls, key=lambda c: c.call_start, reverse=True):
        if version is None:
            macro = PINNED.get(call.macro)
        else:
            macro = PINNABLE.get(call.macro) or (call.macro if call.macro in PINNED else None)
        if macro is not None:
            text = deck_editor.change_slide_call_variant(deck_path, text, call, macro, new_version=version)
    return text


def apply_choices(ctx: ProjectContext, id_slug: str, choices: dict[Path, str], frozen_version: Optional[str]) -> list[str]:
    """Rewrite the decks' calls as chosen ({file path: "current" | "keep"};
    frozen_version is the hyphenated version just frozen, "1-1-0" -- None if
    nothing was frozen, then "keep" can pin nothing). Re-reads every deck, so
    a deck edited since the dialog opened is handled on its current text.
    Returns one log line per deck that changed."""
    log = []
    for usage in find_usage(ctx, id_slug):
        choice = choices.get(usage.deck.path)
        if choice == "current":
            version, wanted = None, PINNED
        elif choice == "keep" and frozen_version:
            version, wanted = frozen_version, PINNABLE
        else:
            continue
        calls = [c for c in usage.calls if c.editable and c.macro in wanted]
        if calls:
            set_pin(usage.deck.path, usage.deck.text, calls, version)
            verb = "now uses the new version" if choice == "current" else f"stays on {slide_versioning.version_label(frozen_version)}"
            log.append(f"    {usage.deck.name}: {len(calls)} call(s) changed -- {verb}")
    return log
