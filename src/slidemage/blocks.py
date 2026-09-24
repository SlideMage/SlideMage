"""Slide blocks: named, ordered groups of \\slide{}-family calls, curated
once as blocks/<name>.tex and copied ("stamped") into any deck.

A stamped copy is wrapped in a marker pair so it can be found again -- to
show it as a group in the deck editor, and to push local edits back to the
master block ("Update block from here"):

    %% Block: sampling-methods
    %%
    \\slide{...}
    %% End block: sampling-methods
    %%

Inserting copies rather than \\input{}s: each deck's copy stays
independently editable (drop one slide for a shorter course), and changing
a master never touches decks that already copied it. The marker pair
mirrors the two-line "%% <Label>: <value>" / "%%" convention slide files
already use for their own provenance headers (slide_ids.py). Block files
are never compiled, so LaTeX never sees them; in a deck the markers are
plain comments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .archive import _read, _write
from .deck_scan import ARCHIVE_DIR, DECKS_DIR, PROJECT_ROOT, Deck

BLOCKS_DIR = PROJECT_ROOT / "blocks"

# Restricted to what's safe both as a filename on every OS and inside a
# marker line: a name can never contain a character that would let the
# marker regexes below mis-pair, or a "\" that could look like a macro.
_NAME = r"[A-Za-z0-9][A-Za-z0-9_-]*"
NAME_RE = re.compile(rf"^{_NAME}$")
START_RE = re.compile(
    rf"(?m)^[ \t]*%% Block: (?P<name>{_NAME})[ \t]*\r?\n[ \t]*%%[ \t]*\r?\n"
)
END_RE = re.compile(
    rf"(?m)^[ \t]*%% End block: (?P<name>{_NAME})[ \t]*\r?\n[ \t]*%%[ \t]*(?:\r?\n|\Z)"
)


@dataclass
class Block:
    name: str
    path: Path
    text: str

    def as_deck(self) -> Deck:
        """A synthetic Deck, so the deck editor and deck_editor.py's own
        mutation helpers (keyed by path/text, none of them requiring
        \\documentclass) edit a block exactly like a deck. preamble_end=0
        rather than None: a block's preamble is genuinely empty, and None
        makes Deck.preamble_text raise -- the editor reads it to pick
        which template's thumbnails to show."""
        return Deck(
            name=self.name, path=self.path, archived=False, text=self.text,
            supports_version=False, uses_biblatex=False, preamble_end=0,
            chapters=[], output_folders={}, tags=[],
        )

    @property
    def call_count(self) -> int:
        from . import deck_editor

        return len(deck_editor.parse_slide_calls(self.as_deck()))


@dataclass
class BlockSpan:
    """One stamped copy inside a deck's text. start/end cover both marker
    pairs; content_start/content_end cover just the calls between them.
    All four are line starts (end may instead be len(text), for a deck
    whose last line has no terminator)."""

    name: str
    start: int
    content_start: int
    content_end: int
    end: int


def block_path(name: str) -> Path:
    return BLOCKS_DIR / f"{name}.tex"


def is_block_path(path: Path) -> bool:
    return path.suffix == ".tex" and path.parent.resolve() == BLOCKS_DIR.resolve()


def read_block(path: Path) -> Block:
    return Block(name=path.stem, path=path, text=_read(path))


def scan_blocks() -> list[Block]:
    if not BLOCKS_DIR.is_dir():
        return []
    return [read_block(p) for p in sorted(BLOCKS_DIR.glob("*.tex")) if NAME_RE.match(p.stem)]


def name_problem(name: str) -> str | None:
    """Why `name` can't be used for a new block, or None if it can."""
    if not NAME_RE.match(name):
        return ("Use only letters, digits, hyphens and underscores, starting "
                "with a letter or digit (e.g. sampling-methods).")
    if block_path(name).exists():
        return f"A block named {name!r} already exists."
    return None


def create_block(name: str) -> Path:
    problem = name_problem(name)
    if problem is not None:
        raise ValueError(problem)
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    path = block_path(name)
    _write(path, "")
    return path


def _deck_files() -> list[Path]:
    return [
        p for directory in (DECKS_DIR, ARCHIVE_DIR) if directory.is_dir()
        for p in directory.glob("*.tex") if not p.name.startswith("_")
    ]


