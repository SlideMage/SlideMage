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


def masked_same_length(text: str) -> str:
    """`text` with comments replaced by spaces (offsets preserved)."""
    out = []
    for line in text.split("\n"):
        i, n, cut = 0, len(line), -1
        while i < n:
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line if cut < 0 else line[:cut] + " " * (n - cut))
    return "\n".join(out)
