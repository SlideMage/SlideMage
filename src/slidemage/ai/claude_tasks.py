"""The tasks SlideMage hands to a one-shot `claude -p` (Claude Code tasks plan, step 1): the rules the model
gets, the request text, the shape of the answer, and the check of an answer before anything is written.

A task has no tools; the model answers with JSON that SlideMage validates and applies itself. Four answer
shapes: a new text (`{"body": ...}`), an edit list (`{"edits": [{"before", "after"}]}`, each `before` a piece
of the captured text that occurs exactly once), a new frame title (`{"title": ...}`) and a speaker note
(`{"note": ...}`); the summary of a deck (`{"summary": ...}`) is read, never written. check() turns the answer into the new text and accepts it only if it is well formed, the
protected parts of the slide are unchanged and the text has no lint error the captured text did not have.
Pure: no Qt, no process (ai/claude_runner.py runs the task).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from .. import latex_lint, slide_source
from .tools.edits import protected_problem

LANGUAGE_NAMES = {"EN": "English", "DE": "German"}
SLIDE_CHARS, DECK_CHARS = 1500, 60000      # what a summary request carries: per slide, and in all


@dataclass(frozen=True)
class Task:
    name: str
    rules: str                  # the system prompt
    schema: dict                # of the answer: one property, "body", "edits", "title" or "note"
    keeps_structure: bool = False   # the new text has the same environments, overlay specifications and citations

    @property
    def answer(self) -> str:
        return next(iter(self.schema["properties"]))


def _schema(field: str, item: dict) -> dict:
    return {"type": "object", "properties": {field: item}, "required": [field], "additionalProperties": False}


_BODY = _schema("body", {"type": "string"})
_TITLE = _schema("title", {"type": "string"})
_NOTE = _schema("note", {"type": "string"})
_SUMMARY = _schema("summary", {"type": "string"})
_EDITS = _schema("edits", {"type": "array", "items": {
    "type": "object", "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
    "required": ["before", "after"], "additionalProperties": False}})

_PROTECT = (
    "Never change a comment line (starting with %), a \\setSlideVersion line or a \\vbox to 0pt{...} block. "
    "Keep the file's line breaks, tabs and indentation. Answer with the JSON result only.")
_KEEP = "The request puts the source between <slide> tags; the tags are not part of it. " + _PROTECT
# What no task may change: everything of a slide that is not text the audience reads.
_MARKUP = (
    "LaTeX commands and their options, braces, environments, math, overlay specifications such as <2->, labels, "
    "citation keys, file names, slide ids, URLs, and the code shown in \\SMCode{...} and \\SMCmd{...}. ")
_TRANSLATION = (
    "The text is typeset with LuaLaTeX: write umlauts directly. Use the glossary's translations where it has "
    "the term. ")

TRANSLATE = Task("translate", (
    "You translate the LaTeX source of one beamer slide of a university course. Return the whole translated "
    "source. Translate every piece of text the audience reads: frame titles, list items, table cells, "
    "footnotes, notes, source lines, and the text arguments of macros such as \\emph{...}, \\textbf{...}, "
    "\\SMLink{id}{text}. Leave nothing in the source language and add nothing. Keep everything else exactly as "
    "it is: " + _MARKUP + _TRANSLATION + _KEEP), _BODY)

_EDIT_LIST = (
    "Answer with an edit list. `before` is a piece of the source copied character for character, tabs and "
    "spaces included, that occurs exactly once in it (add neighbouring text to make it unique); the pieces of "
    "different edits must not overlap; `after` replaces it. ")
_TEXT = (
    "Change only the text the audience reads (frame titles, list items, table cells, footnotes, source "
    "lines, the text arguments of macros such as \\emph{...} and \\textbf{...}); never " + _MARKUP)

FIX_LATEX = Task("fix_latex", (
    "You fix LaTeX errors in the source of one beamer slide. You get the source and the errors a checker "
    "found in it. Remove each listed error with the smallest change that makes the source correct; change "
    "nothing else: no rewording, no reformatting, nothing the checker did not list. " + _EDIT_LIST + _KEEP),
    _EDITS)

UPDATE_TRANSLATION = Task("update_translation", (
    "You update the translation of one beamer slide of a university course after its source changed. The "
    "request has the current source between <source> tags and the existing translation between <slide> tags; "
    "the tags are not part of either. Return the whole updated translation: change only what the source's "
    "changes require, and keep the translation's wording, line breaks, tabs and indentation wherever the "
    "source did not change. Translate every new or changed piece of text the audience reads and leave nothing "
    "in the source language. Keep everything else exactly as it is in the translation: " + _MARKUP + _TRANSLATION
    + _PROTECT), _BODY)

PROOFREAD = Task("proofread", (
    "You proofread the LaTeX source of one beamer slide of a university course. Fix spelling, grammar, "
    "punctuation and capitalization mistakes, and nothing else: no rewording, no restyling, no shortening, "
    "the meaning stays. " + _TEXT + "Where there is nothing to fix, answer with an empty edit list. " +
    _EDIT_LIST + _KEEP), _EDITS)

CONCISE = Task("concise", (
    "You make the text of one beamer slide of a university course more concise: shorter wording, no filler, "
    "the same statements. " + _TEXT + "Keep the language of the text and the slide's structure: every "
    "environment, overlay specification and citation stays, in the same order. Return the whole shortened "
    "source. " + _KEEP), _BODY, keeps_structure=True)

TITLE = Task("title", (
    "You write a better title for one beamer slide of a university course: shorter and more informative, in "
    "the language of the slide, no longer than the slide's text supports. The request has the current title "
    "and the slide's source between <slide> tags. Answer with the new title text only, a single line, without "
    "the frame command around it and without line breaks. Keep a \\footnote{...} of the current title "
    "unchanged."), _TITLE)

NOTE = Task("note", (
    "You write the speaker note of one beamer slide of a university course: what the instructor says to "
    "present it, in two to four plain sentences, in the language of the slide, the slide's own terms. The "
    "request has the slide's source between <slide> tags. Answer with the note text only, without the "
    "\\note command around it."), _NOTE)

SUMMARISE = Task("summarise", (
    "You summarise a deck of beamer slides of a university course for its instructor. The request has the "
    "slides' LaTeX source, each between <slide> tags. Write a short summary in the language of the slides: "
    "what the deck covers, in the order of the slides, in a few short paragraphs or bullet points, without "
    "LaTeX. Answer with the summary text only."), _SUMMARY)


def translate_request(text: str, source: str, target: str, address: str = "Sie", glossary: str = "") -> str:
    """Translate `text` from `source` to `target` (codes of LANGUAGE_NAMES). `address` ("Sie" or "du") is
    told to the model for German, never left to it; `glossary` is the project's "EN = DE" lines, as they are."""
    lines = [f"Translate this slide from {LANGUAGE_NAMES[source]} to {LANGUAGE_NAMES[target]}.",
             *_style(target, address, glossary)]
    return "\n".join([*lines, "<slide>", text, "</slide>"])


