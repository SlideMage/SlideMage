# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding what a user had before a feature became a plugin, so that the plugin keeps it.

The Claude plugin comes with the key the user entered in SlideMage's AI setup. It lived in three places
(ai/credentials.py reads them; this calls it and does not change it): the ANTHROPIC_API_KEY environment variable,
the system keychain entry ("SlideMage", "anthropic-api-key"), and the ``anthropic_api_key`` entry of SlideMage's
machine settings file (ai_settings.json in SlideMage's folder).
"""
from __future__ import annotations

from ..project import ProjectContext


def legacy_anthropic_key(ctx: ProjectContext) -> str | None:
    """The Anthropic API key from its old places, first hit wins in the old order; None if there is none. Reads
    only: the old copy stays where it is, so that downgrading loses nothing."""
    from ..ai import credentials

    found = credentials.get_api_key(ctx)
    return found.value if found is not None else None
