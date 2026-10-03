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
scanning the current invocation's .build/<jobname>-<id>/<jobname>.log for
LaTeX errors plus checking that invocation's PDF, never by latexmk's exit code:
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
import uuid
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
from .deck_scan import DOCUMENT_END_RE, GROUP_TAGS, PROJECT_ROOT, Chapter, Deck

BUILD_DIR = PROJECT_ROOT / ".build"
PDF_DIR = PROJECT_ROOT / "pdf"

_BUILD_STATE_LOCK = threading.Lock()
_ACTIVE_BUILD_DIRS: set[Path] = set()
_DESTINATION_STATE_LOCK = threading.Lock()
_DESTINATION_NEXT_GENERATION: dict[str, int] = {}
_DESTINATION_LATEST_SUCCESS: dict[str, int] = {}
_DESTINATION_PUBLISH_LOCKS: dict[str, threading.Lock] = {}


def _destination_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _register_output(path: Path) -> tuple[str, int]:
    key = _destination_key(path)
    with _DESTINATION_STATE_LOCK:
        generation = _DESTINATION_NEXT_GENERATION.get(key, 0) + 1
        _DESTINATION_NEXT_GENERATION[key] = generation
    return key, generation


def _mark_output_success(key: str, generation: int) -> bool:
    """Record a compiled invocation unless a later invocation already won."""
    with _DESTINATION_STATE_LOCK:
        latest = _DESTINATION_LATEST_SUCCESS.get(key, 0)
        if generation < latest:
            return False
        _DESTINATION_LATEST_SUCCESS[key] = generation
        return True


def _is_latest_output_success(key: str, generation: int) -> bool:
    with _DESTINATION_STATE_LOCK:
        return _DESTINATION_LATEST_SUCCESS.get(key, 0) == generation


def _destination_publish_lock(key: str) -> threading.Lock:
    with _DESTINATION_STATE_LOCK:
        return _DESTINATION_PUBLISH_LOCKS.setdefault(key, threading.Lock())


def _set_build_dir_active(path: Path, active: bool) -> None:
    with _BUILD_STATE_LOCK:
        if active:
            _ACTIVE_BUILD_DIRS.add(path)
        else:
            _ACTIVE_BUILD_DIRS.discard(path)