def _style(target: str, address: str, glossary: str) -> list[str]:
    """The request lines on the German form of address and the glossary."""
    lines = [f'Address the audience with "{address}" ({"formal" if address == "Sie" else "informal"}).'] \
        if target == "DE" else []
    return lines + (["Glossary, one term per line:", glossary.strip()] if glossary.strip() else [])


def update_request(source: str, translation: str, source_language: str, target: str, address: str = "Sie",
                   glossary: str = "") -> str:
    """Bring `translation` (into `target`) up to date with `source` (in `source_language`); `address` and
    `glossary` as in translate_request."""
    lines = [f"Update this {LANGUAGE_NAMES[target]} translation to match the current {LANGUAGE_NAMES[source_language]} "
             "source.", *_style(target, address, glossary)]
    return "\n".join([*lines, "<source>", source, "</source>", "<slide>", translation, "</slide>"])


def proofread_request(text: str, language: str, address: str = "Sie") -> str:
    """Proofread `text`, a slide in `language` (a code of LANGUAGE_NAMES); the German form of `address` stays."""
    lines = [f"Proofread this {LANGUAGE_NAMES[language]} slide with the spelling rules of its language; keep the "
             "variant of the language that it uses."]
    if language == "DE":
        lines.append(f'The audience is addressed with "{address}": keep it.')
    return "\n".join([*lines, "<slide>", text, "</slide>"])


