"""Multi-language parsing primitives shared by the SlideMage GUI's
language badges (deck_outline.py, the Add slide sheet,
the Details view) and slide_rename.py's translation-link repair
pass. See LANGUAGE_NOTES.md for the whole design.

Language lives in a slide's own id-slug, as its *second* hyphen segment
(<id>-<LANG>-<slug>), exactly mirroring what
Slidemaster_preamble_base.tex's \\setSlideLanguageFromSlug parses at
compile time -- this module is the Python-side twin of that macro, kept
deliberately in sync with it rather than reading anything back out of a
compiled PDF. A slide that predates this feature has no such segment
(own_language() returns None for it), exactly like an untracked
\\setSlideVersion{} today has no footer "v..." segment -- no migration is
needed for the other ~665 files.

Translation cross-references live in a plain header-comment convention,
alongside the existing "%% Included in decks: ..." block
(deck_headers.py):

    %% Translation of: <source id-slug>        -- this file IS a translation
    %% <LANG> translation: <target id-slug>     -- this file HAS a translation

Written by slide_add.create_copy() for a translation (both sides at
once) and kept honest afterward by slide_rename.regenerate_translation_links().
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import slide_source
from .deck_scan import PROJECT_ROOT

SLIDES_DIR = PROJECT_ROOT / "slides"

# Keep in sync with Slidemaster_preamble_base.tex's own
# \setSlideLanguageFromSlug@aux fixed keyword set.
LANGUAGES = ("EN", "DE", "mult")
# Excludes "mult", which is not a translation target.
TRANSLATION_LANGUAGES = ("EN", "DE")

TRANSLATION_OF_RE = re.compile(r"^%% Translation of: (\S+)", re.MULTILINE)
LANG_TRANSLATION_RE = re.compile(r"^%% (EN|DE|mult) translation: (\S+)", re.MULTILINE)

CURRENT_SUFFIX = "-current.tex"
FROZEN_RE = re.compile(r"-v([0-9]+-[0-9]+-[0-9]+)\.tex$")


def bare_id(id_slug_or_ref: str) -> str:
    """Everything before the first hyphen -- a slide's permanent,
    language-independent ID. Matches slide_ids.py's own
    ID_FROM_FILENAME_RE / Slidemaster_preamble_base.tex's \\setSlideID@aux."""
    return id_slug_or_ref.split("-", 1)[0]


def own_language(id_slug: str) -> Optional[str]:
    """"EN"/"DE"/"mult" parsed from id_slug's own second hyphen segment,
    or None for a legacy slide with no such segment."""
    parts = id_slug.split("-", 2)
    if len(parts) >= 2 and parts[1] in LANGUAGES:
        return parts[1]
    return None


def current_name(id_slug: str) -> str:
    """The file name of a slide's current file ("1ab-EN-Demo-current.tex")."""
    return f"{id_slug}{CURRENT_SUFFIX}"


def frozen_name(id_slug: str, version: str) -> str:
    """The frozen file name for a version in its file form ("1-0-0")."""
    return f"{id_slug}-v{version}.tex"


def is_current_file(path: Path) -> bool:
    """Whether `path` is a slide's current file (not one of its frozen versions)."""
    return path.name.endswith(CURRENT_SUFFIX)


def current_path_for_bare_id(bare_id_: str) -> Optional[Path]:
    """The slides/<bare_id_>-...-current.tex path on disk right now, or
    None if that ID has no current file any more (renamed again, or
    deleted) -- by this project's own convention there is at most one
    -current.tex per bare ID."""
    matches = list(SLIDES_DIR.glob(f"{bare_id_}-*{CURRENT_SUFFIX}"))
    return matches[0] if matches else None


def current_id_slug_for_bare_id(bare_id_: str) -> Optional[str]:
    path = current_path_for_bare_id(bare_id_)
    if path is None:
        return None
    return path.name[: -len(CURRENT_SUFFIX)]


def _header(id_slug: str, path: Path | None = None) -> str:
    try:
        return (path or SLIDES_DIR / current_name(id_slug)).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""


