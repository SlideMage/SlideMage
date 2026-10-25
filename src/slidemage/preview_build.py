# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable latexmk builds for interactive previews.

Keep TeX's own dependency graph and auxiliary files between edits. This caches
build state, not slide pixels: latexmk still checks every recorded input. Each
preamble/slide pair has a separate job and an interprocess lock.
"""
from __future__ import annotations

from contextlib import contextmanager
import dataclasses
from collections import deque
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Optional
import shutil
import tempfile
import time
import re
import threading
from .fileio import atomic_write
from .filelock import build_lock, check_cancel
from .preview_metrics import measure, stage, record_line, finish_rules
from . import compiler, preview_format
from .preview_cache import find_tool
from .project import ProjectContext

_ACTIVE_LOCK = threading.RLock()
_ACTIVE = {}


@contextmanager
def active_build(cache: Path, wrapper: Path, cancel=None, *, root: Optional[Path] = None):
    """Reserve paths before mutation; maintenance cannot race a preview process. `root` is the project (or
    background workspace) whose maintenance lock is taken; by default the folder above the wrapper's decks/."""
    paths = (cache.resolve(), wrapper.resolve())
    # This lock stays outside removable .build entries. POSIX readers may
    # compile concurrently; Windows uses its exclusive byte-lock primitive.
    with build_lock(maintenance_lock(root if root is not None else wrapper.parent.parent), shared=True, cancel=cancel):
        with _ACTIVE_LOCK:
            for path in paths:
                _ACTIVE[path] = _ACTIVE.get(path, 0) + 1
        try:
            yield
        finally:
            with _ACTIVE_LOCK:
                for path in paths:
                    _ACTIVE[path] -= 1
                    if not _ACTIVE[path]:
                        del _ACTIVE[path]


def is_active(path: Path) -> bool:
    path = path.resolve()
    with _ACTIVE_LOCK:
        return any(path.is_relative_to(active) or active.is_relative_to(path) for active in _ACTIVE)


def maintenance_lock(project_root: Path) -> Path:
    return project_root / '.previews' / 'preview-maintenance.lock'


@contextmanager
def cleanup_guard(paths, project_root: Path):
    """Check and delete under one reservation lock; skip live external builds."""
    with _ACTIVE_LOCK:
        if any(is_active(path) for path in paths):
            yield False
            return
        with build_lock(maintenance_lock(project_root), blocking=False) as acquired:
            yield acquired


# Single-slide renders leave their PDF in a folder of its own under the OS temp directory (see
# slide_preview.sweep_old_renders).
RENDER_FOLDER_PREFIX = 'slidemage_preview_'
WRAPPER_PREFIX = '_slidemage_preview-'
# A project's preview wrappers live in .build/preview-wrappers/ (v8.58.0; before, in decks/ beside the decks, where
# they piled up in the user's folder). latexmk still runs in decks/, so TeX sees the same folders (run_preview).
# A background workspace keeps them in its own decks/, outside the project.
WRAPPER_FOLDER = 'preview-wrappers'
UNUSED_DAYS = 14


def wrapper_dir(ctx: ProjectContext) -> Path:
    """Where a project's preview wrappers are written."""
    return ctx.build_dir / WRAPPER_FOLDER


def recorded_inputs(fls: Path, database: Path, *, project_root: Path, cache: Path,
                    extra=()) -> list[str]:
    """TeX recorder plus latexmk's bibliography inputs, excluding generated output."""
    cwd = project_root / 'decks'
    names = list(extra)
    if fls.is_file():
        for line in fls.read_text(errors='replace').splitlines():
            if line.startswith('PWD '):
                cwd = Path(line[4:])
            elif line.startswith('INPUT '):
                names.append(line[6:])
    if database.is_file():
        # Recorded names are quoted, with spaces kept; unescape only quotes/backslashes. A source latexmk recorded
        # as missing (size -1: a bibliography biber was never run for, named as the .bcf gives it) fed nothing.
        for name, size in re.findall(r'^\s+"((?:[^"\\]|\\.)*)"\s+[\d.]+\s+(-?\d+)', database.read_text(errors='replace'),
                                     re.M):
            if size != '-1':
                names.append(name.replace('\\"', '"').replace('\\\\', '\\'))
    paths = set()
    formats = project_root / '.build' / 'preview-formats'
    cache_roots = (cache.absolute(), cache.resolve(), formats.absolute(), formats.resolve())
    for name in set(names):
        path = Path(name)
        # Normalize . and .. without repeated filesystem/symlink walks for the
        # hundreds of TeX package/font inputs. stat in watch follows symlinks.
        path = Path(os.path.abspath(path if path.is_absolute() else cwd / path))
        if not any(path.is_relative_to(root) for root in cache_roots) and not path.name.startswith(WRAPPER_PREFIX):
            paths.add(str(path))
    return sorted(paths)


