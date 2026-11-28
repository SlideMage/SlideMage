# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Committed design reference tables must match the live theme definitions."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('make_design_handbook', ROOT / 'tools/manual/make_design_handbook.py')
handbook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handbook)


def test_generated_snippets_match(tmp_path):
    handbook.generate_text(tmp_path)
    committed = ROOT / 'docs/design-handbook/snippets'
    expected = {p.name for p in (tmp_path / 'snippets').iterdir()}
    actual = {p.name for p in committed.glob('*.tex')}
    assert actual == expected, 'Regenerate design handbook tables (including removed files)'
    for name in sorted(expected):
        assert (committed / name).read_text() == (tmp_path / 'snippets' / name).read_text(), (
            f'{name} is stale: run tools/manual/make_design_handbook.py')


def test_widget_images_exist():
    media = ROOT / 'docs/design-handbook/media'
    for name in handbook.expected_images():
        assert (media / name).is_file(), f'Missing handbook widget: {name}'
        assert (media / name).stat().st_size > 0
