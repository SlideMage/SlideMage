# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional framework inputs must be covered even when the recorder never sees them."""
from fnmatch import fnmatchcase
from pathlib import Path
import re

from slidemage.render_evidence import PROBES


def test_framework_probes_are_covered_by_the_inventory():
    framework = Path(__file__).resolve().parents[1] / 'latex'
    probes = r'\\(?:Input)?IfFileExists\b|\b(?:io\s*\.\s*open|kpse\s*\.\s*find_file|lfs\s*\.\s*attributes)\s*\('
    counts = {}
    skipped = {'pdf', '.temp', 'snapshots', '.git', '.build', '.previews', '.backups', '.slidemage',
               '.pytest_cache', '__pycache__', '.venv', 'node_modules'}
    for path in sorted(framework.rglob('*')):
        if path.suffix not in {'.tex', '.sty', '.cls', '.lua'}:
            continue
        source = path.read_text(encoding='utf-8')
        # Strip comments, including TeX comments around embedded Lua, before counting calls.
        source = re.sub(r'--[^\n]*' if path.suffix == '.lua' else r'(?<!\\)%[^\n]*', '', source)
        for probe in re.finditer(probes, source):
            kind = re.sub(r'\s+', '', probe.group()).rstrip('(')
            counts[kind] = counts.get(kind, 0) + 1
            where = f'{path.name}: {source.count(chr(10), 0, probe.start()) + 1}'
            rest = source[probe.end():]
            if kind.startswith('\\'):
                argument = re.match(r'\s*\{([^{}]*)\}', rest)
                assert argument, where
                name = argument[1]
                if name in {r'\jobname.ovl', r'\jobname.top'}:
                    assert kind == r'\InputIfFileExists', where
                    continue
                if name == '#1':
                    definition = source[:probe.start()].rsplit(r'\newcommand', 1)[-1]
                    assert definition.startswith(r'{\SMUseBibliography}[1][SlideMage.bib]{'), where
                    assert definition.rstrip().endswith(r'\def\input@path{}'), where
                    assert rest.startswith(r'{#1}{\addbibresource{#1}}{\addbibresource{../#1}}'), where
                    assert any(fnmatchcase('references.bib', pattern) for pattern in PROBES), where
                    continue
                # These two macros expand only the filename, never its search folder.
                name = name.replace(r'\SMLayoutProfile', 'profile').replace(r'\SMCitationFormat', 'format')
                assert not re.search(r'[\\#]', name), (where, name)
                names = [name]
            elif kind == 'kpse.find_file':
                argument = re.match(r'\s*(.*?)\)', rest, re.S)
                assert argument and re.fullmatch(
                    r'"(?:hyphenation/)?hyph-"\s*\.\.\s*file\s*\.\.\s*"\.pat\.txt"'
                    r'|"SlideMage_(?:alt|measure)\.lua",\s*"(?:lua|tex)"', argument[1]), where
                if argument[1].startswith('"hyph'):
                    assert all(any(fnmatchcase(name, pattern) for pattern in PROBES)
                               for name in ('hyphenation/hyph-de.pat.txt', 'hyph-de.pat.txt')), where
                continue
            elif kind == 'io.open':
                argument = re.match(r'\s*(.*?),\s*"r"\s*\)', rest, re.S)
                assert argument, where
                if path.name == 'SlideMage_alt.lua' and argument[1] == 'path':
                    candidates = re.search(r'local CSV_CANDIDATES\s*=\s*\{([^}]*)\}', source)
                    assert candidates, where
                    assert re.search(r'for _, path in ipairs\(CSV_CANDIDATES\) do\s*local handle =\s*$',
                                     source[:probe.start()]), where
                    names = re.findall(r'"([^"]+)"', candidates[1])
                    assert names, where
                else:
                    # Both opens use the hyphenation kpse result (the second its companion .hyp.txt).
                    assert argument[1] in {'path', 'string.sub(path, 1, -9) .. ".hyp.txt"'}, where
                    binding = source.rfind('local path =', 0, probe.start())
                    assert binding >= 0 and re.match(
                        r'local path = not \(file == ""\) and \(kpse.find_file\("hyphenation/hyph-"',
                        source[binding:]), where
                    continue
            else:
                raise AssertionError(f'{where}: unaudited {kind} probe')
            for name in names:
                name = name.removeprefix('../')
                if name in {'media/alt-text.csv', 'media/alt-text.json'}:
                    continue
                parts = Path(name).parts
                assert parts[0] not in {'slides', 'media', 'snippets'} and not skipped.intersection(parts), (where, name)
                assert len(parts) == 1 and any(fnmatchcase(name, pattern) for pattern in PROBES), (where, name)
    assert counts == {r'\IfFileExists': 4, r'\InputIfFileExists': 2, 'kpse.find_file': 6, 'io.open': 3}
