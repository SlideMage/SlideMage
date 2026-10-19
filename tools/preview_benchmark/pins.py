# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prove unchanged audited pinned calls survive a batch creating a frozen sibling."""
from __future__ import annotations
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from slidemage import deck_scan, preview_equivalence, preview_requests
from slidemage.project import ProjectContext


def run(root, framework, output):
    output.mkdir(parents=True, exist_ok=False)
    os.environ['SLIDEMASTER_LATEX'] = str(framework)
    ctx = ProjectContext.at(root)
    source = ctx.slides_dir / 'aaa-EN-Probe-current.tex'
    frozen = ctx.slides_dir / 'aaa-EN-Probe-v1-0-0.tex'
    frozen.write_text(source.read_text())
    original = deck_scan.read_deck(ctx.decks_dir / 'probe.tex')
    path = ctx.decks_dir / 'pins.tex'
    path.write_text(original.preamble_text + '\n\\slideversion{aaa-EN-Probe}{1-0-0}\n\\end{document}\n')
    deck = deck_scan.read_deck(path)
    spec, = preview_requests.resolve_requests(ctx, deck, source, 'instructor', 'EN',
                                              options=preview_requests.RenderOptions(saved=True))
    assert preview_equivalence.classify_views((spec,)).decisions[0].certain
    service = preview_requests.RenderService()
    def request():
        handle = service.request(spec.target, spec.revision.text, spec.view, spec.language, False,
                                 lambda _: None, spec=spec)
        handle.wait()
        return handle
    first = request()
    assert first.preview_result.status == 'rendered'
    patch = 1
    while (ctx.slides_dir / f'aaa-EN-Probe-v1-0-{patch}.tex').exists():
        patch += 1
    (ctx.slides_dir / f'aaa-EN-Probe-v1-0-{patch}.tex').write_text(source.read_text())
    source.write_text(source.read_text().replace('Shared body.', 'Current version changed.') +
                      '\n% current version updated in batch\n')
    second = request()
    assert second.preview_result.status == 'cached', second.error
    assert second.metrics['cache_hit'] and not second.metrics['rules']
    # Separate current calls still have their own changed revision and version text.
    current = replace(spec.target, macro='slide', version=None)
    new = preview_requests.PreviewRequest(current, preview_requests.SourceRevision.capture(source), spec.view, 'EN')
    assert preview_requests.cache_identity(new) != preview_requests.cache_identity(spec)
    service.close()
    result = dict(initial_compile_count=1, after_batch_compile_count=0, after_batch_raster_count=0,
                  pinned_unchanged=True, current_revision_distinct=True)
    (output / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.project.resolve(), args.framework.resolve(), args.output.resolve())
