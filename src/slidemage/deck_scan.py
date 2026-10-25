# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Discover and parse the decks this project knows how to compile.

A "deck" is any *.tex file directly inside decks/ or decks/archive/ that
contains \\documentclass -- the same "top-level compilable file" concept
README.md already uses, which naturally excludes shared fragments like
decks/test-slides.tex (no \\documentclass of its own).
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import deck_groups, project
from .tex_source import is_commented


SECTION_RE = re.compile(r"\\section\{([^}]*)\}")
DOCUMENT_BEGIN_RE = re.compile(r"\\begin\{document\}")
DOCUMENT_BEGIN_LINE_RE = re.compile(r"^[ \t]*\\begin\{document\}", re.MULTILINE)
DOCUMENT_END_RE = re.compile(r"\\end\{document\}")
DOCUMENTCLASS_RE = re.compile(r"\\documentclass")
DECKVERSIONOVERRIDE_RE = re.compile(r"\\deckversionoverride")
ADDBIBRESOURCE_RE = re.compile(r"\\addbibresource")
# \deckoutputfolder[version]{path} / \deckoutputfolder{path} -- a deck's own
# declared output folder, optionally scoped to one deck version
# (instructor/during-course/after-course), to "presenter" (a presenter
# job's own .version is already "instructor" -- see
# compiler.resolve_output_location() for why this needs its own key
# rather than falling under "instructor"), to "transcript" (the transcript
# writer's own output location -- see transcript.py's
# resolve_transcript_location()), or bare for a fallback that covers
# every output -- every compile version *and* the transcript writer --
# without a more specific declaration of its own ("presenter" falls back
# to "instructor" then the bare form; "transcript" falls back to the bare
# form directly, skipping any version-specific PDF folder, since those
# are a different axis). A real, inert macro (defined as a no-op in
# SlideMage_base.tex) rather than a "%"-comment convention,
# matching every other deck-authored,
# Python-parsed directive in this project (\deckversion, \decklanguage,
# \deckversionoverride -- none of them are comments).
OUTPUT_FOLDER_RE = re.compile(r"\\deckoutputfolder(?:\[([^\]]*)\])?\{([^}]*)\}")

# \decktags{tag1,tag2} -- a deck's own tags (see SlideMage_base.tex's
# inert \decktags). The tags that name one of the project's deck groups
# (deck_groups.py) put the deck into those groups; a deck naming none is in
# the fallback group.
DECKTAGS_RE = re.compile(r"\\decktags\{([^}]*)\}")
# \deckappendixtoc in the preamble: always generate the appendix TOC for
# this deck (whole-deck compiles), whatever the toolbar checkbox says.
DECKAPPENDIXTOC_RE = re.compile(r"\\deckappendixtoc(?![a-zA-Z@])")
COURSE_URL_RE = re.compile(r"^[ \t]*%% SlideMage course URL:[ \t]*([^\r\n]*)\r?$", re.MULTILINE)
# The default groups' tags and the manual's (deck_groups.py).
TAG_WORK = deck_groups.TAG_WORK
TAG_COURSE = deck_groups.TAG_COURSE
TAG_RESEARCH = deck_groups.TAG_RESEARCH
TAG_TEST = deck_groups.TAG_TEST
TAG_MANUAL = deck_groups.TAG_MANUAL
# The default groups' values of deck_groups.group_tags(), selectable_tags() and
# switcher_order(): with a project's own list, ask deck_groups.
GROUP_TAGS = deck_groups.group_tags()
SELECTABLE_GROUP_TAGS = deck_groups.selectable_tags()
GROUP_ORDER = deck_groups.switcher_order()


@dataclass
class Chapter:
    order: int          # 1-based position within the deck
    title: str          # raw \section{...} text, e.g. "Financial Planning"
    slug: str           # filename-safe version, e.g. "Financial-Planning"
    start: int           # char offset of the \section{...} call itself
    end: int             # char offset where this chapter's content ends


