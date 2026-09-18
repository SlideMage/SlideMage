"""Check a slide/deck's raw LaTeX for likely syntax problems via a local
Ollama model (2026-08-31, direct instruction: a "Check syntax" button in
the slide/deck edit tabs).

Heuristic, not a real LaTeX parser: a language model can plausibly catch
unbalanced braces, mismatched \\begin{}/\\end{} pairs, and unescaped
special characters, but it has no notion of this project's own large set
of custom macros (\\tallitem, \\gothamArtifactBegin, \\slide{}, ...) being
genuinely valid syntax -- SYSTEM_PROMPT explicitly tells it not to flag an
unfamiliar command name on its own. Report every finding to the user as a
"possible issue" for a human to judge, never as a definitive error.

Reuses the same call/parse shape as alt_draft.py's own OllamaBackend/
OllamaTranslationBackend (structured JSON via Ollama's `format` option,
tolerating a wrapping <think> block) rather than importing its private
helpers -- small enough (one HTTP call, one parse function) that a second,
self-contained copy here is simpler than threading a new shared-module
import path through a file that is otherwise entirely about image
drafting/translation.

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

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_OLLAMA_HOST = "http://localhost:11434"

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
many of its own, e.g. \\tallitem, \\slide{}, \\gothamArtifactBegin -- an \
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

    @property
    def ok(self) -> bool:
        return self.error is None


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _parse_response_json(text: str) -> Optional[dict]:
    """Same tolerant parse as alt_draft.py's own _parse_response_json --
    strips a wrapping <think> block, falls back to the outermost
    brace-delimited span if a model wraps the JSON in prose despite the
    `format` constraint."""
    text = _THINK_TAG_RE.sub("", text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


@dataclass
class OllamaSyntaxChecker:
    model: str
    host: str = DEFAULT_OLLAMA_HOST
    num_ctx: int = 16384
    think: bool = False
    temperature: float = 0.1
    num_predict: int = 4096
    timeout: float = 300.0

    @property
    def label(self) -> str:
        return f"{self.model}{' +think' if self.think else ''}"

    def check(self, text: str) -> SyntaxCheckResult:
        lines = text.split("\n")
        numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
        payload = {
            "model": self.model,
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "options": {
                "num_ctx": self.num_ctx, "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(numbered_text=numbered)},
            ],
        }
        # Same reasoning as alt_draft.py's own backends: never send `think`
        # as an explicit false, only omit it or send true.
        if self.think:
            payload["think"] = True

        started = time.monotonic()
        try:
            request = urllib.request.Request(
                f"{self.host.rstrip('/')}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return SyntaxCheckResult(
                model=self.label, error=f"Ollama unreachable: {exc}",
                elapsed_s=time.monotonic() - started)
        except (TimeoutError, OSError) as exc:
            return SyntaxCheckResult(
                model=self.label, error=f"Ollama request failed: {exc}",
                elapsed_s=time.monotonic() - started)

        elapsed = time.monotonic() - started
        message = body.get("message") or {}
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""
        fields = _parse_response_json(content) or _parse_response_json(thinking)
        if fields is None:
            shown = content or thinking
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