def write_inputs(pdf: Path, fls: Path, database: Path, *, project_root: Path, cache: Path,
                extra=()):
    pdf.with_suffix('.inputs.json').write_text(json.dumps(recorded_inputs(
        fls, database, project_root=project_root, cache=cache, extra=extra)), encoding='utf-8')


PRUNE_EVERY = 600.0      # seconds between two prune_unused passes over one folder (maybe_prune_unused)
_PRUNED: dict[str, float] = {}
_PRUNED_LOCK = threading.Lock()


def maybe_prune_unused(project_root: Path, build_dir: Path, *, clock=time.monotonic) -> bool:
    """prune_unused, at most once per PRUNE_EVERY for a folder; whether it ran. A render ran it before every compile:
    a pass looks at every wrapper under a lock each (the background workspace holds hundreds, three per slide since
    v8.49.0), so the background workers queued behind one another there, could not stop when told to, and took the
    time the window needed (v8.52.2). Wrappers become old in UNUSED_DAYS: once in ten minutes loses nothing."""
    key, now = str(project_root), clock()
    with _PRUNED_LOCK:
        last = _PRUNED.get(key)
        if last is not None and now - last < PRUNE_EVERY:
            return False
        _PRUNED[key] = now
    prune_unused(project_root, build_dir)
    return True


@measure('prune')
def prune_unused(project_root: Path, build_dir: Path):
    """Delete the wrappers (and build caches) of previews not rendered for UNUSED_DAYS, and wrappers whose cache
    is gone. A cached job keeps its wrapper so latexmk's dependency check keeps working, one per slide and
    preamble, so without this they pile up. Wrappers are in build_dir/WRAPPER_FOLDER, in a background workspace's
    decks/, and, from before v8.58.0, in a project's decks/ (remove_legacy_wrappers deletes those at once)."""
    cache_root = build_dir / 'preview-cache'
    limit = time.time() - UNUSED_DAYS * 86400
    wrappers = [*(project_root / 'decks').glob(WRAPPER_PREFIX + '*.tex'),
                *(build_dir / WRAPPER_FOLDER).glob(WRAPPER_PREFIX + '*.tex')]
    for wrapper in wrappers:
        cache = cache_root / wrapper.stem[len(WRAPPER_PREFIX):]
        lock = cache / 'build.lock'
        with cleanup_guard((cache, wrapper), project_root) as permitted:
            if not permitted:
                continue
            try:
                # A missing cache alone does not make another root's wrapper old.
                if lock.exists():
                    if lock.stat().st_mtime > limit:
                        continue
                elif wrapper.stat().st_mtime > limit:
                    continue
                wrapper.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
            shutil.rmtree(cache, ignore_errors=True)


_LEGACY_SWEPT: set[str] = set()


def remove_legacy_wrappers(ctx: ProjectContext) -> int:
    """Delete the preview wrappers SlideMage before v8.58.0 left in the project's decks/ (once per project and
    session); how many. Nothing reads them any more: a render writes its wrapper to wrapper_dir() and keeps its
    cache, which is found by the same key."""
    key = str(Path(os.path.abspath(ctx.root)))
    with _PRUNED_LOCK:
        if key in _LEGACY_SWEPT:
            return 0
        _LEGACY_SWEPT.add(key)
    removed = 0
    for wrapper in ctx.decks_dir.glob(WRAPPER_PREFIX + '*.tex'):
        with cleanup_guard((wrapper,), ctx.root) as permitted:
            if permitted:
                wrapper.unlink(missing_ok=True)
                removed += 1
    return removed


