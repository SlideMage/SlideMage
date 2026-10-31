# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real deck-refresh integration against the isolated project made by views.py."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from slidemage import deck_outline, deck_scan, preview_target, preview_thumbnails, update_all_previews
from slidemage.preview_requests import RenderService
from slidemage.project import ProjectContext


class MeasuredService(RenderService):
    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, *args, **kwargs):
        request = super().request(*args, **kwargs)
        self.requests.append(request)
        return request


def run(root, framework, output):
    output.mkdir(parents=True, exist_ok=False)
    os.environ['SLIDEMAGE_LATEX'] = str(framework)
    ctx = ProjectContext.at(root)
    original = deck_scan.read_deck(ctx.decks_dir / 'probe.tex')
    path = ctx.decks_dir / 'refresh.tex'
    path.write_text(original.preamble_text + '\n' +
                    '\\slide{aaa-EN-Probe}\n' * 2 +
                    '\\slideversion{aaa-EN-Probe}{1-0-0}\n\\end{document}\n')
    deck = deck_scan.read_deck(path)
    service = MeasuredService()
    events = []
    started = time.perf_counter()
    first = update_all_previews.rerender_deck(ctx, deck, lambda _: None, service=service,
                                             language='EN', progress=events.append)
    assert first and first.details.total == 9, first
    cold_seconds = time.perf_counter() - started
    compile_count = sum(not request.metrics['cache_hit'] for request in service.requests)
    assert events[-1].index == events[-1].total == 9
    service.requests.clear()
    started = time.perf_counter()
    warm = update_all_previews.rerender_deck(ctx, deck, lambda _: None, service=service, language='EN')
    warm_seconds = time.perf_counter() - started
    assert warm and warm.details.count('cached') == 9
    assert all(request.metrics['cache_hit'] for request in service.requests)
    assert all('png' not in request.metrics['stages'] and 'raster_sequence' not in request.metrics['stages']
               for request in service.requests)
    for view in ('instructor', 'during-course', 'after-course'):
        outline = deck_outline.build_outline(ctx, deck, view, 'EN')
        thumbnails = preview_thumbnails.for_outline(ctx, deck, outline, view, 'EN', False)
        for section in thumbnails:
            for row in section.rows:
                target = preview_target.for_call(ctx, deck, row.call, row.position, language='EN',
                    frame_number=row.frame_number, occurrence_key=row.key, hidden=row.hidden)
                pane = service.selected_preview(target, target.source_path.read_text(), view, 'EN', False)
                assert row.image_selection.fresh and pane.fresh
                assert row.image_selection.artifact_id == pane.artifact_id
    result = dict(requests=9, cold_compile_count=compile_count, cold_seconds=cold_seconds,
                  warm_compile_count=0, warm_raster_count=0, warm_seconds=warm_seconds,
                  warm_cache_hits=9, repeated_and_pinned_calls=True,
                  all_view_surface_images_match=True)
    (output / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    service.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.project.resolve(), args.framework.resolve(), args.output.resolve())
