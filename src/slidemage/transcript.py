"""Generate an accessible companion transcript for a deck (ALT_TEXT_NOTES.md,
phase 4).

Markdown is the source format, HTML the delivered one. Generated on demand and
never committed: everything it needs already lives in the deck file, the slide
files, and their `%%ALT` blocks.

Three requirements from the design, each of which is a correctness trap:

1. **Resolve the deck version exactly as the PDF compile does.** A transcript
   that lists a slide the student's PDF doesn't have -- or omits one it does --
   is worse than no transcript. The rules are mirrored from
   Slidemaster_preamble_base.tex and spelled out in `_VERSION_RULES` below.
2. **Never emit `\\note{}` content.** Those are instructor notes.
3. **during-course and after-course only.** The instructor deck's multi-page
   `\\pause` builds are a separate, unsolved problem (see README.md's
   accessibility section); generating one would silently produce a transcript
   of a deck no student has.
"""
from __future__ import annotations

import html as _html
import itertools
import re
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import alt_blocks, alt_images, bibliography, deck_language, deck_scan
from .deck_scan import PROJECT_ROOT, Deck
from .tex_source import COMMENT_RE

SLIDES_DIR = PROJECT_ROOT / "slides"

VERSION_DURING = "during-course"
VERSION_AFTER = "after-course"
VERSION_INSTRUCTOR = "instructor"

# Only the student versions are generated. See the module docstring.
STUDENT_VERSIONS = (VERSION_DURING, VERSION_AFTER)

VERSION_LABELS = {
    VERSION_DURING: "during-course version",
    VERSION_AFTER: "after-course version",
}
VERSION_LABELS_DE = {
    VERSION_DURING: "Semesterbegleitende Version",
    VERSION_AFTER: "Version nach Kursende",
}
_VERSION_LABELS_BY_LANGUAGE = {"en": VERSION_LABELS, "de": VERSION_LABELS_DE}

_ALL_VERSIONS = (VERSION_INSTRUCTOR, VERSION_DURING, VERSION_AFTER)

# How each slide-inclusion command behaves, mirrored from the preamble:
#
#   \slide{ID}                     always included
#   \slidefinal{ID}                always included (final overlay state)
#   \slideversion{ID}{v}           always included, from slides/ID-v<v>.tex
#   \omitslide{ID}                 instructor only -- excluded from students
#   \omitslideversion{ID}{v}       instructor only
#   \conditionalslide[vs]{ID}      included iff the version is in [vs]
#
# Every one of them advances the frame counter even when skipped, so slide
# numbering matches the PDF across versions -- which is the whole reason a
# transcript can say "slide 34" and be believed.
# \slidestep{ID}[vs]{steps} (2026-09-20) is a \conditionalslide{} that also restricts the
# reveal steps. Its [vs] follows the id, so it has its own alternative. Unlike every
# other command it does NOT advance the frame counter when the version is not in [vs]:
# two \slidestep calls at one position are alternatives, exactly one of which exists
# in any given deck version (see \slidestep in Slidemaster_preamble_base.tex).
_SECTION_RE = re.compile(r"\\section\*?\s*(?:\[[^\]]*\])?\s*\{")
_DECK_LANGUAGE_RE = re.compile(r"\\decklanguage\s*\[([^\]]*)\]")

# UI strings that need to read naturally in the deck's own language
# (2026-08-24) -- a German deck's transcript should not show English
# scaffolding around German slide content. Only strings *transcript.py
# itself* writes are here; a slide's own body/title/source text is never
# translated by this module at all -- it's already in whichever language
# that slide's own file is written in (see LANGUAGE_NOTES.md: a
# German-content slide is a separate file, not a translated field), so
# only the alt_images-sourced per-image fields (short/long/takeaway/
# source) and this module's own scaffolding need a language dimension.
STRINGS = {
    "en": {
        "transcript_title": "{deck} — accessible transcript",
        "deck_label": "**Deck:** {deck} ({version})  ",
        "slides_label": "**Slides:** {n} of {total} (the rest are not in this deck version)  ",
        "intro": (
            "This transcript reproduces the text of every slide together with a "
            "written description of every chart, screenshot and photograph. Purely "
            "decorative images are noted as such and not described. Slide numbers "
            "match the PDF."
        ),
        "undescribed_warning": (
            "> ⚠ **{n} slide(s) contain an image that has not been described "
            "yet.** Those points are marked in place below."
        ),
        "missing_files_warning": "> ⚠ Could not read {n} slide file(s): {files}.",
        "summary_label": "**Summary.**",
        "decorative_image": (
            "*[Decorative image ({ref}). It carries no information beyond the "
            "slide text and is not described further.]*"
        ),
        "no_description": (
            "> ⚠ **No description yet** for `{ref}`. This image has not been "
            "described, so its content is missing from this transcript."
        ),
        "figure_label": "### Figure: {caption}",
        "short_description_label": "**Short description.**",
        "full_description_label": "**Full description.**",
        "takeaway_label": "**Takeaway.**",
        "chapter_agenda_label": "**This chapter's slides:**",
        "chapter_agenda_item": "{title} (slide {n})",
    },
    "de": {
        "transcript_title": "{deck} — barrierefreies Transkript",
        "deck_label": "**Deck:** {deck} ({version})  ",
        "slides_label": "**Folien:** {n} von {total} (die restlichen sind nicht in dieser Deck-Version enthalten)  ",
        "intro": (
            "Dieses Transkript gibt den Text jeder Folie zusammen mit einer "
            "schriftlichen Beschreibung jedes Diagramms, Screenshots und Fotos "
            "wieder. Rein dekorative Bilder werden als solche gekennzeichnet und "
            "nicht weiter beschrieben. Die Foliennummern entsprechen dem PDF."
        ),
        "undescribed_warning": (
            "> ⚠ **{n} Folie(n) enthalten ein Bild, das noch nicht beschrieben "
            "wurde.** Diese Stellen sind unten entsprechend markiert."
        ),
        "missing_files_warning": "> ⚠ {n} Foliendatei(en) konnten nicht gelesen werden: {files}.",
        "summary_label": "**Zusammenfassung.**",
        "decorative_image": (
            "*[Dekoratives Bild ({ref}). Es enthält keine Informationen über den "
            "Folientext hinaus und wird nicht weiter beschrieben.]*"
        ),
        "no_description": (
            "> ⚠ **Noch keine Beschreibung** für `{ref}`. Dieses Bild wurde noch "
            "nicht beschrieben, sein Inhalt fehlt daher in diesem Transkript."
        ),
        "figure_label": "### Abbildung: {caption}",
        "short_description_label": "**Kurzbeschreibung.**",
        "full_description_label": "**Vollständige Beschreibung.**",
        "takeaway_label": "**Erkenntnis.**",
        "chapter_agenda_label": "**Die Folien dieses Kapitels:**",
        "chapter_agenda_item": "{title} (Folie {n})",
    },
}

# \deckonly / \deckuncover / \deckvisible share one signature:
#     \deckXXX<overlay>[versions]{content}
# both optional parts defaulting to <1-> and all three versions.
_DECK_COND_RE = re.compile(
    r"\\(?:deckonly|deckuncover|deckvisible)\s*(?:<[^>]*>)?\s*(?:\[(?P<versions>[^\]]*)\])?\s*(?=\{)"
)
# \deckreveal[*][step]{content}: absent in during-course, shown otherwise.
# \deckrevealfinal[*][step]{content}: shown in every student version.
_DECK_REVEAL_RE = re.compile(r"\\deckreveal(?P<final>final)?(?![a-zA-Z])\s*\*?\s*(?:\[[^\]]*\])?\s*(?=\{)")
# \deckitem<spec>: a plain \item in every student version.
_DECK_ITEM_RE = re.compile(r"\\deckitem(?![a-zA-Z])\s*(?:<[^>]*>)?")
# \ifSMInstructorVersion / \ifSMDuringCourseVersion / \ifSMAfterCourseVersion
_VERSION_IF_RE = re.compile(r"\\ifSM(Instructor|DuringCourse|AfterCourse)Version(?![a-zA-Z])")
_TEX_IF_TOKEN_RE = re.compile(r"\\(if[a-zA-Z@]*|else|fi)(?![a-zA-Z@])")
_VERSION_OF_IF = {"Instructor": VERSION_INSTRUCTOR, "DuringCourse": VERSION_DURING,
                  "AfterCourse": VERSION_AFTER}


@dataclass
class DeckSlide:
    """One slide as it appears in a resolved deck."""

    number: int          # frame number, matching the compiled PDF
    slide_id: str
    path: Path
    included: bool       # False = counted for numbering but not in this version
    chapter: int = 0     # how many \section{}s come before it (0 = front matter)


@dataclass
class TranscriptImage:
    reference: str
    role: str
    short: str = ""
    long: str = ""
    takeaway: str = ""
    described: bool = False


@dataclass
class TranscriptSlide:
    number: int
    slide_id: str
    title: str
    body: str
    source: str
    images: list[TranscriptImage] = field(default_factory=list)
    missing_description: bool = False
    # Free text authored in the slide-source editor (not tied to any one
    # image), shown before the slide's own body -- see alt_images.SlideNotes.
    summary: str = ""
    # \SMAgendaTitle{...}: how chapter agendas list this slide
    agenda_title: str = ""
    # the body holds \SMChapterAgenda's placeholder (generate() fills it in)
    chapter_agenda: bool = False


# --------------------------------------------------------------------------
# Deck resolution
# --------------------------------------------------------------------------

