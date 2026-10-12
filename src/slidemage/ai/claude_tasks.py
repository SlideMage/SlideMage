"""The tasks SlideMage hands to a one-shot `claude -p` (Claude Code tasks plan, step 1): the rules the model
gets, the request text, the shape of the answer, and the check of an answer before anything is written.

A task has no tools; the model answers with JSON that SlideMage validates and applies itself. Two answer
shapes: a new text (`{"body": ...}`) and an edit list (`{"edits": [{"before", "after"}]}`, each `before` a
piece of the captured text that occurs exactly once). check() accepts an answer only if it is well formed, the
protected parts of the slide are unchanged and the text has no lint error the captured text did not have.
Pure: no Qt, no process (ai/claude_runner.py runs the task).
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from .. import latex_lint
from .tools.edits import protected_problem

LANGUAGE_NAMES = {"EN": "English", "DE": "German"}


@dataclass(frozen=True)
class Task:
    name: str
    rules: str                  # the system prompt
    schema: dict                # of the answer
    edits: bool = False         # the answer is an edit list, else the whole new text


def _schema(field: str, item: dict) -> dict:
    return {"type": "object", "properties": {field: item}, "required": [field], "additionalProperties": False}


_BODY = _schema("body", {"type": "string"})
_EDITS = _schema("edits", {"type": "array", "items": {
    "type": "object", "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
    "required": ["before", "after"], "additionalProperties": False}})

_KEEP = (
    "The request puts the source between <slide> tags; the tags are not part of it. Never change a comment "
    "line (starting with %), a \\setSlideVersion line or a \\vbox to 0pt{...} block. Keep the file's line "
    "breaks, tabs and indentation. Answer with the JSON result only.")

TRANSLATE = Task("translate", (
    "You translate the LaTeX source of one beamer slide of a university course. Return the whole translated "
    "source. Translate every piece of text the audience reads: frame titles, list items, table cells, "
    "footnotes, notes, source lines, and the text arguments of macros such as \\emph{...}, \\textbf{...}, "
    "\\SMLink{id}{text}. Leave nothing in the source language and add nothing. Keep everything else exactly as "
    "it is: LaTeX commands and their options, braces, environments, math, overlay specifications such as "
    "<2->, labels, citation keys, file names, slide ids, URLs, and the code shown in \\SMCode{...} and "
    "\\SMCmd{...}. The text is typeset with LuaLaTeX: write umlauts directly. Use the glossary's translations "
    "where it has the term. " + _KEEP), _BODY)

FIX_LATEX = Task("fix_latex", (
    "You fix LaTeX errors in the source of one beamer slide. You get the source and the errors a checker "
    "found in it. Remove each listed error with the smallest change that makes the source correct; change "
    "nothing else: no rewording, no reformatting, nothing the checker did not list. Answer with an edit "
    "list. `before` is a piece of the source copied character for character, tabs and spaces included, that "
    "occurs exactly once in it (add neighbouring text to make it unique); the pieces of different edits must "
    "not overlap; `after` replaces it. " + _KEEP), _EDITS, edits=True)


def translate_request(text: str, source: str, target: str, address: str = "Sie", glossary: str = "") -> str:
    """Translate `text` from `source` to `target` (codes of LANGUAGE_NAMES). `address` ("Sie" or "du") is
    told to the model for German, never left to it; `glossary` is the project's "EN = DE" lines, as they are."""
    lines = [f"Translate this slide from {LANGUAGE_NAMES[source]} to {LANGUAGE_NAMES[target]}."]
    if target == "DE":
        lines.append(f'Address the audience with "{address}" ({"formal" if address == "Sie" else "informal"}).')
    if glossary.strip():
        lines += ["Glossary, one term per line:", glossary.strip()]
    return "\n".join([*lines, "<slide>", text, "</slide>"])


def fix_request(text: str, issues: list[latex_lint.LintIssue]) -> str:
    """Fix the errors `issues` (lint_text of `text`) report in `text`."""
    errors = [latex_lint.format_issue(i) for i in issues if i.severity == latex_lint.ERROR]
    return "\n".join(["Fix these errors:", *errors, "<slide>", text, "</slide>"])


def repair_request(request: str, answer: dict | None, problems: list[str]) -> str:
    """The request again, with the answer that was refused and why."""
    return "\n".join([request, "", "Your previous answer was refused:", json.dumps(answer, ensure_ascii=False),
                      *(f"- {problem}" for problem in problems), "Answer again, correcting this."])


def _once(text: str, piece: str) -> int:
    """Where `piece` occurs in `text` exactly once (overlapping occurrences count), else -1."""
    first = text.find(piece)
    return first if first >= 0 and text.find(piece, first + 1) < 0 else -1


def _apply_edits(text: str, edits: list[dict]) -> tuple[str, list[str]]:
    spans, problems = [], []
    for number, edit in enumerate(edits, 1):
        before = edit["before"]
        start = _once(text, before) if before else -1
        if start < 0:
            seen = "is empty" if not before else \
                "does not occur in the source" if before not in text else "occurs more than once in the source"
            problems.append(f'edit {number}: "before" {seen}; copy a piece that occurs exactly once: {before[:60]!r}')
        else:
            spans.append((start, start + len(before), edit["after"]))
    spans.sort()
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        problems.append("two edits overlap")
    if problems:
        return text, problems
    out, end = [], 0
    for start, stop, after in spans:
        out += [text[end:start], after]
        end = stop
    return "".join(out) + text[end:], []


def _errors(text: str) -> Counter:
    return Counter((i.code, i.message) for i in latex_lint.lint_text(text) if i.severity == latex_lint.ERROR)


def check(task: Task, captured: str, answer: dict | None) -> tuple[str, list[str]]:
    """(new text, problems) for the model's `answer` to `task` on `captured`. With problems the text is
    `captured` and the problems are what to tell the model; without, the text is the result, equal to
    `captured` when there is nothing to change."""
    field = "edits" if task.edits else "body"
    value = answer.get(field) if isinstance(answer, dict) else None
    if task.edits:
        if not isinstance(value, list) or not all(
                isinstance(e, dict) and isinstance(e.get("before"), str) and isinstance(e.get("after"), str)
                for e in value):
            return captured, ['the answer must be {"edits": [{"before": ..., "after": ...}]}']
        new, problems = _apply_edits(captured, value)
    else:
        if not isinstance(value, str) or not value.strip():
            return captured, ['the answer must be {"body": "..."} with the text']
        new, problems = value, []
    if problems:
        return captured, problems
    if new == captured:
        return captured, []
    if problem := protected_problem(captured, new):
        return captured, [problem]
    added = _errors(new) - _errors(captured)
    if added:
        return captured, [f"the new text has a LaTeX error ({code}): {message}" for code, message in added]
    return new, []
