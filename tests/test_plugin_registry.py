# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Registrar: ids, the activation lock and unsupported sizes."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage.plugins.manifest import read_manifest
from slidemage.plugins.registry import Registrar

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


def make():
    return Registrar(read_manifest(FIXTURES / "hello"))


def test_rules():
    r = make()
    with r.activation():
        r.add_command("hello.a", "A", lambda d: None)
        with pytest.raises(ValueError):
            r.add_command("hello.a", "A", lambda d: None)
        with pytest.raises(ValueError):
            r.add_command("other.a", "A", lambda d: None)
        with pytest.raises(ValueError):
            r.add_menu_entry("deck", "hello.nope")
        with pytest.raises(ValueError):
            r.add_menu_entry("file", "hello.a")
        with pytest.raises(NotImplementedError, match="large boxes are not supported yet"):
            r.add_sidebar_box("k", "K", lambda d: None, size="large")
        r.add_sidebar_box("k", "K", lambda d: None)
        r.add_settings_tab("S", lambda: None)
        r.add_deck_settings_tab("D", lambda d: None)
        r.add_render_priority(lambda d: True)
        r.add_slide_reference_check(lambda ids: [])
    c = r.contributions
    assert (len(c.commands), len(c.sidebar_boxes), len(c.settings_tabs), len(c.render_priorities),
            len(c.slide_reference_checks)) == (1, 1, 1, 1, 1)
    with pytest.raises(RuntimeError):
        r.add_render_priority(lambda d: True)
    with pytest.raises(RuntimeError):
        r.add_slide_reference_check(lambda ids: [])


def test_host_services_require_a_full_host():
    r = make()
    for call in (r.project_root, r.deck_slides, r.slide_source, r.open_slide, r.deck_output_folder, r.cache_dir):
        with pytest.raises(NotImplementedError):
            call()
