"""Render a slide/region/element, optionally watching its source for changes.

Example: python -m slidemage.preview_cli slides/foo-current.tex --watch
Use SLIDEMASTER_PROJECT to select the project, as with the desktop app.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import time
import json
from . import project
from .preview_metrics import PreviewMetrics


def input_state(paths):
    """A missing/deleted dependency stays watched so recreation triggers a retry."""
    state = {}
    for path in paths:
        try:
            info = path.stat()
            state[path] = (info.st_mtime_ns, info.st_size)
        except OSError:
            state[path] = None
    return state


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--deck', help='Deck name supplying the preview preamble')
    parser.add_argument('--mode', choices=('slide', 'region', 'element'), default='slide')
    parser.add_argument('--lines', help='Inclusive 1-based region, e.g. 12:30')
    parser.add_argument('--overlay', type=int, help='Positive overlay number; omit for all')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--profile', action='store_true', help='Print timings and latexmk pass durations as JSON')
    args = parser.parse_args()
    from . import deck_scan, slide_preview
    project.use(ctx := project.from_environment())
    source = args.source.resolve()
    _, slug, _ = slide_preview.call_for_slide_path(source)
    paths = {source, ctx.root / '.latexmkrc', ctx.root / 'decks/.latexmkrc'}
    deck = next((d for d in deck_scan.scan_decks(ctx) if d.name == args.deck), None) if args.deck else None
    if args.deck and deck is None:
        parser.error(f'Deck not found: {args.deck}')
    if deck:
        paths.add(deck.path)
    previous = None
    while True:
        current = input_state(paths)
        if current != previous:
            start = time.perf_counter()
            try:
                body = source.read_text(encoding='utf-8')
                if args.lines:
                    first, last = map(int, args.lines.split(':'))
                    if first < 1 or last < first:
                        parser.error('--lines must be an inclusive positive range')
                    body = '\n'.join(body.splitlines()[first-1:last])
                preamble = None
                if args.deck:
                    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == args.deck)
                    preamble = deck.preamble_text
                with PreviewMetrics() as metrics:
                    pdf = slide_preview.render_slide_text_to_pdf(
                        slug, body, preamble_text=preamble, preview_mode=args.mode,
                        overlay=args.overlay, reuse_build=not args.no_cache, log=print)
                if args.profile:
                    print(json.dumps(metrics.to_dict()), flush=True)
                try:
                    paths.update(Path(p) for p in json.loads(pdf.with_suffix('.inputs.json').read_text()))
                except (OSError, ValueError):
                    pass
                print(f'{time.perf_counter()-start:.3f}s: {pdf}', flush=True)
                if args.open:
                    slide_preview.open_pdf(pdf)
            except (RuntimeError, ValueError, OSError, StopIteration) as exc:
                print(str(exc), flush=True)
                if not args.watch:
                    raise SystemExit(1)
            # Use the pre-render states for existing inputs: an edit during compilation
            # must still trigger another build. Newly discovered inputs start watched now.
            previous = {path: current.get(path, stamp) for path, stamp in input_state(paths).items()}
        if not args.watch:
            break
        time.sleep(.3)


if __name__ == '__main__':
    main()
