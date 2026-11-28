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

from . import deck_editor, slide_import
from .tex_source import COMMENT_RE, braced_argument

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


# A deck adds what its preamble uses and slides do not: TeX conditionals on lines of their own
#   \ifdefined\deckversionoverride / \deckversion[...] / \else / \deckversion[instructor] / \fi
# and definitions whose body spans lines (\newcommand{\X}{% / body / }). A conditional opens a level only when its
# line starts with \if<name> not followed by a brace (\ifstrequal{..}, \ifthenelse{..} and \ifdeckversioninlist{..}
# are macros, not conditionals) and the line does not close it again; braces count outside comments and \{ \}.
_DECK_IF_RE = re.compile(r"^\\if[a-zA-Z@]*(?![a-zA-Z@])(?!\s*\{)")
_DECK_ELSE_RE = re.compile(r"^\\(?:else|or)(?![a-zA-Z@])")
_DECK_FI_RE = re.compile(r"^\\fi(?![a-zA-Z@])")
_DECK_FI_ANY_RE = re.compile(r"\\fi(?![a-zA-Z@])")
_ESCAPED_BRACE_RE = re.compile(r"\\[{}%]")


def _code_part(line: str) -> str:
    """`line` without its comment and with \\{, \\} and \\% taken out: what braces are counted in."""
    return COMMENT_RE.sub("", _ESCAPED_BRACE_RE.sub("", line))


_SECTIONING = ("section", "subsection", "subsubsection")
_DOCUMENT_END_RE = re.compile(r"^\\end\{document\}")
_SECTIONING_RE = re.compile(r"^\\(section|subsection|subsubsection)(?![a-zA-Z@])")
_DECK_CALL_RE = deck_editor.DECK_CALL_RE


def _indent_width(line: str) -> int:
    return len(re.match(r"[ \t]*", line).group(0).expandtabs(4))


def section_offsets(text: str) -> dict[str, int]:
    """How a deck indents its slide calls under each sectioning level: 1 when most calls after a \\section
    (\\subsection, \\subsubsection) sit deeper than that line, else 0. Decks differ here, and Reindent keeps what
    the deck does."""
    deeper = {name: 0 for name in _SECTIONING}
    level = {name: 0 for name in _SECTIONING}
    current: Optional[tuple[str, int]] = None
    for line in text.split("\n"):
        content = line.lstrip(" \t")
        heading = _SECTIONING_RE.match(content)
        if heading:
            current = (heading.group(1), _indent_width(line))
        elif current is not None and _DECK_CALL_RE.match(content):
            if _indent_width(line) > current[1]:
                deeper[current[0]] += 1
            else:
                level[current[0]] += 1
        elif _DOCUMENT_END_RE.match(content):
            current = None
    return {name: int(deeper[name] > level[name]) for name in _SECTIONING}


def reindent_deck(text: str) -> str:
    """reindent_latex() for a deck: one tab per \\begin{} level (so a deck's body, inside \\begin{document}, is one
    tab in), and also per TeX conditional and per brace group left open at a line's end. A line that starts with
    \\end{}, \\else, \\or, \\fi or a closing brace lines up with the line that opened it. What follows a \\section
    (\\subsection, \\subsubsection) is one tab deeper when the deck already does that (section_offsets()). Comment
    lines follow the code around them; blank lines are left empty."""
    offsets = section_offsets(text)
    extra = {name: 0 for name in _SECTIONING}    # the extra levels of the headings above the current line
    depth = 0
    out_lines = []
    for line in text.split("\n"):
        if not line.strip():
            out_lines.append("")
            continue
        content = line.lstrip(" \t")
        code = _code_part(content)
        heading = _SECTIONING_RE.match(content)
        if heading:                              # a heading drops its own level's extra and those below it
            for name in _SECTIONING[_SECTIONING.index(heading.group(1)):]:
                extra[name] = 0
        elif _DOCUMENT_END_RE.match(content):    # the end of the body ends the sections' levels
            extra = {name: 0 for name in _SECTIONING}
        shown = depth + sum(extra.values())
        if heading:
            extra[heading.group(1)] = offsets[heading.group(1)]
        if content.startswith("%"):
            out_lines.append(("\t" * shown) + content)
            continue
        leading_closers = len(code) - len(code.lstrip("}"))
        opens_if = bool(_DECK_IF_RE.match(content)) and not _DECK_FI_ANY_RE.search(code)
        own = shown - leading_closers
        if _REINDENT_END_RE.match(content) or _DECK_ELSE_RE.match(content) or _DECK_FI_RE.match(content):
            own -= 1
        out_lines.append(("\t" * max(0, own)) + content)
        if _REINDENT_END_RE.match(content) or _DECK_FI_RE.match(content):
            depth -= 1
        if _REINDENT_BEGIN_RE.match(content) or opens_if:
            depth += 1
        depth = max(0, depth + code.count("{") - code.count("}"))
    return "\n".join(out_lines)


