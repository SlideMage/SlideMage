# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Anthropic API key and where it comes from (2026-10-09, UI redesign
step 2).

Lookup order, first hit wins, and the source is reported so Settings can
tell the user where the key they are using actually lives:

1. the ``ANTHROPIC_API_KEY`` environment variable (CI, scripts, and the
   only place a key can live without ever touching the project folder);
2. the system keychain, through the optional ``keyring`` package (import
   guarded: SlideMage works without it);
3. the ``anthropic_api_key`` entry of the settings -- the fallback when
   ``keyring`` is missing or has no usable backend. It is one of
   app_settings.MACHINE_KEYS, so it is kept in SlideMage's own folder on this
   computer (ai_settings.json), never in the project (v8.58.0; before, the
   project's possibly cloud-synced app_settings.json).

This module is a leaf (it only needs app_settings) so providers.py can
read the key without importing the resolver that imports providers.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .. import app_settings
from ..project import ProjectContext

ENV_VAR = "ANTHROPIC_API_KEY"
KEYRING_SERVICE = "SlideMage"
KEYRING_USER = "anthropic-api-key"
FILE_SETTING_KEY = "anthropic_api_key"

SOURCE_ENV = "environment"
SOURCE_KEYCHAIN = "keychain"
SOURCE_FILE = "settings file"


@dataclass(frozen=True)
class ApiKey:
    value: str
    source: str  # SOURCE_ENV / SOURCE_KEYCHAIN / SOURCE_FILE


def _keyring():
    """The ``keyring`` module, or None when it is not installed."""
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def keychain_available() -> bool:
    """True when ``keyring`` is installed and has a real backend (its
    ``fail`` backend, which refuses everything, has priority 0); a key saved
    now goes to the keychain, otherwise to the settings file."""
    module = _keyring()
    if module is None:
        return False
    try:
        return module.get_keyring().priority > 0
    except Exception:  # noqa: BLE001 -- keyring backends raise assorted errors
        return False


def _keychain_get() -> str:
    module = _keyring()
    if module is None:
        return ""
    try:
        return module.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:  # noqa: BLE001 -- keyring backends raise assorted errors; none may break startup
        return ""


def get_api_key(ctx: ProjectContext) -> ApiKey | None:
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return ApiKey(value, SOURCE_ENV)
    value = _keychain_get().strip()
    if value:
        return ApiKey(value, SOURCE_KEYCHAIN)
    value = str(app_settings.get(ctx, FILE_SETTING_KEY) or "").strip()
    if value:
        return ApiKey(value, SOURCE_FILE)
    return None


def set_api_key(ctx: ProjectContext, key: str) -> str:
    """Store `key` (empty clears it from the keychain and the settings
    file; the environment variable is not ours to change). Returns where it
    was stored: SOURCE_KEYCHAIN or SOURCE_FILE, "" when cleared. The key is
    kept in exactly one place, so clearing never leaves a stale copy: an
    older keychain entry is removed when the new key goes to the file, and
    an OSError says so if the keychain refuses to let go of one (the file is
    updated regardless)."""
    key = key.strip()
    module = _keyring()
    in_keychain = False
    if module is not None and key:
        try:
            module.set_password(KEYRING_SERVICE, KEYRING_USER, key)
            in_keychain = True
        except Exception:  # noqa: BLE001 -- no usable backend: fall through to the settings file
            pass
    stuck: Exception | None = None
    if module is not None and not in_keychain and _keychain_get():   # it would shadow the file's key
        try:
            module.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as exc:  # noqa: BLE001 -- keyring backends raise assorted errors
            stuck = exc
    settings = app_settings.load(ctx)
    if key and not in_keychain:
        settings[FILE_SETTING_KEY] = key
    else:
        settings.pop(FILE_SETTING_KEY, None)
    app_settings.save(ctx, settings)
    if stuck is not None:
        raise OSError(f"the system keychain still holds an API key that could not be removed ({stuck}); "
                      "it takes precedence over the settings file")
    if not key:
        return ""
    return SOURCE_KEYCHAIN if in_keychain else SOURCE_FILE
