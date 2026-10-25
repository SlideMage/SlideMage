# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Thumbnails follow exact view/source/call renders; references never claim a match."""
from io import BytesIO
import os
from unittest.mock import Mock

from PIL import Image
import pytest

from slidemage import deck_outline, preview_cache, preview_requests, preview_thumbnails, slide_snapshot
from slidemage.deck_scan import Deck, parse_chapters
from slidemage.project import ProjectContext


def png(color):
    stream = BytesIO()
    Image.new('RGB', (160, 90), color).save(stream, format='PNG')
    return stream.getvalue()


@pytest.fixture
def project(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path / 'project')
    ctx.slides_dir.mkdir(parents=True)
    (ctx.root / 'media').mkdir()
    image = ctx.root / 'media/picture.png'
    image.write_bytes(png('red'))
    for name, body in {
        'aaa-EN-One-current.tex': '%% DE translation: ccc-DE-One\n\\setSlideVersion{1-0-0+}\nCurrent text',
        'aaa-EN-One-v1-0-0.tex': '\\setSlideVersion{1-0-0}\nPinned text',
        'ccc-DE-One-current.tex': '%% Translation of: aaa-EN-One\nDeutscher Text',
    }.items():
        (ctx.slides_dir / name).write_text(body)
    framework = tmp_path / 'framework'
    framework.mkdir()
    package = framework / 'theme.tex'
    package.write_text('THEME ONE')
    env = {'SLIDEMAGE_LATEX': str(framework), 'PATH': '', 'HOME': str(tmp_path)}
    monkeypatch.setattr(preview_thumbnails.compiler, 'build_env', lambda ctx: env)
    return ctx, package, image, env


def deck(ctx, body='\\slide{aaa-EN-One}\n', footer='Course'):
    preamble = '\\documentclass{beamer}\n\\newcommand{\\FooterText}{' + footer + '}\n\\begin{document}'
    text = preamble + '\n' + body + '\\end{document}\n'
    return Deck(name='course', path=ctx.root / 'decks/course.tex', archived=False, text=text,
                supports_version=True, uses_biblatex=False, preamble_end=len(preamble),
                chapters=parse_chapters(text), output_folders={})


def rows(outline):
    return [row for section in outline for row in section.rows]


def store(project, selected_deck, view='instructor', language='EN', *, color='blue', saved=True,
          occurrence=None, text=None):
    ctx, package, image, env = project
    path = ctx.slides_dir / 'aaa-EN-One-current.tex'
    spec, = preview_requests.resolve_requests(ctx, selected_deck, path, view, language,
        occurrence_key=occurrence, options=preview_requests.RenderOptions(saved=saved),
        read_source=(lambda path: text) if text is not None else None)
    # Keep engine output outside the project's search inventory, just as real builds do.
    output = ctx.root.parent / f'output-{view}-{language}-{color}.pdf'
    output.write_bytes(b'PDF ' + color.encode())
    cache = preview_cache.PreviewCache(ctx.root)
    entry = cache.store(preview_requests.cache_identity(spec), env, pdf=output,
        display_png=png(color), secondary_png=png(color),
        dependencies=(spec.target.source_path, package, image), before=cache.begin(env))
    assert entry is not None
    return spec, entry


def lookup(project, selected_deck, view='instructor', language='EN', *, read_source=None, paths=None):
    ctx = project[0]
    outline = deck_outline.build_outline(ctx, selected_deck, view, language)
    return rows(preview_thumbnails.for_outline(ctx, selected_deck, outline, view, language,
                                              read_source=read_source, paths=paths))


@pytest.mark.parametrize('view', ['instructor', 'during-course', 'after-course'])
def test_uses_the_same_final_page_as_the_selected_preview_view(project, view):
    ctx = project[0]
    selected = deck(ctx)
    expected = {}
    for canonical, color in [('instructor', 'red'), ('during-course', 'green'), ('after-course', 'blue')]:
        _, entry = store(project, selected, canonical, color=color)
        expected[canonical] = entry.display_png
    row, = lookup(project, selected, view)
    assert row.thumbnail_verified and not row.stale_preview
    assert row.thumbnail.read_bytes() == expected[view]
    assert 'whole slide, last included reveal step' in row.thumbnail_note


def test_pinned_version_and_other_deck_footer_do_not_reuse_the_current_slide_image(project):
    ctx = project[0]
    live = deck(ctx)
    pinned = deck(ctx, '\\slideversion{aaa-EN-One}{1-0-0}\n')
    store(project, live, color='red')
    _, frozen = store(project, pinned, color='blue')
    row, = lookup(project, pinned)
    assert row.thumbnail_verified and row.thumbnail.read_bytes() == frozen.display_png
    other, = lookup(project, deck(ctx, footer='Different course'))
    assert not other.thumbnail_verified and other.thumbnail is None


