# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project's rules for translations by Claude Code (Claude Code tasks plan, step 2): how the audience is
addressed, `address` ("formal" or "informal") in .slidemage/project.json, and the optional .slidemage/glossary.md
that goes into translation requests: a Markdown table with one column per language (`| EN | DE | FR |`) or the
older "EN = DE" lines. No Qt."""
from __future__ import annotations

from .. import project
from ..project import ProjectContext

ADDRESSES = ("formal", "informal")
GLOSSARY_PATH = ".slidemage/glossary.md"
_KEY, _DE_KEY = "address", "de_address"
_DE_WORDS = {"Sie": "formal", "du": "informal"}      # what _DE_KEY holds; older SlideMage and plugins read it


def address(ctx: ProjectContext) -> str:
    """The project's form of address, for every language: "formal" unless it says "informal". A project that
    has only `de_address` (Sie or du) is read from that."""
    data = project.read_project_json(ctx.root)
    value = data.get(_KEY)
    return value if value in ADDRESSES else _DE_WORDS.get(data.get(_DE_KEY), ADDRESSES[0])


def de_address(ctx: ProjectContext) -> str:
    """The German word for the project's form of address ("Sie" or "du"), for plugin API version 1."""
    return next(word for word, value in _DE_WORDS.items() if value == address(ctx))


def set_address(ctx: ProjectContext, value: str) -> None:
    """Store the form of address, and `de_address` next to it so that an older SlideMage keeps working."""
    data = project.read_project_json(ctx.root)
    data[_KEY] = value
    data[_DE_KEY] = next(word for word, form in _DE_WORDS.items() if form == value)
    project.write_project_json(ctx.root, data)


def glossary(ctx: ProjectContext) -> str:
    """The text of the project's glossary file, "" without one."""
    try:
        return (ctx.root / GLOSSARY_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def glossary_for(text: str, source: str, target: str) -> str:
    """The part of the glossary `text` that a translation from `source` to `target` (language codes, any case)
    needs, as "source term = target term" lines. Table rows with a term for both languages count; so do the
    lines that are not in a table, but only for English and German, which the "EN = DE" form was for."""
    source, target = source.upper(), target.upper()
    old_form = {source, target} == {"EN", "DE"}
    lines: list[str] = []
    columns: tuple[int, int] | None = None          # of source and target in the table being read
    in_table = False
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            in_table, columns = False, None
            if old_form:
                lines.append(line)
            continue
        cells = _cells(line)
        if not in_table:                            # a table starts with its header
            in_table = True
            heads = [cell.upper() for cell in cells]
            columns = (heads.index(source), heads.index(target)) if source in heads and target in heads else None
        elif columns and not set("".join(cells)) <= set("-: "):
            terms = [cells[i] if i < len(cells) else "" for i in columns]
            if all(terms):
                lines.append(f"{terms[0]} = {terms[1]}")
    return "\n".join(lines).strip()
