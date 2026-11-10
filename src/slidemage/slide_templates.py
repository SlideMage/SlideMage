# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Institution templates: which one a deck selects, where their preamble files are, and which one single-slide
renders use."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import project, themes


# Every institution template is a one-line \input{} swap on top of an
# otherwise-shared preamble, so detecting which one a deck uses is one regex
# against its own preamble text, not a whole-file diff. A template is any
# SlideMage_template_<key>.tex the project (or the framework next to it)
# holds; the app knows none by name except its own, "slidemage", the generic
# template shipped in latex/. It is also the default when detection finds
# nothing (a deck with a preamble this regex doesn't recognize at all).
TEMPLATE_PREFIX = "SlideMage_template_"
TEMPLATE_RE = re.compile(r"\\input\{SlideMage_template_([A-Za-z0-9_-]+)\}")
DEFAULT_TEMPLATE = "slidemage"
_LABEL_RE = re.compile(r"^%+\s*SlideMage template name:\s*(.+?)\s*$", re.MULTILINE)


def template_label(key: str, root: Path | None = None) -> str:
    """How the dialogs name a template: the `% SlideMage template name: ...` line in the first lines of its preamble
    file when it has one, else its key read as words ("my-template" -> "My Template")."""
    if root is not None:
        try:
            head = "\n".join(preamble_file(key, root).read_text(encoding="utf-8", errors="replace").splitlines()[:30])
        except OSError:
            head = ""
        found = _LABEL_RE.search(head)
        if found:
            return found.group(1)
    return "SlideMage" if key == DEFAULT_TEMPLATE else " ".join(part.capitalize() for part in key.split("-"))


def detect_template(preamble_text: str) -> str:
    """The template key a deck's own preamble selects, defaulting to DEFAULT_TEMPLATE when the pattern isn't found."""
    match = TEMPLATE_RE.search(preamble_text)
    return match.group(1) if match else DEFAULT_TEMPLATE


# The template a slide is rendered in when no deck is involved -- the slide
# editor's Render to PDF and Preview, tikz illustration renders (2026-10-03,
# direct instruction: chosen in Settings -> General, out of the box the
# generic SlideMage template). Only a template whose preamble file a deck of
# this project can find is offered; otherwise the choice falls back to the
# SlideMage template, then the default one, then whichever template there is.
RENDER_TEMPLATE_SETTING_KEY = "default_template"
OUT_OF_THE_BOX_RENDER_TEMPLATE = "slidemage"


def framework_dirs(root: Path) -> list[Path]:
    """The LaTeX framework folders a project's decks search (its .latexmkrc
    puts one on TEXINPUTS): $SLIDEMAGE_LATEX, else ../latex (a project
    next to the framework, like example/) or ../SlideMage/latex (a project
    next to a SlideMage checkout). Only folders holding
    SlideMage_base.tex count. With none of them, the framework SlideMage
    bundles (v0.14.19), which compiler.build_env then puts on
    $SLIDEMAGE_LATEX for the compiles."""
    found = project.sibling_framework_dirs(root)
    if found:
        return found
    fallback = project.fallback_framework_dir(root)
    return [fallback] if fallback is not None else []


def template_dirs(root: Path) -> list[Path]:
    """The folders a deck's \\input{SlideMage_template_<key>} is found in, in TeX's order (the project's .latexmkrc
    and compiler.build_env's TEXINPUTS): the project root, the framework, then the installed theme packages
    (themes.py; not for a deck snapshot, whose compiles search only its own copies). The first one holding a key's
    file wins."""
    installed = [] if project.is_snapshot(root) else themes.installed_dirs()
    return [root, *framework_dirs(root), *installed]


def preamble_file(template: str, root: Path) -> Path:
    """The template's preamble file, SlideMage_template_<key>.tex: the
    project's own (institution layers live in the project root), else the
    framework's (the SlideMage template, since v5.9.0), else an installed
    theme's. The project-root path when none exists."""
    name = f"SlideMage_template_{template}.tex"
    for folder in template_dirs(root):
        if (folder / name).is_file():
            return folder / name
    return root / name


def available_templates(root: Path) -> list[str]:
    """The keys of the templates whose preamble file a deck of the project can find (project root, framework or an
    installed theme): the app's own first, then the others alphabetically."""
    keys = {file.stem[len(TEMPLATE_PREFIX):] for folder in template_dirs(root)
            for file in folder.glob(f"{TEMPLATE_PREFIX}*.tex")}
    return sorted(keys, key=lambda key: (key != DEFAULT_TEMPLATE, key))


@dataclass(frozen=True)
class PersonalTheme:
    """A template file in the project folder: a personal theme (what the deck settings offer next to the framework's
    and the installed ones). `replaces` is "" or what a copy of the same key elsewhere is, which this one wins over."""

    key: str
    name: str
    path: Path
    replaces: str = ""      # "" | "the shipped template" | "an installed theme"


def personal_themes(root: Path) -> list[PersonalTheme]:
    """The project's own themes, alphabetically by key: every SlideMage_template_<key>.tex in the project folder (the
    same files template_choices() lists from there; TeX finds the project root first, so each wins over a framework
    or installed template of its key)."""
    found = []
    for file in sorted(root.glob(f"{TEMPLATE_PREFIX}*.tex")):
        key = file.stem[len(TEMPLATE_PREFIX):]
        elsewhere = [folder for folder in template_dirs(root)[1:] if (folder / file.name).is_file()]
        if not elsewhere:
            replaces = ""
        elif elsewhere[0] in themes.installed_dirs():
            replaces = "an installed theme"
        else:
            replaces = "the shipped template"
        found.append(PersonalTheme(key, template_label(key, root), file, replaces))
    return found


def render_template(ctx: project.ProjectContext) -> str:
    """The template single-slide renders use (see RENDER_TEMPLATE_SETTING_KEY)."""
    from . import app_settings  # app settings live in the project too

    available = available_templates(ctx.root)
    for key in (app_settings.get(ctx, RENDER_TEMPLATE_SETTING_KEY),
                OUT_OF_THE_BOX_RENDER_TEMPLATE, DEFAULT_TEMPLATE):
        if key in available:
            return key
    return available[0] if available else DEFAULT_TEMPLATE


def set_render_template(ctx: project.ProjectContext, key: str) -> None:
    """Choose the template single-slide renders use (a template key)."""
    from . import app_settings

    if key not in available_templates(ctx.root):
        raise ValueError(f"'{key}' is not a template.")
    app_settings.set(ctx, RENDER_TEMPLATE_SETTING_KEY, key)
