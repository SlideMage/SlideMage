# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The text rules of the source editor, without Qt: what each insert command,
format button and Enter key does to the LaTeX text, and a few file-level
helpers (reindenting, the hyperlink command, the header comment, the citation
key of a .bib entry).

The editor widget (ui/workspace/source_editor.py) only turns a cursor position
and a selection into the arguments of these functions and puts the result
back. An `Edit` is text that replaces the selection (or is inserted at the
cursor) plus where the cursor goes afterwards, as an offset into that text.
Offsets in an `Edit` count characters; the editor translates them to Qt's
UTF-16 positions with `utf16_len()`.
"""
from __future__ import annotations

import re
import struct
from typing import NamedTuple, Optional
from urllib.parse import quote, urlsplit

from . import slide_import
from .tex_source import braced_argument

# The editor's tab width: Settings -> General stores it under this key.
DEFAULT_TAB_WIDTH_CHARS = 2
TAB_WIDTH_SETTING_KEY = "tab_width_chars"


class Edit(NamedTuple):
    text: str
    caret: int   # cursor offset within `text` after the edit


def utf16_len(text: str) -> int:
    """Length of `text` in UTF-16 code units, which is how Qt counts positions."""
    return len(text.encode("utf-16-le")) // 2


def utf16_units(text: str) -> str:
    """`text` with every character outside the BMP as two surrogate "characters",
    so that an index into the result is a Qt position."""
    data = text.encode("utf-16-le")
    return "".join(map(chr, struct.unpack(f"<{len(data) // 2}H", data)))


# -- reindenting ----------------------------------------------------------------

# Only `\begin{}`/`\end{}` tokens at the start of a line count, the same scope
# as the editor's smart Enter: a full brace-nesting indenter would also have to
# reason about braces inside math and macro arguments, which slides use
# constantly and unpredictably (\textcolor{}{}, nested \footnote{\fullcite{}},
# tikz node options). Environment nesting alone is unambiguous and matches
# every slide file's convention: the frame's \begin{standardframe}{...} sits
# flush left, its body one tab in, a nested \begin{itemize} one tab deeper.
_REINDENT_BEGIN_RE = re.compile(r"^\\begin\{")
_REINDENT_END_RE = re.compile(r"^\\end\{")


def reindent_latex(text: str) -> str:
    """Recompute every line's leading whitespace from its \\begin{}/\\end{}
    nesting depth (one tab per level), leaving the rest of each line, and
    blank lines (left truly empty rather than tab-filled), untouched. A line
    at \\end{} dedents before its own indent is assigned, so it lines up with
    its \\begin{}; the depth is clamped at 0 for an unmatched \\end{} (a bug
    elsewhere in the file that this should not amplify)."""
    depth = 0
    out_lines = []
    for line in text.split("\n"):
        content = line.strip()
        if not content:
            out_lines.append("")
            continue
        content = line.lstrip(" \t")
        if _REINDENT_END_RE.match(content):
            depth = max(0, depth - 1)
        out_lines.append(("\t" * depth) + content)
        if _REINDENT_BEGIN_RE.match(content):
            depth += 1
    return "\n".join(out_lines)


def comment_ops(lines: list[str]) -> list[tuple[int, int, str]]:
    """Ctrl+/ on `lines`: per line (column, characters to delete, text to insert).
    "Comment wins" on a mixed selection as in most editors: when every
    non-blank line is already commented, the first % of each is removed,
    otherwise every line (blank ones too, so that a second toggle undoes the
    first) gets a % in column 0."""
    non_blank = [line for line in lines if line.strip()]
    if non_blank and all(line.lstrip().startswith("%") for line in non_blank):
        ops = []
        for line in lines:
            match = re.match(r"[ \t]*(%)", line)
            ops.append((match.start(1), 1, "") if match else (0, 0, ""))
        return ops
    return [(0, 0, "%")] * len(lines)


def outdent_width(line: str, tab_width: int) -> int:
    """Shift+Tab: how many leading characters of `line` make one indentation level -- a tab, or up to
    `tab_width` spaces (and a tab after fewer spaces, which ends the level)."""
    width = 0
    for count, char in enumerate(line, start=1):
        if char == "\t":
            return count
        if char != " ":
            return count - 1
        width += 1
        if width >= tab_width:
            return count
    return len(line)


# -- the hyperlink command --------------------------------------------------------

def format_hyperlink(word: str, url: str) -> str:
    """Build a clickable LaTeX hyperlink from plain visible text and a URL."""
    visible = word.strip()
    clean_url = url.strip()
    if not visible:
        raise ValueError("Enter the word or phrase to display.")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in clean_url):
        raise ValueError("The link URL must not contain spaces or control characters.")
    try:
        parts = urlsplit(clean_url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("Enter a full http:// or https:// link URL.")
        _ = parts.port
    except ValueError as exc:
        raise ValueError(f"Invalid link URL: {exc}") from exc

    # This project wraps hyperref's \href in a LaTeX macro, so URL characters
    # need protection before that macro reads its arguments. Percent-encode
    # braces, backslashes, and non-ASCII characters; preserve URL delimiters.
    encoded = quote(clean_url, safe=":/?#[]@!$&'()*+,;=%-._~")
    for char in "%#&_$":
        encoded = encoded.replace(char, "\\" + char)
    return f"\\href{{{encoded}}}{{{slide_import.escape_latex(visible)}}}"


# -- wrapping and inserting -------------------------------------------------------

LIST_ENVIRONMENTS = {"itemize", "enumerate"}


def wrap_macro(selected: str, macro: str) -> Edit:
    """\\macro{selection}, or \\macro{} with the cursor between the braces."""
    if selected:
        text = f"\\{macro}{{{selected}}}"
        return Edit(text, len(text))
    text = f"\\{macro}{{}}"
    return Edit(text, len(text) - 1)


def wrap_environment(
    selected: str, indent: str, env: str, *,
    item_prefix: str = "\\item ", leading_comment: Optional[str] = None,
) -> Edit:
    """A \\begin{env}/\\end{env} pair around the selection; with no selection an
    empty line is left in between with the cursor on it. \\end{env} gets the
    indentation of the line the selection starts on.

    itemize/enumerate get extra care: with no selection the body is seeded with
    `item_prefix`, as pressing Enter after a typed \\begin{itemize} does; with
    a selection each non-blank line becomes its own item (turning typed lines
    into a list is the point of selecting them), a selection of only blank
    lines still gets one empty item. `leading_comment`, when given, is a line
    of its own before \\begin{env} (the ellipsis list reminds the editor of the
    in-text \\ldots convention)."""
    is_list = env in LIST_ENVIRONMENTS
    comment_line = f"{leading_comment}\n{indent}" if leading_comment else ""
    end = f"\n{indent}\\end{{{env}}}"
    if not selected:
        inner = f"{indent}\t{item_prefix}" if is_list else f"{indent}\t"
        before = f"{comment_line}\\begin{{{env}}}\n{inner}"
        return Edit(before + end, len(before))
    if is_list:
        items = [f"{indent}\t{item_prefix}{line.strip()}" for line in selected.split("\n") if line.strip()]
        body = "\n".join(items) if items else f"{indent}\t{item_prefix}"
    else:
        body = selected
    text = f"{comment_line}\\begin{{{env}}}\n{body}{end}"
    return Edit(text, len(text))


def insert_multilingual(selected: str, macro: str) -> Edit:
    """For a two-argument macro like \\multilingualtext{EN}{DE}: the selection
    goes into the first braces (English, the macro's argument order) and the
    cursor lands in the empty second ones, ready for the translation; with no
    selection both are empty and the cursor lands in the first."""
    if not selected:
        return Edit(f"\\{macro}{{}}{{}}", len(f"\\{macro}{{"))
    text = f"\\{macro}{{{selected}}}{{}}"
    return Edit(text, len(text) - 1)


def wrap_block(selected: str, indent: str, env: str, floating: bool = False) -> Edit:
    """\\begin{env}{Title} ... \\end{env} (floating: \\begin{env}{5cm}{Title}):
    the selection becomes the body, else a blank indented line is left; the
    cursor lands in the title's braces either way."""
    begin = f"\\begin{{{env}}}" + ("{5cm}{}" if floating else "{}")
    body = selected if selected else f"{indent}\t"
    return Edit(f"{begin}\n{body}\n{indent}\\end{{{env}}}", len(begin) - 1)


class Insert(NamedTuple):
    """One entry of an insert menu. `kind` says what it does with `payload`:
    "literal" inserts the label itself (replacing the selection); "wrap_macro"
    wraps the selection as \\{payload}{...}; "wrap_env" in \\begin/\\end of
    environment `payload`; "wrap_env_ellipsis" the same with
    \\item[\\SMBulletEllipsis] items; "wrap_multilingual" a two-argument macro
    (see insert_multilingual); "wrap_block" and "wrap_block_floating" a
    beamer block (see wrap_block). "hyperlink" and "code_file" need the
    user's input first (format_hyperlink, code_file_call). `hint` is the
    LaTeX a menu shows beside a label that is not itself LaTeX."""
    label: str
    kind: str
    payload: Optional[str] = None
    hint: str = ""


# What needs the user's input before there is any text to insert.
ASKS = ("hyperlink", "code_file")

# The two that ask first, then the plain commands.
INSERT_COMMANDS = [
    Insert("Hyperlink…", "hyperlink", hint="\\href{URL}{text}"),
    Insert("Code file…", "code_file", hint="\\SMCodeFile{snippets/…}"),
    Insert("\\conditionalpause[instructor]", "literal"),
    Insert("\\only<2->{...}", "wrap_macro", "only<2->"),
    Insert("\\tallitem", "literal"),
    Insert("\\tallitemnobullet", "literal"),
    # all list levels one font size smaller, for a slide whose text doesn't
    # fit; goes inside the frame -- change the 1 to 2 for two sizes smaller
    Insert("\\shrinklists{1}", "literal"),
    Insert("Both languages", "wrap_multilingual", "multilingualtext", "\\multilingualtext{EN}{DE}"),
]

INSERT_LIST_COMMANDS = [
    Insert("Bulleted list", "wrap_env", "itemize", "\\begin{itemize}"),
    Insert("Bulleted list, ellipses", "wrap_env_ellipsis", "itemize", "\\item[\\SMBulletEllipsis]"),
    Insert("Numbered list", "wrap_env", "enumerate", "\\begin{enumerate}"),
]

# The beamer blocks this project defines (SlideMage_base.tex,
# slides/ZZX-EN-Definition-formula-current.tex shows them side by side).
INSERT_BLOCK_COMMANDS = [
    Insert(label, kind, env, f"\\begin{{{env}}}") for label, kind, env in (
        ("Block", "wrap_block", "block"),
        ("Example block", "wrap_block", "exampleblock"),
        ("Alert block", "wrap_block", "alertblock"),
        ("Reference block", "wrap_block", "referenceblock"),
        ("Definition block", "wrap_block", "definitionblock"),
        ("Info block", "wrap_block", "infoblock"),
        ("Floating block", "wrap_block_floating", "SMFloatingBlock"),
        ("Floating example block", "wrap_block_floating", "SMFloatingExampleBlock"),
        ("Floating info block", "wrap_block_floating", "SMFloatingInfoBlock"),
    )
]


def code_file_call(path: str, keys: str = "") -> str:
    """\\SMCodeFile[keys]{path}: LaTeX source a slide shows from a file at
    `path`, relative to the project folder (`keys` are listings options such
    as firstline=3)."""
    path, keys = path.strip(), keys.strip()
    if not path:
        raise ValueError("Enter the path of the code file.")
    if any(char in path + keys for char in "{}\n\\%") or " " in path:
        raise ValueError("The path and the options must not contain spaces (in the path), braces, "
                         "backslashes, percent signs or line breaks.")
    return f"\\SMCodeFile{f'[{keys}]' if keys else ''}{{{path}}}"


def insert_edit(insert: Insert, selected: str, indent: str) -> Optional[Edit]:
    """What choosing `insert` does to `selected`, the text selected in a line
    indented by `indent`; None for an entry in ASKS, which needs the user's input first."""
    kind, payload = insert.kind, insert.payload
    if kind == "literal":
        return Edit(insert.label, len(insert.label))
    if kind == "wrap_macro":
        return wrap_macro(selected, payload)
    if kind == "wrap_env":
        return wrap_environment(selected, indent, payload)
    if kind == "wrap_env_ellipsis":
        return wrap_environment(
            selected, indent, payload,
            item_prefix="\\item[\\SMBulletEllipsis] ", leading_comment="%Use \\ldots for in-text ellipses")
    if kind == "wrap_multilingual":
        return insert_multilingual(selected, payload)
    if kind == "wrap_block":
        return wrap_block(selected, indent, payload)
    if kind == "wrap_block_floating":
        return wrap_block(selected, indent, payload, floating=True)
    return None


# The format buttons: (button text, macro) -- I, B, U and Tt, then the two words.
FORMAT_MACROS = [("I", "textit"), ("B", "textbf"), ("U", "underline"), ("Tt", "texttt")]
WORD_MACROS = [("Source", "source"), ("Footnote", "footnote")]

# The text colors of the institution preamble, which nearly every deck \inputs.
# A few names resolve to another hex per institution, so a swatch is an
# approximation of the color a slide gets under its deck's template.
TEXTCOLOR_SWATCHES = {
    "c_primary_dark": "#000000",
    "c_primary_highlight": "#ffd500",
    "c_primary_gray": "#c6c6c6",
    "c_primary_white": "#ffffff",
    "c_secondary_violet": "#948dc3",
    "c_tertiary_violet": "#c2bddf",
    "c_secondary_blue": "#689cce",
    "c_tertiary_blue": "#bacce8",
    "c_secondary_green": "#9fcb81",
    "c_tertiary_green": "#cce2ba",
    "c_secondary_red": "#e4684b",
    "c_tertiary_red": "#f1ae95",
    "c_secondary_orange": "#f6a968",
    "c_tertiary_orange": "#fbd0aa",
    "c_secondary_yellow": "#ffe063",
    "c_tertiary_yellow": "#ffeeaf",
    "c_tertiary_gray": "#e3e3e3",
    "c_custom_gray": "#333333",
    "c_custom_red": "#c00000",
    "c_custom_green": "#00b050",
}
_TEXTCOLOR_CATEGORY_ORDER = {"custom": 0, "primary": 1, "secondary": 2, "tertiary": 3}
TEXTCOLOR_PALETTE = sorted(
    TEXTCOLOR_SWATCHES, key=lambda name: (_TEXTCOLOR_CATEGORY_ORDER[name.split("_")[1]], name))


# -- Enter ------------------------------------------------------------------------

# No trailing "$": a \begin{ENV} is very often followed by its own arguments on
# the same line (\begin{standardframe}{Title}, a title with nested braces like
# \footnote{\fullcite{key}}) that this makes no attempt to brace-match.
# Detecting the opening `\begin{ENV}` token plus "Enter at the true end of the
# line" is enough to know that this line opens ENV.
_BEGIN_ENV_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}")
# standardframe's body is a whole slide, not a short list: inserting its
# \end{standardframe} right after the title only gets in the way of typing.
_NO_AUTO_END_ENVIRONMENTS = {"standardframe"}
# Checked after the \begin{ENV} trigger, so "\item \begin{itemize}" (an item
# that opens a nested list) still gets the more specific handling. Captures an
# optional bracketed label, which the next item repeats.
_ITEM_LINE_RE = re.compile(r"^\\item\b(\[[^\]]*\])?")


