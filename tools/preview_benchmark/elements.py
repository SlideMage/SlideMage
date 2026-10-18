"""Measure result 2 and 1+2 on four actual manual selections, separately from full slides."""
import argparse
import json
from pathlib import Path
import re
import shutil
import time

from slidemage import deck_scan, project, slide_preview
from slidemage.preview_build import build_lock


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ctx = project.from_environment()
    root = ctx.root
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == 'slidemage-manual')
    lists = (root/'snippets/1sv-1.tex').read_text()
    formula = re.search(r'\$[^$]+\$', lists)[0]
    figure = re.search(r'\\includegraphics\[[^\]]*\]\{[^}]*\}',
                      (root/'slides/1rb-EN-Figureframe-current.tex').read_text())[0]
    table = re.search(r'\\begin\{gothamtable\}.*?\\end\{gothamtable\}',
                     (root/'slides/1wa-EN-Columns-and-Tables-current.tex').read_text(), re.S)[0]
    cases = [('formula', '1sv-EN-Lists-and-Formulas', formula),
             ('list', '1sv-EN-Lists-and-Formulas', lists),
             ('figure', '1rb-EN-Figureframe', figure),
             ('table', '1wa-EN-Columns-and-Tables', table)]
    original = ctx
    build = original.build_dir
    with build_lock(args.output/'matrix.lock'):
        for cache in (False, True):
            stage = '1+2' if cache else '2'
            out = args.output/stage
            out.mkdir(parents=True, exist_ok=True)
            for name, slug, body in cases:
                log = []
                row = dict(stage=stage, selection=name, slide=slug)
                if cache:
                    ctx = project.ProjectContext(original.root, build/'benchmark-elements'/name)
                def render(revision):
                    return slide_preview.render_slide_text_to_pdf(ctx,
                        slug, body + f'\n\\def\\SMPreviewBenchmarkRevision{{{revision}}}',
                        preamble_text=deck.preamble_text, preview_mode='element', reuse_build=cache, log=log.append)
                start = time.perf_counter()
                try:
                    pdf = render(0)
                    row['cold_seconds'] = time.perf_counter()-start
                    if cache:
                        shutil.rmtree(pdf.parent)
                        start = time.perf_counter()
                        pdf = render(1)
                    row['seconds'] = time.perf_counter()-start if cache else row['cold_seconds']
                    shutil.copy2(pdf, out/(name+'.pdf'))
                    shutil.rmtree(pdf.parent)
                    row['ok'] = True
                except Exception as exc:
                    row.update(ok=False, error=str(exc))
                (out/(name+'.log')).write_text('\n'.join(log))
                with (out/'measurements.jsonl').open('a') as stream:
                    stream.write(json.dumps(row)+'\n')
                print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
