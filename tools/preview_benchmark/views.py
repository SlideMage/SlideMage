# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real LuaLaTeX acceptance probe; isolated inputs and JSON timing evidence.

Run: .venv/bin/python tools/preview_benchmark/views.py --output /tmp/preview-views
The output directory must not exist. No source project or framework is modified.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

import pymupdf
from PIL import Image
from slidemage import deck_scan, preview_batch, preview_equivalence, preview_requests, preview_raster, preview_target, preview_pages, slide_snapshot
from slidemage.project import ProjectContext


class MeasuredService(preview_requests.RenderService):
    def __init__(self, *, exact=False):
        super().__init__()
        self.observed = []
        self.exact = exact

    def request(self, *args, **kwargs):
        if self.exact:
            kwargs['require_pdf'] = True
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
\usetheme{gotham}
\input{Slidemaster_preamble_slidemage}
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
    os.environ['SLIDEMASTER_LATEX'] = str(framework)
    records = []
    service = MeasuredService(exact=True)

    def phase(name, selected_deck, *, view='all', force=False, expected_groups=None, expect_certain=True):
        specs = preview_requests.resolve_requests(ctx, selected_deck, source, view, 'EN',
                    options=preview_requests.RenderOptions(saved=True, force=force))
        classified = preview_equivalence.classify_views(specs)
        if expected_groups is not None:
            assert len({d.group for d in classified.decisions if not d.hidden}) == expected_groups, classified.decisions
        if expect_certain:
            assert all(d.certain for d in classified.decisions), classified.decisions
        start, offset = time.perf_counter(), len(service.observed)
        results = preview_batch.render_batch(service, specs)
        assert all(r.status in ('rendered', 'cached', 'hidden') for r in results), [(r.status, r.error) for r in results]
        # Exact-view requests remain independently compiled reference PDFs.
        # Compare the complete ordered reveal sequence, dimensions included.
        by_group = {}
        for decision, result in zip(classified.decisions, results):
            if decision.hidden:
                continue
            signature = preview_raster.sequence(result.pdf.read_bytes())['signature']
            previous = by_group.setdefault(decision.group, signature)
            assert signature == previous, (name, decision, classified.decisions)
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
                      deduplicated_images=sum(m['deduplicated_images'] for m in metrics), metrics=metrics)
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
    cold = phase('cold-identical-all', current_deck, expected_groups=1)
    assert len(set(signatures(cold))) == 1
    assert all(len(preview_raster.sequence(r.pdf.read_bytes())['pages']) == 2 for r in cold)
    assert len({r.pdf for r in cold}) == 3  # separate view PDFs survive raster sharing
    assert records[-1]['deduplicated_images'] > 0
    assert all(r.display_png == slide_snapshot.page_png(r.pdf, slide_snapshot.FULL_SIZE[0]) for r in cold)
    # Independent file-backed calls establish that canonical captured-text
    # rendering preserves the old saved-source semantics before identities merge.
    start = time.perf_counter()
    for result in cold:
        spec = result.request
        saved_pdf = preview_target.render(spec.target, spec.view, spec.language,
            footer_timestamp=False, log=lambda _: None, capture_snapshot=False, force_build=True)
        assert preview_raster.sequence(saved_pdf.read_bytes())['signature'] == \
               preview_raster.sequence(result.pdf.read_bytes())['signature']
    records.append(dict(phase='saved-versus-captured-reference', seconds=time.perf_counter()-start,
                        reference_compiles=3, identical_sequences=True))
    phase('warm-all', current_deck)
    assert records[-1]['compile_count'] == 0 and records[-1]['cache_hits'] == 3
    service.close()
    service = MeasuredService(exact=True)
    phase('restart-all', current_deck)
    assert records[-1]['compile_count'] == 0 and records[-1]['cache_hits'] == 3
    start = time.perf_counter()
    for result in cold:
        assert service.cached_spec(result.request) is not None
    records.append(dict(phase='view-switch-cache-lookup', seconds=time.perf_counter()-start,
                        compile_count=0, raster_count=0, cache_hits=3))

    # A separate project keeps the scheduler's cold group counts independent
    # of the exact-view reference cache above. Reference PDFs are forced per
    # view, so the comparison cannot accidentally read a shared image twice.
    grouped_ctx, grouped_source, grouped_framework, grouped_deck = fixture(output / 'grouped')
    os.environ['SLIDEMASTER_LATEX'] = str(grouped_framework)
    grouped_service = MeasuredService()
    reference_service = MeasuredService(exact=True)
    for name, body, expected in (
        ('grouped-one', identical, 1),
        ('grouped-two', identical.replace(r'\pause', r'\conditionalpause[instructor]'), 2),
        ('grouped-three', identical.replace(r'\pause', r'\deckreveal[2]{Revealed}'), 3),
    ):
        grouped_source.write_text(body)
        current = grouped_deck()
        grouped_specs = preview_requests.resolve_requests(grouped_ctx, current, grouped_source, 'all', 'EN',
                             options=preview_requests.RenderOptions(saved=True))
        classified = preview_equivalence.classify_views(grouped_specs)
        assert all(d.certain for d in classified.decisions), classified.decisions
        assert len({d.group for d in classified.decisions}) == expected, classified.decisions
        offset = len(grouped_service.observed)
        start = time.perf_counter()
        grouped_results = preview_batch.render_batch(grouped_service, grouped_specs)
        grouped_requests = grouped_service.observed[offset:]
        assert len(grouped_requests) == 3
        assert sum(not request.metrics['cache_hit'] for request in grouped_requests) == expected
        assert all(result.display_png is not None for result in grouped_results)
        grouped_seconds = time.perf_counter() - start
        reference_specs = tuple(replace(spec, options=replace(spec.options, force=True))
                                for spec in grouped_specs)
        start = time.perf_counter()
        reference_results = []
        for spec in reference_specs:
            exact_request = reference_service.request(spec.target, spec.revision.text, spec.view, spec.language,
                                  spec.options.footer_timestamp, lambda _: None, spec=spec)
            exact_request.wait()
            reference_results.append(exact_request.preview_result)
        assert all(result.pdf is not None for result in reference_results)
        assert len({result.pdf for result in reference_results}) == 3
        signatures_by_group = {}
        for decision, grouped_result, reference_result in zip(classified.decisions, grouped_results, reference_results):
            signature = preview_raster.sequence(reference_result.pdf.read_bytes())['signature']
            assert signatures_by_group.setdefault(decision.group, signature) == signature
            assert grouped_result.display_png == slide_snapshot.page_png(reference_result.pdf, slide_snapshot.FULL_SIZE[0])
        metrics = [request.metrics for request in grouped_requests]
        records.append(dict(phase=name, seconds=grouped_seconds, compile_count=expected,
                            latex_passes=sum(sum(rule['rule'] == 'lualatex' for rule in m['rules']) for m in metrics),
                            raster_count=sum('png' in m['stages'] for m in metrics),
                            sequence_raster_count=sum('raster_sequence' in m['stages'] for m in metrics),
                            validation_seconds=sum(m['stages'].get('cache_validation', 0) for m in metrics),
                            dependency_bytes_read=sum(m.get('counters', {}).get('dependency_bytes_read', 0) for m in metrics),
                            metrics=metrics,
                            reference_seconds=time.perf_counter() - start, reference_compiles=3,
                            cache_hits=3 - expected, groups=expected))
        (output / 'results.json').write_text(json.dumps(records, indent=2))
        # Switching to the identical editor buffer reuses completed saved work.
        offset = len(grouped_service.observed)
        draft_start = time.perf_counter()
        draft_specs = tuple(replace(spec, options=replace(spec.options, saved=False)) for spec in grouped_specs)
        draft_results = preview_batch.render_batch(grouped_service, draft_specs)
        assert all(result.status == 'cached' for result in draft_results)
        assert all(request.metrics['cache_hit'] for request in grouped_service.observed[offset:])
        assert all(preview_pages.sequence_images(request, dpi=130) for request in
                   grouped_service.observed[offset:])
        records.append(dict(phase=name + '-identical-buffer', seconds=time.perf_counter()-draft_start,
                            compile_count=0, raster_count=0,
                            cache_hits=3, sequence_reuse=True))
    grouped_service.close()
    reference_service.close()
    os.environ['SLIDEMASTER_LATEX'] = str(framework)

    labels = phase('default-labels-all', deck(hide=False), expected_groups=3)
    assert len(set(signatures(labels))) == 3
    (ctx.root / 'parts').mkdir()
    (ctx.root / 'parts' / 'pause.tex').write_text(r'\conditionalpause[instructor]')
    source.write_text(identical.replace(r'\pause', r'\input{parts/pause}'))
    included = phase('included-instructor-pause', deck(), expected_groups=2)
    assert signatures(included)[0] != signatures(included)[1] == signatures(included)[2]
    source.write_text(identical)
    override_deck = deck(extra_preamble=r'\renewcommand{\FooterText}{\ifSMInstructorVersion Instructor\else\ifSMDuringCourseVersion During\else After\fi\fi}' + '\n')
    override = phase('macro-override-unknown', override_deck, expected_groups=3, expect_certain=False)
    assert len(set(signatures(override))) == 3
    source.write_text(original)
    reveals = phase('conditional-reveals-all', deck(), expected_groups=3)
    assert [len(preview_raster.sequence(r.pdf.read_bytes())['pages']) for r in reveals] == [2, 2, 1]
    assert len(set(signatures(reveals))) == 3
    source.write_text(identical)
    current_deck = deck()
    Image.new('RGB', (80, 40), 'blue').save(ctx.root / 'media' / 'probe.png')
    changed = phase('image-edit-all', current_deck)
    assert records[-1]['compile_count'] == 3 and signatures(changed) != signatures(cold)
    package = framework / 'Slidemaster_preamble_slidemage.tex'
    package.write_text(package.read_text() + '\n\\renewcommand{\\SMBulletColor}{red}\n')
    phase('external-framework-edit-all', current_deck, expect_certain=False)
    assert records[-1]['compile_count'] == 3
    source.write_text(identical.replace('Shared body.', 'Edited body.'))
    phase('same-plus-source-edit-all', current_deck, expect_certain=False)
    assert records[-1]['compile_count'] == 3
    phase('warm-after-edits-all', current_deck, expect_certain=False)
    assert records[-1]['compile_count'] == 0
    numbering = deck(conditional=True)
    specs = preview_requests.resolve_requests(ctx, numbering, source, 'all', 'EN')
    assert [r.target.frame_number for r in specs] == [3, 2, 2]
    hidden = preview_requests.resolve_requests(ctx, numbering,
                    ctx.slides_dir / 'bbb-EN-Hidden-current.tex', 'all', 'EN')
    hidden_results = preview_batch.render_batch(service, hidden)
    assert [r.status for r in hidden_results] == ['rendered', 'hidden', 'hidden']
    # Resolve actual pinned/translated fixture files, then compile those selected inputs.
    pinned = source.with_name('aaa-EN-Probe-v1-0-0.tex')
    pinned.write_text(identical.replace('Shared body.', 'Pinned body.'))
    translated = source.with_name('ccc-DE-Probe-current.tex')
    translated.write_text('%% Translation of: aaa-EN-Probe\n' + identical.replace('Shared body.', 'Deutscher Inhalt.'))
    source.write_text('%% DE translation: ccc-DE-Probe\n' + source.read_text())
    deck_path = numbering.path
    deck_path.write_text(numbering.text.replace('\\slide{aaa-EN-Probe}', '\\slideversion{aaa-EN-Probe}{1-0-0}'))
    pinned_specs = preview_requests.resolve_requests(ctx, deck_scan.read_deck(deck_path), source, 'instructor', 'EN')
    assert pinned_specs[0].revision.path == pinned
    assert preview_batch.render_batch(service, pinned_specs)[0].status == 'rendered'
    translated_specs = preview_requests.resolve_requests(ctx, deck(), source, 'during-course', 'DE')
    assert translated_specs[0].revision.path == translated
    result = preview_batch.render_batch(service, translated_specs)[0]
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