def smart_return(line: str, at_end: bool) -> Edit:
    """The text Enter inserts at the cursor in `line` (`at_end`: the cursor is at
    its end). A new line continues the leading whitespace (tabs: this
    project's convention). At the end of a `\\begin{ENV}` line it also opens
    the matching \\end{ENV} below at the same indentation, with the cursor
    one tab deeper in between (on `\\item ` for a list). After an `\\item` it
    starts the next item with the same label. A \\begin{} typed mid-line falls
    back to plain continuation, since a second \\end{} spliced into the middle
    of a line would corrupt it."""
    indent = re.match(r"[ \t]*", line).group(0)
    if at_end:
        # The last \begin{}, not the first: the one most recently typed.
        matches = list(_BEGIN_ENV_RE.finditer(line))
        if matches and matches[-1].group(1) not in _NO_AUTO_END_ENVIRONMENTS:
            env = matches[-1].group(1)
            item_line = f"{indent}\t\\item " if env in LIST_ENVIRONMENTS else f"{indent}\t"
            return Edit(f"\n{item_line}\n{indent}\\end{{{env}}}", 1 + len(item_line))
        item = _ITEM_LINE_RE.match(line[len(indent):])
        if item:
            text = f"\n{indent}\\item{item.group(1) or ''} "
            return Edit(text, len(text))
    return Edit("\n" + indent, 1 + len(indent))


