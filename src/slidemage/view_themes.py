# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Themes per view: one deck, a theme (and mode) for each of its views.

A deck says it with one comment line in its preamble, for example

    % SlideMage view themes: instructor=uni-graz:dark, after-course=uni-graz

Each entry is `<view>=<template key>[:<mode>]`. The deck's own \input{SlideMage_template_...} line (and its dark
switch) stays the default for a view without an entry and for a compile outside the app, so the deck stays valid TeX.
Only the app uses the line: `preamble_for_view` returns the preamble as that view's compile or render sees it, and every
place that renders or compiles for a view calls it, so the template, the render key and the equivalence of renders
follow without any further bookkeeping (a render's key holds the effective preamble and template).

The one mode that exists today is `dark` (the deck's `\newcommand{\SMDarkMode}{}` switch); an entry fully describes its
view, so `theme` without a mode means the theme's base colours even when the deck's default is dark. Other mode ids are
kept in the line and have no effect until the themes declare modes (docs/plans/theme-editor.md, section 3.8).
"""
from __future__ import annotations

import re

from .deck_editor import VIEWS  # first: deck_editor must load before deck_settings (import cycle)
from . import deck_settings, slide_templates
from .deck_scan import DOCUMENT_BEGIN_LINE_RE

LINE_RE = re.compile(r"^[ \t]*%+[ \t]*SlideMage view themes:[ \t]*(.*?)[ \t]*$", re.MULTILINE | re.IGNORECASE)
_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
_MODE_RE = re.compile(r"[A-Za-z0-9_]+")

DARK = "dark"


def _preamble(text: str) -> tuple[int, int]:
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    return 0, begin.start() if begin else len(text)


def parse(text: str) -> dict[str, tuple[str, str]]:
    """{view: (template key, mode)} from the deck's settings line ("" for no mode). Unknown views and malformed
    entries are ignored; the last line wins."""
    start, end = _preamble(text)
    found = list(LINE_RE.finditer(text, start, end))
    if not found:
        return {}
    entries: dict[str, tuple[str, str]] = {}
    for item in found[-1].group(1).split(","):
        view, _, value = item.strip().partition("=")
        view, value = view.strip(), value.strip()
        key, _, mode = value.partition(":")
        key, mode = key.strip(), mode.strip()
        if view in VIEWS and _KEY_RE.fullmatch(key) and (not mode or _MODE_RE.fullmatch(mode)):
            entries[view] = (key, mode)
    return entries


def format_line(entries: dict[str, tuple[str, str]]) -> str:
    return "% SlideMage view themes: " + ", ".join(
        f"{view}={entries[view][0]}" + (f":{entries[view][1]}" if entries[view][1] else "")
        for view in VIEWS if view in entries)


def set_entries(text: str, entries: dict[str, tuple[str, str]]) -> str:
    """`text` with its settings line replaced by one for `entries` (removed for none). A new line goes just before
    \begin{document}."""
    start, end = _preamble(text)
    for match in reversed(list(LINE_RE.finditer(text, start, end))):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        text = text[:line_start] + text[len(text) if line_end == -1 else line_end + 1:]
    wanted = {v: e for v, e in entries.items() if v in VIEWS}
    if not wanted:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    _, end = _preamble(text)
    return text[:end] + format_line(wanted) + newline + text[end:]


def preamble_for_view(preamble_text: str | None, view: str | None) -> str | None:
    """The preamble as `view` sees it: the template key and the dark switch of that view's entry, else unchanged."""
    if not preamble_text or not view:
        return preamble_text
    entry = parse(preamble_text).get(view)
    if entry is None or not deck_settings.TEMPLATE_INPUT_RE.search(preamble_text):
        return preamble_text
    key, mode = entry
    text = deck_settings.set_template(preamble_text, key)
    try:
        return deck_settings.set_dark_mode(text, mode == DARK)
    except ValueError:
        return text


def template_for(preamble_text: str, view: str | None = None) -> str:
    """The template key the deck uses in `view` (the deck's own for a view without an entry)."""
    return slide_templates.detect_template(preamble_for_view(preamble_text, view) or "")


def templates_used(preamble_text: str) -> set[str]:
    """Every template key any view of the deck uses."""
    return {template_for(preamble_text, view) for view in VIEWS} | {slide_templates.detect_template(preamble_text)}
