# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import time

import pytest

from slidemage.project import ProjectContext
from slidemage import compiler, preview_build, preview_format, slide_preview
from conftest import EXAMPLE_PROJECT


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
    slide_preview.render_slide_to_pdf(EXAMPLE_PROJECT, 'slide', 'abc-EN-Test', preamble_text=pre, overlay=2)
    slide_preview.render_slide_text_to_pdf(EXAMPLE_PROJECT, 'abc-EN-Test', '$x$', preamble_text=pre, preview_mode='element')
    slide_preview.render_slide_text_to_pdf(EXAMPLE_PROJECT, 'abc-EN-Test', 'Text', preamble_text=pre, preview_mode='region')
    assert all(kwargs['snapshot_template'] is None for _, kwargs in calls)


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
            slide_preview.render_slide_text_to_pdf(EXAMPLE_PROJECT, 
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
    # an executable that exists everywhere: the build's configuration key stats what `which` found
    monkeypatch.setattr(preview_format.shutil, 'which', lambda *a, **k: sys.executable)
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


def test_format_invalidates_same_size_mtime_content_and_new_shadow(tmp_path, monkeypatch):
    runs = _fake_engine(monkeypatch)
    first = _ensure(tmp_path)
    package = tmp_path / 'package.sty'
    previous = package.stat()
    package.write_text('y')
    os.utime(package, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert _ensure(tmp_path) == first and len(runs) == 2
    (tmp_path / 'new-shadow.sty').write_text('new search candidate')
    assert _ensure(tmp_path) == first and len(runs) == 3


def test_format_noise_after_the_preamble_is_not_a_failure_but_real_errors_are(tmp_path, monkeypatch):
    noise = ('Success\n)...uni-algos/lua-uni-stage-tables.lua:141: attempt to per\n'
             'Beginning to dump on file preamble.fmt\n')
    _fake_engine(monkeypatch, log=noise)
    assert _ensure(tmp_path)
    _fake_engine(monkeypatch, log='./deck.tex:12: Undefined control sequence.\nBeginning to dump on file x\n')
    assert _ensure(tmp_path / 'other') is None
    _fake_engine(monkeypatch, log='Success\n')  # never reached \dump
    assert _ensure(tmp_path / 'third') is None


def test_format_build_gives_tex_forward_slashes_and_reloads_fontspecs_lua(tmp_path, monkeypatch):
    runs = _fake_engine(monkeypatch)
    directory = _ensure(tmp_path)
    source, output = runs[0][-1], next(c for c in runs[0] if c.startswith('-output-directory='))
    assert '\\' not in source and '\\' not in output        # TeX reads `\.build` in a Windows path as a command
    assert source == (directory / 'preamble.tex').as_posix()
    assert r'\directlua{require("fontspec")}' in (directory / 'preamble.tex').read_text()


def test_fmt_option_names_the_file_for_miktex_and_uses_texformats_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(preview_format, '_is_miktex', lambda env: True)
    assert preview_format.fmt_option(tmp_path, {'A': '1'}) == (
        '-fmt=' + (tmp_path / 'preamble.fmt').as_posix(), {'A': '1'})       # MiKTeX ignores TEXFORMATS
    monkeypatch.setattr(preview_format, '_is_miktex', lambda env: False)
    option, env = preview_format.fmt_option(tmp_path, {'A': '1'})
    assert option == '-fmt=preamble' and env == {'A': '1', 'TEXFORMATS': str(tmp_path) + os.pathsep}


@pytest.mark.skipif(not preview_format.shutil.which('lualatex'), reason='needs LuaLaTeX')
def test_a_real_format_loads_and_fontspec_works_after_it(tmp_path, monkeypatch):
    """The real engine, in a folder whose Windows path has `\\.build` in it: the format builds, loads (MiKTeX:
    through the full path), and a slide that calls fontspec's Lua side runs without errors."""
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '1')
    (tmp_path / 'decks').mkdir()
    preamble = '\\documentclass{article}\n\\usepackage{fontspec}\n'
    directory = preview_format.ensure(preamble, 'real', project_root=tmp_path, build_dir=tmp_path / '.build',
                                      env=dict(os.environ), log=lambda line: None, lock=preview_build.build_lock)
    assert directory is not None and (directory / 'preamble.fmt').is_file()
    (tmp_path / 'decks' / 'body.tex').write_text(
        '\\begin{document}\\addfontfeatures{Numbers=OldStyle}0123 '
        '\\directlua{assert(fontspec, "fontspec Lua missing")}\\end{document}\n', encoding='utf-8')
    option, env = preview_format.fmt_option(directory, dict(os.environ))
    import subprocess
    done = subprocess.run(['lualatex', option, '-interaction=nonstopmode', 'body.tex'], cwd=tmp_path / 'decks',
                          env=env, capture_output=True, text=True, errors='replace', timeout=300)
    assert done.returncode == 0, done.stdout[-2000:]
    assert 'attempt to' not in done.stdout and (tmp_path / 'decks' / 'body.pdf').is_file()


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


def test_recorder_expands_format_inputs_without_depending_on_generated_format(tmp_path):
    root = tmp_path / 'project'
    out = root / '.build/preview-cache/slide'
    fmt = root / '.build/preview-formats/key'
    fmt.mkdir(parents=True)
    out.mkdir(parents=True)
    source = root / 'slides/one.tex'
    theme = tmp_path / 'framework/theme.tex'
    fls = out / 'slide.fls'
    fls.write_text(f'PWD {root}\nINPUT {fmt / "preamble.fmt"}\nINPUT {fmt / "capture.lua"}\nINPUT {source}\n')
    deps = preview_build.recorded_inputs(fls, out / 'missing.fdb_latexmk',
                                        project_root=root, cache=out, extra=[str(theme)])
    assert deps == sorted([str(source), str(theme)])


# -- luaotfload's font-cache race (several LuaLaTeX runs starting at once) -------------------------------------------

RACE_LOG = ('luaotfload | load :     x "...luaotfload-init.lua:301: system : no wr\n'
            'iteable cache path, quiting".\n! Font \\TU/FiraSans-Light.otf(0)/m/n/6 not loadable: metric data not found')


def test_the_font_cache_race_is_recognised_across_tex_line_breaks():
    assert preview_build.font_cache_race(RACE_LOG)
    assert not preview_build.font_cache_race('! Undefined control sequence.')


def _latexmk_runs(monkeypatch, tmp_path, logs):
    """A fake latexmk: each run returns the next log of `logs` (a clean one writes a PDF)."""
    runs = []

    def run_latexmk(command, *, jobname, outdir, **kwargs):
        log_text = logs[len(runs)]
        runs.append(list(command))
        pdf = outdir / f'{jobname}.pdf'
        if 'not loadable' not in log_text:
            pdf.write_bytes(b'%PDF fake')
        return compiler.Build(0 if pdf.exists() else 1, pdf, outdir / f'{jobname}.log', log_text, False)
    monkeypatch.setattr(compiler, 'run_latexmk', run_latexmk)
    monkeypatch.setattr(preview_build, '_pause', lambda seconds, cancel=None: None)
    ctx = SimpleNamespace(root=tmp_path, decks_dir=tmp_path / 'decks')
    (tmp_path / 'decks').mkdir(exist_ok=True)
    out = tmp_path / 'out'
    out.mkdir(exist_ok=True)
    wrapper = tmp_path / 'decks' / 'w.tex'
    wrapper.write_text('x')
    call = lambda: preview_build.run_preview(ctx, wrapper, 'job', 'abc-EN-Test', out, lambda line: None, env={},  # noqa: E731
                                             reusable=False)
    return runs, call


def test_a_run_that_lost_the_font_cache_race_runs_again_with_all_passes(tmp_path, monkeypatch):
    runs, call = _latexmk_runs(monkeypatch, tmp_path, [RACE_LOG, 'Output written on job.pdf'])
    pdf, _ = call()
    assert pdf.is_file() and len(runs) == 2
    assert '-g' not in runs[0] and '-g' in runs[1]


def test_a_race_that_persists_fails_as_font_cache_busy_and_keeps_the_format(tmp_path, monkeypatch):
    runs, call = _latexmk_runs(monkeypatch, tmp_path, [RACE_LOG] * preview_build.FONT_CACHE_ATTEMPTS)
    with pytest.raises(preview_build.FontCacheBusy):
        call()
    assert len(runs) == preview_build.FONT_CACHE_ATTEMPTS
    fmt = tmp_path / 'fmt'
    fmt.mkdir()
    monkeypatch.setattr(preview_format, 'ensure', lambda *a, **k: fmt)

    def busy(*args, **kwargs):
        raise preview_build.FontCacheBusy('Render failed for abc-EN-Test')
    monkeypatch.setattr(preview_build, '_compile_cached', busy)
    ctx = SimpleNamespace(root=tmp_path, build_dir=tmp_path / '.build')
    with pytest.raises(preview_build.FontCacheBusy):
        preview_build.compile_cached(r'\documentclass{beamer}\begin{document}x', 'abc-EN-Test', lambda line: None,
                                     ctx=ctx, env={})
    assert not (fmt / 'format.bad').exists()               # not the format's fault: still used next time


def test_a_format_build_that_lost_the_race_is_not_marked_bad(tmp_path, monkeypatch):
    _fake_engine(monkeypatch, log=RACE_LOG)
    assert _ensure(tmp_path) is None
    assert not list((tmp_path / '.build' / 'preview-formats').glob('*/format.bad'))


def test_preview_builds_read_slidemages_own_latexmk_settings(tmp_path, monkeypatch):
    """-r names a file with PREVIEW_LATEXMKRC (rewritten when someone changed it), and the wrapper names a missing
    .run.xml; both are part of the configuration key, so changing them starts fresh build state."""
    commands, wrappers = [], []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        cache = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-outdir=')))
        job = next(c.split('=', 1)[1] for c in cmd if c.startswith('-jobname='))
        wrappers.append((tmp_path / cmd[-1]).read_text(encoding='utf-8'))
        (cache / (job + '.pdf')).write_bytes(b'pdf')
        (cache / (job + '.log')).write_text('Success')
        return SimpleNamespace(stdout=iter([]), wait=lambda: 0, returncode=0)

    monkeypatch.setattr(compiler.subprocess, 'Popen', popen)
    monkeypatch.setattr(preview_build.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    ctx = ProjectContext.at(tmp_path)
    text = r'\documentclass{beamer}\begin{document}one\end{document}'
    preview_build.compile_cached(text, 'abc', print, ctx=ctx, env={})
    rc = Path(commands[0][commands[0].index('-r') + 1])
    assert rc.read_text(encoding='utf-8') == preview_build.PREVIEW_LATEXMKRC
    assert "$normalize_names = 0;" in preview_build.PREVIEW_LATEXMKRC
    assert r"'^\\\\abx\@aux\@read\@bbl" in preview_build.PREVIEW_LATEXMKRC      # Perl: a literal backslash
    assert wrappers[0].startswith(r'\documentclass{beamer}\begin{document}' + preview_build.RUN_XML_NOTE + 'one')
    rc.write_text('edited', encoding='utf-8')
    preview_build.compile_cached(text, 'abc', print, ctx=ctx, env={})
    assert rc.read_text(encoding='utf-8') == preview_build.PREVIEW_LATEXMKRC
    key = preview_build.configuration_key(text, 'abc', tmp_path, {})
    monkeypatch.setattr(preview_build, 'PREVIEW_LATEXMKRC', preview_build.PREVIEW_LATEXMKRC + '# more\n')
    assert preview_build.configuration_key(text, 'abc', tmp_path, {}) != key


def test_the_framework_names_a_missing_ovl_and_top_like_latex_names_a_missing_aux():
    base = (Path(__file__).resolve().parents[1] / 'latex' / 'Slidemaster_preamble_base.tex').read_text(encoding='utf-8')
    for ext in ('ovl', 'top'):
        assert rf'\InputIfFileExists{{\jobname.{ext}}}{{}}{{\typeout{{No file \jobname.{ext}.}}}}' in base


needs_tex_tools = pytest.mark.skipif(not all(preview_format.shutil.which(tool) for tool in ('latexmk', 'lualatex', 'biber')),
                                     reason='needs latexmk, LuaLaTeX and biber')


def _citing_project(tmp_path):
    """A project under the temp folder (where Git-for-Windows Perl spells the path /tmp/...) and the text of a citing
    slide with a framework-style helper file (read at \\begin{document} with a "No file" line, then rewritten)."""
    (tmp_path / 'decks').mkdir()
    # As a project's own .latexmkrc: $do_cd puts latexmk in decks/, so it names the build folder by its full path, as
    # the .fls does (from the project root it would name it relative to it: one more spelling of every file).
    (tmp_path / '.latexmkrc').write_text(
        "$do_cd = 1;\n$pdf_mode = 4;\n$lualatex = 'lualatex -interaction=nonstopmode -file-line-error %O %S';\n",
        encoding='utf-8')
    (tmp_path / 'decks' / 'refs.bib').write_text('@book{knuth, author={Donald Knuth}, title={The TeXbook}, year={1984}}\n',
                                       encoding='utf-8')
    text = '\n'.join([
        r'\documentclass{article}', r'\usepackage[backend=biber]{biblatex}', r'\addbibresource{refs.bib}',
        r'\newwrite\helper',
        r'\AtBeginDocument{\InputIfFileExists{\jobname.hlp}{}{\typeout{No file \jobname.hlp.}}'
        r'\immediate\openout\helper=\jobname.hlp\immediate\write\helper{\relax}\immediate\closeout\helper}',
        # \fullcite, as the slides cite (a \textcite changes the .bcf in the second run: a real reason for more)
        r'\begin{document}', r'See \fullcite{knuth}.', r'\end{document}', ''])
    return ProjectContext.at(tmp_path), text


def _rules_run(text, ctx, *, force):
    """The rules latexmk ran for one cached build, from the 'Run number' lines of its log."""
    lines = []
    pdf = preview_build.compile_cached(text, 'abc-EN-Test', lines.append, ctx=ctx, env=compiler.build_env(ctx),
                                       force=force)
    assert pdf.is_file()
    runs = [line for line in lines if line.startswith('Run number')]
    return [run.split("'")[1].split()[0] for run in runs], lines


@needs_tex_tools
def test_a_first_render_with_a_bibliography_settles_in_two_lualatex_runs(tmp_path):
    r"""The real tools: a citing slide needs lualatex, biber, lualatex -- latexmk ran a third LuaLaTeX before
    PREVIEW_LATEXMKRC and RUN_XML_NOTE."""
    ctx, text = _citing_project(tmp_path)
    rules, lines = _rules_run(text, ctx, force=True)
    assert rules == ['lualatex', 'biber', 'lualatex'], '\n'.join(lines[-80:])


@needs_tex_tools
def test_a_forced_render_reruns_every_rule_only_when_the_text_is_unchanged(tmp_path):
    """-g only for what latexmk cannot see (an input edited with its time restored): a slide edit makes it run
    LuaLaTeX alone, no biber."""
    ctx, text = _citing_project(tmp_path)
    _rules_run(text, ctx, force=True)
    rules, lines = _rules_run(text.replace('See', 'Also see'), ctx, force=True)
    assert rules == ['lualatex'], '\n'.join(lines[-80:])
    rules, lines = _rules_run(text.replace('See', 'Also see'), ctx, force=True)
    assert 'lualatex' in rules and 'biber' in rules, '\n'.join(lines[-80:])
