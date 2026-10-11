"""Slide-scanning utilities shared by the accessibility system: which images
a slide references, its id/title, and a few brace-matching helpers TeX text
needs that a naive regex gets wrong.

Formerly also read/wrote a `%%ALT` comment block at the bottom of each slide
file. That block (and `media/alt-text.csv`, alt_manifest.py's former CSV
half of the same store) was retired 2026-08-14 in favor of a single
per-image JSON store -- see alt_images.py's own docstring for why. Nothing
describing an image lives in a slide file any more; this module now only
answers "what does this slide reference and what is it called."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .deck_scan import PROJECT_ROOT
from .tex_source import COMMENT_RE

INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")

# \chapterlogo{path} and \begin{sideimageframe}{title}{path} both take a
# literal image path as one of their own arguments, even though the
# \includegraphics{...} they internally feed it to is itself macro-valued
# (\SMChapterLogoPath, #3) and therefore invisible to INCLUDEGRAPHICS_RE
# above. Missing these cost real coverage: checked directly against the
# real project, 2026-08-16 -- 105 of 281 images (~37%) had an empty
# `used_on` in alt-text.json purely because they're only ever placed
# through one of these two frame helpers, never a bare \includegraphics.
CHAPTERLOGO_RE = re.compile(r"\\chapterlogo\s*\{")
SIDEIMAGEFRAME_RE = re.compile(r"\\begin\{sideimageframe\}(?:\[[^\]]*\])?\s*\{")

# \titleframe{title}{subtitle} and \fullbleedframe{path} are *commands*,
# not environments (Slidemaster_preamble_base.tex) -- a slide using either
# never contains \begin{...frame}/\end{...frame} text at all, so
# FRAME_OPEN_RE below (which only matches the \begin{...frame} form) never
# matches them. \fullbleedframe's one brace argument is a literal image
# path, same shape as \chapterlogo above. Added 2026-09-17 after finding
# that both were previously invisible to referenced_images() (a
# \fullbleedframe slide's image got zero description entry) and that
# render_slide() (transcript.py) fell through to dumping the whole raw,
# unstripped source as transcript body text for lack of a frame to slice
# out of -- see that module's own render_slide() comment for the other
# half of this fix.
TITLEFRAME_RE = re.compile(r"\\titleframe\s*\{")
FULLBLEEDFRAME_RE = re.compile(r"\\fullbleedframe\s*\{")

# \SMMugshot{coord}{path}{diameter}{caption} -- the small circular
# portrait photos (Fama, Modigliani, Miller, Thaler, ...). Its own 2nd
# argument is a real literal path, same shape as sideimageframe's 2nd
# argument above; found 2026-08-17 while correlating image sources against
# \source{} calls -- 3 slides (4uq, 6j4, yke) use *only* this macro for
# their images, so they were entirely invisible to scan_slides_raw() (zero
# detected images -> skipped outright), and h36's Thaler photo was silently
# missing from an otherwise-detected slide. Same root cause as the
# chapterlogo/sideimageframe gap above: \includegraphics{#2} inside the
# macro body is templated, not literal, so only the call site carries a
# real path.
MUGSHOT_RE = re.compile(r"\\SMMugshot\s*\{")

# \cornerfigure[keys]{file}, \begin{besidefigure}[keys]{file},
# \fitfigure[keys]{file}, \sectionfigure[keys]{file} (the v5.x figure
# helpers, Slidemaster_preamble_base.tex): the argument is the image file
# -- for \cornerfigure/besidefigure only with a width= or height= key, else
# it is arbitrary content, whose own \includegraphics INCLUDEGRAPHICS_RE
# finds. They were invisible to referenced_images() until 2026-10-04 (found
# in the SlideMage manual: an image placed only with besidefigure had no
# slide in its `used_on`, so no takeaway and no transcript entry).
FIGURE_HELPER_RE = re.compile(
    r"\\(?:cornerfigure|fitfigure|sectionfigure|begin\{besidefigure\})\s*(?:\[[^\]]*\])?\s*\{")

# \begin{tikzillustration}[options]{ID} ... \end{tikzillustration}
# (Slidemaster_preamble_base.tex) -- a hand-drawn tikz diagram with no
# media/ file behind it at all. Its own ID is the only thing that
# identifies it (there is no filename to hash), so -- unlike every macro
# above -- this one also needs its own *options* and *body* extracted, not
# just its argument: see referenced_tikz_illustrations()/
# find_tikz_illustration() below, and alt_images.py for how "tikz:ID" is
# treated as a synthetic image path throughout the rest of the
# accessibility system.
#
# The options group is capturing (not `(?:...)`) -- tikz_render.py has to
# pass it through unchanged when it recompiles this illustration standalone
# for a preview/draft. Dropping it silently degrades a style set through a
# *built-in* tikz hook (e.g. `every node/.style={font=\footnotesize}` just
# renders with the default font instead) but hard-fails with "I do not know
# the key '/tikz/box'" the moment the body references a *custom* style name
# the options block itself defined (`box/.style={...}`, then `\node[box]`
# later in the body) -- found directly, 2026-09-14, against five real
# illustrations whose options define exactly that kind of custom style.
TIKZILLUSTRATION_RE = re.compile(r"\\begin\{tikzillustration\}(\[[^\]]*\])?\s*\{")
TIKZILLUSTRATION_END = "\\end{tikzillustration}"

# Suffixes tried when a slide references an image without one (graphicx
# picks the suffix itself). Same list, same order, as alt_images.py.
_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".eps")


# --------------------------------------------------------------------------
# Brace-matching helpers
# --------------------------------------------------------------------------

def braced_argument(text: str, open_index: int) -> tuple[str, int]:
    """Content of the brace group starting at `open_index`, and the index after it.

    Brace-matched, skipping escaped characters. Returns ("", open_index) if the
    group is unbalanced.
    """
    if open_index >= len(text) or text[open_index] != "{":
        return "", open_index
    depth = 0
    cursor = open_index
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:cursor], cursor + 1
        cursor += 1
    return "", open_index


def _control_sequence_at(text: str, index: int) -> tuple[str, int] | None:
    """Return a TeX control sequence and its end offset at index.

    Control words contain letters (and @); a backslash followed by any
    other character is a one-character control symbol. Treating symbols as
    tokens is important here: in \\\\note the first two backslashes are
    one control symbol, so the remaining letters are not a \\note call.
    """
    if index >= len(text) or text[index] != "\\" or index + 1 >= len(text):
        return None
    cursor = index + 1
    if text[cursor].isalpha() or text[cursor] == "@":
        cursor += 1
        while cursor < len(text) and (text[cursor].isalpha() or text[cursor] == "@"):
            cursor += 1
        return text[index + 1:cursor], cursor
    return "", cursor + 1


def _iter_tex_commands(text: str):
    """Yield active TeX control words as (name, start, end) triples.

    Comments, \\verb literals, and the token consumed by \\string are skipped
    so source examples are not mistaken for executable macros. This is
    intentionally a small lexer, not a TeX expansion engine.
    """
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "%":
            newline = text.find("\n", cursor)
            cursor = len(text) if newline == -1 else newline + 1
            continue
        if char != "\\":
            cursor += 1
            continue

        token = _control_sequence_at(text, cursor)
        if token is None:
            cursor += 1
            continue
        name, end = token
        if name == "verb":
            delimiter_at = end + (1 if end < len(text) and text[end] == "*" else 0)
            if delimiter_at < len(text) and text[delimiter_at] not in "\r\n":
                delimiter = text[delimiter_at]
                literal_end = text.find(delimiter, delimiter_at + 1)
                cursor = len(text) if literal_end == -1 else literal_end + 1
                continue
        if name == "string":
            literal_at = end
            while literal_at < len(text) and text[literal_at].isspace():
                literal_at += 1
            literal = _control_sequence_at(text, literal_at)
            cursor = literal[1] if literal else min(literal_at + 1, len(text))
            continue
        if name:
            yield name, cursor, end
        cursor = end


def _delimited_group_end(text: str, open_index: int, opening: str, closing: str) -> int | None:
    """Find the end of a balanced optional angle or square group."""
    if open_index >= len(text) or text[open_index] != opening:
        return None
    depth = 1
    brace_depth = 0
    cursor = open_index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1
        elif not brace_depth and char == opening:
            depth += 1
        elif not brace_depth and char == closing:
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    return None


def extract_note_calls(text: str, *, mask: bool = False) -> tuple[str, list[str]]:
    r"""Remove Beamer \note commands with optional overlay/options.

    Supported forms include \note {...}, \note<2>{...}, and
    \note<2>[item]{...}. The argument uses the same nested-brace parser
    as other slide macros. Control-sequence tokenization avoids matching
    longer names such as \noteworthy or escaped/stringified examples.
    With `mask=True`, replace notes with spaces while preserving offsets and newlines.
    """
    remainder: list[str] = []
    arguments: list[str] = []
    index = 0
    copied_through = 0

    for name, found, command_end in _iter_tex_commands(text):
        if name != "note" or found < index:
            continue

        cursor = command_end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        seen: set[str] = set()
        while cursor < len(text) and text[cursor] in "<[":
            marker = text[cursor]
            if marker in seen:
                break
            seen.add(marker)
            after_group = _delimited_group_end(
                text, cursor, marker, ">" if marker == "<" else "]"
            )
            if after_group is None:
                break
            cursor = after_group
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1

        content, after = braced_argument(text, cursor)
        if after == cursor:
            continue

        remainder.append(text[copied_through:found])
        if mask:
            remainder.append(re.sub(r"[^\n]", " ", text[found:after]))
        arguments.append(content)
        copied_through = after
        index = after

    remainder.append(text[copied_through:])
    return "".join(remainder), arguments


def extract_macro_calls(text: str, macro: str) -> tuple[str, list[str]]:
    """Remove every `\\macro{...}` from `text`; return (remainder, arguments).

    Brace-matched, for the reason spelled out in `_slide_title` below: a
    non-greedy `\\macro\\{(.*?)\\}` stops at the first closing brace, which is
    the wrong one whenever the argument itself contains a braced macro.
    """
    if macro == "note":
        return extract_note_calls(text)

    needle = f"\\{macro}{{"
    remainder: list[str] = []
    arguments: list[str] = []
    index = 0
    while True:
        found = text.find(needle, index)
        if found == -1:
            remainder.append(text[index:])
            return "".join(remainder), arguments
        remainder.append(text[index:found])
        content, after = braced_argument(text, found + len(needle) - 1)
        if after == found + len(needle) - 1:  # unbalanced; consume the rest
            arguments.append(text[found + len(needle):])
            return "".join(remainder), arguments
        arguments.append(content)
        index = after


FRAME_OPEN_RE = re.compile(
    r"\\begin\{((?:standard|figure|section|highlight|quote|title|sideimage)frame)\}"
    r"(?:\[[^\]]*\])?\s*\{"
)


def frame_type(source: str) -> Optional[str]:
    """The frame a slide is made of: the environment of its \\begin{standardframe}
    (and kin) or "titleframe" for the \\titleframe command; None if neither is found."""
    stripped = COMMENT_RE.sub("", source)
    match = FRAME_OPEN_RE.search(stripped)
    if match:
        return match.group(1)
    return "titleframe" if TITLEFRAME_RE.search(stripped) else None


def _slide_title(source: str, slide_path: Path) -> tuple[str, str]:
    """(slide id, human title). Frame title if parseable, else the filename.

    The title argument is brace-matched, not regex-matched. 70 slide files
    carry a braced macro inside the frame title -- almost always a
    `\\footnote{... \\fullcite{key} ...}` citation -- and a non-greedy `\\{(.*?)\\}`
    cuts at the *inner* brace, producing titles like "Influence of different
    types of estimation errorAdapted from ernst2015". The footnote is then
    dropped outright: it is a citation, not part of the slide's name.
    """
    stem = slide_path.stem
    if stem.endswith("-current"):
        stem = stem[: -len("-current")]
    slide_id, _, slug = stem.partition("-")

    stripped = extract_note_calls(COMMENT_RE.sub("", source))[0]
    # FRAME_OPEN_RE's own "title" alternative matches \begin{titleframe}{,
    # which never actually occurs -- \titleframe is a *command*
    # (\titleframe{title}{subtitle}), not an environment (see
    # TITLEFRAME_RE's own comment above), so a real title-slide file never
    # matches FRAME_OPEN_RE at all and used to fall through to the slug
    # fallback below. Tried as a second match, not folded into
    # FRAME_OPEN_RE itself, since its own brace-matching (first argument
    # only) differs from every \begin{...frame} case.
    match = FRAME_OPEN_RE.search(stripped) or TITLEFRAME_RE.search(stripped)
    if match:
        raw_title, _ = braced_argument(stripped, match.end() - 1)
        raw_title, _footnotes = extract_macro_calls(raw_title, "footnote")
        title = " ".join(raw_title.split())
        title = re.sub(r"\\[a-zA-Z]+\*?", "", title).replace("{", "").replace("}", "")
        title = " ".join(title.split()).strip(" *")
        if title:
            return slide_id, title
    # the slug without its language segment ("EN-Quote-Demo" -> "Quote Demo")
    language, _, rest = slug.partition("-")
    if language in ("EN", "DE", "mult") and rest:
        slug = rest
    return slide_id, slug.replace("-", " ")


# --------------------------------------------------------------------------
# Image references
# --------------------------------------------------------------------------

def _clean_reference(raw: str) -> str | None:
    reference = raw.strip()
    if not reference or "\\" in reference or "#" in reference:
        return None
    return reference


# "tikz:" + an illustration's own ID is this system's synthetic stand-in for
# a real media/ path everywhere a reference is a plain string -- alt_images.py
# treats it as just another ImageEntry key (no file, no bytes to hash), and
# alt_draft.py renders it on the fly instead of reading it off disk. Defined
# here (the lower module in this project's import order -- alt_images.py
# already imports alt_blocks, not the reverse) so both share the one literal
# rather than each hardcoding "tikz:" independently.
TIKZ_PREFIX = "tikz:"


def referenced_tikz_illustrations(source: str) -> list[tuple[str, str, str]]:
    """(illustration id, its own [options] verbatim or "", raw tikz body)
    for every `\\begin{tikzillustration}[options]{ID} ... \\end{tikzillustration}`
    in `source`.

    The options string is returned verbatim (including its own brackets, or
    "" when the call has none) precisely because tikz_render.py has to
    reproduce it unchanged when recompiling this illustration standalone --
    see TIKZILLUSTRATION_RE's own comment for the real failure this fixed
    (a custom style defined in the options, referenced later in the body,
    silently vanishing from a standalone recompile that dropped the
    options).

    Body extraction is a plain literal search for the environment's own
    `\\end{tikzillustration}`, not brace-matching -- this environment isn't
    meant to nest, and its body is arbitrary tikz code full of braces that
    don't pair up the way a `{...}`-argument's do (coordinate/option groups,
    math), so braced_argument() (built for exactly one balanced argument) is
    the wrong tool for a whole environment body.

    Comments are stripped first (same COMMENT_RE as everywhere else in this
    module) for two reasons at once: it is what a version-note-tolerant
    staleness hash needs (see alt_images.tikz_source_hash(), same reasoning
    as slide_context_hash()), and it is *also* exactly the text
    tikz_render.py compiles, so the hash used to cache a render always
    matches what was actually rendered.
    """
    stripped = COMMENT_RE.sub("", source)
    results: list[tuple[str, str, str]] = []
    for match in TIKZILLUSTRATION_RE.finditer(stripped):
        options = match.group(1) or ""
        illustration_id, after_id = braced_argument(stripped, match.end() - 1)
        illustration_id = illustration_id.strip()
        if not illustration_id:
            continue
        end = stripped.find(TIKZILLUSTRATION_END, after_id)
        if end == -1:
            continue  # unclosed environment -- skip rather than guess
        results.append((illustration_id, options, stripped[after_id:end]))
    return results


def find_tikz_illustration(
    illustration_id: str, slides_dir: Path | None = None,
) -> tuple[Path, str, str] | None:
    """Which slide currently defines this tikz illustration, its own
    [options] (verbatim, or "" if none), and its own raw tikz body -- the
    source of truth tikz_render.py compiles from, since ImageEntry itself
    only ever stores a description, never the drawing. A plain linear scan
    across every slide, same cost class scan_slides_raw() already pays on
    every sync."""
    directory = slides_dir or (PROJECT_ROOT / "slides")
    for path in sorted(directory.glob("*-current.tex")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for found_id, options, body in referenced_tikz_illustrations(text):
            if found_id == illustration_id:
                return path, options, body
    return None


def referenced_images(source: str) -> list[str]:
    """Image paths a slide includes, as written, minus macro-valued ones.

    Three call shapes, each contributing a literal path: a bare
    `\\includegraphics{...}`, a `\\chapterlogo{...}` call (its own argument
    is a real path even though the `\\includegraphics{\\SMChapterLogoPath}`
    it feeds is itself macro-valued and gets skipped below), and
    `\\begin{sideimageframe}{title}{path}` (that environment's own second
    mandatory argument -- its *internal* `\\includegraphics{#3}` is
    templated, not literal, so only the call site itself carries a real
    path). Missing the latter two used to cost real coverage -- see
    CHAPTERLOGO_RE/SIDEIMAGEFRAME_RE's own comment above.

    A reference built from a macro or a macro argument (`\\SMChapterLogoPath`,
    a bare `#1` inside another macro's body) can't be resolved without
    expanding TeX, so it is skipped rather than guessed at. In practice those
    live in the preamble, not in slides/ -- slide files spell their paths out.
    """
    stripped = extract_note_calls(COMMENT_RE.sub("", source))[0]
    references = []

    for match in INCLUDEGRAPHICS_RE.finditer(stripped):
        reference = _clean_reference(match.group(1))
        if reference:
            references.append(reference)

    for match in CHAPTERLOGO_RE.finditer(stripped):
        content, _ = braced_argument(stripped, match.end() - 1)
        reference = _clean_reference(content)
        if reference:
            references.append(reference)

    for match in FULLBLEEDFRAME_RE.finditer(stripped):
        # Comma-separated list = layered build-step images (v3.23.0).
        content, _ = braced_argument(stripped, match.end() - 1)
        for part in content.split(","):
            reference = _clean_reference(part)
            if reference:
                references.append(reference)

    for match in SIDEIMAGEFRAME_RE.finditer(stripped):
        # match consumes through the *opening* brace of the title argument
        # (same convention FRAME_OPEN_RE/_slide_title above already use) --
        # skip past the title, then the very next brace group is the path.
        _title, after_title = braced_argument(stripped, match.end() - 1)
        cursor = after_title
        while cursor < len(stripped) and stripped[cursor].isspace():
            cursor += 1
        content, _ = braced_argument(stripped, cursor)
        reference = _clean_reference(content)
        if reference:
            references.append(reference)

    for match in MUGSHOT_RE.finditer(stripped):
        # Same "skip past the first argument, take the next brace group"
        # technique as sideimageframe above -- the path is #2, after #1
        # (the coordinate).
        _coord, after_coord = braced_argument(stripped, match.end() - 1)
        cursor = after_coord
        while cursor < len(stripped) and stripped[cursor].isspace():
            cursor += 1
        content, _ = braced_argument(stripped, cursor)
        reference = _clean_reference(content)
        if reference:
            references.append(reference)

    for match in FIGURE_HELPER_RE.finditer(stripped):
        content, _ = braced_argument(stripped, match.end() - 1)
        if "\\" in content or "\n" in content:
            continue  # arbitrary content (a block, an \includegraphics)
        reference = _clean_reference(content)
        if reference:
            references.append(reference)

    # Tikz illustrations join the same list, as synthetic "tikz:ID"
    # references -- everything downstream (SlideRow.images,
    # alt_images.sync_store()'s used_on population, the Images tab's own
    # per-slide list) treats "which images does this slide reference" as one
    # flat list of opaque reference strings already; this is what makes a
    # hand-drawn diagram show up in that same list with no changes needed
    # anywhere that only ever consumes SlideRow.images generically.
    for illustration_id, _options, _body in referenced_tikz_illustrations(stripped):
        references.append(f"{TIKZ_PREFIX}{illustration_id}")

    return sorted(set(references))


def replace_image_reference(source: str, old_reference: str, new_reference: str) -> tuple[str, int]:
    """Swaps every literal occurrence of `old_reference` for `new_reference`
    across the same five call shapes referenced_images() recognizes --
    `\\includegraphics{...}`, `\\chapterlogo{...}`, `\\fullbleedframe{...}`,
    `\\begin{sideimageframe}{title}{path}`, and
    `\\SMMugshot{coord}{path}{...}` -- for the Images tab's own "Replace
    image…" button (2026-09-18), which swaps a slide's reference to a
    freshly copied-in file. Returns the edited source and how many call
    sites actually changed (0 if `old_reference` isn't used here at all --
    e.g. a slide listed from ImageEntry.used_on that turns out to reference
    the image under a differently-spelled path).

    Deliberately does *not* strip comments first, unlike referenced_images()
    -- this is a textual edit, and the replacement spans below are offsets
    into `source` exactly as given; remapping them back through a
    comment-stripped copy isn't worth it for what would only ever affect an
    identical reference sitting inside an already-commented-out call (inert
    either way).
    """
    spans: list[tuple[int, int]] = []

    for match in INCLUDEGRAPHICS_RE.finditer(source):
        start, end = match.span(1)
        if _clean_reference(source[start:end]) == old_reference:
            spans.append((start, end))

    for match in CHAPTERLOGO_RE.finditer(source):
        content, after = braced_argument(source, match.end() - 1)
        if after != match.end() - 1 and _clean_reference(content) == old_reference:
            spans.append((match.end(), after - 1))

    for match in FULLBLEEDFRAME_RE.finditer(source):
        content, after = braced_argument(source, match.end() - 1)
        if after == match.end() - 1:
            continue
        offset = match.end()
        for part in content.split(","):
            if _clean_reference(part) == old_reference:
                lead = len(part) - len(part.lstrip())
                spans.append((offset + lead, offset + len(part.rstrip())))
            offset += len(part) + 1

    for match in SIDEIMAGEFRAME_RE.finditer(source):
        _title, after_title = braced_argument(source, match.end() - 1)
        cursor = after_title
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        content, after = braced_argument(source, cursor)
        if after != cursor and _clean_reference(content) == old_reference:
            spans.append((cursor + 1, after - 1))

    for match in MUGSHOT_RE.finditer(source):
        _coord, after_coord = braced_argument(source, match.end() - 1)
        cursor = after_coord
        while cursor < len(source) and source[cursor].isspace():
            cursor += 1
        content, after = braced_argument(source, cursor)
        if after != cursor and _clean_reference(content) == old_reference:
            spans.append((cursor + 1, after - 1))

    if not spans:
        return source, 0

    result = source
    for start, end in sorted(spans, reverse=True):
        result = result[:start] + new_reference + result[end:]
    return result, len(spans)


def resolve_image(reference: str) -> Path | None:
    candidate = PROJECT_ROOT / reference
    if candidate.is_file():
        return candidate
    if not candidate.suffix:
        for suffix in _SUFFIXES:
            with_suffix = candidate.with_name(candidate.name + suffix)
            if with_suffix.is_file():
                return with_suffix
    return None


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

@dataclass
class SlideRow:
    """One slide file: what it's called and what images it references.

    Deliberately minimal -- no review state here any more, since that now
    lives entirely in alt_images.py's per-image store, computed per (image,
    slide) pair rather than once per slide file.
    """

    path: Path
    slide_id: str
    title: str
    images: list[str] = field(default_factory=list)


def scan_slides_raw(slides_dir: Path | None = None) -> list[SlideRow]:
    """Every slide that includes at least one image.

    Slides with no images are skipped entirely rather than listed as
    "nothing to describe" -- three quarters of slides/ has no image, and a
    review list padded with them is unusable.
    """
    directory = slides_dir or (PROJECT_ROOT / "slides")
    results: list[SlideRow] = []

    for path in sorted(directory.glob("*-current.tex")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        images = referenced_images(text)
        if not images:
            continue
        slide_id, title = _slide_title(text, path)
        results.append(SlideRow(path=path, slide_id=slide_id, title=title, images=images))
    return results