def _versions_from(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts


def deck_language_of(deck_text: str) -> str:
    """"en"/"de" from the deck's \\decklanguage[...]; always a concrete
    value, never None: language is fixed per deck
    (not a per-compile-run choice the way version is -- see
    LANGUAGE_NOTES.md), so "\\decklanguage[\\decklanguageoverride]" (the
    macro-argument case, only ever used for SlideMage's own one-off
    render preview, never a real deck's own hardcoded line) falling
    through to the preamble's own "en" default is the right answer here,
    the same way it would be at actual compile time for any deck that
    doesn't set \\decklanguageoverride itself.

    This deliberately scans every \\decklanguage[...] occurrence
    and picks the first *literal* one: every real deck's own
    \\ifdefined\\decklanguageoverride ... \\else \\decklanguage[en] ... \\fi
    boilerplate (see README.md/LANGUAGE_NOTES.md) puts the macro-argument
    branch textually *first*, so a plain first-match .search() would
    always see "\\decklanguageoverride" and fall through to the "en"
    default for every real deck, including ones whose actual hardcoded
    language is "de" -- caught by testing against a real deck file, not
    assumed."""
    text = COMMENT_RE.sub("", deck_text)
    for match in _DECK_LANGUAGE_RE.finditer(text):
        value = match.group(1).strip()
        if value and not value.startswith("\\"):
            return value if value in STRINGS else "en"
    return "en"


def _document_body(text: str) -> str:
    """Return a document's body, or all of a body-only fragment.

    Deck preambles often define helper macros whose replacement text contains
    slide commands. Restricting resolution to the document body prevents those
    definitions from being mistaken for actual slides.
    """
    document_start = None
    document_end = None
    for name, start, command_end in alt_blocks.iter_tex_commands(text):
        if name not in {"begin", "end"}:
            continue
        cursor = command_end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        environment, after = alt_blocks.braced_argument(text, cursor)
        if after == cursor or environment.strip() != "document":
            continue
        if name == "begin" and document_start is None:
            document_start = after
        elif name == "end" and document_start is not None:
            document_end = start
            break
    if document_start is None:
        return text
    return text[document_start:document_end]


def _resolve_literal_include(token: str, deck_dir: Path) -> Path | None:
    """Find a literal TeX include from the compiler working directory, then project."""
    requested = Path(token)
    names = [requested]
    if not requested.suffix:
        names = [requested.with_suffix(".tex"), requested]

    if requested.is_absolute():
        bases = [Path()]
    else:
        bases = [deck_dir, PROJECT_ROOT]

    seen: set[Path] = set()
    for base in bases:
        for name in names:
            candidate = name if name.is_absolute() else base / name
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_file():
                return candidate.resolve()
    return None


def _expand_literal_includes(
    source: str,
    source_path: Path,
    deck_dir: Path,
    active_paths: tuple[Path, ...],
) -> str:
    """Inline literal body includes in order, with stack-based cycle checks."""
    clean = COMMENT_RE.sub("", source)
    body = _document_body(clean)
    # Instructor notes may contain arbitrary TeX. They are not deck-level
    # includes and must not affect slide numbering or trigger file lookups.
    body = alt_blocks.extract_note_calls(body)[0]

    parts: list[str] = []
    copied_through = 0
    for name, start, command_end in alt_blocks.iter_tex_commands(body):
        if name not in {"input", "include"} or start < copied_through:
            continue
        cursor = command_end
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        token_text, after = alt_blocks.braced_argument(body, cursor)
        if after == cursor:
            continue
        token = token_text.strip()
        # Macro-valued paths require TeX expansion; only resolve literal paths.
        if not token or "\\" in token or "#" in token:
            continue

        include_path = _resolve_literal_include(token, deck_dir)
        if include_path is None:
            raise FileNotFoundError(
                f"Literal deck include {token!r} from {source_path} was not found."
            )
        if include_path in active_paths:
            chain = " -> ".join(str(path) for path in (*active_paths, include_path))
            raise ValueError(f"Deck include cycle detected: {chain}")

        included_text = include_path.read_text(encoding="utf-8")
        expanded = _expand_literal_includes(
            included_text, include_path, deck_dir, (*active_paths, include_path)
        )
        parts.append(body[copied_through:start])
        parts.append(expanded)
        copied_through = after

    parts.append(body[copied_through:])
    return "".join(parts)


def resolve_deck(deck_path: Path, version: str) -> list[DeckSlide]:
    """Every slide the deck contains, in order, flagged for this version.

    Excluded slides are kept in the list with `included=False` rather than
    dropped, because they still advance the frame counter in the compiled PDF
    -- so the numbers a transcript prints keep matching the numbers a student
    sees.
    """
    deck = deck_scan.read_deck(deck_path)
    language = deck_language_of(deck.text).upper()
    # Preamble definitions and text after the document are not slide placements.
    body = _document_body(deck.text)
    deck = replace(deck, text=body, preamble_end=0)
    deck, _dependencies = deck_language.expand_fragments(deck, strict_includes=True)
    slides: list[DeckSlide] = []
    number = 0

    for slot in deck_language.deck_slots(deck, language):
        call = slot.call
        included = call.included_in(version)
        if call.macro == "slidestep" and not included:
            continue
        number += 1
        slides.append(DeckSlide(
            number=number,
            slide_id=call.id,
            path=SLIDES_DIR / call.source_filename,
            included=included,
            chapter=call.chapter.order if call.chapter else 0,
        ))
    return slides


def _resolve_version_ifs(text: str, version: str) -> str:
    """Keep the branch of \\ifgotham<X>Version ... [\\else ...] \\fi that
    `version` compiles, drop the other one. Nested \\if...\\fi pairs are
    counted so an inner \\else/\\fi doesn't end the outer conditional.
    Before this (2026-09-30) both branches reached the transcript, so a
    slide writing each item once per branch listed every item twice."""
    while True:
        m = _VERSION_IF_RE.search(text)
        if m is None:
            return text
        depth, else_at, fi_at = 0, None, None
        for tok in _TEX_IF_TOKEN_RE.finditer(text, m.end()):
            word = tok.group(1)
            if word.startswith("if"):
                depth += 1
            elif word == "else" and depth == 0 and else_at is None:
                else_at = tok
            elif word == "fi":
                if depth == 0:
                    fi_at = tok
                    break
                depth -= 1
        if fi_at is None:                        # unbalanced; leave the rest alone
            return text[:m.start()] + text[m.end():]
        true_part = text[m.end():else_at.start() if else_at else fi_at.start()]
        false_part = text[else_at.end():fi_at.start()] if else_at else ""
        keep = true_part if _VERSION_OF_IF[m.group(1)] == version else false_part
        text = text[:m.start()] + keep + text[fi_at.end():]


def _resolve_deck_reveals(text: str, version: str) -> str:
    """\\deckitem -> \\item; \\deckreveal/\\deckrevealfinal (starred or not)
    -> their content. \\deckreveal's content stays in the during-course
    transcript too, although that PDF omits it -- the policy pinned by
    tests/test_transcript_policy.py; this only removes the macro and its
    [step] cleanly (they used to leave "[2]" behind)."""
    text = _DECK_ITEM_RE.sub(r"\\item", text)
    out: list[str] = []
    index = 0
    while True:
        match = _DECK_REVEAL_RE.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:match.start()])
        content, after = alt_blocks.braced_argument(text, match.end())
        if after == match.end():
            out.append(text[match.start():])
            return "".join(out)
        out.append(_resolve_deck_reveals(content, version))
        index = after


def resolve_deck_conditionals(text: str, version: str) -> str:
    """Apply `\\deckonly` / `\\deckuncover` / `\\deckvisible` for one version.

    Keeps the braced content when the version qualifies and drops it entirely
    when it does not.

    The instructor short-circuit in the preamble (`\\ifSMInstructorVersion`
    renders the content whatever `[versions]` says) is reproduced here for
    completeness, even though only student versions are ever generated -- so
    this function stays correct if that ever changes.
    """
    text = _resolve_version_ifs(text, version)
    text = _resolve_deck_reveals(text, version)
    out: list[str] = []
    index = 0
    while True:
        match = _DECK_COND_RE.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)

        out.append(text[index:match.start()])
        content, after = alt_blocks.braced_argument(text, match.end())
        if after == match.end():                 # unbalanced; bail out safely
            out.append(text[match.start():])
            return "".join(out)

        versions = _versions_from(match.group("versions"), _ALL_VERSIONS)
        keep = version == VERSION_INSTRUCTOR or version in versions
        if keep:
            # Recurse: the content may itself contain conditionals.
            out.append(resolve_deck_conditionals(content, version))
        index = after


# --------------------------------------------------------------------------
# LaTeX to Markdown
# --------------------------------------------------------------------------

# Environments whose content is layout only -- dropped whole.
#
# `tikzpicture` is deliberately NOT in this list. 66 of the 173 slides that
# use one put real slide text inside it -- axis labels like "Profit/Loss",
# "Aircraft purchase", "Total position", and on several slides an entire
# info block or table nested in a node. Dropping the environment wholesale
# lost that text from the student's transcript, silently. Node *labels* are
# extracted and converted instead; the drawing syntax around them is discarded.
_DROP_ENVIRONMENTS = ("scope",)

# The image itself is described in its own section, from the %%ALT block.
# Left in the body it flattens to noise like "[height=0.78]media/chart-x.png".
_GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")

# \vbox to 0pt{...} / \hbox to 3cm{...} -- TeX's box-glue idiom (a bare "to"
# keyword between the box command and a dimension, no braces). Stripped as
# one unit, opening brace included: leaving \vbox and the dimension to be
# consumed separately (as they would be by the generic macro-name strip and
# _DIMENSION_RE below) still leaves the bare word "to" behind with nothing
# left to remove it -- unlike every other stripped command, it has no
# backslash and isn't a number, so it read as stray text in the transcript
# (used in 149 slides for icon/rule positioning; caught 2026-08-14 in
# #workdeck's transcript, where it showed up as a bare "to" opening two
# slide bodies).
_BOX_TO_RE = re.compile(
    r"\\[vh]box\s+to\s*[-+]?\d*\.?\d+\s*(?:pt|cm|mm|em|ex|in|bp|sp)\b\s*\{")

