# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The regular text of a slide's source: what a spellchecker may read and change, and nothing else
(docs/plans/ai-spellchecker.md, step 1; handover task ai-spellchecker, 2026-11-14, direct request: "the spell check
needs to be carefully scoped to only touch/check regular text: no LaTeX commands, URLs, etc.").

`prose_spans()` gives the stretches of prose as offsets into the file text. It is an allow-list: text is prose only
where a rule below says so, and whatever the scanner does not understand is left out, so an unclear case costs a
missed typo, never a broken slide.

- Prose: body text (also in list items and table cells); the text arguments of the commands in PROSE_COMMANDS
  (\\emph{...}, \\footnote{...}, the second argument of \\href, ...) and the title arguments of the environments in
  ENVIRONMENTS (a frame's or a block's title).
- Never prose: command names and the arguments of every other command (\\label, \\cite, \\includegraphics, \\url,
  colours, \\SMCode, a project's own macros); optional arguments [...] and overlay specifications <...>; math;
  verbatim, \\verb and \\iffalse...\\fi; comments; the protected %% header and \\setSlideVersion (protected_regions);
  URLs, e-mail addresses and file names; the bodies of the environments in SKIPPED_BODIES (math, TikZ, code); and
  words with TeX inside them (Gr\\"o\\ss e, hyphenation hints \\-), which are left out whole.

The invariant every span keeps: it contains none of SPECIAL (`\\ { } $ % & # ^ _ ~ [ ]`). An edit that stays
inside one span and whose replacement has none of them can therefore not touch a command, a group, math or a
comment. `apply_span_edits()` is the one write path that relies on it; `outside_prose()` checks a whole-text change
(the AI proofread) against the same spans.

Pure: no Qt, no I/O. `python -m slidemage.prose_spans FILE...` prints files with their spans marked, to check the
scope on real slides.
"""
from __future__ import annotations

import difflib
import re
import sys
from dataclasses import dataclass

from .alt_blocks import delimited_group_end
from .protected_regions import protected_spans
from .tex_source import IFFALSE_RE, VERB_RE, VERBATIM_ENV_RE, braced_argument, comment_start

SPECIAL = frozenset("\\{}$%&#^_~[]")
_MASK = "\0"            # what masked text is replaced by: it ends a span like a special character
_BREAKS = SPECIAL | {_MASK}

# Argument specifications: one letter per argument, in order.
#   *  an optional star          d  an optional overlay specification <...>     o  an optional [...]
#   m  a {...} that is not prose  T  a {...} that is prose                        U  an optional {...} that is prose
# The kind of a command's prose argument is the second element ("arg": text inside the body).
PROSE_COMMANDS: dict[str, tuple[str, str]] = {
    # standard LaTeX and beamer
    "textbf": ("dT", "arg"), "textit": ("dT", "arg"), "textsl": ("dT", "arg"), "textsc": ("dT", "arg"),
    "textup": ("dT", "arg"), "textmd": ("dT", "arg"), "textrm": ("dT", "arg"), "textsf": ("dT", "arg"),
    "textnormal": ("dT", "arg"), "emph": ("dT", "arg"), "underline": ("T", "arg"), "alert": ("dT", "arg"),
    "structure": ("dT", "arg"), "textsuperscript": ("T", "arg"), "textsubscript": ("T", "arg"),
    "mbox": ("T", "arg"), "enquote": ("*T", "arg"),
    "textcolor": ("dmT", "arg"), "colorbox": ("mT", "arg"),
    "href": ("omT", "arg"), "hyperlink": ("dmT", "arg"), "hyperref": ("oT", "arg"),
    "footnote": ("doT", "footnote"), "footnotetext": ("oT", "footnote"),
    "caption": ("oT", "caption"), "note": ("doT", "note"),
    "frametitle": ("doT", "title"), "framesubtitle": ("dT", "title"),
    "only": ("dT", "arg"), "uncover": ("dT", "arg"), "visible": ("dT", "arg"), "invisible": ("dT", "arg"),
    "onslide": ("*dT", "arg"), "alt": ("dTT", "arg"), "temporal": ("dTTT", "arg"),
    "parbox": ("ooomT", "arg"),
    "item": ("do", "item"),
    # SlideMage (latex/SlideMage_base.tex; latex_help.py documents them)
    "titleframe": ("TT", "title"), "quoteframe": ("TT", "body"), "quotesource": ("T", "arg"),
    "source": ("T", "footnote"), "SMAgendaTitle": ("T", "title"), "SMLink": ("mT", "arg"),
    "SMOrigHref": ("mT", "arg"), "SMQRCode": ("omTo", "caption"), "SMMugshot": ("mmmT", "caption"),
    "SMTikzword": ("mT", "arg"), "SMWarningSign": ("ommTmm", "arg"),
    "deckonly": ("doT", "arg"), "deckuncover": ("doT", "arg"), "deckvisible": ("doT", "arg"),
    "deckreveal": ("*oT", "arg"), "deckrevealfinal": ("*oT", "arg"),
    "tallitem": ("o", "item"), "tallitemnobullet": ("o", "item"),
}

# Commands whose arguments are never prose. Every command that is not in PROSE_COMMANDS is treated this way; the
# list names the ones latex_help.py and latex_help_standard.py document, so that test_prose_spans can make sure each
# documented command was decided on (a new one fails the test until it is put into one table or the other).
NO_PROSE = frozenset({
    # standard
    "includegraphics", "pause", "texttt", "color", "url", "label", "ref", "eqref", "cite", "citep", "citet",
    "vspace", "hspace", "newline", "centering", "frac", "sqrt", "sum", "prod", "int", "lim", "mathbb", "mathbf",
    "mathrm", "mathcal", "text", "left", "right", "hat", "bar", "cdot", "times", "leq", "neq", "approx", "infty",
    # SlideMage
    "cornerfigure", "fitfigure", "sectionfigure", "figurecenter", "fullbleedframe", "progressstrip", "chapterlogo",
    "sidefootnotes", "SMFinalStateForStudents", "SMManualTopMargin", "setSlideVersion", "SMDeckAgenda",
    "SMChapterAgenda", "SMSubsectionAgenda", "SMNavigationBar", "multilingualtext", "SMCode", "SMCmd",
    "SMCodeFile", "EUR", "SMUnderbrace", "SMTikzmark", "SMLineTop", "SMBulletEllipsis", "SMBulletEllipsisScript",
    "SMAlphaItem", "SMNumItem", "SMAlphaPeriodItem", "SMNumPeriodItem", "shrinklists", "SMTightDisplaySkips",
    "conditionalpause", "deckitem", "ifSMInstructorVersion", "ifSMDuringCourseVersion", "ifSMAfterCourseVersion",
    "SMArtifactBegin", "SMArtifactEnd", "slideID", "SMTocLabelFlushLeft", "SMEnumerateLabelFlushLeftShifted",
    "SMTocLabelExtraGap",
    "setlength", "deckversion", "decklanguage", "deckoutputfolder", "deckappendixtoc", "decktags",
    "setfootnotesymbols", "SMSetFootnoteMarkers", "SMAutoTopMarginfalse", "slide", "slideversion", "slidefinal",
    "conditionalslide", "slidestep", "omitslide", "omitslideversion",
})
# (\multilingualtext is prose, but handled on its own: its arguments carry their language. It is in NO_PROSE only
# so that the generic path never reads it.)

# Definitions and TeX boxes: everything up to and including the next brace group is code (\def\x#1{...},
# \vbox to 0pt{...}).
_DEFINITIONS = frozenset({"def", "gdef", "edef", "xdef", "hbox", "vbox", "vtop"})

# Environments: (the arguments after \begin{name}, the kind of their prose arguments, the kind of the body's text).
# An environment not listed here gets its arguments skipped and its body read as the text around it.
ENVIRONMENTS: dict[str, tuple[str, str, str]] = {
    "frame": ("doUU", "title", "body"), "block": ("dT", "title", "body"), "alertblock": ("dT", "title", "body"),
    "exampleblock": ("dT", "title", "body"), "itemize": ("do", "", "item"), "enumerate": ("do", "", "item"),
    "description": ("do", "", "item"), "columns": ("o", "", "body"), "column": ("om", "", "body"),
    "figure": ("o", "", "body"), "table": ("o", "", "body"), "tabular": ("om", "", "cell"),
    "tabularx": ("mm", "", "cell"), "center": ("", "", "body"), "minipage": ("ooom", "", "body"),
    "quote": ("", "", "body"), "quotation": ("", "", "body"),
    # SlideMage
    "standardframe": ("oT", "title", "body"), "sectionframe": ("T", "title", "body"),
    "figureframe": ("oT", "title", "body"), "highlightframe": ("T", "title", "body"),
    "sideimageframe": ("Tm", "title", "body"), "besidefigure": ("om", "", "body"),
    "SMTable": ("om", "", "cell"), "SMFloatingBlock": ("omT", "title", "body"),
    "SMFloatingExampleBlock": ("omT", "title", "body"), "SMFloatingInfoBlock": ("omT", "title", "body"),
    "definitionblock": ("T", "title", "body"), "infoblock": ("T", "title", "body"),
    "referenceblock": ("T", "title", "body"), "SMAlphaItemize": ("", "", "item"), "SMNumItemize": ("", "", "item"),
    "SMAlphaPeriodItemize": ("", "", "item"), "SMNumPeriodItemize": ("", "", "item"),
}

# Environments whose body is never prose: math, pictures and code. (The verbatim kinds are masked before the scan.)
SKIPPED_BODIES = frozenset({
    "equation", "equation*", "align", "align*", "alignat", "alignat*", "flalign", "flalign*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "displaymath", "math", "split", "array", "cases", "matrix",
    "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "tikzpicture", "tikzcd", "circuitikz",
    "forest", "axis", "tikzillustration", "verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment",
    "filecontents", "filecontents*",
})

# TeX inside a word: these join letters, so the word around them is left out whole.
_ACCENT_SYMBOLS = frozenset("'\"^~=.`")
_ACCENT_WORDS = frozenset({"u", "v", "H", "c", "d", "b", "t", "r", "k"})
_LETTER_WORDS = frozenset({"ss", "o", "O", "ae", "AE", "oe", "OE", "aa", "AA", "l", "L", "i", "j"})
_GLUE_SYMBOLS = frozenset("-/")

# Inside prose: addresses and file names are not words. Found before the scan, so a URL's own %, # or _ do not cut
# it into pieces that then look like prose.
_URL_RE = re.compile(r"(?:https?|ftp)://[^\s{}\\]+|\bwww\.[^\s{}\\]+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_FILE_RE = re.compile(
    r"[\w./-]*\w\.(?:tex|sty|cls|bib|bst|png|jpe?g|gif|svg|pdf|eps|tikz|txt|csv|tsv|json|xml|ya?ml|toml|md|html?"
    r"|py|r|do|js|css|zip|docx?|xlsx?|pptx?|odt|mp4|mov|mp3|wav)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"\w+(?:['’]\w+)*")
_SPACE = " \t"


@dataclass(frozen=True)
class Span:
    start: int              # offsets into the file text
    end: int
    kind: str               # "body", "item", "cell", "title", "footnote", "caption", "note" or "arg"
    language: str           # a lowercase code ("en"), or "" when the caller did not say


@dataclass(frozen=True)
class Word:
    start: int
    end: int
    text: str
    language: str


@dataclass(frozen=True)
class SpanEdit:
    start: int
    end: int
    before: str             # what text[start:end] read when it was checked
    after: str


# -- masking ----------------------------------------------------------------------------------------------------

def _masked(text: str) -> str:
    """`text` with everything that is never prose, and has to be found before the scan, replaced by _MASK (line
    breaks kept, offsets unchanged): comments, verbatim, \\verb, \\iffalse blocks, the protected regions, URLs,
    e-mail addresses and file names."""
    chars = list(text)

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = _MASK

    offset = 0
    for line in text.split("\n"):
        cut = comment_start(line)
        if cut >= 0:
            blank(offset + cut, offset + len(line))
        offset += len(line) + 1
    current = "".join(chars)
    for pattern in (VERBATIM_ENV_RE, IFFALSE_RE, VERB_RE):
        for match in pattern.finditer(current):
            blank(match.start(), match.end())
    for start, end in protected_spans(text):
        blank(start, end)
    current = "".join(chars)
    for pattern in (_URL_RE, _FILE_RE):
        for match in pattern.finditer(current):
            blank(match.start(), match.end())
    return "".join(chars)


# -- the scanner ------------------------------------------------------------------------------------------------

def _skip_space(text: str, pos: int, end: int) -> int:
    """Past spaces, tabs and at most one line break (a blank line ends a paragraph, and with it any argument)."""
    newline = False
    while pos < end:
        char = text[pos]
        if char in _SPACE or char == "\r":
            pos += 1
        elif char == "\n" and not newline:
            newline = True
            pos += 1
        else:
            break
    return pos


def _group_end(text: str, pos: int, end: int) -> int | None:
    """The offset after the brace group that opens at `pos`, or None."""
    _, after = braced_argument(text[:end], pos)
    return after if after > pos else None


class _Scanner:
    def __init__(self, masked: str) -> None:
        self.text = masked
        self.runs: list[tuple[int, int, str, str]] = []     # raw prose runs: start, end, kind, language
        self.glue_starts: set[int] = set()                  # a run ending here ends inside a word
        self.glue_ends: set[int] = set()                    # a run starting here starts inside a word

    def args(self, pos: int, end: int, spec: str) -> tuple[list[tuple[str, int, int]], int]:
        """Read the arguments `spec` describes from `pos`: [(letter, inner start, inner end)] of the brace groups
        and the offset after the last argument read. An optional argument that is not there is skipped; a mandatory
        one that is missing ends the reading."""
        text, groups = self.text, []
        for letter in spec:
            at = _skip_space(text, pos, end)
            if letter == "*":
                if at < end and text[at] == "*":
                    pos = at + 1
            elif letter in "do":
                opening, closing = ("<", ">") if letter == "d" else ("[", "]")
                after = delimited_group_end(text[:end], at, opening, closing) if at < end and text[at] == opening \
                    else None
                if after is not None:
                    pos = after
            else:                                   # m, T, U
                after = _group_end(text, at, end) if at < end and text[at] == "{" else None
                if after is None:
                    if letter == "U":
                        continue
                    break
                groups.append((letter, at + 1, after - 1))
                pos = after
        return groups, pos

    def skip_groups(self, pos: int, end: int) -> int:
        """Past every argument that directly follows an unknown command: a star, <...>, [...] and {...} groups."""
        text = self.text
        while True:
            at = _skip_space(text, pos, end)
            if at >= end:
                return pos
            char = text[at]
            if char == "*" and at == pos:
                pos = at + 1
                continue
            after = None
            if char == "{":
                after = _group_end(text, at, end)
            elif char in "[<":
                after = delimited_group_end(text[:end], at, char, "]" if char == "[" else ">")
            if after is None:
                return pos
            pos = after

    def math_end(self, pos: int, end: int) -> int:
        """The offset after the math that starts at `pos` ($, $$, \\( or \\[); the end of the range if unclosed."""
        text = self.text
        if text.startswith("$$", pos):
            closing, start = "$$", pos + 2
        elif text[pos] == "$":
            closing, start = "$", pos + 1
        else:
            closing, start = ("\\)" if text[pos + 1] == "(" else "\\]"), pos + 2
        cursor = start
        while cursor < end:
            if text.startswith(closing, cursor):
                return cursor + len(closing)
            cursor += 2 if text[cursor] == "\\" and closing.startswith("$") else 1
        return end

    def environment_end(self, name: str, pos: int, end: int) -> int:
        """The offset after the \\end{name} that closes the environment whose body starts at `pos`."""
        pattern = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
        depth = 1
        for match in pattern.finditer(self.text, pos, end):
            depth += 1 if match.group(1) == "begin" else -1
            if depth == 0:
                return match.end()
        return end

    def scan(self, pos: int, end: int, kind: str, language: str) -> None:
        """Collect the prose runs of text[pos:end], read as text of `kind` in `language`."""
        text = self.text
        run_start = None

        def close(at: int) -> None:
            nonlocal run_start
            if run_start is not None and at > run_start:
                self.runs.append((run_start, at, kind, language))
            run_start = None

        while pos < end:
            char = text[pos]
            if char not in _BREAKS:
                if run_start is None:
                    run_start = pos
                pos += 1
                continue
            close(pos)
            if char == "$":
                pos = self.math_end(pos, end)
            elif char == "\\":
                pos, kind = self.command(pos, end, kind, language)
            else:                                   # a brace, a special character or masked text
                pos += 1
        close(end)

    def command(self, pos: int, end: int, kind: str, language: str) -> tuple[int, str]:
        """Handle the control sequence at `pos`: (the offset to go on from, the kind of the text that follows)."""
        text = self.text
        if pos + 1 >= end:
            return end, kind
        nxt = text[pos + 1]
        if not (nxt.isalpha() or nxt == "@"):                       # a control symbol
            if nxt in "([":
                return self.math_end(pos, end), kind
            if nxt == "\\":                                         # a line break: \\*[<length>]
                _, after = self.args(pos + 2, end, "*o")
                return after, kind
            if nxt in _ACCENT_SYMBOLS:
                self.glue_starts.add(pos)
                after = pos + 2
                at = _skip_space(text, after, end)
                if at < end and text[at] == "{":
                    after = _group_end(text, at, end) or after
                elif at < end and text[at].isalpha():
                    after = at + 1
                self.glue_ends.add(after)
                return after, kind
            if nxt in _GLUE_SYMBOLS:
                self.glue_starts.add(pos)
                self.glue_ends.add(pos + 2)
            return pos + 2, kind
        cursor = pos + 1
        while cursor < end and (text[cursor].isalpha() or text[cursor] == "@"):
            cursor += 1
        name = text[pos + 1:cursor]
        if name in _LETTER_WORDS or name in _ACCENT_WORDS:
            self.glue_starts.add(pos)
            after = cursor
            at = _skip_space(text, after, end) if name in _ACCENT_WORDS else after
            if name in _ACCENT_WORDS:
                if at < end and text[at] == "{":
                    after = _group_end(text, at, end) or after
                elif at < end and text[at].isalpha():
                    after = at + 1
            else:                       # \ss eats the spaces after it, and \ss{} ends the name the same way
                while after < end and text[after] in _SPACE:
                    after += 1
                if text.startswith("{}", after):
                    after += 2
            self.glue_ends.add(after)
            return after, kind
        if name == "begin":
            return self.begin(cursor, end, kind, language)
        if name == "end":
            _, after = self.args(cursor, end, "m")
            return after, kind
        if name == "let":                           # \let\new\old: the rest of the line
            newline = text.find("\n", cursor, end)
            return (newline if newline >= 0 else end), kind
        if name in _DEFINITIONS:
            brace = text.find("{", cursor, end)
            return (_group_end(text, brace, end) or end) if brace >= 0 else end, kind
        if name == "multilingualtext":
            return self.multilingual(cursor, end, kind), kind
        if name in PROSE_COMMANDS:
            spec, own_kind = PROSE_COMMANDS[name]
            groups, after = self.args(cursor, end, spec)
            for letter, start, stop in groups:
                if letter in "TU":
                    self.scan(start, stop, kind if own_kind in ("arg", "body") else own_kind, language)
            return after, own_kind if own_kind == "item" else kind
        return self.skip_groups(self.assignment(cursor, end), end), kind

    def assignment(self, pos: int, end: int) -> int:
        """Past `= value` after a register name (\\prevdepth=0pt, \\parskip = 1ex plus 1pt): to the end of the
        value's first word or the next control sequence."""
        text = self.text
        at = pos
        while at < end and text[at] in _SPACE:
            at += 1
        if at >= end or text[at] != "=":
            return pos
        at += 1
        while at < end and text[at] in _SPACE:
            at += 1
        while at < end and not text[at].isspace() and text[at] not in _BREAKS:
            at += 1
        return at

    def begin(self, pos: int, end: int, kind: str, language: str) -> tuple[int, str]:
        groups, after = self.args(pos, end, "m")
        if not groups:
            return after, kind
        _, start, stop = groups[0]
        name = self.text[start:stop].strip()
        if name in SKIPPED_BODIES:
            return self.environment_end(name, after, end), kind
        if name in ENVIRONMENTS:
            spec, arg_kind, body_kind = ENVIRONMENTS[name]
            groups, after = self.args(after, end, spec)
            for letter, start, stop in groups:
                if letter in "TU":
                    self.scan(start, stop, arg_kind, language)
            # The body is read on as the text around it; its kind is the environment's until \end{name}.
            body_end = self.environment_end(name, after, end)
            close_at = self.text.rfind("\\end", after, body_end)
            self.scan(after, close_at if close_at >= after else body_end, body_kind, language)
            return body_end, kind
        return self.skip_groups(after, end), kind

    def multilingual(self, pos: int, end: int, kind: str) -> int:
        r"""\multilingualtext{EN text}{DE text}, or \multilingualtext*{EN={...}, DE={...}}: each text in its
        language."""
        text = self.text
        at = _skip_space(text, pos, end)
        if at < end and text[at] == "*":
            groups, after = self.args(at + 1, end, "m")
            if groups:
                _, start, stop = groups[0]
                for match in re.finditer(r"([A-Za-z]{2,3})\s*=\s*\{", text[start:stop]):
                    brace = start + match.end() - 1
                    close = _group_end(text, brace, stop)
                    if close is not None:
                        self.scan(brace + 1, close - 1, kind, match.group(1).lower())
            return after
        groups, after = self.args(pos, end, "TT")
        for (_, start, stop), language in zip(groups, ("en", "de")):
            self.scan(start, stop, kind, language)
        return after


def prose_spans(text: str, language: str = "") -> list[Span]:
    """The prose of `text` (a slide's source) as spans, in order. `language` is the file's own language as a code;
    the arguments of \\multilingualtext get theirs."""
    scanner = _Scanner(_masked(text))
    scanner.scan(0, len(text), "body", language.lower())
    spans = []
    for start, end, kind, lang in sorted(scanner.runs):
        if start in scanner.glue_ends:                  # the rest of a word with TeX inside: left out
            while start < end and text[start].isalpha():
                start += 1
        if end in scanner.glue_starts:
            while end > start and text[end - 1].isalpha():
                end -= 1
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if any(char.isalpha() for char in text[start:end]):
            spans.append(Span(start, end, kind, lang))
    return spans


def words(text: str, spans: list[Span]) -> list[Word]:
    """The words of `spans` in `text`: letters (with an inner apostrophe), split at hyphens and other punctuation.
    Tokens with a digit or an underscore, and abbreviations in capitals of up to five letters, are left out."""
    found = []
    for span in spans:
        for match in _WORD_RE.finditer(text, span.start, span.end):
            token = match.group()
            if any(char.isdigit() or char == "_" for char in token) or (token.isupper() and len(token) <= 5):
                continue
            found.append(Word(match.start(), match.end(), token, span.language))
    return found


# -- changing prose ---------------------------------------------------------------------------------------------

def _inside(text: str, spans: list[Span], start: int, end: int) -> bool:
    """Whether text[start:end] lies inside one span. An insertion at a span's start counts only after a character
    that is not a letter: after \\ldots in "\\ldots." a letter would become part of the command's name."""
    for span in spans:
        if span.start <= start and end <= span.end:
            if start == end == span.start and start > 0 and (text[start - 1].isalpha() or text[start - 1] == "@"):
                return False
            return True
    return False


def replacement_problem(after: str) -> str | None:
    """Why `after` may not go into a span, or None."""
    if any(char in SPECIAL for char in after):
        return f"the replacement {after!r} contains a LaTeX special character"
    if "\n" in after or "\r" in after:
        return f"the replacement {after!r} contains a line break"
    if _URL_RE.search(after):
        return f"the replacement {after!r} contains an address"
    return None


def apply_span_edits(text: str, edits: list[SpanEdit], language: str = "") -> tuple[str, list[str]]:
    """(the new text, problems). Each edit must lie inside one prose span of `text`, `text` must still read
    `before` there, and `after` must pass replacement_problem(). With any problem nothing is changed."""
    spans = prose_spans(text, language)
    problems = []
    for edit in edits:
        if text[edit.start:edit.end] != edit.before:
            problems.append(f"the text at {edit.start} no longer reads {edit.before!r}")
        elif not _inside(text, spans, edit.start, edit.end):
            problems.append(f"{edit.before!r} at {edit.start} is not regular text")
        elif problem := replacement_problem(edit.after):
            problems.append(problem)
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
        problems.append("two edits overlap")
    if problems:
        return text, problems
    out, cursor = [], 0
    for edit in ordered:
        out += [text[cursor:edit.start], edit.after]
        cursor = edit.end
    return "".join(out) + text[cursor:], []


def outside_prose(old: str, new: str) -> str | None:
    """Why `new` is not `old` with only its prose changed, or None. Every changed stretch of `old` must lie inside
    one prose span (an insertion at a span's edge counts as inside), and what replaces it must pass
    replacement_problem()."""
    spans = prose_spans(old)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if not _inside(old, spans, i1, i2):
            shown = old[max(0, i1 - 20):i2 + 20].strip()
            return (f"the change near {shown!r} is outside the regular text: commands and their arguments, math, "
                    "URLs, file names, labels, citation keys and comments stay exactly as they are")
        if problem := replacement_problem(new[j1:j2]):
            return problem
    return None


# -- developer view ---------------------------------------------------------------------------------------------

def marked(text: str, spans: list[Span]) -> str:
    """`text` with each span between ⟦ and ⟧."""
    out, cursor = [], 0
    for span in spans:
        out += [text[cursor:span.start], "⟦", text[span.start:span.end], "⟧"]
        cursor = span.end
    return "".join(out) + text[cursor:]


def main(argv: list[str]) -> int:
    """python -m slidemage.prose_spans FILE...: each file with its prose spans marked."""
    if not argv:
        print("usage: python -m slidemage.prose_spans FILE...", file=sys.stderr)
        return 2
    for name in argv:
        with open(name, encoding="utf-8") as handle:
            text = handle.read()
        code = re.match(r"[^-]+-([A-Z]{2})-", name.replace("\\", "/").rsplit("/", 1)[-1])
        spans = prose_spans(text, code.group(1) if code else "")
        print(f"== {name}: {len(spans)} spans, {len(words(text, spans))} words")
        print(marked(text, spans))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
