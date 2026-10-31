# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve citation keys against SlideMage.bib.

Without this a transcript renders `\\fullcite{loughran1995}` as the bare key
"loughran1995", which tells a student nothing.

A hand-written parser rather than a dependency, because this project declares
exactly one (PySide6) and the actual data is unusually well behaved -- measured
2026-08-14: 89 entries, 89 keys used across the slides, **zero** keys missing
from the file, no `crossref`, no `@string`, and three accent macros in 26 KB.
None of the usual BibTeX horrors apply here. The parser is deliberately strict
about what it understands and falls back to the bare key rather than guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .tex_source import braced_argument



# Same logic as the former one-off sort_bib.py (project root, deleted once
# folded in here) -- SlideMage now runs this itself, on open and close of
# the "Edit .bib" tab (the main window's _on_edit_bib/close_slide_editor_tab), so
# the file never needs a manual sort pass again. Splits on a bare "@" at the
# start of a line rather than trying to fully parse each entry -- the file's
# own entries are already one-per-paragraph, blank-line-separated, so this
# is simpler and just as reliable as re-using load()'s own stricter parser,
# which is built to tolerate malformed fields, not to round-trip formatting.
def sort_entries(path: Path) -> bool:
    """Rewrite the .bib at `path` with its entries sorted
    alphabetically by citation key, preserving the leading header comment
    block verbatim. Returns whether the file actually changed -- a no-op
    write (already sorted) is skipped so the file's mtime/git diff stays
    quiet on every open of an already-tidy file."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    first_entry = re.search(r"^@", text, re.MULTILINE)
    if first_entry is None:
        return False
    header = text[: first_entry.start()]
    body = text[first_entry.start():]

    entries = [e.strip() for e in re.split(r"\n(?=@)", body.strip()) if e.strip()]

    def key_of(entry: str) -> str:
        m = re.match(r"@\w+\{([^,]+),", entry)
        return m.group(1).lower() if m else entry.lower()

    entries.sort(key=key_of)
    new_text = header.rstrip("\n") + "\n\n" + "\n\n".join(entries) + "\n"
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


# Per-entry-type field order for newly written entries (ui/dialogs/citation.py's
# "Add reference" form) -- author/title/year always first, matching every
# existing entry of every type in this file; the rest follows each type's
# own most common existing ordering (see the field-frequency survey this was
# based on: 96 article/23 book/3 online/4 report entries, measured directly).
# Not necessarily identical to every pre-existing entry's own field order
# (a handful vary, e.g. some @book entries put `edition` before `year`,
# some after `publisher`) -- this is the canonical order *new* entries get,
# not a reformatting pass over old ones.
TYPE_FIELDS: dict[str, list[tuple[str, bool]]] = {
    "article": [
        ("author", True), ("title", True), ("year", True),
        ("journaltitle", True), ("volume", False), ("number", False),
        ("pages", False), ("doi", False),
    ],
    "book": [
        ("author", True), ("title", True), ("year", True),
        ("publisher", True), ("edition", False), ("location", False),
        ("isbn", False),
    ],
    "online": [
        ("author", True), ("title", True), ("year", True),
        ("url", True), ("organization", False), ("note", False),
    ],
    "report": [
        ("author", True), ("title", True), ("year", True),
        ("institution", False), ("type", False), ("doi", False),
    ],
}

_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)
_FIELD_RE = re.compile(r"(\w+)\s*=\s*", re.IGNORECASE)

# The handful of TeX accent forms that actually occur in this .bib, plus the
# common ones so a new entry does not silently render as "\"o".
_ACCENTS = {
    ('"', "a"): "ä", ('"', "o"): "ö", ('"', "u"): "ü",
    ('"', "A"): "Ä", ('"', "O"): "Ö", ('"', "U"): "Ü",
    ("'", "a"): "á", ("'", "e"): "é", ("'", "i"): "í",
    ("'", "o"): "ó", ("'", "u"): "ú",
    ("`", "a"): "à", ("`", "e"): "è", ("`", "o"): "ò",
    ("^", "a"): "â", ("^", "e"): "ê", ("^", "o"): "ô",
    ("~", "n"): "ñ", ("c", "c"): "ç",
}
_ACCENT_RE = re.compile(r'\\([\'"`^~c])\s*\{?([A-Za-z])\}?')


@dataclass
class BibEntry:
    key: str
    kind: str
    fields: dict[str, str]

    @property
    def year(self) -> str:
        return self.fields.get("year", "").strip()

    @property
    def title(self) -> str:
        return self.fields.get("title", "").strip()

    @property
    def container(self) -> str:
        """Journal, book or publisher -- whatever names where it appeared."""
        for name in ("journaltitle", "journal", "booktitle", "publisher",
                     "institution", "organization"):
            value = self.fields.get(name, "").strip()
            if value:
                return value
        return ""

    @property
    def surnames(self) -> list[str]:
        raw = self.fields.get("author") or self.fields.get("editor") or ""
        out: list[str] = []
        for person in re.split(r"\s+and\s+", raw):
            person = person.strip().rstrip(",")
            if not person:
                continue
            if "," in person:                      # "Loughran, T."
                out.append(person.split(",")[0].strip())
            else:                                  # "T. Loughran"
                out.append(person.split()[-1].strip())
        return out


def _clean(value: str) -> str:
    value = _ACCENT_RE.sub(
        lambda m: _ACCENTS.get((m.group(1), m.group(2)), m.group(2)), value)
    value = value.replace("\\&", "&").replace("--", "\u2013")
    value = re.sub(r"\\[a-zA-Z]+\s*", "", value)
    value = value.replace("{", "").replace("}", "")
    return " ".join(value.split())


def _read_value(text: str, start: int) -> tuple[str, int]:
    """Read one field value at `start`: {braced}, "quoted", or bare."""
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return "", index

    if text[index] == "{":
        value, after = braced_argument(text, index)
        return (value, after) if after != index else (text[index + 1:], len(text))  # unbalanced: the rest

    if text[index] == '"':
        end = text.find('"', index + 1)
        if end == -1:
            return text[index + 1:], len(text)
        return text[index + 1:end], end + 1

    end = index
    while end < len(text) and text[end] not in ",}\n":
        end += 1
    return text[index:end], end


def load(path: Path) -> dict[str, BibEntry]:
    """Parse a .bib file into {key: BibEntry}. Empty dict if unreadable."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    entries: dict[str, BibEntry] = {}
    for match in _ENTRY_RE.finditer(text):
        kind, key = match.group(1).lower(), match.group(2).strip()
        cursor = match.end()
        fields: dict[str, str] = {}
        depth = 1                                   # inside the entry's brace
        while cursor < len(text):
            char = text[cursor]
            if char == "}" and depth == 1:
                break
            field = _FIELD_RE.match(text, cursor)
            if field:
                value, cursor = _read_value(text, field.end())
                fields[field.group(1).lower()] = _clean(value)
                continue
            cursor += 1
        entries[key] = BibEntry(key=key, kind=kind, fields=fields)
    return entries


