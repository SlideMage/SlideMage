# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure TeX source-text patterns and masking helpers."""
from __future__ import annotations

import re

# An unescaped "%" starts a comment running to end of line; "\%" (a
# literal percent sign) does not. "Unescaped" here means "not immediately
# preceded by a single backslash". The classic even/odd-backslash case
# ("\\%") is not handled by this approximation. is_commented() uses it
# to recognize a commented-out \section{}/\slide{}-family call.
COMMENT_RE = re.compile(r"(?<!\\)%.*")

VERBATIM_ENV_RE = re.compile(
    r"\\begin\{(verbatim\*?|Verbatim|lstlisting|minted)\}.*?\\end\{\1\}", re.DOTALL)
IFFALSE_RE = re.compile(r"\\iffalse\b.*?\\fi\b", re.DOTALL)
VERB_RE = re.compile(r"\\verb\*?([^a-zA-Z\s*])(.*?)\1")

INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")


def is_commented(text: str, pos: int) -> bool:
    """Whether the character at `pos` in `text` falls inside a "%"-started
    LaTeX comment -- true if an unescaped "%" appears anywhere between the
    start of pos's own line and pos itself. Shared by deck_scan.parse_chapters()
    and deck_editor.is_commented_out(), so a commented-out
    \\section{}/\\slide{}-family call is recognized as not really there by
    both deck_scan's chapter list and appendix_toc.py's own slide-call
    filtering. Unlike _parse_output_folders()/find_decktags()'s own
    narrower "starts-with-%" check, this also catches a macro that follows
    a live "%" occurring earlier on the same line, not just one at the very
    start of it."""
    line_start = text.rfind("\n", 0, pos) + 1
    return bool(COMMENT_RE.search(text, line_start, pos))


def comment_start(line: str) -> int:
    r"""Index of the "%" that starts a comment in one line, or -1. A backslash escapes the next character, so
    "\\%" (a line break, then a comment) is a comment and "\%" is not; COMMENT_RE does not tell these apart."""
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 2
        elif line[i] == "%":
            return i
        else:
            i += 1
    return -1


def masked_same_length(text: str) -> str:
    """`text` with comments replaced by spaces (offsets preserved)."""
    out = []
    for line in text.split("\n"):
        cut = comment_start(line)
        out.append(line if cut < 0 else line[:cut] + " " * (len(line) - cut))
    return "\n".join(out)


def blanked_verbatim(text: str) -> str:
    """`text` with verbatim bodies, \\verb and \\iffalse blocks replaced by spaces (offsets and line breaks kept)."""
    for pattern in (VERBATIM_ENV_RE, IFFALSE_RE, VERB_RE):
        text = pattern.sub(lambda match: re.sub(r"[^\n]", " ", match.group()), text)
    return text


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
