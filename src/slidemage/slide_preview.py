"""Render a single slide to a standalone, temporary PDF and open it --
used by the workspace's Preview (ui/workspace/preview_view.py, through
preview_target.py) with the open deck's own preamble, so theme/colors/footer
match how the slide actually looks in context. A slide that is in no deck
falls back to a generic standalone preamble matching decks/test.tex, this
project's own demo deck.

Reuses compiler.py's own build_env()/FATAL_ERROR_RE (the Git-for-Windows
Perl PATH fix and the "trust the log, not the exit code" pass/fail check --
see that module's own docstring for why both are needed) rather than
duplicating them.
"""
from __future__ import annotations

from datetime import datetime
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from . import app_settings, compile_log, compiler, open_path, preview_build, project
from . import slide_language, slide_snapshot
from .compiler import build_env
from .deck_editor import format_call
from .preview_metrics import measure
from .tex_source import COMMENT_RE


LogCallback = Callable[[str], None]

# A file just written by latexmk/lualatex can stay locked for a moment on
# Windows (the cloud-sync client and the search indexer open new files in a
# synced project folder; lualatex's own handle on the .fls/.synctex files may
# outlive latexmk by a few ms). Deleting or moving it then raises
# PermissionError (WinError 32).
_LOCK_RETRIES = 8
_LOCK_RETRY_DELAY = 0.25
# Leftovers of earlier previews that never got cleaned up are swept once they
# are this old (seconds).
_STALE_PREVIEW_AGE = 3600


# Single-slide renders (the slide editor's "Render to PDF", a Preview popup's
# "Render now") leave their PDF in a folder of its own under the OS temp
# directory so the viewer opens it; nothing else ever deleted them. They are
# removed once they are at least this old (seconds) -- 24 hours by default,
# direct instruction 2026-10-11 -- by sweep_old_renders(), which runs shortly
# after the app starts and after every render, so "sometime after" that age.
# Since v8.21.0 the age is a setting (Settings -> General, app_settings key
# RENDER_CLEANUP_SETTING_KEY, in hours; 0 = never delete them).
RENDER_FOLDER_PREFIX = preview_build.RENDER_FOLDER_PREFIX
RENDER_MAX_AGE = 24 * 3600
RENDER_CLEANUP_SETTING_KEY = "render_cleanup_hours"
RENDER_CLEANUP_NEVER = 0
RENDER_CLEANUP_CHOICES = (     # (hours, label) for Settings -> General
    (1, "After 1 hour"), (24, "After 24 hours"), (72, "After 3 days"), (168, "After 1 week"),
    (720, "After 30 days"), (RENDER_CLEANUP_NEVER, "Never"))
RENDER_CLEANUP_DEFAULT_HOURS = RENDER_MAX_AGE // 3600


def render_cleanup_hours(ctx: project.ProjectContext) -> int:
    """The project's cleanup setting in hours (RENDER_CLEANUP_NEVER: never); a missing or
    unreadable value means the default, 24 hours."""
    try:
        hours = int(app_settings.get(ctx, RENDER_CLEANUP_SETTING_KEY, RENDER_CLEANUP_DEFAULT_HOURS))
    except (TypeError, ValueError, OSError):
        return RENDER_CLEANUP_DEFAULT_HOURS
    return hours if hours >= 0 else RENDER_CLEANUP_DEFAULT_HOURS


def sweep_renders(ctx: project.ProjectContext, temp_dir: Optional[Path] = None) -> int:
    """sweep_old_renders() with the project's cleanup setting; does nothing when it is Never.
    Best-effort and silent, like sweep_old_renders()."""
    try:
        hours = render_cleanup_hours(ctx)
    except Exception:  # noqa: BLE001 -- a cleanup must never break a render or the start
        return 0
    if hours == RENDER_CLEANUP_NEVER:
        return 0
    return sweep_old_renders(hours * 3600, temp_dir)


