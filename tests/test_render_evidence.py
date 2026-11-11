# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

from slidemage import render_evidence
from slidemage.render_evidence import ValidationPass, file_state


def bytes_read(function, *args):
    from slidemage.preview_metrics import PreviewMetrics

    with PreviewMetrics() as metrics:
        result = function(*args)
    return result, metrics.counters.get('content_bytes_read', 0)


def test_validation_pass_reads_configuration_once_and_a_new_pass_sees_changes(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    env = {'SLIDEMAGE_LATEX': str(tmp_path / 'framework'), 'HOME': str(tmp_path)}
    (root / '.latexmkrc').write_text('configuration')
    validation = ValidationPass()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    latexmk = bin_dir / ('latexmk.exe' if os.name == 'nt' else 'latexmk')     # `which` needs the extension on Windows
    latexmk.write_bytes(b'x' * 5000)
    latexmk.chmod(0o755)
    env = dict(env, PATH=str(bin_dir))
    first, read = bytes_read(validation.configuration, root, env)
    assert read >= 5000 and first['tools']['latexmk'] == file_state(latexmk)
    assert set(first['tools']) == {'latexmk', 'lualatex', 'biber'}
    again, read = bytes_read(validation.configuration, root, env)
    assert again == first and read == 0
    latexmk.write_bytes(b'y' * 5001)
    assert ValidationPass().configuration(root, env) != first


def test_inventory_stays_current_only_when_changed_names_cannot_affect_its_inputs(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    for folder in ('media', 'decks', 'pdf'):
        (root / folder).mkdir(parents=True)
    picture = root / 'media/fig.png'
    picture.write_bytes(b'picture')

    def settle():                       # a listing is reused only once its directory's mtime is not recent
        for folder in (root, root / 'media', root / 'decks', root / 'pdf'):
            os.utime(folder, (time.time() - 60, time.time() - 60))

    settle()
    env = {'SLIDEMAGE_LATEX': str(tmp_path / 'latex')}
    inputs = [picture]
    listed = []
    scandir = os.scandir

    def listing(path):
        listed.append(path)
        return scandir(path)

    monkeypatch.setattr(os, 'scandir', listing)
    before = render_evidence.search_inventory(root, env)
    recorded = render_evidence.inventory_state(before, inputs)
    listed.clear()
    assert render_evidence.search_inventory(root, env) == before
    assert listed == []

    (root / 'media/unrelated.png').write_bytes(b'other picture')
    (root / 'pdf/output.pdf').write_bytes(b'output')
    current = render_evidence.search_inventory(root, env)
    assert render_evidence.inventory_state(current, inputs) == recorded
    assert listed == [picture.parent]

    (root / 'media/fig.pdf').write_bytes(b'alternative')
    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) != recorded
    (root / 'media/fig.pdf').unlink()
    (root / 'decks/SlideMage_project_macros.tex').write_text('optional')
    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) != recorded
    (root / 'decks/SlideMage_project_macros.tex').unlink()
    (root / 'media/alt-text.csv').write_text('image,role')
    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) != recorded
    (root / 'media/alt-text.csv').unlink()

    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) == recorded

    settle()                            # then listed once more
    render_evidence.search_inventory(root, env)
    listed.clear()
    assert render_evidence.search_inventory(root, env, inputs=inputs) == current
    assert listed == [picture.parent]
    listed.clear()
    assert render_evidence.search_inventory(root, env, force=True) == current
    assert set(listed) == {root, picture.parent, root / 'decks'}
