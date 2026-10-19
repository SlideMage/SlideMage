# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check a slide/deck's raw LaTeX for likely syntax problems via a local
(Ollama) or cloud (Claude) model (2026-08-31, direct instruction: a "Check
syntax" button in the slide/deck edit tabs; any ChatProvider since
2026-10-09).

Heuristic, not a real LaTeX parser: a language model can plausibly catch
unbalanced braces, mismatched \\begin{}/\\end{} pairs, and unescaped
special characters, but it has no notion of this project's own large set
of custom macros (\\tallitem, \\SMArtifactBegin, \\slide{}, ...) being
genuinely valid syntax -- SYSTEM_PROMPT explicitly tells it not to flag an
unfamiliar command name on its own. Report every finding to the user as a
"possible issue" for a human to judge, never as a definitive error.

The reply is requested as JSON (RESPONSE_SCHEMA) and parsed with
ai.providers.parse_json_object, shared with the image-description backend.

Safety of the "offer to fix" half: each SyntaxIssue carries the model's
own claimed `original` text for the line it is reporting, alongside its
`suggested_fix`. fix_is_safe() only ever allows a fix to be applied when
`original` matches the *live* buffer's own line content exactly --
a hallucinated line number or misremembered content makes the fix simply
unavailable (never silently applied to the wrong line). This is the
whole reason "replace the lines that contain the errors" is safe to
offer at all despite the checker itself being unreliable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .ai.providers import Cancelled, ChatProvider, ProviderError, parse_json_object

SYSTEM_PROMPT = """\
You are a meticulous LaTeX syntax checker. You are given the raw LaTeX \
source of one beamer slide or deck file from an academic slide deck \
project.

Find syntax problems: unbalanced or mismatched braces `{` `}`, mismatched \
\\begin{...}/\\end{...} pairs (wrong nesting, a \\begin with no matching \
\\end or vice versa), unescaped LaTeX special characters outside math mode \
(a literal %, &, _, or # that is not preceded by a backslash and is not \
part of a comment), and obviously malformed commands (a command name \
broken across a line, a brace argument left open, a stray closing brace \
with nothing to close).

Do NOT flag: custom macros you do not recognize (this project defines \
many of its own, e.g. \\tallitem, \\slide{}, \\SMArtifactBegin -- an \
unfamiliar command name is not itself an error), intentional TikZ/math \
syntax, or stylistic choices. Only report things you are reasonably \
confident are genuine syntax problems that would cause a LaTeX compile to \
fail or behave incorrectly.

The source is shown to you with each line prefixed "N: " giving its \
1-indexed line number, for your reference only -- that "N: " prefix is \
NOT part of the real file. Your "original" and "suggested_fix" fields \
must never include it, and must reproduce the real line's own \
leading whitespace exactly.

For each problem, report: the 1-indexed line number it starts on; a short \
description; the exact original text of that line, copied \
character-for-character (leading whitespace included, line-number prefix \
excluded); and, only if you are genuinely confident, a corrected \
replacement for that exact line. Leave suggested_fix as an empty string \
if you are not confident, rather than guessing.

If you find no problems, return an empty issues list. Do not invent \
problems just to have something to report."""

USER_TEMPLATE = """\
Here is the LaTeX source, with reference-only line numbers prefixed on \
each line as described above:

{numbered_text}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "problem": {"type": "string"},
                    "original": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                },
                "required": ["line", "problem", "original"],
            },
        },
    },
    "required": ["issues"],
}


@dataclass
class SyntaxIssue:
    line: int  # 1-indexed
    problem: str
    original: str = ""
    suggested_fix: str = ""

    def fix_is_safe(self, buffer_lines: list[str]) -> bool:
        """Whether `suggested_fix` can be safely auto-applied: there is
        one, and `original` exactly matches what is really on this line
        right now in `buffer_lines` (str.split("\\n") of the live buffer).
        The only guard standing between a model's claim about a line and
        actually overwriting it -- see this module's own docstring."""
        if not self.suggested_fix:
            return False
        index = self.line - 1
        if index < 0 or index >= len(buffer_lines):
            return False
        return buffer_lines[index] == self.original


@dataclass
class SyntaxCheckResult:
    issues: list[SyntaxIssue] = field(default_factory=list)
    model: str = ""
    elapsed_s: float = 0.0
    error: Optional[str] = None
    # True when SyntaxChecker.abort() ended the request (the user
    # pressed Escape) -- `error` then only says so, it is not a failure.
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class SyntaxChecker:
    provider: ChatProvider
    num_ctx: int = 16384
    think: bool = False
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: float = 300.0

    @property
    def label(self) -> str:
        return f"{self.provider.label}{' +think' if self.think else ''}"

    def abort(self) -> None:
        """Ends a running check() from another thread (2026-09-26, direct
        instruction: Escape aborts a running check). check() runs on a
        worker thread, abort() on the GUI thread."""
        self.provider.abort()

    def check(self, text: str) -> SyntaxCheckResult:
        lines = text.split("\n")
        numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        started = time.monotonic()
        try:
            reply = self.provider.chat(
                [{"role": "user", "content": USER_TEMPLATE.format(numbered_text=numbered)}],
                system=SYSTEM_PROMPT, schema=RESPONSE_SCHEMA,
                temperature=self.temperature, max_tokens=self.max_tokens,
                timeout=self.timeout, think=self.think, num_ctx=self.num_ctx)
        except Cancelled:
            return SyntaxCheckResult(
                model=self.label, error="Aborted.", cancelled=True,
                elapsed_s=time.monotonic() - started)
        except ProviderError as exc:
            return SyntaxCheckResult(
                model=self.label, error=str(exc), elapsed_s=time.monotonic() - started)

        elapsed = time.monotonic() - started
        fields = parse_json_object(reply.text) or parse_json_object(reply.thinking)
        if fields is None:
            shown = reply.text or reply.thinking
            error = (f"Model returned non-JSON output: {shown[:200]!r}" if shown
                    else "Model returned an empty response")
            return SyntaxCheckResult(model=self.label, error=error, elapsed_s=elapsed)

        issues: list[SyntaxIssue] = []
        for raw in fields.get("issues") or []:
            if not isinstance(raw, dict):
                continue
            try:
                line = int(raw.get("line"))
            except (TypeError, ValueError):
                continue
            issues.append(SyntaxIssue(
                line=line,
                problem=str(raw.get("problem") or "").strip(),
                original=str(raw.get("original") or ""),
                suggested_fix=str(raw.get("suggested_fix") or ""),
            ))
        return SyntaxCheckResult(issues=issues, model=self.label, elapsed_s=elapsed)
