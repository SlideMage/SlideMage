from pathlib import Path
from types import SimpleNamespace
import os
import re
import time

import pytest

from slidemage import preview_build, slide_preview


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
    for invalid in (0, -1, '2', True):
        with pytest.raises(ValueError):
            slide_preview._overlay_line(invalid)


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
        return SimpleNamespace(stdout=iter([]), wait=lambda: None, returncode=int(fail))

    monkeypatch.setattr(preview_build.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    kwargs = dict(project_root=tmp_path, build_dir=tmp_path / '.build', env={}, fatal_error_re=re.compile('^!'))
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
        if age != 'none':
            lock = build / 'preview-cache' / key / 'build.lock'
            lock.parent.mkdir(parents=True)
            lock.touch()
            if age:
                os.utime(lock, (age, age))
    (decks / 'deck.tex').write_text('x')
    preview_build.prune_unused(tmp_path, build)
    assert sorted(p.name for p in decks.iterdir()) == ['_slidemage_preview-fresh.tex', 'deck.tex']
    assert (build / 'preview-cache' / 'fresh').exists() and not (build / 'preview-cache' / 'stale').exists()


def test_partial_previews_never_replace_full_slide_snapshot(monkeypatch):
    calls = []
    monkeypatch.setattr(slide_preview, '_compile_and_extract',
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    pre = r'\documentclass{beamer}\begin{document}'
    slide_preview.render_slide_to_pdf('slide', 'abc-EN-Test', preamble_text=pre, overlay=2)
    slide_preview.render_slide_text_to_pdf('abc-EN-Test', '$x$', preamble_text=pre, preview_mode='element')
    slide_preview.render_slide_text_to_pdf('abc-EN-Test', 'Text', preamble_text=pre, preview_mode='region')
    assert all(kwargs['snapshot_template'] is None for _, kwargs in calls)
    assert r'\SMCompileTimestampValue' in calls[0][0][0]
    assert slide_preview._preview_timestamp_line(False) == ''


def test_commented_frame_does_not_prevent_region_wrapper():
    _, body = slide_preview._region_source(r'\begin{document}', '% \\titleframe{demo}\nHello', 'region')
    assert body.startswith(r'\begin{frame}')


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
                               wait=lambda: None, returncode=12)

    monkeypatch.setattr(preview_build.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    kwargs = dict(project_root=tmp_path, build_dir=tmp_path / '.build', env={}, fatal_error_re=re.compile('^!'))
    preview_build.compile_cached(r'\begin{document}Hi', 'abc', print, **kwargs)
    produce = False
    with pytest.raises(RuntimeError):
        preview_build.compile_cached(r'\begin{document}Changed', 'abc', print, **kwargs)


def test_element_rejects_frame_only_options():
    pre = r'\documentclass{beamer}\begin{document}'
    for options in ({'overlay': 1}, {'presenter': True}):
        with pytest.raises(ValueError):
            slide_preview.render_slide_text_to_pdf(
                'abc-EN-Test', '$x$', preamble_text=pre, preview_mode='element', **options)
