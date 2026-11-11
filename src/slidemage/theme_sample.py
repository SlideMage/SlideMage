# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""The theme sample deck, rendered with a theme as it is being edited (docs/plans/theme-editor.md, section 3.3, stage
C1c): the theme form shows its pages beside the fields, in the colour mode chosen there.

The deck (assets/theme_sample/theme-sample.tex) is compiled in a work folder of the project's build folder
(.build/theme-sample/<key>/<mode>/), with the buffer's text written there as SlideMage_template_<key>.tex: that folder
comes first on TEXINPUTS, so the edited text wins over the file on disk, and the project root and the framework follow,
so the theme's logo and its \inputs are found as for a deck. Nothing in the project changes."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import compiler, slide_templates

SAMPLE_DIR = Path(__file__).resolve().parent / "assets" / "theme_sample"
DECK = "theme-sample"
# What each page of the sample deck shows (1-based page numbers), for the form's page picker.
PAGES: tuple[tuple[int, str], ...] = (
    (1, "Title frame"), (2, "Title bar, lists and footnotes"), (3, "Blocks"), (4, "Code"), (5, "Highlight frame"),
    (6, "Standout frame"), (7, "Quote frame"))


@dataclass(frozen=True)
class SampleResult:
    pdf: Optional[Path]     # None when the compile failed or was stopped
    log: str                # the TeX log's last lines when it failed, else ""
    mode: str


def work_dir(build_dir: Path, key: str, mode: str) -> Path:
    return build_dir / "theme-sample" / (key or "theme") / (mode or "base")


def deck_text(key: str, mode: str, root: Path) -> str:
    """The sample deck with its colour mode and theme lines filled in."""
    text = (SAMPLE_DIR / f"{DECK}.tex").read_text(encoding="utf-8")
    mode_line = f"\\newcommand{{\\SMModeOverride}}{{{mode}}}" if mode else "% (the theme's base mode)"
    theme_line = (f"\\graphicspath{{{{{root.as_posix()}/}}}}\n"
                  f"\\input{{{slide_templates.TEMPLATE_PREFIX}{key}}}")
    return text.replace("%MODE%", mode_line, 1).replace("%THEME%", theme_line, 1)


def prepare(work: Path, theme_text: str, key: str, mode: str, root: Path) -> Path:
    """Write the theme's text, the deck and its snippet into `work`; returns the deck's path."""
    work.mkdir(parents=True, exist_ok=True)
    (work / f"{slide_templates.TEMPLATE_PREFIX}{key}.tex").write_text(theme_text, encoding="utf-8")
    shutil.copyfile(SAMPLE_DIR / "snippet.tex", work / "snippet.tex")
    deck = work / f"{DECK}.tex"
    deck.write_text(deck_text(key, mode, root), encoding="utf-8")
    return deck


def texinputs(work: Path, root: Path, env: dict) -> str:
    """The work folder first (the edited theme wins), then the project root and the framework, then what was set."""
    folders = [work, root, *slide_templates.framework_dirs(root)]
    rest = env.get("TEXINPUTS", "")
    return os.pathsep.join([str(folder) for folder in folders] + [rest])


def render(ctx, theme_text: str, key: str, mode: str, *, cancel: Optional[compiler.CancelToken] = None,
           log: Callable[[str], None] = lambda _line: None) -> SampleResult:
    """Compile the sample deck with `theme_text` as the theme `key` in colour mode `mode` ("" for the base)."""
    work = work_dir(ctx.build_dir, key, mode)
    deck = prepare(work, theme_text, key, mode, ctx.root)
    env = compiler.build_env(ctx)
    env["TEXINPUTS"] = texinputs(work, ctx.root, env)
    cmd = compiler.latexmk_command(deck, DECK, work, "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                                   cwd=work)
    try:
        build = compiler.run_latexmk(cmd, jobname=DECK, outdir=work, cwd=work, env=env, log=log, cancel=cancel)
    except OSError as exc:
        return SampleResult(None, f"latexmk could not be started: {exc}", mode)
    if build.stopped:
        return SampleResult(None, "", mode)
    if not build.ok:
        tail = "\n".join(line for line in build.log_text.splitlines() if line.startswith("!") or "Error" in line)
        return SampleResult(None, tail[-2000:] or build.log_text[-2000:], mode)
    return SampleResult(build.pdf, "", mode)
