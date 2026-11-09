# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified, immutable preview artifacts, independent of Qt and the render workers.

Recorder inputs are hashed by content. Search-root inventories additionally catch
new files which shadow a former input (including a formerly absent optional file).
Unsupported search expressions deliberately disable reuse.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import functools
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import threading
import time
import uuid

from .fileio import atomic_write
from .filelock import build_lock
from .preview_metrics import measure
from .render_evidence import (FileStates, ValidationPass, configuration_state, dependency_state, digest,
                             file_state, input_state, search_roots, search_state, thumbnail_png)

SCHEMA = 2
MAX_BYTES = 512 * 1024 * 1024
MAX_AGE = 14 * 86400
PRUNE_INTERVAL = 600
# Per cache root, in this process: [monotonic time of the last prune(), bytes the cache holds by estimate].
_PRUNED = {}
_PRUNED_LOCK = threading.Lock()


def valid_sequence(value):
    from .preview_raster import SEQUENCE_SCHEMA, SEQUENCE_DPI

    if not isinstance(value, dict):
        return False
    config = value.get('configuration', {})
    if not isinstance(config, dict):
        return False
    pages = value.get('pages')
    if not isinstance(pages, list) or not pages:
        return False
    for page in pages:
        if (not isinstance(page, dict) or set(page) != {'size', 'pixels', 'sha256'}
                or not isinstance(page['size'], list) or len(page['size']) != 2
                or not isinstance(page['pixels'], list) or len(page['pixels']) != 2
                or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in page['size'])
                or any(type(n) is not int or n <= 0 for n in page['pixels'])
                or not isinstance(page['sha256'], str) or len(page['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in page['sha256'])):
            return False
    return (config.get('schema') == SEQUENCE_SCHEMA and config.get('dpi') == SEQUENCE_DPI
            and config.get('colorspace') == 'rgb' and config.get('alpha') is False
            and config.get('annots') is True and isinstance(config.get('renderer'), str)
            and bool(value.get('pages'))
            and value.get('signature') == digest({key: value[key] for key in ('configuration', 'pages')}))


def same_pinned_resolution(old, new, inputs, identity):
    """Only audited pinned calls may ignore non-shadowing new frozen siblings.

    Supported source rules cannot enumerate version files or test optional inputs.
    Existing entries, dependency bytes and tool configuration must still match;
    a new file bearing any recorded input's basename could shadow it and misses.
    """
    if (not identity.get('target', [None, None, None])[2]
            or identity['options'].get('presenter') or identity['options'].get('mode') != 'slide'
            or old['configuration'] != new['configuration']
            or set(old['search']) != set(new['search'])):
        return False
    basenames = {Path(path).name for path in inputs}
    slides = (Path(identity['root']) / 'slides').resolve()
    for root, entries in old['search'].items():
        current = new['search'][root]
        if entries is None or current is None:
            if entries != current:
                return False
            continue
        previous = {tuple(entry) for entry in entries}
        latest = {tuple(entry) for entry in current}
        if not previous <= latest:
            return False
        for relative, symlink in latest - previous:
            path = Path(root) / relative
            if (symlink is not None or path.resolve().parent != slides or path.name in basenames
                    or re.fullmatch(r'.+-v[0-9]+-[0-9]+-[0-9]+\.tex', path.name) is None):
                return False
    return True


@dataclass(frozen=True)
class CachedPreview:
    directory: Path
    pdf: Path | None
    display_png: bytes | None
    secondary_png: bytes | None
    page_images: tuple
    dependencies: tuple[str, ...]
    render_stamp: str | None
    raster_sequence: dict | None = None
    deduplicated_images: int = 0
    sequence_images: tuple[bytes, ...] = ()
    request_spec: object | None = None


class PreviewCache:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        from .project import preview_cache_dir
        self.root = preview_cache_dir(self.project_root) / 'render-results'
        # An earlier build kept this cache inside the project (synced along with it): it is only a cache.
        old = self.project_root / '.previews' / 'render-results'
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
        self._thumbnail_original = {}

    def canonical_image_id(self, path: Path) -> str:
        """Return the final-page blob hash even when its display is a small thumbnail."""
        return self._thumbnail_original.get(path, path.stem)

    def _evidence(self, env: dict, *, stability=False):
        return {'configuration': configuration_state(self.project_root, env),
                'search': search_state(self.project_root, env, stability=stability)}

    def begin(self, env: dict):
        """Capture a race guard before compilation; None means do not store."""
        try:
            return self._evidence(env, stability=True)
        except (OSError, ValueError):
            return None

    def lookup(self, identity, env: dict, *, validation=None) -> CachedPreview | None:
        return self._lookup(identity, env, validation=validation)

    def group_lookup(self, group: str, env: dict, *, validation=None, thumbnail=False, display_only=False):
        """Validated image-group representative and its own PDF view.

        The representative's exact record carries recorder inputs and all
        artifact checks. Its PDF is never evidence for another view's PDF.
        """
        try:
            path = self.root / 'groups' / group / 'current.json'
            record = json.loads(path.read_text())
            if record.get('schema') != SCHEMA or record.get('group') != group:
                return None
            identity = record['identity']
            entry = self._lookup(identity, env, validation=validation, thumbnail=thumbnail,
                                 display_only=display_only)
            return (entry, record['view'], identity, record.get('classification_evidence')) if entry is not None else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def publish_group(self, group: str, identity, view: str, *, evidence: str):
        """Point a content-derived image group at a verified exact-view record."""
        if not group.startswith('group-') or not group[6:].isalnum():
            return
        path = self.root / 'groups' / group / 'current.json'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, json.dumps({'schema': SCHEMA, 'group': group, 'identity': identity,
                                           'view': view, 'classification_evidence': evidence}))
        except OSError:
            pass  # The exact per-view record remains usable.

    @staticmethod
    def display_context(identity):
        """Display history crosses source edits, but no deck/view/scope boundary."""
        context = json.loads(json.dumps(identity))
        if isinstance(context.get('source'), dict):
            context['source'].pop('content_hash', None)
        return context

    def remember_display(self, requested_identity, representative_identity, representative_view,
                         *, evidence=None, observed_at=None):
        """Persist which exact artifact supplied one requested view's fresh pixels."""
        context = self.display_context(requested_identity)
        path = self.root / 'display-history' / digest(context) / 'current.json'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            observed_at = observed_at or time.time_ns()
            with build_lock(path.parent / 'history.lock'):
                try:
                    prior = json.loads(path.read_text())
                except (OSError, ValueError):
                    prior = {}
                if prior.get('observed_at', -1) > observed_at:
                    return
                atomic_write(path, json.dumps({'schema': SCHEMA, 'context': context,
                                               'representative': representative_identity,
                                               'representative_view': representative_view,
                                               'classification_evidence': evidence,
                                               'observed_at': observed_at}))
        except (OSError, TypeError, ValueError):
            pass  # Display history must never disrupt a valid render.

    def previous_display(self, requested_identity, *, validation=None, thumbnail=False):
        """Return historical pixels and their original view provenance, never freshness."""
        context = self.display_context(requested_identity)
        try:
            path = self.root / 'display-history' / digest(context) / 'current.json'
            record = json.loads(path.read_text())
            if record.get('schema') != SCHEMA or record.get('context') != context:
                return None
            representative = record['representative']
            artifact = self._lookup(representative, {}, validation=validation,
                                    thumbnail=thumbnail, display_only=not thumbnail, historical=True)
            return (artifact, record['representative_view'], representative,
                    record.get('classification_evidence'), record.get('observed_at', 0)) if artifact is not None else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def remember_transient(self, requested_identity, png: bytes, view: str, *, observed_at=None):
        """Keep accepted pixels as display-only history when validation is unavailable."""
        context = self.display_context(requested_identity)
        checksum = hashlib.sha256(png).hexdigest()
        image = self.root / 'transient-images' / (checksum + '.png')
        path = self.root / 'transient-history' / digest(context) / 'current.json'
        try:
            image.parent.mkdir(parents=True, exist_ok=True)
            with build_lock(self.root / 'transient-maintenance.lock', shared=True):
                if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != checksum:
                    atomic_write(image, png)
                path.parent.mkdir(parents=True, exist_ok=True)
                observed_at = observed_at or time.time_ns()
                with build_lock(path.parent / 'history.lock'):
                    try:
                        prior = json.loads(path.read_text())
                    except (OSError, ValueError):
                        prior = {}
                    if prior.get('observed_at', -1) > observed_at:
                        return
                    atomic_write(path, json.dumps({'schema': SCHEMA, 'context': context, 'checksum': checksum,
                                                   'source_hash': requested_identity.get('source', {}).get('content_hash'),
                                                   'view': view, 'observed_at': observed_at}))
            self._prune_transients()
        except (OSError, TypeError, ValueError):
            pass

    def _prune_transients(self):
        """Bound display-only fallback records and their content-addressed PNGs."""
        with build_lock(self.root / 'transient-maintenance.lock', blocking=False) as acquired:
            if not acquired:
                return
            records = sorted((path for path in (self.root / 'transient-history').glob('*/current.json')),
                             key=lambda path: path.stat().st_mtime_ns, reverse=True)
            keep = records[:256]
            for path in records[256:]:
                shutil.rmtree(path.parent, ignore_errors=True)
            referenced = set()
            for path in keep:
                try:
                    referenced.add(json.loads(path.read_text())['checksum'])
                except (OSError, ValueError, KeyError, TypeError):
                    return
            for image in (self.root / 'transient-images').glob('*.png'):
                if image.stem not in referenced:
                    image.unlink(missing_ok=True)

    def previous_transient(self, requested_identity, *, thumbnail=False):
        context = self.display_context(requested_identity)
        try:
            record = json.loads((self.root / 'transient-history' / digest(context) / 'current.json').read_text())
            if record.get('schema') != SCHEMA or record.get('context') != context:
                return None
            checksum = record['checksum']
            if not isinstance(checksum, str) or len(checksum) != 64:
                return None
            image = self.root / 'transient-images' / (checksum + '.png')
            data = image.read_bytes()
            if hashlib.sha256(data).hexdigest() != checksum:
                return None
            return (image if thumbnail else data, checksum, record['source_hash'],
                    record['view'], record.get('observed_at', 0))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def previous(self, identity) -> CachedPreview | None:
        """Display-only historical result: verify artifacts, never assert freshness.

        The exact source/view/deck identity must still match. Render requests
        continue using lookup(), which validates every dependency.
        """
        return self._lookup(identity, {}, historical=True)

    def display_lookup(self, identity, env: dict, *, validation=None, historical=False) -> CachedPreview | None:
        """Validate final pixels and inputs without loading unrelated reveal blobs."""
        return self._lookup(identity, env, validation=validation, display_only=True, historical=historical)

    def thumbnail_path(self, identity, env: dict, validation: ValidationPass) -> Path | None:
        """The same verified final-page image as the pane, without loading all PNGs.

        Content-addressed image paths are safe for the delegate's pixmap cache.
        A concurrent eviction simply makes the delegate show a placeholder.
        """
        return self._lookup(identity, env, validation=validation, thumbnail=True)

    def previous_thumbnail_path(self, identity, validation: ValidationPass) -> Path | None:
        """Integrity-checked historical image for display with an older-preview label."""
        return self._lookup(identity, {}, validation=validation, thumbnail=True, historical=True)

    @measure('cache_validation')
    def _lookup(self, identity, env, *, validation=None, thumbnail=False, display_only=False, historical=False):
        from .preview_equivalence import CONTRACT
        try:
            files = FileStates(search_roots(self.project_root, {} if historical else env))   # historical: no inputs checked
            states = (functools.partial(validation.inputs, states=files) if validation is not None
                      else functools.partial(input_state, states=files))
            identity = json.loads(json.dumps(identity))
            with build_lock(self.root / 'maintenance.lock', shared=True):
                index = json.loads((self.root / digest(identity) / 'current.json').read_text())
                directory = self.root / digest(identity) / index['generation']
                if directory.parent != self.root / digest(identity) or not directory.name.isalnum():
                    return None
                data = json.loads((directory / 'manifest.json').read_text())
                if data['schema'] != SCHEMA or data['identity'] != identity:
                    return None
                if not historical:
                    evidence = validation.evidence(self, env) if validation is not None else self._evidence(env)
                    if data['evidence'] != evidence and not (
                            type(data.get('audited_resolution')) is int and
                            data['audited_resolution'] == CONTRACT and
                            same_pinned_resolution(data['evidence'], evidence, data['inputs'], identity)):
                        return None
                    inputs = (validation.dependency_inputs(data['inputs'], files) if validation is not None
                              else dependency_state(data['inputs'], files))
                    if data['inputs'] != inputs:
                        return None
                if data.get('raster_sequence') is not None and not valid_sequence(data['raster_sequence']):
                    return None
                sequence_count = len((data.get('raster_sequence') or {}).get('pages', []))
                if any(f'sequence-{index}.png' not in data['blobs'] for index in range(sequence_count)):
                    return None
                artifacts = data['artifacts']
                if any(Path(name).name != name for name in artifacts):
                    return None
                if not thumbnail and not display_only and states(directory / name for name in artifacts) != {
                        str(directory / name): state for name, state in artifacts.items()}:
                    return None
                blobs = data['blobs']
                checked = (blobs.get('display.png'),) if display_only else (
                    (blobs.get('thumbnail.png') or blobs.get('display.png'),) if thumbnail else
                    (checksum for name, checksum in blobs.items() if name != 'thumbnail.png'))
                for checksum in checked:
                    if (not isinstance(checksum, str) or len(checksum) != 64
                            or any(c not in '0123456789abcdef' for c in checksum)):
                        return None
                    path = self.root / 'images' / (checksum + '.png')
                    state = states((path,))[str(path.absolute())]
                    if state is None or state[1] != checksum:
                        if thumbnail and checksum == blobs.get('thumbnail.png') and blobs.get('display.png'):
                            fallback = blobs['display.png']
                            fallback_path = self.root / 'images' / (fallback + '.png')
                            fallback_state = states((fallback_path,))[str(fallback_path.absolute())]
                            if fallback_state is not None and fallback_state[1] == fallback:
                                checked = (fallback,)
                                break
                        return None
                if thumbnail:
                    checksum = checked[0]
                    original = blobs.get('display.png')
                    if checksum and original:
                        path = self.root / 'images' / (checksum + '.png')
                        self._thumbnail_original[path] = original
                        return path
                    return None
                if display_only:
                    checksum = blobs.get('display.png')
                    if not checksum:
                        return None
                    pdf = directory / 'preview.pdf'
                    expected = artifacts.get('preview.pdf')
                    pdf_state = states((pdf,)).get(str(pdf.absolute())) if expected is not None else None
                    return CachedPreview(directory, pdf if pdf_state == expected else None,
                                         (self.root / 'images' / (checksum + '.png')).read_bytes(), None, (),
                                         tuple(data['inputs']), data.get('render_stamp'), data.get('raster_sequence'))
                return self._read(directory, data)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            return None

    def _read(self, directory, data):
        def png(name):
            checksum = data['blobs'].get(name)
            return (self.root / 'images' / (checksum + '.png')).read_bytes() if checksum else None
        return CachedPreview(directory, directory / 'preview.pdf', png('display.png'), png('secondary.png'),
                             tuple((tuple(name) if isinstance(name, list) else name, png(filename)) for name, filename in data['pages']),
                             tuple(data['inputs']), data.get('render_stamp'),
                             data.get('raster_sequence'), data.get('deduplicated_images', 0),
                             tuple(png(f'sequence-{index}.png') for index in
                                   range(len((data.get('raster_sequence') or {}).get('pages', [])))))

    def store(self, identity, env: dict, *, pdf: Path, display_png=None, secondary_png=None,
              page_images=(), dependencies=(), render_stamp=None, before=None,
              raster_sequence=None, audited_resolution=False, thumbnail=None) -> CachedPreview | None:
        """Record a finished render. `thumbnail` is the list thumbnail if the rasteriser already made one."""
        from .preview_equivalence import CONTRACT
        directory = None
        try:
            identity = json.loads(json.dumps(identity))
            current = self.begin(env)
            if before is None or before != current:
                return None
            # A missing recorder is not evidence of an input-free TeX document.
            if not dependencies:
                return None
            files = FileStates(search_roots(self.project_root, env))
            inputs = dependency_state(dependencies, files)
            # What _evidence() would give right now: `current` without the stability fields. The check below
            # (begin() again) rejects the result unless nothing moved in between.
            evidence = {'configuration': current['configuration'],
                        'search': {root: None if entries is None else [entry[:2] for entry in entries]
                                   for root, entries in current['search'].items()}}
            with build_lock(self.root / 'maintenance.lock', shared=True):
                parent = self.root / digest(identity)
                # Short names: the cache sits several folders deep in a project, and Windows paths stop at 260.
                directory = parent / uuid.uuid4().hex[:16]
                directory.mkdir(parents=True)
                shutil.copy2(pdf, directory / 'preview.pdf')
                written = (directory / 'preview.pdf').stat().st_size
                blobs = {'display.png': display_png, 'secondary.png': secondary_png,
                         'thumbnail.png': thumbnail if thumbnail is not None else
                                          thumbnail_png(display_png) if display_png is not None else None}
                pages = []
                for index, (name, data) in enumerate(page_images):
                    filename = f'page-{index}.png'
                    blobs[filename] = data
                    pages.append([name, filename])
                sequence_evidence = None
                if raster_sequence is not None:
                    options = identity.get('options', {})
                    if (not isinstance(options, dict) or options.get('presenter')
                            or options.get('mode', 'slide') != 'slide' or options.get('overlay') is not None):
                        raise ValueError('Raster equivalence is limited to ordinary slide previews')
                    if not valid_sequence(raster_sequence):
                        raise ValueError('Invalid raster sequence')
                    sequence_evidence = {key: raster_sequence[key] for key in ('configuration', 'signature', 'pages')}
                    if len(raster_sequence['images']) != len(sequence_evidence['pages']):
                        raise ValueError('Incomplete raster sequence')
                    for index, image in enumerate(raster_sequence['images']):
                        blobs[f'sequence-{index}.png'] = image
                references, deduplicated = {}, 0
                image_root = self.root / 'images'
                image_root.mkdir(exist_ok=True)
                for name, data in blobs.items():
                    if data is not None:
                        checksum = hashlib.sha256(data).hexdigest()
                        destination = image_root / (checksum + '.png')
                        # The name is the content hash: a blob that is there and still hashes to it is the same
                        # image (FileStates memoises the check: the cache lies outside the roots).
                        if destination.exists() and files(destination) == [str(destination.resolve()), checksum]:
                            deduplicated += 1
                        else:
                            atomic_write(destination, data)
                            written += len(data)
                        references[name] = checksum
                artifacts = {path.name: file_state(path) for path in directory.iterdir()}
                data = {'schema': SCHEMA, 'identity': identity, 'created': time.time(),
                        'evidence': evidence, 'inputs': inputs, 'artifacts': artifacts,
                        'pages': pages, 'render_stamp': render_stamp, 'blobs': references,
                        'raster_sequence': sequence_evidence, 'deduplicated_images': deduplicated,
                        'audited_resolution': CONTRACT if audited_resolution else None}
                if before != self.begin(env) or inputs != input_state(dependencies, files):
                    shutil.rmtree(directory, ignore_errors=True)
                    return None
                manifest = json.dumps(data)
                atomic_write(directory / 'manifest.json', manifest)
                atomic_write(parent / 'current.json', json.dumps({'generation': directory.name}))
                with _PRUNED_LOCK:
                    if str(self.root) in _PRUNED:
                        _PRUNED[str(self.root)][1] += written + len(manifest)
                return self._read(directory, data)
        except (OSError, ValueError, TypeError, KeyError):
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            return None

    @contextmanager
    def lease(self, entry: CachedPreview, *, blocking=True):
        """Keep this generation alive until the consumer releases its PDF."""
        lease = None
        path = entry.directory / ('.lease-' + uuid.uuid4().hex[:12] + '.lock')
        try:
            with build_lock(self.root / 'maintenance.lock', shared=True, blocking=blocking) as acquired:
                if not acquired:
                    raise BlockingIOError('Preview maintenance is in progress')
                if not entry.pdf.is_file():
                    raise FileNotFoundError(entry.pdf)
                # Windows byte locks are exclusive even for shared=True. Each
                # consumer therefore owns its own lock, never another reader's.
                lease = build_lock(path)
                lease.__enter__()
            yield entry
        finally:
            if lease is not None:
                lease.__exit__(None, None, None)
                path.unlink(missing_ok=True)

    def maybe_prune(self):
        """prune() for the render path: at most every PRUNE_INTERVAL seconds, or when the cache may be over its limit.

        The first call in a process prunes. Then prune() leaves an estimate of the cache size, store() adds what
        it wrote, and the next prune() happens when the interval has passed or the estimate exceeds MAX_BYTES.
        """
        with _PRUNED_LOCK:
            state = _PRUNED.get(str(self.root))
            if state is not None and time.monotonic() - state[0] < PRUNE_INTERVAL and state[1] <= MAX_BYTES:
                return
        self.prune()

    def _generations(self):
        """(manifest time, bytes, folder) of every <digest>/<generation>/ folder that holds a manifest."""
        def entries(path):
            try:
                with os.scandir(path) as listing:
                    return list(listing)
            except OSError:
                return []
        found = []
        for top in entries(self.root):
            for generation in entries(top.path) if top.is_dir() else ():
                try:
                    size, stamp = 0, None
                    for item in entries(generation.path) if generation.is_dir() else ():
                        if item.is_file():
                            stat = item.stat()
                            size += stat.st_size
                            if item.name == 'manifest.json':
                                stamp = stat.st_mtime
                    if stamp is not None:
                        found.append((stamp, size, Path(generation.path)))
                except OSError:
                    continue
        return found, sum(item.stat().st_size for item in entries(self.root / 'images') if item.name.endswith('.png'))

    def prune(self, *, max_bytes=MAX_BYTES, max_age=MAX_AGE):
        """Remove oldest unleased generations. Current records may become misses."""
        with build_lock(self.root / 'maintenance.lock', blocking=False) as permitted:
            if not permitted:
                return
            entries, images = self._generations()
            total = sum(size for _, size, _ in entries) + images
            deleted = False
            for stamp, size, directory in sorted(entries):
                if stamp >= time.time() - max_age and total <= max_bytes:
                    continue
                leased = False
                for path in directory.glob('.lease-*.lock'):
                    with build_lock(path, blocking=False) as acquired:
                        if not acquired:
                            leased = True
                            break
                if not leased:
                    shutil.rmtree(directory, ignore_errors=True)
                    total -= size
                    deleted = True
            with _PRUNED_LOCK:
                _PRUNED[str(self.root)] = [time.monotonic(), total]
            if not deleted:
                return  # no blob lost a reference, so reading every manifest would find nothing to remove
            # The exclusive maintenance lock excludes stores and lookups. Keep
            # blobs referenced by any surviving generation, including leases.
            referenced = set()
            for manifest in self.root.glob('*/*/manifest.json'):
                try:
                    referenced.update(json.loads(manifest.read_text())['blobs'].values())
                except (OSError, ValueError, KeyError, TypeError):
                    return  # corrupt evidence cannot justify deleting shared data
            for path in (self.root / 'images').glob('*.png'):
                if path.stem not in referenced:
                    path.unlink(missing_ok=True)
