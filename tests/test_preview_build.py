# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from types import SimpleNamespace
import json
import os
import shutil
import sys
import time

import pytest

from slidemage.project import ProjectContext
from slidemage import compiler, preview_build, preview_format


@pytest.fixture(autouse=True)
def _no_precompiled_preamble(monkeypatch):
    # These tests fake latexmk; the format tests below opt back in.
    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '0')
    monkeypatch.setattr(preview_build, 'DIRECT_LUALATEX', False)


def test_cached_preview_reuses_build_state_and_recovers_from_a_missing_input(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    dependency = tmp_path / 'SlideMage_setup.tex'
    dependency.touch()
    commands = []

    def run(command, *, jobname, outdir, **kwargs):
        commands.append(command)
        pdf, log, aux = (outdir / f'{jobname}.{ext}' for ext in ('pdf', 'log', 'aux'))
        failed = not dependency.exists() or (log.exists() and 'not found' in log.read_text() and '-g' not in command)
        message = "! LaTeX Error: File 'SlideMage_setup.tex' not found." if failed else 'Success'
        log.write_text(message)
        if not failed:
            pdf.write_bytes(b'%PDF fresh')
            aux.touch()
        return compiler.Build(int(failed), pdf, log, message, False)

    monkeypatch.setattr(compiler, 'run_latexmk', run)
    text = r'\documentclass{beamer}\begin{document}one\end{document}'

    def compile_text(wrapper):
        return preview_build.compile_cached(wrapper, 'abc', print, ctx=ctx, env={})

    compile_text(text)
    wrapper = Path(commands[0][-1])
    rc = Path(commands[0][commands[0].index('-r') + 1])
    settings = preview_build.PREVIEW_LATEXMKRC
    assert rc.read_text(encoding='utf-8') == settings
    assert "$normalize_names = 0;" in settings and r"'^\\\\abx\@aux\@read\@bbl" in settings
    assert wrapper.read_text(encoding='utf-8').startswith(
        r'\documentclass{beamer}\begin{document}' + preview_build.RUN_XML_NOTE + 'one')

    rc.write_text('edited', encoding='utf-8')
    compile_text(text.replace('one', 'two'))
    assert rc.read_text(encoding='utf-8') == settings
    assert commands[0] == commands[1] and list(ctx.build_dir.rglob('*.aux'))

    dependency.unlink()
    broken = text.replace('one', 'three')
    with pytest.raises(RuntimeError, match='not found'):
        compile_text(broken)
    dependency.touch()
    compile_text(broken)
    compile_text(broken)
    assert '-g' in commands[-2] and '-g' not in commands[-1]

    key = preview_build.configuration_key(text, 'abc', tmp_path, {})
    monkeypatch.setattr(preview_build, 'PREVIEW_LATEXMKRC', settings + '# more\n')
    assert preview_build.configuration_key(text, 'abc', tmp_path, {}) != key


def test_unused_preview_wrappers_and_formats_are_pruned(tmp_path):
    build = tmp_path / '.build'
    decks, wrappers = tmp_path / 'decks', build / preview_build.WRAPPER_FOLDER
    decks.mkdir()
    wrappers.mkdir(parents=True)
    now = time.time()
    old = now - (preview_build.UNUSED_DAYS + 1) * 86400
    recent = now - 86400
    caches, formats = build / 'preview-cache', build / 'preview-formats'

    def touch_at(path, age):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        os.utime(path, (age, age))

    for label, age in (('fresh', recent), ('stale', old)):
        for folder in (decks, wrappers):
            key = f'{folder.name}-{label}'
            (folder / f'_slidemage_preview-{key}.tex').touch()
            touch_at(caches / key / 'build.lock', age)
        touch_at(formats / label / 'build.lock', age)
    retained = formats / 'three-days' / 'build.lock'
    touch_at(retained, now - 3 * 86400)
    touch_at(decks / '_slidemage_preview-orphan.tex', old)
    fresh_orphan = decks / '_slidemage_preview-recent-orphan.tex'
    fresh_orphan.touch()
    real_deck = decks / 'course.tex'
    real_deck.touch()

    preview_build.prune_unused(tmp_path, build)
    assert set(decks.iterdir()) == {real_deck, fresh_orphan, decks / '_slidemage_preview-decks-fresh.tex'}
    assert [p.name for p in wrappers.iterdir()] == [f'_slidemage_preview-{wrappers.name}-fresh.tex']
    assert {p.name for p in caches.iterdir()} == {'decks-fresh', f'{wrappers.name}-fresh'}
    assert {p.name for p in formats.iterdir()} == {'fresh', 'three-days'}
    preview_build.prune_unused(tmp_path, build, 2)
    assert not retained.exists()
    with preview_build.active_build(build, decks, root=tmp_path):
        preview_build.prune_unused(tmp_path, build, 0)
        assert (caches / 'decks-fresh').exists() and (formats / 'fresh').exists()
    preview_build.prune_unused(tmp_path, build, 0)
    assert list(caches.iterdir()) == list(formats.iterdir()) == list(wrappers.iterdir()) == []
    assert list(decks.iterdir()) == [real_deck]


def test_rerun_limit_accepts_only_a_new_clean_pdf(tmp_path, monkeypatch):
    produce = True

    def run(command, *, jobname, outdir, on_line, **kwargs):
        pdf = outdir / f'{jobname}.pdf'
        if produce:
            pdf.write_bytes(b'fresh output')
        on_line('Maximum runs of lualatex reached\n')
        on_line('lualatex needed too many passes\n')
        return compiler.Build(12, pdf, outdir / f'{jobname}.log', 'Successful TeX pass', False)

    monkeypatch.setattr(compiler, 'run_latexmk', run)
    kwargs = dict(ctx=ProjectContext.at(tmp_path), env={})
    preview_build.compile_cached(r'\begin{document}Hi', 'abc', print, **kwargs)
    produce = False
    with pytest.raises(RuntimeError):
        preview_build.compile_cached(r'\begin{document}Changed', 'abc', print, **kwargs)


def _fake_engine(monkeypatch, log='Success\nBeginning to dump on file preamble.fmt\n'):
    """Stand in for `lualatex -ini`: writes the format, its log and recorder file."""
    runs = []

    def run(cmd, **kwargs):
        runs.append(cmd)
        out = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-output-directory=')))
        (out / 'preamble.fmt').write_bytes(b'format')
        (out / 'preamble.log').write_text(log)
        package = out.parents[2] / 'package.sty'  # outside the format's own directory
        package.write_text(package.read_text() if package.exists() else 'x')
        (out / 'preamble.fls').write_text(f'PWD {out}\nINPUT {package}\n')
        return SimpleNamespace(returncode=1)  # the dump's own Lua noise makes TeX exit 1

    monkeypatch.setenv('SLIDEMAGE_PREVIEW_FORMAT', '1')
    # an executable that exists everywhere: the build's configuration key stats what `which` found
    monkeypatch.setattr(shutil, 'which', lambda *a, **k: sys.executable)
    monkeypatch.setattr(preview_format.subprocess, 'run', run)
    return runs


def _ensure(tmp_path):
    return preview_format.ensure(
        r'\documentclass{beamer}', 'key', project_root=tmp_path, build_dir=tmp_path / '.build', env={},
        log=lambda line: None, lock=preview_build.build_lock)


def test_format_is_reused_until_its_inputs_or_search_paths_change(tmp_path, monkeypatch):
    runs = _fake_engine(monkeypatch)
    first = _ensure(tmp_path)
    assert first and (first / 'preamble.fmt').is_file()
    text = (first / 'preamble.tex').read_text()
    assert text.startswith(r'\documentclass{beamer}') and text.rstrip().endswith(r'\dump')
    assert (first / 'capture.lua').is_file() and 'SMLuaReplayList' in text
    assert r'\directlua{require("fontspec")}' in text
    assert runs[0][-1] == (first / 'preamble.tex').as_posix()
    assert f'-output-directory={first.as_posix()}' in runs[0]
    package = tmp_path / 'package.sty'
    assert preview_format.inputs(first) == [str(package)]
    assert _ensure(tmp_path) == first and len(runs) == 1

    previous = package.stat()
    package.write_text('y')
    os.utime(package, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert _ensure(tmp_path) == first and len(runs) == 2
    (tmp_path / 'decks' / 'package.sty').write_text('shadows the one the format read')
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


def test_fmt_option_names_the_file_for_miktex_and_uses_texformats_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(preview_format, '_is_miktex', lambda env: True)
    assert preview_format.fmt_option(tmp_path, {'A': '1'}) == (
        '-fmt=' + (tmp_path / 'preamble.fmt').as_posix(), {'A': '1'})       # MiKTeX ignores TEXFORMATS
    monkeypatch.setattr(preview_format, '_is_miktex', lambda env: False)
    option, env = preview_format.fmt_option(tmp_path, {'A': '1'})
    assert option == '-fmt=preamble' and env == {'A': '1', 'TEXFORMATS': str(tmp_path) + os.pathsep}


@pytest.mark.skipif(not shutil.which('lualatex'), reason='needs LuaLaTeX')
def test_a_real_format_loads_and_fontspec_works_after_it(tmp_path, monkeypatch):
    """Load a real format and exercise fontspec's Lua code."""
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

    def run(command, *, jobname, outdir, **kwargs):
        commands.append(command)
        with_format = any(c.startswith('-lualatex=') for c in command)
        pdf = outdir / f'{jobname}.pdf'
        if not with_format:
            pdf.write_bytes(b'pdf')
        return compiler.Build(int(with_format), pdf, outdir / f'{jobname}.log',
                              '! Format breaks this' if with_format else 'Success', False)

    monkeypatch.setattr(compiler, 'run_latexmk', run)
    kwargs = dict(ctx=ProjectContext.at(tmp_path), env={})
    wrapper = r'\documentclass{beamer}\begin{document}one\end{document}'
    pdf = preview_build.compile_cached(wrapper, 'abc', print, **kwargs)
    assert pdf.is_file()
    preview_build.compile_cached(wrapper, 'abc', print, **kwargs)
    assert [any(c.startswith('-lualatex=') for c in cmd) for cmd in commands] == [True, False, False]
    assert 'TeX' not in ''.join(commands[0])


def test_recorder_normalizes_inputs_and_filters_only_generated_paths(tmp_path):
    root = tmp_path / 'project with spaces'
    out = root / '.build/preview-cache/slide'
    out.mkdir(parents=True)
    fls = out / 'slide.fls'
    source = root / 'slides/one.tex'
    sibling = out.with_name('slide-extra') / 'input.tex'
    framework = root / '.build/preview-formats-extra/theme.tex'
    generated = root / '.build/preview-formats/key'
    theme = tmp_path / 'framework/theme.tex'
    fls.write_text(f'PWD {root / "decks"}\nINPUT ../slides/./one.tex\nINPUT {source}\n'
                   f'INPUT {out / "slide.aux"}\nINPUT {sibling}\nINPUT {framework}\n'
                   f'INPUT {generated / "preamble.fmt"}\nINPUT {generated / "capture.lua"}\n'
                   'INPUT _slidemage_preview-wrapper.tex\n')
    database = out / 'slide.fdb_latexmk'
    database.write_text('  "../references with spaces.bib" 123 42 abc\n'
                        '  "../missing.bib" 0 -1 0\n')
    deps = preview_build.recorded_inputs(fls, database, ctx=ProjectContext.at(root), cache=out, extra=[str(theme)])
    assert deps == sorted(map(str, (source, sibling, framework, theme, root / 'references with spaces.bib')))


RACE_LOG = ('luaotfload | load :     x "...luaotfload-init.lua:301: system : no wr\n'
            'iteable cache path, quiting".\n! Font \\TU/FiraSans-Light.otf(0)/m/n/6 not loadable: metric data not found')


def test_the_font_cache_race_is_recognised_across_tex_line_breaks():
    assert preview_build.font_cache_race(RACE_LOG)
    assert not preview_build.font_cache_race('! Undefined control sequence.')


def _latexmk_runs(monkeypatch, tmp_path, logs):
    """Replay latexmk logs, writing a PDF after a clean pass."""
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
    ctx = ProjectContext.at(tmp_path)
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
    ctx = ProjectContext.at(tmp_path)
    with pytest.raises(preview_build.FontCacheBusy):
        preview_build.compile_cached(r'\documentclass{beamer}\begin{document}x', 'abc-EN-Test', lambda line: None,
                                     ctx=ctx, env={})
    assert not (fmt / 'format.bad').exists()               # not the format's fault: still used next time


def test_a_format_build_that_lost_the_race_is_not_marked_bad(tmp_path, monkeypatch):
    _fake_engine(monkeypatch, log=RACE_LOG)
    assert _ensure(tmp_path) is None
    assert not list((tmp_path / '.build' / 'preview-formats').glob('*/format.bad'))


def test_the_framework_names_a_missing_ovl_and_top_like_latex_names_a_missing_aux():
    base = (Path(__file__).resolve().parents[1] / 'latex' / 'SlideMage_base.tex').read_text(encoding='utf-8')
    for ext in ('ovl', 'top'):
        assert rf'\InputIfFileExists{{\jobname.{ext}}}{{}}{{\typeout{{No file \jobname.{ext}.}}}}' in base


needs_tex_tools = pytest.mark.skipif(not all(shutil.which(tool) for tool in ('latexmk', 'lualatex', 'biber')),
                                     reason='needs latexmk, LuaLaTeX and biber')


def _citing_project(tmp_path):
    """A citing slide with a framework-style generated helper file."""
    (tmp_path / 'decks').mkdir()
    # Exercise a project rc that tells latexmk to change directories.
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
def test_citing_preview_uses_a_build_wrapper_and_only_reruns_needed_rules(tmp_path):
    ctx, text = _citing_project(tmp_path)
    rules, lines = _rules_run(text, ctx, force=False)
    assert rules == ['lualatex', 'biber', 'lualatex'], '\n'.join(lines[-80:])
    assert [p.name for p in ctx.decks_dir.iterdir()] == ['refs.bib']
    assert len(list(preview_build.wrapper_dir(ctx).glob('_slidemage_preview-*.tex'))) == 1

    edited = text.replace('See', 'Also see')
    rules, lines = _rules_run(edited, ctx, force=True)
    assert rules == ['lualatex'], '\n'.join(lines[-80:])
    rules, lines = _rules_run(edited, ctx, force=True)
    assert 'lualatex' in rules and 'biber' in rules, '\n'.join(lines[-80:])


def _in_view(text, view):
    """Model a framework helper file whose contents depend on the selected view."""
    return text.replace(r'\begin{document}', '\n'.join([
        r'\newcommand{\deckversion}[1][]{\gdef\viewname{#1}}\newwrite\viewfile',
        r'\AtBeginDocument{\InputIfFileExists{\jobname.vw}{}{\typeout{No file \jobname.vw.}}}',
        r'\AtEndDocument{\immediate\openout\viewfile=\jobname.vw\immediate\write\viewfile{\noexpand\gdef\noexpand\seen{\viewname}}'
        r'\immediate\closeout\viewfile}',
        r'\begin{document}', f'\\deckversion[{view}]']), 1)


def test_each_view_and_language_has_a_build_folder_of_its_own(tmp_path, monkeypatch):
    caches = []
    monkeypatch.setattr(preview_build, '_compile_reserved', lambda *a, **k: caches.append(k['cache']) or tmp_path)
    ctx = ProjectContext.at(tmp_path)

    def folder(view, language='', text='one'):
        wrapper = '\\documentclass{beamer}\n\\deckversion[instructor]\n\\begin{document}\n' + view
        wrapper += language + f'\\setSlideID{{abc}}\n{text} \\deckversion[inside]\n'
        preview_build.compile_cached(wrapper, 'abc', lambda _: None, ctx=ctx, env={})
        return caches[-1]

    instructor, course = folder('\\deckversion[instructor]\n'), folder('\\deckversion[during-course]\n')
    german = folder('\\deckversion[during-course]\n', '\\decklanguage[DE]\n')
    assert len({instructor, course, german}) == 3
    # the same view with other slide text, and the cache folder of the wrapper's name, stay the same
    assert folder('\\deckversion[instructor]\n', text='two') == instructor
    assert folder('\\deckversion[during-course]\n', text='two') == course
    assert folder('') != instructor


@needs_tex_tools
def test_returning_to_a_view_runs_lualatex_once(tmp_path):
    """Each view keeps its own helper file between edits."""
    ctx, text = _citing_project(tmp_path)
    views = [_in_view(text, view) for view in ('instructor', 'during-course')]
    for wrapper in views:
        _rules_run(wrapper, ctx, force=True)
    for wrapper in views:
        rules, lines = _rules_run(wrapper.replace('See', 'See once more'), ctx, force=True)
        assert rules == ['lualatex'], '\n'.join(lines[-80:])


def test_the_wrapper_pass_runs_at_most_once_in_ten_minutes_per_folder(tmp_path, monkeypatch):
    # Every render ran it: the background workers queued behind one another over hundreds of wrappers (v8.52.2).
    ran = []
    monkeypatch.setattr(preview_build, "prune_unused", lambda root, build, days: ran.append(root))
    now = {"t": 1000.0}
    clock = lambda: now["t"]
    one, two = tmp_path / "one", tmp_path / "two"
    assert preview_build.maybe_prune_unused(one, tmp_path, clock=clock)
    assert not preview_build.maybe_prune_unused(one, tmp_path, clock=clock)
    assert preview_build.maybe_prune_unused(two, tmp_path, clock=clock)            # another folder has its own time
    now["t"] += preview_build.PRUNE_EVERY + 1
    assert preview_build.maybe_prune_unused(one, tmp_path, clock=clock)
    assert ran == [one, two, one]


def test_a_changed_aux_falls_back_to_latexmk(tmp_path, monkeypatch):
    monkeypatch.setattr(preview_build, 'DIRECT_LUALATEX', True)
    commands = []

    def run(command, *, jobname, outdir, cwd, env, **kwargs):
        commands.append(command)
        if command[0] != 'latexmk':
            assert env == dict(PATH='recorded', HOME='home')
        pdf, log = outdir / (jobname + '.pdf'), outdir / (jobname + '.log')
        pdf.write_bytes(b'%PDF fresh')
        log.write_text('Success')
        (outdir / (jobname + '.aux')).write_text(str(len(commands)))
        (outdir / (jobname + '.direct.json')).write_text(
            json.dumps(dict(command='lualatex', cwd=str(cwd), env=dict(PATH='recorded'))))
        return compiler.Build(0, pdf, log, 'Success', False)

    monkeypatch.setattr(compiler, 'run_latexmk', run)
    ctx = ProjectContext.at(tmp_path)
    text = r'\begin{document}First\end{document}'
    kwargs = dict(ctx=ctx, env=dict(TEXINPUTS='shadow', PATH='inherited', HOME='home'))
    preview_build.compile_cached(text, 'abc', lambda _: None, **kwargs)
    preview_build.compile_cached(text.replace('First', 'Second'), 'abc', lambda _: None, **kwargs)
    assert [cmd[0] == 'latexmk' for cmd in commands] == [True, False, True]
    assert '-g' in commands[-1]


def test_a_spare_is_used_once_and_a_preamble_change_discards_it(tmp_path, monkeypatch):
    import io
    from unittest.mock import Mock

    monkeypatch.setattr(preview_build, 'DIRECT_LUALATEX', True)
    ctx = ProjectContext.at(tmp_path)
    focus = ('abc', 'instructor', 'EN')
    preview_build.set_focus(ctx, focus)
    cancel = compiler.CancelToken()
    cancel.preview_focus = focus
    cancel.preview_evidence = dict(started=0, inventory={})
    processes = []
    discarded = []
    commands = []

    def run(command, *, jobname, outdir, cwd, env, **kwargs):
        commands.append(command)
        pdf, log = outdir / (jobname + '.pdf'), outdir / (jobname + '.log')
        pdf.write_bytes(b'%PDF fresh')
        log.write_text('Success')
        (outdir / (jobname + '.direct.json')).write_text(json.dumps(dict(
            command=f'lualatex "{command[-1]}"', source=f'"{command[-1]}"', cwd=str(cwd), env=env)))
        return compiler.Build(0, pdf, log, 'Success', False)

    def popen(command, **kwargs):
        assert kwargs['stdin'] == compiler.subprocess.PIPE
        proc = Mock(stdin=io.StringIO())

        def wait():
            if proc.stdin.getvalue():
                wrapper = Path(proc.stdin.getvalue().strip())
                cache = ctx.build_dir / 'preview-cache' / wrapper.stem.removeprefix('_slidemage_preview-')
                (cache / (wrapper.stem.removeprefix('_slidemage_') + '.pdf')).write_bytes(b'%PDF spare')
            return 0

        proc.wait = wait
        processes.append(proc)
        return proc

    monkeypatch.setattr(compiler, 'run_latexmk', run)
    monkeypatch.setattr(compiler.subprocess, 'Popen', popen)
    monkeypatch.setattr(compiler.CancelToken, '_kill', lambda proc: discarded.append(proc))
    text = r'\documentclass{article}\begin{document}First\end{document}'
    try:
        preview_build.compile_cached(text, 'abc', lambda _: None, ctx=ctx, env={}, cancel=cancel)
        first = processes[0]
        started = preview_build._FOCUSED[ctx.root]['spare']['started']
        preview_build.compile_cached(text.replace('First', 'Second'), 'abc', lambda _: None,
                                     ctx=ctx, env={}, cancel=cancel)
        assert first.stdin.closed and len(processes) == 2 and len(commands) == 1
        assert cancel.preview_evidence['started'] == started
        preview_build.compile_cached(text.replace('article', 'report'), 'abc', lambda _: None,
                                     ctx=ctx, env={}, cancel=cancel)
        assert discarded == [processes[1]] and len(commands) == 2 and len(processes) == 3
    finally:
        preview_build.set_focus(ctx, None)


FILE_LINE_LOG = ('(./SlideMage_alt.lua)\n/home/user/.cache/slidemage/render-store/x/work/decks/_slidemage_preview-1.t\n'
                 'ex:42: Missing $ inserted.\n<inserted text> \n                $\nl.42 \\end{figureframe}\n\n'
                 + 'Here is how much of LuaTeX\'s memory you used:\n' * 30)


def test_a_failed_render_leads_with_its_first_error(tmp_path, monkeypatch):
    _runs, call = _latexmk_runs(monkeypatch, tmp_path, [])
    monkeypatch.setattr(compiler, 'run_latexmk', lambda command, *, jobname, outdir, **kwargs: compiler.Build(
        1, outdir / f'{jobname}.pdf', outdir / f'{jobname}.log', FILE_LINE_LOG, False))
    with pytest.raises(RuntimeError) as failure:
        call()
    assert compiler.first_tex_error('x\n! Undefined control sequence.\nl.9 \\foo\nmore').startswith(
        '! Undefined control sequence.\nl.9')
    assert compiler.first_tex_error('Output written on job.pdf (1 page).') == ''
    message = str(failure.value)
    assert message.startswith('Render failed for abc-EN-Test:\n! Missing $ inserted.\n')
    assert 'l.42 \\end{figureframe}' in message and message.endswith("Here is how much of LuaTeX's memory you used:")
