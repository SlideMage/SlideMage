# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared render evidence and validation, independent of Qt and the render workers."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import threading
import time

from . import project
from .preview_metrics import count

# The slide list's thumbnail is 56x31.5 logical pixels (ui/workspace/slide_tree.THUMB_W): this is enough for a
# device pixel ratio of 3 (300 % display scaling); the list reduces it once to the screen's own ratio
# (2026-10-30, direct request; was 320x180, three times what any screen used).
THUMBNAIL_MAX = (168, 95)
_SKIP_DIRS = {'.git', '.build', '.previews', '.backups', '.slidemage', '.pytest_cache', '__pycache__', '.venv', 'node_modules'}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_state(path: Path):
    """Content, resolved location and missing state; never trust modification time."""
    try:
        data = path.read_bytes()
        count('content_bytes_read', len(data))
        return [str(path.resolve()), hashlib.sha256(data).hexdigest()]
    except FileNotFoundError:
        return None


MEMO_LIMIT = 20_000
MEMO_RACY_SECONDS = 3.0
_MEMO = OrderedDict()           # absolute path -> ((size, mtime_ns, inode, ctime_ns), [resolved, sha256])
_MEMO_LOCK = threading.Lock()


class FileStates:
    """file_state() that does not re-read the TeX distribution: the states of one lookup, store or validation.

    A file inside one of `roots` (the trees users edit: search_roots()) is always read, so an edit that restores
    the modification time is still seen. Any other file (TeX Live's or MiKTeX's own trees, the tool binaries, the
    cache's own artifacts) is read once per process and again only when (size, mtime, inode, ctime) changes,
    which a package update or a repair always does. ctime is when the file's metadata last changed and cannot
    be set from userland on Linux and macOS; on Windows it is the creation time, but a rewritten file still
    changes size or mtime (or its inode: an installer replaces files). A file changed less than MEMO_RACY_SECONDS
    ago is read every time, as its timestamps may not have moved yet. A missing file is never remembered.
    The result is what file_state() returns, so stored states stay valid. The memo is shared by every thread
    and bounded to MEMO_LIMIT files.
    """
    def __init__(self, roots):
        # String prefixes: Path.resolve()/is_relative_to() per input cost more than the hashing they save.
        self._prefixes = tuple(dict.fromkeys(os.path.join(os.path.normcase(str(path)), '')
                                             for root in roots for path in (root.absolute(), root.resolve())))

    def _inside(self, name: str) -> bool:
        name = os.path.join(os.path.normcase(name), '')
        return any(name.startswith(prefix) for prefix in self._prefixes)

    def __call__(self, path: Path):
        key = os.path.abspath(path)
        if self._inside(key):
            return file_state(path)
        try:
            info = os.stat(key)
        except FileNotFoundError:
            return None
        fingerprint = (info.st_size, info.st_mtime_ns, info.st_ino, info.st_ctime_ns)
        with _MEMO_LOCK:
            known = _MEMO.get(key)
            if known is not None and known[0] == fingerprint:
                _MEMO.move_to_end(key)
                return list(known[1])
        # Not known yet (or changed): a name outside the roots may still lead into them through a link. A link
        # that is pointed elsewhere later changes the fingerprint (stat follows it), so a hit never needs this.
        if self._inside(os.path.realpath(key)):
            return file_state(path)
        state = file_state(path)
        if state is not None and time.time() - max(info.st_mtime, info.st_ctime) >= MEMO_RACY_SECONDS:
            with _MEMO_LOCK:
                _MEMO[key] = (fingerprint, state)
                _MEMO.move_to_end(key)
                while len(_MEMO) > MEMO_LIMIT:
                    _MEMO.popitem(last=False)
        return state


_TOOLS = {}
TOOL_SECONDS = 30


def find_tool(name: str, path: str | None):
    """shutil.which(name, path=path), looked up again at most every TOOL_SECONDS for the same PATH (a scan of
    PATH is slow on Windows; the preview asks for six tools several times a render)."""
    now = time.monotonic()
    known = _TOOLS.get((name, path))
    if known is None or now - known[1] >= TOOL_SECONDS:
        known = _TOOLS[name, path] = (shutil.which(name, path=path), now)
    return known[0]


def input_state(paths, states=None) -> dict:
    states = states or file_state
    return {str(Path(path).absolute()): states(Path(path)) for path in sorted(set(map(str, paths)))}


def dependency_state(paths, states=None):
    paths = tuple(paths)
    result = input_state(paths, states)
    for path in paths:
        try:
            count('dependency_bytes_read', Path(path).stat().st_size)
        except FileNotFoundError:
            pass
    return result


