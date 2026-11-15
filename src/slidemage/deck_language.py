# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve a deck's logical slide slots to their language partners.

Deck files remain unchanged. The original call owns placement, visibility
and reveal steps; a translation has its own version history, so switching
languages uses its current file. Explicit calls of other members of a
translation group in old decks are folded into one slot, even when they
occur in another section: the call of the group's original owns it, else the
earliest call into the group.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

from . import alt_blocks, deck_editor, languages, slide_language
from .deck_editor import SlideCall
from .deck_scan import Chapter, Deck
from .project import ProjectContext, find_upward
from .tex_source import INPUT_RE, blanked_verbatim, masked_same_length


# A partner has no version of its own to pin: the call that pins one becomes the plain call.
PARTNER_MACROS = {"slideversion": "slide", "omitslideversion": "omitslide"}
# The PDF language tags \decklanguage in SlideMage_base.tex picks itself; any other language is its own code.
_TEX_PDF_TAGS = {"en": "en-US", "de": "de-DE"}


def resolve_call(call: SlideCall, language: str, links: slide_language.TranslationLinks) -> SlideCall:
    language = language.upper()
    if links.own(call.id_slug) in (None, slide_language.MULT, language):
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


def slots(ctx: ProjectContext, calls: list[SlideCall], language: str, *,
          links: slide_language.TranslationLinks | None = None) -> list[SlideSlot]:
    """Preserve all original occurrences; omit separately listed translations.

    A translation called on its own is a slot too. Repeated originals and
    different slidestep calls retain their order and their individual rules.
    `links` is a scan of the slides folder to share between decks.
    """
    return _slots(calls, language, links or slide_language.links_for(ctx))


def _slots(calls: list[SlideCall], language: str, links: slide_language.TranslationLinks) -> list[SlideSlot]:
    in_group: dict[str, list[str]] = {}       # a group's original -> the ids of the slides the deck calls from it
    for call in calls:
        original = links.group(call.id_slug).original
        if original is not None and call.id not in in_group.setdefault(slide_language.bare_id(original), []):
            in_group[slide_language.bare_id(original)].append(call.id)
    owners: dict[str, str] = {}
    for original, called in in_group.items():
        owner = original if original in called else called[0]
        owners.update({slide_id: owner for slide_id in called if slide_id != owner})
    return [SlideSlot(c, resolve_call(c, language, links),
                     tuple(p for p in calls if owners.get(p.id) == c.id),
                     tuple(slide_language.bare_id(member) for member in links.group(c.id_slug).members.values()
                           if slide_language.bare_id(member) != c.id))
            for c in calls if c.id not in owners]


def masked(text: str) -> str:
    """Blank verbatim, inactive blocks, comments and notes, preserving offsets."""
    return alt_blocks.extract_note_calls(masked_same_length(blanked_verbatim(text)), mask=True)[0]


def calls_in(text: str, chapters: list[Chapter], *, comments: bool = False) -> list[SlideCall]:
    """Physical calls, preserving offsets and chapters; `comments` includes commented calls too."""
    shim = SimpleNamespace(text=text if comments else masked_same_length(text), chapters=chapters)
    return deck_editor.parse_slide_calls(shim)  # type: ignore[arg-type]


@dataclass
class ExpandedCall(SlideCall):
    source: Path
    block: str | None
    index: int | None
    source_line: int
    expanded: SlideCall  # offsets in the expanded text, for compile-only replacements

    @property
    def identity(self) -> tuple[int, int | None]:
        return self.call_start, self.index


@dataclass
class _SourceSpan:
    start: int
    end: int
    source: Path
    source_start: int
    source_line: int
    placement: tuple[int, int] | None


def _resolve_calls(deck: Deck, *, strict_includes: bool = False) -> tuple[Deck, list[Path], list[ExpandedCall]]:
    """Executable calls, with placement in the deck and provenance in the physical file.

    An included call owns the include's span in the deck; its index distinguishes
    calls within that occurrence. `expanded` retains offsets for compile copies.
    """
    spans: list[_SourceSpan] = []
    expanded, dependencies = expand_fragments(deck, strict_includes=strict_includes, _spans=spans)
    calls = deck_editor.parse_slide_calls(replace(expanded, text=masked(expanded.text)))
    result = []
    span_index = 0
    indices: dict[int, int] = {}
    for call in calls:
        while spans[span_index].end <= call.call_start:
            span_index += 1
        span = spans[span_index]
        offset = span.source_start + call.call_start - span.start
        start, end = span.placement or (offset, offset + call.call_end - call.call_start)
        line_start, line_end = deck_editor.line_span(deck.text, start, end)
        index = None
        if span.placement is not None:
            index = indices.get(start, 0)
            indices[start] = index + 1
        result.append(ExpandedCall(
            **{**vars(call), 'call_start': start, 'call_end': end,
               'line_start': line_start, 'line_end': line_end,
               'chapter': deck_editor._find_chapter(deck.chapters, start)},
            source=span.source,
            block=span.source.stem if index is not None and span.source.parent.name == "blocks" else None,
            index=index,
            source_line=span.source_line + expanded.text.count("\n", span.start, call.call_start),
            expanded=call))
    return expanded, dependencies, result


def expanded_calls(ctx: ProjectContext, deck: Deck) -> list[ExpandedCall]:
    """The deck's executable calls, including every occurrence of a linked block."""
    return _resolve_calls(deck)[2]


def active_calls(deck: Deck) -> list[ExpandedCall]:
    """Executable expanded calls, retaining physical placement and chapter objects."""
    return _resolve_calls(deck)[2]


