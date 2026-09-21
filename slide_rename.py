"""Change a slide's own language segment (<id>-<slug> -> <id>-<LANG>-<slug>,
or <id>-<OLDLANG>-<slug> -> <id>-<LANG>-<slug>), and keep translation
cross-reference header comments honest afterward. See LANGUAGE_NOTES.md
for the whole design.

Two entry points:

- set_slide_language(): the actual rename -- renames current.tex plus
  every frozen -vX-Y-Z.tex sibling (git mv when tracked, else a plain
  move, same fallback archive.py already established), rewrites every
  \\slide-family reference to the old id-slug across every deck (including
  #workdeck.tex, unlike deck_headers.py's own header regeneration which
  deliberately excludes it), then re-runs deck_headers.regenerate_headers()
  and regenerate_translation_links() so both kinds of derived text stay in
  sync with the rename.

- regenerate_translation_links(): mirrors
  deck_headers.regenerate_headers()'s own "recompute from disk state,
  don't trust old text" approach, but per translation cross-reference
  header line rather than per deck-inclusion header block. Run standalone
  (its own SlideMage toolbar button) or automatically after a rename /
  after AddSlideDialog's "base on existing slide" flow.

Deliberately does NOT try to reconcile roles across a pair of files (which
side says "Translation of:" vs "<LANG> translation:") -- it only ever
refreshes a comment line that already names a bare ID, resolving that
bare ID's *current* on-disk id-slug/language. It never invents a new line
on a side that never declared the relationship, matching
add_deck_headers.py's own add-only caution.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import deck_headers, slide_language
from .deck_scan import ARCHIVE_DIR, DECKS_DIR, PROJECT_ROOT

SLIDES_DIR = PROJECT_ROOT / "slides"
WORKDECK_PATH = DECKS_DIR / "#workdeck.tex"

# SlideMage.bat launches the GUI with no console of its own -- same
# fix, same reason, as compiler.py's/archive.py's own subprocess calls.
_NO_CONSOLE_KWARGS: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

# Mirrors deck_headers.SLIDE_CALL_RE's own macro set, plus conditionalslide
# (deck_headers.py's own regex omits it -- a pre-existing gap unrelated to
# this feature, left alone here rather than silently "fixed" as a
# drive-by; conditionalslide references still get rewritten correctly by
# THIS module's own pattern, just not counted by deck_headers.py's
# separate "Included in decks" bookkeeping).
_MACROS = (
    "slide", "slidefinal", "slideversion",
    "omitslide", "omitslideversion", "conditionalslide", "slidestep",
)


def _is_git_repo() -> bool:
    return (PROJECT_ROOT / ".git").exists()


def _is_git_tracked(path: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(PROJECT_ROOT))],
        cwd=PROJECT_ROOT, capture_output=True, **_NO_CONSOLE_KWARGS,
    )
    return result.returncode == 0


def _move(src: Path, dest: Path) -> None:
    if _is_git_repo() and _is_git_tracked(src):
        subprocess.run(
            ["git", "mv", str(src.relative_to(PROJECT_ROOT)), str(dest.relative_to(PROJECT_ROOT))],
            cwd=PROJECT_ROOT, check=True, **_NO_CONSOLE_KWARGS,
        )
    else:
        shutil.move(str(src), str(dest))


def compute_new_id_slug(id_slug: str, language: str) -> str:
    """<id>-<slug> or <id>-<OLDLANG>-<slug> -> <id>-<language>-<slug>."""
    if language not in slide_language.LANGUAGES:
        raise ValueError(f"language must be one of {slide_language.LANGUAGES}, got {language!r}")
    parts = id_slug.split("-", 2)
    if len(parts) < 2:
        raise ValueError(f"not a valid id-slug (needs at least one hyphen): {id_slug!r}")
    slide_id = parts[0]
    if len(parts) >= 3 and parts[1] in slide_language.LANGUAGES:
        slug = parts[2]
    else:
        slug = "-".join(parts[1:])
    return f"{slide_id}-{language}-{slug}"


def _reference_pattern(id_slug: str) -> re.Pattern:
    # Anchored on both sides (macro-name-open-brace prefix, closing brace
    # suffix) so the id-slug has to be the *entire* argument, not merely a
    # substring of some other, longer id-slug/slug.
    return re.compile(
        r"(\\(?:" + "|".join(_MACROS) + r")(?:\[[^\]]*\])?\{)"
        + re.escape(id_slug) + r"(\})"
    )


def count_references(id_slug: str) -> int:
    """How many \\slide-family calls, across every deck (including
    #workdeck.tex), currently reference this id-slug -- for a
    confirmation dialog before set_slide_language() rewrites them."""
    pattern = _reference_pattern(id_slug)
    total = 0
    deck_paths = [
        p for directory in (DECKS_DIR, ARCHIVE_DIR) if directory.is_dir()
        for p in directory.glob("*.tex")
    ]
    for deck_path in deck_paths:
        text = deck_path.read_text(encoding="utf-8", newline="")
        total += len(pattern.findall(text))
    return total


def _rewrite_references_in_file(deck_path: Path, id_slug: str, new_id_slug: str) -> int:
    text = deck_path.read_text(encoding="utf-8", newline="")
    pattern = _reference_pattern(id_slug)
    new_text, n = pattern.subn(r"\g<1>" + new_id_slug + r"\g<2>", text)
    if n:
        deck_path.write_text(new_text, encoding="utf-8", newline="")
    return n


def set_slide_language(id_slug: str, language: str) -> str:
    """Renames slides/<id_slug>-current.tex (and every frozen
    -vX-Y-Z.tex sibling) to carry `language`'s segment, rewrites every
    reference across every deck, and regenerates both derived-text kinds
    (deck-inclusion headers, translation cross-references). Returns the
    new id-slug (unchanged from id_slug if it already carried this exact
    language segment)."""
    new_id_slug = compute_new_id_slug(id_slug, language)
    if new_id_slug == id_slug:
        return id_slug

    current_src = SLIDES_DIR / f"{id_slug}-current.tex"
    if not current_src.exists():
        raise FileNotFoundError(f"{current_src} does not exist")
    current_dest = SLIDES_DIR / f"{new_id_slug}-current.tex"
    if current_dest.exists():
        raise FileExistsError(f"{current_dest} already exists")

    renames: list[tuple[Path, Path]] = [(current_src, current_dest)]
    version_prefix_len = len(id_slug)
    for version_src in SLIDES_DIR.glob(f"{id_slug}-v*.tex"):
        suffix = version_src.name[version_prefix_len:]  # "-vX-Y-Z.tex"
        version_dest = SLIDES_DIR / f"{new_id_slug}{suffix}"
        if version_dest.exists():
            raise FileExistsError(f"{version_dest} already exists")
        renames.append((version_src, version_dest))

    for src, dest in renames:
        _move(src, dest)

    deck_paths = [
        p for directory in (DECKS_DIR, ARCHIVE_DIR) if directory.is_dir()
        for p in directory.glob("*.tex")
        if p.name != "#workdeck.tex"
    ]
    if WORKDECK_PATH.exists():
        deck_paths.append(WORKDECK_PATH)
    for deck_path in deck_paths:
        _rewrite_references_in_file(deck_path, id_slug, new_id_slug)

    deck_headers.regenerate_headers()
    regenerate_translation_links()
    return new_id_slug


def set_slide_languages_bulk(id_slugs: list[str], language: str) -> dict[str, str]:
    """Bulk sibling of set_slide_language() -- e.g. for a one-time "tag
    every legacy slide as EN" migration pass (see LANGUAGE_NOTES.md).
    Same rename + reference-rewrite as the single-slide version, but
    batched for many slides at once rather than looped:

    - Every deck file is read and written **once**, with every applicable
      rename applied to it in a single regex pass, instead of once per
      (slide, deck) pair -- calling set_slide_language() in a loop over
      665 slides would re-read/re-write every deck file 665 times each.
    - deck_headers.regenerate_headers()/regenerate_translation_links()
      (each their own full project-wide scan) run **once** at the end,
      not once per slide.
    - Destination-collision checks for every slide run *before* any file
      is actually moved, so a problem partway through the list is caught
      up front rather than leaving some slides renamed and others not.

    Slides already carrying `language`'s own segment are silently
    skipped (not an error, not included in the returned mapping) -- safe
    to call again on a list that partially overlaps a previous run.
    Returns {old_id_slug: new_id_slug} for every slide actually renamed.
    """
    mapping: dict[str, str] = {}
    for id_slug in id_slugs:
        new_id_slug = compute_new_id_slug(id_slug, language)
        if new_id_slug != id_slug:
            mapping[id_slug] = new_id_slug
    if not mapping:
        return {}

    # Validate every rename up front -- a FileExistsError discovered on
    # slide 400 of 665 after already moving the first 399 would leave the
    # project in a half-migrated state that's annoying to reason about.
    planned: list[tuple[Path, Path]] = []
    for id_slug, new_id_slug in mapping.items():
        current_src = SLIDES_DIR / f"{id_slug}-current.tex"
        if not current_src.exists():
            raise FileNotFoundError(f"{current_src} does not exist")
        current_dest = SLIDES_DIR / f"{new_id_slug}-current.tex"
        if current_dest.exists():
            raise FileExistsError(f"{current_dest} already exists")
        planned.append((current_src, current_dest))
        version_prefix_len = len(id_slug)
        for version_src in SLIDES_DIR.glob(f"{id_slug}-v*.tex"):
            suffix = version_src.name[version_prefix_len:]
            version_dest = SLIDES_DIR / f"{new_id_slug}{suffix}"
            if version_dest.exists():
                raise FileExistsError(f"{version_dest} already exists")
            planned.append((version_src, version_dest))

    for src, dest in planned:
        _move(src, dest)

    # One combined pattern, alternating every old id-slug -- three groups
    # (macro-name/open-brace prefix, the id-slug itself, closing brace) so
    # the replacement is a plain dict lookup on group 2, same anchoring
    # (full-argument match, no substring risk) as _reference_pattern()
    # above.
    pattern = re.compile(
        r"(\\(?:" + "|".join(_MACROS) + r")(?:\[[^\]]*\])?\{)("
        + "|".join(re.escape(s) for s in mapping) + r")(\})"
    )

    def _repl(m: "re.Match[str]") -> str:
        return m.group(1) + mapping[m.group(2)] + m.group(3)

    deck_paths = [
        p for directory in (DECKS_DIR, ARCHIVE_DIR) if directory.is_dir()
        for p in directory.glob("*.tex")
        if p.name != "#workdeck.tex"
    ]
    if WORKDECK_PATH.exists():
        deck_paths.append(WORKDECK_PATH)
    for deck_path in deck_paths:
        text = deck_path.read_text(encoding="utf-8", newline="")
        new_text = pattern.sub(_repl, text)
        if new_text != text:
            deck_path.write_text(new_text, encoding="utf-8", newline="")

    deck_headers.regenerate_headers()
    regenerate_translation_links()
    return mapping


def _resolve_reference(bare_ref: str) -> Optional[str]:
    return slide_language.current_id_slug_for_bare_id(slide_language.bare_id(bare_ref))


def regenerate_translation_links() -> tuple[int, list[str]]:
    """Rescan every slides/*-current.tex file's own "%% Translation of:
    ..." / "%% <LANG> translation: ..." header lines and refresh each to
    point at its target's *current* id-slug/language. Returns (files
    changed, [report strings for any link whose target no longer has a
    -current.tex] -- surfaced in the GUI log/a summary dialog rather than
    silently dropped, same as alt_images.SyncReport.missing)."""
    changed = 0
    missing: list[str] = []

    for path in sorted(SLIDES_DIR.glob("*-current.tex")):
        own_name = path.name[: -len(slide_language.CURRENT_SUFFIX)]
        text = path.read_text(encoding="utf-8", newline="")
        new_text = text

        m = slide_language.TRANSLATION_OF_RE.search(new_text)
        if m:
            resolved = _resolve_reference(m.group(1))
            if resolved is None:
                missing.append(
                    f"{own_name}: \"Translation of: {m.group(1)}\" no longer "
                    "resolves to a slides/*-current.tex file -- left as-is, please check."
                )
            elif resolved != m.group(1):
                new_text = new_text[: m.start(1)] + resolved + new_text[m.end(1):]

        def _lang_repl(lm: "re.Match[str]") -> str:
            resolved = _resolve_reference(lm.group(2))
            if resolved is None:
                missing.append(
                    f"{own_name}: \"{lm.group(1)} translation: {lm.group(2)}\" no "
                    "longer resolves to a slides/*-current.tex file -- left as-is, "
                    "please check."
                )
                return lm.group(0)
            target_lang = slide_language.own_language(resolved) or lm.group(1)
            return f"%% {target_lang} translation: {resolved}"

        new_text = slide_language.LANG_TRANSLATION_RE.sub(_lang_repl, new_text)

        if new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="")
            changed += 1

    return changed, missing
