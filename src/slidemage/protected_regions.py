# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Protected regions of a slide: what a model must never rewrite (2026-08-31, direct instruction;
moved here from ai_draft.py when the whole-slide rewrite dialog was replaced by the chat's edit tools).

An open rewrite has no ground truth to check against, so a model must not be able to touch what it
cannot understand: mask_protected_regions() replaces the file's own leading header-comment block, its
\\setSlideVersion{} line with opaque `%%%PROTECTED_N%%%` placeholder tokens, and says where they were.
That is version-tracking metadata SlideMage maintains itself.

(2026-10-30, direct request, after slide tjn: \\vbox to 0pt{...} blocks -- Slidemaster_preamble_base.tex's
own absolute-overlay idiom, see README.md's "Available layouts" section -- used to be protected too, as
calibrated positioning math. On tjn the model refused to turn annotation lines into arrows or move a label
and a box, because they all sat in such a block. They are ordinary slide content the user wants the AI to
edit, so they are no longer protected; the model is told they hold measured page coordinates, to change
those only when asked and to check the result with render_preview.)

The chat's edit tools (ai/tools/edits.py) use mask_protected_regions() to refuse an edit that
touches those regions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


_HEADER_COMMENT_LINE_RE = re.compile(r"^\s*%")
_SET_SLIDE_VERSION_RE = re.compile(r"^\\setSlideVersion\{[^}]*\}[ \t]*$", re.MULTILINE)


def _header_comment_span(text: str) -> Optional[tuple[int, int]]:
    """Start and end offset of the file's own leading %-comment block -- same rule as
    latex_edit.header_comment_lines: consecutive lines starting with optional whitespace then '%', up to
    the first line that isn't. A leading byte-order mark is not part of it."""
    start = end = 1 if text.startswith("\ufeff") else 0
    for line in text[start:].splitlines(keepends=True):
        if not _HEADER_COMMENT_LINE_RE.match(line):
            break
        end += len(line)
    return (start, end) if end > start else None


@dataclass
class MaskResult:
    masked_text: str
    placeholders: dict[str, str]  # "%%%PROTECTED_0%%%" -> original text


def protected_spans(text: str) -> list[list[int]]:
    """The protected regions of `text` as [start, end] offsets, in order, overlapping or adjacent ones merged."""
    spans: list[list[int]] = []

    header = _header_comment_span(text)
    if header:
        spans.append(list(header))

    for m in _SET_SLIDE_VERSION_RE.finditer(text):
        spans.append([m.start(), m.end()])

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
    return merged


def mask_protected_regions(text: str) -> MaskResult:
    """Replace every protected region in `text` with a unique placeholder
    token. See this module's own docstring for exactly what "protected"
    covers and why."""
    placeholders: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0
    for i, (start, end) in enumerate(protected_spans(text)):
        token = f"%%%PROTECTED_{i}%%%"
        placeholders[token] = text[start:end]
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = end
    pieces.append(text[cursor:])
    return MaskResult(masked_text="".join(pieces), placeholders=placeholders)
