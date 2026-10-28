# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A plugin's secrets (plugin_api.Credentials): the environment, the system keychain, or a file.

Lookup order, first hit wins, and where it came from is reported so a Settings page can say so:

1. the environment variable the plugin named (only for the default secret name, and read-only: it is not the
   plugin's to change);
2. the system keychain through the optional ``keyring`` package, under the service "SlideMage:<plugin id>" (import
   guarded: SlideMage works without it);
3. a file ``config_dir()/plugins/secrets/<plugin id>.json`` with owner-only permissions (0600; Windows has no such
   bit, but the folder is the user's own), in SlideMage's folder on this computer, never in a project, so a
   cloud-synced project folder never carries a key.

A secret is kept in one place only, so clearing never leaves a stale copy, as ai/credentials.py does for the
Anthropic key. No Qt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import project

DEFAULT_NAME = "key"
SOURCE_ENV = "environment"
SOURCE_KEYCHAIN = "keychain"
SOURCE_FILE = "file"
SERVICE_PREFIX = "SlideMage:"


def _keyring():
    """The ``keyring`` module, or None when it is not installed."""
    try:
        import keyring
    except ImportError:
        return None
    return keyring


class PluginCredentials:
    def __init__(self, plugin_id: str, env_var: str | None = None) -> None:
        self.plugin_id = plugin_id
        self.env_var = env_var

    @property
    def path(self) -> Path:
        return project.config_dir() / "plugins" / "secrets" / f"{self.plugin_id}.json"

    @property
    def _service(self) -> str:
        return SERVICE_PREFIX + self.plugin_id

    # -- the file

    def _read_file(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} \
            if isinstance(data, dict) else {}

    def _write_file(self, data: dict[str, str]) -> None:
        path = self.path
        if not data:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            # Created with 0600 from the start: the secret is never readable by others, not even for a moment.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(json.dumps(data, indent=2) + "\n")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    # -- the keychain

    def _keychain_get(self, name: str) -> str:
        module = _keyring()
        if module is None:
            return ""
        try:
            return module.get_password(self._service, name) or ""
        except Exception:  # noqa: BLE001 -- keyring backends raise assorted errors; none may break a plugin
            return ""

    # -- Credentials

    def _lookup(self, name: str) -> tuple[str, str]:
        if self.env_var and name == DEFAULT_NAME:
            value = os.environ.get(self.env_var, "").strip()
            if value:
                return value, SOURCE_ENV
        value = self._keychain_get(name).strip()
        if value:
            return value, SOURCE_KEYCHAIN
        value = self._read_file().get(name, "").strip()
        if value:
            return value, SOURCE_FILE
        return "", ""

    def get(self, name: str = DEFAULT_NAME) -> str | None:
        return self._lookup(name)[0] or None

    def where(self, name: str = DEFAULT_NAME) -> str:
        return self._lookup(name)[1]

    def set(self, value: str, name: str = DEFAULT_NAME) -> str:
        value = value.strip()
        module = _keyring()
        in_keychain = False
        if module is not None and value:
            try:
                module.set_password(self._service, name, value)
                in_keychain = True
            except Exception:  # noqa: BLE001 -- no usable backend: fall through to the file
                pass
        stuck: Exception | None = None
        if module is not None and not in_keychain and self._keychain_get(name):    # it would shadow the file
            try:
                module.delete_password(self._service, name)
            except Exception as exc:  # noqa: BLE001
                stuck = exc
        data = self._read_file()
        if value and not in_keychain:
            data[name] = value
        else:
            data.pop(name, None)
        self._write_file(data)
        if stuck is not None:
            raise OSError(f"the system keychain still holds a secret that could not be removed ({stuck}); "
                          "it takes precedence over the file")
        if not value:
            return ""
        return SOURCE_KEYCHAIN if in_keychain else SOURCE_FILE

    def clear(self, name: str = DEFAULT_NAME) -> None:
        self.set("", name)
