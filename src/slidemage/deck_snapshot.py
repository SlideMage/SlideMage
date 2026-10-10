"""Deck snapshots: a frozen, self-contained copy of one deck (v5.33.0,
docs/DECK_SNAPSHOT_PLAN.md).

A snapshot holds everything needed to compile a deck later exactly as it
compiled on the day it was taken -- deck, slides, media, snippets, institution
template, bibliography, alt-text store and the LaTeX framework -- so later
project edits and SlideMage releases can't change it. Layout of
``<project>/snapshots/<deck>_<YYYY-MM-DD>_<HH-MM>/`` (or the same tree in a
``.zip``)::

    README.txt, render.bat, render.sh, snapshot.json
    reference-pdf/<jobname>.pdf     the PDFs built when the snapshot was taken
    app/                            optional: the SlideMage that made it
    <framework path>/               e.g. SlideMage/latex, copied whole
    <project folder>/               the files the deck uses, same relative paths
        decks/_snapshot_<jobname>.tex  one wrapper per compiled version
        .build/<jobname>/<jobname>.timestamp  the footer stamp, pre-seeded

The project and the framework keep their positions relative to each other, so
the project's own, unchanged .latexmkrc finds the framework as it always does.

Which files a deck uses is decided by compiling it: every version (and the
presenter PDF) is compiled with latexmk's -recorder, and every file the
compile read (.fls) is copied -- project files and the framework; files of the
TeX distribution are only recorded. biber's .bib files come from the .blg.
These reference compiles run with SOURCE_DATE_EPOCH set, and their footer
timestamps are kept, so a later render of the snapshot reproduces them. Then
(unless switched off) the snapshot is rendered from its own folder: every file
that compile reads must be inside the snapshot or the TeX distribution, and
its pages must equal the reference PDFs.

Free of Qt (deleting old snapshots uses QtCore's trash function only).
Command line::

    python -m slidemage.deck_snapshot create <deck name or .tex> [...] [--zip] ...
    python -m slidemage.deck_snapshot verify <snapshot folder or zip>
    python -m slidemage.deck_snapshot list
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from . import app_settings, compile_records, compiler, project
from .compiler import FATAL_ERROR_RE, CancelToken, CompileJob
from .compile_records import (
    BIBER_NEEDED_RE as _BIBER_NEEDED_RE,
    LOG_FILE_LINE_RE as _LOG_FILE_LINE_RE,
    LOG_FORMAT_RE as _LOG_FORMAT_RE,
    is_within,
    norm as _norm,
    parse_blg_sources,
    parse_fls,
    sha256 as _sha256,
)
from .deck_scan import PROJECT_ROOT, Deck

SNAPSHOTS_DIRNAME = "snapshots"
SNAPSHOT_FORMAT = 1
MANIFEST_NAME = project.SNAPSHOT_MANIFEST
PARTIAL_PREFIX = ".partial-"
WRAPPER_PREFIX = "_snapshot_"
REFERENCE_PDF_DIR = "reference-pdf"
FRAMEWORK_MARKER = "Slidemaster_preamble_base.tex"
NAME_TIME_FORMAT = "%Y-%m-%d_%H-%M"
# <deck>_<YYYY-MM-DD>_<HH-MM>, optionally _2, _3, ... for a second snapshot of
# the same form within one minute.
NAME_RE = re.compile(r"^(?P<deck>.+)_(?P<stamp>\d{4}-\d\d-\d\d_\d\d-\d\d)(?:_(?P<n>\d+))?$")

# Files a deck needs that its compile doesn't read itself (or that latexmk
# reads before the recorder starts), relative to the project root.
ALWAYS_PROJECT_FILES = (
    ".latexmkrc", "decks/.latexmkrc", project.MARKER,
    "media/alt-text.csv", "media/alt-text.json",
)
# Project folders whose files never belong in a snapshot even if a compile
# reads them (build output, caches, other snapshots).
# (.previews: the slide previews a generated appendix shows are copied per
# version instead, see copy_job_previews().)
EXCLUDED_PROJECT_DIRS = (".build", ".previews", ".git", SNAPSHOTS_DIRNAME, ".slidemage")
PREVIEWS_DIRNAME = ".previews"
ISOLATING_ENV_VARS = project.SNAPSHOT_ISOLATING_ENV_VARS

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[str], None]



class SnapshotError(Exception):
    """A snapshot could not be made; the message says why."""


@dataclass
class SnapshotOptions:
    zip: bool = False
    # Copy the TeX distribution's package files and fonts into texmf/ (a
    # record; renders don't use them -- texmf/README.txt says how to).
    texmf: bool = False
    include_app: bool = False
    reference_pdfs: bool = True
    verify: bool = True
    footer_timestamp: bool = True
    # None: the deck's own \deckappendixtoc decides.
    appendix_toc: Optional[bool] = None
    presenter: bool = True
    # Use a version's last compile instead of compiling it again when nothing
    # it read has changed since (compile_records.py).
    reuse: bool = True


@dataclass
class ExistingSnapshot:
    path: Path               # the folder or the .zip
    deck_name: str
    created: str             # ISO time from snapshot.json ("" if unreadable)
    is_zip: bool
    size: int                # bytes (whole folder, or the zip)

    @property
    def label(self) -> str:
        when = self.created[:16].replace("T", " ") if self.created else "?"
        form = "zip" if self.is_zip else "folder"
        return f"{self.deck_name}  {when}  {form}  {format_size(self.size)}"


@dataclass
class SnapshotResult:
    deck_name: str
    ok: bool
    path: Optional[Path] = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    size: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    deleted: list[Path] = field(default_factory=list)
    skipped: bool = False   # cancelled before it started


@dataclass
class VerifyReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _JobOutput:
    """What one reference (or verification) compile left behind."""
    job_name: str
    pdf: Path
    inputs: list[Path]
    log_text: str
    bib_sources: list[Path]
    timestamp: Optional[str]   # contents of <jobname>.timestamp
    # The SOURCE_DATE_EPOCH this PDF corresponds to: the snapshot's own for a
    # compile made for it, the compile's start for a reused one (None: the
    # snapshot's); renders of the snapshot use it, so \today matches.
    epoch: Optional[int] = None
    reused_from: str = ""      # "" or the ISO time of the reused compile
    # norm(path) -> the file to copy instead (a reused compile's kept slide
    # previews: the current ones may have been refreshed since)
    copies: dict[str, Path] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Small helpers

def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


# Remembered between runs (app_settings), and used as they are by the snapshot the archive
# question offers.
OUTPUT_SETTING_KEY = "snapshot_output"        # "folder" / "zip"
TEXMF_SETTING_KEY = "snapshot_texmf"
APP_SETTING_KEY = "snapshot_app"


def saved_options() -> SnapshotOptions:
    """The settings last used in the Snapshots sheet."""
    return SnapshotOptions(
        zip=app_settings.get(OUTPUT_SETTING_KEY, "folder") == "zip",
        texmf=bool(app_settings.get(TEXMF_SETTING_KEY, False)),
        include_app=bool(app_settings.get(APP_SETTING_KEY, False)),
    )


def save_options(options: SnapshotOptions) -> None:
    app_settings.set(OUTPUT_SETTING_KEY, "zip" if options.zip else "folder")
    app_settings.set(TEXMF_SETTING_KEY, options.texmf)
    app_settings.set(APP_SETTING_KEY, options.include_app)


def describe_options(options: SnapshotOptions) -> str:
    """"folder, without LaTeX package files" -- for the archive question."""
    parts = [".zip file" if options.zip else "folder",
             "with LaTeX package files" if options.texmf else "without LaTeX package files"]
    if options.include_app:
        parts.append("with the SlideMage app")
    return ", ".join(parts)


def summary_text(results: list[SnapshotResult]) -> str:
    lines = []
    for r in results:
        if r.ok:
            line = f"✓  {r.deck_name}: {r.path.name}  ({format_size(r.size)})"
            if r.deleted:
                line += f" -- {len(r.deleted)} older snapshot(s) moved to the trash"
        elif r.skipped:
            line = f"–  {r.deck_name}: skipped (stopped)"
        else:
            line = f"✗  {r.deck_name}: {r.error}"
        lines.append(line)
        lines.extend(f"      warning: {w}" for w in r.warnings)
    return "\n".join(lines)


def _rel(path: Path, root: Path) -> str:
    """`path` relative to `root`, with forward slashes."""
    return Path(os.path.relpath(str(path), str(root))).as_posix()


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _popen_kwargs() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _run_text(cmd: list[str], cwd: Optional[Path] = None, any_exit_code: bool = False) -> str:
    """A command's stdout ("" if it can't run, or exits with an error unless
    `any_exit_code`) -- for version strings and kpsewhich lookups."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                errors="replace", timeout=30, **_popen_kwargs())
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 or any_exit_code else ""