# Bare TeX dimensions left behind by struts and spacing commands (\vbox to
# 0pt, \vspace{9.58pt}) once the macro itself is stripped. They are layout,
# and read as stray numbers in a transcript.
_DIMENSION_RE = re.compile(
    r"(?<![\w.])[-+]?\d*\.?\d+\s*(?:pt|cm|mm|em|ex|in|bp|sp)\b")

# \conditionalpause[versions] -- \pause, gated to specific deck versions
# (Slidemaster_preamble_base.tex's own doc comment: "Usage:
# \conditionalpause[instructor,during-course]"). Its optional argument has no
# dedicated consumer the way \includegraphics's does, so the generic
# backslash-command strip below removes only "\conditionalpause" and leaves
# the bracket group ("[instructor]") behind as stray text -- caught
# 2026-08-14 in #workdeck's transcript (used in 51 slides).
_CONDITIONAL_PAUSE_RE = re.compile(r"\\conditionalpause\s*(?:\[[^\]]*\])?")
# \SMTikzmark{name} is an invisible anchor; \SMTikzword{name}{text}
# keeps its text. Only the name goes -- the generic strip left it behind as a
# stray word ("a \SMTikzmark{x}mark" read "a xmark").
_TIKZ_MARK_NAME_RE = re.compile(r"\\SMTikz(?:mark|word)\s*\{[^{}]*\}")
# \setbeamertemplate{itemize subitem}{...}, \setbeamerfont{...}{...},
# \setbeamercolor{...}{...} are styling: the generic strip left the template
# name behind as text ("itemize subitem"). One level of nested braces in the
# value ({\SMBulletEllipsis}, {size=\small}).
_SETBEAMER_RE = re.compile(
    r"\\setbeamer(?:template|font|color|covered)\*?\s*\{[^{}]*\}"
    r"(?:\s*\[[^\]]*\])?(?:\s*\{(?:[^{}]|\{[^{}]*\})*\})?")
# The project's ellipsis bullets (\item[\SMBulletEllipsis]) and \ldots.
_ELLIPSIS_RE = re.compile(
    r"\\(?:SMBulletEllipsis(?:Script)?|ldots|dots|textellipsis)(?![a-zA-Z])(?:\{\})?")
# "\ " (control space) is just a space; not the "\\" of a line break before one
_CONTROL_SPACE_RE = re.compile(r"(?<!\\)((?:\\\\)*)\\ ")
# Environments that only wrap; their content is kept, the wrapper discarded.
_UNWRAP_ENVIRONMENTS = ("minipage", "center", "column", "columns", "figure",
                        "table", "adjustbox", "besidefigure")
# Beamer-style blocks: rendered as a titled quote so the label survives.
_BLOCK_ENVIRONMENTS = ("definitionblock", "infoblock", "gothamfloatinginfoblock",
                       "gothamfloatingexampleblock", "gothamfloatingblock",
                       "alertblock", "exampleblock", "referenceblock", "block")
_LIST_ENVIRONMENTS = {
    "itemize": "-",
    "gothamalphaitemize": "-",
    "enumerate": "1.",
}

_ENV_OPEN_RE_CACHE: dict[str, re.Pattern] = {}


# Environments taking a mandatory argument after \begin{...}: minipage's
# width, column's width. Without consuming it the argument leaks into the
# transcript as stray text ("0.42" from \begin{minipage}{0.42\textwidth}).
# besidefigure's argument is its image path (described in its own section);
# tikzillustration's is the illustration's ID.
_MANDATORY_ARG_ENVIRONMENTS = ("minipage", "column", "adjustbox", "besidefigure",
                               "tikzillustration")


def _env_open_re(name: str) -> re.Pattern:
    if name not in _ENV_OPEN_RE_CACHE:
        tail = r"\s*\{[^{}]*\}" if name in _MANDATORY_ARG_ENVIRONMENTS else ""
        _ENV_OPEN_RE_CACHE[name] = re.compile(
            r"\\begin\{" + re.escape(name) + r"\}\s*(?:<[^>]*>)?\s*(?:\[[^\]]*\])?"
            + tail
        )
    return _ENV_OPEN_RE_CACHE[name]


def _find_environment(text: str, name: str, start: int = 0):
    """(open_start, body_start, body_end, end_stop) of the first `name` env.

    Nesting-aware: an `itemize` inside an `itemize` matches its own `\\end`.
    Returns None when there is no complete occurrence.
    """
    opener = _env_open_re(name)
    match = opener.search(text, start)
    if match is None:
        return None
    close = "\\end{" + name + "}"
    depth = 1
    cursor = match.end()
    while cursor < len(text):
        next_open = opener.search(text, cursor)
        next_close = text.find(close, cursor)
        if next_close == -1:
            return None
        if next_open is not None and next_open.start() < next_close:
            depth += 1
            cursor = next_open.end()
            continue
        depth -= 1
        if depth == 0:
            return match.start(), match.end(), next_close, next_close + len(close)
        cursor = next_close + len(close)
    return None


def _transform_environments(text: str, name: str, handler) -> str:
    """Replace every `name` environment via handler(body) -> str."""
    guard = 0
    while guard < 500:                      # cheap infinite-loop insurance
        guard += 1
        found = _find_environment(text, name)
        if found is None:
            return text
        open_start, body_start, body_end, end_stop = found
        replacement = handler(text[body_start:body_end])
        text = text[:open_start] + replacement + text[end_stop:]
    return text


_ITEM_SPLIT_RE = re.compile(r"\\item\b\s*(?:<[^>]*>)?")


def _render_list(body: str, marker: str, depth: int) -> str:
    # Convert nested list environments FIRST and park them in placeholders.
    # Splitting on \item otherwise tears a nested list apart -- its own \items
    # become items of the outer list and its \begin/\end survive as the stray
    # word "itemize" in the output.
    parked: list[str] = []

    def park(inner: str, m=marker) -> str:
        parked.append("\n" + _render_list(inner, m, depth + 1) + "\n")
        return f"\x00{len(parked) - 1}\x00"

    for nested_name, nested_marker in _LIST_ENVIRONMENTS.items():
        body = _transform_environments(
            body, nested_name,
            lambda inner, m=nested_marker: park(inner, m))

    items = _ITEM_SPLIT_RE.split(body)
    lead = items[0].strip()
    lines: list[str] = []
    if lead:                                # text before the first \item
        rendered_lead = _inline_markdown(lead)
        for slot, text in enumerate(parked):
            rendered_lead = rendered_lead.replace(f"\x00{slot}\x00", text)
        lines.append(rendered_lead)
    indent = "  " * depth
    for number, raw in enumerate(items[1:], start=1):
        # \item[label]: the label leads the item's text (it used to be left
        # behind as "[]" once its macro was stripped).
        label = ""
        stripped = raw.lstrip()
        if stripped.startswith("["):
            close = stripped.find("]")
            if close != -1:
                label = _inline_markdown(stripped[1:close]).strip()
                raw = stripped[close + 1:]
        rendered = _convert_body(raw, depth + 1).strip()
        if label and rendered:
            rendered = f"{label} {rendered}"
        for slot, text in enumerate(parked):
            rendered = rendered.replace(f"\x00{slot}\x00", text)
        if not rendered:
            continue
        bullet = f"{number}." if marker == "1." else "-"
        first, _, rest = rendered.partition("\n")
        lines.append(f"{indent}{bullet} {first}")
        for line in rest.splitlines():
            lines.append(f"{indent}  {line}" if line.strip() else "")
    return "\n".join(lines)


def _skip_optional_argument(body: str) -> str:
    """Drop a leading [...] option (\\begin{gothamtable}[gap=12pt]{...},
    \\begin{gothamfloatinginfoblock}[top=0pt]{...}{...})."""
    stripped = body.lstrip()
    if stripped.startswith("["):
        close = stripped.find("]")
        if close > 0:
            return stripped[close + 1:]
    return body


def _render_block(body: str, label: str) -> str:
    """A beamer block becomes a titled Markdown quote."""
    title = ""
    stripped = _skip_optional_argument(body).lstrip()
    if label.startswith("gothamfloating") and stripped.startswith("{"):
        # the floating variants take the block's width first: {6cm}{Title}
        _width, after = alt_blocks.braced_argument(stripped, 0)
        if after > 0:
            stripped = stripped[after:].lstrip()
    body = stripped
    if stripped.startswith("{"):
        title, after = alt_blocks.braced_argument(stripped, 0)
        if after > 0:
            body = stripped[after:]
    heading = _inline_markdown(title).strip() or label.replace("block", "").title()
    inner = _convert_body(body, 0).strip()
    quoted = "\n".join(f"> {line}" if line.strip() else ">"
                       for line in inner.splitlines())
    return f"\n> **{heading}**\n>\n{quoted}\n"


# How many mandatory arguments each table environment takes after \begin{}.
# Consumed by count rather than by matching what a column spec "looks like":
# a spec may contain macros (`{@{}l<{\hspace{12pt}}c@{}}` on slide btg), and
# any character-class pattern that admits those also admits a real first
# table cell. The signature is known, so use it.
_TABLE_SPEC_ARGS = {"gothamtable": 1, "tabular": 1, "tabularx": 2}


def _strip_column_spec(body: str, count: int) -> str:
    """Drop a table environment's leading option and mandatory argument(s)."""
    body = _skip_optional_argument(body)
    for _ in range(count):
        stripped = body.lstrip()
        if not stripped.startswith("{"):
            break
        _content, after = alt_blocks.braced_argument(stripped, 0)
        if after == 0:
            break
        body = stripped[after:]
    return body


# A row ends at \\ (with an optional [<skip>], which used to start the next
# row as "[ ]"); a cell at an & that is not the escaped \&.
_TABLE_ROW_END_RE = re.compile(r"\\\\\*?(?:\s*\[[^\]]*\])?")
_TABLE_CELL_END_RE = re.compile(r"(?<!\\)&")


