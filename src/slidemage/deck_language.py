# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve a deck's logical slide slots to their language partners.

Deck files remain unchanged. The original call owns placement, visibility
and reveal steps; a partner has its own version history, so switching
languages uses its current file. Explicit partner calls in old decks are
folded into the original slot, even when they occur in another section.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from . import alt_blocks, deck_editor, slide_language
from .deck_editor import SlideCall
from .deck_scan import Chapter, Deck
from .project import ProjectContext
from .tex_source import INPUT_RE, blanked_verbatim, masked_same_length


# A partner has no version of its own to pin: the call that pins one becomes the plain call.
PARTNER_MACROS = {"slideversion": "slide", "omitslideversion": "omitslide"}


def resolve_call(call: SlideCall, language: str, links: slide_language.TranslationLinks) -> SlideCall:
    language = language.upper()
    if slide_language.own_language(call.id_slug) in (None, "mult", language):
        return call
    # Translation links belong to the slide, independently of a frozen
    # version's old header. Never transfer a version number between slides.
    partner = links.find(call.id_slug, language)
    if partner is None:
        return call
    slide_id, slug = partner.split("-", 1)
    return replace(call, id=slide_id, slug=slug, macro=PARTNER_MACROS.get(call.macro, call.macro), version=None)


@dataclass(frozen=True)
class SlideSlot:
    original: SlideCall
    call: SlideCall
    folded: tuple[SlideCall, ...] = ()
    related_ids: tuple[str, ...] = ()

    def matches(self, slide_id: str) -> bool:
        if slide_id in (self.original.id, self.call.id) or any(c.id == slide_id for c in self.folded):
            return True
        return slide_id in self.related_ids


def slots(ctx: ProjectContext, calls: list[SlideCall], language: str) -> list[SlideSlot]:
    """Preserve all original occurrences; omit separately listed translations.

    A translation called on its own is a slot too. Repeated originals and
    different slidestep calls retain their order and their individual rules.
    """
    return _slots(calls, language, slide_language.TranslationLinks(ctx.slides_dir))


def _slots(calls: list[SlideCall], language: str, links: slide_language.TranslationLinks) -> list[SlideSlot]:
    by_id = {c.id: c for c in calls}
    owners: dict[str, str] = {}
    for call in calls:
        text = links.header(call.id_slug)
        if match := slide_language.TRANSLATION_OF_RE.search(text):
            original = links.partner(match.group(1))
            if (original and slide_language.bare_id(original) in by_id and original != call.id_slug
                    and slide_language.own_language(original) != slide_language.own_language(call.id_slug)):
                owners[call.id] = slide_language.bare_id(original)
        for match in slide_language.LANG_TRANSLATION_RE.finditer(text):
            partner = links.partner(match.group(2))
            if (partner and slide_language.own_language(partner) == match.group(1)
                    and slide_language.own_language(partner) != slide_language.own_language(call.id_slug)
                    and slide_language.bare_id(partner) in by_id and partner != call.id_slug):
                owners.setdefault(slide_language.bare_id(partner), call.id)
    # Malformed reciprocal links must not remove both slides.
    owners = {child: owner for child, owner in owners.items() if owner not in owners}
    return [SlideSlot(c, resolve_call(c, language, links),
                     tuple(p for p in calls if owners.get(p.id) == c.id),
                     tuple(slide_language.bare_id(partner) for lang in slide_language.TRANSLATION_LANGUAGES
                           if (partner := links.find(c.id_slug, lang))))
            for c in calls if c.id not in owners]


def masked(text: str) -> str:
    """Blank verbatim, inactive blocks, comments and notes, preserving offsets."""
    return alt_blocks.extract_note_calls(masked_same_length(blanked_verbatim(text)), mask=True)[0]


def calls_in(text: str, chapters: list[Chapter]) -> list:
    """Slide calls with only comments masked, preserving offsets and chapters."""
    shim = SimpleNamespace(text=masked_same_length(text), chapters=chapters)
    return deck_editor.parse_slide_calls(shim)  # type: ignore[arg-type]


def active_calls(deck: Deck) -> list[SlideCall]:
    """Executable calls, with original character offsets and chapter objects."""
    return deck_editor.parse_slide_calls(replace(deck, text=masked(deck.text)))


def deck_slots(ctx: ProjectContext, deck: Deck, language: str) -> list[SlideSlot]:
    return slots(ctx, active_calls(deck), language)