def replace_with_retry(source: Path, target: Path, attempts: int = 40, delay: float = 0.25) -> None:
    """os.replace(), retried for a while: on Windows a virus scanner or the
    search indexer often holds a just-written file open for a moment, and the
    rename of a freshly written snapshot folder then fails with "access
    denied" although nothing is wrong."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def snapshots_dir(root: Path = PROJECT_ROOT) -> Path:
    return root / SNAPSHOTS_DIRNAME


# --------------------------------------------------------------------------
# Naming and existing snapshots

def snapshot_name(deck_name: str, when: datetime, directory: Path, is_zip: bool) -> str:
    """`<deck>_<YYYY-MM-DD>_<HH-MM>`, with `_2`, `_3`, ... when a snapshot of
    the same form (folder or zip) already has that name. A folder and a zip of
    the same minute share the base name; so does an unfinished .partial-."""
    base = f"{deck_name}_{when.strftime(NAME_TIME_FORMAT)}"
    candidate, n = base, 1
    while True:
        target = directory / (candidate + (".zip" if is_zip else ""))
        partial = directory / f"{PARTIAL_PREFIX}{candidate}"
        if not target.exists() and not partial.exists():
            return candidate
        n += 1
        candidate = f"{base}_{n}"


def read_manifest(path: Path) -> Optional[dict]:
    """snapshot.json of a snapshot folder or zip, or None."""
    try:
        if path.is_dir():
            data = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
        elif path.suffix.lower() == ".zip" and path.is_file():
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist()
                         if n.count("/") == 1 and n.endswith("/" + MANIFEST_NAME)]
                if not names:
                    return None
                data = json.loads(zf.read(names[0]).decode("utf-8"))
        else:
            return None
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        return None
    return data if isinstance(data, dict) else None


def find_snapshots(deck_names: Optional[Iterable[str]] = None,
                   root: Path = PROJECT_ROOT) -> list[ExistingSnapshot]:
    """Every finished snapshot in <project>/snapshots/ (folders and zips),
    optionally only those of `deck_names`. A snapshot belongs to the deck its
    snapshot.json names -- never decided by the name prefix, since one deck's
    name can be the prefix of another's (t-X vs t-X-extra). Sorted by deck,
    then oldest first."""
    wanted = set(deck_names) if deck_names is not None else None
    directory = snapshots_dir(root)
    found: list[ExistingSnapshot] = []
    if not directory.is_dir():
        return found
    for entry in directory.iterdir():
        if entry.name.startswith(PARTIAL_PREFIX) or entry.name.startswith("."):
            continue
        is_zip = entry.is_file() and entry.suffix.lower() == ".zip"
        if not (entry.is_dir() or is_zip):
            continue
        manifest = read_manifest(entry)
        if manifest is None or not isinstance(manifest.get("deck_name"), str):
            continue
        if wanted is not None and manifest["deck_name"] not in wanted:
            continue
        found.append(ExistingSnapshot(
            path=entry, deck_name=manifest["deck_name"],
            created=str(manifest.get("created", "")), is_zip=is_zip,
            size=_dir_size(entry)))
    found.sort(key=lambda s: (s.deck_name.lower(), s.created, s.path.name))
    return found


def move_to_trash(path: Path) -> bool:
    """Move a snapshot to the Recycle Bin / trash; False when the platform or
    the drive can't (the snapshot then stays). Never deletes permanently."""
    try:
        from PySide6.QtCore import QFile
    except ImportError:
        return False
    try:
        result = QFile.moveToTrash(str(path))
    except Exception:  # noqa: BLE001 -- a failed trash move just keeps the file
        return False
    # PySide6 returns (ok, new_path) or a bare bool depending on version.
    ok = result[0] if isinstance(result, tuple) else bool(result)
    return bool(ok) and not path.exists()


def ensure_gitignored(root: Path = PROJECT_ROOT) -> bool:
    """Add `snapshots/` to the project's .gitignore unless a line already
    covers it. True when the line was added."""
    gitignore = root / ".gitignore"
    try:
        with open(gitignore, encoding="utf-8", newline="") as f:  # keep CRLF visible
            text = f.read()
    except FileNotFoundError:
        text = ""
    except OSError:
        return False
    lines = {line.strip() for line in text.splitlines()}
    if lines & {"snapshots", "snapshots/", "/snapshots", "/snapshots/"}:
        return False
    newline = "\r\n" if "\r\n" in text else "\n"
    addition = ("" if not text or text.endswith(("\n", "\r")) else newline)
    addition += f"# SlideMage deck snapshots (Decks -> Create deck snapshot){newline}snapshots/{newline}"
    with open(gitignore, "a", encoding="utf-8", newline="") as f:
        f.write(addition)
    return True


# --------------------------------------------------------------------------
# Compiling and reading what a compile used

def snapshot_jobs(deck: Deck, options: SnapshotOptions) -> list[CompileJob]:
    """The compiles a snapshot captures: every version of the deck (or the one
    version-less compile) and, by default, the presenter PDF."""
    appendix = deck.appendix_toc if options.appendix_toc is None else options.appendix_toc
    versions = ["instructor", "during-course", "after-course"] if deck.supports_version else [None]
    jobs = [CompileJob(deck, v, None, footer_timestamp=options.footer_timestamp,
                       appendix_toc=appendix) for v in versions]
    if options.presenter:
        jobs.append(CompileJob(deck, "instructor" if deck.supports_version else None, None,
                               footer_timestamp=options.footer_timestamp,
                               presenter=True, appendix_toc=appendix))
    return jobs


def timestamp_value(text: Optional[str]) -> str:
    """"2026-10-07 14:53" from a .timestamp file's
    \\gdef\\SMCompileTimestampValue{2026-10-07 14:53}; "" for none."""
    if not text:
        return ""
    m = re.search(r"\{([^{}]*)\}\s*$", text.strip())
    return m.group(1) if m else text.strip()