def thumbnail_png(png: bytes) -> bytes | None:
    """Derive a small, aspect-preserving PNG from the final-page pixels."""
    try:
        from PIL import Image

        with Image.open(BytesIO(png)) as original:
            original.load()
            if original.width <= THUMBNAIL_MAX[0] and original.height <= THUMBNAIL_MAX[1]:
                return png
            original.thumbnail(THUMBNAIL_MAX, Image.Resampling.LANCZOS)
            output = BytesIO()
            original.save(output, format='PNG')
            return output.getvalue()
    except Exception:  # noqa: BLE001 -- malformed image data is a cacheable full-size fallback
        return None  # Invalid legacy/test pixels keep using the full blob.


def search_roots(project_root: Path, env: dict) -> tuple[Path, ...]:
    framework = ([Path(env['SLIDEMAGE_LATEX'])] if env.get('SLIDEMAGE_LATEX')
                 else project.sibling_framework_dirs(project_root))
    roots = [project_root, *framework]
    for name in ('TEXINPUTS', 'BIBINPUTS', 'BSTINPUTS', 'LUAINPUTS'):
        for value in env.get(name, '').split(os.pathsep):
            if not value:
                continue  # default system trees are validated through recorder inputs
            value = value.removeprefix('!!').removesuffix('//')
            if any(char in value for char in '{}$~*?'):
                raise ValueError('Unsupported TeX search expression')
            path = Path(value)
            roots.append(path if path.is_absolute() else project_root / 'decks' / path)
    return tuple(dict.fromkeys(path.absolute() for path in roots))


