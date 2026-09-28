"""Render a single slide to a standalone, temporary PDF and open it --
available from both the deck slide-list editor (deck_editor_tab.py, using
that deck's own preamble so theme/colors/footer match how the slide
actually looks in context) and the slide-source editor (slide_source_tab.py,
which has no owning deck, so it falls back to a generic standalone
preamble matching decks/test.tex, this project's own demo deck).

Reuses compiler.py's own _build_env()/FATAL_ERROR_RE (the Git-for-Windows
Perl PATH fix and the "trust the log, not the exit code" pass/fail check --
see that module's own docstring for why both are needed) rather than
duplicating them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

from . import open_path
from . import slide_snapshot
from .compiler import BUILD_DIR, FATAL_ERROR_RE, _build_env
from .deck_editor import VERSION_FILE_RE, format_call
from .deck_scan import PROJECT_ROOT

DECKS_DIR = PROJECT_ROOT / "decks"

LogCallback = Callable[[str], None]

# Standalone preamble for previewing a slide with no owning deck context
# (the slide-source editor's own "Render to PDF" button) -- same
# institution/aspect ratio as decks/test.tex, plus a bibliography setup
# (below) that decks/test.tex itself doesn't need.
#
# Bibliography (biblatex + biber) -- same setup and house citation-driver
# customization (book/article/online/report) as decks/t-Uni-FM2-2027s.tex
# and decks/t-Uni-IA2-2026w.tex, which copy this same block verbatim
# between each other already (see either deck's own extensive comments for
# the reasoning behind every piece of it) -- this makes a third call site,
# copied the same way rather than factored out, per those decks' own
# comment on when that'd be worth doing. Added 2026-07-24 (direct
# instruction: "check and fix why references are not properly rendered
# when I render just a single slide from the slide edit tab") -- without
# this, \textcite{}/\fullcite{} are simply undefined here, which
# nonstopmode mode doesn't treat as fatal: it skips the undefined command
# and keeps going, so the citation text just silently goes missing from
# the rendered PDF rather than the render failing outright (confirmed
# directly, before this fix, by test-rendering a citation-using slide this
# way and inspecting both the resulting PDF and the raw compile log).
#
# The bib path is hardcoded as ../Slidemaster.bib, not those two decks' own
# \IfFileExists compile-from-either-location cascade -- this wrapper is
# always written to decks/ and always compiled with that as its cwd (via
# latexmk's own $do_cd), so the one correct relative path is knowable up
# front, the same fix already established for the identical class of
# problem in archive.py (see SlideMage/README.md's "Archiving and
# biblatex don't mix" section for why the cascade itself is actively
# wrong, not just unnecessary, here: it was confirmed to make biber
# silently veto itself).
GENERIC_PREAMBLE = r"""\documentclass[aspectratio=169]{beamer}
\usetheme{gotham}
\makeatletter
\def\input@path{{../}}
\makeatother
\graphicspath{{../}}
\input{Slidemaster_preamble_uni-graz}

\usepackage[style=authoryear, backend=biber, giveninits=true, uniquename=init, maxcitenames=3, mincitenames=1, maxbibnames=3, minbibnames=1]{biblatex}
\addbibresource{../Slidemaster.bib}