def removable_build_entries() -> list[Path]:
    """Immediate .build children safe for the GUI's temporary-file cleanup.

    Per-invocation directories remain excluded while latexmk or any PDF copy
    attempt can still read them. Root-level legacy build files are included
    for compatibility with older runs and slide previews.
    """
    with _BUILD_STATE_LOCK:
        if not BUILD_DIR.is_dir():
            return []
        return sorted(
            (entry for entry in BUILD_DIR.iterdir() if entry not in _ACTIVE_BUILD_DIRS),
            key=lambda entry: entry.name,
        )


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
    just a folder) ... use that filename for the generated file". That
    literal filename can be the fallback for more than one distinct job in
    the same batch (every chapter of a per-chapter compile; a presenter
    job with no [presenter]-specific line of its own; every version
    sharing one bare, unqualified \\deckoutputfolder{...}) -- see
    run_jobs()'s own collision check for what happens then; this function
    always returns the literal name as declared, uninvolved in that."""
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
    # Whether the footer shows \SMCompileTimestamp -- True (the shared
    # preamble's own default) unless the GUI's "Footer timestamp" checkbox
    # was unticked for this batch. A deck can still hardcode
    # \SMShowCompileTimestampfalse/true in its own preamble (as
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
    # generates the appendix for a whole-deck job (job.chapter is None) --
    # of any version since 2026-10-03 (direct instruction; it used to be
    # the instructor/presenter compiles only). A per-chapter job stays
    # without one, even with this set: its PDF holds one chapter, and an
    # appendix of the whole deck's slides would link to slides that aren't
    # in it.
    appendix_toc: bool = False

    @property
    def _appendix_applies(self) -> bool:
        """Whether appendix_toc actually generates content for *this* job
        -- a whole-deck compile (see appendix_toc field's own comment).
        Shared by jobname and _wrapper_text() below so a per-chapter job's
        filename never claims an appendix it doesn't have."""
        return self.appendix_toc and self.chapter is None

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
        lines.append("\\def\\SMFooterTimestampOverride{0}")
    if job.presenter:
        lines.append("\\def\\SMPresenterModeOverride{1}")
    if job._appendix_applies:
        lines.append("\\def\\SMAppendixTocOverride{1}")

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
        lines.append(appendix_toc.generate_appendix_tex(
            job.deck, template, job.version or "instructor"))
        lines.append("\\end{document}")
    else:
        lines.append(f"\\input{{{job.deck.path.name}}}")

    return "\n".join(lines) + "\n"


def _relocate_pdf(
    pdf_source: Path, dest_pdf: Path, destination_key: str, generation: int,
) -> bool:
    """Stage a copy beside the output and publish only the latest compile."""
    staged_pdf = dest_pdf.with_name(
        f".{dest_pdf.name}.slidemage-{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(str(pdf_source), str(staged_pdf))
        source_size = pdf_source.stat().st_size
        if staged_pdf.stat().st_size != source_size:
            raise OSError(
                f"copied {staged_pdf.stat().st_size} of {source_size} bytes"
            )
        publish_lock = _destination_publish_lock(destination_key)
        with publish_lock:
            if not _is_latest_output_success(destination_key, generation):
                return False
            os.replace(staged_pdf, dest_pdf)
            if dest_pdf.stat().st_size != source_size:
                raise OSError(
                    f"published {dest_pdf.stat().st_size} of {source_size} bytes"
                )
        return True
    finally:
        staged_pdf.unlink(missing_ok=True)


def _release_build_dir_after_attempts(
    build_dir: Path, attempts_drained: threading.Event, remove: bool,
) -> None:
    """Keep a compile source immutable until every retry worker has stopped."""
    def release() -> None:
        attempts_drained.wait()
        if remove:
            shutil.rmtree(build_dir, ignore_errors=True)
        _set_build_dir_active(build_dir, False)

    if attempts_drained.is_set():
        release()
    else:
        threading.Thread(target=release, daemon=True).start()


def _relocate_pdf_and_finish(
    pdf_source: Path, dest_pdf: Path, jobname: str, job: CompileJob,
    log: LogCallback, cancel: Optional["CancelToken"] = None,
    on_relocated: Optional[Callable[[bool, Path], None]] = None,
    *, build_dir: Path, destination_key: str, generation: int,
) -> None:
    """Retry publication of one immutable invocation PDF in the background."""
    started = time.monotonic()
    done = threading.Event()
    succeeded = threading.Event()
    superseded = threading.Event()
    attempts_drained = threading.Event()
    attempts_drained.set()
    attempts_lock = threading.Lock()
    pending_attempts = 0
    attempt_count = 0

    def _attempt() -> None:
        nonlocal pending_attempts
        try:
            if not _relocate_pdf(pdf_source, dest_pdf, destination_key, generation):
                superseded.set()
                done.set()
                return
            succeeded.set()
            done.set()
        except Exception:
            # Another retry may still land; keep the source immutable while
            # this attempt remains alive, even if it stalls inside the OS.
            return
        finally:
            with attempts_lock:
                pending_attempts -= 1
                if pending_attempts == 0:
                    attempts_drained.set()

    while not done.is_set():
        elapsed = time.monotonic() - started
        if elapsed >= PDF_MOVE_RETRY_TOTAL_SECONDS:
            break
        if cancel is not None and cancel.is_set():
            source_display = _display_path(pdf_source)
            log(f"*** FAIL: {jobname} -- stopped by user while relocating the "
               f"PDF; left at {source_display} for manual recovery ***")
            if on_relocated is not None:
                on_relocated(False, dest_pdf)
            _release_build_dir_after_attempts(build_dir, attempts_drained, remove=False)
            return

        attempt_count += 1
        with attempts_lock:
            pending_attempts += 1
            attempts_drained.clear()
        worker = threading.Thread(target=_attempt, daemon=True)
        try:
            worker.start()
        except Exception:
            with attempts_lock:
                pending_attempts -= 1
                if pending_attempts == 0:
                    attempts_drained.set()
            raise
        if attempt_count == 1:
            log(f"    (moving {jobname}.pdf into {_display_path(dest_pdf)} -- "
               "this can take a moment if a sync client is still indexing it)")
        elif attempt_count % 6 == 0:
            log(f"    (still trying to publish {jobname}.pdf, "
                f"{elapsed / 60:.0f} min so far -- retrying up to "
                f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min total)")
        done.wait(PDF_MOVE_RETRY_INTERVAL_SECONDS)

    if superseded.is_set() and not succeeded.is_set():
        log(f"*** FAIL: {jobname} -- output superseded by a newer successful "
            "compile; this PDF was not published ***")
        if on_relocated is not None:
            on_relocated(False, dest_pdf)
        _release_build_dir_after_attempts(build_dir, attempts_drained, remove=True)
        return

    if not succeeded.is_set():
        source_display = _display_path(pdf_source)
        log(f"*** FAIL: {jobname} -- couldn't publish PDF into "
            f"{_display_path(dest_pdf)} after "
            f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min; left at "
            f"{source_display} for manual recovery ***")
        if on_relocated is not None:
            on_relocated(False, dest_pdf)
        _release_build_dir_after_attempts(build_dir, attempts_drained, remove=False)
        return

    # Refresh slide snapshots only from this invocation's immutable source,
    # and only if no newer successful compile has replaced it as current.
    if (job.version in (None, "instructor") and not job.presenter
            and _is_latest_output_success(destination_key, generation)):
        try:
            template = slide_snapshot.detect_template(job.deck.preamble_text)
            n = slide_snapshot.capture_deck(pdf_source, template)
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
    _release_build_dir_after_attempts(build_dir, attempts_drained, remove=True)


def run_job(
    job: CompileJob, log: LogCallback, cancel: Optional[CancelToken] = None,
    dest_override: Optional[tuple[Path, str]] = None,
    on_relocated: Optional[Callable[[bool, Path], None]] = None,
) -> bool:
    """Compile one job and background publication of its invocation PDF.

    Job names and callbacks stay stable for the GUI. Each invocation gets a
    private wrapper and latexmk output directory so a retry worker from an
    older run can never read or clean files created by a newer one.
    """
    deck_dir = job.deck.path.parent
    jobname = job.jobname
    invocation_id = uuid.uuid4().hex
    wrapper_path = deck_dir / f"_slidemage_{jobname}_{invocation_id}.tex"
    build_dir = BUILD_DIR / f"{jobname}-{invocation_id}"
    output_dir, output_stem = (
        dest_override if dest_override is not None else resolve_output_location(job)
    )
    dest_pdf = output_dir / f"{output_stem}.pdf"
    destination_key, generation = _register_output(dest_pdf)
    _set_build_dir_active(build_dir, True)
    relocation_started = False

    log(f"==== Compiling {job.deck.name} -> {jobname} ====")
    try:
        # Preserve the deck's literal line endings when its preamble or body
        # is spliced into a chapter/appendix wrapper.
        wrapper_path.write_text(_wrapper_text(job), encoding="utf-8", newline="")
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        build_dir.mkdir(parents=True, exist_ok=False)

        rel_wrapper = wrapper_path.relative_to(PROJECT_ROOT)
        isolated_output = build_dir.resolve().as_posix()
        cmd = [
            "latexmk", "-f", f"-jobname={jobname}",
            f"-auxdir={isolated_output}", f"-outdir={isolated_output}",
            str(rel_wrapper),
        ]
        env = _build_env()
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
            return False
        finally:
            if cancel is not None:
                cancel._set_process(None)

        if cancel is not None and cancel.is_set():
            log(f"*** FAIL: {jobname} -- stopped by user ***")
            return False

        log_path = build_dir / f"{jobname}.log"
        # The configured output path is private to this invocation; there is
        # no deck-directory or prior-build fallback that can pass as fresh.
        pdf_source = build_dir / f"{jobname}.pdf"
        ok = pdf_source.is_file() and pdf_source.stat().st_size > 0
        if ok and log_path.exists():
            if FATAL_ERROR_RE.search(
                log_path.read_text(encoding="utf-8", errors="replace")
            ):
                ok = False
        elif not log_path.exists():
            ok = False

        if not ok:
            log(f"*** FAIL: {jobname} -- see {log_path} ***")
            if on_relocated is not None:
                on_relocated(False, pdf_source)
            return False

        output_dir.mkdir(parents=True, exist_ok=True)
        if not _mark_output_success(destination_key, generation):
            log(f"*** FAIL: {jobname} -- output superseded by a newer successful "
                "compile; this PDF was not published ***")
            if on_relocated is not None:
                on_relocated(False, dest_pdf)
            return True

        dest_display = _display_path(dest_pdf)
        log(f"==== MOVING: {jobname} -> {dest_display} ==== "
            f"(now backgrounded -- retrying for up to "
            f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min if needed, "
            "no longer blocking the rest of the queue)")
        relocation = threading.Thread(
            target=_relocate_pdf_and_finish,
            args=(pdf_source, dest_pdf, jobname, job, log, cancel, on_relocated),
            kwargs={
                "build_dir": build_dir,
                "destination_key": destination_key,
                "generation": generation,
            },
            daemon=True,
        )
        relocation.start()
        relocation_started = True
        return True
    finally:
        wrapper_path.unlink(missing_ok=True)
        if not relocation_started:
            _set_build_dir_active(build_dir, False)


def _disambiguated_destinations(
    jobs: list[CompileJob], log: LogCallback
) -> dict[int, tuple[Path, str]]:
    """resolve_output_location(job) for every job in this batch, except
    that when two or more jobs resolve to the exact same destination file
    (a literal \\deckoutputfolder filename shared by every chapter of a
    per-chapter compile, by a presenter job with no [presenter]-specific
    line of its own, or by every version sharing one bare, unqualified
    \\deckoutputfolder{...}), each of those jobs falls back to its own
    default PDF_DIR-style job.jobname stem instead -- silently overwriting
    one job's PDF with another's is worse than not honoring the declared
    literal filename for jobs that turn out not to be unique. Keyed by
    id(job): CompileJob has no __eq__/__hash__ of its own, and two
    distinct jobs in the same batch can otherwise compare unequal only by
    identity anyway (e.g. two different chapters share every other field)."""
    dests = {id(job): resolve_output_location(job) for job in jobs}
    by_dest_pdf: dict[Path, list[CompileJob]] = {}
    for job in jobs:
        output_dir, output_stem = dests[id(job)]
        by_dest_pdf.setdefault(output_dir / f"{output_stem}.pdf", []).append(job)
    for dest_pdf, colliding in by_dest_pdf.items():
        if len(colliding) < 2:
            continue
        output_dir, _ = dests[id(colliding[0])]
        log(f"*** {dest_pdf.name}'s \\deckoutputfolder is shared by "
           f"{len(colliding)} jobs in this batch "
           f"({', '.join(j.jobname for j in colliding)}) -- "
           f"using each job's own default filename there instead of "
           f"letting them overwrite each other ***")
        for job in colliding:
            dests[id(job)] = (output_dir, job.jobname)
    return dests


def job_stage(job: CompileJob) -> int:
    """Where a job falls in a multi-job run: Presenter, Instructor,
    During-course, After-course, After-course per chapter (0..4)."""
    if job.presenter:
        return 0
    if job.chapter is not None:
        return 4
    return {"during-course": 2, "after-course": 3}.get(job.version, 1)


def order_jobs(jobs: list[CompileJob]) -> list[CompileJob]:
    """The order a batch of jobs is compiled in (2026-10-03, direct
    instruction): version by version -- Presenter, Instructor, During-course,
    After-course, After-course per chapter -- and within each version deck by
    deck, by the deck table's groups: work decks, course decks, research
    presentations, test decks. Decks of one group, and the chapters of one
    deck, stay in the order the jobs came in (the table's order): the sort is
    stable. Selecting During-course and Presenter for #workdeck and IA2
    compiles #workdeck Presenter, IA2 Presenter, #workdeck During-course,
    IA2 During-course."""
    group_rank = {tag: i for i, tag in enumerate(GROUP_TAGS)}
    return sorted(jobs, key=lambda job: (
        job_stage(job), group_rank.get(job.deck.group, len(group_rank))))


def run_jobs(
    jobs: list[CompileJob], log: LogCallback, cancel: Optional[CancelToken] = None
) -> dict[str, bool]:
    """Run every job in order; one failure doesn't stop the rest. Returns
    {jobname: success} for a summary. If `cancel` is set partway through
    (the GUI's "Stop creation" button), the job in progress is killed
    (see run_job) and whatever's still queued is skipped rather than
    started."""
    destinations = _disambiguated_destinations(jobs, log)
    results: dict[str, bool] = {}
    for job in jobs:
        if cancel is not None and cancel.is_set():
            skipped = len(jobs) - len(results)
            log(f"==== Stopped: {skipped} job(s) skipped ====")
            break
        results[job.jobname] = run_job(
            job, log, cancel=cancel, dest_override=destinations[id(job)]
        )
    return results
