"""Fast, static pre-render check of the LaTeX that is about to be compiled
(2026-09-26, direct instruction: "check for obvious syntax errors before
rendering a pdf -- for a single slide, a deck, or everything -- scoped to
just what is being rendered").

Deliberately a *lexical* check, not a LaTeX parser: it never expands a
macro, so it cannot know what a custom command does. It only reports things
that are wrong (or almost certainly wrong) regardless of what the project's
own macros do, and every check below was run over all ~900 slide files and
every deck first and tuned until it stayed quiet on the existing, compiling
material. Measured cost: about 0.1 ms per slide file, i.e. a whole deck of
several hundred slides is checked in well under a tenth of a second (the
lexical result is memoised per file text, so re-checking an unchanged file
is a dictionary lookup).

Checks (the `CHECKS` table below is the single source of truth for the
listing shown in the GUI and in README.md):

  errors (the compile will fail, or the output is certainly broken)
    encoding      control character / invalid UTF-8 in the source
    braces        unbalanced { } (unclosed opener, stray closer)
    environments  \\begin{x} without \\end{x}, \\end{x} without \\begin{x},
                  wrong nesting order
    math-dollar   odd number of $ (math left open), also across a blank line
    math-delims   \\[ \\] and \\( \\) not paired, \\left without \\right
    ampersand     unescaped & outside a table/alignment/matrix/tikz context
    hash          unescaped # outside a macro definition or URL
    citation      \\fullcite/\\cite/... key that is not in Slidemaster.bib
    image         \\includegraphics/\\chapterlogo file that does not exist
    code-file     \\SMCodeFile{path} whose file does not exist
    slide-file    a \\slide{}-family call whose slides/*.tex file is missing

  warnings (very likely a mistake, but the compile may still succeed)
    underscore    _ in running text outside math / macro arguments
    percent       "5% growth": the % starts a comment and swallows the rest
    overlay       \\only<2-> style overlay specification whose > is missing
    optional-arg  \\item[ label never closed on its line
    table-edges   gothamtable with neither [gap=...] nor @{} edges: its rules
                  run past the text on both sides
    heading-text  frame opens with a bare \\textbf{...} line above its list

Not checked (needs a real TeX run): undefined macros, wrong argument counts,
missing packages, anything that depends on macro expansion.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from . import bibliography
from .deck_scan import Chapter, Deck
from .project import ProjectContext
from .tex_source import IFFALSE_RE, INPUT_RE, VERB_RE, VERBATIM_ENV_RE, masked_same_length

ERROR = "error"
WARNING = "warning"

# (code, severity, short description) -- keep in sync with the module
# docstring above and the README section "Pre-render syntax check".
CHECKS: list[tuple[str, str, str]] = [
    ("encoding", ERROR, "Control characters (e.g. a stray backspace or form feed) or invalid UTF-8 in the source -- LuaTeX stops with \"Text line contains an invalid character\"."),
    ("braces", ERROR, "Unbalanced curly braces: an opening { that is never closed, or a closing } with nothing to close (\\{ and \\} and comments are ignored)."),
    ("environments", ERROR, "\\begin{x} without a matching \\end{x}, \\end{x} without \\begin{x}, or environments closed in the wrong order."),
    ("math-dollar", ERROR, "Math mode left open: an odd number of unescaped $ signs in the file, or an unclosed $...$ at a blank line."),
    ("math-delims", ERROR, "Unpaired \\[ ... \\] or \\( ... \\), or a different number of \\left and \\right."),
    ("ampersand", ERROR, "Unescaped & in running text (outside tabular/array/align/matrix/tikz contexts) -- \"Misplaced alignment tab character &\"."),
    ("hash", ERROR, "Unescaped # outside a macro definition or a URL -- \"You can't use macro parameter character #\"."),
    ("citation", ERROR, "\\fullcite/\\cite/\\textcite/\\parencite/... with a key that is not in Slidemaster.bib."),
    ("image", ERROR, "\\includegraphics, \\chapterlogo, \\fullbleedframe or sideimageframe pointing at a file that does not exist (the extension may be omitted)."),
    ("code-file", ERROR, "\\SMCodeFile{path} pointing at a file that does not exist (the path is relative to the project root, extension included)."),
    ("slide-file", ERROR, "A deck's \\slide/\\slidefinal/\\slidestep/\\conditionalslide/\\slideversion/... call whose slides/<id>-current.tex (or -vX-Y-Z.tex) file does not exist."),
    ("underscore", WARNING, "_ in running text outside math and outside macro arguments that take names/paths (\"Missing $ inserted\")."),
    ("caret", WARNING, "^ in running text outside math (\"10^6\" typed without $...$) -- \"Missing $ inserted\"."),
    ("percent", WARNING, "A % directly after a digit and followed by more text (\"5% growth\"): the % starts a comment and silently drops the rest of the line."),
    ("overlay", WARNING, "Overlay specification whose closing > is missing, e.g. \\only<2-{...}."),
    ("optional-arg", WARNING, "\\item[ ... whose closing ] is missing on that line."),
    ("heading-text", WARNING, "A content frame that opens with a bare \\textbf{...} line directly above its list: the heading reads as a detached label -- make it the list's first \\item."),
    ("table-edges", WARNING, "\\begin{gothamtable}{...} with neither a [gap=...] option nor @{} at the edges of its column spec: the table rules run \\tabcolsep past the text on both sides. Write \\begin{gothamtable}[gap=12pt]{lcc}."),
]
_SEVERITY = {code: sev for code, sev, _ in CHECKS}


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str
    line: int                 # 1-based line in `source`
    source: str = ""          # display name: file name / "buffer"
    path: Optional[Path] = None

    @property
    def severity(self) -> str:
        return _SEVERITY[self.code]

    def with_source(self, source: str, path: Optional[Path]) -> "LintIssue":
        return LintIssue(self.code, self.message, self.line, source, path)


# --------------------------------------------------------------------------
# Lexical layer
# --------------------------------------------------------------------------

# Environments in which & is a column separator.
_COLUMN_ENVS = {
    "tabular", "tabular*", "tabularx", "tabulary", "longtable", "array", "tabu",
    "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix",
    "align", "align*", "alignat", "alignat*", "flalign", "flalign*", "aligned",
    "alignedat", "split", "cases", "dcases", "eqnarray", "eqnarray*", "xalignat",
    "gothamtable", "subarray", "IEEEeqnarray",
}
# Contexts that contain TikZ/PGF code: & (matrix), _ in node names, etc. are
# not checked inside them.
_TIKZ_ENVS = {"tikzpicture", "tikzillustration", "axis", "semilogxaxis", "semilogyaxis",
              "loglogaxis", "groupplot", "pgfpicture", "scope", "tikzcd", "forest"}
_MATH_ENVS = {"equation", "equation*", "align", "align*", "alignat", "alignat*", "gather",
              "gather*", "multline", "multline*", "flalign", "flalign*", "eqnarray",
              "eqnarray*", "displaymath", "math", "aligned", "gathered", "split", "cases",
              "array", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix"}
# Macros whose argument is a name/path/key, never typeset text: an _ there is fine.
_NON_TYPESET_OWNERS = {
    "textcolor", "color", "colorbox", "fcolorbox", "definecolor", "colorlet", "pagecolor",
    "includegraphics", "input", "include", "InputIfFileExists", "graphicspath",
    "slide", "slidefinal", "slideversion", "omitslide", "omitslideversion",
    "conditionalslide", "slidestep", "setSlideID", "setSlideVersion", "chapterlogo",
    "fullbleedframe", "label", "ref", "pageref", "eqref", "hyperlink", "hypertarget",
    "href", "url", "nolinkurl", "begin", "end", "cite", "fullcite", "parencite", "textcite",
    "autocite", "footcite", "citeauthor", "citeyear", "citetitle", "smartcite",
    "supercite", "tikzillustration", "tikz", "node", "draw", "fill", "path", "coordinate",
    "foreach", "tikzset", "pgfmathsetmacro", "pgfplotsset", "addplot", "setlength",
    "addtolength", "newcommand", "renewcommand", "providecommand", "def", "gdef", "edef",
    "xdef", "let", "pgfkeys", "usepackage", "RequirePackage", "addbibresource",
    "deckoutputfolder", "decktags", "SMCodeFile", "note",  # \note can hold typeset text, but see below
}
_NON_TYPESET_OWNERS.discard("note")  # typeset text: an unescaped _ there is a real error

# Macros whose first argument is a URL/target, where & and # are legal.
_URL_OWNERS = {"href", "url", "nolinkurl", "hyperlink", "hypertarget", "hyperref"}

# Commands after which the following brace group(s) are a definition body
# (# is a parameter there): name -> number of brace groups that belong to it.
_DEF_COMMANDS = {
    "newcommand": 2, "renewcommand": 2, "providecommand": 2, "def": 1, "gdef": 1,
    "edef": 1, "xdef": 1, "newenvironment": 3, "renewenvironment": 3,
    "NewDocumentCommand": 3, "RenewDocumentCommand": 3, "ProvideDocumentCommand": 3,
    "DeclareDocumentCommand": 3, "NewExpandableDocumentCommand": 3,
    "NewDocumentEnvironment": 4, "RenewDocumentEnvironment": 4,
    "DeclareBibliographyDriver": 2, "DeclareFieldFormat": 3, "DeclareNameFormat": 2,
    "DeclareListFormat": 2, "DeclareDelimFormat": 2, "tikzset": 1, "pgfkeys": 1,
    "setbeamertemplate": 2, "defbeamertemplate": 4, "pgfdeclareshape": 2,
    "AtBeginDocument": 1, "AtEndDocument": 1, "AtBeginEnvironment": 2, "AtEndEnvironment": 2,
    "apptocmd": 3, "patchcmd": 3, "pretocmd": 3, "newtcolorbox": 3, "DeclareRobustCommand": 2,
    "newrobustcmd": 2, "renewrobustcmd": 2, "NewCommandCopy": 2, "pgfmathdeclarefunction": 3,
    "usebeamertemplate": 1, "setbeamerfont": 2, "setbeamercolor": 2, "tikzstyle": 1,
    "newtheorem": 2, "DeclareMathOperator": 2, "hypersetup": 1, "setkeys": 1,
    "ExplSyntaxOn": 0, "makeatletter": 0,
}
_CODE_REGION_ON = {"ExplSyntaxOn", "makeatletter"}
_CODE_REGION_OFF = {"ExplSyntaxOff", "makeatother"}
_OVERLAY_MACROS = ("only", "uncover", "visible", "invisible", "onslide", "alt", "temporal",
                   "item", "textcolor", "textbf", "textit", "emph", "action")
_OVERLAY_OPEN_RE = re.compile(
    r"\\(?:%s)\s*<[^<>]*$" % "|".join(_OVERLAY_MACROS), re.MULTILINE)

_CMD_RE = re.compile(r"\\([a-zA-Z@]+\*?)")
_BEGIN_END_RE = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")


def _mask_comments_and_verbatim(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Text with comments, verbatim bodies, \\verb and \\iffalse blocks blanked
    out (line structure preserved) plus [(line, message)] for % that looks
    like an unescaped percent sign."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = VERBATIM_ENV_RE.sub(blank, text)
    text = IFFALSE_RE.sub(blank, text)
    text = VERB_RE.sub(blank, text)
    percent_hits: list[tuple[int, str]] = []
    out_lines: list[str] = []
    for number, line in enumerate(text.split("\n"), 1):
        i, n = 0, len(line)
        cut = -1
        while i < n:
            c = line[i]
            if c == "\\":
                i += 2
                continue
            if c == "%":
                cut = i
                break
            i += 1
        if cut >= 0:
            after = line[cut + 1:]
            if cut > 0 and line[cut - 1].isdigit() and re.match(r"\s+[A-Za-z]", after):
                percent_hits.append(
                    (number, "'%' directly after a digit starts a comment -- everything after it "
                             "on this line is ignored; write \\% for a percent sign"))
            line = line[:cut]
        out_lines.append(line.rstrip("\r"))
    return "\n".join(out_lines), percent_hits


@lru_cache(maxsize=4096)
def _lex(text: str) -> tuple[LintIssue, ...]:
    issues: list[LintIssue] = []

    def add(code: str, line: int, message: str) -> None:
        issues.append(LintIssue(code, message, line))

    # -- encoding ----------------------------------------------------------------
    for number, raw in enumerate(text.split("\n"), 1):
        for ch in raw:
            if ch == "\ufffd":
                add("encoding", number, "invalid UTF-8 (U+FFFD replacement character) -- the file's encoding is damaged here")
                break
            if ord(ch) < 32 and ch not in "\t\r":
                add("encoding", number, f"control character U+{ord(ch):04X} in the source (LuaTeX: \"Text line contains an invalid character\")")
                break

    masked, percent_hits = _mask_comments_and_verbatim(text)
    blank_lines = {number for number, raw in enumerate(text.split("\n"), 1) if not raw.strip()}
    for number, message in percent_hits:
        add("percent", number, message)

    brace_stack: list[tuple[int, Optional[str]]] = []   # (line, owner command)
    env_stack: list[tuple[str, int]] = []
    dollar_open: Optional[int] = None
    dd_open: Optional[int] = None
    paren_open: Optional[int] = None
    bracket_open: Optional[int] = None
    left_count = right_count = 0
    left_line = 1

    pending: Optional[str] = None     # command whose arguments we may be inside
    opt_depth = 0
    code_region = False               # \ExplSyntaxOn / \makeatletter
    def_stack: list[list[int]] = []   # [brace depth at command, groups expected, groups closed, start line, opened]

    line = 1
    i, n = 0, len(masked)
    while i < n:
        c = masked[i]
        if c == "\n":
            line += 1
            # A blank line (empty in the *source*, not merely comment-only)
            # ends any open inline math, and any definition command that
            # never got its braces (a \let-like use).
            if line in blank_lines:
                if dollar_open is not None:
                    add("math-dollar", dollar_open, "$ opened here is not closed before the next blank line")
                    dollar_open = None
                def_stack[:] = [e for e in def_stack if e[4]]
            i += 1
            continue
        if c == "\\":
            m = _BEGIN_END_RE.match(masked, i)
            if m:
                kind, name = m.group(1), m.group(2).strip()
                if kind == "begin":
                    env_stack.append((name, line))
                else:
                    if not env_stack:
                        add("environments", line, f"\\end{{{name}}} without a matching \\begin{{{name}}}")
                    elif env_stack[-1][0] == name:
                        env_stack.pop()
                    elif any(e[0] == name for e in env_stack):
                        while env_stack and env_stack[-1][0] != name:
                            top = env_stack.pop()
                            add("environments", top[1], f"\\begin{{{top[0]}}} is not closed before \\end{{{name}}} on line {line}")
                        if env_stack:
                            env_stack.pop()
                    else:
                        add("environments", line, f"\\end{{{name}}} does not match the open \\begin{{{env_stack[-1][0]}}} (line {env_stack[-1][1]})")
                pending = None
                i = m.end()
                continue
            cm = _CMD_RE.match(masked, i)
            if cm:
                name = cm.group(1).rstrip("*")
                if name == "left":
                    left_count += 1
                    left_line = line
                elif name == "right":
                    right_count += 1
                if name in _CODE_REGION_ON:
                    code_region = True
                elif name in _CODE_REGION_OFF:
                    code_region = False
                if name in _DEF_COMMANDS and _DEF_COMMANDS[name] > 0:
                    def_stack.append([len(brace_stack), _DEF_COMMANDS[name], 0, line, 0])
                pending = name
                i = cm.end()
                continue
            # control symbol: \{ \} \$ \& \% \# \_ \\ \[ \] \( \) \, ...
            nxt = masked[i + 1] if i + 1 < n else ""
            if nxt == "[":
                if bracket_open is not None:
                    add("math-delims", bracket_open, "\\[ opened again before the previous one was closed")
                bracket_open = line
            elif nxt == "]":
                if bracket_open is None:
                    add("math-delims", line, "\\] without a matching \\[")
                bracket_open = None
            elif nxt == "(":
                paren_open = line
            elif nxt == ")":
                if paren_open is None:
                    add("math-delims", line, "\\) without a matching \\(")
                paren_open = None
            if nxt == "\n":
                i += 1
                continue
            pending = None
            i += 2
            continue

        if c == "{":
            for entry in def_stack:
                if len(brace_stack) == entry[0]:
                    entry[4] = 1
            brace_stack.append((line, pending))
            i += 1
            continue
        if c == "}":
            if not brace_stack:
                add("braces", line, "closing } without a matching {")
            else:
                brace_stack.pop()
            for entry in reversed(def_stack):
                if len(brace_stack) <= entry[0]:
                    entry[2] += 1
                    break
            while def_stack and def_stack[-1][2] >= def_stack[-1][1]:
                def_stack.pop()
            i += 1
            continue
        if c == "<" and pending is not None and opt_depth == 0:
            # overlay specification right after a command: \only<2->{...}
            close = masked.find(">", i)
            newline = masked.find("\n", i)
            if close != -1 and (newline == -1 or close < newline):
                i = close + 1
                continue
        if c == "[" and pending is not None:
            opt_depth += 1
            i += 1
            continue
        if c == "]" and opt_depth:
            opt_depth -= 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue

        # -- ordinary character ------------------------------------------------
        if opt_depth == 0:
            pending = None if c not in "<*" else pending

        in_tikz = any(e[0] in _TIKZ_ENVS for e in env_stack) or any(
            o in ("tikz", "node", "draw", "path", "foreach", "tikzset") for _, o in brace_stack if o)
        in_math = (dollar_open is not None or dd_open is not None or paren_open is not None
                   or bracket_open is not None or any(e[0] in _MATH_ENVS for e in env_stack))
        in_def = bool(def_stack) or code_region

        if c == "$":
            if masked.startswith("$$", i):
                dd_open = None if dd_open is not None else line
                i += 2
                continue
            dollar_open = None if dollar_open is not None else line
            i += 1
            continue
        if c == "&" and not in_def and not in_tikz:
            if not any(e[0] in _COLUMN_ENVS for e in env_stack) and not in_math and not any(
                    o in _URL_OWNERS for _, o in brace_stack if o):
                add("ampersand", line, "unescaped & in running text -- write \\& (or put it inside a table/align)")
            i += 1
            continue
        if c == "#" and not in_def and not in_tikz:
            if not any(o in _URL_OWNERS for _, o in brace_stack if o):
                add("hash", line, "unescaped # -- write \\# (a macro parameter outside a definition is an error)")
            i += 1
            continue
        if c == "_" and not in_math and not in_tikz and not in_def:
            prev_c = masked[i - 1] if i > 0 else ""
            next_c = masked[i + 1] if i + 1 < n else ""
            if prev_c.isalnum() and next_c.isalnum() and not any(
                    o in _NON_TYPESET_OWNERS or o.lower().endswith("color")
                    for _, o in brace_stack if o):
                add("underscore", line, "'_' in running text outside math -- write \\_ (LaTeX: \"Missing $ inserted\")")
        if c == "^" and not in_math and not in_tikz and not in_def:
            if not any(o in _NON_TYPESET_OWNERS or o.lower().endswith("color")
                       for _, o in brace_stack if o):
                add("caret", line, "'^' in running text outside math -- put the exponent in $...$ or write \\textasciicircum (LaTeX: \"Missing $ inserted\")")
        i += 1

    # -- end of file ------------------------------------------------------------
    for ln, _owner in brace_stack:
        add("braces", ln, "opening { is never closed")
    for name, ln in env_stack:
        add("environments", ln, f"\\begin{{{name}}} is never closed")
    if dollar_open is not None:
        add("math-dollar", dollar_open, "$ opened here is never closed")
    if dd_open is not None:
        add("math-dollar", dd_open, "$$ opened here is never closed")
    if paren_open is not None:
        add("math-delims", paren_open, "\\( opened here is never closed by \\)")
    if bracket_open is not None:
        add("math-delims", bracket_open, "\\[ opened here is never closed by \\]")
    if left_count != right_count:
        add("math-delims", left_line, f"{left_count} \\left but {right_count} \\right in this file")

    # -- overlay specs ----------------------------------------------------------
    for m in _OVERLAY_OPEN_RE.finditer(masked):
        add("overlay", masked.count("\n", 0, m.start()) + 1, "overlay specification '<' is never closed with '>'")

    # -- \item[ label ----------------------------------------------------------
    for number, ln_text in enumerate(masked.split("\n"), 1):
        for m in re.finditer(r"\\item\s*\[", ln_text):
            depth = 0
            for ch in ln_text[m.end():]:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                elif ch == "]" and depth <= 0:
                    break
            else:
                add("optional-arg", number, "\\item[ label has no closing ] on this line")
    issues.sort(key=lambda x: (x.line, x.code))
    return tuple(issues)


# --------------------------------------------------------------------------
# External-state layer (never cached: depends on bib / files on disk)
# --------------------------------------------------------------------------

_CITE_RE = re.compile(
    r"\\(?:fullcite|cite|parencite|textcite|autocite|footcite|footfullcite|citeauthor|"
    r"citeyear|citetitle|smartcite|supercite|Cite|Parencite|Textcite)\*?"
    r"(?:\[[^\]]*\]){0,2}\{([^{}]*)\}")
_IMAGE_RES = (
    re.compile(r"\\includegraphics\*?(?:\[[^\]]*\]){0,2}\{([^{}]+)\}"),
    re.compile(r"\\chapterlogo\{([^{}]+)\}"),
    re.compile(r"\\fullbleedframe\{([^{}]+)\}"),
    re.compile(r"\\begin\{sideimageframe\}\{[^{}]*\}\{([^{}]+)\}"),
    # the v5.x figure helpers; an argument with a backslash is content, not a file
    re.compile(r"\\(?:cornerfigure|fitfigure|sectionfigure|begin\{besidefigure\})(?:\[[^\]]*\])?\{([^{}\\\n]+)\}"),
)
_CODE_FILE_RE = re.compile(r"\\SMCodeFile(?:\[[^\]]*\])?\{([^{}]+)\}")
_IMAGE_SUFFIXES = ("", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".gif")
# \begin{gothamtable}{spec} without an option (an option is [gap=...])
_GOTHAMTABLE_RE = re.compile(r"\\begin\{gothamtable\}\s*\{")
# A content frame whose first line is a bare \textbf{...} with a list right
# below it ("fix the itemization (first line should be an item)", given 14
# times on converted slides, 2026-07-15)
_HEADING_TEXT_RE = re.compile(
    r"\\begin\{(?:standard|figure|highlight|sideimage)frame\}(?:\[[^\]\n]*\])?\{[^\n]*\}[ \t]*\n"
    r"\s*(?P<head>\\textbf\{[^{}\n]*\})[ \t]*(?:\\\\|\\par)?[ \t]*\n"
    r"\s*\\begin\{(?:itemize|enumerate)\}")

_bib_cache: tuple[tuple[Path, float, int], frozenset[str]] | None = None


def bib_keys(ctx: ProjectContext) -> frozenset[str]:
    """Every citation key in Slidemaster.bib, cached until the file changes."""
    global _bib_cache
    try:
        st = ctx.bibliography_path.stat()
        stamp = (ctx.root, st.st_mtime, st.st_size)
    except OSError:
        return frozenset()
    if _bib_cache is None or _bib_cache[0] != stamp:
        _bib_cache = (stamp, frozenset(bibliography.load(ctx.bibliography_path)))
    return _bib_cache[1]


def _citations(masked: str):
    """(key, offset) of every key a citation command of the (comment-masked) text names."""
    for m in _CITE_RE.finditer(masked):
        for key in (k.strip() for k in m.group(1).split(",")):
            if key:
                yield key, m.start(1)


def cited_keys(text: str) -> list[str]:
    """The citation keys a slide's text cites (comments and verbatim text left out), in order of
    first use, each once; keys built from macros or arguments are left out."""
    masked, _ = _mask_comments_and_verbatim(text)
    return list(dict.fromkeys(k for k, _ in _citations(masked) if "\\" not in k and "#" not in k))


def _external(ctx: ProjectContext, text: str) -> list[LintIssue]:
    masked, _ = _mask_comments_and_verbatim(text)
    issues: list[LintIssue] = []
    keys = bib_keys(ctx)

    def line_of(pos: int) -> int:
        return masked.count("\n", 0, pos) + 1

    if keys:
        for key, position in _citations(masked):
            if key not in keys and "\\" not in key and "#" not in key:
                issues.append(LintIssue("citation", f"citation key '{key}' is not in Slidemaster.bib", line_of(position)))
    for regex in _IMAGE_RES:
        for m in regex.finditer(masked):
            # \fullbleedframe takes a comma-separated list (one image per reveal step)
            for ref in (r.strip() for r in m.group(1).split(",")):
                if not ref or "\\" in ref or "#" in ref or "{" in ref:
                    continue
                if not any((ctx.root / (ref + s)).is_file() for s in _IMAGE_SUFFIXES):
                    issues.append(LintIssue("image", f"image file '{ref}' does not exist", line_of(m.start(1))))
    for m in _CODE_FILE_RE.finditer(masked):
        ref = m.group(1).strip()
        if ref and "\\" not in ref and "#" not in ref and not (ctx.root / ref).is_file():
            issues.append(LintIssue("code-file", f"code file '{ref}' does not exist", line_of(m.start(1))))
    for m in _GOTHAMTABLE_RE.finditer(masked):
        if not masked[m.end():].lstrip().startswith("@{}"):
            issues.append(LintIssue(
                "table-edges", "gothamtable rules will run past the text: "
                "use \\begin{gothamtable}[gap=12pt]{...} (or @{} at both edges)", line_of(m.start())))
    for m in _HEADING_TEXT_RE.finditer(masked):
        issues.append(LintIssue(
            "heading-text", "the slide opens with bold text above its list: "
            "make it the list's first \\item instead", line_of(m.start("head"))))
    return issues


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def lint_text(ctx: ProjectContext, text: str, source: str = "buffer", path: Optional[Path] = None) -> list[LintIssue]:
    """All issues in one piece of LaTeX source (the editor buffer, a file...)."""
    found = [i.with_source(source, path) for i in _lex(text)]
    found += [i.with_source(source, path) for i in _external(ctx, text)]
    found.sort(key=lambda x: (x.line, x.code))
    return found


def read_source(path: Path) -> Optional[str]:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def lint_file(ctx: ProjectContext, path: Path) -> list[LintIssue]:
    text = read_source(path)
    if text is None:
        return [LintIssue("slide-file", f"file does not exist or cannot be read: {path.name}", 1, path.name, path)]
    return lint_text(ctx, text, path.name, path)


@dataclass
class CheckResult:
    issues: list[LintIssue] = field(default_factory=list)
    files_checked: int = 0
    seconds: float = 0.0

    @property
    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == WARNING]

    def summary(self) -> str:
        return (f"{self.files_checked} file(s) checked in {self.seconds * 1000:.0f} ms: "
                f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)")


def check_deck_job(ctx: ProjectContext, deck: Deck, version: Optional[str] = None, chapter: Optional[Chapter] = None,
                   result: Optional[CheckResult] = None, seen: Optional[set] = None,
                   language: Optional[str] = None) -> CheckResult:
    """Everything a compile of `deck` (in `version`, whole or one `chapter`)
    reads: the deck file itself (preamble, plus only the chosen chapter for a
    per-chapter job), every slide file its included calls load, and any
    `\\input{}`ed deck fragment (e.g. test-slides.tex) with its own slides."""
    started = time.perf_counter()
    result = result if result is not None else CheckResult()
    seen = seen if seen is not None else set()

    def check_file(path: Path, keep=None) -> None:
        if path in seen:
            return
        seen.add(path)
        result.files_checked += 1
        for issue in lint_file(ctx, path):
            if keep is None or keep(issue.line):
                result.issues.append(issue)

    text = deck.text
    keep = None
    if chapter is not None and deck.preamble_end is not None:
        pre_lines = text.count("\n", 0, deck.preamble_end) + 1
        ch_first = text.count("\n", 0, chapter.start) + 1
        ch_last = text.count("\n", 0, chapter.end) + 1
        keep = lambda ln: ln <= pre_lines or ch_first <= ln <= ch_last  # noqa: E731
    seen.add(deck.path)
    result.files_checked += 1
    for issue in lint_text(ctx, text, deck.path.name, deck.path):
        if keep is None or keep(issue.line):
            result.issues.append(issue)

    from . import deck_language
    from .deck_settings import read_settings
    language = (language or read_settings(deck.text).language).upper()
    resolved_deck, inline_inputs = deck_language.compile_deck(ctx, deck, language)
    calls = [s.call for s in deck_language.deck_slots(ctx, resolved_deck, language)]
    for path in inline_inputs:
        if path.parent != ctx.slides_dir:
            check_file(path)
    for call in calls:
        if chapter is not None and (call.chapter is None or call.chapter.order != chapter.order):
            continue
        if not call.included_in(version):
            continue
        path = ctx.slides_dir / call.source_filename
        if not path.is_file():
            line = text.count("\n", 0, call.call_start) + 1
            result.issues.append(LintIssue(
                "slide-file", f"{path.name} does not exist (called as \\{call.macro}{{{call.id_slug}}})",
                line, deck.path.name, deck.path))
            continue
        check_file(path)

    # \input{fragment} decks (test-slides.tex): their slide calls count too
    if deck.preamble_end is not None and resolved_deck.text == text:
        body = masked_same_length(text)[deck.preamble_end:]
        for m in INPUT_RE.finditer(body):
            name = m.group(1).strip()
            frag = ctx.decks_dir / (name if name.endswith(".tex") else name + ".tex")
            if frag.is_file() and frag not in seen:
                frag_text = read_source(frag) or ""
                seen.add(frag)
                result.files_checked += 1
                result.issues.extend(lint_text(ctx, frag_text, frag.name, frag))
                for slot in deck_language.slots(ctx, deck_language.calls_in(frag_text, []), language):
                    call = slot.call
                    if not call.included_in(version):
                        continue
                    path = ctx.slides_dir / call.source_filename
                    if not path.is_file():
                        result.issues.append(LintIssue(
                            "slide-file", f"{path.name} does not exist (called as \\{call.macro}{{{call.id_slug}}})",
                            frag_text.count("\n", 0, call.call_start) + 1, frag.name, frag))
                    else:
                        check_file(path)
    result.seconds += time.perf_counter() - started
    return result


def check_jobs(ctx: ProjectContext, jobs: Iterable) -> CheckResult:
    """Union over compile jobs (objects with .deck/.version/.chapter): each
    file is checked once, however many jobs read it."""
    result, seen = CheckResult(), set()
    started = time.perf_counter()
    for job in jobs:
        check_deck_job(ctx, job.deck, job.version, job.chapter, result, seen, getattr(job, "language", None))
    result.seconds = time.perf_counter() - started
    return _dedupe(result)


def check_slide_files(ctx: ProjectContext, paths: Iterable[Path]) -> CheckResult:
    result = CheckResult()
    started = time.perf_counter()
    for path in dict.fromkeys(paths):
        result.files_checked += 1
        result.issues.extend(lint_file(ctx, path))
    result.seconds = time.perf_counter() - started
    return _dedupe(result)


def check_buffer(ctx: ProjectContext, text: str, name: str, path: Optional[Path] = None) -> CheckResult:
    started = time.perf_counter()
    result = CheckResult(files_checked=1)
    result.issues.extend(lint_text(ctx, text, name, path))
    result.seconds = time.perf_counter() - started
    return result


def _dedupe(result: CheckResult) -> CheckResult:
    unique = list(dict.fromkeys(result.issues))
    result.issues = unique
    return result


def format_issue(issue: LintIssue) -> str:
    where = f"{issue.source}:{issue.line}" if issue.source else f"line {issue.line}"
    return f"[{issue.severity}] {where} ({issue.code}) {issue.message}"
