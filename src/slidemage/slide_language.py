"""Multi-language parsing primitives shared by the SlideMage GUI's
language badges (deck_outline.py, qt_add_slide_dialog.py,
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

Written by AddSlideDialog's "base on existing slide" flow (both sides at
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

TRANSLATION_OF_RE = re.compile(r"^%% Translation of: (\S+)", re.MULTILINE)
LANG_TRANSLATION_RE = re.compile(r"^%% (EN|DE|mult) translation: (\S+)", re.MULTILINE)

CURRENT_SUFFIX = "-current.tex"


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


def cross_referenced_language(id_slug: str, path: Optional[Path] = None) -> Optional[str]:
    """The language of whatever this slide's own header comment names as
    a translation partner, in either direction -- None if there's no such
    comment, the partner file no longer exists, or the file can't be
    read. Cheap enough to call per row in a slide list (one small regex
    search over one already-short header block), but does read the file,
    unlike own_language() which is pure string parsing."""
    if path is None:
        path = SLIDES_DIR / f"{id_slug}{CURRENT_SUFFIX}"
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError:
        return None

    m = TRANSLATION_OF_RE.search(text)
    if m:
        partner_id_slug = current_id_slug_for_bare_id(bare_id(m.group(1)))
        if partner_id_slug is not None:
            return own_language(partner_id_slug)
        return None

    lm = LANG_TRANSLATION_RE.search(text)
    if lm:
        return lm.group(1)

    return None


@dataclass
class TranslationLink:
    """A slide and the partner its header comment names."""

    partner: str                # the partner's id-slug
    language: Optional[str]     # the partner's language
    path: Path                  # the partner's current file
    is_translation: bool        # this slide is the translation of `partner` (else `partner` is of this)
    outdated: bool              # the original was saved in SlideMage after the translation was last written


def translation_link(id_slug: str, path: Optional[Path] = None) -> Optional[TranslationLink]:
    """The slide's translation partner, from its own header comment ("%% Translation of:" or
    "%% <LANG> translation:"), or None when there is no such comment or the partner's file is gone.

    `outdated` measures this and nothing more: the original has been saved through SlideMage
    (slide_source.last_saved(): its newest backup) later than the translation was last written
    (the later of its own newest backup and its file's mtime). It is not a comparison of
    content, and an edit made outside SlideMage is not noticed."""
    path = path or SLIDES_DIR / f"{id_slug}{CURRENT_SUFFIX}"
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError:
        return None
    if m := TRANSLATION_OF_RE.search(text):
        is_translation, ref = True, m.group(1)
    elif m := LANG_TRANSLATION_RE.search(text):
        is_translation, ref = False, m.group(2)
    else:
        return None
    partner = current_id_slug_for_bare_id(bare_id(ref))
    partner_path = current_path_for_bare_id(bare_id(ref))
    if partner is None or partner_path is None or partner == id_slug:
        return None
    original, translation = (partner_path, path) if is_translation else (path, partner_path)
    saved = slide_source.last_saved(original)
    written = max(filter(None, (slide_source.last_saved(translation),
                                datetime.fromtimestamp(translation.stat().st_mtime))))
    return TranslationLink(partner, own_language(partner), partner_path, is_translation,
                           saved is not None and saved > written)


@dataclass
class LanguageBadge:
    """What a GUI list row should show for one slide -- built once per
    row so every caller (deck_outline.py, qt_add_slide_dialog.py,
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


def badge_for(id_slug: str, path: Optional[Path] = None) -> LanguageBadge:
    own = own_language(id_slug)
    cross = cross_referenced_language(id_slug, path) if own is not None else None
    return LanguageBadge(own=own, cross_referenced=cross)