def _flatten_table(body: str, spec_args: int = 1) -> str:
    """A table inside a table cell (a picture over its caption) as one line:
    left in place, its own \\\\ and & split the outer table's rows."""
    body = _strip_column_spec(body, spec_args)
    return " ".join(part.strip() for part in
                    _TABLE_CELL_END_RE.split(_TABLE_ROW_END_RE.sub(" ", body)))


def _render_table(body: str, spec_args: int = 1) -> str:
    """Best-effort LaTeX table to Markdown table.

    Deliberately conservative: rows are split on `\\\\` and cells on `&`, and
    anything that doesn't look rectangular is emitted as plain lines instead of
    a malformed table. A wrong table is harder to read than no table.
    """
    body = _strip_column_spec(body, spec_args)
    for name, count in _TABLE_SPEC_ARGS.items():
        body = _transform_environments(
            body, name, lambda inner, n=count: _flatten_table(inner, n))
    body = re.sub(r"\\(?:hline|toprule|midrule|bottomrule|rowcolor\{[^}]*\})", "",
                  body)
    rows = [r.strip() for r in _TABLE_ROW_END_RE.split(body) if r.strip()]
    cells = [[_inline_markdown(c).strip() for c in _TABLE_CELL_END_RE.split(row)]
             for row in rows]
    cells = [row for row in cells if any(c for c in row)]
    if not cells:
        return ""
    width = max(len(row) for row in cells)
    if width < 2:
        return "\n".join(" ".join(row) for row in cells)
    padded = [row + [""] * (width - len(row)) for row in cells]
    out = ["| " + " | ".join(padded[0]) + " |",
           "|" + "|".join(["---"] * width) + "|"]
    for row in padded[1:]:
        out.append("| " + " | ".join(row) + " |")
    return "\n" + "\n".join(out) + "\n"


_INLINE_MACROS = (
    (re.compile(r"\\textbf\s*\{"), "**", "**"),
    (re.compile(r"\\alert\s*\{"), "**", "**"),
    (re.compile(r"\\underline\s*\{"), "**", "**"),
    (re.compile(r"\\(?:emph|textit)\s*\{"), "*", "*"),
)
# A literal backslash in the text (\textbackslash): parked as \x03 while the
# inline conversion strips macro names, put back by _finish() once the whole
# body is converted.
_BACKSLASH_SLOT = "\x03"
_TEXTBACKSLASH_RE = re.compile(r"\\textbackslash(?![a-zA-Z])(?:\{\})?\s?")

# Code in running text -- \SMCode{text}, \SMCmd{name} (which prints
# \name), \texttt{text} -- is shown verbatim as `code`. Its argument is
# typeset LaTeX (\{ \_ \textbackslash), so it is decoded once and then
# parked behind a \x04<n>\x04 slot until _finish(): every later pass (the
# brace strip, "--" to an en dash, `` to a curly quote, the bare-dimension
# strip that ate the "12pt" of "gap=12pt") would otherwise mangle it -- the
# manual's \SMCmd{input}\SMCode{\{...\}} came out as "`\input“...\`".
# Adjacent spans are one span: \SMCmd{slide}\SMCode{\{id\}} is `\slide{id}`.
_CODE_SPAN_RE = re.compile(r"\\(SMCode|SMCmd|texttt)\s*\{")
_CODE_SPAN_RUN_RE = re.compile(r"(?:\x04\d+\x04)+")
_CODE_SPAN_ID_RE = re.compile(r"\x04(\d+)\x04")
_code_spans: dict[int, str] = {}
_code_span_ids = itertools.count()


def _code_text(raw: str) -> str:
    """A code argument's typeset text: escapes decoded, formatting dropped."""
    text = _TEXTBACKSLASH_RE.sub(_BACKSLASH_SLOT, raw)
    text = text.replace("\\{", "\x05").replace("\\}", "\x06")
    for escaped, plain in (("\\_", "_"), ("\\#", "#"), ("\\%", "%"), ("\\&", "&"),
                           ("\\$", "$"), ("\\,", " "), ("\\ ", " ")):
        text = text.replace(escaped, plain)
    text = re.sub(r"\\textasciitilde(?![a-zA-Z])(?:\{\})?", "\x07", text)
    text = re.sub(r"\\textasciicircum(?![a-zA-Z])(?:\{\})?", "^", text)
    text = _ELLIPSIS_RE.sub("...", text)
    text = _SYMBOL_RE.sub(lambda m: _SYMBOLS[m.group(1)], text)
    text = text.replace("~", " ").replace("\x07", "~")
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
    text = text.replace("{", "").replace("}", "")
    return (text.replace("\x05", "{").replace("\x06", "}")
            .replace(_BACKSLASH_SLOT, "\\"))


def _park_code_spans(text: str) -> str:
    out: list[str] = []
    index = 0
    while True:
        match = _CODE_SPAN_RE.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:match.start()])
        content, after = alt_blocks.braced_argument(text, match.end() - 1)
        if after == match.end() - 1:
            out.append(text[match.start():])
            return "".join(out)
        code = ("\\" if match.group(1) == "SMCmd" else "") + _code_text(content)
        if code.strip():
            slot = next(_code_span_ids)
            _code_spans[slot] = code
            out.append(f"\x04{slot}\x04")
        index = after


def _finish(text: str) -> str:
    """Put the parked code spans and literal backslashes back."""
    def span(match: re.Match) -> str:
        code = "".join(_code_spans.pop(int(n), "")
                       for n in _CODE_SPAN_ID_RE.findall(match.group(0)))
        return f"`{code}`" if code else ""
    return _CODE_SPAN_RUN_RE.sub(span, text).replace(_BACKSLASH_SLOT, "\\")


# Maths and symbols a reader should hear as what they are -- stripped as
# macros, "$\rightarrow$" left an empty "$$" and \dfrac{a}{b} became "ab".
_SYMBOLS = {
    "rightarrow": "→", "to": "→", "Rightarrow": "⇒", "leftarrow": "←",
    "Leftarrow": "⇐", "leftrightarrow": "↔", "Leftrightarrow": "⇔",
    "mapsto": "↦", "uparrow": "↑", "downarrow": "↓",
    "times": "×", "cdot": "·", "pm": "±", "mp": "∓", "div": "÷",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "sim": "∼", "equiv": "≡", "triangleq": "≜", "propto": "∝",
    "infty": "∞", "partial": "∂", "sum": "∑", "prod": "∏", "int": "∫",
    "in": "∈", "notin": "∉", "subset": "⊂", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "sqrt": "√", "degree": "°", "textdegree": "°",
    "EUR": "€", "euro": "€", "checkmark": "✓", "quad": " ", "qquad": " ",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ",
    "Psi": "Ψ", "Omega": "Ω",
    "textdagger": "†", "dag": "†", "textdaggerdbl": "‡", "ddag": "‡",
    "S": "§", "textsection": "§", "P": "¶", "textparagraph": "¶",
    "pounds": "£", "copyright": "©", "textregistered": "®", "texttrademark": "™",
}
_SYMBOL_RE = re.compile(
    r"\\(" + "|".join(sorted(_SYMBOLS, key=len, reverse=True)) + r")(?![a-zA-Z])(?:\{\})?")
_FRAC_RE = re.compile(r"\\[dt]?frac\s*\{")
_UNDERBRACE_RE = re.compile(r"\\SMUnderbrace\s*\{")
# Maths holding only code (the manual's labelled file name) is not maths to
# a reader: its dollars go.
_CODE_ONLY_MATH_RE = re.compile(r"(?<!\\)\$([^$]*\x04\d+\x04[^$]*)(?<!\\)\$")
# ... and neither is a lone symbol: "$→$" reads as the arrow
_SYMBOL_ONLY_MATH_RE = re.compile(r"(?<!\\)\$([^$a-zA-Z0-9\\\s]+)\$")
# \hyperlink{target}{text}: the target is an ID, the text is the link
_HYPERLINK_TARGET_RE = re.compile(r"\\hyperlink\s*\{[^{}]*\}")


def _replace_two_arguments(text: str, pattern: re.Pattern, render) -> str:
    """Every `pattern{a}{b}` replaced by render(a, b) (both brace-matched)."""
    out: list[str] = []
    index = 0
    while True:
        match = pattern.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        first, after = alt_blocks.braced_argument(text, match.end() - 1)
        cursor = after
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        second, after2 = alt_blocks.braced_argument(text, cursor)
        if after == match.end() - 1 or after2 == cursor:
            out.append(text[index:match.end()])
            index = match.end()
            continue
        out.append(text[index:match.start()] + render(first, second))
        index = after2


def _fraction(numerator: str, denominator: str) -> str:
    def group(part: str) -> str:
        part = part.strip()
        return f"({part})" if re.search(r"[-+*/=, ]", part) else part
    return f"{group(numerator)}/{group(denominator)}"
# A \\ line break (with an optional [<skip>]) is a space in running text: the
# generic macro strip used to take "\SlideMage" out of "...\\SlideMage" and
# leave a stray backslash behind ("demonstration\ 5.12").
_LINE_BREAK_RE = re.compile(r"\\\\\*?(?:\[[^\]]*\])?")
_PERIODCENTERED_RE = re.compile(r"\\textperiodcentered(?![a-zA-Z])(?:\{\})?")

# Colour commands (v4.1.0, direct instruction): a transcript omits colour.
# The command and its colour argument(s) go, the coloured text stays --
# the generic macro/brace strip in _inline_markdown() used to leave the
# colour name glued to the text ("c_primary_highlightdata dredging",
# "[HTML]C00000Promotes ..."). \color is a switch with no text argument.
_COLOR_COMMAND_RE = re.compile(
    r"\\fcolorbox\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}"
    r"|\\(?:textcolor|colorbox|cellcolor|rowcolor|columncolor|color)(?![a-zA-Z])"
    r"\s*(?:<[^>]*>)?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}"
)
_HREF_RE = re.compile(r"\\href\s*\{")
_URL_RE = re.compile(r"\\url\s*\{")
_CITE_RE = re.compile(r"\\(fullcite|textcite|citep|citet|cite)\s*\{([^}]*)\}")

