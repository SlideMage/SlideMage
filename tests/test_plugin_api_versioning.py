# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin API versioning policy (docs/PLUGIN_GUIDE.md, "Versioning"): API 1 is what 1.0 ships, additions are
marked "Since SlideMage 1.x." and required through requires_slidemage, and no docstring tells authors to probe."""
from __future__ import annotations

import re
from pathlib import Path

from slidemage import plugin_api

_SOURCE = Path(plugin_api.__file__).read_text(encoding="utf-8")


def test_no_docstring_tells_authors_to_probe_with_getattr():
    """The module's own lazy-loading __getattr__ is fine; advice to call getattr/hasattr on plugin_api or the host is not."""
    advice = re.compile(r"(getattr|hasattr)\s*\(\s*(plugin_api|host|self)\b|check\s+with\s+getattr|without\s+it\s+has", re.I)
    hits = [m.group(0) for m in advice.finditer(_SOURCE)]
    assert hits == [], f"plugin_api tells authors to probe: {hits}"


def test_no_docstring_names_the_release_that_added_a_feature_before_1_0():
    """Everything before 1.0 is simply API 1; only additions after 1.0 carry 'Since SlideMage 1.x.'."""
    stale = re.compile(r"(SlideMage\s+v\d+\.\d+|[Aa]dded\s+in\s+v?\d+\.\d+|came\s+with\s+SlideMage)")
    assert stale.findall(_SOURCE) == []


def test_policy_is_written_down_where_authors_look():
    doc = " ".join(plugin_api.__doc__.split())
    assert "Since SlideMage 1.x." in doc and "PLUGIN_GUIDE.md" in doc
    guide = (Path(plugin_api.__file__).parents[2] / "docs" / "PLUGIN_GUIDE.md").read_text(encoding="utf-8")
    assert "## Versioning" in guide and "Since SlideMage 1.x." in " ".join(guide.split())
    assert plugin_api.SUPPORTED_API_VERSIONS == {plugin_api.API_VERSION}
