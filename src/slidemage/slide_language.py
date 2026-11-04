# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-language parsing primitives shared by the SlideMage GUI's
language badges (deck_outline.py, the Add slide sheet,
the Details view) and slide_rename.py's translation-link repair
pass.

Language lives in a slide's own id-slug, as its *second* hyphen segment
(<id>-<LANG>-<slug>), exactly mirroring what
SlideMage_base.tex's \\setSlideLanguageFromSlug parses at
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

A slide and its translations are a translation group, a star: one original (the slide
that is nobody's translation), each translation naming it, and the original naming each
translation. Only the project's languages count as a language (languages.py).

Written by slide_add.create_copy() for a translation (both sides at
once) and kept honest afterward by slide_rename.regenerate_translation_links().
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .project import ProjectContext


# A multilingual slide: the same in every language, so it is nobody's translation.
MULT = "mult"

TRANSLATION_OF_RE = re.compile(r"^%% Translation of: (\S+)", re.MULTILINE)
# Only the project's codes count as a language (TranslationLinks).
LANG_TRANSLATION_RE = re.compile(r"^%% ([A-Z]{2}|mult) translation: (\S+)", re.MULTILINE)

CURRENT_SUFFIX = "-current.tex"
FROZEN_RE = re.compile(r"-v([0-9]+-[0-9]+-[0-9]+)\.tex$")


def bare_id(id_slug_or_ref: str) -> str:
    """Everything before the first hyphen -- a slide's permanent,
    language-independent ID. Matches slide_ids.py's own
    ID_FROM_FILENAME_RE / SlideMage_base.tex's \\setSlideID@aux."""
    return id_slug_or_ref.split("-", 1)[0]


def own_language(id_slug: str, codes: tuple[str, ...]) -> Optional[str]:
    """One of `codes` (the project's languages, upper case: languages.Languages.codes) or "mult", parsed from
    id_slug's own second hyphen segment, or None for a slide with no such segment. Any other word there
    ("x7k-IT-Governance" in a project without Italian) is part of the slug."""
    parts = id_slug.split("-", 2)
    if len(parts) >= 2 and (parts[1] in codes or parts[1] == MULT):
        return parts[1]
    return None


def current_name(id_slug: str) -> str:
    """The file name of a slide's current file ("1ab-EN-Demo-current.tex")."""
    return f"{id_slug}{CURRENT_SUFFIX}"


def frozen_name(id_slug: str, version: str) -> str:
    """The frozen file name for a version in its file form ("1-0-0")."""
    return f"{id_slug}-v{version}.tex"


# Below current_name()/frozen_name(), not up with the other imports: deck_editor (by way of
# deck_settings) needs FROZEN_RE and those two names, and imports them through this same module's
# own `languages` import below -- languages -> deck_settings -> deck_editor -> back here, while
# this module is still mid-initialization. Nothing above this line touches `languages` or
# `slide_source` at module-execution time (both are only used inside function bodies further
# down), so the import is safe to make here instead, after the names the cycle needs exist.
from . import languages, slide_source


def is_current_file(path: Path) -> bool:
    """Whether `path` is a slide's current file (not one of its frozen versions)."""
    return path.name.endswith(CURRENT_SUFFIX)


def current_path_for_bare_id(ctx: ProjectContext, bare_id_: str) -> Optional[Path]:
    """The slides/<bare_id_>-...-current.tex path on disk right now, or
    None if that ID has no current file any more (renamed again, or
    deleted) -- by this project's own convention there is at most one
    -current.tex per bare ID."""
    matches = list(ctx.slides_dir.glob(f"{bare_id_}-*{CURRENT_SUFFIX}"))
    return matches[0] if matches else None


def current_id_slug_for_bare_id(ctx: ProjectContext, bare_id_: str) -> Optional[str]:
    path = current_path_for_bare_id(ctx, bare_id_)
    if path is None:
        return None
    return path.name[: -len(CURRENT_SUFFIX)]


def _header(path: Path) -> str:
    try:
        return path.read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""


@dataclass(frozen=True)
class Group:
    """A slide's translation group: the slide that is nobody's translation and its translations."""

    original: Optional[str]      # the original's id-slug; None when the links name none (a cycle, or a tangle)
    members: dict[str, str]      # language -> id-slug, the original among them; a language two slides claim is left out
    valid: bool                  # a star: every translation names the original, one slide per language


class TranslationLinks:
    """One scan per resolution, including links recorded on only one side. `codes` are the project's
    languages (languages.Languages.codes); only they count as a slide's language."""

    def __init__(self, slides_dir: Path, codes: tuple[str, ...]) -> None:
        self.slides_dir = slides_dir
        self.codes = codes
        self.paths = {bare_id(p.name): p
                      for p in self.slides_dir.glob("*-current.tex")}
        self.headers: dict[str, str] = {}
        self._groups: dict[str, Group] | None = None

    def own(self, id_slug: str) -> str | None:
        return own_language(id_slug, self.codes)

    def header(self, id_slug: str) -> str:
        if id_slug not in self.headers:
            self.headers[id_slug] = _header(self.slides_dir / current_name(id_slug))
        return self.headers[id_slug]

    def group(self, id_slug: str) -> Group:
        """The translation group of the slide with this id-slug's bare id. A slide of no language, or with no
        current file, is its own group. Links count from either side, as "Translation of:" and as
        "<LANG> translation:"."""
        if self._groups is None:
            self._groups = self._scan()
        return self._groups.get(bare_id(id_slug)) or Group(id_slug, {}, True)

    def find(self, id_slug: str, language: str) -> str | None:
        """The id-slug of the group's member in `language`, None for the slide's own language and for a language
        the group has no single slide in (conflicting links do not pick an arbitrary one)."""
        language = language.upper()
        if self.own(id_slug) in (None, MULT, language):
            return None
        return self.group(id_slug).members.get(language)

    def _scan(self) -> dict[str, Group]:
        slugs = {bare: path.name[:-len(CURRENT_SUFFIX)] for bare, path in self.paths.items()}
        slugs = {bare: slug for bare, slug in slugs.items() if self.own(slug) not in (None, MULT)}
        parents: dict[str, set[str]] = {bare: set() for bare in slugs}
        for bare, slug in slugs.items():
            header = self.header(slug)
            for m in TRANSLATION_OF_RE.finditer(header):
                original = bare_id(m.group(1))
                if original in slugs and self.own(slugs[original]) != self.own(slug):
                    parents[bare].add(original)
            for m in LANG_TRANSLATION_RE.finditer(header):
                translation = bare_id(m.group(2))
                if translation in slugs and self.own(slugs[translation]) == m.group(1) != self.own(slug):
                    parents[translation].add(bare)
        neighbours: dict[str, set[str]] = {bare: set(found) for bare, found in parents.items()}
        for bare, found in parents.items():
            for parent in found:
                neighbours[parent].add(bare)
        groups: dict[str, Group] = {}
        for start in slugs:
            if start in groups:
                continue
            component, todo = {start}, [start]
            while todo:
                for other in neighbours[todo.pop()] - component:
                    component.add(other)
                    todo.append(other)
            roots = [bare for bare in component if not parents[bare]]
            rooted = len(roots) == 1 and all(len(parents[bare]) == 1 for bare in component if bare != roots[0])
            claimed: dict[str, list[str]] = {}
            for bare in sorted(component):
                claimed.setdefault(self.own(slugs[bare]), []).append(slugs[bare])
            members = {language: found[0] for language, found in claimed.items() if len(found) == 1}
            if rooted:
                members[self.own(slugs[roots[0]])] = slugs[roots[0]]
            star = rooted and all(parents[bare] == {roots[0]} for bare in component if bare != roots[0])
            group = Group(slugs[roots[0]] if rooted else None, members, star and len(members) == len(component))
            groups.update(dict.fromkeys(component, group))
        return groups


def links_for(ctx: ProjectContext) -> TranslationLinks:
    """A fresh scan of the project's slides, with the project's languages."""
    return TranslationLinks(ctx.slides_dir, languages.project_languages(ctx).codes)


def translated_languages(ctx: ProjectContext, id_slug: str, *, links: Optional[TranslationLinks] = None) -> tuple[str, ...]:
    """The languages, in the project's order, of the other slides in this slide's translation group.

    Links belong to the current slide, also when a frozen version of it is shown.
    Pass a shared index when building badges for a whole list."""
    links = links or links_for(ctx)
    own = links.own(id_slug)
    if own in (None, MULT):
        return ()
    members = links.group(id_slug).members
    return tuple(code for code in links.codes if code != own and code in members)


@dataclass
class TranslationLink:
    """A slide and one other member of its translation group."""

    partner: str                # the partner's id-slug
    language: Optional[str]     # the partner's language
    path: Path                  # the partner's current file
    is_translation: bool        # this slide is the translation of `partner`, the original (else `partner` is of this,
                                # or both are translations of the group's original)
    outdated: bool              # the original was saved in SlideMage after the translation was last written
    is_original: bool = False   # this slide is the original and `partner` its translation


def translation_group(ctx: ProjectContext, id_slug: str, path: Optional[Path] = None, *,
                      links: Optional[TranslationLinks] = None) -> list[TranslationLink]:
    """One link to each other member of the slide's translation group, in the project's language order; empty
    for a slide with no translations. Links belong to the current slide, even when `path` is a frozen version.

    `outdated` measures this and nothing more: the original has been saved through SlideMage
    (slide_source.last_saved(): its newest backup) later than the translation was last written
    (the later of its own newest backup and its file's mtime). It is not a comparison of
    content, and an edit made outside SlideMage is not noticed. The translation is the partner, or this slide
    when the partner is the original."""
    links = links or links_for(ctx)
    own = links.own(id_slug)
    if own in (None, MULT):
        return []
    path = path or links.slides_dir / current_name(id_slug)
    group = links.group(id_slug)
    original = group.original
    is_original = original is not None and bare_id(original) == bare_id(id_slug)
    found = []
    for language in links.codes:
        partner = group.members.get(language)
        if language == own or partner is None:
            continue
        partner_path = links.paths[bare_id(partner)]
        is_translation = partner == original
        if is_translation:
            original_path, translation = partner_path, path
        elif is_original:
            original_path, translation = path, partner_path
        else:
            original_path, translation = links.paths.get(bare_id(original or "")), partner_path
        saved = slide_source.last_saved(ctx, original_path) if original_path else None
        written = max(filter(None, (slide_source.last_saved(ctx, translation),
                                    datetime.fromtimestamp(translation.stat().st_mtime))))
        found.append(TranslationLink(partner, language, partner_path, is_translation,
                                     saved is not None and saved > written, is_original))
    return found


@dataclass
class LanguageBadge:
    """What a GUI list row should show for one slide -- built once per
    row so every caller (deck_outline.py, the Add slide sheet,
    the Details view) renders the same underlying facts, even
    though each one displays them slightly differently (rich-text HTML,
    plain text + bold font, a QLabel)."""

    own: Optional[str]
    languages: tuple[str, ...]      # the other languages of the slide's translation group

    @property
    def both(self) -> bool:
        """True when this slide's own language *and* at least one translation into a
        *different* language exist -- the case that should be visually highlighted."""
        return self.own is not None and bool(self.languages)

    def text(self) -> str:
        """"" for an untagged slide, "[EN]" for a tagged one, "[EN + DE]" or "[EN + DE FR]" with
        translations, "[EN +3]" from four languages on (the tooltip lists them) -- callers append/style
        this however suits their widget."""
        if self.own is None:
            return ""
        if not self.languages:
            return f"[{self.own}]"
        if len(self.languages) >= 3:
            return f"[{self.own} +{len(self.languages)}]"
        return f"[{self.own} + {' '.join(self.languages)}]"


def badge_for(ctx: ProjectContext, id_slug: str, *, links: Optional[TranslationLinks] = None) -> LanguageBadge:
    links = links or links_for(ctx)
    return LanguageBadge(own=links.own(id_slug), languages=translated_languages(ctx, id_slug, links=links))


def call_for_slide_path(path: Path) -> tuple[str, str, Optional[str]]:
    """Given slides/<id>-<slug>-current.tex or slides/<id>-<slug>-vX-Y-Z.tex,
    return (macro, id_slug, version) for the \\slide{}/\\slideversion{}
    call that loads exactly that file -- used by the slide-source editor,
    which only knows its own file path, not a deck-parsed SlideCall."""
    name = path.name
    if name.endswith(CURRENT_SUFFIX):
        return "slide", name[: -len(CURRENT_SUFFIX)], None
    m = FROZEN_RE.search(name)
    if m:
        return "slideversion", name[: m.start()], m.group(1)
    raise ValueError(f"{name}: doesn't look like a slides/ current or version file")
