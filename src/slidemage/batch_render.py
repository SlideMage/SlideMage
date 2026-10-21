# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Several slides of one deck, view and language compiled as ONE document, for the requests of a batch (preview_batch).

A deck refresh renders every slide it finds no verified preview of. Each alone costs two LuaLaTeX passes and a biber
run; k slides in one document cost them once (docs/findings.md, plan 5). The pages are the same pixel for pixel as the
slides' own renders, so each slide is split off as a PDF of its own and recorded by RenderService.request like a
render of its own (PrebuiltRender): same identity, images and cache entry. A document that does not compile or cannot be
split gives nothing, and its requests render singly.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from . import compiler, deck_context, preview_build, preview_cache, preview_raster_client, render_key, slide_preview, slide_snapshot
from .preview_requests import PrebuiltRender

ALL_PAGES = 100000


def eligible(spec) -> bool:
    """Whether a request's render can be one slide of a document of several: a whole, visible slide of a deck in
    its plain editor-style render, that needs nothing of the deck around it (a contents or agenda slide would show its
    links on every slide of the document)."""
    options, target = spec.options, spec.target
    return not (target.hidden or target.needs_context or spec.capture_error or options.presenter or options.mode != 'slide'
                or options.overlay is not None or options.all_steps or deck_context.reasons(spec.revision.text))


def groups(service, candidates, size: int) -> list[list]:
    """The documents to compile for `candidates`, [(key, request)] in plan order: the eligible requests the service
    finds no verified preview of (all, when forced), `size` at most per document, of one view, language and preamble, and
    one per bare slide id (the pages of a repeated one could not be told apart; it waits for a later document).
    A request that would be alone in its document is left out: it renders singly."""
    batches: dict[tuple, list[list]] = {}
    for key, spec in candidates:
        if size < 2 or not eligible(spec):
            continue
        try:
            if not spec.options.force and service.is_cached(spec):
                continue
        except Exception:  # noqa: BLE001 -- not classifiable: it renders singly
            continue
        open_ = batches.setdefault((spec.view, spec.language, spec.target.preamble_text), [])
        for batch in open_:
            if len(batch) < size and all(other.target.bare_id != spec.target.bare_id for _key, other in batch):
                batch.append((key, spec))
                break
        else:
            open_.append([(key, spec)])
    return sorted((batch for open_ in batches.values() for batch in open_ if len(batch) > 1),
                  key=lambda batch: batch[0][0])


def build(batch: list, cancel=None, log=None) -> dict:
    """Compile the requests of `batch` (one of `groups`') in one document and split it: {key: PrebuiltRender}. The
    guard of the cache is taken before the compile, as a render of its own would. Each slide's dependencies are the
    files the document read that its pages depend on (render_key.unit_inputs; the preamble's text counts as the
    slide's, so a picture only the preamble names stays one). RuntimeError when the document does not compile or its
    pages are not those of its slides."""
    first = batch[0][1]
    ctx, target = first.target.context, first.target
    before = preview_cache.PreviewCache(ctx.root).begin(compiler.build_env(ctx))
    if before is None:
        raise RuntimeError('the preview cache cannot guard a render now')
    slides = [(spec.target.id_slug, spec.revision.text, spec.target.frame_number, spec.target.steps, spec.target.version,
               spec.target.macro in ('omitslide', 'omitslideversion'), spec.target.macro == 'slidefinal')
              for _key, spec in batch]
    pdf = slide_preview.render_slide_texts_to_pdf(ctx, slides, first.view, first.language.lower(), target.preamble_text,
                                                  log=log, cancel=cancel)
    folders, built = [], {}
    try:
        texts = preview_raster_client.read_document(pdf, 'pdf', 1, ALL_PAGES)['texts']
        runs = slide_snapshot.batch_runs(texts, [spec.target.bare_id for _key, spec in batch])
        inputs = [Path(name) for name in json.loads(pdf.with_suffix('.inputs.json').read_text())]
        for (key, spec), pages in zip(batch, runs):
            folders.append(Path(tempfile.mkdtemp(prefix=preview_build.RENDER_FOLDER_PREFIX)))
            own = folders[-1] / f'{spec.target.id_slug}.pdf'
            preview_raster_client.read_document(pdf, 'extract_pages', pages[0] + 1, len(pages), out=own)
            files = render_key.unit_inputs(ctx, inputs, spec.target.source_path,
                                           spec.revision.text + (spec.target.preamble_text or ''))
            built[key] = PrebuiltRender(own, map(str, files), before)
        return built
    except BaseException:
        for folder in folders:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(pdf.parent, ignore_errors=True)