def reindent_bib(text: str) -> str:
    """A .bib file: an entry's @type{key, line and its closing brace flush left, each field one tab in. A line that
    continues a field's value (inside its braces or quotes) keeps its own leading whitespace, and so does everything
    else inside a value; text between entries is flushed left. Braces are counted as BibTeX does (all of them)."""
    depth = 0           # brace (or entry parenthesis) depth: 0 between entries, 1 at the fields
    closer = "}"        # the entry's own closing delimiter: } or )
    in_quote = False    # inside a "..." value at field level
    out_lines = []
    for line in text.split("\n"):
        content = line.lstrip(" \t")
        if not content:
            out_lines.append("")
        elif depth == 0:
            out_lines.append(content)
        elif depth == 1 and not in_quote:
            out_lines.append(content if content.startswith(closer) else "\t" + content)
        else:
            out_lines.append(line)
        for char in content if depth or content.startswith("@") else "":
            if depth == 0:
                if char in "{(":
                    depth, closer = 1, "}" if char == "{" else ")"
            elif char == '"' and depth == 1:
                in_quote = not in_quote
            elif char == "{":
                depth += 1
            elif char == closer and depth == 1 and not in_quote:
                depth, in_quote = 0, False
            elif char == "}" and depth > 1:
                depth -= 1
    return "\n".join(out_lines)


REINDENTERS = {"slide": reindent_latex, "deck": reindent_deck, "bib": reindent_bib}


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


def insert_multilingual(selected: str, codes: tuple[str, ...]) -> Edit:
    """\\multilingualtext{EN={...}, DE={}, FR={}}, one key per language of the project (the first, its main
    language, first): the selection goes into the first braces and the cursor lands in the second ones, ready for
    the translation (in the first when there is no selection or no other language). The two-argument form
    \\multilingualtext{EN}{DE} is gone (2026-11-24, compat_multilingual.py)."""
    first = f"\\multilingualtext{{{codes[0]}={{"
    rest = "".join(f", {code}={{}}" for code in codes[1:])
    text = f"{first}{selected}}}{rest}}}"
    if not selected or len(codes) < 2:
        return Edit(text, len(first) + len(selected))
    return Edit(text, len(first) + len(selected) + len(f"}}, {codes[1]}={{"))


def multilingual_for(insert: "Insert", codes: tuple[str, ...]) -> "Insert":
    """The languages entry for a project with the language `codes` (the main one first): one key per language in
    its payload, hint and hover text."""
    if insert.kind != "wrap_multilingual" or not codes:
        return insert
    others = f", with an empty slot for {', '.join(codes[1:])}" if len(codes) > 1 else ""
    return insert._replace(
        payload=",".join(codes),
        hint=f"\\multilingualtext{{{', '.join(f'{code}={{...}}' for code in codes)}}}",
        tip=f"The selection as the text in {codes[0]}, the project's main language{others}. A deck shows the text "
            f"of its own language; a deck in a language the list lacks shows the main language's.")


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
    \\item[\\SMBulletEllipsis] items; "wrap_multilingual" \\multilingualtext with a key per
    language, the comma-joined codes in `payload` (see insert_multilingual, multilingual_for); "wrap_block" and "wrap_block_floating" a
    beamer block (see wrap_block). "hyperlink", "qr" and "code_file" need the
    user's input first (format_hyperlink, the QR code sheet, code_file_call). `hint` is the
    LaTeX a menu shows beside a label that is not itself LaTeX; `tip` the menu's hover text."""
    label: str
    kind: str
    payload: Optional[str] = None
    hint: str = ""
    tip: str = ""