@dataclass
class Deck:
    name: str            # jobname: filename without .tex
    path: Path
    archived: bool
    text: str
    supports_version: bool
    uses_biblatex: bool
    preamble_end: int | None  # char offset just past \begin{document}, or
                               # None if the file has no \begin{document}
                               # (shouldn't happen for a real deck)
    chapters: list[Chapter]
    # \deckoutputfolder-declared output destinations: version name
    # ("instructor"/"during-course"/"after-course"), "presenter", None (the
    # bare, every-version fallback), or "transcript" -> raw path text as written
    # in the deck (not yet resolved against the project folder, nor checked for
    # naming a full file rather than a folder -- compiler.resolve_output_location()
    # does that for compiled PDFs, transcript.resolve_transcript_location()
    # for transcripts). Empty dict for a deck with no \deckoutputfolder at all.
    output_folders: dict[str | None, str]

    # The deck's own \decktags{...}, lowercased, in file order. Parsed from
    # the deck's text (parse_tags()), never inferred from its filename.
    tags: list[str] = field(default_factory=list)
    course_url: str | None = None
    # \deckappendixtoc in the preamble (parse_appendix_toc())
    appendix_toc: bool = False
    # which PDF "Open pdf" opens by default (parse_open_pdf(); None = instructor)
    open_pdf: str | None = None

    # The deck's groups in switcher order and their roles (deck_groups.groups_of(),
    # roles_of()), from the project's list at scan time; a Deck made without them
    # gets them from its tags and the default groups.
    groups: tuple[str, ...] | None = None
    roles: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.groups is None:
            self.groups = deck_groups.groups_of(self.tags)
        if self.roles is None:
            self.roles = deck_groups.roles_of(self.groups)

    @property
    def group(self) -> str:
        """The first of the deck's groups ("" for a deck in none): the one
        it is listed and compiled under."""
        return self.groups[0] if self.groups else ""

    @property
    def is_pinned(self) -> bool:
        """In a group with the `pinned` role: first in the deck switcher."""
        return deck_groups.ROLE_PINNED in self.roles

    @property
    def is_test_deck(self) -> bool:
        """In a group with the `test` role (by default `test`): layout
        regression fixtures (decks/test*.tex, verify_accessibility.tex) whose
        slides come from a shared fragment rather than \\slide{} calls of
        their own, so there is no slide list or source to open for them in
        the GUI, and no background previews."""
        return deck_groups.ROLE_TEST in self.roles

    @property
    def has_chapters(self) -> bool:
        return len(self.chapters) > 0

    @property
    def preamble_text(self) -> str:
        """Everything up to and including \\begin{document}."""
        if self.preamble_end is None:
            raise ValueError(f"{self.name}: no \\begin{{document}} found")
        return self.text[: self.preamble_end]

    def chapter_text(self, chapter: Chapter) -> str:
        return self.text[chapter.start : chapter.end]


def slugify(title: str) -> str:
    """'Financial Planning' -> 'Financial-Planning'.

    Collapses any run of non-alphanumeric characters to a single hyphen and
    strips leading/trailing hyphens; case is left as written so the slug
    still reads like the section title.
    """
    slug = re.sub(r"[^0-9A-Za-z]+", "-", title).strip("-")
    return slug or "chapter"


def parse_chapters(text: str) -> list[Chapter]:
    doc_end_match = DOCUMENT_END_RE.search(text)
    doc_end = doc_end_match.start() if doc_end_match else len(text)

    matches = [m for m in SECTION_RE.finditer(text) if not is_commented(text, m.start())]
    chapters: list[Chapter] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else doc_end
        title = m.group(1).strip()
        chapters.append(
            Chapter(
                order=i + 1,
                title=title,
                slug=slugify(title),
                start=m.start(),
                end=end,
            )
        )
    return chapters


def _parse_output_folders(text: str) -> dict[str | None, str]:
    """Every \\deckoutputfolder declaration in `text`, keyed by version
    (or None for the bare, all-versions fallback), or "transcript" for the
    transcript-specific output location (transcript.py's own
    resolve_transcript_location()). Last declaration for a given key wins
    if the deck has more than one -- simplest rule, matches how a human
    reads two conflicting lines.

    A commented-out declaration is skipped (2026-09-17, direct report:
    "the command is still honored, but shouldn't be") -- OUTPUT_FOLDER_RE
    itself has no notion of "%" (finditer() is a plain substring search
    over the whole text), so without this check a line like
    "% \\deckoutputfolder{...}" matched exactly like a live one. Same
    leading-comment check already used for this purpose at
    slide_versioning.py's set_marker(): a match is skipped only when the
    text from the start of its own line up to the match itself, once
    left-stripped, starts with "%" -- a live directive that merely shares
    its line with a *trailing* comment is unaffected.
    """
    folders: dict[str | None, str] = {}
    for m in OUTPUT_FOLDER_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].lstrip().startswith("%"):
            continue
        # group(1) is None outright for the bare \deckoutputfolder{path}
        # form (no "[...]" at all, not just an empty "[]") -- (m.group(1)
        # or "").strip() collapses both that and an explicit empty "[]"
        # to the same "() -> fallback" case.
        version = (m.group(1) or "").strip() or None
        folders[version] = m.group(2).strip()
    return folders


def find_decktags(text: str) -> "re.Match[str] | None":
    """The first live (not %-commented) \\decktags{...} in `text`, or None.
    Same leading-comment check _parse_output_folders() uses: a match is
    skipped only when everything before it on its own line, left-stripped,
    starts with "%"."""
    for m in DECKTAGS_RE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if not text[line_start:m.start()].lstrip().startswith("%"):
            return m
    return None


def parse_tags(text: str) -> list[str]:
    """A deck's tags: the comma-separated list inside its first live
    \\decktags{...}, stripped and lowercased, empties dropped."""
    m = find_decktags(text)
    if m is None:
        return []
    return [t for t in (part.strip().lower() for part in m.group(1).split(",")) if t]


