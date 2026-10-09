"""The Anthropic API key and where it comes from (2026-10-09, UI redesign
step 2).

Lookup order, first hit wins, and the source is reported so Settings can
tell the user where the key they are using actually lives:

1. the ``ANTHROPIC_API_KEY`` environment variable (CI, scripts, and the
   only place a key can live without ever touching the project folder);
2. the system keychain, through the optional ``keyring`` package (import
   guarded: SlideMage works without it);
3. the ``anthropic_api_key`` entry of app_settings.json -- the fallback
   when ``keyring`` is missing or has no usable backend. That file is
   gitignored but sits inside the (possibly cloud-synced) project folder,
   so Settings says so when the key ends up there.

This module is a leaf (it only needs app_settings) so providers.py can
read the key without importing the resolver that imports providers.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .. import app_settings

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


def _keychain_get() -> str:
    module = _keyring()
    if module is None:
        return ""
    try:
        return module.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:  # noqa: BLE001 -- keyring backends raise assorted errors; none may break startup
        return ""


def get_api_key() -> ApiKey | None:
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return ApiKey(value, SOURCE_ENV)
    value = _keychain_get().strip()
    if value:
        return ApiKey(value, SOURCE_KEYCHAIN)
    value = str(app_settings.get(FILE_SETTING_KEY) or "").strip()
    if value:
        return ApiKey(value, SOURCE_FILE)
    return None


def set_api_key(key: str) -> str:
    """Store `key` (empty clears it from the keychain and the settings
    file; the environment variable is not ours to change). Returns where it
    was stored: SOURCE_KEYCHAIN or SOURCE_FILE, "" when cleared. The key is
    kept in exactly one place, so clearing never leaves a stale copy."""
    key = key.strip()
    module = _keyring()
    in_keychain = False
    if module is not None:
        try:
            if key:
                module.set_password(KEYRING_SERVICE, KEYRING_USER, key)
            elif _keychain_get():
                module.delete_password(KEYRING_SERVICE, KEYRING_USER)
            in_keychain = bool(key)
        except Exception:  # noqa: BLE001 -- no usable backend: fall through to the settings file
            in_keychain = False
    settings = app_settings.load()
    if key and not in_keychain:
        settings[FILE_SETTING_KEY] = key
    else:
        settings.pop(FILE_SETTING_KEY, None)
    app_settings.save(settings)
    if not key:
        return ""
    return SOURCE_KEYCHAIN if in_keychain else SOURCE_FILE
