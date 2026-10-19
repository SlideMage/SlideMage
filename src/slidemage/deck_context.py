# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Slides that need the rest of the deck, rendered in a deck's context (docs/plans/deck-context-preview.md).

A contents slide, a chapter agenda, a slide that prints the current section or refers to another slide looks
wrong (empty, or numbered 1) when it is typeset alone. Such slides, found by `reasons()` from their own text,
are rendered in one of two ways:

- **in the deck** (mode "deck"): through partial_compile, on top of the auxiliary files of the last whole-deck
  compile of that version (kept with its compile record): the real contents, agendas, section, numbers, links.
  It needs that compile and the deck unchanged before the slide, as a page compile does;
- **with a skeleton** (mode "skeleton"): the deck's `\section`/`\subsection` commands before the slide, then the
  slide, then the rest of them (so a contents slide lists every section), and for every other slide of the
  version the record that `\SMChapterAgenda` reads (`\setSlideID` + `\SMAgendaTitle{<title>}`, no frame), with the
  titles read from the slide files. Section page numbers are not the real ones; the Preview says so.

`mode_of(pdf)` tells which of the two made a PDF (None: a normal single-slide render).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import compile_records, deck_language, partial_compile
from .compiler import CancelToken, CompileJob
from .deck_scan import Deck
from .project import ProjectContext
from .tex_source import is_commented

DECK, SKELETON = "deck", "skeleton"
REASON_TEXT = {
    "contents": "a table of contents or agenda",
    "section": "the current section",
    "numbers": "frame or page numbers",
    "references": "a reference to another place of the deck",
}

# What a slide's own text uses that only means something inside a deck. The footer's frame number is not here:
# every slide has it, and the frame number line of the preview wrapper gives it.
_REASON_PATTERNS = (
    ("contents", re.compile(r"\\(?:tableofcontents|SMDeckAgenda|SMChapterAgenda|SMSubsectionAgenda)(?![A-Za-z@])")),
    ("section", re.compile(r"\\(?:insertsection|insertsubsection|insertsectionhead|insertsubsectionhead|"
                           r"insertsectionnumber|insertsubsectionnumber|secname|subsecname)(?![A-Za-z@])"
                           r"|\\begin\s*\{sectionframe\}")),
    ("numbers", re.compile(r"\\(?:inserttotalframenumber|insertpresentationendpage|insertframenumber|"
                           r"insertpagenumber|progressstrip)(?![A-Za-z@])")),
    ("references", re.compile(r"\\(?:ref|pageref|cref|Cref|autoref|nameref|hyperlink)(?![A-Za-z@])")),
)

_FRAME_BEGIN_RE = re.compile(r"\\begin\s*\{(?:[A-Za-z]*frame)\}")
_TITLE_COMMAND_RE = re.compile(r"\\(?:frametitle|SMAgendaTitle)(?![A-Za-z@])")
_SECTION_COMMAND_RE = re.compile(r"^[ \t]*\\(?:sub)?section\*?[ \t]*(?:\[[^\]\n]*\])?[ \t]*\{", re.MULTILINE)
FLUSH_FRAME = "\\begin{frame}[plain]\\end{frame}\n"      # ships the sections written after the slide

_cache: dict[tuple, tuple[str, ...]] = {}
_modes: OrderedDict[str, str] = OrderedDict()
_modes_lock = threading.Lock()


def reasons(text: str) -> tuple[str, ...]:
    """Why the slide whose source is `text` needs the deck around it, as keys of REASON_TEXT (empty: it does not)."""
    from .latex_lint import _mask_comments_and_verbatim

    masked = _mask_comments_and_verbatim(text)[0]
    return tuple(name for name, pattern in _REASON_PATTERNS if pattern.search(masked))


