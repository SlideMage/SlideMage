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
    """Always read user files; memoize unchanged TeX distribution files and artifacts.

    User edits may restore mtimes. Package updates change size, mtime, inode or ctime
    (creation time on Windows). Recent files are re-read until their timestamps settle.
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


def input_state(paths) -> dict:
    return {str(Path(path).absolute()): file_state(Path(path)) for path in sorted(set(map(str, paths)))}


def webp(image: bytes, size: tuple[int, int] | None = None) -> bytes:
    """A stored page image as lossless WebP (the rasteriser's exact pixels, about half a PNG's bytes;
    docs/plans/render-store-fixes.md, D9), shrunk to fit `size` for the thumbnail."""
    from PIL import Image

    with Image.open(BytesIO(image)) as picture:
        picture.load()
        if size is not None:
            picture.thumbnail(size, Image.Resampling.LANCZOS)
        output = BytesIO()
        picture.save(output, format='WEBP', lossless=True, exact=True)
        return output.getvalue()


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


BUNDLED = '<bundled framework>'


def _label(folder) -> str:
    """A search folder as evidence. SlideMage's own framework is named, not located: a one-file build unpacks it into
    a new temporary folder at every start, and a moved install would otherwise make every render stale."""
    bundled = project.template_dir('latex')
    return BUNDLED if bundled is not None and Path(folder).absolute() == bundled.absolute() else str(folder)


def search_state(project_root: Path, env: dict) -> dict:
    """Inventory search candidates for the precompiled format."""
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
                entries.append([relative, str(path.resolve()) if path.is_symlink() else None])
        inventories[str(root)] = entries
    return inventories


_INVENTORY_DIRS = {}
_INVENTORY_LOCK = threading.Lock()


def search_inventory(project_root: Path, env: dict, *, force=False, inputs=()) -> dict:
    """Capture names before TeX starts; reuse directory listings until their mtimes change.

    A listing taken within MEMO_RACY_SECONDS of its directory's mtime is taken again: a name added in the same
    clock tick (about 16 ms on Windows) leaves the mtime unchanged.

    Sweep planning forces a full re-list; strict checks re-list the directories of
    recorded inputs. The precompiled format uses whole-tree search_state instead.
    """
    relist = {Path(path).absolute().parent for path in inputs}
    conservative, stems = {}, {}
    project_root = project_root.absolute()
    for root in search_roots(project_root, env):
        label = _label(root)
        names = conservative[label] = []
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                mtime = directory.stat().st_mtime_ns
            except FileNotFoundError:
                if directory != root:
                    raise
                conservative[label] = None
                continue
            with _INVENTORY_LOCK:
                known = _INVENTORY_DIRS.get(directory)
                if (force or directory in relist or known is None or known[0] != mtime
                        or time.time_ns() - mtime < MEMO_RACY_SECONDS * 1e9):
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
                    names.append(path.relative_to(root).as_posix())
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
    # Desktop and terminal PATHs differ; resolved tools above cover the relevant changes (2026-11-09).
    relevant = {name: value for name, value in env.items() if name.startswith(
        ('TEX', 'LUA', 'BIB', 'BST', 'FONTCONFIG', 'LATEXMK', 'MIKTEX')) or name in
        ('SLIDEMAGE_LATEX', 'SOURCE_DATE_EPOCH', 'FORCE_SOURCE_DATE', 'OSFONTDIR',
         'VARTEXFONTS', 'SLIDEMAGE_PREVIEW_FORMAT')}
    if 'SLIDEMAGE_LATEX' in relevant:
        relevant['SLIDEMAGE_LATEX'] = _label(relevant['SLIDEMAGE_LATEX'])
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
        self._configuration = {}
        self._inventories = {}
        self._frameworks = {}
        self.hashed_bytes = 0
        self.dependency_seconds = 0.0
        self.configuration_seconds = 0.0

    def build_env(self, ctx):
        from . import compiler

        if ctx.root not in self._env:
            self._env[ctx.root] = compiler.build_env(ctx)
        return self._env[ctx.root]

    def framework_dirs(self, root):
        from . import slide_templates

        if root not in self._frameworks:
            self._frameworks[root] = slide_templates.framework_dirs(root)
        return self._frameworks[root]

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
