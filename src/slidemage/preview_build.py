"""Reusable latexmk builds for interactive previews.

Keep TeX's own dependency graph and auxiliary files between edits. This caches
build state, not slide pixels: latexmk still checks every recorded input. Each
preamble/slide pair has a separate job and an interprocess lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import re
import threading
from .filelock import build_lock, check_cancel
from .preview_metrics import measure, stage, record_line, finish_rules
from . import compiler, preview_format
from .project import ProjectContext

_ACTIVE_LOCK = threading.RLock()
_ACTIVE = {}


@contextmanager
def active_build(cache: Path, wrapper: Path, cancel=None):
    """Reserve paths before mutation; maintenance cannot race a preview process."""
    paths = (cache.resolve(), wrapper.resolve())
    # This lock stays outside removable .build entries. POSIX readers may
    # compile concurrently; Windows uses its exclusive byte-lock primitive.
    with build_lock(maintenance_lock(wrapper.parent.parent), shared=True, cancel=cancel):
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
UNUSED_DAYS = 14


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
        # Recorded names are quoted, with spaces kept; unescape only quotes/backslashes.
        for name in re.findall(r'^\s+"((?:[^"\\]|\\.)*)"\s+\d', database.read_text(errors='replace'), re.M):
            names.append(name.replace('\\"', '"').replace('\\\\', '\\'))
    paths = set()
    cache_roots = (cache.absolute(), cache.resolve())
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


@measure('prune')
def prune_unused(project_root: Path, build_dir: Path):
    """Delete the wrappers in decks/ (and build caches) of previews not rendered for UNUSED_DAYS,
    and wrappers whose cache is gone. A cached job leaves its wrapper in decks/ so latexmk's
    dependency check keeps working, one per slide and preamble, so without this they pile up."""
    cache_root = build_dir / 'preview-cache'
    limit = time.time() - UNUSED_DAYS * 86400
    for wrapper in (project_root / 'decks').glob(WRAPPER_PREFIX + '*.tex'):
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
        executable = shutil.which(name, path=env.get('PATH'))
        if executable:
            path = Path(executable).resolve()
            info = path.stat()
            tools[name] = (str(path), info.st_size, info.st_mtime_ns)
    configuration = {
        'schema': 2,
        'root': str(project_root.resolve()), 'slide': id_slug, 'preamble': preamble,
        'search': {name: value for name, value in env.items() if name.startswith(
            ('TEX', 'LUA', 'BIB', 'FONTCONFIG', 'LATEXMK', 'MIKTEX')) or name in
            ('SLIDEMASTER_LATEX', 'PATH', 'SOURCE_DATE_EPOCH', 'OSFONTDIR', 'VARTEXFONTS')},
        'tools': tools,
        'rc': [(str(path), path.read_text(errors='replace') if path.is_file() else '') for path in rc_paths],
    }
    return hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()[:24]


def compile_cached(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, cancel=None):
    """Build with the preamble precompiled when that works, else the ordinary way.

    A run that fails only with the format is repeated without it, so a preamble
    the format cannot reproduce costs one slower build, never a wrong preview.
    """
    check_cancel(cancel)
    preamble, marker, body = wrapper_text.partition(r'\begin{document}')
    format_dir = None
    if marker:
        format_dir = preview_format.ensure(
            preamble, configuration_key(wrapper_text, '', ctx.root, env),
            project_root=ctx.root, build_dir=ctx.build_dir, env=env, log=log, lock=build_lock, cancel=cancel)
    if format_dir is not None:
        try:
            return _compile_cached(marker + body, id_slug, log, ctx=ctx, env=env,
                                   key_text=wrapper_text, format_dir=format_dir, cancel=cancel)
        except RuntimeError as exc:
            check_cancel(cancel)
            log(f'    (precompiled preamble run failed: {str(exc).splitlines()[0][:100]}; retrying without it)')
    pdf = _compile_cached(wrapper_text, id_slug, log, ctx=ctx, env=env, key_text=wrapper_text, format_dir=None, cancel=cancel)
    if format_dir is not None:
        # The slide builds without the format but not with it: stop using it.
        preview_format.disable(format_dir)
    return pdf


def _compile_cached(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, key_text, format_dir, cancel=None):
    key = configuration_key(key_text, id_slug, ctx.root, env)
    if format_dir is not None:
        # A rebuilt format means changed preamble inputs, which latexmk's own
        # dependency list (only the slide's) cannot see: use fresh state.
        built = (format_dir / 'preamble.fmt').stat().st_mtime_ns
        key = key[:16] + hashlib.sha256(f'{built}'.encode()).hexdigest()[:8]
    cache = ctx.build_dir / 'preview-cache' / key
    prune_unused(ctx.root, ctx.build_dir)
    jobname = 'preview-' + key
    wrapper = ctx.root / 'decks' / ('_slidemage_' + jobname + '.tex')
    with active_build(cache, wrapper, cancel):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / 'build.lock').touch()
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        with build_lock(cache / 'build.lock', cancel=cancel):
            return _compile_reserved(wrapper_text, id_slug, log, ctx=ctx, env=env,
                                     cache=cache, wrapper=wrapper, jobname=jobname,
                                     format_dir=format_dir, cancel=cancel)


def _compile_reserved(wrapper_text, id_slug, log, *, ctx: ProjectContext, env, cache, wrapper, jobname, format_dir=None, cancel=None):
    unstable = cache / 'rerun-limit'
    if unstable.exists():
        # Retaining oscillating layout state changes the next preview.
        # Start this job fresh until it manages to converge again.
        for generated in cache.glob(jobname + '.*'):
            generated.unlink(missing_ok=True)
    # Leave the source and outputs in place: rewriting an unchanged wrapper
    # would defeat latexmk's normal dependency check.
    if not wrapper.exists() or wrapper.read_bytes() != wrapper_text.encode('utf-8'):
        with stage('wrapper_write'):
            wrapper.write_text(wrapper_text, encoding='utf-8', newline='')
    # Returned previews contain only a temporary PDF, so a SyncTeX file in
    # this private build directory cannot be used by the external viewer.
    options = ['-synctex=0']
    if format_dir is not None:
        # The project's .latexmkrc command line plus -fmt; the wrapper is the slide only.
        # Found through TEXFORMATS: a path given to -fmt names the recorder file.
        options.append('-lualatex=lualatex -fmt=' + preview_format.NAME
                       + ' -interaction=nonstopmode -file-line-error %O %S')
        env = dict(env, TEXFORMATS=str(format_dir) + os.pathsep)
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

    with stage('latexmk'):
        try:
            build = compiler.run_latexmk(
                compiler.latexmk_command(wrapper, jobname, outdir, '-f', *options, cwd=ctx.root, aux=reusable),
                jobname=jobname, outdir=outdir, cwd=ctx.root, env=env, log=log, on_line=on_line, bufsize=-1, cancel=cancel)
        except FileNotFoundError as exc:
            raise RuntimeError('latexmk not found on PATH -- is a TeX distribution installed?') from exc
        finish_rules()
    check_cancel(cancel)
    tail = ''.join(output_tail)
    rerun_limit = bool(reusable and build.returncode and pdf.exists() and pdf.stat().st_mtime_ns != previous_pdf
                       and 'Maximum runs of' in tail and 'needed too many passes' in tail)
    if not build.ok or (reusable and build.returncode and not rerun_limit):
        raise RuntimeError(f'Render failed for {id_slug}:\n' + '\n'.join(build.log_text.splitlines()[-25:]))
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
