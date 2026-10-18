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
import signal
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
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

from . import appendix_toc, compile_log, compile_passes, compile_records, project, slide_snapshot
from .deck_editor import VIEWS
from .deck_scan import DOCUMENT_END_RE, GROUP_ORDER, Chapter, Deck
from .processes import no_console_kwargs


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


def set_build_dir_active(path: Path, active: bool) -> None:
    with _BUILD_STATE_LOCK:
        if active:
            _ACTIVE_BUILD_DIRS.add(path)
        else:
            _ACTIVE_BUILD_DIRS.discard(path)


def removable_build_entries(ctx: project.ProjectContext) -> list[Path]:
    """Immediate .build children safe for the GUI's temporary-file cleanup.

    Per-invocation directories remain excluded while latexmk or any PDF copy
    attempt can still read them. Root-level legacy build files are included
    for compatibility with older runs and slide previews. The compile
    records (.build/compile-records/, compile_records.py) always stay
    (2026-10-08, direct instruction: "They are small and would be good to
    keep even if the user generally wants to clean up").
    """
    from .preview_build import is_active
    with _BUILD_STATE_LOCK:
        if not ctx.build_dir.is_dir():
            return []
        return sorted(
            (entry for entry in ctx.build_dir.iterdir()
             if entry not in _ACTIVE_BUILD_DIRS and not is_active(entry)
             and entry.name != compile_records.RECORDS_DIRNAME),
            key=lambda entry: entry.name,
        )


def resolve_output_location(ctx: project.ProjectContext, job: "CompileJob") -> tuple[Path, str]:
    """Where this job's compiled PDF should actually land, and what its
    filename (without ".pdf") should be: a deck-declared \\deckoutputfolder
    (deck_scan.py's OUTPUT_FOLDER_RE) directory plus job.jobname by
    default, or ctx.pdf_dir plus job.jobname if the deck has none. A
    version-less deck (job.version is None) is treated as "instructor" for
    lookup purposes, so a bare `\\deckoutputfolder[instructor]{...}` line
    works the same whether or not the deck formally supports the
    During-course/After-course version system -- same normalization
    per-chapter jobs already get for free, since their own .version is
    already "instructor"/"after-course". A relative path resolves against
    ctx.root, the same base every relative \\includegraphics path in
    this project already resolves against (confirmed: real slides
    reference e.g. "media/icon-x.png" and compile correctly with latexmk
    invoked from ctx.root).

    A presenter job (job.presenter) checks `\\deckoutputfolder[presenter]{...}`
    first, before falling back to the same instructor/bare lookup any other
    job uses -- job.version is *already* "instructor" for a presenter job
    (build_jobs() below), so without this a
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
    if project.is_snapshot(ctx.root):
        # A deck snapshot's \deckoutputfolder paths belong to the project it
        # was taken from; its PDFs stay inside the snapshot.
        return ctx.pdf_dir, job.jobname
    version_key = job.version or "instructor"
    if job.presenter:
        raw = (job.deck.output_folders.get("presenter")
                or job.deck.output_folders.get(version_key)
                or job.deck.output_folders.get(None))
    else:
        raw = job.deck.output_folders.get(version_key) or job.deck.output_folders.get(None)
    if raw is None:
        return ctx.pdf_dir, job.jobname
    path = Path(raw)
    resolved = path if path.is_absolute() else ctx.root / path
    if resolved.suffix:
        return resolved.parent, resolved.stem
    return resolved, job.jobname


@dataclass
class DeckPdf:
    """One PDF of a deck on disk (deck_pdfs())."""
    label: str              # "Instructor", "Presenter", "After-course, 2: Title", ...
    path: Path
    mtime: float
    # the PDF "Open pdf" opens by default: the deck's own choice
    # (deck.open_pdf, "%% SlideMage open PDF: ..."), else the instructor PDF
    preferred: bool
    run_id: Optional[str] = None   # its /SlideMageRun (see CompileJob.run_id)


def job_label(job: CompileJob) -> str:
    label = "Presenter" if job.presenter else {
        "during-course": "During-course", "after-course": "After-course"}.get(
        job.version or "", "Instructor")
    if job.chapter is not None:
        label += f", chapter {job.chapter.order}: {job.chapter.title}"
    if job.language:
        label += f" · {job.language.upper()}"
    return label


def _is_preferred(job: CompileJob) -> bool:
    """Whether `job` makes the PDF its deck's "Open pdf" opens by default."""
    if job.chapter is not None:
        return False
    choice = job.deck.open_pdf or "instructor"
    if choice == "presenter":
        return job.presenter
    if job.presenter:
        return False
    if choice in ("during-course", "after-course") and job.deck.supports_version:
        return job.version == choice
    return job.version in (None, "instructor")