def parse_appendix_toc(text: str) -> bool:
    """Whether the deck's preamble has a live \\deckappendixtoc."""
    begin = DOCUMENT_BEGIN_RE.search(text)
    preamble = text[:begin.start()] if begin else text
    return any(not is_commented(preamble, m.start())
               for m in DECKAPPENDIXTOC_RE.finditer(preamble))


def parse_course_url(text: str) -> str | None:
    """Read the first course URL marker in the deck preamble."""
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    preamble = text[:begin.start()] if begin else text
    match = COURSE_URL_RE.search(preamble)
    return match.group(1).strip() or None if match else None


# "%% SlideMage open PDF: during-course" in the preamble (v5.34.0, direct
# instruction): which PDF the deck table's "Open pdf" opens by default.
# Missing = the instructor PDF. A comment, like the course URL, so a deck
# with it still compiles against an older framework.
OPEN_PDF_CHOICES = ("instructor", "during-course", "after-course", "presenter")
OPEN_PDF_RE = re.compile(r"^[ \t]*%% SlideMage open PDF:[ \t]*([^\r\n]*)\r?$", re.MULTILINE)


def parse_open_pdf(text: str) -> str | None:
    """The deck's "Open pdf" default (one of OPEN_PDF_CHOICES), or None."""
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    preamble = text[:begin.start()] if begin else text
    match = OPEN_PDF_RE.search(preamble)
    value = match.group(1).strip().lower() if match else ""
    return value if value in OPEN_PDF_CHOICES else None


def read_deck(path: Path, archived: bool = False,
              groups: Sequence[deck_groups.DeckGroup] = deck_groups.DEFAULT_GROUPS) -> Deck:
    """Read one deck or body fragment, preserving its literal line endings.
    Its groups and roles come from `groups`, the project's list."""
    # newline="" passes CRLF through untouched, matching every other
    # reader in this package (archive.py, slide_source.py, ...) --
    # without it, Path.read_text()'s universal-newlines default silently
    # normalizes this project's CRLF files to bare "\n", so deck.text
    # never byte-matches archive.read()'s raw re-read of the same file
    # in deck_editor.py's stale-file check, which then raises
    # StaleFileError on every single edit, even immediately after a
    # fresh restart.
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        text = f.read()
    doc_begin_match = DOCUMENT_BEGIN_RE.search(text)
    tags = parse_tags(text)
    in_groups = deck_groups.groups_of(tags, groups)
    return Deck(
        name=path.stem,
        path=path,
        archived=archived,
        text=text,
        supports_version=bool(DECKVERSIONOVERRIDE_RE.search(text)),
        uses_biblatex=bool(ADDBIBRESOURCE_RE.search(text)),
        preamble_end=doc_begin_match.end() if doc_begin_match else None,
        chapters=parse_chapters(text),
        output_folders=_parse_output_folders(text),
        tags=tags,
        course_url=parse_course_url(text),
        appendix_toc=parse_appendix_toc(text),
        open_pdf=parse_open_pdf(text),
        groups=in_groups,
        roles=deck_groups.roles_of(in_groups, groups),
    )


def is_generated_wrapper(name: str) -> bool:
    """Underscore-prefixed TeX wrappers generated by SlideMage or compile-all-versions.bat."""
    return name.startswith("_") and name.lower().endswith(".tex")


def scan_dir(directory: Path, archived: bool,
             groups: Sequence[deck_groups.DeckGroup] = deck_groups.DEFAULT_GROUPS) -> list[Deck]:
    """The decks directly in `directory`, their groups from `groups` (the
    project's list; scan_decks() loads it)."""
    decks: list[Deck] = []
    if not directory.is_dir():
        return decks
    for path in sorted(directory.glob("*.tex")):
        if is_generated_wrapper(path.name):
            continue
        deck = read_deck(path, archived, groups)
        if not DOCUMENTCLASS_RE.search(deck.text):
            continue  # a fragment (e.g. test-slides.tex), not a deck
        decks.append(deck)
    return decks


def scan_decks(ctx: project.ProjectContext) -> list[Deck]:
    """Every discovered deck: active decks first, then archived ones, each
    group sorted by filename. The project's deck groups are read once, for
    every deck's groups and roles."""
    groups = deck_groups.load(ctx)
    return scan_dir(ctx.decks_dir, archived=False, groups=groups) + scan_dir(ctx.archive_dir, archived=True, groups=groups)


if __name__ == "__main__":
    for deck in scan_decks(project.from_environment()):
        tag = "archived" if deck.archived else "active"
        ver = "yes" if deck.supports_version else "no"
        bib = "yes" if deck.uses_biblatex else "no"
        print(f"{deck.name}  [{tag}]  version-override={ver}  biblatex={bib}"
              f"  chapters={len(deck.chapters)}")
        for ch in deck.chapters:
            print(f"    {ch.order:02d}. {ch.title}  -> {ch.slug}")
