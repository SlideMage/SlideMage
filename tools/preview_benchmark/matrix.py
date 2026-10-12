"""Measure every applicable full-slide combination of results 1, 3 and 4.

R1 is reusable latexmk state (the format probe records whether .fmt is viable).
R3 is an in-memory complete-frame region. R4 requests overlay 1 of each frame.
R2 is measured separately on selectable self-contained manual code snippets.
Run sequentially, without other TeX compilers, after run.py's baseline.
"""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

import pymupdf
from slidemage import deck_scan, project, deck_editor, slide_preview
from slidemage.preview_build import build_lock


def signature(pdf):
    with pymupdf.open(pdf) as doc:
        return [dict(width=p.rect.width, height=p.rect.height,
                     pixels=hashlib.sha256(p.get_pixmap().samples).hexdigest()) for p in doc]


def run_matrix(args):
    deck = next(d for d in deck_scan.scan_decks(project.transitional_context()) if d.name == 'slidemage-manual')
    calls = [c for c in deck_editor.parse_slide_calls(deck)
             if not deck_editor.is_commented_out(deck.text, c)][:args.limit]
    original = project.transitional_context()
    original_build = original.build_dir
    original_compile = slide_preview.compile_and_extract
    revision = 0
    reference_stamp = ""

    def compile_revision(wrapper, *a, **kw):
        # Forces an actual TeX rerun while keeping rendered pixels unchanged.
        # This is a changed-input rebuild, NOT a cache-hit or word-edit timing.
        wrapper = wrapper.replace(r'\end{document}', f'\\def\\SMPreviewBenchmarkRevision{{{revision}}}\n' + r'\end{document}')
        # The footer-annotation example measures timestamp width even with
        # its visible timestamp disabled. Freeze it to the baseline PDF clock.
        wrapper = wrapper.replace(r'\begin{document}', r'\begin{document}' +
                                  '\n' + slide_preview._preview_timestamp_line(True, reference_stamp), 1)
        return original_compile(wrapper, *a, **kw)

    slide_preview.compile_and_extract = compile_revision
    for cache, region, overlay in ((True, False, False), (False, True, False),
                                   (False, False, True), (True, True, False),
                                   (True, False, True), (False, True, True),
                                   (True, True, True)):
        if not any((cache, region, overlay)):
            continue
        stage = '+'.join(str(n) for n, enabled in ((1, cache), (3, region), (4, overlay)) if enabled)
        if args.stages and stage not in args.stages:
            continue
        out = args.output / stage
        out.mkdir(parents=True, exist_ok=True)
        # Isolate all combinations so none benefits from a preceding stage.
        project.use(project.ProjectContext(original.root, original_build / ('benchmark-' + stage) if cache else original_build))
        for i, call in enumerate(calls, 1):
            if (args.output / 'STOP').exists():
                print('Stopped between previews; remove STOP to resume.', flush=True)
                return
            if (out / f'{i:03}.json').exists():
                continue
            if cache:
                project.use(project.ProjectContext(original.root, original_build / ('benchmark-' + stage) / f'{i:03}'))
            with pymupdf.open(args.output / 'baseline' / f'{i:03}.pdf') as ref:
                date = ref.metadata['creationDate'][2:14]
                reference_stamp = f'{date[:4]}-{date[4:6]}-{date[6:8]} {date[8:10]}:{date[10:12]}'
            log = []
            row = dict(stage=stage, index=i, slide=call.id_slug, macro=call.macro, steps=call.steps)
            common = dict(preamble_text=deck.preamble_text, frame_number=i,
                          footer_timestamp=False, log=log.append,
                          reuse_build=cache, overlay=1 if overlay else None)
            if region:
                source = (project.transitional_context().root / 'slides' / call.source_filename).read_text()
                # Match the selected call's reveal restriction when rendering a
                # complete source region rather than invoking the saved-file macro.
                if call.steps:
                    source = f'\\gdef\\SMSlideSteps{{{call.steps}}}\n' + source
                def render():
                    return slide_preview.render_slide_text_to_pdf(project.transitional_context(), call.id_slug, source, preview_mode='region', **common)
            else:
                def render():
                    return slide_preview.render_slide_to_pdf(project.transitional_context(), call.macro, call.id_slug, call.version, call.conditions,
                                                              steps=call.steps, **common)
            try:
                revision = 0
                start = time.perf_counter()
                pdf = render()
                row['cold_seconds'] = time.perf_counter() - start
                if cache:
                    shutil.rmtree(pdf.parent)
                    revision = 1
                    start = time.perf_counter()
                    pdf = render()
                    row['seconds'] = time.perf_counter() - start
                    # Keep a separate unchanged-input measurement; do not rank
                    # these cache hits against actual compilation latency.
                    start = time.perf_counter()
                    hit = render()
                    row['unchanged_seconds'] = time.perf_counter() - start
                    shutil.rmtree(hit.parent)
                else:
                    row['seconds'] = row['cold_seconds']
                shutil.copy2(pdf, out / f'{i:03}.pdf')
                shutil.rmtree(pdf.parent)
                sig = signature(out / f'{i:03}.pdf')
                row['pages'] = len(sig)
                baseline = signature(args.output / 'baseline' / f'{i:03}.pdf')
                # Overlay 1 matches the first page for ordinary one-frame slides;
                # repeated slidestep calls with only overlay 3 are marked separately.
                row['pixel_match'] = sig == (baseline[:1] if overlay else baseline)
                if overlay and call.steps == '3':
                    row['pixel_match'] = None
                    row['comparison_note'] = 'Requested overlay 1 is absent from the baseline call restricted to overlay 3'
                row['ok'] = True
            except Exception as exc:
                row.update(ok=False, error=str(exc))
            (out / f'{i:03}.log').write_text('\n'.join(log))
            (out / f'{i:03}.json').write_text(json.dumps(row, indent=2))
            with (out / 'measurements.jsonl').open('a') as stream:
                stream.write(json.dumps(row)+'\n')
            print(json.dumps(row), flush=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stages', nargs='*')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with build_lock(args.output / 'matrix.lock'):
        run_matrix(args)


if __name__ == '__main__':
    main()