def deck_slots(ctx: ProjectContext, deck: Deck, language: str, *,
               links: slide_language.TranslationLinks | None = None) -> list[SlideSlot]:
    return slots(ctx, expanded_calls(ctx, deck), language, links=links)


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
    expanded, _, calls = _resolve_calls(deck)
    active = slots(ctx, calls, language)
    replacements = {s.original.identity: call_text(s.call) for s in active if s.call != s.original}
    kept = {s.original.identity for s in active}
    text = expanded.text
    for call in reversed(calls):
        start, end = call.expanded.call_start, call.expanded.call_end
        replacement = replacements.get(call.identity, text[start:end] if call.identity in kept else "")
        text = text[:start] + replacement + text[end:]
    return text


def expand_fragments(deck: Deck, *, strict_includes: bool = False,
                     _spans: list[_SourceSpan] | None = None) -> tuple[Deck, list[Path]]:
    """Expand local body fragments without rewriting their files.

    Only fragments containing slide calls are expanded. Their original files
    are returned as compile-record dependencies, because TeX reads the inline
    copy instead of opening them itself. `strict_includes` raises for missing
    literal includes and cycles instead of leaving them for TeX.
    """
    from .deck_scan import parse_chapters

    root = find_upward(deck.path.parent) or deck.path.parent.parent
    dependencies: list[Path] = []

    def expand(text: str, source: Path, seen: frozenset[Path],
               placement: tuple[int, int] | None = None) -> tuple[str, list[_SourceSpan]]:
        directory = source.parent
        edits = []
        begin = (deck.preamble_end if deck.preamble_end is not None else len(text)) if source == deck.path else 0
        for match in INPUT_RE.finditer(masked(text), begin):
            name = match.group(1).strip()
            if not name or "\\" in name or "#" in name:
                continue  # Macro-valued paths require TeX expansion.
            block = match.group().startswith(r"\slideblock")
            if block:
                name = f"blocks/{name}"
            name = name if name.endswith(".tex") else name + ".tex"
            candidates = ((root / name,) if block else
                          (deck.path.parent / name, root / name, directory / name))
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
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            with path.open(encoding="utf-8", errors="replace", newline="") as file:
                fragment = file.read()
            expanded, spans = expand(fragment, path, seen | {path.resolve()},
                                     placement or (match.start(), match.end()))
            if not deck_editor.SLIDE_CALL_RE.search(masked(expanded)):
                continue
            dependencies.append(path)
            # A newline terminates a fragment's trailing comment before the rest of the deck.
            edits.append((match.start(), match.end(), expanded + "\n", spans))
        parts, origins = [], []
        pos = size = 0
        for start, end, replacement, spans in edits:
            parts.append(text[pos:start])
            origins.append(_SourceSpan(size, size + start - pos, source, pos,
                                       text.count("\n", 0, pos) + 1, placement))
            size += start - pos
            origins.extend(replace(span, start=span.start + size, end=span.end + size) for span in spans)
            parts.append(replacement)
            size += len(replacement)
            pos = end
        parts.append(text[pos:])
        origins.append(_SourceSpan(size, size + len(text) - pos, source, pos,
                                   text.count("\n", 0, pos) + 1, placement))
        return "".join(parts), origins

    expanded, spans = expand(deck.text, deck.path, frozenset({deck.path.resolve()}))
    if _spans is not None:
        _spans.extend(spans)
    return replace(deck, text=expanded, chapters=parse_chapters(expanded)), sorted(set(dependencies))


def compile_deck(ctx: ProjectContext, deck: Deck, language: str) -> tuple[Deck, list[Path]]:
    """Resolve calls, inlining fragments only when language resolution changes them."""
    from .deck_scan import parse_chapters

    if deck.preamble_end is None:
        return deck, []
    candidate, dependencies = expand_fragments(deck)
    expanded = candidate.text
    resolved = resolved_text(ctx, candidate, language)
    links = slide_language.links_for(ctx)
    header_inputs = {links.paths[slide_id] for slot in deck_slots(ctx, candidate, language)
                     if slot.related_ids for slide_id in (slot.original.id, *slot.related_ids)
                     if slide_id in links.paths}
    if resolved == expanded:
        return deck, sorted(header_inputs)
    return replace(deck, text=resolved, chapters=parse_chapters(resolved)), sorted(set(dependencies) | header_inputs)


def language_for_job(job) -> str:
    from .deck_settings import read_settings

    return (getattr(job, "language", None) or read_settings(job.deck.text).language).upper()


def language_lines(ctx: ProjectContext, language: str | None, *, deck: str | None = None) -> str:
    """The lines put after a deck's preamble so its own setting cannot undo the UI choice, newline-terminated.

    First `\\SMProjectLanguages[main]{EN,DE,FR}`, which SlideMage_base.tex reads the project's languages from. Then,
    for `language` (none for None), `\\decklanguage[xx]` and, when the table's PDF tag is not the one TeX picks for
    the language itself, `\\SMPdfLang{fr-FR}`. `deck` is the deck's own language when `language` is None: its PDF
    tag is written too, so that the PDF /Lang is the table's also without an override."""
    own = languages.project_languages(ctx)
    lines = f"\\SMProjectLanguages[{own.main}]{{{','.join(own.codes)}}}\n"
    if language is not None:
        lines += f"\\decklanguage[{language.lower()}]\n"
    if pdf := (language or deck):
        code = pdf.lower()
        if languages.pdf_tag(code) != _TEX_PDF_TAGS.get(code, code):
            lines += f"\\SMPdfLang{{{languages.pdf_tag(code)}}}\n"
    return lines
