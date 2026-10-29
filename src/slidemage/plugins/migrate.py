# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read legacy settings without changing the originals, so plugins can adopt them."""
from __future__ import annotations

import os

from .. import app_settings
from ..project import ProjectContext
from .credentials import _keyring


def legacy_anthropic_key(ctx: ProjectContext) -> str | None:
    """Read the old environment, keychain and settings file in their original order."""
    value = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if value:
        return value
    module = _keyring()
    if module is not None:
        try:
            value = (module.get_password("SlideMage", "anthropic-api-key") or "").strip()
        except Exception:  # noqa: BLE001 -- a keychain failure must not stop startup
            value = ""
        if value:
            return value
    return str(app_settings.peek(ctx, "anthropic_api_key") or "").strip() or None