# -- braces, the header comment, the .bib -------------------------------------------

def _is_escaped(text: str, pos: int) -> bool:
    return pos > 0 and text[pos - 1] == "\\"


def matching_brace(text: str, pos: int) -> Optional[int]:
    """The position of the brace that closes (or opens) the one at `pos`."""
    char = text[pos]
    depth = 0
    if char == "{":
        after = braced_argument(text, pos)[1]
        return after - 1 if after != pos else None
    for i in range(pos, -1, -1):
        if _is_escaped(text, i):
            continue
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            depth -= 1
            if depth == 0:
                return i
    return None


def brace_pair(text: str, cursor: int) -> Optional[tuple[int, int]]:
    """The matching pair of braces the cursor touches (on either side), if any."""
    for candidate in (cursor, cursor - 1):
        if 0 <= candidate < len(text) and text[candidate] in "{}" and not _is_escaped(text, candidate):
            match = matching_brace(text, candidate)
            return None if match is None else (candidate, match)
    return None


def header_comment_lines(text: str) -> int:
    """How many lines at the top are % comments: the "% Converted from ... /
    v1-N-0 ..." history many slide files carry can run to 30+ lines before the
    \\slide{}-family call."""
    count = 0
    for line in text.splitlines():
        if not line.lstrip().startswith("%"):
            break
        count += 1
    return count


# "@type{key," at the start of a line, as bibliography.py's entry pattern: every
# real entry starts one, so an "@" inside a URL is never taken for an entry.
_BIB_ENTRY_KEY_RE = re.compile(r"^@\w+\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)


def bib_entry_start(text: str, letter: str) -> Optional[int]:
    """Offset of the first .bib entry whose citation key starts with `letter`
    (the file is sorted, so that is where the letter's entries begin)."""
    for match in _BIB_ENTRY_KEY_RE.finditer(text):
        if match.group(1)[0].upper() == letter.upper():
            return match.start()
    return None


def minimal_replacement(old: str, new: str) -> tuple[int, int, str]:
    """The smallest (start, end, replacement) with old[:start] + replacement +
    old[end:] == new -- a common-prefix/suffix diff, cheap at slide-file sizes.
    Patches the version-marker line into the live buffer after a save without
    disturbing the rest. `start` and `end` are UTF-16 offsets (Qt positions)."""
    max_prefix = min(len(old), len(new))
    prefix = 0
    while prefix < max_prefix and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < max_prefix - prefix and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]:
        suffix += 1
    return utf16_len(old[:prefix]), utf16_len(old[:len(old) - suffix]), new[prefix:len(new) - suffix]