def progress_key(jobname: str, verify: bool = False) -> str:
    """The name a snapshot compile goes by in the log's "==== Compiling deck ->
    <key> ====" / "==== Finished: <key> ====" lines (the GUI's progress bar
    follows them): snapshot~<jobname> for the reference compile,
    verify~<jobname> for rendering it from the snapshot."""
    return f"{'verify' if verify else 'snapshot'}~{jobname}"


def wrapper_name(jobname: str) -> str:
    return f"{WRAPPER_PREFIX}{jobname}.tex"


def tex_roots() -> list[Path]:
    """The TeX distribution's trees (MiKTeX roots, TeX Live's texmf-dist/var/
    cache...), from kpsewhich. Files below them are "the TeX distribution"."""
    roots: dict[str, Path] = {}
    for var in ("TEXMF", "TEXMFDIST", "TEXMFLOCAL", "TEXMFSYSVAR", "TEXMFVAR",
                "TEXMFCACHE", "TEXMFROOT", "TEXMFSYSCONFIG", "TEXMFCONFIG"):
        value = _run_text(["kpsewhich", f"--var-value={var}"]).strip()
        for part in re.split(r"[,;{}]", value.replace("!!", "")):
            part = part.strip()
            if part and os.path.isabs(part) and os.path.isdir(part):
                path = Path(os.path.normpath(part))
                roots.setdefault(_norm(path), path)
    # The engine's own folder (formats, binaries) counts too.
    lualatex = shutil.which("lualatex")
    if lualatex:
        install = Path(lualatex).resolve().parent.parent
        roots.setdefault(_norm(install), install)
    return list(roots.values())


def _isolated_env(epoch: int, framework_dir: Optional[Path] = None) -> dict:
    env = compiler._build_env()
    for name in ISOLATING_ENV_VARS:
        env.pop(name, None)
    if framework_dir is not None:
        env["SLIDEMASTER_LATEX"] = str(framework_dir)
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    env["FORCE_SOURCE_DATE"] = "1"
    return env


def run_recorded_compile(
    cwd: Path, wrapper: Path, jobname: str, build_dir: Path, env: dict,
    log: LogCallback, cancel: Optional[CancelToken] = None,
) -> _JobOutput:
    """latexmk -recorder on `wrapper` from `cwd`, output into `build_dir`.
    Raises SnapshotError on a failed compile (same pass/fail rule as
    compiler.run_job: a PDF and no LaTeX error in the log)."""
    build_dir.mkdir(parents=True, exist_ok=True)
    out = build_dir.resolve().as_posix()
    cmd = ["latexmk", "-f", "-recorder", f"-jobname={jobname}",
           f"-auxdir={out}", f"-outdir={out}", _rel(wrapper, cwd)]
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace",
                                bufsize=1, **_popen_kwargs())
    except FileNotFoundError as exc:
        raise SnapshotError("latexmk not found on PATH -- is a TeX distribution installed?") from exc
    if cancel is not None:
        cancel._set_process(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip("\n"))
        proc.wait()
    finally:
        if cancel is not None:
            cancel._set_process(None)
    if cancel is not None and cancel.is_set():
        raise SnapshotError("stopped by user")
    pdf = build_dir / f"{jobname}.pdf"
    log_path = build_dir / f"{jobname}.log"
    fls = build_dir / f"{jobname}.fls"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if not (pdf.is_file() and pdf.stat().st_size > 0) or not log_text \
            or FATAL_ERROR_RE.search(log_text):
        raise SnapshotError(f"{jobname} did not compile -- see {log_path}")
    if not fls.is_file():
        raise SnapshotError(f"{jobname}: latexmk wrote no {fls.name} (-recorder)")
    # A failed biber run still leaves a PDF (citations shown as their keys);
    # an ordinary compile lets that pass, a snapshot must not keep it as its
    # reference. biblatex's final-pass log says so when the .bbl is missing
    # or stale.
    if _BIBER_NEEDED_RE.search(log_text):
        raise SnapshotError(f"{jobname}: the bibliography could not be built (biber failed; "
                            f"see the log above and {log_path})")
    stamp_file = build_dir / f"{jobname}.timestamp"
    timestamp = stamp_file.read_text(encoding="utf-8") if stamp_file.is_file() else None
    return _JobOutput(job_name=jobname, pdf=pdf, inputs=parse_fls(fls), log_text=log_text,
                      bib_sources=parse_blg_sources(build_dir / f"{jobname}.blg"),
                      timestamp=timestamp)


# --------------------------------------------------------------------------
# Deciding what goes into a snapshot

@dataclass
class _Collected:
    project_files: dict[str, Path]       # rel path in project -> source
    framework_dir: Optional[Path]
    tex_files: dict[str, Path]           # normalized key -> path
    external: list[Path]
    warnings: list[str]


def classify_input(path: Path, *, project_root: Path, framework_dir: Optional[Path],
                   build_dirs: Iterable[Path], roots: Iterable[Path]) -> str:
    """"build" (the compile's own aux/output), "framework", "project", "tex"
    (the TeX distribution) or "external" (anything else -- not allowed)."""
    if any(is_within(path, b) for b in build_dirs):
        return "build"
    if framework_dir is not None and is_within(path, framework_dir):
        return "framework"
    if is_within(path, project_root):
        return "project"
    if any(is_within(path, r) for r in roots):
        return "tex"
    return "external"


def find_framework_dir(inputs: Iterable[Path]) -> Optional[Path]:
    for path in inputs:
        if path.name.lower() == FRAMEWORK_MARKER.lower():
            return Path(os.path.normpath(str(path.parent)))
    return None


def collect_files(outputs: list[_JobOutput], project_root: Path, build_dirs: list[Path],
                  roots: list[Path], wrappers: Iterable[Path]) -> _Collected:
    """Sort every file the reference compiles read, plus the files a deck
    always needs, into what the snapshot copies."""
    all_inputs = [p for out in outputs for p in out.inputs]
    framework_dir = find_framework_dir(all_inputs)
    wrapper_keys = {_norm(w) for w in wrappers}
    project_files: dict[str, tuple[str, Path]] = {}   # lowercased rel -> (rel, source)
    tex_files: dict[str, Path] = {}
    external: dict[str, Path] = {}
    warnings: list[str] = []

    def add_project(path: Path) -> None:
        if _norm(path) in wrapper_keys or not path.is_file():
            return
        rel = _rel(path.resolve(), project_root.resolve())
        if rel.startswith("../"):
            return
        if rel.split("/", 1)[0] in EXCLUDED_PROJECT_DIRS:
            return
        project_files.setdefault(rel.lower(), (rel, path.resolve()))

    for path in all_inputs:
        kind = classify_input(path, project_root=project_root, framework_dir=framework_dir,
                              build_dirs=build_dirs, roots=roots)
        if kind == "project":
            add_project(path)
        elif kind == "tex":
            if path.is_file():
                tex_files.setdefault(_norm(path), path)
        elif kind == "external":
            external.setdefault(_norm(path), path)
    for out in outputs:
        for bib in out.bib_sources:
            if is_within(bib, project_root):
                add_project(bib)
            elif framework_dir is None or not is_within(bib, framework_dir):
                external.setdefault(_norm(bib), bib)
    for rel in ALWAYS_PROJECT_FILES:
        candidate = project_root / rel
        if candidate.is_file():
            add_project(candidate)
    if framework_dir is None:
        warnings.append("No LaTeX framework (Slidemaster_preamble_base.tex) among the files "
                        "the compile read -- the snapshot has no framework copy.")
    for path in external.values():
        warnings.append(f"Uses a file outside the project, the framework and the TeX "
                        f"distribution, which a snapshot can't hold: {path}")
    return _Collected(project_files=dict(project_files.values()),
                      framework_dir=framework_dir, tex_files=tex_files,
                      external=list(external.values()), warnings=warnings)


