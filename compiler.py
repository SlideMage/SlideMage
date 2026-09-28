"""Build a compile job's wrapper .tex and run it through latexmk.

Reuses compile-all-versions.bat's own proven trick for picking a deck
version (a tiny wrapper file that \\def's \\deckversionoverride then
\\input{}s the real deck -- latexmk's own -usepretex strips braces/
backslashes from its argument, so a real wrapper *file* is used instead),
extended here to also let a wrapper restrict itself to one chapter's own
slides by copying the deck's preamble verbatim and swapping in just that
chapter's slice of the body.

latexmk is always invoked from the project root (cwd), with a path to the
wrapper relative to that root, so the one shared root .latexmkrc governs
$aux_dir/$do_cd consistently -- matching compile-all.bat/
compile-all-versions.bat's own invocation style. Pass/fail is decided by
scanning .build/<jobname>.log for a line starting with "!" (a fatal LaTeX
error) plus checking the PDF now exists, never by latexmk's exit code:
lualatex returns nonzero even on a fully clean compile, from harmless Fira
Sans font-substitution warnings (see README.md's "Compiling without
TeXstudio" section).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# How often to try the PDF -> pdf/ relocation again, and for how long
# total, before giving up on it for good. Runs entirely on its own
# detached background thread (see _relocate_pdf_and_finish) -- nothing
# else in the app waits on this, so being generous here costs nothing but
# the small chance of leaving a job's compiled PDF in .build/ a while
# longer than ideal if the sync client is having a bad day.
PDF_MOVE_RETRY_INTERVAL_SECONDS = 10.0
PDF_MOVE_RETRY_TOTAL_SECONDS = 15 * 60.0

from . import appendix_toc, slide_snapshot
from .deck_scan import DOCUMENT_END_RE, PROJECT_ROOT, Chapter, Deck

BUILD_DIR = PROJECT_ROOT / ".build"
PDF_DIR = PROJECT_ROOT / "pdf"


def resolve_output_location(job: "CompileJob") -> tuple[Path, str]:
    """Where this job's compiled PDF should actually land, and what its
    filename (without ".pdf") should be: a deck-declared \\deckoutputfolder
    (deck_scan.py's OUTPUT_FOLDER_RE) directory plus job.jobname by
    default, or PDF_DIR plus job.jobname if the deck has none. A
    version-less deck (job.version is None) is treated as "instructor" for
    lookup purposes, so a bare `\\deckoutputfolder[instructor]{...}` line
    works the same whether or not the deck formally supports the
    During-course/After-course version system -- same normalization
    per-chapter jobs already get for free, since their own .version is
    already "instructor"/"after-course". A relative path resolves against
    PROJECT_ROOT, the same base every relative \\includegraphics path in
    this project already resolves against (confirmed: real slides
    reference e.g. "media/icon-x.png" and compile correctly with latexmk
    invoked from PROJECT_ROOT).

    A presenter job (job.presenter) checks `\\deckoutputfolder[presenter]{...}`
    first, before falling back to the same instructor/bare lookup any other
    job uses -- job.version is *already* "instructor" for a presenter job
    (qt_deck_table.py's own DeckRow.build_jobs()), so without this a
    presenter compile would otherwise silently share the plain instructor
    PDF's own folder/filename with no way to tell them apart (2026-09-17,
    found via direct question after a real deck used [presenter] and
    nothing distinguished its output from [instructor]'s).

    If the declared path itself names a full file (i.e. has a suffix --
    "D:/Teaching/IA2/Handout.pdf", not just "D:/Teaching/IA2") rather than
    a bare folder, that exact filename is used instead of job.jobname --
    2026-09-17, direct instruction: "if I specify a full file name (not
    just a folder) ... use that filename for the generated file"."""
    version_key = job.version or "instructor"
    if job.presenter:
        raw = (job.deck.output_folders.get("presenter")
                or job.deck.output_folders.get(version_key)
                or job.deck.output_folders.get(None))
    else:
        raw = job.deck.output_folders.get(version_key) or job.deck.output_folders.get(None)
    if raw is None:
        return PDF_DIR, job.jobname
    path = Path(raw)
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    if resolved.suffix:
        return resolved.parent, resolved.stem
    return resolved, job.jobname


def latest_pdf_for_deck(deck: Deck) -> Optional[Path]:
    """The most recently written PDF SlideMage has produced for `deck`, or
    None if there is none on disk. Checks every output this deck could have
    (each version, presenter, appendix and per-chapter variant) at both the
    destination its current \\deckoutputfolder declarations resolve to and the
    default pdf/ folder -- so a PDF compiled before an output folder was
    declared (or after it was changed) still counts. "Latest" is by file
    modification time."""
    versions = ["instructor", "during-course", "after-course"] if deck.supports_version else [None]
    jobs: list[CompileJob] = []
    for appendix in (False, True):
        for version in versions:
            jobs.append(CompileJob(deck, version, None, appendix_toc=appendix))
        presenter_version = "instructor" if deck.supports_version else None
        jobs.append(CompileJob(deck, presenter_version, None, presenter=True, appendix_toc=appendix))
    chapter_version = "after-course" if deck.supports_version else None
    for chapter in deck.chapters:
        jobs.append(CompileJob(deck, chapter_version, chapter))

    candidates: set[Path] = set()
    for job in jobs:
        output_dir, output_stem = resolve_output_location(job)
        candidates.add(output_dir / f"{output_stem}.pdf")
        candidates.add(PDF_DIR / f"{job.jobname}.pdf")
    existing = [p for p in candidates if p.is_file()]
    return max(existing, key=lambda p: p.stat().st_mtime) if existing else None


def _display_path(path: Path) -> str:
    """A PDF's destination for the compile log -- relative to PROJECT_ROOT
    (e.g. "pdf/foo.pdf") when it's under there, same as the old hardcoded
    "pdf/{jobname}.pdf" text always showed; the full absolute path for a
    \\deckoutputfolder pointing outside the project tree entirely."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)

# Matches either classic TeX-error style ("! message") or this project's
# actual style: .latexmkrc passes -file-line-error unconditionally, which
# reformats *every* TeX-level error (including ones that would otherwise
# start with "!") as "<file>:<line>: message" instead -- confirmed
# directly (a real compile with two genuine "Undefined control sequence"
# errors produced zero lines starting with "!", so the old pattern alone
# silently passed a broken compile as long as a PDF still got emitted,
# which nonstopmode mode almost always allows). Keeping the "^!"
# alternative too rather than replacing it: harmless belt-and-suspenders
# in case some other invocation path (e.g. a hand-run compile without
# -file-line-error) ever produces the classic format instead.
FATAL_ERROR_RE = re.compile(r"^!|^\S.*:[0-9]+: ", re.MULTILINE)

LogCallback = Callable[[str], None]


class CancelToken:
    """Cross-thread stop signal for a batch of jobs, created fresh per
    compile run. The GUI's "Stop creation" button calls request_stop();
    run_jobs() checks is_set() between jobs to skip whatever's still queued,
    and run_job() registers its live Popen here so request_stop() can kill
    it immediately rather than waiting for the current job to finish on its
    own. Killing the registered process alone (proc.kill()) would only kill
    latexmk's own launcher -- it shells out to perl, which shells out to
    lualatex/biber in turn -- so request_stop() uses `taskkill /T` to kill
    the whole process tree instead, the same way CREATE_NO_WINDOW elsewhere
    in this module already treats latexmk as a Windows-only subprocess
    tree."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    def is_set(self) -> bool:
        return self._event.is_set()

    def _set_process(self, proc: Optional[subprocess.Popen]) -> None:
        with self._lock:
            self._proc = proc

    def request_stop(self) -> None:
        self._event.set()
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.kill()


@dataclass
class CompileJob:
    deck: Deck
    version: Optional[str]     # "instructor" / "during-course" / "after-course",
                                # or None for a deck with no version support
    chapter: Optional[Chapter]  # None = whole deck
    # Whether the footer shows \gothamCompileTimestamp -- True (the shared
    # preamble's own default) unless the GUI's "Footer timestamp" checkbox
    # was unticked for this batch. A deck can still hardcode
    # \gothamShowCompileTimestampfalse/true in its own preamble (as
    # t-Uni-IA2-2026w.tex does temporarily, for its front-to-back render/diff
    # final check) -- that runs *after* this override is read, so it always
    # wins over whatever this checkbox says.
    footer_timestamp: bool = True
    # A separate "Presenter" output (never a toggle on the plain instructor
    # PDF) -- beamer's own \setbeameroption{show notes on second screen}
    # dual-screen mechanism, so \note{} content (already authored
    # throughout this project) reaches a presenter-view app like pympress
    # instead of sitting unused. Always paired with instructor-version
    # content by whoever builds this job (qt_deck_table.py's own
    # DeckRow.build_jobs()) regardless of self.version's own value --
    # never on its own a reason to change what version means here.
    presenter: bool = False
    # SlideMage's "Generate appendix TOC" checkbox -- set uniformly on
    # every job a compile batch builds (qt_gui.py's _compile_rows(), same
    # pattern as footer_timestamp), but _wrapper_text() below only actually
    # generates the appendix for an instructor-equivalent, whole-deck job
    # (job.version in (None, "instructor") and job.chapter is None) --
    # silently a no-op on a during-course/after-course or per-chapter job
    # even with this set, per the feature's own scope decision (appendix
    # jobname suffix, but no appendix content, on those).
    appendix_toc: bool = False

    @property
    def _appendix_applies(self) -> bool:
        """Whether appendix_toc actually generates content for *this* job
        -- an instructor-equivalent, whole-deck compile only (see
        appendix_toc field's own comment). Shared by jobname and
        _wrapper_text() below so a during-course/after-course/per-chapter
        job's filename never claims an appendix it doesn't have."""
        return self.appendix_toc and self.chapter is None and self.version in (None, "instructor")

    @property
    def jobname(self) -> str:
        parts = [self.deck.name]
        if self.version:
            parts.append(self.version)
        if self.chapter is not None:
            parts.append(f"{self.chapter.order:02d}-{self.chapter.slug}")
        if self.presenter:
            parts.append("presenter")
        if self._appendix_applies:
            parts.append("appendix")
        return "-".join(parts)


def _find_git_perl_bin() -> Optional[Path]:
    """Locate the usr\\bin\\ folder bundled with Git for Windows, which
    holds the only perl.exe MiKTeX's latexmk.exe has ever found on this
    project's machines (see README.md's "Compiling without TeXstudio"
    section) -- not on PATH by default, so latexmk fails with "MiKTeX
    could not find the script engine 'perl'" without this. Walks every
    ancestor of whichever git.exe is on PATH, since that ancestor's own
    depth varies (e.g. .../Git/cmd/git.exe vs .../Git/mingw64/bin/git.exe
    are a different number of levels above the shared .../Git/usr/bin/)."""
    git_exe = shutil.which("git")
    if not git_exe:
        return None
    git_path = Path(git_exe).resolve()
    for ancestor in git_path.parents:
        candidate = ancestor / "usr" / "bin"
        if (candidate / "perl.exe").exists():
            return candidate
    return None


def _build_env() -> dict:
    env = os.environ.copy()
    perl_bin = _find_git_perl_bin()
    if perl_bin is not None:
        env["PATH"] = str(perl_bin) + os.pathsep + env.get("PATH", "")
    return env


def _wrapper_text(job: CompileJob) -> str:
    lines: list[str] = []
    if job.version:
        lines.append(f"\\def\\deckversionoverride{{{job.version}}}")
    if not job.footer_timestamp:
        lines.append("\\def\\gothamFooterTimestampOverride{0}")
    if job.presenter:
        lines.append("\\def\\gothamPresenterModeOverride{1}")
    if job._appendix_applies:
        lines.append("\\def\\gothamAppendixTocOverride{1}")

    if job.chapter is not None:
        lines.append(job.deck.preamble_text)
        lines.append("")
        lines.append(job.deck.chapter_text(job.chapter))
        lines.append("")
        lines.append("\\end{document}")
    elif job._appendix_applies:
        # Same "copy preamble, inline the body" trick as the per-chapter
        # branch above, needed here for a different reason: the generated
        # appendix has to land *before* the deck's own literal
        # \end{document} -- a plain \input{deck.tex} would hit that
        # \end{document} and stop before anything appended after the
        # \input{} line ever ran.
        body = job.deck.text[job.deck.preamble_end :]
        end_match = DOCUMENT_END_RE.search(body)
        body_without_end = body[: end_match.start()] if end_match else body
        template = slide_snapshot.detect_template(job.deck.preamble_text)
        lines.append(job.deck.preamble_text)
        lines.append(body_without_end)
        lines.append(appendix_toc.generate_appendix_tex(job.deck, template))
        lines.append("\\end{document}")
    else:
        lines.append(f"\\input{{{job.deck.path.name}}}")

    return "\n".join(lines) + "\n"


def _relocate_pdf(pdf_source: Path, dest_pdf: Path) -> None:
    """Copy the freshly compiled PDF into pdf/, replacing whatever's there.
    The .build/ copy is left in place -- run_job's own aux-file cleanup
    deletes it afterward as part of jobname.* housekeeping, not this
    function; that delete targets a fresh local file, not a cloud
    placeholder, so it isn't the same risk this function itself guards
    against.

    A single os.replace() -- confirmed directly (2026-07-28) to avoid the
    standalone-delete stall described below -- was tried first and is
    documented in git history, but a *second* stall recurred later (same
    symptom: three real compile jobs, no exception, "*** FAIL ... couldn't
    move") even with os.replace() in place and confirmed to be the
    running code (process start time vs. fix commit time both checked). A
    direct reproduction of os.replace() against the exact stuck files
    succeeded in milliseconds each time, meaning os.replace() itself isn't
    unreliable in general -- something about the moment run_job calls it
    (mid-batch, PDF just written, whatever else the cloud client/AV/other
    process was doing right then) is what actually triggers the stall, and
    that couldn't be pinned down further. Switching the operation itself
    from a move to a copy (shutil.copy2) is a strictly gentler ask of
    whatever's intercepting these calls -- it doesn't require the
    destination's identity to change hands the way a move/replace does --
    and was explicitly requested as the next thing to try over chasing the
    exact trigger further given the cost of that investigation and the
    small cost of just leaving a redundant copy in .build/.

    dest_pdf's existing content (if any) is a genuine cloud-provider
    reparse point (confirmed via `Get-Item -Force`/`fsutil reparsepoint
    query`, tagged Microsoft Cloud Files API) -- shutil.copy2 opens it for
    writing rather than deleting-then-recreating it, which is the same
    property that made os.replace() an improvement over the original
    unlink()-then-move() two-step in the first place.
    """
    shutil.copy2(str(pdf_source), str(dest_pdf))


RelocatedCallback = Callable[[bool, Path], None]


def _relocate_pdf_and_finish(
    pdf_source: Path, dest_pdf: Path, jobname: str, deck_dir: Path, job: CompileJob,
    log: LogCallback, cancel: Optional["CancelToken"] = None,
    on_relocated: Optional[RelocatedCallback] = None,
) -> None:
    """Move the compiled PDF into place, retrying every
    PDF_MOVE_RETRY_INTERVAL_SECONDS for up to PDF_MOVE_RETRY_TOTAL_SECONDS,
    entirely on its own detached daemon thread -- run_job() fires this and
    returns immediately without waiting for it, so a stuck sync client on
    one job's PDF no longer blocks the next job, the rest of the app, or
    `self.compiling` (see run_job's own comment on why that matters).

    Runs everything that used to happen synchronously right after a
    successful move -- synctex/aux cleanup, the slide preview snapshot
    refresh, and the final PASS/FAIL log line -- since all of it is
    contingent on the move actually succeeding, whenever that turns out to
    be.

    `on_relocated`, if given, is called exactly once, from whichever thread
    happens to finish this function -- (True, dest_pdf) once the move has
    actually landed, or (False, dest_pdf) on every give-up path (stopped by
    the user, or the retry budget ran out). A caller that itself needs the
    PDF right after compiling (pptx_export -- see qt_gui.py's
    _export_pptx_bg) has no other reliable way to know the move (dispatched
    onto this function's own background thread by run_job(), which returns
    immediately without waiting for it) has actually finished, rather than
    racing its own aux-file cleanup below, which deletes the .build/ copy
    run_job() itself just told the caller succeeded (2026-09-28, porting
    SlideMage upstream commit 34cdbd7).

    **Why retrying is safe even though a single attempt can hang
    indefinitely** (confirmed directly, see git history: a real run
    stalled forever right after logging that it was about to move the PDF,
    *no exception ever raised* -- likely a cloud-sync client's
    placeholder-file mechanism doing a synchronous network round-trip
    *inside* the OS call itself, not a plain sharing-violation that would
    fail fast). Python cannot forcibly kill a thread stuck inside a
    blocking OS call, so a hung attempt is simply abandoned, not stopped --
    which means a "retry every 10 seconds" loop must fire a *new* attempt
    on its own fresh thread each time regardless of whether earlier
    attempts ever returned, rather than waiting for one to finish first.
    That is safe specifically *because* every attempt copies the exact
    same already-compiled `pdf_source` to the same `dest_pdf`: even if two
    or more attempts end up writing around the same time, they are writing
    identical bytes from an identical, unchanging source -- not two
    different pieces of content racing. The first attempt to actually
    complete wins; any others still in flight are simply abandoned same as
    a single hung attempt always was.
    """
    started = time.monotonic()
    done = threading.Event()
    succeeded = threading.Event()
    attempt_count = 0
    lock = threading.Lock()

    def _attempt(n: int) -> None:
        try:
            _relocate_pdf(pdf_source, dest_pdf)
            # shutil.copy2() raising nothing is not proof the copy actually
            # landed -- a cloud-sync client intercepting the write (see
            # _relocate_pdf's own docstring) can return normally after
            # writing a truncated or empty file, and this process being
            # killed mid-attempt (GUI closed while a retry was in flight,
            # confirmed to happen: 2026-08-20, a #workdeck compile left
            # exactly a 0-byte pdf/#workdeck-instructor.pdf with no FAIL
            # ever logged and no .build/ leftovers to recover from, right
            # around an app relaunch) leaves whatever partial bytes had
            # been written at that instant, not zero -- so this checks the
            # one thing that's actually verifiable without re-reading the
            # whole file: the byte count matches the known-good source.
            if dest_pdf.stat().st_size != pdf_source.stat().st_size:
                raise OSError(
                    f"copied {dest_pdf.stat().st_size} of "
                    f"{pdf_source.stat().st_size} bytes"
                )
        except Exception:
            return  # a later attempt (or this one, eventually) may still land
        with lock:
            if not done.is_set():
                succeeded.set()
                done.set()

    while not done.is_set():
        elapsed = time.monotonic() - started
        if elapsed >= PDF_MOVE_RETRY_TOTAL_SECONDS:
            break
        if cancel is not None and cancel.is_set():
            log(f"*** FAIL: {jobname} -- stopped by user while relocating the "
               f"PDF; left at .build/{jobname}.pdf for manual recovery ***")
            if on_relocated is not None:
                on_relocated(False, dest_pdf)
            return
        attempt_count += 1
        threading.Thread(target=_attempt, args=(attempt_count,), daemon=True).start()
        if attempt_count == 1:
            log(f"    (moving {jobname}.pdf into pdf/ -- this can take a "
               f"moment if a sync client is still indexing it)")
        elif attempt_count % 6 == 0:  # roughly once a minute at the default interval
            log(f"    (still trying to move {jobname}.pdf into pdf/, "
               f"{elapsed / 60:.0f} min so far -- retrying up to "
               f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min total)")
        done.wait(PDF_MOVE_RETRY_INTERVAL_SECONDS)

    if not succeeded.is_set():
        log(f"*** FAIL: {jobname} -- couldn't move PDF into pdf/ after "
           f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min; left at "
           f".build/{jobname}.pdf for manual recovery ***")
        if on_relocated is not None:
            on_relocated(False, dest_pdf)
        return

    # pdf/ holds only the PDF -- .synctex.gz (wherever it landed) is just
    # discarded, not copied there.
    (deck_dir / f"{jobname}.synctex.gz").unlink(missing_ok=True)

    for aux in BUILD_DIR.glob(f"{jobname}.*"):
        aux.unlink(missing_ok=True)

    # Refresh every slide's compile-time PNG snapshot (slide_snapshot.py)
    # from this deck's pages in one pass, but only for an instructor (or
    # version-less) compile -- a during-course/after-course PDF has
    # partial content and would overwrite the canonical snapshot with it.
    # A presenter compile is instructor-version content too, but its own
    # page structure (every real slide paired with a facing notes page,
    # via beamer's own show-notes-on-second-screen layout) has nothing to
    # do with a normal one-page-per-slide compile, so reading it the usual
    # way would misread or skip pages and corrupt the real preview cache
    # with it -- excluded outright, not just "happens not to match" by
    # accident. Never lets a snapshot failure fail an otherwise-successful
    # compile.
    if job.version in (None, "instructor") and not job.presenter:
        try:
            template = slide_snapshot.detect_template(job.deck.preamble_text)
            n = slide_snapshot.capture_deck(dest_pdf, template)
            if n:
                log(f"    (refreshed {n} slide preview snapshot(s), "
                   f"{slide_snapshot.TEMPLATES[template]})")
        except Exception as exc:
            log(f"    (preview snapshots not updated: {exc})")

    elapsed = time.monotonic() - started
    suffix = f" (after {elapsed:.0f}s)" if elapsed >= 5 else ""
    log(f"==== PASS: {jobname} -> {_display_path(dest_pdf)}{suffix} ====")
    if on_relocated is not None:
        on_relocated(True, dest_pdf)


def run_job(
    job: CompileJob, log: LogCallback, cancel: Optional[CancelToken] = None,
    on_relocated: Optional[RelocatedCallback] = None,
    dest_override: Optional[Path] = None,
) -> bool:
    """Compile one job. Returns True once the LaTeX compile itself
    succeeded -- *not* once the PDF has actually landed in pdf/. `log`
    receives one string per line of progress/output, for a GUI (or the
    console) to display. `cancel`, if given, registers the live subprocess
    so a "Stop creation" request can kill it immediately (see
    CancelToken). `on_relocated`, if given, is threaded straight through to
    _relocate_pdf_and_finish() (see that function's own docstring) -- a
    caller that needs to know once the PDF has actually landed at its final
    destination, not just that the compile itself succeeded. `dest_override`,
    if given, is used as this job's actual output destination in place of
    resolve_output_location(job)'s own result -- run_jobs()'s own
    _disambiguated_destinations() is the only caller that sets this, to
    keep two jobs in the same batch from silently overwriting each other's
    PDF when their own \\deckoutputfolder declarations resolve to the exact
    same file.

    The move into pdf/ is dispatched to its own detached background thread
    (_relocate_pdf_and_finish) and this function does not wait for it.
    That used to be a synchronous, bounded wait right here -- fine when a
    sync client released its lock within a minute, but when it didn't
    (confirmed to happen on real compiles), that wait held up not just this
    job but every job queued after it, and kept `self.compiling` true (so
    the GUI refused a new compile request) for however long the wait
    lasted. A compile succeeding is the expensive, meaningful outcome;
    whether the PDF has been copied into place yet is a separate, cheap-to-
    retry concern that has no business blocking anything else in the app.
    Its own PASS/FAIL lands in the log whenever it resolves, independently
    of this function's return.
    """
    deck_dir = job.deck.path.parent
    jobname = job.jobname
    wrapper_path = deck_dir / f"_slidemage_{jobname}.tex"

    log(f"==== Compiling {job.deck.name} -> {jobname} ====")
    # newline="" -- same reasoning as deck_scan.py's own _scan_dir() read and
    # every other writer of an already-CRLF string in this project:
    # write_text()'s universal-newlines default would otherwise translate
    # every bare "\n" _wrapper_text() emits into "\r\n" *again* on top of any
    # "\r\n" already embedded in job.deck.preamble_text/chapter_text() (the
    # per-chapter and appendix branches splice the deck's own raw CRLF text
    # in verbatim), doubling those lines' line endings to "\r\r\n" in the
    # wrapper file that's actually compiled (2026-09-28, porting SlideMage
    # upstream commit 34cdbd7).
    with open(wrapper_path, "w", encoding="utf-8", newline="") as f:
        f.write(_wrapper_text(job))

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    # Stale timestamp/aux from a previous attempt at this exact jobname
    # would otherwise make a fresh run's success check read old state.
    for stale in BUILD_DIR.glob(f"{jobname}.*"):
        stale.unlink(missing_ok=True)

    rel_wrapper = wrapper_path.relative_to(PROJECT_ROOT)
    # .latexmkrc (shared with compile-all.bat/compile-all-versions.bat,
    # not touched here) leaves $out_dir at its post-$do_cd default -- the
    # deck's own directory -- so its own final step copies/renames the
    # finished PDF there from $aux_dir (.build/). That rename is exactly
    # where a real run stalled forever: this project lives under
    # D:\uniCLOUD\..., almost certainly a cloud-sync client's watched tree,
    # and a sync client can hold a lock on a freshly-written ~90MB PDF (for
    # hashing/upload) far longer than a PDF viewer would -- long enough that
    # latexmk's own internal retry around the rename never returns control
    # to this process at all (confirmed directly: no further log output,
    # ever, right after latexmk logged the rename's "Device or resource
    # busy"). Passing -outdir here (CLI beats the rc file) makes $out_dir
    # equal to $aux_dir for *this* invocation only -- latexmk then has
    # nothing to copy back, so that whole rename (and its failure mode)
    # never happens. Only compiler.py's own invocations get this; the .bat
    # scripts' reliance on the PDF landing next to the source is untouched.
    cmd = [
        "latexmk", "-f", f"-jobname={jobname}", f"-outdir={BUILD_DIR.as_posix()}",
        str(rel_wrapper),
    ]
    env = _build_env()

    # SlideMage.bat launches the GUI with no console of its own (that's
    # the whole point -- a normal-looking app window, not a terminal), so
    # without this, Windows pops up a brand-new console window for latexmk
    # (and everything it shells out to in turn -- perl, lualatex, biber)
    # each time, floating on top of the GUI -- confirmed directly as the
    # "inelegant" behavior this suppresses. CREATE_NO_WINDOW only exists on
    # Windows; this project is Windows-only already (MiKTeX, drive-letter
    # paths throughout), but guarded anyway rather than assumed.
    popen_kwargs: dict = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **popen_kwargs,
        )
        if cancel is not None:
            cancel._set_process(proc)
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip("\n"))
        proc.wait()
    except FileNotFoundError:
        log("*** latexmk not found on PATH -- is a TeX distribution installed? ***")
        wrapper_path.unlink(missing_ok=True)
        return False
    finally:
        if cancel is not None:
            cancel._set_process(None)

    if cancel is not None and cancel.is_set():
        # Killed mid-compile -- the log/PDF on disk reflect a truncated run,
        # not a real pass or fail, so report this as its own outcome rather
        # than letting the usual FATAL_ERROR_RE/PDF-existence check below
        # potentially call it a pass off of stale leftovers.
        log(f"*** FAIL: {jobname} -- stopped by user ***")
        wrapper_path.unlink(missing_ok=True)
        return False

    log_path = BUILD_DIR / f"{jobname}.log"
    # With -outdir=BUILD_DIR above, latexmk writes the PDF straight into
    # .build/ and never touches deck_dir at all -- deck_dir is checked
    # first purely as a defensive fallback (e.g. a stray file left over
    # from before this fix, or a future .latexmkrc change), not because
    # latexmk is expected to put anything there going forward.
    pdf_path = deck_dir / f"{jobname}.pdf"
    fallback_pdf_path = BUILD_DIR / f"{jobname}.pdf"
    pdf_source = pdf_path if pdf_path.exists() else (
        fallback_pdf_path if fallback_pdf_path.exists() else None
    )

    # A 0-byte (or otherwise truncated) PDF counts as no PDF at all --
    # existence alone isn't proof latexmk actually finished writing it
    # (e.g. the whole app getting closed/killed mid-compile leaves exactly
    # this: a stub file some writer already created, no fatal "!" line in
    # an otherwise-truncated log). Without this, that reads as a pass and
    # gets handed to _relocate_pdf_and_finish, which copies the truncated
    # file over into pdf/ same as a real one.
    ok = pdf_source is not None and pdf_source.stat().st_size > 0
    if ok and log_path.exists():
        if FATAL_ERROR_RE.search(log_path.read_text(encoding="utf-8", errors="replace")):
            ok = False
    elif not log_path.exists():
        ok = False

    if ok:
        if dest_override is not None:
            dest_pdf = dest_override
        else:
            output_dir, output_stem = resolve_output_location(job)
            dest_pdf = output_dir / f"{output_stem}.pdf"
        dest_pdf.parent.mkdir(parents=True, exist_ok=True)
        # "==== MOVING: {jobname} -> <dest> ====" is a fixed prefix
        # qt_gui.py's MOVING_LOG_RE parses to drive this job's per-row
        # status badge -- that regex only anchors on "^==== MOVING: (\S+)
        # ->", never on what follows, so the destination text itself can
        # safely show wherever this job's own \deckoutputfolder (or the
        # PDF_DIR default) actually points.
        dest_display = _display_path(dest_pdf)
        log(f"==== MOVING: {jobname} -> {dest_display} ==== "
           f"(now backgrounded -- retrying for up to "
           f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min if needed, "
           f"no longer blocking the rest of the queue)")
        threading.Thread(
            target=_relocate_pdf_and_finish,
            args=(pdf_source, dest_pdf, jobname, deck_dir, job, log, cancel),
            kwargs={"on_relocated": on_relocated},
            daemon=True,
        ).start()
    else:
        log(f"*** FAIL: {jobname} -- see {log_path} ***")

    wrapper_path.unlink(missing_ok=True)
    return ok


