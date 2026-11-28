# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`slidemage --self-test --compile`: does this computer's TeX installation compile SlideMage decks?

The installers (packaging/install-slidemage.sh, packaging/slidemage.iss) run it as their last step, and
tests/installer/ runs it in each Linux container. It makes a project from the bundled example in a temporary folder
(project.init_project, which also copies the framework beside it) and compiles one small deck per bundled layout
profile and template, each with a citation through biblatex and biber, through the same compiler.run_job the window
uses. No window; prints one line per deck and exits 0 only when every deck compiled.

The first compile on a fresh TeX installation can take minutes (luaotfload builds its font list, MiKTeX installs
packages as it goes), so each deck has a generous time limit (DECK_SECONDS) and the caller says so to the user.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

# (deck name, template, layout profile or None for the template's own, the font the PDF must embed). One deck per
# bundled layout profile (latex/SlideMage_layout_*.tex) and per bundled template (latex/SlideMage_template_*.tex), and
# one with the framework's own copy of Fira (latex/fonts/fira/), which the fira profile uses when the TeX distribution
# has none. A missing font is only a warning in TeX (the text falls back to Latin Modern), hence the font check.
DECKS = (
    ("selftest-fira", "slidemage", None, "FiraSans-Light"),
    ("selftest-fira-bundled", "slidemage", None, "FiraSans-Light"),
    ("selftest-lmsans", "slidemage", "lmsans", "LMSans10-Regular"),
    ("selftest-lmroman", "slidemage", "lmroman", "LMRoman10-Regular"),
    ("selftest-grayscale", "grayscale", None, "LMRoman10-Regular"),
)
BUNDLED_FIRA_DECK = "selftest-fira-bundled"     # defines \SMBundledFiraOverride (SlideMage_layout_fira.tex)
CITATION_KEY = "markowitz1952"      # in example/SlideMage.bib
CITATION_AUTHOR = "Markowitz"       # what the resolved citation and the reference list print
DECK_SECONDS = 900                  # per deck; the first one may install packages and build the font list
EXIT_TEX_MISSING = 2                # no latexmk on PATH: nothing was compiled


def deck_text(template: str, layout: str | None, bundled_fira: bool = False) -> str:
    layout_line = f"\\newcommand{{\\SMLayoutProfile}}{{{layout}}}\n" if layout else ""
    if bundled_fira:
        layout_line += "\\def\\SMBundledFiraOverride{}\n"
    return (
        "\\documentclass[aspectratio=169]{beamer}\n"
        "\\makeatletter\\def\\input@path{{../}}\\makeatother\n"
        "\\graphicspath{{../}}\n"
        f"{layout_line}"
        f"\\input{{SlideMage_template_{template}}}\n"
        "\\SMUseBibliography\n"
        "\\newcommand{\\FooterText}{SlideMage self-test}\n"
        "\\begin{document}\n"
        "\\begin{frame}{SlideMage self-test}\n"
        f"A citation: \\parencite{{{CITATION_KEY}}}. \\texttt{{Monospaced code.}} \\textbf{{Bold}} \\emph{{italic}}.\n"
        "\\end{frame}\n"
        "\\begin{frame}{References}\n"
        "\\printbibliography\n"
        "\\end{frame}\n"
        "\\end{document}\n"
    )


def _compile(ctx, deck, font: str, log) -> tuple[bool, str]:
    """(passed, the first TeX error or the reason) for one deck, through compiler.run_job."""
    from . import compiler

    lines: list[str] = []
    outcome: list[tuple[bool, Path]] = []
    relocated = threading.Event()

    def collect(line: str) -> None:
        lines.append(line)
        log(line)

    def finished(ok: bool, path: Path) -> None:
        outcome.append((ok, path))
        relocated.set()

    job = compiler.CompileJob(deck, None, None)
    if not compiler.run_job(ctx, job, collect, on_relocated=finished):
        return False, compiler.first_tex_error("\n".join(lines)) or (lines[-1] if lines else "latexmk failed")
    if not relocated.wait(DECK_SECONDS):
        return False, "the PDF was not published in time"
    ok, pdf = outcome[0]
    if not ok or not pdf.is_file():
        return False, f"no PDF at {pdf}"
    # A citation biber did not resolve still gives a PDF, with the key in bold instead of the reference.
    import pymupdf

    with pymupdf.open(pdf) as document:
        text = " ".join(page.get_text() for page in document)
        fonts = {entry[3].split("+")[-1] for page in document for entry in page.get_fonts()}
    if CITATION_KEY in text or CITATION_AUTHOR not in text:
        return False, f"the citation was not resolved (biber), see {pdf}"
    if not any(name.lower().startswith(font.lower()) for name in fonts):
        return False, f"the PDF has no {font} font (it has {', '.join(sorted(fonts))}), see {pdf}"
    return True, str(pdf)


def run(verbose: bool = False, keep: bool = False) -> int:
    """Compile every deck in DECKS; print the result; the exit status."""
    from . import deck_scan, project, tex_paths

    tex_paths.extend_path()     # cli.main did this already; again for `python -m slidemage.compile_selftest`

    if shutil.which("latexmk") is None:
        print("SlideMage compile self-test: latexmk was not found (no TeX installation, or not on PATH)")
        return EXIT_TEX_MISSING
    folder = Path(tempfile.mkdtemp(prefix="slidemage-selftest-"))
    root = folder / "SelfTest"
    failures = 0
    # The framework under test is the one this SlideMage brings (init_project copies it beside the project), not one
    # $SLIDEMAGE_LATEX points to (a developer's checkout): the project's .latexmkrc would prefer that one.
    saved_framework = os.environ.pop(project.LATEX_ENV_VAR, None)
    try:
        project.init_project(root, copy_example=True)
        for name, template, layout, _font in DECKS:
            text = deck_text(template, layout, bundled_fira=name == BUNDLED_FIRA_DECK)
            (root / "decks" / f"{name}.tex").write_text(text, encoding="utf-8", newline="\n")
        ctx = project.ProjectContext.at(root)
        decks = {d.name: d for d in deck_scan.scan_dir(root / "decks", False)}
        log = (lambda line: print("   ", line)) if verbose else (lambda line: None)
        for name, _template, _layout, font in DECKS:
            print(f"SlideMage compile self-test: {name} ...", flush=True)
            passed, detail = _compile(ctx, decks[name], font, log)
            print(f"SlideMage compile self-test: {name} {'ok' if passed else 'FAILED: ' + detail}", flush=True)
            failures += not passed
    finally:
        if saved_framework is not None:
            os.environ[project.LATEX_ENV_VAR] = saved_framework
        if keep:
            print(f"SlideMage compile self-test: the project is kept at {root}")
        else:
            shutil.rmtree(folder, ignore_errors=True)
    print("SlideMage compile self-test: " + ("ok" if not failures else f"{failures} of {len(DECKS)} decks failed"))
    return 1 if failures else 0


if __name__ == "__main__":      # python -m slidemage.compile_selftest
    sys.exit(run(verbose="-v" in sys.argv, keep="--keep" in sys.argv))