def test_duplicate_calls_keep_their_own_reveal_steps_and_frame_number(project):
    ctx = project[0]
    selected = deck(ctx, '\\slidestep{aaa-EN-One}{1}\n\\slidestep{aaa-EN-One}{2}\n')
    outline = deck_outline.build_outline(ctx, selected, 'instructor', 'EN')
    original = rows(outline)
    _, first = store(project, selected, color='red', occurrence=original[0].key)
    _, second = store(project, selected, color='blue', occurrence=original[1].key)
    result = lookup(project, selected)
    assert all(row.thumbnail_verified for row in result)
    assert [row.thumbnail.read_bytes() for row in result] == [first.display_png, second.display_png]


def test_multilingual_source_uses_actual_render_language_not_shared_mult_snapshot(project):
    ctx = project[0]
    selected = deck(ctx)
    store(project, selected, 'during-course', 'EN', color='red')
    _, german = store(project, selected, 'during-course', 'DE', color='blue')
    row, = lookup(project, selected, 'during-course', 'DE')
    assert row.call.id_slug == 'ccc-DE-One' and row.thumbnail_verified
    assert row.thumbnail.read_bytes() == german.display_png


def test_buffer_revision_matches_draft_render_and_does_not_reuse_saved_source(project):
    ctx = project[0]
    selected = deck(ctx)
    store(project, selected, color='red')
    draft = '\\setSlideVersion{1-0-0+}\nA different draft'
    missing, = lookup(project, selected, read_source=lambda path: draft)
    assert not missing.thumbnail_verified
    _, entry = store(project, selected, saved=False, color='blue', text=draft)
    matching, = lookup(project, selected, read_source=lambda path: draft)
    assert matching.thumbnail_verified and matching.thumbnail.read_bytes() == entry.display_png


def test_legacy_instructor_image_is_labelled_reference_and_hidden_rows_have_no_image(project):
    ctx = project[0]
    selected = deck(ctx, '\\conditionalslide[instructor]{aaa-EN-One}\n')
    reference = slide_snapshot.snapshot_path(ctx, 'aaa', size=slide_snapshot.THUMB_SIZE, id_slug='aaa-EN-One')
    reference.parent.mkdir(parents=True)
    reference.write_bytes(png('red'))
    os.utime(reference, (4_000_000_000, 4_000_000_000))
    row, = lookup(project, selected)
    assert row.thumbnail == reference and not row.thumbnail_verified and not row.stale_preview
    assert 'Shared Instructor reference' in row.thumbnail_note
    hidden, = lookup(project, selected, 'after-course')
    assert hidden.hidden and hidden.thumbnail is None


@pytest.mark.parametrize('dependency', ['source', 'framework', 'image'])
def test_content_edits_with_preserved_mtime_invalidate_thumbnail_matches(project, dependency):
    ctx, package, image, _ = project
    selected = deck(ctx)
    store(project, selected)
    path = {'source': ctx.slides_dir / 'aaa-EN-One-current.tex', 'framework': package, 'image': image}[dependency]
    original = path.stat()
    if dependency == 'source':
        path.write_text(path.read_text().replace('Current text', 'Changed text'))  # same 1-0-0+ marker
    elif dependency == 'framework':
        path.write_text('THEME TWO')
    else:
        path.write_bytes(png('blue'))
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    row, = lookup(project, selected)
    assert not row.thumbnail_verified


def test_list_validation_reads_shared_evidence_once_and_does_not_load_all_images(project, monkeypatch):
    ctx, package, _, _ = project
    selected = deck(ctx, '\\slide{aaa-EN-One}\n\\slide{aaa-EN-One}\n')
    original = rows(deck_outline.build_outline(ctx, selected, 'instructor', 'EN'))
    for row, color in zip(original, ('red', 'blue')):
        store(project, selected, occurrence=row.key, color=color)
    configuration = Mock(wraps=preview_cache.configuration_state)
    files = Mock(wraps=preview_cache.file_state)
    monkeypatch.setattr(preview_cache, 'configuration_state', configuration)
    monkeypatch.setattr(preview_cache, 'file_state', files)
    monkeypatch.setattr(preview_cache.PreviewCache, '_read', lambda *a: pytest.fail('thumbnails must not load every PNG'))
    result = lookup(project, selected)
    assert all(row.thumbnail_verified for row in result)
    assert configuration.call_count == 1
    assert sum(call.args == (package,) for call in files.call_args_list) == 1
    # A new pass must rehash, so memoization never conceals an external edit.
    package.write_text('THEME TWO')
    assert not any(row.thumbnail_verified for row in lookup(project, selected))


def test_invalidated_thumbnail_preserves_own_view_instead_of_instructor_reference(project):
    ctx, package, _, _ = project
    selected = deck(ctx)
    _, expected = store(project, selected, 'during-course', color='blue')
    reference = slide_snapshot.snapshot_path(ctx, 'aaa', size=slide_snapshot.THUMB_SIZE, id_slug='aaa-EN-One')
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(png('red'))
    package.write_text('A new theme')
    row, = lookup(project, selected, 'during-course')
    assert not row.thumbnail_verified and row.stale_preview
    assert row.thumbnail.read_bytes() == expected.display_png
    assert 'Previous render for during-course' in row.thumbnail_note
