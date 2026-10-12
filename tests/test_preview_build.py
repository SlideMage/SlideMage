from pathlib import Path
from types import SimpleNamespace
import os
import time

import pytest

from slidemage.project import ProjectContext, transitional_context
from slidemage import compiler, preview_build, preview_format, slide_preview


@pytest.fixture(autouse=True)
def _no_precompiled_preamble(monkeypatch):
    # These tests fake latexmk; the format tests below opt back in.
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '0')


def test_regions_and_elements_keep_preamble_and_validate():
    pre = r'\documentclass{beamer}\begin{document}'
    assert slide_preview._region_source(pre, 'Hello', 'region')[1] == '\\begin{frame}\nHello\n\\end{frame}'
    frame = r'\begin{standardframe}{Title}Hello\end{standardframe}'
    assert slide_preview._region_source(pre, frame, 'region')[1] == frame
    with pytest.raises(ValueError, match='complete frames'):
        slide_preview._region_source(pre, frame, 'element')
    p, b = slide_preview._region_source(pre, '$x^2$', 'element')
    assert p.index(r'\usepackage[active,tightpage]{preview}') < p.index(r'\begin{document}')
    assert b == '\\begin{preview}\n$x^2$\n\\end{preview}'


def test_overlay_does_not_change_action_defaults():
    assert slide_preview._overlay_line(None) == ''
    assert r'\gdef\beamer@whichframes{2}' in slide_preview._overlay_line(2)
    with pytest.raises(ValueError):
        slide_preview._overlay_line(0)