# Which biblatex command maps to which rendering. \citet is textual
# ("Smith (2020) shows..."), \citep parenthetical ("(Smith, 2020)").
_CITE_STYLES = {"fullcite": "full", "textcite": "text", "citet": "text",
                "citep": "paren", "cite": "paren"}

_BIB_CACHE: dict | None = None


def _bib() -> dict:
    """Slidemaster.bib, parsed once per process."""
    global _BIB_CACHE
    if _BIB_CACHE is None:
        _BIB_CACHE = bibliography.load()
    return _BIB_CACHE


def _render_citation(match: re.Match) -> str:
    style = _CITE_STYLES.get(match.group(1), "full")
    keys = [k.strip() for k in match.group(2).split(",") if k.strip()]
    entries = _bib()
    return "; ".join(bibliography.format_citation(k, entries, style)
                     for k in keys)
_FOOTNOTE_RE = re.compile(r"\\footnote\s*(?:\[[^\]]*\])?\s*\{")


def _apply_wrapped(text: str, pattern: re.Pattern, prefix: str, suffix: str) -> str:
    out: list[str] = []
    index = 0
    while True:
        match = pattern.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:match.start()])
        content, after = alt_blocks.braced_argument(text, match.end() - 1)
        if after == match.end() - 1:
            out.append(text[match.start():])
            return "".join(out)
        inner = _inline_markdown(content).strip()
        out.append(f"{prefix}{inner}{suffix}" if inner else "")
        index = after


def _inline_markdown(text: str) -> str:
    """Inline-level LaTeX to Markdown. Recursive: macros nest."""
    text = _park_code_spans(text)
    text = _COLOR_COMMAND_RE.sub("", text)
    text = _TEXTBACKSLASH_RE.sub(_BACKSLASH_SLOT, text)
    text = _HYPERLINK_TARGET_RE.sub("", text)
    text = _replace_two_arguments(text, _FRAC_RE, _fraction)
    text = _replace_two_arguments(
        text, _UNDERBRACE_RE, lambda term, label: f"{term} [{label.strip()}]")
    text = _CODE_ONLY_MATH_RE.sub(r"\1", text)
    text = _SYMBOL_RE.sub(lambda m: _SYMBOLS[m.group(1)], text)
    text = _SYMBOL_ONLY_MATH_RE.sub(r"\1", text)
    text = _LINE_BREAK_RE.sub(" ", text)
    text = _PERIODCENTERED_RE.sub("·", text)
    # \href{url}{label} -> [label](url)
    while True:
        match = _HREF_RE.search(text)
        if match is None:
            break
        url, after = alt_blocks.braced_argument(text, match.end() - 1)
        if after == match.end() - 1:
            break
        label, after2 = alt_blocks.braced_argument(text, after)
        if after2 == after:
            text = text[:match.start()] + url + text[after:]
            continue
        text = (text[:match.start()]
                + f"[{_inline_markdown(label).strip()}]({url.strip()})"
                + text[after2:])

    text = _apply_wrapped(text, _URL_RE, "<", ">")
    text = _ELLIPSIS_RE.sub("…", text)
    # Footnotes are inlined: a transcript reader has nothing to hover over.
    text = _apply_wrapped(text, _FOOTNOTE_RE, " (", ")")
    # Citation keys are resolved against Slidemaster.bib, so a source line
    # reads "Loughran, Ritter & Rydqvist (1995), ..." rather than the bare
    # key. An unknown key renders as "[key]" rather than disappearing.
    text = _CITE_RE.sub(_render_citation, text)

    for pattern, prefix, suffix in _INLINE_MACROS:
        text = _apply_wrapped(text, pattern, prefix, suffix)

    for escaped, plain in (("\\$", "$"), ("\\&", "&"), ("\\_", "_"),
                           ("\\#", "#"), ("\\%", "%"), ("\\,", " ")):
        text = text.replace(escaped, plain)
    text = text.replace("~", " ")
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    text = text.replace("---", "\u2014").replace("--", "\u2013")
    # a macro and its overlay specification (\only<4>, \uncover<2->)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:<[-\d,|+@a-z.]*>)?", "", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", text)


_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_NODE_RE = re.compile(r"\\node\b")


def _tikz_labels(body: str) -> str:
    """The text of a tikzpicture's `\\node{...}` labels, drawing syntax dropped.

    A node is `\\node[opts] (name) at (coord) {LABEL};` -- the label is the last
    balanced brace group before the terminating semicolon, which is what this
    walks to. Nodes holding only an image contribute nothing (the image is
    described in its own section).
    """
    labels: list[str] = []
    for match in _NODE_RE.finditer(body):
        # Find the node's terminating ";" at brace depth zero.
        cursor, depth, end = match.end(), 0, len(body)
        while cursor < len(body):
            char = body[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            elif char == ";" and depth == 0:
                end = cursor
                break
            cursor += 1

        span = body[match.end():end]
        last_open = span.rfind("{")
        if last_open == -1:
            continue
        content, after = alt_blocks.braced_argument(span, last_open)
        if after == last_open or "includegraphics" in content:
            continue
        rendered = _convert_body(content).strip()
        # The same node is often re-emitted once per overlay step; the
        # transcript has no overlays, so consecutive repeats are noise.
        if rendered and (not labels or labels[-1] != rendered):
            labels.append(rendered)
    return "\n\n".join(labels)


# Layout commands whose arguments are numbers, counters or lengths: the
# generic macro strip left those behind ("1" from \shrinklists{1}, "6.47.6"
# from \fontsize{6.4}{7.6}, "enumi5" from \setcounter{enumi}{5}).
_LAYOUT_COMMAND_RE = re.compile(
    r"\\(?:shrinklists|SMTocLabelFlushLeft|SMEnumerateLabelFlushLeftShifted"
    r"|stepcounter|refstepcounter)\s*\{[^{}]*\}"
    r"|\\(?:fontsize|setcounter|addtocounter|setlength|addtolength)\s*"
    r"\{[^{}]*\}\s*\{[^{}]*\}"
    r"|\\(?:hangindent|hangafter|parindent|leftskip|rightskip|baselineskip"
    r"|tabcolsep|arraystretch)\s*=?\s*[-+]?\d*\.?\d+\s*(?:pt|cm|mm|em|ex|in|bp|sp)?")
# \ifnum ... \fi: a test on a counter or a length -- layout logic (the
# agenda slides' "\ifnum\value{enumi}=0 \item[] \fi"); the condition cannot
# be evaluated here and the branch holds no slide text.
_IFNUM_RE = re.compile(r"\\ifnum(?![a-zA-Z]).*?\\fi(?![a-zA-Z])", re.DOTALL)
# Figure helpers (Slidemaster_preamble_base.tex): the argument is an image
# path (described in its own section) or, for \cornerfigure[block], content
# that stays.
_FIGURE_COMMAND_RE = re.compile(
    r"\\(?:cornerfigure|fitfigure|sectionfigure)\s*(?:\[[^\]]*\])?\s*\{")
_PROGRESS_STRIP_RE = re.compile(r"\\progressstrip\s*\{")
_WARNING_SIGN_RE = re.compile(r"\\SMWarningSign\s*(?:\[[^\]]*\])?\s*\{")
_TOC_RE = re.compile(r"\\tableofcontents\s*(?:\[([^\]]*)\])?")
_TOC_SECTIONS_RE = re.compile(r"sections\s*=\s*\{?\s*([\d\s,\-]+)\}?")
_TOC_SLOT_RE = re.compile(r"\x02SMTOC:([\d,\-]*)\x02")


def _figure_commands(text: str) -> str:
    out: list[str] = []
    index = 0
    while True:
        match = _FIGURE_COMMAND_RE.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        argument, after = alt_blocks.braced_argument(text, match.end() - 1)
        if after == match.end() - 1:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:match.start()])
        out.append(f"\n{argument}\n" if "\\" in argument else " ")
        index = after


def _arguments(text: str, start: int, count: int) -> tuple[list[str], int]:
    """`count` brace-matched arguments from `start` on; ([], start) if short."""
    arguments: list[str] = []
    cursor = start
    for _ in range(count):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        content, after = alt_blocks.braced_argument(text, cursor)
        if after == cursor:
            return [], start
        arguments.append(content)
        cursor = after
    return arguments, cursor


def _replace_command(text: str, pattern: re.Pattern, count: int, render) -> str:
    """Every `pattern` call with `count` arguments (the first one's brace
    ends the pattern) replaced by render(arguments)."""
    out: list[str] = []
    index = 0
    while True:
        match = pattern.search(text, index)
        if match is None:
            out.append(text[index:])
            return "".join(out)
        arguments, after = _arguments(text, match.end() - 1, count)
        if not arguments:
            out.append(text[index:match.end()])
            index = match.end()
            continue
        out.append(text[index:match.start()] + render(arguments))
        index = after


def _progress_strip(arguments: list[str]) -> str:
    steps = [step.strip() for step in arguments[0].split(",") if step.strip()]
    current = arguments[1].strip()
    return " → ".join(
        f"**{step}**" if str(number) == current else step
        for number, step in enumerate(steps, start=1))


def _toc_slot(match: re.Match) -> str:
    sections = _TOC_SECTIONS_RE.search(match.group(1) or "")
    spec = re.sub(r"\s", "", sections.group(1)) if sections else ""
    return f"\n\x02SMTOC:{spec}\x02\n"