def _disambiguated_destinations(
    jobs: list[CompileJob], log: LogCallback
) -> dict[str, Path]:
    """Every job's own resolve_output_location() destination, with a
    same-batch collision broken by appending the colliding jobs' own
    jobnames to their filename.

    Concretely reachable, not just theoretical: resolve_output_location()
    ignores job.jobname entirely and returns a \\deckoutputfolder's own
    literal filename's stem whenever that declaration names an exact file
    rather than a bare folder (see that function's own docstring) -- a
    deck declaring e.g. "\\deckoutputfolder[instructor]{D:/Teaching/IA2/
    Slides.pdf}" and then compiled as several per-chapter jobs (or a
    per-chapter job alongside the whole deck) in the same batch would
    otherwise have every one of those jobs resolve to that exact same
    dest_pdf, each one silently overwriting whichever of the others
    finished moving its PDF into place first (2026-09-28, porting SlideMage
    upstream commit 34cdbd7; IA2's own real \\deckoutputfolder declarations
    plus its per-chapter compiles make this a real, not just hypothetical,
    same-batch collision).

    Logs one line per job renamed this way, so the departure from the
    deck's own declared filename is never silent."""
    dests: dict[str, Path] = {}
    seen_dest: dict[Path, list[str]] = {}
    for job in jobs:
        output_dir, output_stem = resolve_output_location(job)
        dest = output_dir / f"{output_stem}.pdf"
        dests[job.jobname] = dest
        seen_dest.setdefault(dest, []).append(job.jobname)
    for dest, jobnames in seen_dest.items():
        if len(jobnames) < 2:
            continue
        for jobname in jobnames:
            disambiguated = dest.with_name(f"{dest.stem}-{jobname}{dest.suffix}")
            dests[jobname] = disambiguated
            log(f"    (note: {jobname} would share {_display_path(dest)} with "
               f"{len(jobnames) - 1} other job(s) in this run -- writing to "
               f"{_display_path(disambiguated)} instead)")
    return dests


def run_jobs(
    jobs: list[CompileJob], log: LogCallback, cancel: Optional[CancelToken] = None
) -> dict[str, bool]:
    """Run every job in order; one failure doesn't stop the rest. Returns
    {jobname: success} for a summary. If `cancel` is set partway through
    (the GUI's "Stop creation" button), the job in progress is killed
    (see run_job) and whatever's still queued is skipped rather than
    started."""
    dest_overrides = _disambiguated_destinations(jobs, log)
    results: dict[str, bool] = {}
    for job in jobs:
        if cancel is not None and cancel.is_set():
            skipped = len(jobs) - len(results)
            log(f"==== Stopped: {skipped} job(s) skipped ====")
            break
        results[job.jobname] = run_job(
            job, log, cancel=cancel, dest_override=dest_overrides.get(job.jobname)
        )
    return results
