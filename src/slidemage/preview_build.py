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
import subprocess
import tempfile
import time


@contextmanager
def build_lock(path: Path):
    """OS-owned lock, released on crashes as well as normal returns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            stream.write(b'\0')
            stream.flush()
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


WRAPPER_PREFIX = '_slidemage_preview-'
UNUSED_DAYS = 14


def prune_unused(project_root, build_dir):
    """Delete the wrappers in decks/ (and build caches) of previews not rendered for UNUSED_DAYS,
    and wrappers whose cache is gone. A cached job leaves its wrapper in decks/ so latexmk's
    dependency check keeps working, one per slide and preamble, so without this they pile up."""
    cache_root = build_dir / 'preview-cache'
    limit = time.time() - UNUSED_DAYS * 86400
    for wrapper in (project_root / 'decks').glob(WRAPPER_PREFIX + '*.tex'):
        cache = cache_root / wrapper.stem[len(WRAPPER_PREFIX):]
        lock = cache / 'build.lock'
        if lock.exists() and lock.stat().st_mtime > limit:
            continue
        wrapper.unlink(missing_ok=True)
        shutil.rmtree(cache, ignore_errors=True)


def compile_cached(wrapper_text, id_slug, log, *, project_root, build_dir, env,
                   fatal_error_re):
    preamble = wrapper_text.partition(r'\begin{document}')[0]
    configuration = {
        'root': str(project_root.resolve()), 'slide': id_slug, 'preamble': preamble,
        'search': {name: env.get(name, '') for name in
                   ('SLIDEMASTER_LATEX', 'TEXINPUTS', 'BIBINPUTS', 'PATH')},
        'rc': [(project_root / name).read_text(errors='replace')
               if (project_root / name).exists() else ''
               for name in ('.latexmkrc', 'decks/.latexmkrc')],
    }
    key = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()[:24]
    cache = build_dir / 'preview-cache' / key
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'build.lock').touch()
    prune_unused(project_root, build_dir)
    jobname = 'preview-' + key
    wrapper = project_root / 'decks' / ('_slidemage_' + jobname + '.tex')
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    with build_lock(cache / 'build.lock'):
        unstable = cache / 'rerun-limit'
        if unstable.exists():
            # Retaining oscillating layout state changes the next preview.
            # Start this job fresh until it manages to converge again.
            for generated in cache.glob(jobname + '.*'):
                generated.unlink(missing_ok=True)
        # Leave the source and outputs in place: rewriting an unchanged wrapper
        # would defeat latexmk's normal dependency check.
        if not wrapper.exists() or wrapper.read_bytes() != wrapper_text.encode('utf-8'):
            wrapper.write_text(wrapper_text, encoding='utf-8', newline='')
        cmd = ['latexmk', '-f', f'-jobname={jobname}',
               f'-outdir={cache.as_posix()}', f'-auxdir={cache.as_posix()}',
               str(wrapper.relative_to(project_root))]
        pdf = cache / (jobname + '.pdf')
        previous_pdf = pdf.stat().st_mtime_ns if pdf.exists() else None
        output_tail = deque(maxlen=200)
        log(f'==== Rendering {id_slug} (reusable build) ====')
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        try:
            proc = subprocess.Popen(cmd, cwd=project_root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors='replace', **kwargs)
        except FileNotFoundError as exc:
            raise RuntimeError('latexmk not found on PATH') from exc
        for line in proc.stdout:
            output_tail.append(line)
            log(line.rstrip('\n'))
        proc.wait()
        pdf = cache / (jobname + '.pdf')
        logfile = cache / (jobname + '.log')
        contents = logfile.read_text(errors='replace') if logfile.exists() else ''
        # The existing renderer accepts TeX-clean PDFs when latexmk reaches
        # its rerun limit (e.g. the manual's oscillating .top correction).
        # Preserve that behavior only for a PDF actually produced this run;
        # every other nonzero status still fails, including stale outputs.
        rerun_limit = (proc.returncode and pdf.exists()
                       and pdf.stat().st_mtime_ns != previous_pdf
                       and 'Maximum runs of' in ''.join(output_tail)
                       and 'needed too many passes' in ''.join(output_tail))
        if ((proc.returncode and not rerun_limit) or not pdf.exists() or not pdf.stat().st_size
                or not contents or fatal_error_re.search(contents)):
            # Never return a previous successful PDF after an unsuccessful edit.
            raise RuntimeError(f'Render failed for {id_slug}:\n' + '\n'.join(contents.splitlines()[-25:]))
        if rerun_limit:
            unstable.touch()
            log('    (PDF produced, but latexmk reached its rerun limit; layout may not be stable)')
        else:
            unstable.unlink(missing_ok=True)
        dest = Path(tempfile.mkdtemp(prefix='slidemage_preview_')) / (id_slug + '.pdf')
        shutil.copy2(pdf, dest)
        return dest
