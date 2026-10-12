"""A deck's deck-wide settings: the lines of its preamble the Deck settings sheet
(ui/dialogs/deck_settings.py) reads and writes -- template, language, footer
text, course link, output folders and the appendix TOC.

Everything here is plain text in, text out, so the dialog can apply all its
changes in one stale-checked write (deck_editor.apply). Only a live line
(not %-commented) counts, and a setting the deck does not have yet is added
just before \\begin{document}, after the preamble \\input{} that defines the
(inert) macros -- the same rule deck_editor.set_deck_tags() follows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import deck_editor
from .alt_blocks import braced_argument
from .deck_scan import (
    DOCUMENT_BEGIN_LINE_RE,
    OUTPUT_FOLDER_RE,
    DECKAPPENDIXTOC_RE,
    OPEN_PDF_RE,
    parse_course_url,
    parse_open_pdf,
)
from .tex_source import is_commented

# \input{Slidemaster_preamble_<template>} -- which template the deck uses.
TEMPLATE_INPUT_RE = re.compile(r"\\input\{Slidemaster_preamble_([^}\s]+)\}")
# \decklanguage[en] -- a literal code; "\decklanguage[\decklanguageoverride]"
# (the boilerplate's other branch) is left alone.
LANGUAGE_RE = re.compile(r"\\decklanguage\s*\[([^\]]*)\]")
# \newcommand{\FooterText}{...}: the match ends just before the {...}.
FOOTER_RE = re.compile(r"\\(?:re)?newcommand\s*\{\\FooterText\}\s*(?=\{)")

# The keys \deckoutputfolder takes: None is the bare form that covers every
# output, the rest are one version, the presenter PDF or the transcript.
OUTPUT_KEYS: tuple[str | None, ...] = (
    None, "instructor", "presenter", "during-course", "after-course", "transcript")


@dataclass
class DeckSettings:
    template: str = ""
    language: str = "en"
    footer_text: str = ""
    course_url: str = ""
    output_folders: dict[str | None, str] = field(default_factory=dict)
    appendix_toc: bool = False
    # which PDF the deck table's "Open pdf" opens by default (deck_scan.OPEN_PDF_RE)
    open_pdf: str = "instructor"


def set_open_pdf(text: str, choice: str) -> str:
    """`text` with its "%% SlideMage open PDF: ..." line set to `choice`;
    none for the default (instructor). Placed just before \\begin{document},
    like the course link."""
    end = _preamble_end(text)
    for match in reversed(list(OPEN_PDF_RE.finditer(text, 0, end))):
        line_start, line_end = deck_editor.line_span(text, match.start(), match.end())
        text = text[:line_start] + text[line_end:]
    if choice in ("", "instructor"):
        return text
    end = _preamble_end(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    return text[:end] + f"%% SlideMage open PDF: {choice}{newline}" + text[end:]


def _preamble_end(text: str) -> int:
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    return begin.start() if begin else len(text)


def _live(text: str, pattern: re.Pattern[str]) -> list[re.Match[str]]:
    """Matches of `pattern` in the preamble that are not %-commented."""
    end = _preamble_end(text)
    return [m for m in pattern.finditer(text, 0, end) if not is_commented(text, m.start())]


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    """Start of the line holding `pos` and the start of the next line."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, len(text) if end == -1 else end + 1


def _insert_line(text: str, line: str, *, after: re.Match[str] | None = None) -> str:
    """`line` as a new line after the line of `after`, else just before
    \\begin{document} (at the end of the file for a fragment)."""
    newline = deck_editor.eol(text)
    if after is not None:
        _, at = _line_bounds(text, after.start())
        if at == len(text) and not text.endswith("\n"):
            return text + newline + line + newline
        return text[:at] + line + newline + text[at:]
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    at = begin.start() if begin else len(text)
    return text[:at] + line + newline + text[at:]


def _remove(text: str, match: re.Match[str]) -> str:
    """The directive of `match` taken out: its whole line when nothing else
    but whitespace stands before it, else just the directive."""
    start, end = _line_bounds(text, match.start())
    if not text[start:match.start()].strip():
        return text[:start] + text[end:]
    return text[:match.start()] + text[match.end():]


def _clean_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    if any(ch in path for ch in "{}%#"):
        raise ValueError("A folder or file path may not contain { } % or #.")
    return path


def from_form(
    original: DeckSettings, *, template: str, language: str, footer_text: str, course_url: str,
    output_folders: dict[str | None, str], appendix_toc: bool, open_pdf: str,
) -> DeckSettings:
    """The settings a form of the sheet holds, checked: a course link must be a web address
    (ValueError otherwise), an output path may not hold LaTeX specials. A path left as it was in
    `original` stays byte for byte, whatever its slashes; an empty one is no entry."""
    url = course_url.strip()
    folders = {}
    for key, typed in output_folders.items():
        typed = typed.strip()
        path = typed if typed == original.output_folders.get(key, "") else _clean_path(typed)
        if path:
            folders[key] = path
    return DeckSettings(
        template=template, language=language, footer_text=footer_text,
        course_url=deck_editor.normalize_course_url(url) if url else "",
        output_folders=folders, appendix_toc=appendix_toc, open_pdf=open_pdf)


