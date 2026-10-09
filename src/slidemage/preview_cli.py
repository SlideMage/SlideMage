"""Render a slide/region/element, optionally watching its source for changes.

Example: python -m slidemage.preview_cli slides/foo-current.tex --watch
Use SLIDEMASTER_PROJECT to select the project, as with the desktop app.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import time


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
    args = parser.parse_args()
    from . import deck_scan, slide_preview
    source = args.source.resolve()
    _, slug, _ = slide_preview.call_for_slide_path(source)
    preamble = None
    if args.deck:
        preamble = next(d.preamble_text for d in deck_scan.scan_decks() if d.name == args.deck)
    previous = None
    while True:
        body = source.read_text(encoding='utf-8')
        if args.lines:
            first, last = map(int, args.lines.split(':'))
            if first < 1 or last < first:
                parser.error('--lines must be an inclusive positive range')
            body = '\n'.join(body.splitlines()[first-1:last])
        if body != previous:
            start = time.perf_counter()
            try:
                pdf = slide_preview.render_slide_text_to_pdf(
                    slug, body, preamble_text=preamble, preview_mode=args.mode,
                    overlay=args.overlay, reuse_build=not args.no_cache, log=print)
                print(f'{time.perf_counter()-start:.3f}s: {pdf}', flush=True)
                if args.open:
                    slide_preview.open_pdf(pdf)
            except (RuntimeError, ValueError) as exc:
                print(str(exc), flush=True)
                if not args.watch:
                    raise SystemExit(1)
            previous = body
        if not args.watch:
            break
        time.sleep(.3)


if __name__ == '__main__':
    main()
