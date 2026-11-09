# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys

import pytest

from slidemage import render_evidence
from slidemage.render_evidence import FileStates, ValidationPass, file_state


@pytest.fixture
def settled(monkeypatch):
    """Files written by a test are 'racy' (changed so recently that their stat could still move) and never
    remembered; these tests act as if they had been there for a while."""
    monkeypatch.setattr(render_evidence, 'MEMO_RACY_SECONDS', -1)


def bytes_read(function, *args):
    from slidemage.preview_metrics import PreviewMetrics

    with PreviewMetrics() as metrics:
        result = function(*args)
    return result, metrics.counters.get('content_bytes_read', 0)


def states_for(tmp_path):
    root = tmp_path / 'project'
    root.mkdir(exist_ok=True)
    system = tmp_path / 'texlive'
    system.mkdir(exist_ok=True)
    return FileStates([root]), root, system


def test_a_file_outside_the_roots_is_read_once_while_its_stat_is_unchanged(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE')
    first, read = bytes_read(states, package)
    assert read == len('PACKAGE')
    second, read = bytes_read(states, package)
    assert (second, read) == (first, 0)


@pytest.mark.skipif(sys.platform == 'win32', reason='ctime is the creation time on Windows')
def test_a_file_outside_the_roots_changed_with_its_mtime_restored_is_hashed_again(settled, tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'beamer.sty'
    package.write_text('PACKAGE 1')
    first = states(package)
    old = package.stat()
    package.write_text('PACKAGE 2')
    os.utime(package, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert states(package) != first


def test_a_file_changed_a_moment_ago_is_not_remembered(tmp_path):
    states, _, system = states_for(tmp_path)
    package = system / 'cache.luc'
    package.write_text('LUA')
    assert bytes_read(states, package)[1] == bytes_read(states, package)[1] == 3


def test_a_file_inside_the_roots_is_always_read(settled, tmp_path):
    states, root, _ = states_for(tmp_path)
    theme = root / 'theme.sty'
    theme.write_text('THEME ONE')
    assert bytes_read(states, theme)[1] == bytes_read(states, theme)[1] == len('THEME ONE')


def test_validation_pass_reads_configuration_once_and_a_new_pass_sees_changes(settled, tmp_path):
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
    (root / 'decks/optional.tex').write_text('optional')
    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) != recorded
    (root / 'decks/optional.tex').unlink()
    (root / 'media/alt-text.csv').write_text('image,role')
    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) != recorded
    (root / 'media/alt-text.csv').unlink()

    assert render_evidence.inventory_state(render_evidence.search_inventory(root, env), inputs) == recorded

    listed.clear()
    assert render_evidence.search_inventory(root, env, inputs=inputs) == current
    assert listed == [picture.parent]
    listed.clear()
    assert render_evidence.search_inventory(root, env, force=True) == current
    assert set(listed) == {root, picture.parent, root / 'decks'}