def deck_pdfs(ctx: project.ProjectContext, deck: Deck) -> list[DeckPdf]:
    """Every PDF SlideMage has produced for `deck` that is on disk, newest
    first. Checks every output this deck could have (each version, presenter
    and per-chapter variant) at both the destination its current
    \\deckoutputfolder declarations resolve to and the default pdf/ folder --
    so a PDF compiled before an output folder was declared (or after it was
    changed) still counts. Newest is by file modification time."""
    versions = list(VIEWS) if deck.supports_version else [None]
    jobs: list[CompileJob] = []
    for version in versions:
        jobs.append(CompileJob(deck, version, None))
    presenter_version = "instructor" if deck.supports_version else None
    jobs.append(CompileJob(deck, presenter_version, None, presenter=True))
    chapter_version = "after-course" if deck.supports_version else None
    for chapter in deck.chapters:
        jobs.append(CompileJob(deck, chapter_version, chapter))

    from dataclasses import replace
    from .deck_settings import read_settings
    other = "DE" if read_settings(deck.text).language.lower() == "en" else "EN"
    jobs += [replace(job, language=other) for job in jobs]

    found: dict[str, DeckPdf] = {}
    for job in jobs:
        output_dir, output_stem = resolve_output_location(ctx, job)
        for candidate in (output_dir / f"{output_stem}.pdf", ctx.pdf_dir / f"{job.jobname}.pdf"):
            key = _destination_key(candidate)
            if key in found or not candidate.is_file():
                continue
            found[key] = DeckPdf(
                job_label(job), candidate, candidate.stat().st_mtime,
                preferred=_is_preferred(job),
                run_id=compile_records.read_run_id(candidate))
    return sorted(found.values(), key=lambda pdf: pdf.mtime, reverse=True)


def pdf_to_open(pdfs: list[DeckPdf]) -> Optional[DeckPdf]:
    """Which of a deck's PDFs (deck_pdfs()) "Open pdf" opens without asking
    (2026-10-08, direct instructions): the deck's preferred PDF (its setting,
    else the instructor PDF), unless a newer PDF comes from another compile
    run (another /SlideMageRun, or none -- a PDF from before v5.34.0); the
    only PDF there is. None: ask which one."""
    if len(pdfs) == 1:
        return pdfs[0]
    preferred = next((pdf for pdf in pdfs if pdf.preferred), None)
    if preferred is None:
        return None
    for pdf in pdfs:
        if pdf is not preferred and pdf.mtime > preferred.mtime and (
                pdf.run_id is None or pdf.run_id != preferred.run_id):
            return None
    return preferred


def display_path(ctx: project.ProjectContext, path: Path) -> str:
    """A PDF's destination for the compile log -- relative to the project folder
    (e.g. "pdf/foo.pdf") when it's under there, same as the old hardcoded
    "pdf/{jobname}.pdf" text always showed; the full absolute path for a
    \\deckoutputfolder pointing outside the project tree entirely."""
    try:
        return path.relative_to(ctx.root).as_posix()
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