def relative_wrapper(text: str, project_root: Path, jobname: Optional[str] = None) -> str:
    """A wrapper's text as stored in a snapshot: absolute paths into the
    project (a generated appendix's slide previews) made project-relative,
    so the snapshot reads its own copies (the decks' graphicspath has ../);
    with `jobname`, the previews point into that version's own folder
    (job_previews_rel())."""
    for root in {project_root.as_posix(), project_root.resolve().as_posix()}:
        text = text.replace(root.rstrip("/") + "/", "")
    if jobname:
        text = text.replace(f"{PREVIEWS_DIRNAME}/", f"{PREVIEWS_DIRNAME}/{jobname}/")
    return text


def job_previews_rel(rel: str, jobname: str) -> str:
    """".previews/slide_previews/x.png" -> ".previews/<jobname>/slide_previews/x.png":
    each version of a snapshot keeps the previews its own compile read -- they
    differ between versions compiled before and after an instructor compile
    refreshed them."""
    return f"{PREVIEWS_DIRNAME}/{jobname}/{rel[len(PREVIEWS_DIRNAME) + 1:]}"


def copy_job_previews(out: "_JobOutput", jobname: str, project_root: Path,
                      target_project: Path) -> int:
    """Copy the slide previews `out`'s compile read (a reused compile's kept
    copies, else the current files) into the snapshot's per-version folder.
    Returns how many."""
    copied = 0
    for path in out.inputs:
        if not is_within(path, project_root):
            continue
        rel = _rel(path.resolve(), project_root.resolve())
        if not rel.startswith(f"{PREVIEWS_DIRNAME}/"):
            continue
        source = out.copies.get(_norm(path), path)
        if not source.is_file():
            continue
        dest = target_project / job_previews_rel(rel, jobname)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied += 1
    return copied


def framework_relpath(project_root: Path, framework_dir: Path) -> str:
    """Where the framework goes inside a snapshot: its path relative to the
    project's parent folder (SlideMage/latex for SlideMaster, latex for a
    project inside a SlideMage checkout), so the project's .latexmkrc finds it
    exactly as before. A framework elsewhere (via $SLIDEMASTER_LATEX) goes to
    SlideMage/latex; render scripts always point $SLIDEMASTER_LATEX at it."""
    rel = _rel(framework_dir.resolve(), project_root.resolve().parent)
    if rel.startswith("../") or rel == ".." or os.path.isabs(rel) or ":" in rel:
        return "SlideMage/latex"
    return rel


# --------------------------------------------------------------------------
# The TeX environment record (tier 1)

def root_of(path: Path, roots: Iterable[Path]) -> Optional[Path]:
    """The deepest of `roots` holding `path` (TeX Live's texmf-dist, not
    the texlive/2026 folder above it)."""
    holding = [r for r in roots if is_within(path, r)]
    return max(holding, key=lambda r: len(str(r))) if holding else None


def pdf_font_names(pdfs: Iterable[Path]) -> list[str]:
    """The fonts embedded in `pdfs` ("FiraSans-Light", "CMMI10"), without
    the subset prefix. Fonts that are only referenced (the PDF base 14) are
    left out -- there is no file to record."""
    import pymupdf as fitz
    names: set[str] = set()
    for pdf in pdfs:
        with fitz.open(pdf) as doc:
            for page in doc:
                for font in page.get_fonts():
                    if font[1] == "n/a":
                        continue
                    names.add(font[3].split("+", 1)[-1])
    return sorted(names)


def locate_fonts(names: Iterable[str]) -> dict[str, Path]:
    """Font name -> its file in the TeX distribution, via kpsewhich (fonts
    don't show up in latexmk's .fls: luaotfload reads them through its own
    cache). Names without a file are left out."""
    found: dict[str, Path] = {}
    for name in names:
        candidates = [f"{n}{ext}" for n in dict.fromkeys([name, name.lower()])
                      for ext in (".otf", ".ttf", ".pfb")]
        # kpsewhich exits 1 as soon as one candidate is missing, but still
        # prints the ones it found -- so its output counts whatever the code.
        lines = _run_text(["kpsewhich", *candidates], any_exit_code=True).splitlines()
        if lines and lines[0].strip():
            # resolve(): the file's real name (MiKTeX echoes the case asked for)
            found[name] = Path(os.path.normpath(lines[0].strip())).resolve()
    return found


def tex_environment(outputs: list[_JobOutput], tex_files: dict[str, Path],
                    roots: list[Path], fonts: Optional[dict[str, Path]] = None) -> dict:
    engine = _run_text(["lualatex", "--version"]).splitlines()
    latexmk = [line for line in _run_text(["latexmk", "-v"]).splitlines() if "Version" in line]
    biber = _run_text(["biber", "-v"]).splitlines()
    distribution = ""
    if engine:
        m = re.search(r"\((MiKTeX [^)]+|TeX Live [^)]+)\)", engine[0])
        distribution = m.group(1) if m else ""
    formats: list[str] = []
    packages: dict[str, str] = {}
    for out in outputs:
        for m in _LOG_FORMAT_RE.finditer(out.log_text):
            if m.group(1).strip() not in formats:
                formats.append(m.group(1).strip())
        for m in _LOG_FILE_LINE_RE.finditer(out.log_text):
            packages.setdefault(m.group(1), f"{m.group(2)} {m.group(3)}".strip())
    files = []
    for path in sorted(tex_files.values(), key=lambda p: _norm(p)):
        root = root_of(path, roots)
        files.append({"path": _rel(path, root) if root else str(path),
                      "root": str(root) if root else "", "sha256": _sha256(path)})
    font_entries = []
    for name, path in sorted((fonts or {}).items()):
        root = root_of(path, roots)
        font_entries.append({"name": name, "path": _rel(path, root) if root else str(path),
                             "root": str(root) if root else "",
                             "sha256": _sha256(path) if path.is_file() else ""})
    return {
        "engine": engine[0].strip() if engine else "",
        "distribution": distribution,
        "latexmk": latexmk[0].strip() if latexmk else "",
        "biber": biber[0].strip() if biber else "",
        "format": formats,
        "packages": dict(sorted(packages.items())),
        "files": files,
        "fonts": font_entries,
    }


TEXMF_DIR = "texmf"
TEXMF_README = """The TeX distribution's files this deck used when the snapshot was taken:
classes, packages, Lua code and the fonts embedded in its PDFs, in the same
folder layout as in the distribution (tex/latex/beamer/beamer.cls, ...).

They are an exact record of the LaTeX version the snapshot was made with.
render.bat / render.sh do not use them: they compile with the TeX
distribution installed on the computer, so a different TeX version may render
differently. snapshot.json lists every file with its hash, and SlideMage's
"verify" reports the differences.

To compile with these files instead, put this folder first on the search
path before running the render script, e.g. on Windows:
    set "TEXINPUTS=%CD%\\texmf//;"
    set "LUAINPUTS=%CD%\\texmf//;"
    set "OPENTYPEFONTS=%CD%\\texmf//;"
Classes, packages and Lua code are then read from here (tested with MiKTeX
25.4: the PDFs came out identical). Fonts are still found through the
installed TeX's font database (luaotfload), so the font files here are a
record only. Package files from an older TeX version don't always work with
a newer one.
"""