# What needs the user's input before there is any text to insert.
ASKS = ("hyperlink", "qr", "code_file")

# The Insert menu (2026-11-24, direct request), top to bottom: External elements (the three that ask first), the
# Lists and Blocks submenus, Visibility, then the placement and text commands.
INSERT_EXTERNAL_COMMANDS = [
    Insert("Hyperlink…", "hyperlink", hint="\\href{URL}{text}",
           tip="A link: asks for the address; the selection becomes the link text."),
    Insert("QR…", "qr", hint="\\SMQRCode{…}{…}",
           tip="A QR code for a link, an email, a contact, a calendar event or a map location. With the cursor on "
               "a QR code the slide already has, updates that code."),
    Insert("Code file…", "code_file", hint="\\SMCodeFile{snippets/…}",
           tip="LaTeX source shown on the slide, read from a file in snippets/ (created if it does not exist), "
               "with commands and comments in color."),
]

INSERT_VISIBILITY_COMMANDS = [
    Insert("\\conditionalpause[instructor]", "literal",
           tip="A pause only in the instructor deck: the student decks show what follows at once."),
    # students see only the slide's last reveal state; goes right before the frame
    Insert("\\SMFinalStateForStudents", "literal",
           tip="The student decks show only the final state of the next frame's reveal steps. Put it in the "
               "slide file before the frame."),
    Insert("\\only<2->{...}", "wrap_macro", "only<2->",
           tip="The selection only from step 2 on (change the 2 for another step); it takes no space before."),
    Insert("\\uncover<2->{...}", "wrap_macro", "uncover<2->",
           tip="The selection invisible before step 2, but keeping its space (change the 2 for another step)."),
]

INSERT_PLACEMENT_COMMANDS = [
    # an image or other content in the bottom-right corner of the content area, as an overlay
    Insert("\\cornerfigure[corner=se]{...}", "wrap_macro", "cornerfigure[corner=se]",
           tip="An image or other content in a corner of the content area (here the bottom right), as an overlay "
               "that takes no space in the text. Give the image file and width= or height=."),
    Insert("\\SMTextBox[...]{...}", "wrap_macro", "SMTextBox[corner=ne, width=4cm]",
           tip="A bordered text box in the top-right corner, as an overlay. Keys move it (xshift, yshift, "
               "anchor), turn it (rotate) and style it (border, fill, font, textcolor)."),
    # all list levels one font size smaller, for a slide whose text doesn't
    # fit; goes inside the frame -- change the 1 to 2 for two sizes smaller
    Insert("\\shrinklists{1}", "literal",
           tip="All lists of this frame one font size smaller, for a slide whose text does not fit; 2 or 3 for "
               "two or three sizes. Put it inside the frame."),
    # multilingual_for() puts in the project's languages
    Insert("All project languages", "wrap_multilingual", "EN,DE", "\\multilingualtext{EN={...}, DE={...}}",
           tip="The selection as the text in the project's main language, with an empty slot for each other "
               "language: a deck shows the text of its own language."),
]

# Every entry that is neither a list nor a block, in the menu's order.
INSERT_COMMANDS = INSERT_EXTERNAL_COMMANDS + INSERT_VISIBILITY_COMMANDS + INSERT_PLACEMENT_COMMANDS

