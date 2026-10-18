"""Page-image reuse, integrity, resolution and content-based invalidation."""
import json
import os
from types import SimpleNamespace

import pytest

from slidemage import preview_pages, preview_raster


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    import pymupdf
    path = tmp_path / 'slide.pdf'
    with pymupdf.open() as doc:
        for text in ('one', 'two', 'three'):
            doc.new_page(width=320, height=180).insert_text((20, 30), text)
        doc.save(path)
    calls = []
    def raster(*args):
        calls.append(args)
        return preview_raster.document(*args)
    monkeypatch.setattr(preview_pages.preview_raster_client, 'read_document', raster)
    return path, calls


def test_reopening_and_identical_pdf_path_reuse_pages(pdf, tmp_path):
    path, calls = pdf
    first = preview_pages.read_document(path, project_root=tmp_path)
    alias = tmp_path / 'same.pdf'
    alias.write_bytes(path.read_bytes())
    second = preview_pages.read_document(alias, project_root=tmp_path)
    assert first == second and len(calls) == 1
    assert len(first['images']) == first['count'] == 3
    higher = preview_pages.read_document(path, project_root=tmp_path, dpi=180, start=2, count=1)
    assert len(higher['images']) == 1 and len(calls) == 2
    assert preview_pages.read_document(path, project_root=tmp_path, dpi=180, start=2, count=1) == higher
    assert len(calls) == 2


def test_corrupt_pages_raster_again_and_same_stat_edit_misses(pdf, tmp_path):
    path, calls = pdf
    first = preview_pages.read_document(path, project_root=tmp_path)
    from slidemage.project import preview_cache_dir
    cache = next((preview_cache_dir(tmp_path) / 'page-images').glob('*.json'))
    data = json.loads(cache.read_text())
    data['images'][0] = data['images'][1]
    cache.write_text(json.dumps(data))
    assert preview_pages.read_document(path, project_root=tmp_path) == first
    assert len(calls) == 2
    stat = path.stat()
    original = path.read_bytes()
    assert b'%PDF-1.7' in original
    path.write_bytes(original.replace(b'%PDF-1.7', b'%PDF-1.6'))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    preview_pages.read_document(path, project_root=tmp_path)
    assert path.stat().st_size == stat.st_size and len(calls) == 3


def test_sequence_reuse_needs_sufficient_resolution():
    entry = SimpleNamespace(raster_sequence={'configuration': {'dpi': 144}, 'pages': [1, 2]},
                            sequence_images=(b'first', b'last'))
    request = SimpleNamespace(source=SimpleNamespace(_cache_entry=entry))
    assert preview_pages.sequence_images(request, start=2, count=1) == [b'last']
    assert preview_pages.sequence_images(request, dpi=200) is None
    entry.sequence_images = ()
    assert preview_pages.sequence_images(request) is None


def test_cache_write_failure_still_returns_images(pdf, tmp_path, monkeypatch):
    path, calls = pdf
    def blocked(*args):
        raise PermissionError('read only')
    monkeypatch.setattr(preview_pages, 'atomic_write', blocked)
    assert len(preview_pages.read_document(path, project_root=tmp_path)['images']) == 3
    assert len(calls) == 1