def rename_block(old: str, new: str) -> int:
    """Renames blocks/<old>.tex and rewrites the markers of every copy
    already stamped into a deck, so each copy's "Update block from here"
    still points at the renamed master. Returns how many deck files
    changed."""
    problem = name_problem(new)
    if problem is not None:
        raise ValueError(problem)
    block_path(old).rename(block_path(new))
    marker = re.compile(rf"(?m)^([ \t]*%% (?:Block|End block): ){re.escape(old)}([ \t]*\r?)$")
    changed = 0
    for deck_path in _deck_files():
        text = _read(deck_path)
        new_text = marker.sub(rf"\g<1>{new}\g<2>", text)
        if new_text != text:
            _write(deck_path, new_text)
            changed += 1
    return changed


def delete_block(name: str) -> None:
    """Deletes the master only -- copies already stamped into decks are
    independent by design and stay as they are."""
    block_path(name).unlink()


def _lines(text: str) -> list[str]:
    """A block's (or a stamped span's) call lines, indentation stripped and
    leading/trailing blank lines dropped -- the one canonical form both
    stamping and pushing back go through, so a round trip is stable."""
    lines = [line.strip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def stamp_text(block: Block, indent: str, eol: str) -> str:
    """The marker-wrapped copy of `block` to splice into a deck, every line
    indented like the deck's own neighbouring calls and terminated with
    the deck's own line ending."""
    body = [f"{indent}{line}" if line else "" for line in _lines(block.text)]
    lines = [
        f"{indent}%% Block: {block.name}", f"{indent}%%",
        *body,
        f"{indent}%% End block: {block.name}", f"{indent}%%",
    ]
    return eol.join(lines) + eol


def find_spans(text: str) -> list[BlockSpan]:
    """Every stamped copy in a deck's text, in order. Pairs each start
    marker with the next end marker of the same name; an unmatched start
    marker is ignored, and markers nested inside an already-paired span
    are skipped (the app itself never produces nested copies -- see
    insert_positions())."""
    spans: list[BlockSpan] = []
    pos = 0
    while (start := START_RE.search(text, pos)) is not None:
        end = END_RE.search(text, start.end())
        while end is not None and end.group("name") != start.group("name"):
            end = END_RE.search(text, end.end())
        if end is None:
            pos = start.end()
            continue
        spans.append(BlockSpan(
            name=start.group("name"), start=start.start(), content_start=start.end(),
            content_end=end.start(), end=end.end(),
        ))
        pos = end.end()
    return spans


def span_lines(text: str, span: BlockSpan) -> list[str]:
    return _lines(text[span.content_start:span.content_end])


def write_block(name: str, lines: list[str]) -> Path:
    """Overwrites (or recreates) blocks/<name>.tex with `lines` -- CRLF,
    like every other .tex file in this project (.gitattributes)."""
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
    path = block_path(name)
    _write(path, "".join(f"{line}\r\n" for line in lines))
    return path


@dataclass
class InsertPosition:
    label: str
    insert_at: int
    indent: str


def insert_positions(deck: Deck) -> list[InsertPosition]:
    """Where a block can be stamped into `deck`: before its first call,
    after each call, or at the end of a deck with no calls yet. Positions
    inside an existing copy are replaced by one "after block <name>"
    entry, so a new copy is never nested inside another one."""
    from . import deck_editor

    calls = deck_editor.parse_slide_calls(deck)
    if not calls:
        return [InsertPosition("At the end of the deck", deck_editor.end_insert_point(deck.text), "")]

    spans = find_spans(deck.text)

    def enclosing(offset: int) -> BlockSpan | None:
        return next((s for s in spans if s.start <= offset < s.end), None)

    def marker_indent(span: BlockSpan) -> str:
        return re.match(r"[ \t]*", deck.text[span.start:]).group()

    first = calls[0]
    first_span = enclosing(first.call_start)
    positions = [InsertPosition(
        "At the beginning",
        first_span.start if first_span else first.line_start,
        marker_indent(first_span) if first_span else first.indent,
    )]
    listed_spans: set[int] = set()
    for number, call in enumerate(calls, start=1):
        span = enclosing(call.call_start)
        if span is None:
            positions.append(InsertPosition(f"After {number}. {call.id_slug}", call.line_end, call.indent))
        elif span.start not in listed_spans:
            listed_spans.add(span.start)
            positions.append(InsertPosition(f"After block {span.name}", span.end, marker_indent(span)))
    return positions