\DeclareNameAlias{author}{family-given}
\renewcommand*{\multinamedelim}{\addcomma\space}
\renewcommand*{\finalnamedelim}{\addcomma\space}
\DeclareFieldFormat{title}{#1}
\DeclareFieldFormat[article]{title}{#1}
\DeclareFieldFormat{pages}{#1}

\DeclareBibliographyDriver{book}{%
	\printnames{author}\addcomma\space
	\printfield{year}\addperiod\space
	\textquotedbl\printfield{title}\textquotedbl\addcomma\space
	\iffieldundef{edition}{}{\printfield{edition}\addcomma\space}%
	\printlist{publisher}%
	\addperiod
	\newunit
	\finentry}

\DeclareBibliographyDriver{article}{%
	\printnames{author}\addcomma\space
	\printfield{year}\addperiod\space
	\textquotedbl\printfield{title}\textquotedbl\addcomma\space
	\printfield{journaltitle}\space
	\printfield{volume}%
	\iffieldundef{number}{}{(\printfield{number})}%
	\iffieldundef{pages}{}{\addcomma\space\printfield{pages}}%
	\iffieldundef{doi}%
		{\iffieldundef{url}{}{\addcomma\space\href{\thefield{url}}{\thefield{url}}}}%
		{\addcomma\space\href{https://doi.org/\thefield{doi}}{https://doi.org/\thefield{doi}}}%
	\addperiod
	\newunit
	\finentry}

\DeclareBibliographyDriver{online}{%
	\printnames{author}\addcomma\space
	\printfield{year}\addperiod\space
	\textquotedbl\printfield{title}\textquotedbl\addcomma\space
	\iffieldundef{organization}{}{\printfield{organization}\addcomma\space}%
	\iffieldundef{url}{}{\href{\thefield{url}}{\thefield{url}}}%
	\iffieldundef{note}{}{\addcomma\space\printfield{note}}%
	\addperiod
	\newunit
	\finentry}

\DeclareBibliographyDriver{report}{%
	\printnames{author}\addcomma\space
	\printfield{year}\addperiod\space
	\textquotedbl\printfield{title}\textquotedbl\addcomma\space
	\iflistundef{institution}{}{\printlist{institution}\space}%
	\iffieldundef{type}{}{\printfield{type}}%
	\addperiod
	\newunit
	\finentry}

\newcommand{\FooterText}{Slide preview}
\begin{document}
"""


def call_for_slide_path(path: Path) -> tuple[str, str, Optional[str]]:
    """Given slides/<id>-<slug>-current.tex or slides/<id>-<slug>-vX-Y-Z.tex,
    return (macro, id_slug, version) for the \\slide{}/\\slideversion{}
    call that loads exactly that file -- used by the slide-source editor,
    which only knows its own file path, not a deck-parsed SlideCall."""
    name = path.name
    if name.endswith("-current.tex"):
        return "slide", name[: -len("-current.tex")], None
    m = VERSION_FILE_RE.search(name)
    if m:
        return "slideversion", name[: m.start()], m.group(1)
    raise ValueError(f"{name}: doesn't look like a slides/ current or version file")


def _frame_number_line(frame_number: Optional[int]) -> str:
    """\\setcounter{framenumber}{...}, placed right before the \\slide{}-
    family call so its own \\stepcounter lands on frame_number exactly --
    lets a single-slide preview show the same page number the slide has in
    its real deck. Safe to inject unconditionally when given: nothing else
    in Slidemaster_preamble_base.tex touches "framenumber" before a frame's
    own \\stepcounter, and this project's own \\conditionalslide/\\omitslide
    already step that counter even for a call that renders no frame at all
    (see their own comments in Slidemaster_preamble_base.tex), specifically
    so a slide's frame number stays deck-version-invariant -- which is what
    makes a single caller-supplied number correct here regardless of which
    deck version the caller is previewing."""
    if frame_number is None:
        return ""
    return f"\\setcounter{{framenumber}}{{{frame_number - 1}}}\n"


def _deck_version_line(deck_version: Optional[str]) -> str:
    """`\\deckversion[...]` re-sets the same booleans/text a deck's own
    preamble already set (whether that's a real deck's own \\ifdefined...
    \\deckversion[instructor] fallback, or nothing at all for
    GENERIC_PREAMBLE, which relies on Slidemaster_preamble_base.tex's own
    "instructor" default) -- calling it again afterward is harmless and
    simply overrides with the caller's explicit choice. Placed after
    \\begin{document} (i.e. after whichever preamble ran), since
    \\deckversion itself is only defined once that preamble has loaded."""
    if deck_version is None:
        return ""
    return f"\\deckversion[{deck_version}]\n"


def _deck_language_line(deck_language: Optional[str]) -> str:
    """Twin of _deck_version_line above, for the slide-source editor's
    own one-off render language dropdown (2026-08-24) -- lets a
    multilingual (\\multilingualtext{}{}) slide be spot-checked in either
    language without needing a real deck file, mirroring exactly how the
    version dropdown already previews any deck version on demand. Same
    "re-set, harmless to call again" reasoning: \\decklanguage[...] simply
    overrides whichever language the preamble itself defaulted to."""
    if deck_language is None:
        return ""
    return f"\\decklanguage[{deck_language}]\n"


def _footer_timestamp_line(footer_timestamp: bool) -> str:
    """`\\def\\gothamFooterTimestampOverride{0}`, the same hook
    compiler.py's own wrapper defines for a full-deck compile when the
    main toolbar's "Include footer timestamp" checkbox is unticked
    (2026-08-26, direct report -- the slide-source editor's own "Render to
    PDF" ignored that checkbox entirely, always showing the timestamp).
    Unlike _deck_version_line/_deck_language_line above, this can't be
    placed after `preamble` in the wrapper -- Slidemaster_preamble_base.tex
    (which is what actually reads \\gothamFooterTimestampOverride) is
    \\input{}'d *inside* `preamble` itself, near its top, so the \\def has
    to come first for \\ifdefined to see it in time. Only emitted when
    False, same as compiler.py's own `if not job.footer_timestamp`."""
    if footer_timestamp:
        return ""
    return "\\def\\gothamFooterTimestampOverride{0}\n"


def _presenter_mode_line(presenter: bool) -> str:
    """`\\def\\gothamPresenterModeOverride{1}`, the same hook compiler.py's
    own wrapper defines for a real "Presenter" job (CompileJob.presenter)
    -- turns on beamer's dual-screen presenter mechanism
    (Slidemaster_preamble_base.tex's own \\ifdefined\\gothamPresenterModeOverride
    block: pgfpages "show notes on second screen"). Same placement
    constraint as _footer_timestamp_line above (has to come before
    `preamble`, since that's what \\input{}s Slidemaster_preamble_base.tex),
    and same "only emitted when true" shape as compiler.py's own
    `if job.presenter`."""
    if not presenter:
        return ""
    return "\\def\\gothamPresenterModeOverride{1}\n"


def _compile_and_extract(wrapper_text: str, id_slug: str, log: LogCallback,
                         snapshot_template: Optional[str] = None) -> Path:
    """Shared tail end of both render_slide_to_pdf() and
    render_slide_text_to_pdf(): write the wrapper, run latexmk, check the
    log for a real fatal error, move the finished PDF to its own fresh
    temp directory, and clean up every trace of the compile from both
    decks/ and .build/. Raises RuntimeError (with the log's own tail) on
    failure.

    `snapshot_template` (only ever passed by render_slide_to_pdf(), and
    only when it compiled the instructor version -- see there), when not
    None, refreshes .previews/slide_previews/<bare id>-<Template>-*.png from this
    render's last page as a side effect, at that template. Never lets a
    snapshot failure fail the render itself: a stale or missing preview
    image is a much smaller problem than losing a PDF the user actually
    asked to see.
    """
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    # "_slidemage_" prefix matches compiler.py's own wrapper naming, so
    # gui.py's existing "Remove temp files" sweep already covers a wrapper
    # left behind by a crash here too. A uuid suffix (not just the
    # id_slug) makes the jobname unique per call, not just per slide --
    # confirmed necessary directly: rendering the same slide from two tabs
    # at once (or double-clicking two different rows for the same slide)
    # would otherwise race two latexmk invocations over the exact same
    # .build/<jobname>.* files, the same class of corruption
    # deck_headers.py's own _LOCK exists to prevent (see that module).
    safe_id_slug = re.sub(r"[^A-Za-z0-9_-]", "_", id_slug)
    jobname = f"preview-{safe_id_slug}-{uuid.uuid4().hex[:8]}"
    wrapper_path = DECKS_DIR / f"_slidemage_{jobname}.tex"
    # newline="" -- NOT write_text's own default (None, which re-translates
    # every "\n" to the OS line ending on write). wrapper_text is a mix of
    # a real deck's own preamble_text (read by deck_scan.py with
    # newline="", so it already carries the file's literal "\r\n") and
    # freshly-generated fragments (_frame_number_line/_deck_version_line/
    # format_call, plain "\n"). Writing that mix with the default newline
    # handling doubles every already-"\r\n" into "\r\r\n" on Windows, since
    # write_text() still appends its own "\r" in front of the "\n" that's
    # already preceded by one. TeX treats each bare \r as its own
    # end-of-line, so a doubled "\r\r\n" is an invisible extra blank line
    # after every preamble line -- harmless almost everywhere (a stray
    # blank line inside a frame body/itemize is a no-op), but it corrupts
    # any *multi-line macro definition* captured from that preamble, most
    # visibly a \DeclareBibliographyDriver{article}{...} spanning many
    # lines: every field printed by \newcommand{\FooterText} shares that
    # exact bug class, but only became visible via \fullcite's own
    # multi-line driver, where the baked-in blank line after each field
    # only ever shows up once the driver is expanded inline inside a
    # \footnote{} -- exactly the "many surplus line breaks" root-caused
    # 2026-08-17 on kcc-Reasons-Repurchases (direct instruction: "renders
    # fine as part of #workdeck, but Preview -> Render now breaks the
    # footnote"). GENERIC_PREAMBLE (the slide-source editor's own "Render
    # to PDF") never hits this, since it's a plain Python string literal
    # with bare "\n" to begin with -- only a *deck's own* preamble_text
    # (every deck-editor-tab "Preview" -> "Render now") carries pre-existing
    # "\r\n" for this to double.
    wrapper_path.write_text(wrapper_text, encoding="utf-8", newline="")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    rel_wrapper = wrapper_path.relative_to(PROJECT_ROOT)
    # -outdir=BUILD_DIR, same as compiler.py's own run_job -- this has to
    # match .latexmkrc's own $aux_dir exactly (an *absolute* path to this
    # same BUILD_DIR, set unconditionally there), not some other temp
    # location: $aux_dir governs where latexmk actually writes the .log
    # regardless of what -outdir says, so a *different* -outdir here
    # silently splits the two apart -- confirmed directly: the .log ended
    # up in BUILD_DIR while a leftover 0-byte .pdf sat in the mismatched
    # -outdir, and the fatal-error check below, looking for the log in the
    # wrong place, missed it entirely and read the empty .pdf as a pass.
    cmd = [
        "latexmk", "-f", f"-jobname={jobname}", f"-outdir={BUILD_DIR.as_posix()}",
        str(rel_wrapper),
    ]
    env = _build_env()
    popen_kwargs: dict = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    log(f"==== Rendering {id_slug} -> {jobname} ====")
    try:
        proc = subprocess.Popen(
            cmd, cwd=PROJECT_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            **popen_kwargs,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip("\n"))
        proc.wait()
    except FileNotFoundError:
        raise RuntimeError("latexmk not found on PATH -- is a TeX distribution installed?")
    finally:
        wrapper_path.unlink(missing_ok=True)

    log_path = BUILD_DIR / f"{jobname}.log"
    build_pdf_path = BUILD_DIR / f"{jobname}.pdf"
    ok = build_pdf_path.exists() and build_pdf_path.stat().st_size > 0
    if ok and log_path.exists():
        if FATAL_ERROR_RE.search(log_path.read_text(encoding="utf-8", errors="replace")):
            ok = False
    elif not log_path.exists():
        ok = False

    if not ok:
        tail = ""
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-20:])
        log(f"*** FAIL: render of {id_slug} -- see log tail below ***")
        raise RuntimeError(f"Render failed for {id_slug}:\n{tail}")

    # Move the finished PDF out of .build/ into a fresh, genuinely
    # temporary directory of its own (not pdf/ -- this is a scratch
    # preview, not a build artifact), named after the slide itself rather
    # than the jobname's own uuid suffix, for a sane PDF-viewer window
    # title/taskbar entry.
    out_dir = Path(tempfile.mkdtemp(prefix="slidemage_preview_"))
    dest_pdf = out_dir / f"{id_slug}.pdf"
    shutil.move(str(build_pdf_path), str(dest_pdf))
    for aux in BUILD_DIR.glob(f"{jobname}.*"):
        aux.unlink(missing_ok=True)

    if snapshot_template is not None:
        try:
            # bare id, not the full id_slug -- capture_deck() (the "Update
            # previews"/full-compile path) always keys a snapshot by the
            # bare id it parses straight out of the compiled page's own
            # footer ("slide id: XXX", i.e. \slideID, which \setSlideID
            # derives from everything before the *first* "-"). Passing the
            # full id_slug here instead produced e.g.
            # "kcc-Reasons-Repurchases-UniGraz-1920-1080.png" alongside the
            # correct "kcc-UniGraz-1920-1080.png" a full compile would
            # cache -- two different files for the same slide, one of them
            # never found by any lookup (snapshot_path()/is_fresh() only
            # ever look up the bare id) and therefore silently dead weight.
            # Root-caused 2026-08-17 (direct instruction: "some slides have
            # now turned up with full slugs instead of the typical
            # nomenclature") from every "Preview -> Render now" render,
            # not just this project's own recently-touched slides.
            slide_snapshot.capture_single_slide(
                dest_pdf, slide_snapshot.bare_id(id_slug), snapshot_template)
        except Exception as exc:
            log(f"    (preview snapshot not updated: {exc})")

    log(f"==== PASS: render of {id_slug} -> {dest_pdf} ====")
    return dest_pdf


def render_slide_to_pdf(
    macro: str,
    id_slug: str,
    version: Optional[str] = None,
    conditions: Optional[list] = None,
    deck_version: Optional[str] = None,
    deck_language: Optional[str] = None,
    footer_timestamp: bool = True,
    preamble_text: Optional[str] = None,
    frame_number: Optional[int] = None,
    log: Optional[LogCallback] = None,
    steps: Optional[str] = None,
) -> Path:
    """Compile one \\macro{id_slug}[{version}] call to a standalone PDF in
    a fresh OS temp directory (never pdf/ -- this is a scratch preview, not
    a build artifact) and return its path. Raises RuntimeError (with the
    compile log's own tail) on failure.

    preamble_text defaults to GENERIC_PREAMBLE; pass a real Deck's own
    preamble_text (everything through \\begin{document}) to render with
    that deck's actual theme/colors/footer instead.

    deck_version, one of DECK_VERSIONS, overrides whichever deck version
    the preamble itself would otherwise default to (see _deck_version_line).

    frame_number, when given (the slide's own 1-based position among its
    deck's \\slide{}-family calls -- see qt_deck_editor_tab.py's own
    per-row Render button), makes the footer show that same page number
    instead of always "1" (see _frame_number_line).

    `footer_timestamp` (2026-08-30, direct report) mirrors the main
    toolbar's own "Include footer timestamp" checkbox, the same
    _footer_timestamp_line hook render_slide_text_to_pdf's own docstring
    already explains -- this function (the "Preview" popup's "Render now",
    used by both qt_slide_source_tab.py's own _on_preview() and
    qt_deck_editor_tab.py's _render_to_pdf()) ignored it entirely too,
    always showing the timestamp regardless of the checkbox's state; the
    2026-08-26 fix only reached render_slide_text_to_pdf's own separate
    "Render to PDF" button, this sibling function was missed.

    Refreshes this slide's compile-time PNG snapshot (slide_snapshot.py) as
    a side effect, but only when rendering the instructor version -- `None`
    here means "whatever the preamble defaults to", which is instructor
    for GENERIC_PREAMBLE (Slidemaster_preamble_base.tex's own default) and,
    in practice, for every real deck's preamble too. An explicit
    during-course/after-course request is a deliberate look at a *partial*
    version, and must never overwrite the canonical (fullest-content)
    snapshot with it. The snapshot is captured under whichever institution
    template `preamble` itself selects (slide_snapshot.detect_template()),
    not a fixed one -- a deck row previewing under its own preamble ends up
    caching the *right* template's image, not always Graz.
    """
    log = log or (lambda line: None)
    preamble = GENERIC_PREAMBLE if preamble_text is None else preamble_text
    # \slidestep keeps its own reveal-step restriction, but is shown for every deck
    # version: a preview compiles as the instructor deck, which would otherwise
    # render nothing for a call listed only for the student versions.
    call = format_call(macro, id_slug, version, None if macro == "slidestep" else conditions, steps)
    wrapper_text = (
        f"{_footer_timestamp_line(footer_timestamp)}{preamble}"
        f"{_deck_version_line(deck_version)}{_deck_language_line(deck_language)}"
        f"{_frame_number_line(frame_number)}"
        f"\t{call}\n\\end{{document}}\n"
    )
    snapshot_template = (
        slide_snapshot.detect_template(preamble)
        if deck_version in (None, "instructor") else None
    )
    return _compile_and_extract(
        wrapper_text, id_slug, log, snapshot_template=snapshot_template,
    )


def render_slide_text_to_pdf(
    id_slug: str,
    slide_body: str,
    deck_version: Optional[str] = None,
    deck_language: Optional[str] = None,
    footer_timestamp: bool = True,
    presenter: bool = False,
    preamble_text: Optional[str] = None,
    log: Optional[LogCallback] = None,
) -> Path:
    """Like render_slide_to_pdf, but compiles `slide_body` (e.g. the
    slide-source editor's own in-memory buffer text) directly, instead of
    \\slide{}'s own \\input{slides/<id_slug>-current.tex} -- the real
    slides/<id_slug>-*.tex file on disk is never read or written by this
    path. \\slide{}'s own two effects (\\setSlideID{}, then the file's own
    content) are replicated by hand: \\setSlideID{id_slug} followed by
    slide_body pasted in verbatim, exactly where \\input{} would have
    spliced it in.

    This is what lets the slide-source editor preview an unsaved edit
    without saving first and without touching the file's own on-disk
    state (so its dirty flag / Revert button stay exactly as they were
    before rendering).

    \\setSlideLanguageFromSlug{id_slug} alongside \\setSlideID{} replicates
    \\slide{}'s own second effect by hand too (2026-08-24) -- without it, a
    language-tagged slide previewed this way would show no footer language
    tag at all, an inconsistency with what a real \\slide{} compile of the
    same file shows. `deck_language` overrides \\decklanguage the same way
    `deck_version` already overrides \\deckversion, letting a
    \\multilingualtext{}{} slide be spot-checked in either language.

    `footer_timestamp` (2026-08-26, direct report) mirrors the main
    toolbar's own "Include footer timestamp" checkbox, which this render
    path previously ignored entirely -- see _footer_timestamp_line for why
    it has to come before `preamble`, unlike the other two overrides.

    `presenter` (2026-09-25, direct instruction: "include 'Presenter' as
    a version for the render version") turns on beamer's dual-screen
    presenter mechanism the same way compiler.py's own real-deck
    "Presenter" job does (see _presenter_mode_line) -- the slide-source
    editor's "Render version" combo offers it as one more choice
    alongside Instructor/During-course/After-course, but it isn't a
    `deck_version` value itself: content-wise a presenter render is
    always instructor (the combo's own caller passes deck_version=
    "instructor" whenever "Presenter" is picked), this flag is what
    actually switches on the dual-screen layout.

    Also refreshes this slide's compile-time PNG snapshot (2026-08-31,
    direct report: "Render to PDF" succeeded but "Preview" then said no
    preview had been generated yet) -- this function used to call
    _compile_and_extract() without a `snapshot_template`, so it silently
    skipped the capture_single_slide() side effect that
    render_slide_to_pdf() above already documents and performs; the
    "Preview" popup (qt_slide_preview_popup.py's _load_image()) reads
    exactly that cached PNG, so it never found one. Same
    instructor-version-only guard as render_slide_to_pdf(), for the same
    reason: an explicit during-course/after-course request is a
    deliberate look at a *partial* version, and must never overwrite the
    canonical (fullest-content) snapshot with it -- a presenter render
    is excluded from caching too, same reasoning as compiler.py's own
    skip-normal-PDF-handling branch for it (its page count/per-page
    layout is nothing like a normal compile's, so reading it the normal
    way would corrupt the snapshot cache)."""
    log = log or (lambda line: None)
    preamble = GENERIC_PREAMBLE if preamble_text is None else preamble_text
    wrapper_text = (
        f"{_footer_timestamp_line(footer_timestamp)}{_presenter_mode_line(presenter)}{preamble}"
        f"{_deck_version_line(deck_version)}{_deck_language_line(deck_language)}"
        f"\\setSlideID{{{id_slug}}}\\setSlideLanguageFromSlug{{{id_slug}}}\n"
        f"{slide_body}\n\\end{{document}}\n"
    )
    snapshot_template = (
        slide_snapshot.detect_template(preamble)
        if deck_version in (None, "instructor") and not presenter else None
    )
    return _compile_and_extract(
        wrapper_text, id_slug, log, snapshot_template=snapshot_template,
    )


def open_pdf(pdf_path: Path) -> None:
    open_path.open_in_default_app(pdf_path)