# latexmk settings of SlideMage's own, for preview builds only (passed with -r after the project's rc files; deck
# compiles never see them). Without them a slide's first render runs LuaLaTeX three times where two settle it:
# * biblatex writes the checksum of the .bbl it read into the .aux ("nohash" in the first run), and the logreq flags
#   in .run.xml flip after biber ran; latexmk saw the .aux/.run.xml change and ran once more. It tracks the .bbl
#   itself, so those lines are left out of its checksums.
# * latexmk's name normalisation turns the build folder into Git-for-Windows Perl's /c/..., /tmp/... spelling while
#   LuaLaTeX's .fls says C:/...; latexmk then saw every helper file twice and the second name as newly in use.
#   Previews give -outdir/-auxdir themselves, so nothing needs normalising.
# Perl single quotes: '\\\\' is a regex backslash.
PREVIEW_LATEXMKRC = r"""# Written by SlideMage (preview_build.PREVIEW_LATEXMKRC) for preview builds; rewritten when it differs.
$hash_calc_ignore_pattern{'aux'} = '^\\\\abx\@aux\@read\@bbl(?:\@mdfivesum|rerun)';
$hash_calc_ignore_pattern{'xml'} = '^\s*<(?:internal|external) package="biblatex"';
$normalize_names = 0;
"""
# biblatex reads .run.xml silently at the end of the document, so latexmk learned of it only when the second run read
# it, and ran a third to be safe. A missing one now prints the line LaTeX prints for a missing .aux, which latexmk
# reads (the framework does the same for .ovl and .top). After \begin{document}: what precedes it may be the format.
RUN_XML_NOTE = (r'\ifcsname ver@biblatex.sty\endcsname\IfFileExists{\jobname.run.xml}{}'
                r'{\typeout{No file \jobname.run.xml.}}\fi' '\n')


def preview_latexmkrc(build_dir: Path) -> Path:
    """The PREVIEW_LATEXMKRC file in `build_dir`, written if missing or different."""
    path = build_dir / 'preview.latexmkrc'
    try:
        current = path.read_text(encoding='utf-8')
    except OSError:
        current = None
    if current != PREVIEW_LATEXMKRC:
        atomic_write(path, PREVIEW_LATEXMKRC)
    return path


def with_run_xml_note(wrapper_text: str) -> str:
    return wrapper_text.replace('\\begin{document}', '\\begin{document}' + RUN_XML_NOTE, 1)


# The view and language lines of a slide wrapper (slide_preview._deck_version_line, _deck_language_line). Instructor
# writes no .ovl, the student views do, so a view change flips helper files and makes latexmk run LuaLaTeX again.
_VIEW_LINES = re.compile(r'^\\deck(?:version|language)\[[^\]\n]*\]$', re.M)


def view_variant(wrapper_text: str) -> str:
    """The view and language a wrapper sets after \\begin{document}, ahead of its \\setSlideID: with the slide,
    the identity of a build folder. (The presenter mode is a line before the preamble, so the preamble's key has it.)"""
    body = wrapper_text.partition(r'\begin{document}')[2]
    return '|'.join(_VIEW_LINES.findall(body.partition(r'\setSlideID')[0]))


