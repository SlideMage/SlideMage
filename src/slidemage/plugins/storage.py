# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep host metadata outside the plugin-ID namespace, migrating legacy files on first access."""
from __future__ import annotations

import os
from pathlib import Path


def private_file(base: Path, name: str) -> Path:
    path = base / ("." + name)
    legacy = base / name
    if not path.exists() and legacy.is_file():
        try:
            os.replace(legacy, path)
        except OSError:
            return legacy   # keep existing preferences readable if migration is temporarily impossible
    return path
