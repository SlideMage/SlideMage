# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Benchmark single-slide previews through the Preview pane's path (docs/findings.md, Plan 0).

Every render goes through ``preview_requests.RenderService.request(...).wait(pixels_only=True)``, exactly like the
pane, and then waits for the cache record. Per render it reports the time until the pixels (the pane's wait returns),
the time until the record is done (``total``), the latexmk stage and rules (``preview_metrics``), the bytes the cache read
(``content_bytes_read``, ``dependency_bytes_read``) and call counts and seconds of the functions that make up
SlideMage's own share (nested calls are counted in both, so the times do not add up).

Usage, from the repository root (no Qt, nothing is collected by pytest)::

    python tools/preview_bench.py                                   # example/, first deck and slide, Instructor
    python tools/preview_bench.py --repeat 5 --json bench.json      # medians over 5 edit renders, all data to a file
    python tools/preview_bench.py --scenarios cold,edit,deck-refresh --deck my-deck --slide 1b2 --view during-course
    python tools/preview_bench.py --scenarios fill-cache            # prune() time with ~400 cached generations

Scenarios (``--scenarios``, comma separated; default cold,unchanged,edit,view-switch): ``cold`` a forced render;
``unchanged`` the same text again (a cache hit); ``edit`` the text plus a unique ``%`` comment, ``--repeat`` times;
``view-switch`` instructor, during-course, instructor again, each with a fresh edit (one shared build folder);
``deck-refresh`` ``update_all_previews.rerender_deck`` of the whole deck with wall time and child-process CPU
seconds (wall only on Windows); ``fill-cache`` ~400 copied cache generations, then the time of ``prune()``;
``background-batch`` the background renders of the deck in ``--view`` (``--units`` of them, default all), one document
each against ``--batch-size`` (16) in one document, wall time and child-process CPU seconds of each.
Run ``cold`` first for clean numbers: later scenarios render the base text once, unreported, if nothing ran before.

The project is copied to a temp folder (and its preview cache removed again) unless ``--in-place``; ``--keep``
leaves both. The framework folder (``--framework``) is used through ``SLIDEMASTER_LATEX``.
"""
import argparse
import collections
import functools
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

try:
    import resource
except ImportError:  # Windows
    resource = None

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = ('cold', 'unchanged', 'edit', 'view-switch', 'deck-refresh', 'fill-cache', 'background-batch')
DEFAULT_SCENARIOS = 'cold,unchanged,edit,view-switch'
VIEWS = ('instructor', 'during-course', 'after-course')
FILL_GENERATIONS = 400


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--project', type=Path, default=REPO / 'example', help='project folder (default: example/)')
    parser.add_argument('--framework', type=Path, default=REPO / 'latex', help='framework folder (default: latex/)')
    parser.add_argument('--deck', help='deck name (default: the first one not starting with an underscore)')
    parser.add_argument('--slide', help='slide file stem prefix, e.g. 1b2 (default: the first -current slide the deck uses)')
    parser.add_argument('--view', default='instructor', choices=VIEWS)
    parser.add_argument('--language', help="language (default: the deck's, upper-case)")
    parser.add_argument('--repeat', type=int, default=3, help='edit renders to repeat; medians are reported')
    parser.add_argument('--batch-size', type=int, default=16, help='background-batch: slides per document (default: 16)')
    parser.add_argument('--units', type=int, default=0, help='background-batch: render only this many units of the deck (default: all)')
    parser.add_argument('--in-place', action='store_true', help='work in the real project instead of a temp copy')
    parser.add_argument('--keep', action='store_true', help='keep the temp copy and its preview cache')
    parser.add_argument('--json', type=Path, help='write all results to this file')
    parser.add_argument('--scenarios', type=scenario_list, default=scenario_list(DEFAULT_SCENARIOS),
                        help=f'comma list of {", ".join(SCENARIOS)} (default: {DEFAULT_SCENARIOS})')
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error('--repeat must be at least 1')
    return args


def scenario_list(text):
    names = [name.strip() for name in text.split(',') if name.strip()]
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown or not names:
        raise argparse.ArgumentTypeError(f'unknown scenario(s) {unknown or text!r}; choose from {", ".join(SCENARIOS)}')
    return [name for name in SCENARIOS if name in names]  # always in the order they can build on each other


def median(values):
    values = list(values)
    return statistics.median(values) if values else 0.0


def median_by_key(dicts):
    """Per key, the median over the runs (a run without the key counts as 0)."""
    dicts = list(dicts)
    return {key: median(d.get(key, 0) for d in dicts) for key in sorted({key for d in dicts for key in d})}


def rule_totals(rules):
    """latexmk rules of one render as {rule: [times run, seconds]}; latexmk names a rule 'biber <path>', the tool is the key."""
    totals = collections.defaultdict(lambda: [0, 0.0])
    for rule in rules:
        name = rule['rule'].split()[0]
        totals[name][0] += 1
        totals[name][1] += rule['seconds']
    return dict(totals)


def summarize(runs):
    """The medians over repeated renders of one kind (each run is a ``render_once`` record)."""
    rules = [rule_totals(run['rules']) for run in runs]
    timers = [run['timers'] for run in runs]
    names = {name for t in timers for name in t}
    return {
        'runs': len(runs),
        'pixels': median(run.get('pixels', run['total']) for run in runs),
        'total': median(run['total'] for run in runs),
        'stages': median_by_key(run['stages'] for run in runs),
        'rules': {name: {'runs': median(r.get(name, [0, 0])[0] for r in rules),
                         'seconds': median(r.get(name, [0, 0])[1] for r in rules)}
                  for name in sorted({name for r in rules for name in r})},
        'timers': {name: {'calls': median(t.get(name, {}).get('calls', 0) for t in timers),
                          'seconds': median(t.get(name, {}).get('seconds', 0) for t in timers)} for name in sorted(names)},
        'counters': median_by_key(run['counters'] for run in runs),
        'cache_hit': all(run['cache_hit'] for run in runs),
    }


def format_table(headers, rows):
    """Left-aligned first column, right-aligned others, two spaces between."""
    cells = [[str(cell) for cell in row] for row in [headers, *rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = ['  '.join(cell.ljust(width) if i == 0 else cell.rjust(width) for i, (cell, width) in enumerate(zip(row, widths)))
             for row in cells]
    lines.insert(1, '  '.join('-' * width for width in widths))
    return '\n'.join(line.rstrip() for line in lines)


def rules_text(rules):
    def one(name, info):
        times = '' if info['runs'] == 1 else f'*{info["runs"]:g}'
        return f'{name}{times} {info["seconds"]:.2f}'
    return ' '.join(one(name, info) for name, info in rules.items()) or '-'


def summary_table(groups):
    """One row per kind of render: {label: summarize(...)}."""
    rows = [[label, s['runs'], f'{s["pixels"]:.2f}', f'{s["total"]:.2f}', f'{s["stages"].get("latexmk", 0):.2f}', rules_text(s['rules']),
             f'{s["counters"].get("content_bytes_read", 0) / 1e6:.1f}',
             f'{s["counters"].get("dependency_bytes_read", 0) / 1e6:.1f}', 'hit' if s['cache_hit'] else '']
            for label, s in groups.items()]
    return format_table(['render', 'n', 'pixels s', 'total s', 'latexmk s', 'latexmk rules (s)', 'content MB', 'dep MB', 'cache'], rows)


def timer_table(groups):
    """Function timers: one row per function, one column per kind of render ("calls ms")."""
    names = sorted({name for s in groups.values() for name in s['timers']},
                   key=lambda name: -max(s['timers'].get(name, {}).get('seconds', 0) for s in groups.values()))
    rows = [[name, *(f'{t["calls"]:g}x {t["seconds"] * 1000:.0f} ms' if (t := s['timers'].get(name)) else '-'
                     for s in groups.values())] for name in names]
    return format_table(['function (calls, inclusive ms)', *groups], rows) if rows else ''


# ---- environment -----------------------------------------------------------------------------------------------

def tool_version(*command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return 'not found'
    return next((line.strip() for line in out.splitlines() if line.strip()), 'no output')


def header_line():
    return (f'{platform.platform()} | Python {platform.python_version()} | {tool_version("lualatex", "--version")} | '
            f'{tool_version("latexmk", "-v")} | {os.cpu_count()} CPUs')


# ---- timers ----------------------------------------------------------------------------------------------------

STATS = collections.defaultdict(lambda: [0, 0.0])
_STATS_LOCK = threading.Lock()


def instrument():
    """Wrap the functions that make up SlideMage's own share of a render with a call counter and timer, also
    where another module imported them by name. Functions that no longer exist are skipped."""
    from slidemage import (compiler, preview_build, preview_cache, preview_equivalence, preview_format,
                           preview_requests, slide_preview, slide_snapshot)
    targets = [(preview_cache, 'configuration_state'), (preview_cache, 'search_state'), (preview_cache, 'file_state'),
               (preview_cache, 'input_state'), (preview_cache, 'dependency_state'), (preview_cache, 'thumbnail_png'),
               (preview_cache.PreviewCache, 'prune'), (preview_cache.PreviewCache, 'store'),
               (preview_cache.PreviewCache, '_lookup'), (preview_cache.PreviewCache, 'begin'),
               (preview_build, 'configuration_key'), (preview_build, 'prune_unused'), (preview_build, 'publish_preview'),
               (preview_format, '_fresh'), (preview_format, 'ensure'), (compiler, 'run_latexmk'),
               (preview_requests, 'image_group'), (preview_equivalence, 'classify_views'),
               (slide_snapshot, 'prepare_preview_images'), (slide_snapshot, 'preview_sequence'),
               (slide_preview, 'sweep_renders')]
    for owner, name in targets:
        original = getattr(owner, name, None)
        if original is None:
            continue
        label = f'{owner.__name__.split(".")[-1]}.{name}'

        @functools.wraps(original)
        def timed(*args, __original=original, __label=label, **kwargs):
            start = time.perf_counter()
            try:
                return __original(*args, **kwargs)
            finally:
                with _STATS_LOCK:
                    STATS[__label][0] += 1
                    STATS[__label][1] += time.perf_counter() - start
        setattr(owner, name, timed)
        if isinstance(owner, type):
            continue
        for module in [m for key, m in list(sys.modules.items()) if key.startswith('slidemage') and m is not None]:
            if getattr(module, name, None) is original:
                setattr(module, name, timed)


# ---- scenarios -------------------------------------------------------------------------------------------------

class Bench:
    def __init__(self, args, root):
        from slidemage import deck_editor, deck_scan, deck_settings, preview_requests, project
        self.args, self.root = args, root
        self.ctx = project.ProjectContext.at(root)
        decks = [d for d in deck_scan.scan_decks(self.ctx) if not d.archived and not d.name.startswith('_')]
        self.deck = next((d for d in decks if args.deck in (d.name, d.path.stem)), None) if args.deck else next(iter(decks), None)
        if self.deck is None:
            raise SystemExit(f'no deck {args.deck or ""} in {root}'.replace('  ', ' '))
        self.language = (args.language or deck_settings.read_settings(self.deck.text).language).upper()
        used = {call.id for call in deck_editor.parse_slide_calls(self.deck) if not deck_editor.is_commented_out(self.deck.text, call)}
        slides = sorted(self.ctx.slides_dir.glob('*-current.tex'))
        self.slide = next((p for p in slides if (p.stem.startswith(args.slide) if args.slide else p.stem.split('-')[0] in used)), None)
        if self.slide is None:
            raise SystemExit(f'no slide {args.slide or "used by the deck"} in {self.ctx.slides_dir}')
        self.text = self.slide.read_text(encoding='utf-8')
        self.service = preview_requests.RenderService()
        self.warm = False
        self.results = {}

    def target(self, view):
        from slidemage import preview_target
        return preview_target.resolve_views(self.ctx, self.deck, self.slide, view, self.language)[0][1]

    def edited(self):
        return f'{self.text}\n% bench edit {uuid.uuid4().hex}\n'

    def render_once(self, view, text, force=False):
        """One render through the service, as the Preview pane asks for it."""
        from slidemage.preview_metrics import PreviewMetrics
        with _STATS_LOCK:
            STATS.clear()
        start = time.perf_counter()
        error = ''
        with PreviewMetrics() as metrics:
            request = self.service.request(self.target(view), text, view, self.language, lambda line: None,
                                           saved=False, force=force)
            try:
                request.wait(pixels_only=True)
                pixels = time.perf_counter() - start
                request.done.wait()         # then the cache record
            except Exception as exc:  # noqa: BLE001 -- a failed render is a result too
                error = f'{type(exc).__name__}: {exc}'
                pixels = time.perf_counter() - start
        total = time.perf_counter() - start
        data = request.metrics or metrics.to_dict()
        with _STATS_LOCK:
            timers = {name: {'calls': calls, 'seconds': seconds} for name, (calls, seconds) in STATS.items()}
        return {'pixels': pixels, 'total': total, 'stages': data.get('stages', {}), 'rules': data.get('rules', []), 'timers': timers,
                'counters': data.get('counters', {}), 'cache_hit': bool(data.get('cache_hit')), 'error': error}

    def ensure_warm(self):
        if not self.warm:
            self.render_once(self.args.view, self.text)
            self.warm = True

    def record(self, scenario, label, runs):
        failed = [run['error'] for run in runs if run['error']]
        if failed:
            print(f'  {label}: render failed: {failed[0]}')
        self.results.setdefault(scenario, {'runs': {}})['runs'][label] = runs

    def cold(self):
        self.record('cold', 'cold (forced)', [self.render_once(self.args.view, self.text, force=True)])
        self.warm = True

    def unchanged(self):
        self.ensure_warm()
        self.record('unchanged', 'unchanged', [self.render_once(self.args.view, self.text)])

    def edit(self):
        self.ensure_warm()
        self.record('edit', 'edit', [self.render_once(self.args.view, self.edited()) for _ in range(self.args.repeat)])

    def view_switch(self):
        if not self.deck.supports_version:
            print(f'  view-switch: deck {self.deck.name} does not support versions, skipped')
            return
        self.ensure_warm()
        order = ['instructor', 'during-course', 'instructor']
        rounds = [[self.render_once(view, self.edited()) for view in order] for _ in range(self.args.repeat)]
        for step, view in enumerate(order):
            self.record('view-switch', f'{step + 1}. {view}', [r[step] for r in rounds])

    def deck_refresh(self):
        from slidemage import update_all_previews
        children = lambda: (resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None)  # noqa: E731
        before, own, start = children(), time.process_time(), time.perf_counter()
        result = update_all_previews.rerender_deck(self.ctx, self.deck, lambda line: None, service=self.service, force=True)
        wall, after = time.perf_counter() - start, children()
        self.results['deck-refresh'] = {
            'deck': self.deck.name, 'wall_seconds': wall, 'own_cpu_seconds': time.process_time() - own,
            'child_cpu_seconds': (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) if resource else None,
            'refreshed': len(result.refreshed), 'failed': len(result.failed), 'error': result.error}

    def background_batch(self):
        from slidemage import background_renders, render_store
        from slidemage.compiler import CancelToken
        from slidemage.idle_gate import IdleGate
        units = background_renders.deck_units(self.ctx, self.deck, self.args.view, self.language)
        warm, units = units[-1], units[:self.args.units or None]
        if units and units[-1] is warm:
            units = units[:-1]
        children = lambda: (resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None)  # noqa: E731
        results = {}
        for size in (1, self.args.batch_size):
            local = Path(tempfile.mkdtemp(prefix='preview_bench_store_'))
            store = render_store.RenderStore(self.ctx, local)
            gate = IdleGate(startup_delay=0, idle_after=0, only_on_mains=lambda: False, cpu_load=lambda: 0.0, is_busy=lambda: [])
            renderer = background_renders.BackgroundRenderer(self.ctx, store, gate=gate, decks=lambda: [self.deck])
            renderer.batch_size = lambda size=size: size
            try:
                renderer.render_unit(warm, background_renders.ORIGIN_BACKGROUND, CancelToken())     # the format, unreported
                renderer._plan = [((n,), unit) for n, unit in enumerate(units)]
                before, own, start = children(), time.process_time(), time.perf_counter()
                while renderer._plan or renderer.scheduler.pending():
                    renderer._top_up()
                    renderer.scheduler.run_next()
                wall, after = time.perf_counter() - start, children()
                fresh = sum(1 for unit in units if renderer.resolver.lookup(unit).final)
                results[size] = {'units': len(units), 'fresh': fresh, 'wall_seconds': wall, 'own_cpu_seconds': time.process_time() - own,
                                 'child_cpu_seconds': (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) if resource else None}
            finally:
                renderer.stop()
                store.close()
                shutil.rmtree(local, ignore_errors=True)
        self.results['background-batch'] = {'deck': self.deck.name, 'view': self.args.view, 'language': self.language, 'by_batch_size': results}

    def fill_cache(self):
        from slidemage import preview_cache
        cache = preview_cache.PreviewCache(self.root)
        generations = sorted(cache.root.glob('*/*/manifest.json'), key=lambda path: path.stat().st_mtime)
        if not generations:
            self.cold()
            generations = sorted(cache.root.glob('*/*/manifest.json'), key=lambda path: path.stat().st_mtime)
        if not generations:
            raise SystemExit('fill-cache: the render left no cache generation to copy')
        source = generations[-1].parent
        size = sum(path.stat().st_size for path in source.iterdir() if path.is_file())
        count = max(0, min(FILL_GENERATIONS, int(preview_cache.MAX_BYTES * .8 // max(size, 1))) - len(generations))
        for _ in range(count):  # new digest folders: prune() only scans them, nothing looks them up
            shutil.copytree(source, cache.root / uuid.uuid4().hex / source.name,
                            ignore=shutil.ignore_patterns('.lease-*.lock'))
        manifests = list(cache.root.glob('*/*/manifest.json'))
        seconds = []
        for _ in range(self.args.repeat):
            start = time.perf_counter()
            cache.prune()
            seconds.append(time.perf_counter() - start)
        self.results['fill-cache'] = {
            'generations': len(manifests), 'manifest_bytes': sum(path.stat().st_size for path in manifests),
            'generation_bytes': size, 'prune_seconds': seconds, 'prune_median_seconds': median(seconds),
            'survivors': len(list(cache.root.glob('*/*/manifest.json')))}

    def report(self):
        for scenario in self.args.scenarios:
            data = self.results.get(scenario)
            if not data:
                continue
            print(f'\n== {scenario}')
            if 'runs' in data:
                groups = {label: summarize(runs) for label, runs in data['runs'].items() if not any(r['error'] for r in runs)}
                data['summary'] = groups
                if groups:
                    print(summary_table(groups))
                    print('\n' + timer_table(groups))
            elif scenario == 'background-batch':
                for size, row in data['by_batch_size'].items():
                    cpu = row['child_cpu_seconds']
                    print(f'{data["deck"]} {data["view"]} {data["language"]}, batch size {size}: {row["fresh"]} of {row["units"]} slides, '
                          f'wall {row["wall_seconds"]:.1f} s, child CPU {"n/a" if cpu is None else f"{cpu:.1f} s"}, '
                          f'SlideMage CPU {row["own_cpu_seconds"]:.1f} s')
            elif scenario == 'deck-refresh':
                cpu = data['child_cpu_seconds']
                print(f'{data["deck"]}: wall {data["wall_seconds"]:.1f} s, child CPU '
                      f'{"n/a" if cpu is None else f"{cpu:.1f} s"}, SlideMage CPU {data["own_cpu_seconds"]:.1f} s, '
                      f'{data["refreshed"]} refreshed, {data["failed"]} failed' + (f' ({data["error"]})' if data['error'] else ''))
            else:
                print(f'{data["generations"]} generations ({data["generation_bytes"] / 1e6:.1f} MB each, manifests '
                      f'{data["manifest_bytes"] / 1e6:.1f} MB): prune() median {data["prune_median_seconds"] * 1000:.0f} ms '
                      f'over {len(data["prune_seconds"])} runs; {data["survivors"]} generations left')


def run(args):
    from slidemage import project, render_store
    source = args.project.resolve()
    root = source
    if not args.in_place:
        root = Path(tempfile.mkdtemp(prefix='preview_bench_')) / source.name
        shutil.copytree(source, root, ignore=shutil.ignore_patterns('.build', '.previews', '_slidemage_preview-*'))
    os.environ[project.ENV_VAR] = str(root)
    os.environ['SLIDEMASTER_LATEX'] = str(args.framework.resolve())
    print(header_line())
    bench = None
    try:
        instrument()
        bench = Bench(args, root)
        print(f'project {root} | deck {bench.deck.name} | slide {bench.slide.stem} | view {args.view} | '
              f'language {bench.language} | repeat {args.repeat}')
        for scenario in args.scenarios:
            getattr(bench, scenario.replace('-', '_'))()
        bench.report()
        if args.json:
            args.json.write_text(json.dumps({'header': header_line(), 'project': str(root), 'deck': bench.deck.name,
                                             'slide': bench.slide.stem, 'view': args.view, 'language': bench.language,
                                             'repeat': args.repeat, 'results': bench.results}, indent=2), encoding='utf-8')
    finally:
        if bench is not None:
            bench.service.close()
        if not args.in_place and not args.keep:
            shutil.rmtree(root.parent, ignore_errors=True)
            shutil.rmtree(project.preview_cache_dir(root), ignore_errors=True)
            shutil.rmtree(project.cache_dir() / 'render-store' / render_store.project_id(root), ignore_errors=True)
    return 0


def main(argv=None):
    return run(parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
