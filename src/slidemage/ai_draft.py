"""Protected regions of a slide: what a model must never rewrite (2026-08-31, direct instruction;
the whole-slide rewrite dialog was replaced by the chat's edit tools, 2026-10-10).

An open rewrite has no ground truth to check against, so two things keep it from being a blind,
high-risk edit:

1. **Mechanical protection**, not a prompt-only request: before the
   model ever sees the slide, mask_protected_regions() replaces the
   file's own leading header-comment block, its \\setSlideVersion{}
   line, and every \\vbox to 0pt{...} block (Slidemaster_preamble_base.tex's
   own absolute-overlay idiom -- see README.md's "Available layouts"
   section, "the same \\vbox to 0pt{\\vss ...} technique the footer/
   logo/title bar use") with opaque `%%%PROTECTED_N%%%` placeholder
   tokens. The model physically never sees that content, so it cannot
   rewrite, "improve", or subtly break calibrated positioning math or
   version-tracking metadata it has no way to understand -- deliberately
   *not* all tikz/overlay content, since an ordinary tikz chart or
   diagram is exactly the kind of thing a rewrite prompt might
   legitimately need to touch.
2. **Verified reconstruction**: unmask() refuses (returns None) unless
   every placeholder handed out comes back exactly once, unaltered, with
   no extra or invented ones -- a model that loses, duplicates, or
   hallucinates a protected block produces no usable proposal at all,
   rather than a "mostly right" one silently missing its footer.

The chat's edit tools (ai/tools/edits.py) use mask_protected_regions() to refuse an edit that
touches those regions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import draft_prompts

_PLACEHOLDER_TOKEN_RE = re.compile(r"%%%PROTECTED_(\d+)%%%")
_HEADER_COMMENT_LINE_RE = re.compile(r"^\s*%")
_SET_SLIDE_VERSION_RE = re.compile(r"^\\setSlideVersion\{[^}]*\}[ \t]*$", re.MULTILINE)
# Not a generic tikzpicture/overlay match -- deliberately anchored to this
# one specific wrapper (see this module's own docstring for why).
_VBOX_OPEN_RE = re.compile(r"\\vbox\s+to\s+0pt\s*\{")


def _find_matching_brace(text: str, open_pos: int) -> Optional[int]:
    """Index of the '}' matching the '{' at `open_pos`, or None if
    unbalanced. Same escaped-brace handling as latex_edit.matching_brace
    (the source editor's brace matcher)."""
    depth = 0
    i = open_pos
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _header_comment_end(text: str) -> int:
    """End offset (exclusive) of the file's own leading %-comment block --
    same rule as latex_edit.header_comment_lines:
    consecutive lines starting with optional whitespace then '%', up to
    the first line that isn't."""
    offset = 0
    for line in text.splitlines(keepends=True):
        if _HEADER_COMMENT_LINE_RE.match(line):
            offset += len(line)
        else:
            break
    return offset


@dataclass
class MaskResult:
    masked_text: str
    placeholders: dict[str, str]  # "%%%PROTECTED_0%%%" -> original text


def mask_protected_regions(text: str) -> MaskResult:
    """Replace every protected region in `text` with a unique placeholder
    token. See this module's own docstring for exactly what "protected"
    covers and why."""
    spans: list[list[int]] = []

    header_end = _header_comment_end(text)
    if header_end > 0:
        spans.append([0, header_end])

    for m in _SET_SLIDE_VERSION_RE.finditer(text):
        spans.append([m.start(), m.end()])

    for m in _VBOX_OPEN_RE.finditer(text):
        close = _find_matching_brace(text, m.end() - 1)
        if close is not None:
            spans.append([m.start(), close + 1])

    # Merge overlapping/adjacent spans (e.g. the header block butting
    # straight up against a \setSlideVersion line right after it) into
    # one placeholder each, so two placeholders can never end up
    # straddling or interleaving the same stretch of text.
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    placeholders: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0
    for i, (start, end) in enumerate(merged):
        token = f"%%%PROTECTED_{i}%%%"
        placeholders[token] = text[start:end]
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = end
    pieces.append(text[cursor:])
    return MaskResult(masked_text="".join(pieces), placeholders=placeholders)


def unmask(text: str, placeholders: dict[str, str]) -> tuple[Optional[str], list[str]]:
    """Restore every placeholder in `text` to its real protected content.

    Returns (reconstructed_text, problems). reconstructed_text is None --
    meaning this proposal must not be offered to the user at all -- unless
    every placeholder handed out in `placeholders` appears in `text`
    exactly once, with no extra/invented tokens and no duplicates.
    `problems` explains what went wrong for the caller to surface.
    """
    found_tokens = [f"%%%PROTECTED_{n}%%%" for n in _PLACEHOLDER_TOKEN_RE.findall(text)]
    expected = set(placeholders)
    found_set = set(found_tokens)

    problems: list[str] = []
    missing = expected - found_set
    unexpected = found_set - expected
    duplicated = {t for t in found_tokens if found_tokens.count(t) > 1}

    if missing:
        problems.append(
            f"{len(missing)} protected block(s) went missing from the model's output")
    if unexpected:
        problems.append(
            f"the model's output references {len(unexpected)} protected block(s) "
            f"that were never sent to it")
    if duplicated:
        problems.append(
            f"{len(duplicated)} protected block(s) were duplicated in the model's output")

    if problems:
        return None, problems

    result = text
    for token, original in placeholders.items():
        result = result.replace(token, original)
    return result, []


SYSTEM_PROMPT = """\
You are an expert LaTeX editor working on one slide (a beamer frame) from \
an academic finance-course slide deck. You are given the slide's complete \
raw LaTeX source and a request describing a change its author wants made.

Rewrite the source to carry out the request, and return the COMPLETE \
revised source -- not a diff, not just the changed part, not an \
explanation. Preserve everything not related to the request exactly as it \
is: LaTeX commands and environments you don't need to touch, the overall \
document structure, indentation style, and comments.

Some lines look like `%%%PROTECTED_N%%%` (N is a number). These are \
placeholders standing in for content that has been hidden from you and \
that you must not be able to edit. You MUST reproduce every one of these \
placeholder lines EXACTLY as given, verbatim, in your output, each in the \
same relative position in the document. Never invent a new one, never \
duplicate one, never remove one, never alter its digits.

Only use LaTeX commands and environments that are standard, or that \
already appear elsewhere in the slide you were given -- do not invent new \
custom macro names.

Return ONLY the revised LaTeX source as your answer: no markdown code \
fences, no commentary before or after it."""


def effective_system_prompt() -> str:
    """The slide-rewrite system prompt:
    the user's own saved override (Preferences dialog, draft_prompts.py)
    if they've set one, else this module's own hardcoded SYSTEM_PROMPT
    above."""
    return draft_prompts.get_custom_prompt(draft_prompts.KIND_SLIDE_REWRITE) or SYSTEM_PROMPT
