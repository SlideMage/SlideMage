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
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import alt_blocks, alt_images, bibliography
from .deck_scan import PROJECT_ROOT, Deck

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
_SLIDE_CALL_RE = re.compile(
    r"\\(?P<cmd>slidefinal|slideversion|slide|omitslideversion|omitslide"
    r"|conditionalslide)\s*(?:\[(?P<versions>[^\]]*)\])?\s*\{(?P<id>[^}]*)\}"
    r"(?:\s*\{(?P<second>[^}]*)\})?"
)

_DECK_VERSION_RE = re.compile(r"\\deckversion\s*\[([^\]]*)\]")
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
    },
}

# \deckonly / \deckuncover / \deckvisible share one signature:
#     \deckXXX<overlay>[versions]{content}
# both optional parts defaulting to <1-> and all three versions.
_DECK_COND_RE = re.compile(
    r"\\(?:deckonly|deckuncover|deckvisible)\s*(?:<[^>]*>)?\s*(?:\[(?P<versions>[^\]]*)\])?\s*(?=\{)"
)


@dataclass
class DeckSlide:
    """One slide as it appears in a resolved deck."""

    number: int          # frame number, matching the compiled PDF
    slide_id: str
    path: Path
    included: bool       # False = counted for numbering but not in this version


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


# --------------------------------------------------------------------------
# Deck resolution
# --------------------------------------------------------------------------