class TranslationLinks:
    """One scan per resolution, including links recorded on only one side."""

    def __init__(self, slides_dir: Path | None = None) -> None:
        self.slides_dir = slides_dir or SLIDES_DIR
        self.paths = {bare_id(p.name): p
                      for p in self.slides_dir.glob("*-current.tex")}
        self.headers: dict[str, str] = {}
        self.reverse: dict[tuple[str, str], set[str]] | None = None

    def partner(self, ref: str) -> str | None:
        path = self.paths.get(bare_id(ref))
        partner = path.name[:-len(CURRENT_SUFFIX)] if path else None
        return partner if partner and own_language(partner) in TRANSLATION_LANGUAGES else None

    def header(self, id_slug: str) -> str:
        if id_slug not in self.headers:
            self.headers[id_slug] = _header(id_slug, self.slides_dir / current_name(id_slug))
        return self.headers[id_slug]

    def find(self, id_slug: str, language: str, path: Path | None = None) -> str | None:
        language = language.upper()
        if own_language(id_slug) in (None, "mult", language):
            return None
        text = _header(id_slug, path) if path else self.header(id_slug)
        refs = [m.group(1) for m in TRANSLATION_OF_RE.finditer(text)]
        refs += [m.group(2) for m in LANG_TRANSLATION_RE.finditer(text)
                 if m.group(1) == language]
        for ref in refs:
            partner = self.partner(ref)
            if partner and partner != id_slug and own_language(partner) == language:
                return partner
        if self.reverse is None:
            self.reverse = {}
            for file in self.paths.values():
                slug = file.name[:-len(CURRENT_SUFFIX)]
                own = own_language(slug)
                if own not in TRANSLATION_LANGUAGES:
                    continue
                header = self.header(slug)
                refs = [m.group(1) for m in TRANSLATION_OF_RE.finditer(header)]
                refs += [m.group(2) for m in LANG_TRANSLATION_RE.finditer(header)]
                for ref in refs:
                    partner = self.partner(ref)
                    if partner and own_language(partner) != own:
                        self.reverse.setdefault((bare_id(partner), own), set()).add(slug)
        candidates = self.reverse.get((bare_id(id_slug), language), set())
        # Conflicting reverse links do not pick an arbitrary translation.
        return next(iter(candidates)) if len(candidates) == 1 else None


def cross_referenced_language(id_slug: str, path: Optional[Path] = None, *,
                              links: Optional[TranslationLinks] = None) -> Optional[str]:
    """The language of this slide's resolved translation partner, or None.

    Links belong to the current slide, even when `path` is a frozen version.
    Pass a shared index when building badges for a whole list."""
    links = links or TranslationLinks()
    return next((language for language in TRANSLATION_LANGUAGES
                 if links.find(id_slug, language)), None)


@dataclass
class TranslationLink:
    """A slide and its resolved translation partner."""

    partner: str                # the partner's id-slug
    language: Optional[str]     # the partner's language
    path: Path                  # the partner's current file
    is_translation: bool        # this slide is the translation of `partner` (else `partner` is of this)
    outdated: bool              # the original was saved in SlideMage after the translation was last written


def translation_link(id_slug: str, path: Optional[Path] = None, *,
                     links: Optional[TranslationLinks] = None) -> Optional[TranslationLink]:
    """The slide's resolved translation partner, including links recorded on only one side.
    Links belong to the current slide, even when `path` is a frozen version.

    `outdated` measures this and nothing more: the original has been saved through SlideMage
    (slide_source.last_saved(): its newest backup) later than the translation was last written
    (the later of its own newest backup and its file's mtime). It is not a comparison of
    content, and an edit made outside SlideMage is not noticed."""
    links = links or TranslationLinks()
    path = path or links.slides_dir / current_name(id_slug)
    partner = next((partner for language in TRANSLATION_LANGUAGES
                    if (partner := links.find(id_slug, language))), None)
    if partner is None:
        return None
    partner_path = links.paths[bare_id(partner)]
    text = links.header(id_slug)
    is_translation = any(links.partner(m.group(1)) == partner
                         for m in TRANSLATION_OF_RE.finditer(text))
    if not is_translation and not any(m.group(1) == own_language(partner)
                                     and links.partner(m.group(2)) == partner
                                     for m in LANG_TRANSLATION_RE.finditer(text)):
        # A reverse link carries the opposite role of the partner's comment.
        is_translation = not any(bare_id(m.group(1)) == bare_id(id_slug)
                                 for m in TRANSLATION_OF_RE.finditer(links.header(partner)))
    original, translation = (partner_path, path) if is_translation else (path, partner_path)
    saved = slide_source.last_saved(original)
    written = max(filter(None, (slide_source.last_saved(translation),
                                datetime.fromtimestamp(translation.stat().st_mtime))))
    return TranslationLink(partner, own_language(partner), partner_path, is_translation,
                           saved is not None and saved > written)


@dataclass
class LanguageBadge:
    """What a GUI list row should show for one slide -- built once per
    row so every caller (deck_outline.py, the Add slide sheet,
    the Details view) renders the same underlying facts, even
    though each one displays them slightly differently (rich-text HTML,
    plain text + bold font, a QLabel)."""

    own: Optional[str]
    cross_referenced: Optional[str]

    @property
    def both(self) -> bool:
        """True when this slide's own language *and* a cross-referenced
        translation into a *different* language both exist -- the case
        that should be visually highlighted."""
        return (
            self.own is not None
            and self.cross_referenced is not None
            and self.cross_referenced != self.own
        )

    def text(self) -> str:
        """"" for an untagged slide, "[EN]" for a tagged one, "[EN + DE]"
        when both() -- callers append/style this however suits their
        widget."""
        if self.own is None:
            return ""
        if self.both:
            return f"[{self.own} + {self.cross_referenced}]"
        return f"[{self.own}]"


def badge_for(id_slug: str, path: Optional[Path] = None, *,
              links: Optional[TranslationLinks] = None) -> LanguageBadge:
    own = own_language(id_slug)
    cross = cross_referenced_language(id_slug, path, links=links) if own is not None else None
    return LanguageBadge(own=own, cross_referenced=cross)