@measure('cache_configuration')
def configuration_key(wrapper_text, id_slug, project_root: Path, env):
    preamble = wrapper_text.partition(r'\begin{document}')[0]
    rc_paths = [project_root / name for name in ('.latexmkrc', 'decks/.latexmkrc')]
    # latexmk also reads user/system rc files. Changes must not reuse old state.
    user_home = Path(env.get('HOME') or env.get('USERPROFILE') or Path.home())
    rc_paths += [user_home / '.latexmkrc',
                 Path(env.get('XDG_CONFIG_HOME', str(user_home / '.config'))) / 'latexmk/latexmkrc',
                 Path('/etc/LatexMk')]
    if env.get('LATEXMKRCSYS'):
        rc_paths.append(Path(env['LATEXMKRCSYS']))
    tools = {}
    for name in ('latexmk', 'lualatex', 'pdflatex', 'xelatex', 'biber', 'bibtex'):
        executable = find_tool(name, env.get('PATH'))
        if executable:
            path = Path(executable).resolve()
            info = path.stat()
            tools[name] = (str(path), info.st_size, info.st_mtime_ns)
    configuration = {
        'schema': 3,                    # 3: PREVIEW_LATEXMKRC and RUN_XML_NOTE
        'preview_rc': PREVIEW_LATEXMKRC, 'run_xml_note': RUN_XML_NOTE,
        'root': str(project_root.resolve()), 'slide': id_slug, 'preamble': preamble,
        'search': {name: value for name, value in env.items() if name.startswith(
            ('TEX', 'LUA', 'BIB', 'FONTCONFIG', 'LATEXMK', 'MIKTEX')) or name in
            ('SLIDEMAGE_LATEX', 'PATH', 'SOURCE_DATE_EPOCH', 'OSFONTDIR', 'VARTEXFONTS')},
        'tools': tools,
        'rc': [(str(path), path.read_text(errors='replace') if path.is_file() else '') for path in rc_paths],
    }
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()[:24]


def compile_cached(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, cancel=None, force=False,
                   workspace: Optional[Path] = None):
    """Build with the preamble precompiled when that works, else the ordinary way.

    A run that fails only with the format is repeated without it, so a preamble
    the format cannot reproduce costs one slower build, never a wrong preview.

    `force` makes latexmk rerun every rule (-g), but only when the slide's wrapper is unchanged: a changed wrapper
    reruns LuaLaTeX alone, which reads every input again. Accepted edge case: a .bib (or other input) edited with
    its time and size restored in the same render as a slide text change is not seen by biber, as with latexmk itself.
    """
    check_cancel(cancel)
    if workspace is not None:
        # Background renders keep everything of theirs outside the project: the wrapper, the build caches and
        # the precompiled format live in `workspace`; TeX still runs in the project's decks/ folder.
        ctx = dataclasses.replace(ctx, build_dir=workspace / 'build')
    preamble, marker, body = wrapper_text.partition(r'\begin{document}')
    format_dir = None
    if marker:
        format_dir = preview_format.ensure(
            preamble, configuration_key(wrapper_text, '', ctx.root, env),
            project_root=ctx.root, build_dir=ctx.build_dir, env=env, log=log, lock=build_lock, cancel=cancel)
    if format_dir is not None:
        try:
            return _compile_cached(marker + body, id_slug, log, ctx=ctx, env=env,
                                   key_text=wrapper_text, format_dir=format_dir, cancel=cancel, force=force, workspace=workspace)
        except FontCacheBusy:
            raise                       # not the format's fault: keep it
        except RuntimeError as exc:
            check_cancel(cancel)
            log(f'    (precompiled preamble run failed: {str(exc).splitlines()[0][:100]}; retrying without it)')
    pdf = _compile_cached(wrapper_text, id_slug, log, ctx=ctx, env=env, key_text=wrapper_text, format_dir=None, cancel=cancel,
                          force=force, workspace=workspace)
    if format_dir is not None:
        # The slide builds without the format but not with it: stop using it.
        preview_format.disable(format_dir)
    return pdf


def _compile_cached(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, key_text, format_dir, cancel=None,
                    force=False, workspace: Optional[Path] = None):
    # One build folder per view: the format key (compile_cached) stays per preamble.
    variant = view_variant(key_text)
    key = configuration_key(key_text, id_slug + '|' + variant if variant else id_slug, ctx.root, env)
    if format_dir is not None:
        # A rebuilt format means changed preamble inputs, which latexmk's own
        # dependency list (only the slide's) cannot see: use fresh state.
        built = (format_dir / 'preamble.fmt').stat().st_mtime_ns
        key = key[:16] + hashlib.sha256(f'{built}'.encode()).hexdigest()[:8]
    cache = ctx.build_dir / 'preview-cache' / key
    root = workspace if workspace is not None else ctx.root
    maybe_prune_unused(root, ctx.build_dir)
    if workspace is None:
        remove_legacy_wrappers(ctx)
    check_cancel(cancel)            # told to stop while waiting: before the build, not after it
    jobname = 'preview-' + key
    folder = workspace / 'decks' if workspace is not None else wrapper_dir(ctx)
    wrapper = folder / ('_slidemage_' + jobname + '.tex')
    with active_build(cache, wrapper, cancel, root=root):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / 'build.lock').touch()
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        with build_lock(cache / 'build.lock', cancel=cancel):
            return _compile_reserved(wrapper_text, id_slug, log, ctx=ctx, env=env,
                                     cache=cache, wrapper=wrapper, jobname=jobname,
                                     format_dir=format_dir, cancel=cancel, force=force)