def entry_line(key: str, path: Path) -> int | None:
    """The 1-based line of `@type{key,` in the .bib, or None when the file has no such entry."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(rf"^[ \t]*@\w+\s*\{{\s*{re.escape(key)}\s*,", text, re.MULTILINE)
    return text.count("\n", 0, match.start()) + 1 if match else None


KEY_RE = re.compile(r"^[a-z]+[0-9]{4}[a-z]?$")


def _first_surname(author_field: str) -> str:
    """Same splitting rules as BibEntry.surnames, but only the first
    author -- used to seed a new entry's own suggested key, same
    "lowercase first author's surname + year" convention this file's own
    header comment documents."""
    first = re.split(r"\s+and\s+", author_field.strip())[0].strip().rstrip(",")
    if not first:
        return ""
    if "," in first:
        surname = first.split(",")[0].strip()
    else:
        surname = first.split()[-1].strip()
    return re.sub(r"[^A-Za-z]", "", surname).lower()


def suggest_key(author_field: str, year: str, existing: dict[str, BibEntry]) -> str:
    """<first author's surname><year>, lowercased, e.g. "Smith, John and
    Doe, Jane" + "2024" -> "smith2024" -- this file's own established key
    convention (see its own header comment). Appends "a", "b", "c", ... if
    the plain form already exists (case-insensitively), so a second
    citation by the same first author in the same year never silently
    collides."""
    surname = _first_surname(author_field)
    year = year.strip()
    base = f"{surname}{year}" if surname and year else ""
    if not base:
        return ""
    taken = {k.lower() for k in existing}
    if base.lower() not in taken:
        return base
    for letter in "abcdefghijklmnopqrstuvwxyz":
        candidate = f"{base}{letter}"
        if candidate.lower() not in taken:
            return candidate
    return base  # exhausted a-z -- extremely unlikely, caller's own duplicate check still applies


def format_entry(kind: str, key: str, fields: dict[str, str]) -> str:
    """Render one new entry back to .bib text -- field order/column
    alignment matching this file's own existing style. `fields` should
    already be in TYPE_FIELDS' own write order (an insertion-ordered
    dict, as the GUI form builds it); blank-valued fields are skipped
    entirely rather than written as `{}`. A bare "&" is auto-escaped to
    "\\&" (every literal ampersand in the file today is already written
    that way -- e.g. "Journal of Economic Behavior \\& Organization"),
    so the person filling in the form doesn't need to know LaTeX escaping
    to type a journal/publisher name that happens to contain one."""
    pairs = [(name, re.sub(r"(?<!\\)&", r"\\&", value.strip()))
             for name, value in fields.items() if value and value.strip()]
    if not pairs:
        raise ValueError("at least one field besides the key is required")
    width = max(len(name) for name, _ in pairs)
    lines = [f"@{kind}{{{key},"]
    lines.extend(f"\t{name.ljust(width)} = {{{value}}}," for name, value in pairs)
    lines.append("}")
    return "\n".join(lines)


def add_entry(kind: str, key: str, fields: dict[str, str], path: Path) -> str:
    """Insert a new entry into `path` (default SlideMage.bib) and leave
    the file alphabetically sorted by key afterward -- appends the new
    entry, then re-runs sort_entries() rather than computing its own
    insertion point, so "kept sorted" (the file's own header-comment
    invariant) is enforced by the exact same code path regardless of how
    the file might already be out of order. Raises ValueError if `key`
    already exists (case-insensitively -- BibTeX keys are technically
    case-sensitive, but every key in this file is already lowercase by
    convention, so a same-key-different-case entry would be confusing
    dead weight rather than a legitimately distinct citation). Returns
    the newly written entry's own text."""
    existing = load(path)
    if key.lower() in {k.lower() for k in existing}:
        raise ValueError(f"citation key {key!r} already exists in {path.name}")
    entry_text = format_entry(kind, key, fields)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    new_text = text.rstrip("\n") + "\n\n" + entry_text + "\n"
    path.write_text(new_text, encoding="utf-8", newline="\n")
    sort_entries(path)
    return entry_text


