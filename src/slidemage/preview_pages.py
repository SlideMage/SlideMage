"""Content-addressed PDF page images shared by comparisons and inspection tools.

Call on a worker: PDF hashing, cache validation and raster IPC perform I/O.
The cache includes renderer/version, page range and resolution; source edits and
PDF replacement cannot reuse old pages, even when size and mtime are preserved.
"""
from __future__ import annotations

import base64
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path

from . import preview_raster_client
from .fileio import atomic_write
from .filelock import build_lock
from .preview_cache import digest, MAX_BYTES

SCHEMA = 1
PNG = b'\x89PNG\r\n\x1a\n'


def sequence_images(request, *, start=1, count=60, dpi=130):
    """Use already validated full-sequence images when their resolution suffices.

    ``wait()`` must have succeeded first, holding the immutable cache generation.
    The source of a group consumer owns the same proven image sequence.
    """
    source = getattr(request, 'source', request)
    entry = getattr(source, '_cache_entry', None)
    evidence = getattr(entry, 'raster_sequence', None)
    images = getattr(entry, 'sequence_images', ())
    if (evidence is not None and evidence['configuration']['dpi'] >= dpi
            and images and len(images) == len(evidence['pages'])):
        return list(images[start - 1:start - 1 + count])
    return None


def read_document(pdf: Path, *, project_root: Path, start=1, count=60, dpi=130) -> dict:
    """Return ``count`` (total PDF pages) and requested PNG ``images``.

    Lock each identity so simultaneous consumers share raster work. Cache writes
    are optional; inability to persist pages must not prevent PDF inspection.
    """
    if start < 1 or count < 1 or dpi <= 0:
        raise ValueError('Page range and resolution must be positive')
    checksum = hashlib.sha256(pdf.read_bytes()).hexdigest()
    try:
        renderer = version('pymupdf')
    except PackageNotFoundError:
        from .version import VERSION_NUMBER
        renderer = f'bundled-{VERSION_NUMBER}'
    identity = dict(schema=SCHEMA, pdf=checksum, renderer=renderer,
                    start=start, count=count, dpi=dpi)
    from .project import preview_cache_dir
    root = preview_cache_dir(Path(project_root)) / 'page-images'     # this computer's, not the synced project's
    key = digest(identity)
    path = root / f'{key}.json'

    def render():
        result = preview_raster_client.read_document(pdf, 'pdf_images', start, count, dpi)
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('PDF changed while reading preview pages')
        return result

    try:
        with build_lock(root / f'{key}.lock'):
            try:
                data = json.loads(path.read_text())
                images = [base64.b64decode(item, validate=True) for item in data['images']]
                total = data['count']
                if (data['identity'] == identity and isinstance(total, int) and total >= 0
                        and len(images) == min(count, max(0, total - start + 1))
                        and all(image.startswith(PNG) for image in images)
                        and data['hashes'] == [hashlib.sha256(image).hexdigest() for image in images]):
                    if hashlib.sha256(pdf.read_bytes()).hexdigest() != checksum:
                        raise RuntimeError('PDF changed while reading preview pages')
                    return {'count': total, 'images': images}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            result = render()
            try:
                atomic_write(path, json.dumps(dict(identity=identity, count=result['count'],
                    images=[base64.b64encode(image).decode('ascii') for image in result['images']],
                    hashes=[hashlib.sha256(image).hexdigest() for image in result['images']])))
                # Bound this secondary cache independently of leased render artifacts.
                files = sorted(root.glob('*.json'), key=lambda item: item.stat().st_mtime_ns, reverse=True)
                size = 0
                for item in files:
                    size += item.stat().st_size
                    if size > MAX_BYTES and item != path:
                        item.unlink(missing_ok=True)
            except OSError:
                pass
            return result
    except OSError:
        return render()