def sweep_old_renders(max_age: float = RENDER_MAX_AGE, temp_dir: Optional[Path] = None) -> int:
    """Delete the single-slide render folders (`slidemage_preview_*` under
    the temp directory) that are at least `max_age` seconds old; returns how
    many were removed. Only folders that look like ours (that prefix, holding
    nothing but files) are touched. Best-effort and silent: a PDF a viewer
    still has open stays (Windows won't delete it) and is retried by the next
    sweep."""
    root = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    cutoff = time.time() - max_age
    removed = 0
    try:
        candidates = list(root.glob(f"{RENDER_FOLDER_PREFIX}*"))
    except OSError:
        return 0
    for folder in candidates:
        try:
            if not folder.is_dir() or folder.stat().st_mtime > cutoff:
                continue
            files = list(folder.iterdir())
            if any(not f.is_file() for f in files):
                continue
            if any(f.stat().st_mtime > cutoff for f in files):
                continue  # something in it was written recently
            for f in files:
                f.unlink()
            folder.rmdir()
            removed += 1
        except OSError:
            continue  # in use, or already gone -- the next sweep tries again
    return removed


def _retry_on_lock(action: Callable[[], None]) -> bool:
    """Run `action`, retrying while the OS reports the file is locked.
    True when it eventually worked, False when it never did (the caller
    decides whether that matters)."""
    for attempt in range(_LOCK_RETRIES):
        try:
            action()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt + 1 < _LOCK_RETRIES:
                time.sleep(_LOCK_RETRY_DELAY)
    return False


def _remove_build_files(ctx: project.ProjectContext, jobname: str) -> int:
    """Delete every .build/<jobname>.* file; returns how many stayed behind.
    Never raises: a build file that cannot be deleted right now is not a
    reason to fail a render that has already succeeded."""
    left = 0
    for aux in ctx.build_dir.glob(f"{jobname}.*"):
        if not _retry_on_lock(lambda aux=aux: aux.unlink(missing_ok=True)):
            left += 1
    return left