def lower_priority(proc: subprocess.Popen) -> None:
    """Run `proc` (and what it launches from now on) below normal priority. Best-effort."""
    try:
        if os.name == "nt":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x4000
            ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(int(proc._handle)), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
    except (OSError, AttributeError, ValueError):
        pass


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
        self._job_killed = False
        self._skipped: set[str] = set()
        # Background renders run their process at below-normal priority (set right after it starts, so
        # what it launches inherits it).
        self.low_priority = False

    def is_set(self) -> bool:
        return self._event.is_set()

    def _set_process(self, proc: Optional[subprocess.Popen]) -> None:
        with self._lock:
            self._proc = proc
            stopped = self._event.is_set()
        if proc is not None and self.low_priority:
            lower_priority(proc)
        if stopped:
            self._kill(proc)

    def request_stop(self) -> None:
        """Stop the whole run: kill the job being compiled, skip the rest."""
        self._event.set()
        with self._lock:
            proc = self._proc
        self._kill(proc)

    def stop_current(self) -> None:
        """Stop only the job being compiled (job_stopped() tells its runner);
        the queue goes on with the next job. Nothing happens while no
        compile process runs."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return
            self._job_killed = True
        self._kill(proc)

    def job_stopped(self) -> bool:
        """Whether the job that just ended was stopped, by stop_current() or
        by a stop of the whole run. Reads (and clears) the single-job flag."""
        with self._lock:
            killed, self._job_killed = self._job_killed, False
        return killed or self._event.is_set()

    def skip(self, jobname: str) -> None:
        """Take a queued job out of the run."""
        with self._lock:
            self._skipped.add(jobname)

    def is_skipped(self, jobname: str) -> bool:
        with self._lock:
            return jobname in self._skipped

    @staticmethod
    def _kill(proc: Optional[subprocess.Popen]) -> None:
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
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                proc.kill()


def run_streamed(
    cmd: list[str], *, cwd: Path, env: dict, log: LogCallback,
    cancel: Optional[CancelToken] = None, on_line: Optional[LogCallback] = None,
    errors: Optional[str] = None, bufsize: int = 1,
) -> int:
    """Stream process output to log, with an optional callback on each raw line.

    Keep the caller's decoding and buffering options; launch errors propagate.
    """
    if cancel is not None and cancel.is_set():
        return -1
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors=errors, bufsize=bufsize,
            **no_console_kwargs(),
            **({"start_new_session": True} if cancel is not None and os.name != "nt" else {}),
        )
        if cancel is not None:
            cancel._set_process(proc)
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_line is not None:
                on_line(line)
            log(line.rstrip("\n"))
        return proc.wait()
    finally:
        if cancel is not None:
            cancel._set_process(None)


def latexmk_command(wrapper: Path, jobname: str, outdir: Path, *options: str, cwd: Path, aux: bool = True) -> list[str]:
    """latexmk on `wrapper` (given relative to `cwd`, the folder latexmk runs in), its output in
    `outdir` -- also its auxiliary files unless `aux` is False. -recorder (the .fls list of every file
    read, which compile_records keeps for deck snapshots) is among the `options` of the jobs that need it."""
    out = outdir.as_posix()
    return ["latexmk", *options, f"-jobname={jobname}", f"-outdir={out}", *([f"-auxdir={out}"] if aux else []),
            os.path.relpath(wrapper, cwd)]


@dataclass
class Build:
    """What a latexmk run left in its output folder."""
    returncode: int
    pdf: Path
    log_path: Path
    log_text: str
    stopped: bool       # the job was stopped by the user (or the whole run was)

    @property
    def ok(self) -> bool:
        """Pass/fail is the output, never latexmk's exit code (lualatex returns nonzero on a clean
        compile): a PDF, a TeX log, and no LaTeX error in that log. Only meaningful for an output
        folder the run owns, or one whose stale PDF the caller checks (the cached preview build)."""
        return (bool(self.log_text) and self.pdf.is_file() and self.pdf.stat().st_size > 0
                and not FATAL_ERROR_RE.search(self.log_text))


def run_latexmk(cmd: list[str], *, jobname: str, outdir: Path, cwd: Path, env: dict, log: LogCallback,
                cancel: Optional[CancelToken] = None, on_line: Optional[LogCallback] = None,
                errors: Optional[str] = "replace", bufsize: int = 1) -> Build:
    """run_streamed() for a latexmk command, then the outcome. FileNotFoundError (no latexmk) propagates."""
    returncode = run_streamed(cmd, cwd=cwd, env=env, log=log, cancel=cancel, on_line=on_line,
                              errors=errors, bufsize=bufsize)
    log_path = outdir / f"{jobname}.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    return Build(returncode, outdir / f"{jobname}.pdf", log_path, log_text,
                 cancel is not None and cancel.job_stopped())


@contextmanager
def wrapper_file(path: Path, text: str, remove: Callable[[Path], object] = lambda p: p.unlink(missing_ok=True)):
    """Write a wrapper .tex for the duration of a build. newline="" keeps the text's own line endings:
    it mixes a deck's preamble (read with newline="", so it carries the file's literal "\r\n") with
    freshly generated "\n" lines, and write_text's default would double every "\r\n" into "\r\r\n" on
    Windows -- TeX takes each bare \r for an end of line, so a multi-line macro captured from that
    preamble (a bibliography driver, say) would gain blank lines."""
    path.write_text(text, encoding="utf-8", newline="")
    try:
        yield path
    finally:
        remove(path)


@dataclass
class CompileJob:
    deck: Deck
    version: Optional[str]     # "instructor" / "during-course" / "after-course",
                                # or None for a deck with no version support
    chapter: Optional[Chapter]  # None = whole deck
    # A separate "Presenter" output (never a toggle on the plain instructor
    # PDF) -- beamer's own \setbeameroption{show notes on second screen}
    # dual-screen mechanism, so \note{} content (already authored
    # throughout this project) reaches a presenter-view app like pympress
    # instead of sitting unused. Always paired with instructor-version
    # content by whoever builds this job (build_jobs()
    # below) regardless of self.version's own value --
    # never on its own a reason to change what version means here.
    presenter: bool = False
    # SlideMage's "Generate appendix TOC" checkbox -- set uniformly on
    # every job a compile batch builds (the window's _compile_jobs()), but wrapper_text() below only actually
    # generates the appendix for a whole-deck job (job.chapter is None) --
    # of any version since 2026-10-03 (direct instruction; it used to be
    # the instructor/presenter compiles only). A per-chapter job stays
    # without one, even with this set: its PDF holds one chapter, and an
    # appendix of the whole deck's slides would link to slides that aren't
    # in it.
    appendix_toc: bool = False
    # A page compile (partial_compile.py, v5.35.0): only these frame numbers
    # (the slide footers' numbers) of a whole-deck version, on top of its
    # last whole-deck compile; None = the whole deck. replace_pages: put the
    # new pages into that compile's PDF (else into a "<pdf>-pages-..." file).
    pages: Optional[list[int]] = None
    replace_pages: bool = True
    # The click that started this compile (2026-10-08, direct instruction):
    # every PDF of one compile run carries it in its info dictionary
    # (/SlideMageRun), so "Open pdf" can tell PDFs of the same run, with no
    # change in between, from later ones. None: not stamped.
    run_id: Optional[str] = None
    language: Optional[str] = None   # EN/DE override; None uses the deck's setting
    resolve_translations: bool = True   # False for a maintenance deck rendering each file independently

    @property
    def _appendix_applies(self) -> bool:
        """Whether appendix_toc actually generates content for *this* job
        -- a whole-deck compile (see appendix_toc field's own comment).
        Used by wrapper_text() below."""
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
        if self.language:
            from .deck_settings import read_settings
            if self.language.lower() != read_settings(self.deck.text).language.lower():
                parts.append(self.language.lower())
        # No "-appendix" suffix (2026-10-03, direct instruction; it used to
        # mark a compile with the generated appendix): with or without the
        # appendix a job writes the same file.
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


def build_env(ctx: project.ProjectContext) -> dict:
    env = os.environ.copy()
    perl_bin = _find_git_perl_bin()
    if perl_bin is not None:
        env["PATH"] = str(perl_bin) + os.pathsep + env.get("PATH", "")
    # Inside a deck snapshot: its own framework copy and fixed PDF dates.
    return project.snapshot_compile_env(ctx.root, env)


def wrapper_text(ctx: project.ProjectContext, job: CompileJob) -> str:
    from . import deck_language
    lines: list[str] = []
    if job.version:
        lines.append(f"\\def\\deckversionoverride{{{job.version}}}")
    if job.presenter:
        lines.append("\\def\\SMPresenterModeOverride{1}")
    if job._appendix_applies:
        lines.append("\\def\\SMAppendixTocOverride{1}")
    if job.run_id:
        lines.append(compile_records.run_id_line(job.run_id))
    if job.language:
        lines.append(f"\\def\\decklanguageoverride{{{job.language.lower()}}}")

    language = deck_language.language_for_job(job)
    resolved_deck, _dependencies = (deck_language.compile_deck(ctx, job.deck, language)
                                   if job.resolve_translations else (job.deck, []))
    resolved = resolved_deck.text
    preamble = job.deck.preamble_text if job.deck.preamble_end is not None else ""
    if job.language and preamble:
        preamble += "\n" + deck_language.language_line(language)

    if job.chapter is not None:
        lines.append(preamble)
        lines.append("")
        chapter = next(c for c in resolved_deck.chapters if c.order == job.chapter.order)
        lines.append(resolved_deck.chapter_text(chapter))
        lines.append("")
        lines.append("\\end{document}")
    elif job._appendix_applies:
        # Same "copy preamble, inline the body" trick as the per-chapter
        # branch above, needed here for a different reason: the generated
        # appendix has to land *before* the deck's own literal
        # \end{document} -- a plain \input{deck.tex} would hit that
        # \end{document} and stop before anything appended after the
        # \input{} line ever ran.
        body = resolved[job.deck.preamble_end :]
        end_match = DOCUMENT_END_RE.search(body)
        body_without_end = body[: end_match.start()] if end_match else body
        template = slide_snapshot.detect_template(job.deck.preamble_text)
        lines.append(preamble)
        lines.append(body_without_end)
        lines.append(appendix_toc.generate_appendix_tex(
            ctx, resolved_deck, template, job.version or "instructor"))
        lines.append("\\end{document}")
    elif job.language or resolved != job.deck.text:
        lines.append(preamble)
        lines.append(resolved[job.deck.preamble_end:])
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
        set_build_dir_active(build_dir, False)

    if attempts_drained.is_set():
        release()
    else:
        threading.Thread(target=release, daemon=True).start()


def _relocate_pdf_and_finish(
    ctx: project.ProjectContext, pdf_source: Path, dest_pdf: Path, jobname: str, job: CompileJob,
    log: LogCallback, cancel: Optional["CancelToken"] = None,
    on_relocated: Optional[Callable[[bool, Path], None]] = None,
    *, build_dir: Path, destination_key: str, generation: int,
    record: Optional[tuple[Path, str, float]] = None,
) -> None:
    """Retry publication of one immutable invocation PDF in the background.
    `record` (wrapper path, wrapper text, compile start time): once published,
    the compile is recorded for deck snapshots (compile_records.py)."""
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
            source_display = display_path(ctx, pdf_source)
            log(compile_log.failed(jobname, "stopped by user while relocating the "
               f"PDF; left at {source_display} for manual recovery"))
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
            log(f"    (moving {jobname}.pdf into {display_path(ctx, dest_pdf)} -- "
               "this can take a moment if a sync client is still indexing it)")
        elif attempt_count % 6 == 0:
            log(f"    (still trying to publish {jobname}.pdf, "
                f"{elapsed / 60:.0f} min so far -- retrying up to "
                f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min total)")
        done.wait(PDF_MOVE_RETRY_INTERVAL_SECONDS)

    if superseded.is_set() and not succeeded.is_set():
        log(compile_log.failed(jobname, "output superseded by a newer successful "
            "compile; this PDF was not published"))
        if on_relocated is not None:
            on_relocated(False, dest_pdf)
        _release_build_dir_after_attempts(build_dir, attempts_drained, remove=True)
        return

    if not succeeded.is_set():
        source_display = display_path(ctx, pdf_source)
        log(compile_log.failed(jobname, "couldn't publish PDF into "
            f"{display_path(ctx, dest_pdf)} after "
            f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min; left at "
            f"{source_display} for manual recovery"))
        if on_relocated is not None:
            on_relocated(False, dest_pdf)
        _release_build_dir_after_attempts(build_dir, attempts_drained, remove=False)
        return

    # Recorded before the preview refresh below: a generated appendix shows
    # the cached previews, and the record must describe what this compile
    # read -- a refreshed thumbnail then (rightly) counts as a change.
    if record is not None and _is_latest_output_success(destination_key, generation):
        wrapper_path, wrapper_text, compile_started = record
        compile_records.write_record(ctx, jobname, build_dir, wrapper_path, wrapper_text,
                                     dest_pdf, compile_started, log, deck_path=job.deck.path)

    # Refresh slide snapshots only from this invocation's immutable source,
    # and only if no newer successful compile has replaced it as current.
    if (job.version in (None, "instructor") and not job.presenter
            and _is_latest_output_success(destination_key, generation)):
        try:
            template = slide_snapshot.detect_template(job.deck.preamble_text)
            n = slide_snapshot.capture_deck(ctx, pdf_source, template)
            if n:
                log(f"    (refreshed {n} slide preview snapshot(s), "
                    f"{slide_snapshot.TEMPLATES[template]})")
        except Exception as exc:
            log(f"    (preview snapshots not updated: {exc})")

    elapsed = time.monotonic() - started
    suffix = f" (after {elapsed:.0f}s)" if elapsed >= 5 else ""
    log(compile_log.passed(jobname, display_path(ctx, dest_pdf), suffix))
    if on_relocated is not None:
        on_relocated(True, dest_pdf)
    _release_build_dir_after_attempts(build_dir, attempts_drained, remove=True)


def run_job(
    ctx: project.ProjectContext, job: CompileJob, log: LogCallback, cancel: Optional[CancelToken] = None,
    dest_override: Optional[tuple[Path, str]] = None,
    on_relocated: Optional[Callable[[bool, Path], None]] = None,
) -> bool:
    """Compile one job and background publication of its invocation PDF.

    Job names and callbacks stay stable for the GUI. Each invocation gets a
    private wrapper and latexmk output directory so a retry worker from an
    older run can never read or clean files created by a newer one.
    A page compile (job.pages) goes to partial_compile.run_page_job().
    """
    if job.pages and job.chapter is None:
        from . import partial_compile   # imports this module
        return partial_compile.run_page_job(ctx, job, log, cancel)
    deck_dir = job.deck.path.parent
    jobname = job.jobname
    invocation_id = uuid.uuid4().hex
    wrapper_path = deck_dir / f"_slidemage_{jobname}_{invocation_id}.tex"
    build_dir = ctx.build_dir / f"{jobname}-{invocation_id}"
    output_dir, output_stem = (
        dest_override if dest_override is not None else resolve_output_location(ctx, job)
    )
    dest_pdf = output_dir / f"{output_stem}.pdf"
    destination_key, generation = _register_output(dest_pdf)
    set_build_dir_active(build_dir, True)
    relocation_started = False

    log(compile_log.compiling(job.deck.name, jobname))
    try:
        wrapper = wrapper_text(ctx, job)
        with wrapper_file(wrapper_path, wrapper):
            ctx.build_dir.mkdir(parents=True, exist_ok=True)
            build_dir.mkdir(parents=True, exist_ok=False)
            # The configured output path is private to this invocation; there is no deck-directory
            # or prior-build fallback that can pass as fresh.
            cmd = latexmk_command(wrapper_path, jobname, build_dir.resolve(), "-f", "-recorder", cwd=ctx.root)
            compile_started = time.time()
            passes = 0

            def count_passes(line: str) -> None:
                nonlocal passes
                run = compile_passes.RUN_RE.match(line)
                if run:
                    passes = max(passes, int(run.group(1)))

            try:
                build = run_latexmk(cmd, jobname=jobname, outdir=build_dir, cwd=ctx.root, env=build_env(ctx),
                                    log=log, cancel=cancel, on_line=count_passes)
            except FileNotFoundError:
                log("*** latexmk not found on PATH -- is a TeX distribution installed? ***")
                return False

        if build.stopped:
            log(compile_log.failed(jobname, "stopped by user"))
            return False
        pdf_source = build.pdf
        if build.ok and compile_records.BIBER_NEEDED_RE.search(build.log_text):
            log(f"Warning: {jobname} -- the bibliography could not be built "
                f"(biber failed); citations show as keys. See {build.log_path}")
        if not build.ok:
            log(compile_log.failed(jobname, f"see {build.log_path}"))
            if on_relocated is not None:
                on_relocated(False, pdf_source)
            return False
        compile_passes.remember(ctx, job, passes)   # the next progress estimate

        output_dir.mkdir(parents=True, exist_ok=True)
        if not _mark_output_success(destination_key, generation):
            log(compile_log.failed(jobname, "output superseded by a newer successful "
                "compile; this PDF was not published"))
            if on_relocated is not None:
                on_relocated(False, dest_pdf)
            return True

        dest_display = display_path(ctx, dest_pdf)
        log(compile_log.moving(jobname, dest_display,
            f" (now backgrounded -- retrying for up to "
            f"{PDF_MOVE_RETRY_TOTAL_SECONDS / 60:.0f} min if needed, "
            "no longer blocking the rest of the queue)"))
        relocation = threading.Thread(
            target=_relocate_pdf_and_finish,
            args=(ctx, pdf_source, dest_pdf, jobname, job, log, cancel, on_relocated),
            kwargs={
                "build_dir": build_dir,
                "destination_key": destination_key,
                "generation": generation,
                # whole-deck compiles only: those are what a snapshot reuses
                "record": ((wrapper_path, wrapper, compile_started)
                           if job.chapter is None else None),
            },
            daemon=True,
        )
        relocation.start()
        relocation_started = True
        return True
    finally:
        if not relocation_started:
            set_build_dir_active(build_dir, False)


def _disambiguated_destinations(
    ctx: project.ProjectContext, jobs: list[CompileJob], log: LogCallback
) -> dict[int, tuple[Path, str]]:
    """resolve_output_location(job) for every job in this batch, except
    that when two or more jobs resolve to the exact same destination file
    (a literal \\deckoutputfolder filename shared by every chapter of a
    per-chapter compile, by a presenter job with no [presenter]-specific
    line of its own, or by every version sharing one bare, unqualified
    \\deckoutputfolder{...}), each of those jobs falls back to its own
    default pdf-folder-style job.jobname stem instead -- silently overwriting
    one job's PDF with another's is worse than not honoring the declared
    literal filename for jobs that turn out not to be unique. Keyed by
    id(job): CompileJob has no __eq__/__hash__ of its own, and two
    distinct jobs in the same batch can otherwise compare unequal only by
    identity anyway (e.g. two different chapters share every other field)."""
    dests = {id(job): resolve_output_location(ctx, job) for job in jobs}
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


def unchanged_jobs(
    ctx: project.ProjectContext, jobs: list[CompileJob], destinations: dict[str, Path]
) -> list[tuple[CompileJob, str]]:
    """The whole-deck jobs whose last compile is still current
    (compile_records.py: nothing it read changed, same settings, the PDF
    unchanged) and was published where this compile would put its PDF
    (`destinations`: jobname -> PDF path), with that compile's ISO time.
    The GUI asks before compiling them again (2026-10-08, direct
    instruction)."""
    unchanged = []
    for job in jobs:
        if job.chapter is not None or job.pages or job.jobname not in destinations:
            continue
        fresh, _why = compile_records.fresh_output(ctx.build_dir, job.jobname, wrapper_text(ctx, job))
        if fresh is not None and (compile_records.norm(fresh.pdf)
                                  == compile_records.norm(destinations[job.jobname])):
            unchanged.append((job, fresh.created))
    return unchanged


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
    presentations, the manual, test decks. Decks of one group, and the chapters of one
    deck, stay in the order the jobs came in (the table's order): the sort is
    stable. Selecting During-course and Presenter for #workdeck and IA2
    compiles #workdeck Presenter, IA2 Presenter, #workdeck During-course,
    IA2 During-course."""
    group_rank = {tag: i for i, tag in enumerate(GROUP_ORDER)}
    return sorted(jobs, key=lambda job: (
        job_stage(job), group_rank.get(job.deck.group, len(group_rank))))


def build_jobs(deck: Deck, kind: str, pages: Optional[list[int]] = None) -> list[CompileJob]:
    """The jobs behind one entry of the Compile menu: `kind` is a view
    ("instructor", "during-course", "after-course"), "all" (every view the deck has), "chapters" (the
    after-course version split into one PDF per chapter) or "presenter"
    (beamer's notes mode, always instructor content). A deck without
    \\deckversionoverride has only its hardcoded content, so every view is
    the one job with no version. `pages` (partial_compile.py) restricts a
    view or the presenter PDF to those frames; chapters are always whole."""
    if kind == "all":
        views = VIEWS if deck.supports_version else (None,)
        return [CompileJob(deck, view, None, pages=pages) for view in views]
    if kind == "chapters":
        version = "after-course" if deck.supports_version else None
        return [CompileJob(deck, version, chapter) for chapter in deck.chapters]
    if kind == "presenter":
        version = "instructor" if deck.supports_version else None
        return [CompileJob(deck, version, None, presenter=True, pages=pages)]
    return [CompileJob(deck, kind if deck.supports_version else None, None, pages=pages)]


def run_jobs(
    ctx: project.ProjectContext, jobs: list[CompileJob], log: LogCallback, cancel: Optional[CancelToken] = None
) -> dict[str, bool]:
    """Run every job in order; one failure doesn't stop the rest. Returns
    {jobname: success} for a summary. If `cancel` is set partway through
    (the GUI's "Stop creation" button), the job in progress is killed
    (see run_job) and whatever's still queued is skipped rather than
    started. Jobs the GUI took out of the queue (cancel.skip) are left out
    one by one."""
    destinations = _disambiguated_destinations(ctx, jobs, log)
    results: dict[str, bool] = {}
    for position, job in enumerate(jobs):
        if cancel is not None and cancel.is_set():
            log(compile_log.stopped(len(jobs) - position))
            break
        if cancel is not None and cancel.is_skipped(job.jobname):
            log(compile_log.skipped(job.jobname))
            continue
        results[job.jobname] = run_job(
            ctx, job, log, cancel=cancel, dest_override=destinations[id(job)]
        )
    return results