def reasons_for_file(path: Path) -> tuple[str, ...]:
    """reasons() of a slide file, remembered until the file changes."""
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return ()
    found = _cache.get(stamp)
    if found is None:
        try:
            found = reasons(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            found = ()
        _cache[stamp] = found
        while len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
    return found


def describe(found: tuple[str, ...]) -> str:
    return ", ".join(REASON_TEXT[name] for name in found)


# -- which of the two renders made a PDF --------------------------------------------------------------

def remember_mode(pdf: Path, mode: str) -> None:
    with _modes_lock:
        _modes[str(pdf)] = mode
        while len(_modes) > 64:
            _modes.popitem(last=False)


def mode_of(pdf: Optional[Path]) -> Optional[str]:
    with _modes_lock:
        return _modes.get(str(pdf)) if pdf is not None else None


# -- titles ---------------------------------------------------------------------------------------

def _group(text: str, start: int) -> Optional[tuple[str, int]]:
    """The brace group whose `{` is at `start`: (its content, the index after its `}`); None if it never closes."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None


def frame_title(text: str) -> Optional[str]:
    r"""The title a slide gives its first frame: the first brace argument after `\begin{...frame}` (and its
    options), `\frametitle{}` or `\SMAgendaTitle{}`, whichever comes first; None when there is none."""
    from .latex_lint import _mask_comments_and_verbatim

    masked = _mask_comments_and_verbatim(text)[0]
    found = sorted([(m.end(), "begin") for m in _FRAME_BEGIN_RE.finditer(masked)]
                   + [(m.end(), "title") for m in _TITLE_COMMAND_RE.finditer(masked)])
    for end, kind in found:
        i = end
        while True:
            match = re.compile(r"\s*(?:\[[^\]]*\]|<[^>]*>)").match(masked, i) if kind == "begin" else None
            if match is None:
                break
            i = match.end()
        match = re.compile(r"\s*\{").match(masked, i)
        if match is None:
            continue
        group = _group(masked, match.end() - 1)
        if group is not None and group[0].strip():
            return " ".join(group[0].split())
    return None


def _defines_macros_of(title: str, text: str) -> bool:
    """Whether `title` uses a macro that the slide file defines itself (the skeleton cannot know what it means)."""
    for name in set(re.findall(r"\\([A-Za-z@]+)", title)):
        if re.search(r"\\(?:newcommand|renewcommand|providecommand|def|gdef|edef|xdef|NewDocumentCommand)"
                     r"\s*\*?\s*\{?\s*\\" + re.escape(name) + r"(?![A-Za-z@])", text):
            return True
    return False


def aux_titles(aux: Path, jobname: str) -> dict[str, str]:
    r"""{slide id: title} from `\SMAgendaEntryTitle{id}{title}` lines of a whole-deck compile's .aux (empty if
    there is none): what the chapter agendas of that compile showed, even if the deck changed since."""
    try:
        text = (aux / f"{jobname}.aux").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    titles: dict[str, str] = {}
    for match in re.finditer(r"\\SMAgendaEntryTitle\{([^{}]*)\}\{", text):
        group = _group(text, match.end() - 1)
        if group is not None:
            titles.setdefault(match.group(1).lower(), group[0])
    return titles


# -- the skeleton ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Skeleton:
    before: str
    after: str


def _record(ctx: ProjectContext, call, fallback: dict[str, str]) -> str:
    title: Optional[str] = None
    try:
        text = (ctx.slides_dir / call.source_filename).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    if text:
        title = frame_title(text)
        if title is not None and _defines_macros_of(title, text):
            title = fallback.get(call.id.lower())
    out = f"\\setSlideID{{{call.id_slug}}}"
    if title:
        out += f"\\SMAgendaTitle{{{title}}}"
    return out + "\n"


def skeleton(ctx: ProjectContext, deck: Deck, position: int, id_slug: str, view: str, language: str,
             titles: Optional[dict[str, str]] = None) -> Optional[Skeleton]:
    r"""The deck's `\section`/`\subsection` commands and agenda records around its `position`-th slide call (1-based,
    as the slide list counts), or None if that call is not `id_slug` (the deck changed). `titles`: what to use for
    a title built from a macro the slide defines itself (the last compile's titles)."""
    slots = deck_language.deck_slots(ctx, deck, language)
    if not 1 <= position <= len(slots) or slots[position - 1].call.id_slug != id_slug:
        return None
    chosen = slots[position - 1].original
    text = deck.text
    begin = deck.preamble_end or 0
    end_match = re.search(r"\\end\{document\}", text[begin:])
    limit = begin + end_match.start() if end_match else len(text)
    events: list[tuple[int, str]] = []
    for match in _SECTION_COMMAND_RE.finditer(text, begin, limit):
        if is_commented(text, match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))):
            continue
        group = _group(text, match.end() - 1)
        if group is not None:
            command = text[match.start():group[1]].strip()
            events.append((match.start(), command + "\n"))
    fallback = titles or {}
    for slot in slots:
        if slot.original.call_start == chosen.call_start:
            continue
        if slot.call.included_in(view):
            events.append((slot.original.call_start, _record(ctx, slot.call, fallback)))
    events.sort(key=lambda event: event[0])
    before = "".join(chunk for offset, chunk in events if offset < chosen.call_start)
    after = "".join(chunk for offset, chunk in events if offset > chosen.call_start)
    return Skeleton(before, after + FLUSH_FRAME if after else "")


def drop_last_page(pdf: Path) -> None:
    """Take the flush frame's page off the end of `pdf` (what the skeleton added after the slide)."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        if len(doc) < 2:
            return
        doc.delete_page(len(doc) - 1)
        temporary = pdf.with_suffix(".trimmed.pdf")
        doc.save(temporary)
    temporary.replace(pdf)


# -- rendering ----------------------------------------------------------------------------------

def render_in_deck(ctx: ProjectContext, deck: Deck, view: str, slide_id: str, id_slug: str, log: Callable[[str], None],
                   cancel: Optional[CancelToken] = None, *,
                   all_steps: bool = False, language: Optional[str] = None) -> Optional[Path]:
    """The slide `id_slug` of `deck` typeset by a page compile in the deck's last whole-deck compile of `view`:
    a PDF of its own pages (in a scratch folder), or None when that is not possible (no usable compile, the deck
    changed before the slide, the slide is not in that compile)."""
    from . import slide_preview

    job = CompileJob(deck, view if deck.supports_version else None, None,
                     language=language)
    try:
        frames = partial_compile.frames_for_slides(ctx, job, [slide_id])
        if not frames:
            return None
        the_plan = partial_compile.plan(ctx, job, frames)
        if all_steps:
            the_plan.extra_lines = slide_preview._overlay_line(None, True)
        output = partial_compile.run(the_plan, log, cancel)
    except partial_compile.PartialError as exc:
        log(f"    (no deck context render: {exc})")
        return None
    try:
        pages = partial_compile.new_pages_of(the_plan, output)
        wanted = [index for group in pages for index in group]
        if not wanted:
            return None
        folder = Path(tempfile.mkdtemp(prefix="slidemage_preview_"))
        target = folder / f"{id_slug}-in-{job.jobname}.pdf"
        partial_compile.write_pages(output.pdf, wanted, target)
        remember_mode(target, DECK)
        return target
    finally:
        shutil.rmtree(output.build_dir, ignore_errors=True)


def aux_titles_for(ctx: ProjectContext, deck: Deck, view: str, language: Optional[str] = None) -> dict[str, str]:
    job = CompileJob(deck, view if deck.supports_version else None, None, language=language)
    return aux_titles(compile_records.aux_dir(ctx.build_dir, job.jobname), job.jobname)