def _sweep_stale_previews(ctx: project.ProjectContext) -> None:
    """Best-effort removal of .build/preview-* files left behind by renders
    that were interrupted (or whose cleanup hit a locked file)."""
    cutoff = time.time() - _STALE_PREVIEW_AGE
    try:
        for stale in ctx.build_dir.glob("preview-*.*"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                pass
    except OSError:
        pass

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

# GENERIC_PREAMBLE's template line; template_preamble() swaps it for another
# template's (2026-10-03: the default render template is a setting now, see
# slide_snapshot.render_template()).
_GRAZ_INPUT = "\\input{Slidemaster_preamble_uni-graz}"


def template_preamble(template: str) -> str:
    """GENERIC_PREAMBLE rendering in `template` (a slide_snapshot.TEMPLATES
    key; an unknown one falls back to slide_snapshot.DEFAULT_TEMPLATE)."""
    if template not in slide_snapshot.TEMPLATES:
        template = slide_snapshot.DEFAULT_TEMPLATE
    return GENERIC_PREAMBLE.replace(
        _GRAZ_INPUT, f"\\input{{Slidemaster_preamble_{template}}}")


def default_preamble(ctx: project.ProjectContext) -> str:
    """The preamble for a render with no deck: the default render template
    chosen in Settings -> General (slide_snapshot.render_template())."""
    return template_preamble(slide_snapshot.render_template(ctx))


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
    """`\\def\\SMFooterTimestampOverride{0}`, the same hook
    compiler.py's own wrapper defines for a full-deck compile when the
    main toolbar's "Include footer timestamp" checkbox is unticked
    (2026-08-26, direct report -- the slide-source editor's own "Render to
    PDF" ignored that checkbox entirely, always showing the timestamp).
    Unlike _deck_version_line/_deck_language_line above, this can't be
    placed after `preamble` in the wrapper -- Slidemaster_preamble_base.tex
    (which is what actually reads \\SMFooterTimestampOverride) is
    \\input{}'d *inside* `preamble` itself, near its top, so the \\def has
    to come first for \\ifdefined to see it in time. Only emitted when
    False, same as compiler.py's own `if not job.footer_timestamp`."""
    if footer_timestamp:
        return ""
    return "\\def\\SMFooterTimestampOverride{0}\n"


def _presenter_mode_line(presenter: bool) -> str:
    """`\\def\\SMPresenterModeOverride{1}`, the same hook compiler.py's
    own wrapper defines for a real "Presenter" job (CompileJob.presenter)
    -- turns on beamer's dual-screen presenter mechanism
    (Slidemaster_preamble_base.tex's own \\ifdefined\\SMPresenterModeOverride
    block: pgfpages "show notes on second screen"). Same placement
    constraint as _footer_timestamp_line above (has to come before
    `preamble`, since that's what \\input{}s Slidemaster_preamble_base.tex),
    and same "only emitted when true" shape as compiler.py's own
    `if job.presenter`."""
    if not presenter:
        return ""
    return "\\def\\SMPresenterModeOverride{1}\n"


@measure('build')
def compile_and_extract(ctx: project.ProjectContext, wrapper_text: str, id_slug: str, log: LogCallback,
                         snapshot_template: Optional[str] = None,
                         reuse_build: bool = True, cancel=None) -> Path:
    """Shared tail end of both render_slide_to_pdf() and
    render_slide_text_to_pdf(): build the wrapper (preview_build.run_preview),
    check the log for a real fatal error, move the finished PDF to its own
    fresh temp directory, and clean up every trace of the compile from both
    decks/ and .build/. Raises RuntimeError (with the log's own tail) on
    failure.

    With reuse_build=True, keep latexmk state in an isolated, locked cache;
    reuse_build=False retains the original fresh-job behavior for comparison.

    `snapshot_template` (only ever passed by render_slide_to_pdf(), and
    only when it compiled the instructor version -- see there), when not
    None, refreshes .previews/slide_previews/<bare id>-<Template>-*.png from this
    render's last page as a side effect, at that template. Never lets a
    snapshot failure fail the render itself: a stale or missing preview
    image is a much smaller problem than losing a PDF the user actually
    asked to see.
    """
    env = build_env(ctx)
    dest_pdf = (preview_build.compile_cached(wrapper_text, id_slug, log, ctx=ctx, env=env, cancel=cancel) if reuse_build
                else _compile_fresh(ctx, wrapper_text, id_slug, log, env, cancel))
    if snapshot_template is not None:
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
        try:
            slide_snapshot.capture_single_slide(
                ctx, dest_pdf, slide_language.bare_id(id_slug), snapshot_template)
        except Exception as exc:
            log(f"    (preview snapshot not updated: {exc})")
    log(compile_log.render_passed(id_slug, dest_pdf))
    return dest_pdf


def _compile_fresh(ctx: project.ProjectContext, wrapper_text: str, id_slug: str, log: LogCallback, env: dict, cancel=None) -> Path:
    """A build of its own: a unique jobname, latexmk's output in .build/, nothing kept afterwards."""
    ctx.decks_dir.mkdir(parents=True, exist_ok=True)
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
    wrapper_path = ctx.decks_dir / f"_slidemage_{jobname}.tex"
    with preview_build.active_build(ctx.build_dir, wrapper_path, cancel):
        ctx.build_dir.mkdir(parents=True, exist_ok=True)
        log(compile_log.rendering(id_slug, jobname))
        try:
            with compiler.wrapper_file(wrapper_path, wrapper_text, remove=lambda p: _retry_on_lock(lambda: p.unlink(missing_ok=True))):
                pdf, _ = preview_build.run_preview(ctx, wrapper_path, jobname, id_slug, ctx.build_dir, log,
                                                   env=env, reusable=False, cancel=cancel)
        except RuntimeError:
            log(compile_log.render_failed(id_slug, "see log tail below"))
            raise

        def copy_out(source: Path, dest: Path) -> None:
            # Not shutil.move(): a locked source makes its copy-then-delete
            # fallback fail after the copy, and the PDF is what matters here.
            if not _retry_on_lock(lambda: shutil.copyfile(source, dest)):
                raise OSError(f"could not read {source}")

        try:
            dest_pdf = preview_build.publish_preview(ctx, pdf, id_slug, ctx.build_dir, jobname, copy=copy_out)
        except OSError as exc:
            log(compile_log.render_failed(
                id_slug, f"the finished PDF could not be copied out of .build/ ({exc})"))
            raise RuntimeError(f"Render failed for {id_slug}: {exc}") from exc
        left = _remove_build_files(ctx, jobname)
        if left:
            log(f"    ({left} build file(s) of this render could not be deleted yet "
                f"-- they will be swept with a later render)")
        _sweep_stale_previews(ctx)
        return dest_pdf


@measure('render')
def render_slide_to_pdf(
    ctx: project.ProjectContext,
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
    reuse_build: bool = True,
    overlay: Optional[int] = None,
    capture_snapshot: bool = True,
    cancel=None,
    all_steps: bool = False,
) -> Path:
    """Compile one \\macro{id_slug}[{version}] call to a standalone PDF in
    a fresh OS temp directory (never pdf/ -- this is a scratch preview, not
    a build artifact) and return its path. Raises RuntimeError (with the
    compile log's own tail) on failure.

    preamble_text defaults to default_preamble() (the default render
    template from Settings -> General); pass a real Deck's own
    preamble_text (everything through \\begin{document}) to render with
    that deck's actual theme/colors/footer instead.

    deck_version, one of DECK_VERSIONS, overrides whichever deck version
    the preamble itself would otherwise default to (see _deck_version_line).

    frame_number, when given (the slide's own 1-based position among its
    deck's \\slide{}-family calls), makes the footer show that same page number
    instead of always "1" (see _frame_number_line).

    reuse_build retains dependency-checked auxiliary state between requests.
    overlay selects a positive reveal number per frame; None keeps all pages.
    Explicit overlay selections do not update canonical snapshots, and neither
    does `capture_snapshot=False` (a frozen version looked at on its own is not
    what the slide's thumbnail should show).

    `footer_timestamp` (2026-08-30, direct report) mirrors the main
    toolbar's own "Include footer timestamp" checkbox, the same
    _footer_timestamp_line hook render_slide_text_to_pdf's own docstring
    already explains -- this function (the Preview's "Render now",
    preview_target.render()) ignored it entirely too,
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
    preamble = default_preamble(ctx) if preamble_text is None else preamble_text
    # \slidestep keeps its own reveal-step restriction, but is shown for every deck
    # version: a preview compiles as the instructor deck, which would otherwise
    # render nothing for a call listed only for the student versions.
    call = format_call(macro, id_slug, version, None if macro == "slidestep" else conditions, steps)
    wrapper_text = (
        f"{_footer_timestamp_line(footer_timestamp)}{preamble}"
        f"{_deck_version_line(deck_version)}{_deck_language_line(deck_language)}"
        f"{_preview_timestamp_line(footer_timestamp)}"
        f"{_frame_number_line(frame_number)}{_overlay_line(overlay, all_steps)}"
        f"\t{call}\n\\end{{document}}\n"
    )
    snapshot_template = (
        slide_snapshot.detect_template(preamble)
        if capture_snapshot and deck_version in (None, "instructor") and overlay is None and not all_steps else None
    )
    return compile_and_extract(
        ctx, wrapper_text, id_slug, log, snapshot_template=snapshot_template,
        reuse_build=reuse_build, cancel=cancel,
    )


@measure('render')
def render_slide_text_to_pdf(
    ctx: project.ProjectContext,
    id_slug: str,
    slide_body: str,
    deck_version: Optional[str] = None,
    deck_language: Optional[str] = None,
    footer_timestamp: bool = True,
    presenter: bool = False,
    preamble_text: Optional[str] = None,
    log: Optional[LogCallback] = None,
    reuse_build: bool = True,
    preview_mode: str = "slide",
    overlay: Optional[int] = None,
    frame_number: Optional[int] = None,
    capture_snapshot: bool = True,
    cancel=None,
    all_steps: bool = False,
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
    compile_and_extract() without a `snapshot_template`, so it silently
    skipped the capture_single_slide() side effect that
    render_slide_to_pdf() above already documents and performs; the
    Preview (preview_target.cached_image()) reads
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
    preamble = default_preamble(ctx) if preamble_text is None else preamble_text
    if overlay is not None and preview_mode == "element":
        raise ValueError("Element previews do not have frame overlays")
    if presenter and preview_mode == "element":
        raise ValueError("Use Instructor instead of Presenter for an element preview")
    preamble, slide_body = _region_source(preamble, slide_body, preview_mode)
    wrapper_text = (
        f"{_footer_timestamp_line(footer_timestamp)}{_presenter_mode_line(presenter)}{preamble}"
        f"{_frame_number_line(frame_number)}{_overlay_line(overlay, all_steps)}"
        f"{_deck_version_line(deck_version)}{_deck_language_line(deck_language)}"
        f"{_preview_timestamp_line(footer_timestamp)}"
        f"\\setSlideID{{{id_slug}}}\\setSlideLanguageFromSlug{{{id_slug}}}\n"
        f"{slide_body}\n\\end{{document}}\n"
    )
    snapshot_template = (
        slide_snapshot.detect_template(preamble)
        if capture_snapshot and deck_version in (None, "instructor") and not presenter
        and preview_mode == "slide" and overlay is None and not all_steps else None
    )
    return compile_and_extract(
        ctx, wrapper_text, id_slug, log, snapshot_template=snapshot_template,
        reuse_build=reuse_build, cancel=cancel,
    )


def open_pdf(pdf_path: Path) -> None:
    open_path.open_in_default_app(pdf_path)



def _overlay_line(overlay: Optional[int], all_steps: bool = False) -> str:
    """Apply a frame-level restriction, including to raw Beamer frames.

    Default action specifications affect item visibility, not which PDF pages
    are produced. Patch the frame loop instead and fail explicitly on changes
    to Beamer's interface. An explicit selection overrides a slidestep filter.
    `all_steps` selects every overlay (`1-`), so it overrides a \\slidestep's steps, the final-state
    flag and a spec written on the slide's own raw frame: page k is then overlay k.
    """
    if all_steps and overlay is None:
        return (
            "\\makeatletter\n"
            "\\pretocmd{\\beamer@doseveralframes}"
            "{\\gdef\\beamer@whichframes{1-}}"
            "{}{\\PackageError{SlideMage}{Cannot select all preview overlays}{}}\n"
            "\\makeatother\n"
        )
    if overlay is None:
        return ""
    if isinstance(overlay, bool) or not isinstance(overlay, int) or overlay < 1:
        raise ValueError("Overlay must be a positive integer")
    return (
        "\\makeatletter\n"
        "\\pretocmd{\\beamer@doseveralframes}"
        f"{{\\gdef\\beamer@whichframes{{{overlay}}}}}"
        "{}{\\PackageError{SlideMage}{Cannot select preview overlay}{}}\n"
        "\\pretocmd{\\beamer@autobreakframe}"
        "{\\PackageError{SlideMage}{Overlay preview does not support allowframebreaks}{Use all overlays}}"
        "{}{\\PackageError{SlideMage}{Cannot validate preview overlay}{}}\n"
        "\\makeatother\n"
    )


def _region_source(preamble: str, body: str, mode: str) -> tuple[str, str]:
    """Build AUCTeX-style region or preview-latex element wrappers.

    A region must be a complete frame or a self-contained fragment; arbitrary
    unbalanced selections are deliberately left to TeX's normal diagnostics.
    Element previews have their own crop and never refresh full-slide snapshots.
    """
    if mode == "slide":
        return preamble, body
    if mode not in ("region", "element"):
        raise ValueError(f"Unknown preview mode: {mode}")
    if not body.strip():
        raise ValueError("Select some LaTeX to preview first")
    has_frame = re.search(r"\\begin\{\w*frame\}|\\(?:title|section|quote|figure|fullbleed|standout)frame\b", COMMENT_RE.sub("", body))
    if mode == "region":
        return preamble, body if has_frame else "\\begin{frame}\n" + body + "\n\\end{frame}"
    if has_frame:
        raise ValueError("Element preview needs a formula, graphic or text fragment; use Region for complete frames")
    marker = r"\begin{document}"
    if marker not in preamble:
        raise ValueError("The preview preamble must include \\begin{document}")
    # Beamer normally initializes this list-spacing hook when opening a
    # frame. Isolated preview elements never open one; use its normal default.
    setup = ("\\usepackage[active,tightpage]{preview}\n"
             "\\setlength{\\PreviewBorder}{6pt}\n"
             "\\makeatletter\\providecommand{\\beamer@cramped}{}\\makeatother\n")
    preamble = preamble.replace(marker, setup + marker, 1)
    return preamble, "\\begin{preview}\n" + body + "\n\\end{preview}"


def _preview_timestamp_line(enabled: bool, stamp: Optional[str] = None) -> str:
    """Refresh the timestamp file, preserving the framework's normal input path.

    The literal value is stable across latexmk passes but changes on the next
    request in a new minute. Loading this file also preserves TeX whitespace
    in examples that measure the timestamp without displaying it.
    """
    if not enabled:
        return ""
    stamp = stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        "\\immediate\\openout\\SMCompileTimestampFile=\\jobname.timestamp\\relax\n"
        "\\immediate\\write\\SMCompileTimestampFile{"
        f"\\string\\gdef\\string\\SMCompileTimestampValue{{{stamp}}}" + "}\n"
        "\\immediate\\closeout\\SMCompileTimestampFile\n"
    )