INSERT_LIST_COMMANDS = [
    Insert("Bulleted list", "wrap_env", "itemize", "\\begin{itemize}",
           tip="A bulleted list; each selected line becomes an item."),
    Insert("Bulleted list, ellipses", "wrap_env_ellipsis", "itemize", "\\item[\\SMBulletEllipsis]",
           tip="A list whose items start with an ellipsis instead of a bullet."),
    Insert("Numbered list", "wrap_env", "enumerate", "\\begin{enumerate}",
           tip="A numbered list; each selected line becomes an item."),
    Insert("\\tallitem", "literal",
           tip="An item with extra room above it, for a stacked fraction: use it on the fraction's line and on "
               "the item after it."),
    Insert("\\tallitemnobullet", "literal",
           tip="Like \\tallitem, without a bullet: for a display formula that continues the previous item."),
]

# The beamer blocks this project defines (SlideMage_base.tex,
# slides/ZZX-EN-Definition-formula-current.tex shows them side by side).
INSERT_BLOCK_COMMANDS = [
    Insert(label, kind, env, f"\\begin{{{env}}}", tip) for label, kind, env, tip in (
        ("Block", "wrap_block", "block", "A block with a title bar; the selection becomes its body."),
        ("Example block", "wrap_block", "exampleblock", "A block for an example, in the example color."),
        ("Alert block", "wrap_block", "alertblock", "A block for a warning, in the alert color."),
        ("Reference block", "wrap_block", "referenceblock", "A block for references and citations."),
        ("Definition block", "wrap_block", "definitionblock",
         "A block for a definition, with a definition symbol in its title bar."),
        ("Info block", "wrap_block", "infoblock", "A block for a supplementary aside, with a circled i in its "
                                                  "title bar."),
        ("Floating block", "wrap_block_floating", "SMFloatingBlock",
         "A block of a given width (5cm) to place freely, for example with \\cornerfigure."),
        ("Floating example block", "wrap_block_floating", "SMFloatingExampleBlock",
         "An example block of a given width (5cm) to place freely."),
        ("Floating info block", "wrap_block_floating", "SMFloatingInfoBlock",
         "An info block of a given width (5cm), usually in the top-right corner with \\cornerfigure[block]."),
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
        return insert_multilingual(selected, tuple(payload.split(",")))
    if kind == "wrap_block":
        return wrap_block(selected, indent, payload)
    if kind == "wrap_block_floating":
        return wrap_block(selected, indent, payload, floating=True)
    return None


# The format buttons: (button text, macro) -- I, B, U and Tt, then the word. Source (\source) left the row
# 2026-10-26, direct request.
FORMAT_MACROS = [("I", "textit"), ("B", "textbf"), ("U", "underline"), ("Tt", "texttt")]
WORD_MACROS = [("Footnote", "footnote")]

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


def smart_return(line: str, at_end: bool, text: Optional[str] = None) -> Edit:
    """The text Enter inserts at the cursor in `line` (`at_end`: the cursor is at
    its end). A new line continues the leading whitespace (tabs: this
    project's convention). At the end of a `\\begin{ENV}` line it also opens
    the matching \\end{ENV} below at the same indentation, with the cursor
    one tab deeper in between (on `\\item ` for a list) -- unless `text`, the
    whole file, has an \\end{ENV} for every \\begin{ENV} already (outside
    comments): then only the line inside opens, and no second \\end{} lands
    under the first. After an `\\item` it
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
            if text is not None and _is_closed(text, env):
                return Edit(f"\n{item_line}", 1 + len(item_line))
            return Edit(f"\n{item_line}\n{indent}\\end{{{env}}}", 1 + len(item_line))
        item = _ITEM_LINE_RE.match(line[len(indent):])
        if item:
            text = f"\n{indent}\\item{item.group(1) or ''} "
            return Edit(text, len(text))
    return Edit("\n" + indent, 1 + len(indent))


def _is_closed(text: str, env: str) -> bool:
    """Whether `text` has as many \\end{env} as \\begin{env}, comments left out."""
    code = COMMENT_RE.sub("", text)
    name = re.escape(env)
    return len(re.findall(rf"\\end\{{{name}\}}", code)) >= len(re.findall(rf"\\begin\{{{name}\}}", code))


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