def copy_texmf(dest: Path, tex_files: dict[str, Path], fonts: dict[str, Path],
               roots: list[Path]) -> int:
    """Copy the recorded TeX distribution files and the PDFs' font files
    into `dest` (the snapshot's texmf/), keeping their path below the TeX
    root. luaotfload's caches are left out (they're rebuilt from the fonts).
    Returns the number of files copied."""
    copied: set[str] = set()
    for path in [*tex_files.values(), *fonts.values()]:
        if "luatex-cache" in _norm(path) or not path.is_file():
            continue
        root = root_of(path, roots)
        rel = _rel(path, root) if root else f"fonts/{path.name}"
        if rel.lower() in copied:
            continue
        copied.add(rel.lower())
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    _write_text(dest / "README.txt", TEXMF_README)
    return len(copied)


def environment_differences(recorded: dict, current: dict) -> list[str]:
    """Human-readable differences between two tex_environment() records."""
    diffs = []
    for key in ("engine", "distribution", "latexmk", "biber"):
        if recorded.get(key) and current.get(key) and recorded[key] != current[key]:
            diffs.append(f"{key}: snapshot {recorded[key]!r}, now {current[key]!r}")
    if recorded.get("format") and current.get("format") \
            and recorded["format"] != current["format"]:
        diffs.append(f"LaTeX format: snapshot {recorded['format']}, now {current['format']}")
    old, new = recorded.get("packages", {}), current.get("packages", {})
    for name in sorted(set(old) & set(new)):
        if old[name] != new[name]:
            diffs.append(f"{name}: snapshot {old[name]!r}, now {new[name]!r}")
    return diffs


# --------------------------------------------------------------------------
# Writing the snapshot

