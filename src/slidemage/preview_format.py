"""Precompiled preamble formats for interactive previews.

Loading a deck's preamble (beamer, tikz, pgfplots, biblatex, the theme and
its fonts) is about half of every LuaLaTeX run, and the slide-sized rest is
small. A TeX *format* stores the loaded preamble, so an edit only has to run
the slide.

A format keeps TeX's state but not the engine's, so the preamble is dumped
together with three repairs (PRELUDE_TAIL):

* pgf reserves PDF object numbers at load time; they are re-reserved when
  the document starts.
* Lua state (functions, callbacks) is gone; the template's \\SMLuaOnce{...}
  blocks, recorded in \\SMLuaReplayList, run again from \\everyjob.
* A font loaded in the preamble keeps its metrics but loses luaotfload's
  Lua-side data, so OpenType kerning and ligatures silently stop applying to
  it. The font specifications are captured when the format is dumped (see
  CAPTURE_LUA) and the fonts are defined again from \\everyjob.
* graphics caches \\saveimageresource indices by file name; an image the
  preamble measured would reference a PDF object that no longer exists, so
  those cache entries are forgotten.

None of this is guaranteed for an arbitrary preamble, so every failure path
returns None and the caller builds the slide the ordinary way; a run that
fails only with the format is repeated without it (see preview_build).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from .compiler import FATAL_ERROR_RE
from .preview_metrics import stage
from .processes import no_console_kwargs

SCHEMA = 2
ENGINE = 'lualatex'
NAME = 'preamble'   # the format's file name (and TeX jobname) inside its directory

# Runs just before the dump (a file, so TeX never tokenizes it). The captured
# specifications are stored in a Lua bytecode register, which formats keep.
BYTECODE_REGISTER = 7001
CAPTURE_LUA = r"""
local entries = {}
local n = 0
for id = 1, font.max() do
  local f = font.getfont(id)
  if f and (f.format == "opentype" or f.format == "truetype") and f.name then
    n = n + 1
    entries[n] = string.format("{%d,%q,%d}", id, f.name, f.size)
  end
end
local src = "local list = {" .. table.concat(entries, ",") .. "}\n" .. [[
local cb = callback.find("define_font")
for _, e in ipairs(list) do
  local id, name, size = e[1], e[2], e[3]
  if cb and not font.getfont(id) then
    local tfm = cb(name, size, id)
    if type(tfm) == "table" then font.define(id, tfm) end
  end
end
]]
lua.bytecode[__REGISTER__] = load(src, "slidemage-font-replay")
"""

# Appended to the preamble before \dump. Guarded: a preamble without beamer/pgf
# or without the template's replay list is dumped unchanged.
PRELUDE_TAIL = r"""
\begingroup\makeatletter
\@ifundefined{pgf@sys@pdf@install@pageresources}{}{%
  \AtBeginDocument{%
    \pdfextension obj reserveobjnum \xdef\pgf@sys@pdf@extgs@objnum{\the\numexpr\pdffeedback lastobj\relax}%
    \pdfextension obj reserveobjnum \xdef\pgf@sys@pdf@pattern@objnum{\the\numexpr\pdffeedback lastobj\relax}%
    \pdfextension obj reserveobjnum \xdef\pgf@sys@pdf@colrospaces@objnum{\the\numexpr\pdffeedback lastobj\relax}%
    \pgf@sys@pdf@install@pageresources
  }%
}
\@ifundefined{SMLuaReplayList}{}{%
  \edef\SM@t{\the\everyjob\the\SMLuaReplayList}\global\everyjob\expandafter{\SM@t}%
}
\directlua{dofile("__CAPTURE__")}
\global\everyjob\expandafter{\the\everyjob\directlua{lua.bytecode[__REGISTER__]()}}
\directlua{
  local out = {} local n = 0
  for _, name in ipairs(tex.hashtokens()) do
    if name:find("^[^ ]+[.][A-Za-z0-9]+ image") or name:find("^[^ ]+[.][A-Za-z0-9]+ height")
        or name:find("^[^ ]+[.][A-Za-z0-9]+ width") then
      n = n + 1
      out[n] = "\\global\\expandafter\\let\\csname " .. name .. "\\endcsname\\relax"
    end
  end
  tex.print(table.concat(out, " "))
}
\endgroup
\dump
"""


def _stamp(path: Path):
    try:
        info = path.stat()
    except OSError:
        return None
    return [str(path), info.st_mtime_ns, info.st_size]


def _fls_inputs(fls: Path, cwd: Path, skip: Path) -> list[str]:
    names = []
    for line in fls.read_text(errors='replace').splitlines():
        if line.startswith('PWD '):
            cwd = Path(line[4:])
        elif line.startswith('INPUT '):
            path = Path(os.path.abspath(Path(line[6:]) if Path(line[6:]).is_absolute()
                                        else cwd / line[6:]))
            if not path.is_relative_to(skip) and path.is_file():
                names.append(str(path))
    return sorted(set(names))


def _fresh(manifest: Path) -> bool:
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        return all(_stamp(Path(item[0])) == item for item in data['inputs'])
    except (OSError, ValueError, KeyError, IndexError):
        return False


def _texinputs(project_root: Path, env: dict) -> str:
    """What the project's .latexmkrc sets: the project, the framework, then the rest."""
    framework = env.get('SLIDEMASTER_LATEX') or str(project_root / '..' / 'latex')
    return os.pathsep.join([str(project_root), framework, env.get('TEXINPUTS', '')])


