"""Resolve a deck's logical slide slots to their language partners.

Deck files remain unchanged. The original call owns placement, visibility
and reveal steps; a partner has its own version history, so switching
languages uses its current file. Explicit partner calls in old decks are
folded into the original slot, even when they occur in another section.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re

from . import alt_blocks, deck_editor, slide_language
from .deck_editor import SlideCall
from .deck_scan import Deck


def _header(id_slug: str, path: Path | None = None) -> str:
    try:
        return (path or slide_language.SLIDES_DIR / slide_language.current_name(id_slug)).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""


class _Links:
    """One scan per resolution, including links recorded on only one side."""

    def __init__(self, slides_dir: Path | None = None) -> None:
        self.slides_dir = slides_dir or slide_language.SLIDES_DIR
        self.paths = {slide_language.bare_id(p.name): p
                      for p in self.slides_dir.glob("*-current.tex")}
        self.headers: dict[str, str] = {}
        self.reverse: dict[tuple[str, str], set[str]] | None = None

    def partner(self, ref: str) -> str | None:
        path = self.paths.get(slide_language.bare_id(ref))
        partner = path.name[:-len(slide_language.CURRENT_SUFFIX)] if path else None
        return partner if partner and slide_language.own_language(partner) in ("EN", "DE") else None

    def header(self, id_slug: str) -> str:
        if id_slug not in self.headers:
            self.headers[id_slug] = _header(id_slug, self.slides_dir / slide_language.current_name(id_slug))
        return self.headers[id_slug]

    def find(self, id_slug: str, language: str, path: Path | None = None) -> str | None:
        language = language.upper()
        if slide_language.own_language(id_slug) in (None, "mult", language):
            return None
        text = _header(id_slug, path) if path else self.header(id_slug)
        refs = [m.group(1) for m in slide_language.TRANSLATION_OF_RE.finditer(text)]
        refs += [m.group(2) for m in slide_language.LANG_TRANSLATION_RE.finditer(text)
                 if m.group(1) == language]
        for ref in refs:
            partner = self.partner(ref)
            if partner and partner != id_slug and slide_language.own_language(partner) == language:
                return partner
        if self.reverse is None:
            self.reverse = {}
            for file in self.paths.values():
                slug = file.name[:-len(slide_language.CURRENT_SUFFIX)]
                own = slide_language.own_language(slug)
                if own not in ("EN", "DE"):
                    continue
                header = self.header(slug)
                refs = [m.group(1) for m in slide_language.TRANSLATION_OF_RE.finditer(header)]
                refs += [m.group(2) for m in slide_language.LANG_TRANSLATION_RE.finditer(header)]
                for ref in refs:
                    partner = self.partner(ref)
                    if partner and slide_language.own_language(partner) != own:
                        self.reverse.setdefault((slide_language.bare_id(partner), own), set()).add(slug)
        candidates = self.reverse.get((slide_language.bare_id(id_slug), language), set())
        # Conflicting reverse links do not pick an arbitrary translation.
        return next(iter(candidates)) if len(candidates) == 1 else None


def partner_for(id_slug: str, language: str, path: Path | None = None,
                *, slides_dir: Path | None = None) -> str | None:
    """An existing, explicitly linked partner in `language`; never guess from a slug."""
    return _Links(slides_dir).find(id_slug, language, path)


def resolve_call(call: SlideCall, language: str, *, _links: _Links | None = None) -> SlideCall:
    language = language.upper()
    if slide_language.own_language(call.id_slug) in (None, "mult", language):
        return call
    # Translation links belong to the slide, independently of a frozen
    # version's old header. Never transfer a version number between slides.
    partner = (_links or _Links()).find(call.id_slug, language)
    if partner is None:
        return call
    slide_id, slug = partner.split("-", 1)
    macro = {"slideversion": "slide", "omitslideversion": "omitslide"}.get(call.macro, call.macro)
    return replace(call, id=slide_id, slug=slug, macro=macro, version=None)


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


def slots(calls: list[SlideCall], language: str, *, slides_dir: Path | None = None) -> list[SlideSlot]:
    """Preserve all original occurrences; omit separately listed translations.

    A translation called on its own is a slot too. Repeated originals and
    different slidestep calls retain their order and their individual rules.
    """
    by_id = {c.id: c for c in calls}
    links = _Links(slides_dir)
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
    return [SlideSlot(c, resolve_call(c, language, _links=links),
                     tuple(p for p in calls if owners.get(p.id) == c.id),
                     tuple(slide_language.bare_id(partner) for lang in ("EN", "DE")
                           if (partner := links.find(c.id_slug, lang))))
            for c in calls if c.id not in owners]


def _masked(text: str) -> str:
    from . import latex_lint
    for pattern in (latex_lint._VERBATIM_ENV_RE, latex_lint._IFFALSE_RE, latex_lint._VERB_RE):
        text = pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), text)
    return alt_blocks.extract_note_calls(latex_lint._masked_same_length(text), mask=True)[0]


def active_calls(deck: Deck) -> list[SlideCall]:
    """Executable calls, with original character offsets and chapter objects."""
    return deck_editor.parse_slide_calls(replace(deck, text=_masked(deck.text)))


def deck_slots(deck: Deck, language: str) -> list[SlideSlot]:
    calls = active_calls(deck)
    return slots(calls, language)


def call_text(call: SlideCall) -> str:
    if call.version is not None:
        return f"\\{call.macro}{{{call.id_slug}}}{{{call.version}}}"
    if call.macro == "slidestep":
        return f"\\slidestep{{{call.id_slug}}}[{','.join(call.conditions or [])}]{{{call.steps}}}"
    if call.macro == "conditionalslide":
        return f"\\conditionalslide[{','.join(call.conditions or [])}]{{{call.id_slug}}}"
    return f"\\{call.macro}{{{call.id_slug}}}"


def resolved_text(deck: Deck, language: str) -> str:
    """A compile-only copy with resolved calls, retaining all surrounding TeX."""
    active = deck_slots(deck, language)
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
    from . import latex_lint
    from .deck_scan import _parse_chapters

    dependencies: list[Path] = []

    def expand(text: str, directory: Path, seen: frozenset[Path]) -> str:
        edits = []
        for match in latex_lint._INPUT_RE.finditer(_masked(text)):
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
            if not deck_editor.SLIDE_CALL_RE.search(_masked(expanded)):
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
    return replace(deck, text=expanded, chapters=_parse_chapters(expanded)), sorted(set(dependencies))


def compile_deck(deck: Deck, language: str) -> tuple[Deck, list[Path]]:
    """Resolve calls, inlining fragments only when language resolution changes them."""
    from .deck_scan import _parse_chapters

    if deck.preamble_end is None:
        return deck, []
    candidate, dependencies = expand_fragments(deck)
    expanded = candidate.text
    resolved = resolved_text(candidate, language)
    links = _Links()
    header_inputs = {links.paths[slide_id] for slot in deck_slots(candidate, language)
                     if slot.related_ids for slide_id in (slot.original.id, *slot.related_ids)
                     if slide_id in links.paths}
    if resolved == expanded:
        return deck, sorted(header_inputs)
    return replace(deck, text=resolved, chapters=_parse_chapters(resolved)), sorted(set(dependencies) | header_inputs)


def language_for_job(job) -> str:
    from .deck_settings import read_settings

    return (getattr(job, "language", None) or read_settings(job.deck.text).language).upper()


def language_line(language: str) -> str:
    # Run after the deck preamble so its own setting cannot undo the UI choice.
    return f"\\decklanguage[{language.lower()}]\n"
