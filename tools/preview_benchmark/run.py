"""Sequential manual preview benchmark; run with SLIDEMASTER_PROJECT=example.

Writes one durable JSONL measurement per call, including errors, and retains PDFs.
No concurrency: timings include wrapper creation, latexmk and PNG snapshot capture.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

from slidemage import deck_scan, project, deck_editor, slide_preview


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--stage', default='baseline')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    deck = next(d for d in deck_scan.scan_decks(project.transitional_context()) if d.name == 'slidemage-manual')
    calls = [c for c in deck_editor.parse_slide_calls(deck)
             if not deck_editor.is_commented_out(deck.text, c)]
    for i, call in enumerate(calls[:args.limit], 1):
        log = []
        row = dict(stage=args.stage, index=i, slide=call.id_slug, macro=call.macro, steps=call.steps)
        start = time.perf_counter()
        try:
            pdf = slide_preview.render_slide_to_pdf(
                call.macro, call.id_slug, call.version, call.conditions,
                preamble_text=deck.preamble_text, frame_number=i,
                footer_timestamp=False, steps=call.steps, log=log.append, reuse_build=False)
            row['seconds'] = time.perf_counter() - start
            shutil.copy2(pdf, args.output / f'{i:03}.pdf')
            shutil.rmtree(pdf.parent)
            import pymupdf
            with pymupdf.open(args.output / f'{i:03}.pdf') as doc:
                row['pages'] = len(doc)
            row['ok'] = True
        except Exception as exc:
            row.update(seconds=time.perf_counter()-start, ok=False, error=str(exc))
        (args.output / f'{i:03}.log').write_text('\n'.join(log))
        with (args.output / 'measurements.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
