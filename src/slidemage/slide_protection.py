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
    "That edit would change a protected part of the slide: the comment block at the top of the file "
    "or the \\setSlideVersion line. SlideMage manages those; leave "
    "them as they are and change only the rest of the slide.")


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
    Guaranteed: the protected texts are unchanged and in the same order, and a header comment
    that started the file still does (BOM aside). Where a version line sits
    among the ordinary text is not checked."""
    def parts(text: str) -> tuple[list[str], bool]:
        masked = mask_protected_regions(text)
        first = next(iter(masked.placeholders), None)
        return list(masked.placeholders.values()), first is not None and \
            masked.masked_text.lstrip("\ufeff").startswith(first)

    return None if parts(before) == parts(after) else PROTECTED_MESSAGE