def _git(root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, errors="replace", timeout=30, **_popen_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _project_git_state(root: Path, rels: Iterable[str]) -> dict:
    head = _git(root, "rev-parse", "--short", "HEAD")
    if head is None:
        return {"commit": "", "dirty_files_in_snapshot": []}
    # Both relative to `root`, also when the project is a subfolder of the
    # repository (example/ in a SlideMage checkout).
    modified = _git(root, "diff", "--name-only", "--relative", "HEAD") or ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    changed = {line.strip().replace("\\", "/").lower()
               for line in (modified + "\n" + untracked).splitlines() if line.strip()}
    dirty = sorted(rel for rel in rels if rel.lower() in changed)
    return {"commit": head.strip(), "dirty_files_in_snapshot": dirty}


def _app_info() -> dict:
    from . import version
    commit = version._run_git("rev-parse", "--short", "HEAD") or ""
    dirty = bool(version._run_git("status", "--porcelain", "--untracked-files=no"))
    return {"version": version.VERSION_NUMBER, "commit": commit,
            "dirty": dirty if commit else False, "frozen": bool(getattr(sys, "frozen", False))}


def _copy_app(dest: Path, log: LogCallback) -> Optional[str]:
    """The running SlideMage into app/: the exe itself, or for a run from
    source an archive of the checkout's committed state. Returns a note."""
    from . import version
    dest.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        shutil.copy2(exe, dest / exe.name)
        note = f"{exe.name} {version.VERSION_NUMBER}"
    else:
        repo = Path(__file__).resolve().parents[2]
        archive = dest / f"SlideMage-src-{version.VERSION_NUMBER}.zip"
        if _git(repo, "archive", "--format=zip", "-o", str(archive), "HEAD") is None:
            log("    (could not archive the SlideMage source; only its version is recorded)")
            note = None
        else:
            note = f"source archive of commit {_app_info()['commit']}"
    (dest / "version.txt").write_text(
        f"{version.VERSION_NUMBER}\n{version.VERSION}\n", encoding="utf-8")
    return note


def _render_bat(project_dir: str, framework_rel: str, jobs: list[tuple[str, str, int]]) -> str:
    """render.bat; `jobs` = (jobname, wrapper, SOURCE_DATE_EPOCH) per version."""
    fw = framework_rel.replace("/", "\\")
    lines = [
        "@echo off",
        "rem Renders this deck snapshot exactly as it compiled when the snapshot was taken.",
        "rem PDFs land in " + project_dir + "\\pdf\\. Needs a TeX distribution (MiKTeX) with",
        "rem latexmk and perl; see README.txt.",
        "setlocal",
        f'cd /d "%~dp0{project_dir}"',
        f'set "SLIDEMASTER_LATEX=%~dp0{fw}"',
        "set TEXINPUTS=",
        "set BIBINPUTS=",
        "set LUAINPUTS=",
        "set FORCE_SOURCE_DATE=1",
        "where perl >nul 2>nul",
        "if errorlevel 1 (",
        "  for /f \"delims=\" %%G in ('where git 2^>nul') do if not defined GITEXE set \"GITEXE=%%G\"",
        ")",
        'if defined GITEXE for %%D in ("%GITEXE%\\..\\..") do if exist "%%~fD\\usr\\bin\\perl.exe" set "PATH=%%~fD\\usr\\bin;%PATH%"',
        'if not exist pdf mkdir pdf',
        "set FAILED=0",
    ]
    for jobname, wrapper, epoch in jobs:
        lines.append(f'call :job "{jobname}" "{wrapper}" {epoch}')
    lines += [
        'if "%FAILED%"=="1" (echo One or more versions failed -- see the .log files in .build\\. & exit /b 1)',
        "echo Done. The PDFs are in %CD%\\pdf\\",
        "exit /b 0",
        "",
        ":job",
        "set SOURCE_DATE_EPOCH=%~3",
        'latexmk -f -jobname=%~1 -auxdir="%CD%\\.build\\%~1" -outdir="%CD%\\.build\\%~1" %2',
        'if exist ".build\\%~1\\%~1.pdf" (copy /y ".build\\%~1\\%~1.pdf" "pdf\\%~1.pdf" >nul) else (set FAILED=1)',
        "exit /b 0",
        "",
    ]
    return "\r\n".join(lines)


def _render_sh(project_dir: str, framework_rel: str, jobs: list[tuple[str, str, int]]) -> str:
    lines = [
        "#!/bin/sh",
        "# Renders this deck snapshot exactly as it compiled when the snapshot was taken.",
        f"# PDFs land in {project_dir}/pdf/. Needs a TeX distribution with latexmk; see README.txt.",
        'here=$(cd "$(dirname "$0")" && pwd)',
        f'cd "$here/{project_dir}" || exit 1',
        f'SLIDEMASTER_LATEX="$here/{framework_rel}"; export SLIDEMASTER_LATEX',
        "unset TEXINPUTS BIBINPUTS LUAINPUTS",
        "FORCE_SOURCE_DATE=1; export FORCE_SOURCE_DATE",
        "mkdir -p pdf",
        "failed=0",
        "job() {",
        '  SOURCE_DATE_EPOCH="$3"; export SOURCE_DATE_EPOCH',
        '  latexmk -f -jobname="$1" -auxdir="$PWD/.build/$1" -outdir="$PWD/.build/$1" "$2"',
        '  if [ -f ".build/$1/$1.pdf" ]; then cp ".build/$1/$1.pdf" "pdf/$1.pdf"; else failed=1; fi',
        "}",
    ]
    for jobname, wrapper, epoch in jobs:
        lines.append(f"job '{jobname}' '{wrapper}' {epoch}")
    lines += [
        'if [ "$failed" = 1 ]; then echo "One or more versions failed -- see the .log files in .build/."; exit 1; fi',
        'echo "Done. The PDFs are in $PWD/pdf/"',
        "",
    ]
    return "\n".join(lines)


def _readme(manifest: dict) -> str:
    tex = manifest["tex"]
    app = manifest["slidemage"]
    jobs = "\n".join(f"  - {j['jobname']}" for j in manifest["jobs"])
    return f"""Deck snapshot: {manifest['deck']}
Taken {manifest['created'][:16].replace('T', ' ')} with SlideMage {app['version']}.

This folder holds everything needed to compile the deck exactly as it compiled
on that day: the deck, its slides, media, snippets, institution template,
bibliography, image descriptions and the LaTeX framework. Later changes to the
project or to SlideMage don't affect it.

Rendering
  Windows: double-click render.bat.   Linux/macOS: sh render.sh
  The PDFs land in {manifest['project_dir']}/pdf/. Versions:
{jobs}
  The PDFs built when the snapshot was taken are in {REFERENCE_PDF_DIR}/ (if included).

  SlideMage can also open {manifest['project_dir']}/ as a project (read-only).

TeX distribution used
  {tex.get('engine', '')}
  latexmk: {tex.get('latexmk', '')}    biber: {tex.get('biber', '')}
  LaTeX format: {'; '.join(tex.get('format', []))}
  A different TeX installation may render differently; snapshot.json lists
  every package version and file hash. SlideMage's "verify" compares them.

Files
  snapshot.json lists every file with its SHA-256 hash.
"""


def _write_text(path: Path, text: str, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline if newline == "\n" else "")


def build_manifest_files(root: Path) -> list[dict]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = _rel(path, root)
        if rel == MANIFEST_NAME:
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return files


def write_zip(source: Path, target: Path, top: str, when: datetime) -> None:
    """A deterministic zip of `source`: entries under `top/`, sorted, with
    snapshot.json first, all dated `when`."""
    stamp = (max(when.year, 1980), when.month, when.day, when.hour, when.minute, 0)
    files = sorted((p for p in source.rglob("*") if p.is_file()), key=lambda p: _rel(p, source))
    files.sort(key=lambda p: _rel(p, source) != MANIFEST_NAME)
    tmp = target.with_name(target.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            info = zipfile.ZipInfo(f"{top}/{_rel(path, source)}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as src, zf.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    replace_with_retry(tmp, target)


# --------------------------------------------------------------------------
# Verification

@contextmanager
def _scratch_dir(kind: str) -> Iterator[Path]:
    """A temporary folder in the project's .build/ (see verify_folder for why
    not %TEMP%), protected from the GUI's temp-file cleanup while in use."""
    path = compiler.BUILD_DIR / f"snapshot-{kind}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    compiler._set_build_dir_active(path, True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        compiler._set_build_dir_active(path, False)


def first_difference(reference: str, rendered: str, width: int = 60) -> str:
    """'reference "..." , now "..."' for the first line that differs."""
    a, b = reference.splitlines(), rendered.splitlines()
    for line_a, line_b in zip(a, b):
        if line_a != line_b:
            return f'reference "{line_a[:width]}", now "{line_b[:width]}"'
    if len(a) != len(b):
        return f"reference has {len(a)} lines, now {len(b)}"
    return "whitespace only"


def compare_pdfs(reference: Path, rendered: Path) -> list[str]:
    """Differences between two PDFs: page count, then each page's text and
    pixels (36 dpi). Empty when they match."""
    if reference.read_bytes() == rendered.read_bytes():
        return []
    import pymupdf as fitz
    problems: list[str] = []
    with fitz.open(reference) as a, fitz.open(rendered) as b:
        if a.page_count != b.page_count:
            return [f"{rendered.name}: {b.page_count} pages, reference has {a.page_count}"]
        matrix = fitz.Matrix(0.5, 0.5)
        for i in range(a.page_count):
            pa, pb = a[i], b[i]
            text_a, text_b = pa.get_text(), pb.get_text()
            if text_a != text_b:
                problems.append(f"{rendered.name}: page {i + 1} text differs "
                                f"({first_difference(text_a, text_b)})")
                continue
            if pa.get_pixmap(matrix=matrix).samples != pb.get_pixmap(matrix=matrix).samples:
                problems.append(f"{rendered.name}: page {i + 1} looks different")
    return problems


def verify_folder(snapshot_root: Path, log: LogCallback,
                  cancel: Optional[CancelToken] = None,
                  check_hashes: bool = True) -> VerifyReport:
    """Render a snapshot folder from itself and check that (1) every file the
    compiles read is inside the snapshot or the TeX distribution and (2) the
    pages equal the reference PDFs. Build output goes to a temporary folder,
    so the snapshot itself isn't changed."""
    manifest = read_manifest(snapshot_root)
    if manifest is None:
        return VerifyReport(False, [f"{snapshot_root}: no readable {MANIFEST_NAME}"])
    report = VerifyReport(True)
    if check_hashes:
        for entry in manifest.get("files", []):
            path = snapshot_root / entry["path"]
            if not path.is_file():
                report.problems.append(f"missing: {entry['path']}")
            elif path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]:
                report.problems.append(f"changed: {entry['path']}")
        if report.problems:
            report.ok = False
            return report
    project_dir = snapshot_root / manifest["project_dir"]
    framework = snapshot_root / manifest["framework_dir"]
    roots = tex_roots()
    default_epoch = int(manifest["source_date_epoch"])
    outputs: list[_JobOutput] = []
    # Build output in the project's .build/, not the system temp folder: Git
    # for Windows' perl (which runs latexmk) maps %TEMP% to /tmp, a path the
    # native TeX engine can't resolve.
    with _scratch_dir("verify") as tmp:
        for job in manifest["jobs"]:
            if cancel is not None and cancel.is_set():
                report.ok = False
                report.problems.append("stopped by user")
                return report
            jobname = job["jobname"]
            build = Path(tmp) / jobname
            build.mkdir(parents=True)
            seed = project_dir / ".build" / jobname / f"{jobname}.timestamp"
            if seed.is_file():
                shutil.copy2(seed, build / seed.name)
            key = progress_key(jobname, verify=True)
            log(f"==== Compiling {manifest.get('deck_name', '?')} -> {key} ====")
            log("    (verifying: rendering from the snapshot itself)")
            env = _isolated_env(int(job.get("source_date_epoch", default_epoch)), framework)
            try:
                out = run_recorded_compile(project_dir, project_dir / job["wrapper"], jobname,
                                           build, env, log, cancel)
            except SnapshotError as exc:
                report.ok = False
                report.problems.append(str(exc))
                continue
            finally:
                log(f"==== Finished: {key} ====")
            outputs.append(out)
            for path in out.inputs + out.bib_sources:
                if is_within(path, snapshot_root) or is_within(path, build):
                    continue
                if any(is_within(path, r) for r in roots):
                    continue
                report.ok = False
                report.problems.append(f"{jobname} read a file outside the snapshot: {path}")
            reference = snapshot_root / REFERENCE_PDF_DIR / f"{jobname}.pdf"
            if reference.is_file():
                diffs = compare_pdfs(reference, out.pdf)
                if diffs:
                    report.ok = False
                    report.problems.extend(diffs[:20])
                    if len(diffs) > 20:
                        report.problems.append(f"... and {len(diffs) - 20} more page differences")
                else:
                    report.notes.append(f"{jobname}: identical to the reference PDF")
            else:
                report.notes.append(f"{jobname}: compiled (no reference PDF to compare)")
        if outputs:
            current = tex_environment(outputs, {}, roots)
            for diff in environment_differences(manifest.get("tex", {}), current):
                report.notes.append(f"TeX differs from the snapshot's: {diff}")
    return report


def verify_snapshot(path: Path, log: LogCallback,
                    cancel: Optional[CancelToken] = None) -> VerifyReport:
    """verify_folder() for a snapshot folder or zip (extracted to a temporary
    folder first)."""
    if path.is_dir():
        return verify_folder(path, log, cancel)
    if not (path.is_file() and path.suffix.lower() == ".zip"):
        return VerifyReport(False, [f"{path}: not a snapshot folder or zip"])
    with _scratch_dir("extract") as tmp:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        tops = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(tops) != 1:
            return VerifyReport(False, [f"{path.name}: expected one top-level folder"])
        return verify_folder(tops[0], log, cancel)


# --------------------------------------------------------------------------
# Making one snapshot

def _check_cancel(cancel: Optional[CancelToken]) -> None:
    if cancel is not None and cancel.is_set():
        raise SnapshotError("stopped by user")


def create_snapshot(
    deck: Deck, options: SnapshotOptions, log: LogCallback,
    cancel: Optional[CancelToken] = None, progress: Optional[ProgressCallback] = None,
    when: Optional[datetime] = None, project_root: Path = PROJECT_ROOT,
) -> SnapshotResult:
    """Snapshot one deck into <project>/snapshots/. Never raises for an
    ordinary failure: the result says what went wrong, and nothing half-
    written is left behind."""
    progress = progress or (lambda _text: None)
    when = (when or datetime.now()).replace(microsecond=0)
    epoch = int(when.timestamp())
    result = SnapshotResult(deck_name=deck.name, ok=False)
    directory = snapshots_dir(project_root)
    directory.mkdir(parents=True, exist_ok=True)
    name = snapshot_name(deck.name, when, directory, options.zip)
    partial = directory / f"{PARTIAL_PREFIX}{name}"
    build_root = compiler.BUILD_DIR / f"snapshot-{uuid.uuid4().hex}"
    compiler._set_build_dir_active(build_root, True)
    jobs = snapshot_jobs(deck, options)
    wrappers: list[Path] = []
    try:
        # 1. Reference compiles, recorded -- or a version's last compile when
        # nothing it read has changed since (compile_records.py).
        outputs: list[_JobOutput] = []
        wrapper_texts: list[str] = []
        env = _isolated_env(epoch)
        if os.environ.get("SLIDEMASTER_LATEX"):
            env["SLIDEMASTER_LATEX"] = os.environ["SLIDEMASTER_LATEX"]
        for i, job in enumerate(jobs, 1):
            _check_cancel(cancel)
            key = progress_key(job.jobname)
            wrapper_text = compiler._wrapper_text(job)
            wrapper_texts.append(wrapper_text)
            if options.reuse:
                fresh, why = compile_records.fresh_output(compiler.BUILD_DIR, job.jobname,
                                                          wrapper_text)
                if fresh is not None:
                    progress(f"{job.jobname} unchanged ({i} of {len(jobs)})")
                    log(f"==== Compiling {deck.name} -> {key} ====")
                    log(f"    ({job.jobname}: nothing it uses changed since its compile of "
                        f"{fresh.created[:16].replace('T', ' ')} -- using "
                        f"{fresh.pdf} instead of compiling it again)")
                    log(f"==== Finished: {key} ====")
                    outputs.append(_JobOutput(
                        job_name=job.jobname, pdf=fresh.pdf, inputs=fresh.inputs,
                        log_text=fresh.log_text, bib_sources=fresh.bib_sources,
                        timestamp=fresh.timestamp, epoch=fresh.started,
                        reused_from=fresh.created, copies=fresh.copies))
                    continue
                log(f"    ({job.jobname} is compiled: {why})")
            progress(f"compiling {job.jobname} ({i} of {len(jobs)})")
            log(f"==== Compiling {deck.name} -> {key} ====")
            wrapper = deck.path.parent / wrapper_name(job.jobname)
            wrappers.append(wrapper)
            wrapper.write_text(wrapper_text, encoding="utf-8", newline="")
            try:
                outputs.append(run_recorded_compile(
                    project_root, wrapper, job.jobname, build_root / job.jobname, env, log, cancel))
            finally:
                wrapper.unlink(missing_ok=True)
                log(f"==== Finished: {key} ====")

        # 2. What to copy.
        _check_cancel(cancel)
        progress("collecting files")
        roots = tex_roots()
        collected = collect_files(outputs, project_root, [build_root], roots, wrappers)
        result.warnings.extend(collected.warnings)
        if collected.framework_dir is None:
            raise SnapshotError(collected.warnings[0])

        # 3. Write the snapshot into .partial-<name>/.
        progress("copying files")
        if partial.exists():
            shutil.rmtree(partial)
        partial.mkdir(parents=True)
        project_dir = project_root.resolve().name
        target_project = partial / project_dir
        for rel, source in sorted(collected.project_files.items()):
            dest = target_project / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        fw_rel = framework_relpath(project_root, collected.framework_dir)
        shutil.copytree(collected.framework_dir, partial / fw_rel,
                        ignore=shutil.ignore_patterns("__pycache__", ".git"))
        job_entries = []
        deck_rel_dir = _rel(deck.path.parent.resolve(), project_root.resolve())
        for job, out, wrapper_text in zip(jobs, outputs, wrapper_texts):
            wrapper_rel = f"{deck_rel_dir}/{wrapper_name(job.jobname)}"
            _write_text(target_project / wrapper_rel,
                        relative_wrapper(wrapper_text, project_root, job.jobname))
            copy_job_previews(out, job.jobname, project_root, target_project)
            if out.timestamp is not None:
                _write_text(target_project / ".build" / job.jobname / f"{job.jobname}.timestamp",
                            out.timestamp)
            if options.reference_pdfs:
                (partial / REFERENCE_PDF_DIR).mkdir(exist_ok=True)
                shutil.copy2(out.pdf, partial / REFERENCE_PDF_DIR / f"{job.jobname}.pdf")
            job_entries.append({
                "jobname": job.jobname, "wrapper": wrapper_rel,
                "version": job.version, "presenter": job.presenter,
                "appendix_toc": job._appendix_applies, "footer_timestamp": job.footer_timestamp,
                "timestamp": timestamp_value(out.timestamp),
                "source_date_epoch": out.epoch if out.epoch is not None else epoch,
                "reused_compile": out.reused_from,
            })
        app = _app_info()
        app_note = _copy_app(partial / "app", log) if options.include_app else None
        fonts = locate_fonts(pdf_font_names(out.pdf for out in outputs))
        if options.texmf:
            progress("copying LaTeX package files")
            result.counts["texmf"] = copy_texmf(partial / TEXMF_DIR, collected.tex_files,
                                                fonts, roots)
        created = when.astimezone().isoformat()
        info = project.read_project_info(project_root)
        project_json = {
            "format": info["format"], "last_app_version": app["version"],
            "highest_app_version": app["version"],
            "compat": {"checked_version": app["version"]},
            "snapshot": {"of": _rel(deck.path.resolve(), project_root.resolve()),
                         "deck_name": deck.name, "created": created, "read_only": True},
        }
        _write_text(target_project / project.PROJECT_INFO_PATH, json.dumps(project_json, indent=2) + "\n")
        render_jobs = [(e["jobname"], e["wrapper"], e["source_date_epoch"]) for e in job_entries]
        _write_text(partial / "render.bat", _render_bat(project_dir, fw_rel, render_jobs), "\r\n")
        _write_text(partial / "render.sh", _render_sh(project_dir, fw_rel, render_jobs))
        manifest = {
            "snapshot_format": SNAPSHOT_FORMAT,
            "name": name,
            "created": created,
            "deck": _rel(deck.path.resolve(), project_root.resolve()),
            "deck_name": deck.name,
            "project_dir": project_dir,
            "framework_dir": fw_rel,
            "source_date_epoch": epoch,
            "options": {"zip": options.zip, "texmf": options.texmf,
                        "app_included": options.include_app,
                        "reference_pdfs": options.reference_pdfs},
            "jobs": job_entries,
            "slidemage": {**app, "included": app_note or ""},
            "project": {"name": project_dir,
                        **_project_git_state(project_root, collected.project_files)},
            "tex": tex_environment(outputs, collected.tex_files, roots, fonts),
            "warnings": result.warnings,
        }
        _write_text(partial / "README.txt", _readme(manifest))
        manifest["files"] = build_manifest_files(partial)
        _write_text(partial / MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
        result.counts.update({"project": len(collected.project_files),
                         "framework": sum(1 for p in (partial / fw_rel).rglob("*") if p.is_file()),
                         "tex (recorded)": len(collected.tex_files),
                         "jobs": len(jobs),
                         "reused": sum(1 for out in outputs if out.reused_from)})

        # 4. Verify from the snapshot itself.
        _check_cancel(cancel)
        if options.verify:
            progress("verifying (rendering from the snapshot)")
            report = verify_folder(partial, log, cancel, check_hashes=False)
            for note in report.notes:
                log(f"    {note}")
            if not report.ok:
                raise SnapshotError("verification failed: " + "; ".join(report.problems[:5]))

        # 5. Finish: rename the folder, or zip it.
        _check_cancel(cancel)
        progress("finishing")
        if options.zip:
            target = directory / f"{name}.zip"
            write_zip(partial, target, name, when)
            shutil.rmtree(partial)
        else:
            target = directory / name
            replace_with_retry(partial, target)
        result.ok = True
        result.path = target
        result.size = _dir_size(target)
        if ensure_gitignored(project_root):
            log("    (added snapshots/ to the project's .gitignore)")
        log(f"==== Snapshot of {deck.name} -> {_rel(target, project_root)} "
            f"({format_size(result.size)}) ====")
        for warning in result.warnings:
            log(f"    warning: {warning}")
        return result
    except SnapshotError as exc:
        result.error = str(exc)
    except Exception as exc:  # noqa: BLE001 -- report, never leave a half snapshot
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        for wrapper in wrappers:
            wrapper.unlink(missing_ok=True)
        shutil.rmtree(build_root, ignore_errors=True)
        compiler._set_build_dir_active(build_root, False)
        if not result.ok and partial.exists():
            shutil.rmtree(partial, ignore_errors=True)
    log(f"*** Snapshot of {deck.name} FAILED: {result.error} ***")
    return result


def snapshot_decks(
    decks: list[Deck], options: SnapshotOptions, log: LogCallback,
    cancel: Optional[CancelToken] = None,
    progress: Optional[Callable[[int, int, str, str], None]] = None,
    delete_old: Optional[list[ExistingSnapshot]] = None,
    project_root: Path = PROJECT_ROOT,
) -> list[SnapshotResult]:
    """Snapshot `decks` one after the other. One deck's failure doesn't stop
    the others; a cancel stops the current deck and skips the rest. Each of
    `delete_old` (snapshots the user agreed to delete) goes to the trash only
    once its deck's new snapshot succeeded."""
    results: list[SnapshotResult] = []
    for i, deck in enumerate(decks, 1):
        if cancel is not None and cancel.is_set():
            results.append(SnapshotResult(deck.name, ok=False, error="skipped (stopped)",
                                          skipped=True))
            continue

        def step(text: str, i: int = i, deck: Deck = deck) -> None:
            if progress is not None:
                progress(i, len(decks), deck.name, text)

        result = create_snapshot(deck, options, log, cancel, step, project_root=project_root)
        if result.ok and delete_old:
            for old in delete_old:
                if old.deck_name != deck.name or not old.path.exists():
                    continue
                if move_to_trash(old.path):
                    result.deleted.append(old.path)
                    log(f"    (moved the older snapshot {old.path.name} to the trash)")
                else:
                    result.warnings.append(f"Could not move {old.path.name} to the trash; kept.")
                    log(f"    (could not move {old.path.name} to the trash -- kept)")
        results.append(result)
    return results


# --------------------------------------------------------------------------
# Command line

def _find_decks(names: list[str]) -> list[Deck]:
    from .deck_scan import scan_decks
    decks = scan_decks()
    chosen = []
    for name in names:
        stem = Path(name).stem if name.lower().endswith(".tex") else name
        matches = [d for d in decks if d.name == stem]
        if not matches:
            raise SystemExit(f"No deck named {stem!r} (decks/ or decks/archive/).")
        chosen.append(matches[0])
    return chosen


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m slidemage.deck_snapshot",
                                     description="Deck snapshots (see docs/DECK_SNAPSHOT_PLAN.md).")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="snapshot one or more decks into <project>/snapshots/")
    create.add_argument("decks", nargs="+", help="deck names or .tex files")
    create.add_argument("--zip", action="store_true", help="write a .zip instead of a folder")
    create.add_argument("--texmf", action="store_true", help="include LaTeX package files")
    create.add_argument("--with-app", action="store_true", help="include the SlideMage app")
    create.add_argument("--delete-old", action="store_true",
                        help="move older snapshots of these decks to the trash once the new one exists")
    create.add_argument("--no-reference-pdfs", action="store_true")
    create.add_argument("--no-presenter", action="store_true")
    create.add_argument("--no-verify", action="store_true")
    create.add_argument("--recompile", action="store_true",
                        help="compile every version, even those unchanged since their last compile")
    verify = sub.add_parser("verify", help="check a snapshot renders from itself, as recorded")
    verify.add_argument("path")
    sub.add_parser("list", help="list the project's snapshots")
    args = parser.parse_args(argv)

    def log(line: str) -> None:
        print(line, flush=True)

    if args.command == "list":
        for snap in find_snapshots():
            print(f"{snap.label}  {snap.path.name}")
        return 0
    if args.command == "verify":
        report = verify_snapshot(Path(args.path), log)
        for note in report.notes:
            print(f"note: {note}")
        for problem in report.problems:
            print(f"PROBLEM: {problem}")
        print("OK" if report.ok else "FAILED")
        return 0 if report.ok else 1
    decks = _find_decks(args.decks)
    options = SnapshotOptions(zip=args.zip, texmf=args.texmf, include_app=args.with_app,
                              reference_pdfs=not args.no_reference_pdfs,
                              verify=not args.no_verify, presenter=not args.no_presenter,
                              reuse=not args.recompile)
    old = find_snapshots([d.name for d in decks]) if args.delete_old else []
    started = time.monotonic()
    results = snapshot_decks(decks, options, log, delete_old=old)
    print()
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        where = r.path.name if r.path else r.error
        print(f"{status} {r.deck_name}: {where}" + (f" ({format_size(r.size)})" if r.ok else ""))
    print(f"({time.monotonic() - started:.0f}s)")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