def _compile_reserved(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, cache, wrapper, jobname, format_dir=None, cancel=None, force=False):
    unstable = cache / 'rerun-limit'
    if unstable.exists():
        # Retaining oscillating layout state changes the next preview.
        # Start this job fresh until it manages to converge again.
        for generated in cache.glob(jobname + '.*'):
            generated.unlink(missing_ok=True)
    wrapper_text = with_run_xml_note(wrapper_text)
    # Leave the source and outputs in place: rewriting an unchanged wrapper
    # would defeat latexmk's normal dependency check.
    changed = not wrapper.exists() or wrapper.read_bytes() != wrapper_text.encode('utf-8')
    if changed:
        with stage('wrapper_write'):
            wrapper.write_text(wrapper_text, encoding='utf-8', newline='')
    # Returned previews contain only a temporary PDF, so a SyncTeX file in
    # this private build directory cannot be used by the external viewer.
    options = ['-synctex=0', '-r', preview_latexmkrc(ctx.build_dir).as_posix()]
    if force and not changed:
        # Go mode: a changed wrapper makes latexmk run LuaLaTeX, which reads every input again, so only an
        # unchanged one needs -g to see an input edited with its time and size restored.
        options.append('-g')
    if format_dir is not None:
        # The project's .latexmkrc command line plus -fmt; the wrapper is the slide only.
        fmt, env = preview_format.fmt_option(format_dir, env)
        options.append('-lualatex=lualatex ' + fmt + ' -interaction=nonstopmode -file-line-error %O %S')
    log(f'==== Rendering {id_slug} (reusable build) ====')
    pdf, rerun_limit = run_preview(ctx, wrapper, jobname, id_slug, cache, log, env=env, reusable=True,
                                   options=options, cancel=cancel)
    if rerun_limit:
        unstable.touch()
        log('    (PDF produced, but latexmk reached its rerun limit; layout may not be stable)')
    else:
        unstable.unlink(missing_ok=True)
    return publish_preview(ctx, pdf, id_slug, cache, jobname,
                           extra=preview_format.inputs(format_dir) if format_dir is not None else ())


FONT_CACHE_ATTEMPTS = 3
_FONT_CACHE_RACE = preview_format._FONT_CACHE_RACE


class FontCacheBusy(RuntimeError):
    """Every attempt lost luaotfload's font-cache race (font_cache_race): a failure of the moment, not the slide's
    or the precompiled preamble's."""


def font_cache_race(log_text: str) -> bool:
    """Did luaotfload give up because it found its font cache "not writable"? It tests that by creating and
    deleting a file of one fixed name in the cache folder, so LuaLaTeX runs that start at the same moment can make
    each other fail it (Windows refuses to open a file that is being deleted). Without luaotfload every font is
    missing, and MiKTeX spends about a second per font trying to make one. TeX wraps log lines, so line breaks are
    ignored."""
    return _FONT_CACHE_RACE in log_text.replace('\r', '').replace('\n', '')


