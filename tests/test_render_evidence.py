# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

from slidemage import render_evidence
from slidemage.preview_metrics import PreviewMetrics
from slidemage.render_evidence import ValidationPass, file_state


def test_validation_pass_reads_configuration_once_and_a_new_pass_sees_changes(tmp_path):
    root, bin_dir = tmp_path / 'project', tmp_path / 'bin'
    root.mkdir()
    bin_dir.mkdir()
    (root / '.latexmkrc').write_text('configuration')
    latexmk = bin_dir / ('latexmk.exe' if os.name == 'nt' else 'latexmk')
    latexmk.write_bytes(b'x' * 5000)
    latexmk.chmod(0o755)
    env = {'SLIDEMAGE_LATEX': str(tmp_path / 'framework'), 'HOME': str(tmp_path), 'PATH': str(bin_dir)}
    validation = ValidationPass()
    with PreviewMetrics() as first_read:
        first = validation.configuration(root, env)
    assert first_read.counters['content_bytes_read'] >= 5000
    assert first['tools'] == {'latexmk': file_state(latexmk), 'lualatex': None, 'biber': None}
    latexmk.write_bytes(b'y' * 5001)
    with PreviewMetrics() as second_read:
        assert validation.configuration(root, env) == first
    assert not second_read.counters.get('content_bytes_read')
    assert ValidationPass().configuration(root, env) != first


def test_inventory_ignores_unrelated_names_and_relists_only_as_needed(tmp_path, monkeypatch):
    root, framework, theme = (tmp_path / name for name in ('project', 'latex', 'theme'))
    media = root / 'media'
    directories = (root, media, root / 'decks', framework, theme, theme / 'hyphenation')
    for folder in (*directories, root / 'pdf'):
        folder.mkdir()
    picture, base = media / 'fig.png', framework / 'SlideMage_base.tex'
    for path in (picture, base):
        path.write_bytes(b'read')
    env = {'SLIDEMAGE_LATEX': str(framework), 'TEXINPUTS': str(theme)}
    inputs, listed = [picture, base], []
    scandir = os.scandir

    def listing(path):
        listed.append(path)
        return scandir(path)

    def settle():
        for folder in directories:
            os.utime(folder, (time.time() - 60,) * 2)

    def inventory(**kwargs):
        return render_evidence.search_inventory(root, env, **kwargs)

    def evidence(current):
        return render_evidence.inventory_state(current, inputs)

    monkeypatch.setattr(os, 'scandir', listing)
    settle()
    before = inventory()
    recorded = evidence(before)
    listed.clear()
    assert inventory() == before and listed == []

    (media / 'unrelated.png').write_bytes(b'unused')
    (root / 'pdf/output.pdf').write_bytes(b'output')
    assert evidence(inventory()) == recorded and listed == [media]
    for unused in (root / 'SlideMage_layout_x.tex', framework / 'SlideMage_citation_x.tex',
                   *(folder / 'SlideMage_template_x.tex' for folder in (root, framework, theme)), theme / 'logo.pdf'):
        unused.write_bytes(b'unused')
        assert evidence(inventory(force=True)) == recorded, unused
    for candidate in (media / 'fig.pdf', theme / base.name, root / 'SlideMage_project_macros.tex',
                      root / 'decks/SlideMage_project_macros.tex', media / 'alt-text.csv',
                      framework / '.latexmkrc', theme / 'hyphenation/hyph-xx.pat.txt'):
        candidate.write_bytes(b'candidate')
        assert evidence(inventory(force=True)) != recorded, candidate
        candidate.unlink()
        assert evidence(inventory(force=True)) == recorded, candidate

    settle()
    current = inventory()
    listed.clear()
    assert inventory(inputs=inputs) == current and set(listed) == {media, framework}
    listed.clear()
    assert inventory(force=True) == current and set(listed) == set(directories)
