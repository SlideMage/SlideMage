# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real LuaLaTeX acceptance probe; isolated inputs and JSON timing evidence.

Run: .venv/bin/python tools/preview_benchmark/views.py --output /tmp/preview-views
The output directory must not exist. No source project or framework is modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

import pymupdf
from PIL import Image
from slidemage import deck_scan, batch_render, preview_requests, preview_raster, preview_target, render_lookup, slide_snapshot
from slidemage.project import ProjectContext


class MeasuredService(preview_requests.RenderService):
    def __init__(self):
        super().__init__()
        self.observed = []

    def request(self, *args, **kwargs):
        request = super().request(*args, **kwargs)
        self.observed.append(request)
        return request


def fixture(output):
    repo = Path(__file__).resolve().parents[2]
    framework = output / 'external-framework'
    shutil.copytree(repo / 'latex', framework)
    root = output / 'project'
    for folder in ('slides', 'decks', 'media'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / 'example' / '.latexmkrc', root / '.latexmkrc')
    (root / 'slide_ids.csv').write_text('')
    Image.new('RGB', (80, 40), 'red').save(root / 'media' / 'probe.png')
    source = root / 'slides' / 'aaa-EN-Probe-current.tex'
    source.write_text(r'''\setSlideVersion{1-0-0+}
\begin{standardframe}{Preview views}
\includegraphics[height=1cm]{media/probe.png}
Shared body.\conditionalpause[instructor,during-course]
Second reveal.\deckonly<2->[instructor]{Instructor content}
\end{standardframe}
''')
    (root / 'slides' / 'bbb-EN-Hidden-current.tex').write_text(
        r'\begin{standardframe}{Hidden}Instructor only\end{standardframe}')
    preamble = r'''\documentclass[aspectratio=169]{beamer}
\input{SlideMage_template_slidemage}
\newcommand{\FooterText}{Preview integration}
\ifdefined\deckversionoverride\deckversion[\deckversionoverride]\else\deckversion[instructor]\fi
\ifdefined\decklanguageoverride\decklanguage[\decklanguageoverride]\else\decklanguage[en]\fi
'''
    path = root / 'decks' / 'probe.tex'
    def deck(*, hide=True, conditional=False, extra_preamble=''):
        path.write_text(preamble + ('\\def\\SMFooterHide{deck}\n' if hide else '') + extra_preamble +
                        '\\begin{document}\n' +
                        ('\\conditionalslide[instructor]{bbb-EN-Hidden}\n'
                         '\\slidestep{bbb-EN-Hidden}[instructor]{1}\n' if conditional else '') +
                        '\\slide{aaa-EN-Probe}\n\\end{document}\n')
        return deck_scan.read_deck(path)
    return ProjectContext.at(root), source, framework, deck


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    ctx, source, framework, deck = fixture(output)
    os.environ['SLIDEMAGE_LATEX'] = str(framework)
    records = []
    service = MeasuredService()

    def phase(name, selected_deck, *, view='all', force=False):
        specs = batch_render.plan_slide(ctx, selected_deck, source, view, 'EN',
                    options=preview_requests.RenderOptions(saved=True, force=force))
        start, offset = time.perf_counter(), len(service.observed)
        results = batch_render.render_batch(service, specs)
        assert all(r.status in ('rendered', 'cached', 'hidden') for r in results), [(r.status, r.error) for r in results]
        requests = service.observed[offset:]
        metrics = [r.metrics for r in requests]
        record = dict(phase=name, seconds=time.perf_counter()-start,
                      statuses=[r.status for r in results],
                      compile_count=sum(not m['cache_hit'] for m in metrics),
                      latex_passes=sum(sum(rule['rule'] == 'lualatex' for rule in m['rules']) for m in metrics),
                      raster_count=sum('png' in m['stages'] for m in metrics),
                      sequence_raster_count=sum('raster_sequence' in m['stages'] for m in metrics),
                      cache_hits=sum(m['cache_hit'] for m in metrics),
                      validation_seconds=sum(m['stages'].get('cache_validation', 0) for m in metrics),
                      dependency_bytes_read=sum(m.get('counters', {}).get('dependency_bytes_read', 0) for m in metrics),
                      content_bytes_read=sum(m.get('counters', {}).get('content_bytes_read', 0) for m in metrics),
                      metrics=metrics)
        records.append(record)
        (output / 'results.json').write_text(json.dumps(records, indent=2))
        assert all(r.status in ('rendered', 'cached', 'hidden') for r in results), [(r.status, r.error) for r in results]
        return results

    def signatures(results):
        return [preview_raster.sequence(r.pdf.read_bytes())['signature'] for r in results]

    # Start with two truly identical reveal pages in all three views.
    original = source.read_text()
    identical = original.replace('\\conditionalpause[instructor,during-course]', '\\pause').replace(
        '\\deckonly<2->[instructor]{Instructor content}', '')
    source.write_text(identical)
    current_deck = deck()
    cold = phase('cold-identical-all', current_deck)
    cold_signatures = signatures(cold)
    assert len(set(cold_signatures)) == 1
    assert all(len(preview_raster.sequence(r.pdf.read_bytes())['pages']) == 2 for r in cold)
    assert len({r.pdf for r in cold}) == 3
    assert all(r.display_png == slide_snapshot.prepare_preview_images(r.pdf)[0][0] for r in cold)
    # Independent file-backed calls establish that canonical captured-text
    # rendering preserves the old saved-source semantics before identities merge.
    start = time.perf_counter()
    for result in cold:
        spec = result.request
        saved_pdf = preview_target.render(spec.target, spec.view, spec.language,
            log=lambda _: None, force_build=True)
        assert preview_raster.sequence(saved_pdf.read_bytes())['signature'] == \
               preview_raster.sequence(result.pdf.read_bytes())['signature']
    records.append(dict(phase='saved-versus-captured-reference', seconds=time.perf_counter()-start,
                        reference_compiles=3, identical_sequences=True))
    phase('warm-all', current_deck)
    assert records[-1]['compile_count'] == 0 and records[-1]['cache_hits'] == 3
    service.close()
    service = MeasuredService()
    phase('restart-all', current_deck)
    assert records[-1]['compile_count'] == 0 and records[-1]['cache_hits'] == 3
    start = time.perf_counter()
    for result in cold:
        spec = result.request
        renderer = service._renderer(spec.target.context)
        assert render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec), strict=True)[0] == 'current'
    records.append(dict(phase='view-switch-cache-lookup', seconds=time.perf_counter()-start,
                        compile_count=0, raster_count=0, cache_hits=3))

    labels = phase('default-labels-all', deck(hide=False))
    assert len(set(signatures(labels))) == 3
    (ctx.root / 'parts').mkdir()
    (ctx.root / 'parts' / 'pause.tex').write_text(r'\conditionalpause[instructor]')
    source.write_text(identical.replace(r'\pause', r'\input{parts/pause}'))
    included = phase('included-instructor-pause', deck())
    assert signatures(included)[0] != signatures(included)[1] == signatures(included)[2]
    source.write_text(identical)
    override_deck = deck(extra_preamble=r'\renewcommand{\FooterText}{\ifSMInstructorVersion Instructor\else\ifSMDuringCourseVersion During\else After\fi\fi}' + '\n')
    override = phase('macro-override-unknown', override_deck)
    assert len(set(signatures(override))) == 3
    source.write_text(original)
    reveals = phase('conditional-reveals-all', deck())
    assert [len(preview_raster.sequence(r.pdf.read_bytes())['pages']) for r in reveals] == [2, 2, 1]
    assert len(set(signatures(reveals))) == 3
    source.write_text(identical)
    current_deck = deck()
    Image.new('RGB', (80, 40), 'blue').save(ctx.root / 'media' / 'probe.png')
    changed = phase('image-edit-all', current_deck)
    assert records[-1]['compile_count'] == 3 and signatures(changed) != cold_signatures
    package = framework / 'SlideMage_template_slidemage.tex'
    package.write_text(package.read_text() + '\n\\renewcommand{\\SMBulletColor}{red}\n')
    phase('external-framework-edit-all', current_deck)
    assert records[-1]['compile_count'] == 3
    source.write_text(identical.replace('Shared body.', 'Edited body.'))
    phase('same-plus-source-edit-all', current_deck)
    assert records[-1]['compile_count'] == 3
    phase('warm-after-edits-all', current_deck)
    assert records[-1]['compile_count'] == 0
    numbering = deck(conditional=True)
    specs = batch_render.plan_slide(ctx, numbering, source, 'all', 'EN')
    assert [r.target.frame_number for r in specs] == [3, 2, 2]
    hidden = batch_render.plan_slide(ctx, numbering,
                    ctx.slides_dir / 'bbb-EN-Hidden-current.tex', 'all', 'EN')
    hidden_results = batch_render.render_batch(service, hidden)
    assert [r.status for r in hidden_results] == ['rendered', 'hidden', 'hidden']
    # Resolve actual pinned/translated fixture files, then compile those selected inputs.
    pinned = source.with_name('aaa-EN-Probe-v1-0-0.tex')
    pinned.write_text(identical.replace('Shared body.', 'Pinned body.'))
    translated = source.with_name('ccc-DE-Probe-current.tex')
    translated.write_text('%% Translation of: aaa-EN-Probe\n' + identical.replace('Shared body.', 'Deutscher Inhalt.'))
    source.write_text('%% DE translation: ccc-DE-Probe\n' + source.read_text())
    deck_path = numbering.path
    deck_path.write_text(numbering.text.replace('\\slide{aaa-EN-Probe}', '\\slideversion{aaa-EN-Probe}{1-0-0}'))
    pinned_specs = batch_render.plan_slide(ctx, deck_scan.read_deck(deck_path), source, 'instructor', 'EN')
    assert pinned_specs[0].revision.path == pinned
    assert batch_render.render_batch(service, pinned_specs)[0].status == 'rendered'
    translated_specs = batch_render.plan_slide(ctx, deck(), source, 'during-course', 'DE')
    assert translated_specs[0].revision.path == translated
    result = batch_render.render_batch(service, translated_specs)[0]
    assert result.status == 'rendered', result.error
    with pymupdf.open(result.pdf) as pdf:
        assert 'Deutscher Inhalt' in ''.join(page.get_text() for page in pdf)
    service.close()
    (output / 'results.json').write_text(json.dumps(records, indent=2))
    print(json.dumps([{k: v for k, v in row.items() if k != 'metrics'} for row in records], indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output.resolve())