def _pause(seconds: float, cancel=None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        check_cancel(cancel)
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def run_preview(ctx: ProjectContext, wrapper: Path, jobname: str, id_slug: str, outdir: Path, log, *, env, reusable: bool,
                options=(), cancel=None) -> tuple[Path, bool]:
    """latexmk on a preview wrapper into `outdir`: the one execution of a fresh build (a folder of its
    own, .build/) and a reusable one (its cache folder, keeping latexmk's state between edits).
    Returns the PDF and whether latexmk gave up at its rerun limit. Raises RuntimeError (with the
    log's tail) unless the run produced a good PDF.

    Only a reusable build can hold a previous run's PDF, so only it also fails on a nonzero exit; it
    accepts one a TeX-clean PDF is produced for when latexmk reaches its rerun limit (the manual's
    oscillating .top correction), and never returns a previous successful PDF after an unsuccessful
    edit. A fresh build keeps latexmk's auxiliary files where .latexmkrc puts them ($aux_dir is
    this same .build/), so it passes no -auxdir."""
    check_cancel(cancel)
    pdf = outdir / (jobname + '.pdf')
    previous_pdf = pdf.stat().st_mtime_ns if pdf.exists() else None
    output_tail = deque(maxlen=200)

    def on_line(line):
        output_tail.append(line)
        record_line(line)

    if Path(os.path.abspath(wrapper.parent)) != Path(os.path.abspath(ctx.decks_dir)):
        # The wrapper is not in decks/: in .build/preview-wrappers/, or outside the project (a background render).
        # latexmk's rc files make it change into the source's folder, so it is told not to, and runs in decks/
        # itself: TeX then sees the same folders as for a wrapper in decks/ (the ../ of the deck preambles). The
        # project's own rc file is read from there.
        ctx.decks_dir.mkdir(parents=True, exist_ok=True)       # latexmk's folder, even before the first deck
        rc = ctx.decks_dir / '.latexmkrc'
        # -cd- after the -r: latexmk applies its arguments in order, and a project rc file may set $do_cd.
        extra = (['-r', str(ctx.root / '.latexmkrc')] if not rc.is_file() and (ctx.root / '.latexmkrc').is_file() else []) + ['-cd-']
        command = compiler.latexmk_command(wrapper, jobname, outdir, '-f', *extra, *options, cwd=ctx.decks_dir, aux=reusable,
                                           absolute=True)
        run_cwd = ctx.decks_dir
    else:
        command = compiler.latexmk_command(wrapper, jobname, outdir, '-f', *options, cwd=ctx.root, aux=reusable)
        run_cwd = ctx.root
    for attempt in range(1, FONT_CACHE_ATTEMPTS + 1):
        with stage('latexmk'):
            try:
                build = compiler.run_latexmk(
                    command, jobname=jobname, outdir=outdir, cwd=run_cwd, env=env, log=log, on_line=on_line, bufsize=-1, cancel=cancel)
            except FileNotFoundError as exc:
                raise RuntimeError('latexmk not found on PATH -- is a TeX distribution installed?') from exc
            finish_rules()
        check_cancel(cancel)
        if attempt == FONT_CACHE_ATTEMPTS or not font_cache_race(build.log_text):
            break
        # luaotfload lost a race for its font cache (see font_cache_race): the slide is fine, the run is not. Again,
        # all passes, after a moment so the processes that started with it are past their start.
        log('    (font cache busy: several LuaLaTeX runs started at once; running this one again)')
        _pause(random.uniform(0.2, 1.0), cancel)
        if '-g' not in command:
            command.insert(command.index('-f') + 1, '-g')
        output_tail.clear()
    tail = ''.join(output_tail)
    rerun_limit = bool(reusable and build.returncode and pdf.exists() and pdf.stat().st_mtime_ns != previous_pdf
                       and 'Maximum runs of' in tail and 'needed too many passes' in tail)
    if not build.ok or (reusable and build.returncode and not rerun_limit):
        error = FontCacheBusy if font_cache_race(build.log_text) else RuntimeError
        raise error(f'Render failed for {id_slug}:\n' + '\n'.join(build.log_text.splitlines()[-25:]))
    return pdf, rerun_limit


def publish_preview(ctx: ProjectContext, pdf: Path, id_slug: str, outdir: Path, jobname: str, *, extra=(), copy=shutil.copy2) -> Path:
    """Copy a built preview PDF to a folder of its own in the temp directory (named after the slide
    for a sane viewer title) and write its recorded inputs beside it."""
    dest = Path(tempfile.mkdtemp(prefix=RENDER_FOLDER_PREFIX)) / (id_slug + '.pdf')
    with stage('pdf_copy'):
        copy(pdf, dest)
    with stage('dependencies'):
        write_inputs(dest, outdir / (jobname + '.fls'), outdir / (jobname + '.fdb_latexmk'),
                     project_root=ctx.root, cache=outdir, extra=extra)
    return dest