def search(entries: dict[str, BibEntry], query: str) -> list[str]:
    """The keys, sorted, of the entries that contain every word of `query`
    (case-insensitive) in their key, author, title, year or container."""
    words = query.lower().split()
    found = []
    for key in sorted(entries):
        entry = entries[key]
        haystack = " ".join((key, entry.fields.get("author", ""), entry.title, entry.year,
                             entry.container)).lower()
        if all(word in haystack for word in words):
            found.append(key)
    return found


def _authors(entry: BibEntry) -> str:
    names = entry.surnames
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    if len(names) == 3:
        return f"{names[0]}, {names[1]} & {names[2]}"
    return f"{names[0]} et al."


def format_citation(key: str, entries: dict[str, BibEntry], style: str) -> str:
    """Render one citation. Unknown keys fall back to the bare key.

    `style` mirrors the biblatex commands used in the slides:
      full   -> \\fullcite  : Author (Year), "Title", Container.
      text   -> \\textcite  : Author (Year)
      paren  -> \\cite etc. : (Author, Year)
    """
    entry = entries.get(key)
    if entry is None:
        return f"[{key}]"

    authors = _authors(entry)
    year = entry.year

    if style == "text":
        return f"{authors} ({year})" if authors and year else (authors or key)
    if style == "paren":
        if authors and year:
            return f"({authors}, {year})"
        return f"({authors or year or key})"

    parts: list[str] = []
    if authors:
        parts.append(f"{authors} ({year})" if year else authors)
    elif year:
        parts.append(f"({year})")
    if entry.title:
        parts.append(f"\u201c{entry.title}\u201d")
    if entry.container:
        parts.append(entry.container)

    # Volume/issue/pages, in the conventional journal form: "130(4), 1547-1621".
    # `number` is biblatex's field for the issue; 61 of the 89 entries carry a
    # volume, 39 an issue and 61 page ranges, so this is worth rendering
    # properly rather than appending whatever happens to be present.
    volume = entry.fields.get("volume", "").strip()
    issue = (entry.fields.get("number") or entry.fields.get("issue") or "").strip()
    pages = entry.fields.get("pages", "").strip()

    locator = ""
    if volume:
        locator = f"{volume}({issue})" if issue else volume
    elif issue:
        locator = f"No. {issue}"
    if pages:
        # An en dash already, courtesy of _clean()'s "--" handling.
        label = "p." if _is_single_page(pages) else "pp."
        locator = f"{locator}, {label} {pages}" if locator else f"{label} {pages}"
    if locator:
        parts.append(locator)

    edition = entry.fields.get("edition", "").strip()
    if edition:
        # Every edition value in this bib already spells out its own wording
        # ("5th global ed.", "International ed."), so appending "edn." would
        # produce "International ed. edn.". Only a bare number needs help.
        parts.append(f"{edition} ed." if edition.isdigit() else edition)

    return ", ".join(parts) if parts else f"[{key}]"


def _is_single_page(pages: str) -> bool:
    return not re.search(r"[\u2013\u2014-]", pages.strip())