def call_text(call: SlideCall) -> str:
    if call.version is not None:
        return f"\\{call.macro}{{{call.id_slug}}}{{{call.version}}}"
    if call.macro == "slidestep":
        return f"\\slidestep{{{call.id_slug}}}[{','.join(call.conditions or [])}]{{{call.steps}}}"
    if call.macro == "conditionalslide":
        return f"\\conditionalslide[{','.join(call.conditions or [])}]{{{call.id_slug}}}"
    return f"\\{call.macro}{{{call.id_slug}}}"


def resolved_text(ctx: ProjectContext, deck: Deck, language: str) -> str:
    """A compile-only copy with resolved calls, retaining all surrounding TeX."""
    active = deck_slots(ctx, deck, language)
    replacements = {s.original.call_start: (call_text(s.call) if s.call != s.original
                    else deck.text[s.original.call_start:s.original.call_end]) for s in active}
    text = deck.text
    for call in reversed(active_calls(deck)):
        text = text[:call.call_start] + replacements.get(call.call_start, "") + text[call.call_end:]
    return text


def expand_fragments(deck: Deck, *, strict_includes: bool = False) -> tuple[Deck, list[Path]]:
    """Expand local body fragments without rewriting their files.

    Only fragments containing slide calls are expanded. Their original files
    are returned as compile-record dependencies, because TeX reads the inline
    copy instead of opening them itself. `strict_includes` raises for missing
    literal includes and cycles instead of leaving them for TeX.
    """
    from .deck_scan import parse_chapters

    dependencies: list[Path] = []

    def expand(text: str, directory: Path, seen: frozenset[Path]) -> str:
        edits = []
        for match in INPUT_RE.finditer(masked(text)):
            name = match.group(1).strip()
            if not name or "\\" in name or "#" in name:
                continue  # Macro-valued paths require TeX expansion.
            name = name if name.endswith(".tex") else name + ".tex"
            candidates = (deck.path.parent / name, deck.path.parent.parent / name, directory / name)
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                if strict_includes:
                    raise FileNotFoundError(f"Literal deck include {name!r} from {directory} was not found.")
                continue
            if path.resolve() in seen:
                if strict_includes:
                    raise ValueError(f"Deck include cycle detected at {path}")
                continue
            # Themes, media and slide sources keep their normal input behavior.
            if not path.resolve().is_relative_to(deck.path.parent.parent.resolve()):
                continue
            with path.open(encoding="utf-8", errors="replace", newline="") as file:
                fragment = file.read()
            expanded = expand(fragment, path.parent, seen | {path.resolve()})
            if not deck_editor.SLIDE_CALL_RE.search(masked(expanded)):
                continue
            dependencies.append(path)
            # A newline terminates a fragment's trailing comment before the rest of the deck.
            edits.append((match.start(), match.end(), expanded + "\n"))
        for start, end, replacement in reversed(edits):
            text = text[:start] + replacement + text[end:]
        return text

    if deck.preamble_end is None:
        return deck, []
    expanded = deck.preamble_text + expand(deck.text[deck.preamble_end:], deck.path.parent,
                                         frozenset({deck.path.resolve()}))
    return replace(deck, text=expanded, chapters=parse_chapters(expanded)), sorted(set(dependencies))


def compile_deck(ctx: ProjectContext, deck: Deck, language: str) -> tuple[Deck, list[Path]]:
    """Resolve calls, inlining fragments only when language resolution changes them."""
    from .deck_scan import parse_chapters

    if deck.preamble_end is None:
        return deck, []
    candidate, dependencies = expand_fragments(deck)
    expanded = candidate.text
    resolved = resolved_text(ctx, candidate, language)
    links = slide_language.TranslationLinks(ctx.slides_dir)
    header_inputs = {links.paths[slide_id] for slot in deck_slots(ctx, candidate, language)
                     if slot.related_ids for slide_id in (slot.original.id, *slot.related_ids)
                     if slide_id in links.paths}
    if resolved == expanded:
        return deck, sorted(header_inputs)
    return replace(deck, text=resolved, chapters=parse_chapters(resolved)), sorted(set(dependencies) | header_inputs)


def language_for_job(job) -> str:
    from .deck_settings import read_settings

    return (getattr(job, "language", None) or read_settings(job.deck.text).language).upper()


def language_line(language: str) -> str:
    # Run after the deck preamble so its own setting cannot undo the UI choice.
    return f"\\decklanguage[{language.lower()}]\n"