def _convert_body(text: str, depth: int = 0) -> str:
    text = _park_code_spans(text)
    text = _CONTROL_SPACE_RE.sub(r"\1 ", text)
    text = _SETBEAMER_RE.sub("", text)
    text = _TIKZ_MARK_NAME_RE.sub("", text)
    text = _IFNUM_RE.sub(" ", text)
    text = _LAYOUT_COMMAND_RE.sub(" ", text)
    text = _figure_commands(text)
    text = _replace_command(text, _PROGRESS_STRIP_RE, 2, _progress_strip)
    text = _replace_command(text, _WARNING_SIGN_RE, 5,
                            lambda arguments: f"⚠ {arguments[2].strip()}")
    text = _GRAPHICS_RE.sub(" ", text)
    text = _CONDITIONAL_PAUSE_RE.sub(" ", text)
    text = _BOX_TO_RE.sub(" ", text)
    text = _DIMENSION_RE.sub(" ", text)
    for name in _DROP_ENVIRONMENTS:
        text = _transform_environments(text, name, lambda _body: "")
    # A tikzillustration is described like an image, in its own section;
    # its node labels would only repeat that description.
    text = _transform_environments(text, "tikzillustration", lambda _body: "")
    text = _transform_environments(text, "tikzpicture", _tikz_labels)
    for name in _UNWRAP_ENVIRONMENTS:
        text = _transform_environments(text, name, lambda body: "\n" + body + "\n")
    for name in _BLOCK_ENVIRONMENTS:
        text = _transform_environments(
            text, name, lambda body, n=name: _render_block(body, n))
    for name, spec_args in _TABLE_SPEC_ARGS.items():
        text = _transform_environments(
            text, name, lambda body, n=spec_args: _render_table(body, n))
    for name, marker in _LIST_ENVIRONMENTS.items():
        text = _transform_environments(
            text, name, lambda body, m=marker: "\n" + _render_list(body, m, depth) + "\n")

    # Table rows are skipped: their cells were already converted in
    # _render_table, and re-running inline conversion turns the separator
    # "|---|---|" into "|—|—|" (the em-dash rule), which stops the row being
    # recognised as a table at all -- every cell then renders as a stray
    # paragraph beginning with a pipe.
    lines = [line.rstrip() if _TABLE_LINE_RE.match(line)
             else _inline_markdown(line).rstrip()
             for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line.strip() or (out and out[-1].strip()):
            out.append(line.rstrip())
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


# --------------------------------------------------------------------------
# Rendering one slide
# --------------------------------------------------------------------------

_FRAME_END_RE = re.compile(r"\\end\{\w*frame\}")
_PLAIN_FRAME_OPEN_RE = re.compile(r"\\begin\{frame\}\s*(?:<[^>]*>)?\s*(?:\[[^\]]*\])?")

# \SMCodeFile[listings keys]{path}: LaTeX source a slide shows from a file
# (snippets/<id>-<n>.tex). The transcript shows the file's text as a fenced
# code block. Parked behind a placeholder while the body is converted -- the
# inline conversion would strip every macro out of it -- and put back after.
_CODE_FILE_RE = re.compile(r"\\SMCodeFile\s*(?:\[([^\]]*)\])?\s*\{([^{}]+)\}")
_CODE_LINE_KEY_RE = re.compile(r"\b(firstline|lastline)\s*=\s*(\d+)")
_CODE_SLOT = "\x02SMCODE{}\x02"


def _park_code_files(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def park(match: re.Match) -> str:
        ref = match.group(2).strip()
        try:
            lines = (PROJECT_ROOT / ref).read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = [f"(code file {ref} not found)"]
        keys = dict(_CODE_LINE_KEY_RE.findall(match.group(1) or ""))
        first = int(keys.get("firstline", 1))
        last = int(keys.get("lastline", len(lines)))
        code = "\n".join(lines[first - 1:last]).replace("\t", "  ").rstrip()
        blocks.append(f"```latex\n{code}\n```")
        return "\n\n" + _CODE_SLOT.format(len(blocks) - 1) + "\n\n"

    return _CODE_FILE_RE.sub(park, text), blocks


# Navigation (Slidemaster_preamble_base.tex, "Navigation for readers"):
# \SMChapterAgenda becomes the list of the chapter's slides (filled in by
# generate(), which knows the deck); \SMDeckAgenda is a link target only;
# \SMAgendaTitle{text} names the slide in agendas.
_CHAPTER_AGENDA_RE = re.compile(r"\\SMChapterAgenda(?![a-zA-Z@])\s*(?:\[[^\]]*\])?")
_DECK_AGENDA_RE = re.compile(r"\\SMDeckAgenda(?![a-zA-Z@])")
_AGENDA_TITLE_RE = re.compile(r"\\SMAgendaTitle\s*\{")
_AGENDA_SLOT = "\x02SMAGENDA\x02"


def _unpark_code_files(text: str, blocks: list[str]) -> str:
    for slot, block in enumerate(blocks):
        text = text.replace(_CODE_SLOT.format(slot), block)
    return text


# A slide's own macros (\providecommand{\galleryitem}[3]{...} at its top):
# expanded, so their arguments are read where they are used -- the
# definition's #1 #2 and the call's bare arguments otherwise both leaked
# into the transcript. Mandatory arguments, and an optional first one with
# its default; \def is left alone.
_LOCAL_MACRO_DEF_RE = re.compile(
    r"\\(?:provide|new|renew)command\*?\s*(?:\{\s*\\([a-zA-Z@]+)\s*\}|\\([a-zA-Z@]+))"
    r"\s*(?:\[(\d)\])?\s*(?:\[([^\]]*)\])?\s*\{")


def _expand_local_macros(text: str) -> str:
    macros: dict[str, tuple[int, str | None, str]] = {}
    while True:
        match = _LOCAL_MACRO_DEF_RE.search(text)
        if match is None:
            break
        body, after = alt_blocks.braced_argument(text, match.end() - 1)
        if after == match.end() - 1:
            break
        macros[match.group(1) or match.group(2)] = (
            int(match.group(3) or 0), match.group(4), body)
        text = text[:match.start()] + text[after:]

    for _ in range(5):                      # macros using macros
        changed = False
        for name, (count, default, body) in macros.items():
            pattern = re.compile(r"\\" + re.escape(name) + r"(?![a-zA-Z@])")
            out: list[str] = []
            index = 0
            for match in pattern.finditer(text):
                if match.start() < index:
                    continue
                cursor = match.end()
                arguments: list[str] = []
                if default is not None and count:
                    rest = text[cursor:].lstrip()
                    if rest.startswith("["):
                        close = rest.find("]")
                        arguments.append(rest[1:close])
                        cursor = len(text) - len(rest) + close + 1
                    else:
                        arguments.append(default)
                more, cursor = _arguments(text, cursor, count - len(arguments))
                if len(arguments) + len(more) < count:
                    continue
                arguments += more
                expansion = body
                for number, argument in enumerate(arguments, start=1):
                    expansion = expansion.replace(f"#{number}", argument)
                out.append(text[index:match.start()] + expansion)
                index = cursor
                changed = True
            out.append(text[index:])
            text = "".join(out)
        if not changed:
            break
    return text


_MULTILINGUAL_NEEDLE = "\\multilingualtext{"


def _resolve_multilingual_text(text: str, language: str) -> str:
    """Replaces every \\multilingualtext{EN}{DE} call with just its EN or
    DE argument, mirroring \\ifSMGerman's own choice at compile time
    (Slidemaster_preamble_base.tex) -- brace-matched
    (alt_blocks.braced_argument), not a naive regex, since either argument
    can itself contain a braced macro (e.g. \\textbf{...}).

    Must run before title/body extraction: a "mult" slide's transcript
    otherwise showed *both* languages concatenated together (2026-08-25,
    reported directly against g6q) -- alt_blocks.slide_title()'s own
    macro-name-stripping regex only ever removes the bare "\\multilingualtext"
    token, then strips every remaining brace indiscriminately, leaving
    "{EN}{DE}" collapse into "ENDE" rather than picking one."""
    out: list[str] = []
    index = 0
    while True:
        found = text.find(_MULTILINGUAL_NEEDLE, index)
        if found == -1:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:found])
        first_open = found + len(_MULTILINGUAL_NEEDLE) - 1
        arg_en, after_first = alt_blocks.braced_argument(text, first_open)
        if after_first == first_open:  # unbalanced first arg -- leave the rest untouched
            out.append(text[found:])
            return "".join(out)
        arg_de, after_second = alt_blocks.braced_argument(text, after_first)
        if after_second == after_first:  # no second {...} immediately following -- malformed
            out.append(text[found:after_first])
            index = after_first
            continue
        out.append(arg_de if language == "de" else arg_en)
        index = after_second