def test_cached_build_retains_aux_and_rejects_stale_pdf(tmp_path, monkeypatch):
    commands = []
    fail = False

    def popen(cmd, **kwargs):
        commands.append(cmd)
        cache = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-outdir=')))
        job = next(c.split('=', 1)[1] for c in cmd if c.startswith('-jobname='))
        (cache / (job + '.pdf')).write_bytes(b'old pdf')
        (cache / (job + '.aux')).write_text('remember me')
        (cache / (job + '.log')).write_text('! Bad edit' if fail else 'Success')
        return SimpleNamespace(stdout=iter([]), wait=lambda: int(fail), returncode=int(fail))

    monkeypatch.setattr(compiler.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    kwargs = dict(ctx=ProjectContext.at(tmp_path), env={})
    one = r'\documentclass{beamer}\begin{document}one\end{document}'
    two = one.replace('one', 'two')
    preview_build.compile_cached(one, 'abc', print, **kwargs)
    preview_build.compile_cached(two, 'abc', print, **kwargs)
    assert commands[0] == commands[1]  # one edit keeps the same dependency graph
    assert list((tmp_path / '.build').rglob('*.aux'))
    fail = True
    with pytest.raises(RuntimeError, match='Bad edit'):
        preview_build.compile_cached(two + '%broken', 'abc', print, **kwargs)


def test_unused_preview_wrappers_are_pruned(tmp_path):
    build = tmp_path / '.build'
    decks = tmp_path / 'decks'
    decks.mkdir()
    old = time.time() - (preview_build.UNUSED_DAYS + 1) * 86400
    for key, age in (('fresh', None), ('stale', old), ('nocache', 'none')):
        (decks / f'_slidemage_preview-{key}.tex').write_text('x')
        if age == 'none':
            os.utime(decks / f'_slidemage_preview-{key}.tex', (old, old))
        if age != 'none':
            lock = build / 'preview-cache' / key / 'build.lock'
            lock.parent.mkdir(parents=True)
            lock.touch()
            if age:
                os.utime(lock, (age, age))
    (decks / 'deck.tex').write_text('x')
    for key in ('new-unique', 'other'):
        (decks / f'_slidemage_preview-{key}.tex').write_text('job without a cache in this build root')
    preview_build.prune_unused(tmp_path, build)
    assert sorted(p.name for p in decks.iterdir()) == [
        '_slidemage_preview-fresh.tex', '_slidemage_preview-new-unique.tex',
        '_slidemage_preview-other.tex', 'deck.tex',
    ]
    assert (build / 'preview-cache' / 'fresh').exists() and not (build / 'preview-cache' / 'stale').exists()


def test_partial_previews_never_replace_full_slide_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(slide_preview, 'compile_and_extract',
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    pre = r'\documentclass{beamer}\begin{document}'
    slide_preview.render_slide_to_pdf(transitional_context(), 'slide', 'abc-EN-Test', preamble_text=pre, overlay=2)
    slide_preview.render_slide_text_to_pdf(transitional_context(), 'abc-EN-Test', '$x$', preamble_text=pre, preview_mode='element')
    slide_preview.render_slide_text_to_pdf(transitional_context(), 'abc-EN-Test', 'Text', preamble_text=pre, preview_mode='region')
    assert all(kwargs['snapshot_template'] is None for _, kwargs in calls)
    assert r'\SMCompileTimestampValue' in calls[0][0][1]
    assert slide_preview._preview_timestamp_line(False) == ''


def test_rerun_limit_accepts_only_a_new_clean_pdf(tmp_path, monkeypatch):
    produce = True

    def popen(cmd, **kwargs):
        cache = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-outdir=')))
        job = next(c.split('=', 1)[1] for c in cmd if c.startswith('-jobname='))
        if produce:
            (cache / (job + '.pdf')).write_bytes(b'fresh output')
        (cache / (job + '.log')).write_text('Successful TeX pass')
        return SimpleNamespace(stdout=iter(['Maximum runs of lualatex reached\n',
                                           'lualatex needed too many passes\n']),
                               wait=lambda: 12, returncode=12)

    monkeypatch.setattr(compiler.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    kwargs = dict(ctx=ProjectContext.at(tmp_path), env={})
    preview_build.compile_cached(r'\begin{document}Hi', 'abc', print, **kwargs)
    produce = False
    with pytest.raises(RuntimeError):
        preview_build.compile_cached(r'\begin{document}Changed', 'abc', print, **kwargs)


def test_element_rejects_frame_only_options():
    pre = r'\documentclass{beamer}\begin{document}'
    for options in ({'overlay': 1}, {'presenter': True}):
        with pytest.raises(ValueError):
            slide_preview.render_slide_text_to_pdf(transitional_context(), 
                'abc-EN-Test', '$x$', preamble_text=pre, preview_mode='element', **options)


def _fake_engine(monkeypatch, log='Success\nBeginning to dump on file preamble.fmt\n', make_fmt=True):
    """Stand in for `lualatex -ini`: writes the format, its log and recorder file."""
    runs = []

    def run(cmd, **kwargs):
        runs.append(cmd)
        out = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-output-directory=')))
        if make_fmt:
            (out / 'preamble.fmt').write_bytes(b'format')
        (out / 'preamble.log').write_text(log)
        package = out.parents[2] / 'package.sty'  # outside the format's own directory
        package.write_text(package.read_text() if package.exists() else 'x')
        (out / 'preamble.fls').write_text(f'PWD {out}\nINPUT {package}\n')
        return SimpleNamespace(returncode=1)  # the dump's own Lua noise makes TeX exit 1

    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '1')
    monkeypatch.setattr(preview_format.shutil, 'which', lambda *a, **k: '/bin/lualatex')
    monkeypatch.setattr(preview_format.subprocess, 'run', run)
    return runs


def _ensure(tmp_path, preamble=r'\documentclass{beamer}'):
    return preview_format.ensure(
        preamble, 'key', project_root=tmp_path, build_dir=tmp_path / '.build', env={},
        log=lambda line: None, lock=preview_build.build_lock)


def test_format_is_built_once_and_rebuilt_when_an_input_changes(tmp_path, monkeypatch):
    runs = _fake_engine(monkeypatch)
    first = _ensure(tmp_path)
    assert first and (first / 'preamble.fmt').is_file()
    text = (first / 'preamble.tex').read_text()
    assert text.startswith(r'\documentclass{beamer}') and text.rstrip().endswith(r'\dump')
    assert (first / 'capture.lua').is_file() and 'SMLuaReplayList' in text
    package = tmp_path / 'package.sty'
    assert preview_format.inputs(first) == [str(package)]
    assert _ensure(tmp_path) == first and len(runs) == 1  # unchanged inputs: reused
    package.write_text('changed, and longer')
    assert _ensure(tmp_path) == first and len(runs) == 2  # an input changed: rebuilt


def test_format_noise_after_the_preamble_is_not_a_failure_but_real_errors_are(tmp_path, monkeypatch):
    noise = ('Success\n)...uni-algos/lua-uni-stage-tables.lua:141: attempt to per\n'
             'Beginning to dump on file preamble.fmt\n')
    _fake_engine(monkeypatch, log=noise)
    assert _ensure(tmp_path)
    _fake_engine(monkeypatch, log='./deck.tex:12: Undefined control sequence.\nBeginning to dump on file x\n')
    assert _ensure(tmp_path / 'other') is None
    _fake_engine(monkeypatch, log='Success\n')  # never reached \dump
    assert _ensure(tmp_path / 'third') is None


def test_slide_failing_only_with_the_format_is_rebuilt_without_it_and_the_format_disabled(
        tmp_path, monkeypatch):
    _fake_engine(monkeypatch)
    commands = []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        cache = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-outdir=')))
        job = next(c.split('=', 1)[1] for c in cmd if c.startswith('-jobname='))
        with_format = any(c.startswith('-lualatex=') for c in cmd)
        if not with_format:
            (cache / (job + '.pdf')).write_bytes(b'pdf')
        (cache / (job + '.log')).write_text('! Format breaks this' if with_format else 'Success')
        return SimpleNamespace(stdout=iter([]), wait=lambda: int(with_format), returncode=int(with_format))

    monkeypatch.setattr(compiler.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    kwargs = dict(ctx=ProjectContext.at(tmp_path), env={})
    wrapper = r'\documentclass{beamer}\begin{document}one\end{document}'
    pdf = preview_build.compile_cached(wrapper, 'abc', print, **kwargs)
    assert pdf.is_file()
    assert any(c.startswith('-lualatex=') for c in commands[0])
    assert 'TeX' not in ''.join(commands[0])
    assert not any(c.startswith('-lualatex=') for c in commands[1])
    # The format stays disabled: the next request goes straight to the ordinary build.
    preview_build.compile_cached(wrapper, 'abc', print, **kwargs)
    assert not any(c.startswith('-lualatex=') for c in commands[2])
    assert len(commands) == 3
