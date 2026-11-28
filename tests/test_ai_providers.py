# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral response parsing."""
from slidemage.ai.providers import parse_json_object


def test_parse_json_object_tolerates_fences_think_blocks_and_prose():
    assert parse_json_object('<think>x</think>Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object("[1]") is None and parse_json_object("") is None
