"""Isolated Qt cache-display probe with seeded artifacts; never invokes TeX.

The synthetic cache fixtures exercise validation/painting, not output equivalence.
Run after the real-engine gate, without concurrent tests, builds or compilers.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
import pymupdf
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from slidemage import compiler, deck_outline, preview_cache, preview_requests
from slidemage.deck_scan import read_deck
from slidemage.project import ProjectContext
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Toast
from slidemage.ui.workspace.actions import build_registry
from slidemage.ui.workspace.slide_list import SlideList
from slidemage.ui.workspace.state import WorkspaceState


def run(output, rows):
    output.mkdir(parents=True, exist_ok=False)
    ctx = ProjectContext.at(output / 'project')
    ctx.slides_dir.mkdir(parents=True)
    ctx.decks_dir.mkdir()
    source = ctx.slides_dir / 'aaa-EN-Probe-current.tex'
    source.write_text(r'\begin{standardframe}{Display probe}Synthetic workload\end{standardframe}')
    path = ctx.decks_dir / 'display.tex'
    path.write_text('\\documentclass{beamer}\n\\begin{document}\n' +
                    '\\slide{aaa-EN-Probe}\n' * rows + '\\end{document}\n')
    deck = read_deck(path)
    dependency = output / 'synthetic-font-input.bin'
    dependency.write_bytes(bytes(range(256)) * (128 * 1024))
    pdf = output / 'synthetic.pdf'
    with pymupdf.open() as doc:
        doc.new_page(width=320, height=180).insert_text((20, 30), 'Synthetic display workload')
        doc.save(pdf)
    image = BytesIO()
    Image.new('RGB', (160, 90), '#f4f4f4').save(image, 'PNG')
    png = image.getvalue()
    env = compiler.build_env(ctx)
    cache = preview_cache.PreviewCache(ctx.root)
    before = cache.begin(env)
    for slot in deck_outline.resolve_slots(ctx, deck, 'instructor', 'EN'):
        spec, = preview_requests.resolve_requests(ctx, deck, source, 'instructor', 'EN',
                                                   occurrence_key=slot.key)
        assert cache.store(preview_requests.cache_identity(spec), env, pdf=pdf, display_png=png,
                           secondary_png=png, page_images=(), dependencies=(source, dependency), before=before)
    app = QApplication.instance() or QApplication([])
    state = WorkspaceState(ctx)
    host = QWidget()
    window = SimpleNamespace(project=ctx, commands=build_registry(), compiling=False)
    panel = SlideList(window, state, ThemeManager(), Toast(host))
    panel.resize(360, 700)
    panel.show()
    samples = []
    paints = []
    class Paints(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Paint:
                paints.append(time.perf_counter())
            return False
    watcher = Paints(panel)
    panel.tree.viewport().installEventFilter(watcher)
    gaps = []
    previous = time.perf_counter()
    def tick():
        nonlocal previous
        now = time.perf_counter()
        gaps.append(now - previous)
        previous = now
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(10)
    state.set_deck(deck)
    def settle():
        deadline = time.perf_counter() + 60
        while panel._thumbnail_future is not None:
            app.processEvents()
            time.sleep(.001)
            if time.perf_counter() > deadline:
                raise RuntimeError('Thumbnail validation timed out')
        app.processEvents()
    settle()
    items = list(panel.tree.slide_items())
    panel.tree.setCurrentItem(items[rows // 2])
    panel.tree.verticalScrollBar().setValue(panel.tree.verticalScrollBar().maximum() // 2)
    selected = state.selection
    scroll = panel.tree.verticalScrollBar().value()
    for _ in range(3):
        gaps.clear()
        paints.clear()
        started = time.perf_counter()
        panel._refresh_all_preview_rows()
        settle()
        samples.append(dict(panel._thumbnail_metrics,
                            wall_seconds=time.perf_counter() - started,
                            max_timer_gap_seconds=max(gaps, default=0),
                            first_paint_seconds=paints[0] - started if paints else None,
                            last_paint_seconds=paints[-1] - started if paints else None))
        assert list(panel.tree.slide_items()) == items
        assert state.selection == selected and panel.tree.verticalScrollBar().value() == scroll
    result = dict(rows=rows, workload='synthetic populated cache, shared 32 MiB dependency',
                  qt_platform=os.environ['QT_QPA_PLATFORM'], samples=samples,
                  selection_and_scroll_preserved=True, compile_count=0, raster_count=0)
    (output / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    timer.stop()
    panel._thumbnail_executor.shutdown(wait=True)
    panel.hide()
    panel.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=200)
    args = parser.parse_args()
    run(args.output.resolve(), args.rows)
