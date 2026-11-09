# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in pixel comparison of the warm fast lane with latexmk."""
import os
import shutil

import pymupdf
import pytest

from slidemage import compiler, deck_scan, preview_build, slide_preview
from slidemage.project import ProjectContext, _ignore_template_build_output
from conftest import EXAMPLE_PROJECT


@pytest.mark.skipif(os.environ.get('SLIDEMAGE_REAL_LATEX') != '1',
                    reason='set SLIDEMAGE_REAL_LATEX=1 to run real LuaLaTeX acceptance fixtures')
def test_direct_lualatex_matches_latexmk_pixels(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    shutil.copytree(EXAMPLE_PROJECT.root, root, ignore=_ignore_template_build_output)
    ctx = ProjectContext.at(root)
    deck = deck_scan.read_deck(ctx.decks_dir / 'slidemage-manual.tex')
    source = ctx.slides_dir / '1b2-EN-Managing-a-Slide-current.tex'
    text = source.read_text().replace('several also update the decks that use it.',
                                    r'several also update the decks that use it.\footnote{\fullcite{markowitz1952}}')
    calls = []
    run = compiler.run_streamed

    def observed(command, **kwargs):
        calls.append(command)
        return run(command, **kwargs)

    monkeypatch.setattr(compiler, 'run_streamed', observed)
    kwargs = dict(preamble_text=deck.preamble_text, deck_version='instructor', deck_language='EN', all_steps=True)
    slide_preview.render_slide_text_to_pdf(ctx, '1b2-EN-Managing-a-Slide', text, **kwargs)
    calls.clear()
    edited = text.replace(r'\emph{Rename\ldots}', r'\emph{Retitle\ldots}')
    direct = slide_preview.render_slide_text_to_pdf(ctx, '1b2-EN-Managing-a-Slide', edited, **kwargs)
    assert len(calls) == 1 and calls[0][0] != 'latexmk', calls
    monkeypatch.setattr(preview_build, 'DIRECT_LUALATEX', False)
    reference = slide_preview.render_slide_text_to_pdf(ctx, '1b2-EN-Managing-a-Slide', edited, force_build=True, **kwargs)
    with pymupdf.open(direct) as actual, pymupdf.open(reference) as expected:
        contents = ' '.join(' '.join(page.get_text().split()) for page in actual)
        assert 'Portfolio Selection' in contents
        assert 'Image source(s):' in contents and 'Screenshot of SlideMage' in contents
        assert any(page.get_images() for page in actual)
        assert len(actual) == len(expected)
        for page, reference_page in zip(actual, expected):
            pixels = page.get_pixmap(dpi=150)
            reference_pixels = reference_page.get_pixmap(dpi=150)
            assert (pixels.width, pixels.height, pixels.samples) == (
                reference_pixels.width, reference_pixels.height, reference_pixels.samples)