def stem(directory: Path) -> Path:
    return directory / NAME


def inputs(directory: Path) -> list[str]:
    """Files the format was built from: part of a preview's dependency list."""
    try:
        data = json.loads((directory / 'format.json').read_text(encoding='utf-8'))
        return [item[0] for item in data['inputs']]
    except (OSError, ValueError, KeyError):
        return []


def disable(directory: Path) -> None:
    (directory / 'format.bad').touch()


def ensure(preamble: str, key: str, *, project_root: Path, build_dir: Path, env: dict,
           log, lock) -> Path | None:
    """Return the format's directory (its `preamble.fmt` is the format), or None.

    `lock` is preview_build.build_lock: formats are shared by every slide of a
    preamble, so two previews may ask for the same one at once.
    """
    if os.environ.get('SLIDEMAGE_PREVIEW_FORMAT') == '0' or not shutil.which(ENGINE, path=env.get('PATH')):
        return None
    directory = build_dir / 'preview-formats' / f'{SCHEMA}-{key}'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with lock(directory / 'build.lock'):
            if (directory / 'format.bad').exists():
                return None
            fmt = stem(directory).with_suffix('.fmt')
            if fmt.is_file() and _fresh(directory / 'format.json'):
                return directory
            return _build(preamble, directory, project_root=project_root, env=env,
                          log=log)
    except OSError:
        return None


def _build(preamble, directory, *, project_root, env, log):
    for old in directory.glob(NAME + '.*'):
        old.unlink(missing_ok=True)
    source = stem(directory).with_suffix('.tex')
    capture = directory / 'capture.lua'
    capture.write_text(CAPTURE_LUA.replace('__REGISTER__', str(BYTECODE_REGISTER)), encoding='utf-8')
    tail = (PRELUDE_TAIL.replace('__CAPTURE__', capture.as_posix())
            .replace('__REGISTER__', str(BYTECODE_REGISTER)))
    source.write_text(preamble + '\n' + tail, encoding='utf-8', newline='')
    run_env = dict(env, TEXINPUTS=_texinputs(project_root, env))
    cwd = project_root / 'decks'
    cwd.mkdir(parents=True, exist_ok=True)
    cmd = [ENGINE, '-ini', '-recorder', '-interaction=nonstopmode', '-file-line-error',
           f'-jobname={NAME}', f'-output-directory={directory}', '&' + ENGINE, str(source)]
    kwargs = no_console_kwargs()
    log('==== Precompiling preamble (once per preamble) ====')
    with stage('format_build'):
        try:
            subprocess.run(cmd, cwd=cwd, env=run_env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=300, **kwargs)
        except (OSError, subprocess.TimeoutExpired):
            disable(directory)
            return None
    fmt = stem(directory).with_suffix('.fmt')
    logfile = stem(directory).with_suffix('.log')
    contents = logfile.read_text(errors='replace') if logfile.exists() else ''
    fls = stem(directory).with_suffix('.fls')
    # LaTeX's pre_dump hook prints a Lua error about lua-uni-algos' lazy tables
    # when the format is dumped; it does not affect the format, so it is not a failure.
    errors = [m for m in FATAL_ERROR_RE.finditer(contents)
              if 'lua-uni-' not in contents[m.start():contents.find('\n', m.start())]]
    if (not fmt.is_file() or errors or '\n!' in contents
            or 'Beginning to dump on file' not in contents or not fls.is_file()):
        log('    (preamble cannot be precompiled; previews build the ordinary way)')
        disable(directory)
        return None
    stamps = [_stamp(Path(name)) for name in _fls_inputs(fls, cwd, directory)]
    (directory / 'format.json').write_text(
        json.dumps({'inputs': [s for s in stamps if s]}), encoding='utf-8')
    return directory
