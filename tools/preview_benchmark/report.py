"""Publish measured benchmark rows and a speed table; never extrapolate missing rows."""
import argparse
import json
import statistics
from pathlib import Path

STAGES = {
    'baseline': 'Baseline (fresh job)',
    '1': '1: reusable build state (fmt fallback)',
    '3': '3: complete source region',
    '4': '4: overlay 1',
    '1+3': '1 + 3',
    '1+4': '1 + 4',
    '3+4': '3 + 4',
    '1+3+4': '1 + 3 + 4',
}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    all_rows = {}
    for stage in STAGES:
        path = args.source / stage / 'measurements.jsonl'
        if path.exists():
            # Last measurement wins only if a call was explicitly rerun.
            by_index = {r['index']: r for r in map(json.loads, path.read_text().splitlines())}
            all_rows[stage] = [by_index[i] for i in sorted(by_index)]
    baseline = all_rows.get('baseline', [])
    expected = len(baseline)
    baseline_total = sum(r['seconds'] for r in baseline if r['ok'])
    lines = [
        '# Manual preview benchmark — 9 October 2026', '',
        'Measured sequentially on an AMD Ryzen 7 PRO 6850U, with LuaHBTeX 1.22.0 '
        '(TeX Live 2025/Debian), latexmk 4.87, and Python 3.14.5. '
        'The existing TeX font cache was warm in every configuration.', '',
        f'The corpus contains {expected} active slide calls (including repeated '
        'slidestep variants) from `example/decks/slidemage-manual.tex`. '
        'Baseline was collected before modifying the preview implementation. '
        'Every duration includes the preview API call, including PNG capture '
        'when that API generates a canonical snapshot; opening a PDF viewer is excluded.', '',
        '| Configuration | Successful calls | Pages | Total seconds | Mean seconds | Median seconds | Speedup |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for stage, label in STAGES.items():
        rows = all_rows.get(stage, [])
        good = [r for r in rows if r['ok']]
        if len(good) != expected or len(rows) != expected or not expected:
            lines.append(f'| {label} | {len(good)}/{expected} | — | incomplete | — | — | — |')
            continue
        times = [r['seconds'] for r in good]
        total = sum(times)
        lines.append(f'| {label} | {len(good)}/{expected} | {sum(r["pages"] for r in good)} | '
                     f'{total:.2f} | {statistics.mean(times):.3f} | {statistics.median(times):.3f} | '
                     f'{baseline_total/total:.2f}× |')
    candidates = {stage: sum(r['seconds'] for r in rows) for stage, rows in all_rows.items()
                  if len(rows) == expected and all(r['ok'] for r in rows)}
    if all(stage in candidates for stage in STAGES):
        full = min(('1', '3', '1+3'), key=candidates.get)
        selected = min(('4', '1+4', '3+4', '1+3+4'), key=candidates.get)
        lines += ['', f'Fastest measured complete-slide configuration: **{full}**, '
                  f'**{candidates[full]:.2f} s** total. Fastest selected-overlay configuration: '
                  f'**{selected}**, **{candidates[selected]:.2f} s** total.', '',
                  'The default editor path combines reusable builds with in-memory source rendering '
                  'and retains all overlays. Selecting a region and a specific overlay uses 1 + 3 + 4. '
                  'Its roughly 0.1-second total advantage over 1 + 4 in this run is too small to '
                  'establish a repeatable difference. First builds are not three times faster; '
                  'the main gain is on subsequent rebuilds.']
    lines += ['', '## Cold builds and unchanged requests', '',
              '| Cached configuration | Initial builds, total s | Initial median s | Unchanged median s |',
              '|---|---:|---:|---:|']
    for stage, rows in all_rows.items():
        if rows and all(r.get('ok') and 'unchanged_seconds' in r for r in rows):
            lines.append(f'| {STAGES[stage]} | {sum(r["cold_seconds"] for r in rows):.2f} | '
                         f'{statistics.median(r["cold_seconds"] for r in rows):.3f} | '
                         f'{statistics.median(r["unchanged_seconds"] for r in rows):.3f} |')
    lines += ['', '## Interpretation and limits', '',
              '- **Result 1 is a fallback, not working `.fmt` caching.** Both the full manual '
              'preamble and a Beamer-class-only `mylatexformat` dump failed in '
              '`lua-uni-stage-tables.lua:141` (`attempt to perform arithmetic on a string value`). '
              'The implementation instead retains latexmk auxiliary state and dependencies. '
              'Manual PDF graphics already reuse pre-rendered assets; dynamic theme TikZ remains compiled normally.',
              '- Cached rows measure an actual source change after a separately measured initial build. '
              'A harmless macro changes between runs to force compilation without changing the expected pixels. '
              'These are changed-input measurements, not actual word-edit measurements. '
              'Unchanged cache-hit timings are shown separately and are not used for speedup.',
              '- The spacing-reference slide already reaches latexmk’s rerun limit in the baseline. '
              'Its cached configuration deliberately clears unconverged auxiliary state before subsequent '
              'requests, preserving the baseline output at the cost of a fresh build for this one case.',
              '- Result 3 renders the complete source of each manual call as a region. '
              'The previous app already supported whole-buffer preview; explicit selection is the added feature. '
              'Region previews do not update the canonical full-slide PNG.',
              '- Result 4 intentionally shows only overlay 1, so its output is smaller than a full preview. '
              'A requested overlay overrides a call’s existing slidestep filter. '
              'It remains opt-in rather than discarding overlays from the ordinary preview.',
              '- Result 2 uses `preview.sty` for selected elements. Whole Beamer frames are rejected '
              'in element mode: it is not a drop-in full-slide renderer. Combining this mode with '
              'the mutually exclusive region mode or a frame-overlay selection has no defined meaning.',
              '- PDF verification rasterizes every page at 72 dpi and compares pixels and page dimensions '
              'against the original standalone-preview path. For overlay 1, the corresponding first baseline '
              'page is used. The call restricted to overlay 3 has no overlay-1 reference and is marked '
              'not comparable. This does not establish equivalence to a full-deck build, whose navigation '
              'and cross-frame state can differ from standalone previews.',
              '- The footer-annotation slide measures a timestamp even when it is hidden. '
              'Comparison runs freeze the timestamp to the baseline PDF’s minute and retain the normal '
              'timestamp-file loading behavior so its annotation positions remain comparable.',
              '- A separate actual title edit changed “Lists and formulas” to “Lists and equations”: '
              'the initial preview took 7.345 s and the edited preview 4.492 s. A deliberately undefined '
              'command was rejected, and the repaired preview succeeded. Extra LaTeX passes make this '
              'real edit slower than the minimal-rebuild workload in the main table.',
              '- Overlapping samples from an interrupted process were discarded and rerun sequentially. '
              'One pass per configuration is reported; differences of a few percent can be measurement noise.', '',
              '## Rendering checks', '', '| Configuration | Pixel matches | Not comparable | Mismatches |',
              '|---|---:|---:|---:|']
    for stage, rows in all_rows.items():
        if stage != 'baseline':
            lines.append(f'| {STAGES[stage]} | {sum(r.get("pixel_match") is True for r in rows)} | '
                         f'{sum(r.get("pixel_match") is None for r in rows)} | '
                         f'{sum(r.get("pixel_match") is False for r in rows)} |')
    lines += ['', '## Element previews (result 2)', '',
              'These four self-contained selections come from the manual: its Sharpe-ratio formula, '
              'nested list, correlation-matrix figure and Gotham table. They are not complete slides, '
              'so their timings are not part of the 77-call speedup ranking.', '',
              '| Selection | 2: fresh element, s | 1 + 2: warm element, s |',
              '|---|---:|---:|']
    element_rows = {}
    for stage in ('2', '1+2'):
        path = args.source / stage / 'measurements.jsonl'
        element_rows[stage] = ({r['selection']: r for r in map(json.loads, path.read_text().splitlines())}
                               if path.exists() else {})
    for selection in ('formula', 'list', 'figure', 'table'):
        values = []
        for stage in ('2', '1+2'):
            row = element_rows[stage].get(selection, {})
            values.append(f"{row['seconds']:.3f}" if row.get('ok') else 'not measured / failed')
        lines.append(f'| {selection} | {values[0]} | {values[1]} |')
    all_rows['elements'] = element_rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines)+'\n')
    args.output.with_suffix('.json').write_text(json.dumps(all_rows, indent=2)+'\n')
    print(args.output)


if __name__ == '__main__':
    main()