def search_state(project_root: Path, env: dict, *, stability=False) -> dict:
    """Inventory search candidates, not generated output or unrelated file contents.

    The stability variant also detects writes during a render, before its recorder
    has told us which files the engine read. ctime is used only for that race check;
    cache freshness itself always uses content digests.
    """
    inventories = {}
    for root in search_roots(project_root, env):
        entries = []
        if not root.exists():
            inventories[str(root)] = None
            continue
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
            dirs[:] = sorted(name for name in dirs if name not in _SKIP_DIRS)
            parent = Path(directory)
            # Directory symlinks could introduce an unbounded search tree.
            if any((parent / name).is_symlink() for name in dirs):
                raise ValueError('Unsupported symlinked TeX search directory')
            for name in sorted(files):
                if name.startswith(('_slidemage_', '_snapshot_')):
                    continue
                path = parent / name
                relative = path.relative_to(root).as_posix()
                entry = [relative, str(path.resolve()) if path.is_symlink() else None]
                if stability:
                    stat = path.stat()
                    entry.extend([stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
                entries.append(entry)
        inventories[str(root)] = entries
    return inventories


_INVENTORY_DIRS = {}
_INVENTORY_LOCK = threading.Lock()


def search_inventory(project_root: Path, env: dict, *, force=False, inputs=()) -> dict:
    """Capture names before TeX starts; reuse directory listings until their mtimes change.

    Sweep planning forces a full re-list; strict checks re-list the directories of
    recorded inputs. Keep this separate from the preview cache's whole-tree search_state.
    """
    relist = {Path(path).absolute().parent for path in inputs}
    conservative, stems = {}, {}
    project_root = project_root.absolute()
    for root in search_roots(project_root, env):
        names = conservative[str(root)] = []
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                mtime = directory.stat().st_mtime_ns
            except FileNotFoundError:
                if directory != root:
                    raise
                conservative[str(root)] = None
                continue
            with _INVENTORY_LOCK:
                known = _INVENTORY_DIRS.get(directory)
                if force or directory in relist or known is None or known[0] != mtime:
                    dirs, files = [], []
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_dir():
                                if entry.name in _SKIP_DIRS or (directory == project_root
                                        and entry.name in {'pdf', '.temp', 'snapshots'}):
                                    continue
                                if entry.is_symlink():
                                    raise ValueError('Unsupported symlinked TeX search directory')
                                dirs.append(entry.name)
                            elif not entry.name.startswith(('_slidemage_', '_snapshot_')):
                                files.append(entry.name)
                    known = _INVENTORY_DIRS[directory] = (mtime, dirs, files)
            pending.extend(directory / name for name in known[1])
            for name in known[2]:
                path = directory / name
                relative = path.relative_to(project_root) if path.is_relative_to(project_root) else None
                if (relative is not None and relative.parts[0] in {'slides', 'media', 'snippets'}
                        and relative.as_posix() not in {'media/alt-text.csv', 'media/alt-text.json'}):
                    stems.setdefault(path.stem, set()).add(str(path))
                else:
                    names.append(str(path))
        names.sort()
    return {'conservative': digest(conservative),
            'stems': {stem: sorted(paths) for stem, paths in stems.items()}}


def inventory_state(inventory: dict, inputs) -> dict:
    """Evidence to record, or compare with a record: conservative names and input-stem candidates."""
    stems = set()
    for name in inputs:
        path = Path(name)
        if not path.is_absolute() or str(path) in inventory['stems'].get(path.stem, ()):
            stems.add(path.stem)
    return {'conservative': inventory['conservative'],
            'stems': {stem: inventory['stems'].get(stem, []) for stem in sorted(stems)}}


def configuration_state(project_root: Path, env: dict) -> dict:
    """Actual compile environment, tool bytes, and latexmk configuration sources."""
    home = Path(env.get('HOME') or env.get('USERPROFILE') or Path.home())
    rc = [project_root / '.latexmkrc', project_root / 'decks/.latexmkrc', home / '.latexmkrc',
          Path(env.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'latexmk/latexmkrc', Path('/etc/LatexMk')]
    if env.get('LATEXMKRCSYS'):
        rc.append(Path(env['LATEXMKRCSYS']))
    states = FileStates(search_roots(project_root, env))
    tools = {}
    for name in ('latexmk', 'lualatex', 'pdflatex', 'xelatex', 'biber', 'bibtex'):
        executable = find_tool(name, env.get('PATH'))
        tools[name] = states(Path(executable)) if executable else None
    # Not PATH (2026-11-09): it is part of the render store's fast key now, and a terminal start and a desktop
    # start differ in PATH; the tools' resolved paths and contents above cover what it changes.
    relevant = {name: value for name, value in env.items() if name.startswith(
        ('TEX', 'LUA', 'BIB', 'BST', 'FONTCONFIG', 'LATEXMK', 'MIKTEX')) or name in
        ('SLIDEMAGE_LATEX', 'SOURCE_DATE_EPOCH', 'FORCE_SOURCE_DATE', 'OSFONTDIR',
         'VARTEXFONTS', 'SLIDEMAGE_PREVIEW_FORMAT')}
    return {'environment': relevant, 'tools': tools, 'rc': input_state(rc)}


class ValidationPass:
    """Share expensive evidence reads within one synchronous validation pass.

    Never retain this across UI refreshes: edits with unchanged mtimes still have
    to be detected on the next pass.
    """
    def __init__(self):
        self._files = {}
        self._env = {}
        self.tex = {}
        self._evidence = {}
        self._configuration = {}
        self._inventories = {}
        self.hashed_bytes = 0
        self.dependency_bytes = 0
        self.dependency_seconds = 0.0
        self.configuration_seconds = 0.0
        self.stability_seconds = 0.0
        self.stability_bytes = 0

    def build_env(self, ctx):
        from . import compiler

        if ctx.root not in self._env:
            self._env[ctx.root] = compiler.build_env(ctx)
        return self._env[ctx.root]

    def inputs(self, paths, states=None):
        states = states or file_state
        result = {}
        for path in paths:
            path = Path(path).absolute()
            key = str(path)
            if key not in self._files:
                start = time.perf_counter()
                self._files[key] = states(path)
                self.dependency_seconds += time.perf_counter() - start
                try:
                    self.hashed_bytes += path.stat().st_size
                except OSError:
                    pass
            result[key] = self._files[key]
        return result

    def dependency_inputs(self, paths, states=None):
        before = self.hashed_bytes
        result = self.inputs(paths, states)
        self.dependency_bytes += self.hashed_bytes - before
        return result

    def configuration(self, project_root, env):
        key = (str(project_root), digest(env))
        if key not in self._configuration:
            start = time.perf_counter()
            self._configuration[key] = configuration_state(project_root, env)
            self.configuration_seconds += time.perf_counter() - start
        return self._configuration[key]

    def inventory(self, project_root, env, *, force=False):
        key = (str(project_root), digest(env))
        if key not in self._inventories:
            self._inventories[key] = search_inventory(project_root, env, force=force)
        return self._inventories[key]

    def evidence(self, cache, env):
        key = (str(cache.project_root), digest(env))
        if key not in self._evidence:
            configuration = self.configuration(cache.project_root, env)
            start = time.perf_counter()
            self._evidence[key] = {'configuration': configuration,
                                  'search': search_state(cache.project_root, env)}
            self.configuration_seconds += time.perf_counter() - start
        return self._evidence[key]

    def stable(self, cache, env):
        """Reject a result if an input changed while this validation batch ran."""
        start = time.perf_counter()
        try:
            states = FileStates(search_roots(cache.project_root, env))
            for path, state in self._files.items():
                candidate = Path(path)
                current = states(candidate)
                try:
                    self.stability_bytes += candidate.stat().st_size
                except OSError:
                    pass
                if current != state:
                    return False
            key = (str(cache.project_root), digest(env))
            return key not in self._evidence or self._evidence[key] == cache._evidence(env)
        except (OSError, ValueError):
            return False
        finally:
            self.stability_seconds += time.perf_counter() - start