def concise_request(text: str) -> str:
    return "\n".join(["Make the text of this slide more concise.", "<slide>", text, "</slide>"])


def title_request(text: str) -> str:
    """A better title for the slide `text`, which has a frame title (slide_source.title_span)."""
    start, end = slide_source.title_span(text)
    return "\n".join(["Write a better title for this slide.", f"Current title: {text[start:end]}",
                      "<slide>", text, "</slide>"])


def note_request(text: str) -> str:
    return "\n".join(["Write the speaker note for this slide.", "<slide>", text, "</slide>"])


def summarise_request(bodies: list[str]) -> str:
    """Summarise the deck whose slides have the sources `bodies`: each is cut after SLIDE_CHARS characters, and
    slides that would take the request past DECK_CHARS are left out (the request says how many)."""
    parts, size = ["Summarise this deck."], 0
    for number, body in enumerate(bodies):
        slide = f"<slide>\n{body[:SLIDE_CHARS]}\n</slide>"
        size += len(slide)
        if size > DECK_CHARS:
            parts.append(f"({len(bodies) - number} more slides are not shown.)")
            break
        parts.append(slide)
    return "\n".join(parts)


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


_STRUCTURE_RE = re.compile(
    r"\\(?:begin|end)\{[^}]*\}|<[-+\d,|:]+>|\\[A-Za-z]*[cC]ite[A-Za-z]*\*?(?:\[[^\]]*\])*\{[^}]*\}")


def _structure_problem(captured: str, new: str) -> str | None:
    """The message to give the model when `new` has other environments, overlay specifications or citations
    than `captured`."""
    before, after = Counter(_STRUCTURE_RE.findall(captured)), Counter(_STRUCTURE_RE.findall(new))
    changed = list((before - after) | (after - before))
    return None if not changed else ("the new text must keep every environment, overlay specification and "
                                     f"citation; these differ: {', '.join(sorted(changed)[:5])}")


def _new_text(task: Task, captured: str, value) -> tuple[str, list[str]]:
    """(the text `value` makes of `captured`, problems) for the answer's one property."""
    if task.answer == "edits":
        if not isinstance(value, list) or not all(
                isinstance(e, dict) and isinstance(e.get("before"), str) and isinstance(e.get("after"), str)
                for e in value):
            return captured, ['the answer must be {"edits": [{"before": ..., "after": ...}]}']
        return _apply_edits(captured, value)
    if not isinstance(value, str) or not value.strip() or (task.answer == "title" and "\n" in value.strip()):
        return captured, [f'the answer must be {{"{task.answer}": "..."}} with the '
                          f'{"title in one line" if task.answer == "title" else "text"}']
    if task.answer == "title":
        if slide_source.title_span(captured) is None:
            return captured, ["the slide has no frame title to replace"]
        return slide_source.set_title(captured, value.strip()), []
    if task.answer == "note":
        return slide_source.add_note(captured, value.strip()), []
    return value, []


def check(task: Task, captured: str, answer: dict | None) -> tuple[str, list[str]]:
    """(new text, problems) for the model's `answer` to `task` on `captured`. With problems the text is
    `captured` and the problems are what to tell the model; without, the text is the result, equal to
    `captured` when there is nothing to change."""
    new, problems = _new_text(task, captured, answer.get(task.answer) if isinstance(answer, dict) else None)
    if problems:
        return captured, problems
    if new == captured or task.answer == "summary":     # a summary is no edit of `captured`: nothing to protect
        return new, []
    if problem := protected_problem(captured, new) or (task.keeps_structure and _structure_problem(captured, new)):
        return captured, [problem]
    added = _errors(new) - _errors(captured)
    if added:
        return captured, [f"the new text has a LaTeX error ({code}): {message}" for code, message in added]
    return new, []