def _versions_from(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or default


def deck_version_of(deck_text: str) -> str | None:
    """The version a deck file hard-codes, or None if it decides at compile time.

    Returns None when `\\deckversion[...]` holds a macro rather than a literal:
    SlideMage compiles each version by wrapping the deck and defining
    `\\deckversionoverride`, so most real decks read `\\deckversion[\\deckversionoverride]`
    and have no fixed version of their own. Informational only -- a transcript
    is always generated for an explicitly chosen version, never for whatever
    the file happens to say.
    """
    match = _DECK_VERSION_RE.search(alt_blocks.COMMENT_RE.sub("", deck_text))
    if not match:
        return VERSION_INSTRUCTOR          # the preamble's own default
    listed = _versions_from(match.group(1), (VERSION_INSTRUCTOR,))
    return listed[0] if listed[0] in _ALL_VERSIONS else None


def deck_language_of(deck_text: str) -> str:
    """"en"/"de" -- mirrors deck_version_of() above, for \\decklanguage[...]
    instead of \\deckversion[...]. Unlike deck_version_of(), always
    returns a concrete value rather than None: language is fixed per deck
    (not a per-compile-run choice the way version is -- see
    LANGUAGE_NOTES.md), so "\\decklanguage[\\decklanguageoverride]" (the
    macro-argument case, only ever used for SlideMage's own one-off
    render preview, never a real deck's own hardcoded line) falling
    through to the preamble's own "en" default is the right answer here,
    the same way it would be at actual compile time for any deck that
    doesn't set \\decklanguageoverride itself.

    Unlike deck_version_of()'s single .search() (fine there -- a macro
    match legitimately means "no single answer, informational only" for
    version), this deliberately scans every \\decklanguage[...] occurrence
    and picks the first *literal* one: every real deck's own
    \\ifdefined\\decklanguageoverride ... \\else \\decklanguage[en] ... \\fi
    boilerplate (see README.md/LANGUAGE_NOTES.md) puts the macro-argument
    branch textually *first*, so a plain first-match .search() would
    always see "\\decklanguageoverride" and fall through to the "en"
    default for every real deck, including ones whose actual hardcoded
    language is "de" -- caught by testing against a real deck file, not
    assumed."""
    text = alt_blocks.COMMENT_RE.sub("", deck_text)
    for match in _DECK_LANGUAGE_RE.finditer(text):
        value = match.group(1).strip()
        if value and not value.startswith("\\"):
            return value if value in STRINGS else "en"
    return "en"


def resolve_deck(deck_path: Path, version: str) -> list[DeckSlide]:
    """Every slide the deck contains, in order, flagged for this version.

    Excluded slides are kept in the list with `included=False` rather than
    dropped, because they still advance the frame counter in the compiled PDF
    -- so the numbers a transcript prints keep matching the numbers a student
    sees.
    """
    text = alt_blocks.COMMENT_RE.sub("", deck_path.read_text(encoding="utf-8"))
    slides: list[DeckSlide] = []
    number = 0

    for match in _SLIDE_CALL_RE.finditer(text):
        command = match.group("cmd")
        slide_id = match.group("id").strip()
        if not slide_id:
            continue
        number += 1

        if command in ("omitslide", "omitslideversion"):
            included = version == VERSION_INSTRUCTOR
        elif command == "conditionalslide":
            included = version in _versions_from(match.group("versions"),
                                                 _ALL_VERSIONS)
        else:
            included = True

        if command == "slideversion" and match.group("second"):
            filename = f"{slide_id}-v{match.group('second').strip()}.tex"
        elif command == "omitslideversion" and match.group("second"):
            filename = f"{slide_id}-v{match.group('second').strip()}.tex"
        else:
            filename = f"{slide_id}-current.tex"

        slides.append(DeckSlide(
            number=number,
            slide_id=slide_id.partition("-")[0],
            path=SLIDES_DIR / filename,
            included=included,
        ))
    return slides


def resolve_deck_conditionals(text: str, version: str) -> str:
    """Apply `\\deckonly` / `\\deckuncover` / `\\deckvisible` for one version.

    Keeps the braced content when the version qualifies and drops it entirely
    when it does not.

    The instructor short-circuit in the preamble (`\\ifgothamInstructorVersion`
    renders the content whatever `[versions]` says) is reproduced here for
    completeness, even though only student versions are ever generated -- so
    this function stays correct if that ever changes.
    """
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
# Environments that only wrap; their content is kept, the wrapper discarded.
_UNWRAP_ENVIRONMENTS = ("minipage", "center", "column", "columns", "figure",
                        "table", "adjustbox")
# Beamer-style blocks: rendered as a titled quote so the label survives.
_BLOCK_ENVIRONMENTS = ("definitionblock", "infoblock", "gothamfloatinginfoblock",
                       "alertblock", "exampleblock", "block")
_LIST_ENVIRONMENTS = {
    "itemize": "-",
    "gothamalphaitemize": "-",
    "enumerate": "1.",
}

_ENV_OPEN_RE_CACHE: dict[str, re.Pattern] = {}


# Environments taking a mandatory argument after \begin{...}: minipage's
# width, column's width. Without consuming it the argument leaks into the
# transcript as stray text ("0.42" from \begin{minipage}{0.42\textwidth}).
_MANDATORY_ARG_ENVIRONMENTS = ("minipage", "column", "adjustbox")


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
        rendered = _convert_body(raw, depth + 1).strip()
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


def _render_block(body: str, label: str) -> str:
    """A beamer block becomes a titled Markdown quote."""
    title = ""
    stripped = body.lstrip()
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
    """Drop a table environment's leading mandatory argument(s)."""
    for _ in range(count):
        stripped = body.lstrip()
        if not stripped.startswith("{"):
            break
        _content, after = alt_blocks.braced_argument(stripped, 0)
        if after == 0:
            break
        body = stripped[after:]
    return body


def _render_table(body: str, spec_args: int = 1) -> str:
    body = _strip_column_spec(body, spec_args)
    """Best-effort LaTeX table to Markdown table.

    Deliberately conservative: rows are split on `\\\\` and cells on `&`, and
    anything that doesn't look rectangular is emitted as plain lines instead of
    a malformed table. A wrong table is harder to read than no table.
    """
    body = re.sub(r"\\(?:hline|toprule|midrule|bottomrule|rowcolor\{[^}]*\})", "",
                  body)
    rows = [r.strip() for r in re.split(r"\\\\", body) if r.strip()]
    cells = [[_inline_markdown(c).strip() for c in row.split("&")] for row in rows]
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
    (re.compile(r"\\texttt\s*\{"), "`", "`"),
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
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
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


def _convert_body(text: str, depth: int = 0) -> str:
    text = _GRAPHICS_RE.sub(" ", text)
    text = _CONDITIONAL_PAUSE_RE.sub(" ", text)
    text = _BOX_TO_RE.sub(" ", text)
    text = _DIMENSION_RE.sub(" ", text)
    for name in _DROP_ENVIRONMENTS:
        text = _transform_environments(text, name, lambda _body: "")
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

_MULTILINGUAL_NEEDLE = "\\multilingualtext{"


def _resolve_multilingual_text(text: str, language: str) -> str:
    """Replaces every \\multilingualtext{EN}{DE} call with just its EN or
    DE argument, mirroring \\ifgothamGerman's own choice at compile time
    (Slidemaster_preamble_base.tex) -- brace-matched
    (alt_blocks.braced_argument), not a naive regex, since either argument
    can itself contain a braced macro (e.g. \\textbf{...}).

    Must run before title/body extraction: a "mult" slide's transcript
    otherwise showed *both* languages concatenated together (2026-08-25,
    reported directly against g6q) -- alt_blocks._slide_title()'s own
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

    stripped = alt_blocks.COMMENT_RE.sub("", source_text)
    stripped = resolve_deck_conditionals(stripped, version)

    # \note{} is removed before anything else looks at the text. Instructor
    # notes must never reach a student transcript, and dropping them at the
    # front is a stronger guarantee than filtering later.
    body, _notes = alt_blocks.extract_macro_calls(stripped, "note")
    body, sources = alt_blocks.extract_macro_calls(body, "source")

    slide_id, title = alt_blocks._slide_title(source_text, deck_slide.path)

    begin = alt_blocks.FRAME_OPEN_RE.search(body)
    end = _FRAME_END_RE.search(body)
    if begin and end:
        _title_arg, after_title = alt_blocks.braced_argument(body, begin.end() - 1)
        if after_title < end.start():
            body = body[after_title:end.start()]
    else:
        # \titleframe{title}{subtitle}/\fullbleedframe{path} are commands,
        # not environments, so they never match FRAME_OPEN_RE/_FRAME_END_RE
        # above -- without this branch, `body` stayed the *entire* raw
        # stripped source (this slide's own macro call included), and
        # _convert_body() below only strips bare macro *names*, leaving
        # brace-argument content (a version string, a raw image path)
        # flattened into the transcript text. The title slide's own title
        # is already captured separately via _slide_title() above, so only
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
    entry = TranscriptSlide(
        number=deck_slide.number,
        slide_id=slide_id,
        title=title,
        body=_convert_body(body).strip(),
        source=_inline_markdown(" ".join(sources)).strip(),
        summary=notes.summary if notes else "",
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


def generate_single_slide(
    source_text: str, bare_id: str, version: str, language: str
) -> TranscriptResult:
    """qt_slide_source_tab.py's own "Render transcript" button (2026-08-25)
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
    a real Path, and alt_blocks._slide_title()/entry.takeaway_for() derive
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
    missing_files: list[str] = []

    for deck_slide in deck_slides:
        if not deck_slide.included:
            continue
        entry = render_slide(deck_slide, version, entries, slide_notes, language=language)
        if entry is None:
            missing_files.append(deck_slide.path.name)
            continue
        rendered.append(entry)

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
        lambda m: f'<a href="{_html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
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