def render_slide(deck_slide: DeckSlide, version: str,
                 entries: dict[str, "alt_images.ImageEntry"],
                 slide_notes: dict[str, "alt_images.SlideNotes"] | None = None,
                 language: str = "en",
                 ) -> TranscriptSlide | None:
    """Turn one slide file into a transcript entry, or None if unreadable."""
    try:
        source_text = deck_slide.path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Resolved before anything else looks at the text (comment-stripping,
    # title extraction, body conversion all derive from source_text below)
    # so both the title and the body reflect only the requested language.
    source_text = _resolve_multilingual_text(source_text, language)

    stripped = COMMENT_RE.sub("", source_text)
    stripped = resolve_deck_conditionals(stripped, version)
    stripped, _notes = alt_blocks.extract_note_calls(stripped)
    body = _expand_local_macros(stripped)
    body, sources = alt_blocks.extract_macro_calls(body, "source")
    body, quote_sources = alt_blocks.extract_macro_calls(body, "quotesource")
    sources += quote_sources
    body, agenda_titles = alt_blocks.extract_macro_calls(body, "SMAgendaTitle")
    body = _DECK_AGENDA_RE.sub("", body)
    has_chapter_agenda = bool(_CHAPTER_AGENDA_RE.search(body))
    body = _CHAPTER_AGENDA_RE.sub("\n\n" + _AGENDA_SLOT + "\n\n", body)
    body = _TOC_RE.sub(_toc_slot, body)
    agenda_title = (_finish(_inline_markdown(agenda_titles[0]).strip())
                    if agenda_titles else "")

    slide_id, title = alt_blocks.slide_title(stripped, deck_slide.path)
    if agenda_title and not (alt_blocks.FRAME_OPEN_RE.search(stripped)
                             or alt_blocks.TITLEFRAME_RE.search(stripped)):
        title = agenda_title  # a title-less frame (\quoteframe, \fullbleedframe)

    begin = alt_blocks.FRAME_OPEN_RE.search(body)
    plain = _PLAIN_FRAME_OPEN_RE.search(body)
    end = _FRAME_END_RE.search(body)
    if begin and end:
        _title_arg, after_title = alt_blocks.braced_argument(body, begin.end() - 1)
        if begin.group(0).startswith("\\begin{sideimageframe}"):
            _path, after_title = _arguments(body, after_title, 1)  # its image
        if after_title < end.start():
            body = body[after_title:end.start()]
    elif plain and end:
        # \begin{frame}[standout]: beamer's own frame, title optional
        cursor = plain.end()
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if body.startswith("{", cursor):
            _title_arg, cursor = alt_blocks.braced_argument(body, cursor)
        body = body[cursor:end.start()]
    else:
        # \titleframe{title}{subtitle}/\fullbleedframe{path} are commands,
        # not environments, so they never match FRAME_OPEN_RE/_FRAME_END_RE
        # above -- without this branch, `body` stayed the *entire* raw
        # stripped source (this slide's own macro call included), and
        # _convert_body() below only strips bare macro *names*, leaving
        # brace-argument content (a version string, a raw image path)
        # flattened into the transcript text. The title slide's own title
        # is already captured separately via slide_title() above, so only
        # its subtitle (the second argument) is real body content; a
        # fullbleedframe slide has no text at all -- its image's own
        # description (now detected by referenced_images(), see
        # alt_blocks.py's FULLBLEEDFRAME_RE) is the whole story.
        title_cmd = alt_blocks.TITLEFRAME_RE.search(body)
        fullbleed_cmd = alt_blocks.FULLBLEEDFRAME_RE.search(body)
        if title_cmd:
            _title_arg, after_title = alt_blocks.braced_argument(body, title_cmd.end() - 1)
            cursor = after_title
            while cursor < len(body) and body[cursor].isspace():
                cursor += 1
            subtitle, _after_subtitle = alt_blocks.braced_argument(body, cursor)
            body = subtitle
        elif fullbleed_cmd:
            body = ""

    notes = (slide_notes or {}).get(slide_id)
    body, code_blocks = _park_code_files(body)
    entry = TranscriptSlide(
        number=deck_slide.number,
        slide_id=slide_id,
        title=title,
        body=_unpark_code_files(_finish(_convert_body(body).strip()), code_blocks),
        source=_finish(" ".join(_inline_markdown(" ".join(sources)).split())),
        summary=notes.summary if notes else "",
        agenda_title=agenda_title,
        chapter_agenda=has_chapter_agenda,
    )

    for reference in alt_blocks.referenced_images(stripped):
        described = alt_images.lookup(entries, reference)
        role = described.role if described else alt_images.ROLE_INFORMATIVE
        if language == "de" and described:
            image = TranscriptImage(
                reference=reference, role=role,
                short=described.short_de, long=described.long_de,
                takeaway=described.takeaway_for_de(slide_id),
            )
        else:
            image = TranscriptImage(
                reference=reference,
                role=role,
                short=described.short if described else "",
                long=described.long if described else "",
                takeaway=described.takeaway_for(slide_id) if described else "",
            )
        image.described = bool(image.long) or role == alt_images.ROLE_DECORATIVE
        if not image.described:
            entry.missing_description = True
        entry.images.append(image)

    return entry


def _render_image(image: TranscriptImage, language: str = "en") -> list[str]:
    strings = STRINGS[language]
    if image.role == alt_images.ROLE_DECORATIVE:
        return [strings["decorative_image"].format(ref=image.reference), ""]
    if not image.long:
        return [strings["no_description"].format(ref=image.reference), ""]

    out = [strings["figure_label"].format(caption=image.short or image.reference), ""]
    if image.short:
        out += [f"{strings['short_description_label']} {image.short}", ""]
    out += [strings["full_description_label"], "", image.long, ""]
    if image.takeaway:
        out += [f"{strings['takeaway_label']} {image.takeaway}", ""]
    return out


def _entry_markdown_lines(entry: TranscriptSlide, language: str = "en") -> list[str]:
    """One slide's own transcript block -- factored out of generate()'s
    per-slide loop (2026-08-25) so generate_single_slide() below can
    produce byte-for-byte the same rendering for a lone slide preview as
    generate() would inside a real deck."""
    strings = STRINGS[language]
    lines = [
        f"## Slide {entry.number} — {entry.title}",
        "",
        f"*Slide ID {entry.slide_id}*",
        "",
    ]
    if entry.summary:
        lines += [f"{strings['summary_label']} {entry.summary}", ""]
    if entry.body:
        lines += [entry.body, ""]
    for image in entry.images:
        lines += _render_image(image, language=language)
    if entry.source:
        lines += [f"*{entry.source}*", ""]
    lines += ["---", ""]
    return lines


def _fill_chapter_agendas(entries: list[TranscriptSlide], chapters: list[int],
                          language: str = "en") -> None:
    """Replace each \\SMChapterAgenda placeholder with the list of the other
    slides in the same chapter (by \\section), as the PDF's agenda shows them:
    each slide once (a \\slidestep slide at its first place), its
    \\SMAgendaTitle or title, plus its slide number."""
    strings = STRINGS[language]
    for index, entry in enumerate(entries):
        if not entry.chapter_agenda:
            continue
        seen: set[str] = set()
        items: list[str] = []
        for other, chapter in zip(entries, chapters):
            if other is entry or chapter != chapters[index] or other.slide_id in seen:
                continue
            seen.add(other.slide_id)
            items.append("- " + strings["chapter_agenda_item"].format(
                title=other.agenda_title or other.title, n=other.number))
        block = "\n".join([strings["chapter_agenda_label"], ""] + items) if items else ""
        entry.body = entry.body.replace(_AGENDA_SLOT, block).strip()


def _section_titles(deck_path: Path) -> list[str]:
    """The deck's \\section titles, in order (literal includes expanded, as
    resolve_deck() counts them)."""
    source = deck_path.read_text(encoding="utf-8")
    text = _expand_literal_includes(source, deck_path, deck_path.parent.resolve(),
                                    (deck_path.resolve(),))
    text = COMMENT_RE.sub("", text)
    titles: list[str] = []
    for match in _SECTION_RE.finditer(text):
        title, _after = alt_blocks.braced_argument(text, match.end() - 1)
        titles.append(_finish(_inline_markdown(title).strip()))
    return titles


def _section_numbers(spec: str, total: int) -> list[int]:
    """beamer's sections={1-5,7} option; empty means every section."""
    if not spec:
        return list(range(1, total + 1))
    numbers: list[int] = []
    for part in spec.split(","):
        first, _, last = part.partition("-")
        if first.isdigit():
            numbers.extend(range(int(first), int(last or first) + 1)
                           if (last or first).isdigit() else [int(first)])
    return numbers


def _fill_deck_tocs(entries: list[TranscriptSlide], chapters: list[int],
                    section_titles: list[str], language: str = "en") -> None:
    """Replace each \\tableofcontents placeholder with the deck's chapters
    (the sections it asks for), each with the number of its first slide."""
    strings = STRINGS[language]
    first_slide: dict[int, int] = {}
    for entry, chapter in zip(entries, chapters):
        first_slide.setdefault(chapter, entry.number)

    def render(match: re.Match) -> str:
        items: list[str] = []
        for number in _section_numbers(match.group(1), len(section_titles)):
            if not 1 <= number <= len(section_titles):
                continue
            title = section_titles[number - 1]
            if number in first_slide:
                title = strings["chapter_agenda_item"].format(
                    title=title, n=first_slide[number])
            items.append(f"{number}. {title}")
        return "\n".join(items)

    for entry in entries:
        entry.body = _TOC_SLOT_RE.sub(render, entry.body).strip()


def generate_single_slide(
    source_text: str, bare_id: str, version: str, language: str
) -> TranscriptResult:
    """The Preview's own "Render transcript" menu entry (2026-08-25)
    -- one slide's transcript entry, independent of any real deck (no
    numbering/deck title/undescribed-image-count context beyond this one
    slide), rendered exactly as generate() would render it inside a real
    deck. `version` silently falls back to VERSION_DURING when it isn't a
    student version (e.g. "instructor", picked from the same Render-bar
    combo used for PDF rendering) -- transcripts genuinely don't exist for
    that version at all, so refusing outright would just be an extra click
    to route around for what's still a routine preview action.

    `source_text` -- the editor's current buffer, possibly unsaved -- is
    written to a throwaway temp file under `bare_id`'s own real filename
    stem before render_slide() ever sees it: that function only reads from
    a real Path, and alt_blocks.slide_title()/entry.takeaway_for() derive
    this slide's *identity* (its bare id, and therefore its own per-slide
    image-takeaway overrides and transcript summary) from that filename's
    stem, not from anything inside the text itself. A randomly-named temp
    file would silently produce a transcript for a slide with no identity
    at all -- no takeaway overrides, no summary, wrong image lookups."""
    if version not in STUDENT_VERSIONS:
        version = VERSION_DURING

    entries = alt_images.load_store()
    slide_notes = alt_images.load_slide_notes()
    tmp_dir = Path(tempfile.mkdtemp(prefix="slidemage-transcript-"))
    try:
        tmp_path = tmp_dir / f"{bare_id}-current.tex"
        tmp_path.write_text(source_text, encoding="utf-8", newline="")
        deck_slide = DeckSlide(number=1, slide_id=bare_id, path=tmp_path, included=True)
        entry = render_slide(deck_slide, version, entries, slide_notes, language=language)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if entry is None:
        raise RuntimeError("Could not read this slide's own text.")
    _fill_chapter_agendas([entry], [0], language)  # no deck: no chapter to list
    _fill_deck_tocs([entry], [0], [], language)

    lines = _entry_markdown_lines(entry, language=language)
    return TranscriptResult(
        markdown="\n".join(lines),
        slides=[entry],
        total_in_deck=1,
        undescribed=1 if entry.missing_description else 0,
        language=language,
    )


# --------------------------------------------------------------------------
# Whole-deck generation
# --------------------------------------------------------------------------

@dataclass
class TranscriptResult:
    markdown: str
    slides: list[TranscriptSlide]
    total_in_deck: int
    undescribed: int
    language: str = "en"


def generate(deck_path: Path, version: str) -> TranscriptResult:
    if version not in STUDENT_VERSIONS:
        raise ValueError(
            f"Transcripts are generated for {' and '.join(STUDENT_VERSIONS)} "
            f"only, not {version!r} — see ALT_TEXT_NOTES.md."
        )

    language = deck_language_of(deck_path.read_text(encoding="utf-8"))
    strings = STRINGS[language]
    version_labels = _VERSION_LABELS_BY_LANGUAGE[language]

    entries = alt_images.load_store()
    slide_notes = alt_images.load_slide_notes()
    deck_slides = resolve_deck(deck_path, version)
    rendered: list[TranscriptSlide] = []
    chapters: list[int] = []
    missing_files: list[str] = []

    for deck_slide in deck_slides:
        if not deck_slide.included:
            continue
        entry = render_slide(deck_slide, version, entries, slide_notes, language=language)
        if entry is None:
            missing_files.append(deck_slide.path.name)
            continue
        rendered.append(entry)
        chapters.append(deck_slide.chapter)
    _fill_chapter_agendas(rendered, chapters, language)
    _fill_deck_tocs(rendered, chapters, _section_titles(deck_path), language)

    undescribed = sum(1 for s in rendered if s.missing_description)

    lines = [
        f"# {strings['transcript_title'].format(deck=deck_path.stem)}",
        "",
        strings["deck_label"].format(deck=deck_path.stem, version=version_labels[version]),
        strings["slides_label"].format(n=len(rendered), total=len(deck_slides)),
        "",
        strings["intro"],
        "",
    ]
    if undescribed:
        lines += [strings["undescribed_warning"].format(n=undescribed), ""]
    if missing_files:
        lines += [
            strings["missing_files_warning"].format(
                n=len(missing_files), files=", ".join(missing_files[:5])
            ),
            "",
        ]
    lines.append("---")
    lines.append("")

    for entry in rendered:
        lines += _entry_markdown_lines(entry, language=language)

    return TranscriptResult(
        markdown="\n".join(lines),
        slides=rendered,
        total_in_deck=len(deck_slides),
        undescribed=undescribed,
        language=language,
    )


# --------------------------------------------------------------------------
# HTML delivery
# --------------------------------------------------------------------------

# A deliberately small Markdown subset -- exactly the constructs generate()
# emits, nothing more. A general Markdown library would be a second
# dependency in a project that declares one, to render output we control the
# shape of.
_H_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)-\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)\d+\.\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline_html(text: str) -> str:
    out = _html.escape(text, quote=False)
    out = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _LINK_RE.sub(
        # The full line was escaped above; decode the URL once before
        # escaping it for an HTML attribute, or "&" becomes "&amp;amp;".
        lambda m: f'<a href="{_html.escape(_html.unescape(m.group(2)), quote=True)}">{m.group(1)}</a>',
        out)
    out = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def markdown_to_html_body(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    list_stack: list[tuple[int, str]] = []       # (indent, tag)
    paragraph: list[str] = []
    in_quote = False

    def close_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{_inline_html(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_lists(to_indent: int = -1) -> None:
        while list_stack and list_stack[-1][0] > to_indent:
            out.append(f"</{list_stack.pop()[1]}>")

    def close_quote() -> None:
        nonlocal in_quote
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            close_paragraph()
            index += 1
            continue

        # Fenced code block (```lang ... ```): a \SMCodeFile listing.
        if stripped.startswith("```"):
            close_paragraph(); close_lists(); close_quote()
            language = stripped[3:].strip()
            index += 1
            code: list[str] = []
            while index < len(lines) and lines[index].strip() != "```":
                code.append(lines[index])
                index += 1
            index += 1
            css = f' class="language-{_html.escape(language)}"' if language else ""
            out.append(f"<pre><code{css}>{_html.escape(chr(10).join(code), quote=False)}</code></pre>")
            continue

        # Table: a header row followed by a |---|---| separator.
        if (stripped.startswith("|") and index + 1 < len(lines)
                and _TABLE_SEP_RE.match(lines[index + 1].strip())):
            close_paragraph(); close_lists(); close_quote()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            out.append("<table><thead><tr>"
                       + "".join(f'<th scope="col">{_inline_html(c)}</th>'
                                 for c in header)
                       + "</tr></thead><tbody>")
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [c.strip() for c in lines[index].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline_html(c)}</td>"
                                            for c in cells) + "</tr>")
                index += 1
            out.append("</tbody></table>")
            continue

        heading = _H_RE.match(stripped)
        if heading:
            close_paragraph(); close_lists(); close_quote()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
            index += 1
            continue

        if stripped == "---":
            close_paragraph(); close_lists(); close_quote()
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            close_paragraph(); close_lists()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            content = stripped[1:].strip()
            if content:
                out.append(f"<p>{_inline_html(content)}</p>")
            index += 1
            continue
        close_quote()

        bullet = _BULLET_RE.match(line)
        ordered = _ORDERED_RE.match(line)
        if bullet or ordered:
            close_paragraph()
            match = bullet or ordered
            indent = len(match.group(1))
            tag = "ul" if bullet else "ol"
            close_lists(indent)
            if not list_stack or list_stack[-1][0] < indent:
                out.append(f"<{tag}>")
                list_stack.append((indent, tag))
            out.append(f"<li>{_inline_html(match.group(2))}</li>")
            index += 1
            continue

        close_lists()
        paragraph.append(stripped)
        index += 1

    close_paragraph(); close_lists(); close_quote()
    return "\n".join(out)


_HTML_SHELL = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font: 1rem/1.65 system-ui, -apple-system, "Segoe UI", sans-serif;
    max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 6rem;
    color: #16181d; background: #fff;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6e8ec; background: #16181d; }}
    a {{ color: #8ab4f8; }}
    th, td {{ border-color: #3a3f4a; }}
    blockquote {{ border-left-color: #5a6270; }}
  }}
  h1 {{ font-size: 1.75rem; line-height: 1.25; }}
  h2 {{ font-size: 1.3rem; margin-top: 2.5rem; }}
  h3 {{ font-size: 1.05rem; margin-top: 1.75rem; }}
  hr {{ border: 0; border-top: 1px solid currentColor; opacity: .18; margin: 2rem 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #c9ced8; padding: .4rem .6rem; text-align: left; }}
  th {{ font-weight: 600; }}
  blockquote {{
    margin: 1rem 0; padding: .25rem 0 .25rem 1rem;
    border-left: 4px solid #9aa3b2;
  }}
  code {{ font-family: ui-monospace, Consolas, monospace; font-size: .92em; }}
  pre {{ overflow-x: auto; padding: .6rem .8rem; border: 1px solid #c9ced8; border-radius: 4px; }}
  :focus-visible {{ outline: 3px solid #2f6feb; outline-offset: 2px; }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def to_html(result: TranscriptResult, title: str) -> str:
    return _HTML_SHELL.format(title=_html.escape(title, quote=False),
                              body=markdown_to_html_body(result.markdown),
                              lang=result.language)


def resolve_transcript_location(deck: Deck, deck_path: Path, version: str) -> tuple[Path, str]:
    """Where this deck's transcript should land, and what its filename
    (without extension) should be: a deck-declared
    \\deckoutputfolder[transcript]{...} (deck_scan.py's OUTPUT_FOLDER_RE),
    falling back to the deck's own bare \\deckoutputfolder{...} (no
    "[...]" at all) if it has no [transcript]-specific line of its own --
    same "specific key, then the bare every-output fallback" chain
    compiler.resolve_output_location() already uses for PDF output, so a
    deck's one bare \\deckoutputfolder{path} line (its own documented
    "every version" fallback) covers transcripts too unless overridden.
    Falls back to transcripts/ + the usual "<deck>-<version>-transcript"
    stem only if the deck has neither.

    2026-09-17, direct report: a deck with only a bare
    \\deckoutputfolder{...} (no [transcript] line) still had its
    transcript land in transcripts/, not that folder -- this used to be a
    deliberate choice (a PDF-output folder shouldn't silently redirect
    transcripts too), but doesn't match how deck authors actually use the
    bare form: it's meant as "everything about this deck goes here", not
    "every PDF version except transcripts". [transcript] still exists
    for a deck that genuinely wants its transcripts somewhere else.

    If the declared path names a full file (has a suffix) rather than a
    bare folder, its own stem names both the .md and .html output --
    same "full filename, not just a folder" rule as
    compiler.resolve_output_location()."""
    default_stem = f"{deck_path.stem}-{version}-transcript"
    raw = deck.output_folders.get("transcript") or deck.output_folders.get(None)
    if raw is None:
        return PROJECT_ROOT / "transcripts", default_stem
    path = Path(raw)
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    if resolved.suffix:
        return resolved.parent, resolved.stem
    return resolved, default_stem


def write_transcript(deck_path: Path, version: str,
                     directory: Path | None = None,
                     filename_stem: str | None = None) -> tuple[Path, Path, TranscriptResult]:
    """Generate and write both formats. Returns (markdown path, html path, result)."""
    result = generate(deck_path, version)
    target_dir = directory or (PROJECT_ROOT / "transcripts")
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = filename_stem or f"{deck_path.stem}-{version}-transcript"

    md_path = target_dir / f"{stem}.md"
    html_path = target_dir / f"{stem}.html"
    md_path.write_text(result.markdown, encoding="utf-8")
    html_path.write_text(
        to_html(result, f"{deck_path.stem} — accessible transcript"),
        encoding="utf-8")
    return md_path, html_path, result
