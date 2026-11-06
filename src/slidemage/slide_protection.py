# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Claude Code hook and the chat tools share about protecting a slide: which file is a slide's live or frozen
version, and whether an edit touches the protected parts. Dependency-light so the hook process starts fast."""
from __future__ import annotations

from pathlib import Path

from . import slide_language
from .project import ProjectContext
from .protected_regions import mask_protected_regions

PROTECTED_MESSAGE = (
    "That edit would change a protected part of the slide: the '%%' lines at the top of the file "
    "(such as '%% Included in decks:') or the \\setSlideVersion line. SlideMage manages those; leave "
    "them as they are and change only the rest of the slide. The ordinary '%' notes at the top may be edited.")


def slide_kind(ctx: ProjectContext, path: Path) -> str | None:
    """"current" / "frozen" for a file in slides/ that is a slide's current or frozen version."""
    if path.parent != ctx.slides_dir.resolve():
        return None
    try:
        macro, _id_slug, _version = slide_language.call_for_slide_path(path)
    except ValueError:
        return None
    return "current" if macro == "slide" else "frozen"


def protected_problem(before: str, after: str) -> str | None:
    """The message to give the model when `after` differs from `before` in a protected part.
    Guaranteed: the protected texts are unchanged and in the same order. The `%%` lines are found only inside the
    leading comment block (protected_regions), so moving them out of it, or putting a non-comment line above them,
    loses them and is refused too; the ordinary `%` notes around them may change (v0.14.25). Where a version line
    sits among the ordinary text is not checked."""
    def parts(text: str) -> list[str]:
        return list(mask_protected_regions(text).placeholders.values())

    return None if parts(before) == parts(after) else PROTECTED_MESSAGE