def template_choices(root: Path) -> list[tuple[str, str]]:
    """[(key, label)] of every template the project's decks can \\input: the
    known ones first, then any other Slidemaster_preamble_<name>.tex in the
    project folder or the framework."""
    from . import slide_snapshot

    keys = list(slide_snapshot.available_templates(root))
    prefix = "Slidemaster_preamble_"
    for folder in (root, *slide_snapshot.framework_dirs(root)):
        for file in sorted(folder.glob(f"{prefix}*.tex")):
            key = file.stem[len(prefix):]
            if key != "base" and key not in keys:
                keys.append(key)
    return [(key, slide_snapshot.TEMPLATE_LABELS.get(key, key)) for key in keys]


# ---- reading -------------------------------------------------------------

def read_settings(text: str) -> DeckSettings:
    settings = DeckSettings()
    template = _live(text, TEMPLATE_INPUT_RE)
    if template:
        settings.template = template[0].group(1)
    for match in _live(text, LANGUAGE_RE):
        code = match.group(1).strip()
        if code and not code.startswith("\\"):
            settings.language = code
            break
    footer = _live(text, FOOTER_RE)
    if footer:
        settings.footer_text = braced_argument(text, footer[0].end())[0]
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    preamble = text[:begin.start()] if begin else text
    settings.course_url = parse_course_url(text) or ""
    settings.open_pdf = parse_open_pdf(text) or "instructor"
    for match in _live(text, OUTPUT_FOLDER_RE):
        key = (match.group(1) or "").strip() or None
        settings.output_folders[key] = match.group(2).strip()
    settings.appendix_toc = any(
        not is_commented(preamble, m.start()) for m in DECKAPPENDIXTOC_RE.finditer(preamble))
    return settings


# ---- writing -------------------------------------------------------------

def set_template(text: str, template: str) -> str:
    matches = _live(text, TEMPLATE_INPUT_RE)
    if not matches:
        raise ValueError("This deck has no \\input{Slidemaster_preamble_...} line to change.")
    name = template.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(f"'{template}' is not a template name.")
    group = matches[0].span(1)
    return text[:group[0]] + name + text[group[1]:]


def set_language(text: str, code: str) -> str:
    code = code.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", code):
        raise ValueError(f"'{code}' is not a language code such as en or de.")
    literal = [m for m in _live(text, LANGUAGE_RE)
               if m.group(1).strip() and not m.group(1).strip().startswith("\\")]
    if not literal:
        return _insert_line(text, f"\\decklanguage[{code}]")
    for match in reversed(literal):
        span = match.span(1)
        text = text[:span[0]] + code + text[span[1]:]
    return text


def set_footer_text(text: str, value: str) -> str:
    footer = _live(text, FOOTER_RE)
    if footer:
        start = footer[0].end()
        after = braced_argument(text, start)[1]
        if after == start:
            raise ValueError("The \\FooterText line in this deck has unbalanced braces.")
        return text[:start] + "{" + value + "}" + text[after:]
    if not value:
        return text
    return _insert_line(text, "\\newcommand{\\FooterText}{" + value + "}")


def set_output_folder(text: str, key: str | None, path: str) -> str:
    """Set (or, for an empty `path`, remove) the \\deckoutputfolder of `key`."""
    path = _clean_path(path)
    same = [m for m in _live(text, OUTPUT_FOLDER_RE)
            if ((m.group(1) or "").strip() or None) == key]
    if not path:
        for match in reversed(same):
            text = _remove(text, match)
        return text
    if same:
        span = same[-1].span(2)  # the last declaration is the one that counts
        return text[:span[0]] + path + text[span[1]:]
    line = "\\deckoutputfolder" + (f"[{key}]" if key else "") + "{" + path + "}"
    others = _live(text, OUTPUT_FOLDER_RE) or _live(text, TEMPLATE_INPUT_RE)
    return _insert_line(text, line, after=others[-1] if others else None)


def set_appendix_toc(text: str, on: bool) -> str:
    live = [m for m in _live(text, DECKAPPENDIXTOC_RE)]
    if on:
        return text if live else _insert_line(text, "\\deckappendixtoc")
    for match in reversed(live):
        text = _remove(text, match)
    return text


def apply_settings(text: str, old: DeckSettings, new: DeckSettings, deck_name: str = "the deck") -> str:
    """`text` with every setting that differs between `old` and `new` written."""
    if new.template != old.template:
        text = set_template(text, new.template)
    if new.language != old.language:
        text = set_language(text, new.language)
    if new.footer_text != old.footer_text:
        text = set_footer_text(text, new.footer_text)
    if new.course_url != old.course_url:
        text = deck_editor.course_url_text(text, new.course_url, deck_name)
    for key in OUTPUT_KEYS:
        before, after = old.output_folders.get(key, ""), new.output_folders.get(key, "")
        if after != before:
            text = set_output_folder(text, key, after)
    if new.appendix_toc != old.appendix_toc:
        text = set_appendix_toc(text, new.appendix_toc)
    if new.open_pdf != old.open_pdf:
        text = set_open_pdf(text, new.open_pdf)
    return text


def save_settings(deck_path: Path, expected_text: str, old: DeckSettings, new: DeckSettings) -> str:
    """Write the changes in one stale-checked write; returns the new text."""
    return deck_editor.apply(
        deck_path, expected_text,
        lambda text: apply_settings(text, old, new, deck_path.name))
