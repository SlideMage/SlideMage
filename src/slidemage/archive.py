"""Move a deck's .tex file into decks/archive/, patching its own path
fallbacks so it keeps compiling from one directory deeper than decks/.

decks/archive/<name>.tex sits two levels below the project root instead of
one, so the deck's own \\input@path/\\graphicspath fallbacks (hard-coded for
exactly one level -- see README.md's directory-layout section) need an
extra "../". Nothing else in the file changes; prose comments are left
untouched -- only these specific functional lines.

For a deck using biblatex, the original two-branch
\\IfFileExists{Slidemaster.bib}{...}{\\addbibresource{../Slidemaster.bib}}
(supporting compile-from-root vs. compile-from-decks/) is replaced with a
single, unconditional \\addbibresource{../../Slidemaster.bib} rather than
extended into a three-branch cascade (tried first, and confirmed broken by
inspecting the actual compile log): the extra \\IfFileExists branch didn't
resolve the way its own logic implies -- biber recorded "../Slidemaster.bib"
(one level short) as the winning branch even though decks/Slidemaster.bib
doesn't exist, and latexmk then silently vetoed running biber at all since
that path doesn't exist, leaving every citation unresolved with no fatal
error. This project always compiles archived decks through latexmk with
$do_cd (cwd is always decks/archive/ -- there's no separate "compiled from
a different depth" case for an archived file, unlike decks/ itself, which
genuinely needs to support both project-root and decks/ invocation), so the
correct relative path is knowable up front and doesn't need runtime probing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .deck_scan import ARCHIVE_DIR, PROJECT_ROOT, Deck

INPUT_PATH_RE = re.compile(r"\\def\\input@path\{\{\.\./\}\}")

# the slidemage GUI script runs with no console of its own, so without
# this, Windows pops up a new console window for each `git` call below --
# same fix, same reason, as compiler.py's own subprocess.Popen call.
_NO_CONSOLE_KWARGS: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
GRAPHICSPATH_RE = re.compile(r"\\graphicspath\{\{\.\./\}\}")
BIB_IFFILEEXISTS_RE = re.compile(
    r"\\IfFileExists\{Slidemaster\.bib\}\{\\addbibresource\{Slidemaster\.bib\}\}"
    r"\{\\addbibresource\{\.\./Slidemaster\.bib\}\}"
)
INPUT_CALL_RE = re.compile(r"\\input\{([^}]+)\}")


def _sibling_dependencies(deck: Deck) -> list[str]:
    """Bare \\input{X} calls (no path separator, e.g. \\input{test-slides})
    whose X.tex lives alongside the deck in decks/ itself -- unlike
    \\input{Slidemaster_preamble_uni-*} (a project-root resource, handled by
    the path fallbacks this module patches) or \\input{slides/...} (already
    has its own path), a bare same-directory sibling has no fallback at all:
    it resolves relative to cwd only. Archiving moves *only* the requested
    deck's own .tex (per how this feature was scoped), so a deck depending
    on such a sibling would silently break once one level deeper than it."""
    siblings = []
    for name in INPUT_CALL_RE.findall(deck.text):
        if "/" in name or "\\" in name:
            continue
        if name.startswith("Slidemaster_preamble_"):
            continue
        if (deck.path.parent / f"{name}.tex").exists():
            siblings.append(name)
    return siblings


def _is_git_repo() -> bool:
    return (PROJECT_ROOT / ".git").exists()


def _is_git_tracked(path: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(PROJECT_ROOT))],
        cwd=PROJECT_ROOT,
        capture_output=True,
        **_NO_CONSOLE_KWARGS,
    )
    return result.returncode == 0


def _read(path: Path) -> str:
    # newline='' passes CRLF through untouched, matching this project's own
    # convention (see add_deck_headers.py's own header comment) -- so the
    # regex substitutions below don't need to know or care which line
    # ending the file actually uses.
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def archive_deck(deck: Deck) -> Path:
    """Move decks/<name>.tex to decks/archive/<name>.tex (via `git mv` in a
    git working tree, else a plain move), then patch its
    \\input@path/\\graphicspath/Slidemaster.bib fallbacks for the extra
    directory depth. Returns the new path."""
    if deck.archived:
        raise ValueError(f"{deck.name} is already archived")

    siblings = _sibling_dependencies(deck)
    if siblings:
        raise RuntimeError(
            f"{deck.name}: \\input{{}}s sibling file(s) in decks/ itself "
            f"({', '.join(siblings)}) that archiving would leave behind -- "
            "only this deck's own .tex would move, breaking that \\input{}. "
            "Not supported for decks structured this way; move/copy the "
            "sibling(s) into decks/archive/ by hand first if needed."
        )

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / deck.path.name
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")

    # `git mv` refuses outright ("fatal: not under version control") on a
    # file that's never been committed -- a brand-new deck, or any file
    # still untracked -- so that case falls back to a plain move, same as
    # a non-git checkout; there's no history to preserve for it anyway.
    if _is_git_repo() and _is_git_tracked(deck.path):
        subprocess.run(
            [
                "git", "mv",
                str(deck.path.relative_to(PROJECT_ROOT)),
                str(dest.relative_to(PROJECT_ROOT)),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            **_NO_CONSOLE_KWARGS,
        )
    else:
        shutil.move(str(deck.path), str(dest))

    text = _read(dest)

    text, n_input_path = INPUT_PATH_RE.subn(r"\\def\\input@path{{../../}}", text)
    text, n_graphicspath = GRAPHICSPATH_RE.subn(r"\\graphicspath{{../../}}", text)
    if n_input_path == 0 or n_graphicspath == 0:
        raise RuntimeError(
            f"{deck.name}: expected \\input@path{{{{../}}}}/\\graphicspath{{{{../}}}} "
            "not found -- archived file may not resolve the project root correctly; "
            "fix by hand."
        )

    if deck.uses_biblatex:
        text, n_bib = BIB_IFFILEEXISTS_RE.subn(
            r"\\addbibresource{../../Slidemaster.bib}",
            text,
        )
        if n_bib == 0:
            raise RuntimeError(
                f"{deck.name}: uses biblatex but the expected "
                "\\IfFileExists{Slidemaster.bib}{...}{...} pattern wasn't found -- "
                "archived file's bibliography path may be broken; fix by hand."
            )

    _write(dest, text)
    return dest
