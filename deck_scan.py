"""Discover and parse the decks this project knows how to compile.

A "deck" is any *.tex file directly inside decks/ or decks/archive/ that
contains \\documentclass -- the same "top-level compilable file" concept
README.md already uses, which naturally excludes shared fragments like
decks/test-slides.tex (no \\documentclass of its own).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _find_project_root() -> Path:
    # Not frozen: SlideMage/ sits directly inside the real project root,
    # same as always. Frozen (PyInstaller): __file__ points into a bundle/
    # temp-extraction dir, not the real, live project tree the compiled exe
    # is meant to operate on (decks/slides/media/etc, edited independently
    # of whatever build the exe happens to be) -- start from the exe's own
    # location instead and walk upward looking for slide_ids.csv, a marker
    # unique to this project's real root, so the exe keeps working
    # regardless of exactly where it's placed (dist/, project root, ...) as
    # long as it stays somewhere inside/near the actual project tree.
    start = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )
    for candidate in (start, *start.parents):
        if (candidate / "slide_ids.csv").exists():
            return candidate
    return start


PROJECT_ROOT = _find_project_root()
DECKS_DIR = PROJECT_ROOT / "decks"
ARCHIVE_DIR = DECKS_DIR / "archive"

SECTION_RE = re.compile(r"\\section\{([^}]*)\}")
# A "%" that isn't escaped as "\%" starts a LaTeX comment running to the end
# of its line -- used by is_commented() below to recognize a commented-out
# \section{}/\slide{}-family call as not really there (2026-09-28, porting
# SlideMage upstream commit 34cdbd7).
COMMENT_RE = re.compile(r"(?<!\\)%.*")
DOCUMENT_BEGIN_RE = re.compile(r"\\begin\{document\}")
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
# Slidemaster_preamble_base.tex) rather than a "%"-comment convention,
# matching every other deck-authored,
# Python-parsed directive in this project (\deckversion, \decklanguage,
# \deckversionoverride -- none of them are comments).
OUTPUT_FOLDER_RE = re.compile(r"\\deckoutputfolder(?:\[([^\]]*)\])?\{([^}]*)\}")

# \decktags{tag1,tag2} -- a deck's own tags (see Slidemaster_preamble_base.tex's
# inert \decktags). The deck tables group decks by whichever of GROUP_TAGS a
# deck carries; a deck carrying none is a course deck. When a deck carries
# several, the first one in GROUP_TAGS' order wins.
DECKTAGS_RE = re.compile(r"\\decktags\{([^}]*)\}")
TAG_WORK = "work"
TAG_COURSE = "course"
TAG_RESEARCH = "research"
TAG_TEST = "test"
GROUP_TAGS = (TAG_WORK, TAG_COURSE, TAG_RESEARCH, TAG_TEST)


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
    # in the deck (not yet resolved against PROJECT_ROOT, nor checked for
    # naming a full file rather than a folder -- compiler.resolve_output_location()
    # does that for compiled PDFs, transcript.resolve_transcript_location()
    # for transcripts). Empty dict for a deck with no \deckoutputfolder at all.
    output_folders: dict[str | None, str]

    # The deck's own \decktags{...}, lowercased, in file order. Parsed from
    # the deck's text (parse_tags()), never inferred from its filename.
    tags: list[str] = field(default_factory=list)

    @property
    def group(self) -> str:
        """Which deck-table group this deck belongs to: the first of
        GROUP_TAGS it carries, else TAG_COURSE."""
        for tag in GROUP_TAGS:
            if tag in self.tags:
                return tag
        return TAG_COURSE

    @property
    def is_test_deck(self) -> bool:
        """Tagged `test`: layout regression fixtures (decks/test*.tex,
        verify_accessibility.tex) whose slides come from a shared fragment
        rather than \\slide{} calls of their own, so there is no slide list
        or source to open for them in the GUI."""
        return self.group == TAG_TEST

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


def is_commented(text: str, pos: int) -> bool:
    """Whether the character at `pos` in `text` falls inside a "%"-started
    LaTeX comment -- true if an unescaped "%" appears anywhere between the
    start of pos's own line and pos itself. Shared by _parse_chapters()
    below and deck_editor.is_commented_out(), so a commented-out
    \\section{}/\\slide{}-family call is recognized as not really there by
    both this module's chapter list and appendix_toc.py's own slide-call
    filtering. Unlike _parse_output_folders()/find_decktags()'s own
    narrower "starts-with-%" check, this also catches a macro that follows
    a live "%" occurring earlier on the same line, not just one at the very
    start of it (2026-09-28, porting SlideMage upstream commit 34cdbd7)."""
    line_start = text.rfind("\n", 0, pos) + 1
    return bool(COMMENT_RE.search(text, line_start, pos))


def _parse_chapters(text: str) -> list[Chapter]:
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


def _scan_dir(directory: Path, archived: bool) -> list[Deck]:
    decks: list[Deck] = []
    if not directory.is_dir():
        return decks
    for path in sorted(directory.glob("*.tex")):
        if path.name.startswith("_"):
            continue  # SlideMage's / compile-all-versions.bat's own
            # generated wrapper files, never a real deck
        # newline="" passes CRLF through untouched, matching every other
        # reader in this package (archive.py, slide_source.py, ...) --
        # without it, Path.read_text()'s universal-newlines default silently
        # normalizes this project's CRLF files to bare "\n", so deck.text
        # never byte-matches archive._read()'s raw re-read of the same file
        # in deck_editor.py's stale-file check, which then raises
        # StaleFileError on every single edit, even immediately after a
        # fresh restart.
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
        if not DOCUMENTCLASS_RE.search(text):
            continue  # a fragment (e.g. test-slides.tex), not a deck
        doc_begin_match = DOCUMENT_BEGIN_RE.search(text)
        decks.append(
            Deck(
                name=path.stem,
                path=path,
                archived=archived,
                text=text,
                supports_version=bool(DECKVERSIONOVERRIDE_RE.search(text)),
                uses_biblatex=bool(ADDBIBRESOURCE_RE.search(text)),
                preamble_end=doc_begin_match.end() if doc_begin_match else None,
                chapters=_parse_chapters(text),
                output_folders=_parse_output_folders(text),
                tags=parse_tags(text),
            )
        )
    return decks


def scan_decks() -> list[Deck]:
    """Every discovered deck: active decks first, then archived ones, each
    group sorted by filename."""
    return _scan_dir(DECKS_DIR, archived=False) + _scan_dir(ARCHIVE_DIR, archived=True)


if __name__ == "__main__":
    for deck in scan_decks():
        tag = "archived" if deck.archived else "active"
        ver = "yes" if deck.supports_version else "no"
        bib = "yes" if deck.uses_biblatex else "no"
        print(f"{deck.name}  [{tag}]  version-override={ver}  biblatex={bib}"
              f"  chapters={len(deck.chapters)}")
        for ch in deck.chapters:
            print(f"    {ch.order:02d}. {ch.title}  -> {ch.slug}")
