# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host.credentials(): a plugin's secrets by namespace (environment, keychain or a 0600 file), and the lookup of the
Anthropic key in its old places for the Claude plugin."""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from slidemage import project
from slidemage.ai import credentials as legacy
from slidemage.plugins import credentials as creds, migrate
from slidemage.plugins.credentials import PluginCredentials
from slidemage.plugins.migrate import legacy_anthropic_key
from slidemage.project import ProjectContext


class FakeKeyring:
    def __init__(self, broken_delete=False):
        self.store, self.broken_delete = {}, broken_delete

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        if self.broken_delete:
            raise RuntimeError("locked")
        self.store.pop((service, user), None)


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(creds, "_keyring", lambda: None)
    monkeypatch.delenv("FIX_KEY", raising=False)
    return tmp_path / "config"


def test_a_file_is_used_without_a_keychain(config):
    c = PluginCredentials("claude")
    assert c.get() is None and c.where() == ""
    assert c.set("sk-1") == "file"
    assert (c.get(), c.where()) == ("sk-1", "file")
    path = config / "plugins" / "secrets" / "claude.json"
    assert json.loads(path.read_text()) == {"key": "sk-1"}
    c.clear()
    assert c.get() is None and not path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="no permission bits")
def test_the_file_is_owner_only(config):
    c = PluginCredentials("claude")
    c.set("sk-1")
    c.set("sk-2", name="other")
    path = config / "plugins" / "secrets" / "claude.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not list(path.parent.glob("*.tmp"))


def test_plugins_do_not_share_secrets(config):
    PluginCredentials("claude").set("a")
    PluginCredentials("ollama").set("b")
    assert PluginCredentials("claude").get() == "a" and PluginCredentials("ollama").get() == "b"
    assert PluginCredentials("third").get() is None


def test_names_are_separate_secrets():
    c = PluginCredentials("claude")
    c.set("one")
    c.set("two", name="admin")
    assert (c.get(), c.get("admin")) == ("one", "two")
    c.clear("admin")
    assert (c.get(), c.get("admin")) == ("one", None)


def test_the_environment_wins_for_the_default_name_only(monkeypatch):
    monkeypatch.setenv("FIX_KEY", " from-env ")
    c = PluginCredentials("claude", env_var="FIX_KEY")
    c.set("stored")
    c.set("stored2", name="admin")
    assert (c.get(), c.where()) == ("from-env", "environment")
    assert (c.get("admin"), c.where("admin")) == ("stored2", "file")
    c.clear()
    assert c.get() == "from-env"            # the environment is not the plugin's to change
    monkeypatch.delenv("FIX_KEY")
    assert c.get() is None


def test_the_keychain_is_preferred_and_the_file_holds_no_copy(monkeypatch, config):
    fake = FakeKeyring()
    monkeypatch.setattr(creds, "_keyring", lambda: fake)
    c = PluginCredentials("claude")
    c.set("old")
    assert c.set("sk-1") == "keychain"
    assert fake.store == {("SlideMage:claude", "key"): "sk-1"}
    assert (c.get(), c.where()) == ("sk-1", "keychain")
    assert not (config / "plugins" / "secrets" / "claude.json").exists()
    c.clear()
    assert fake.store == {} and c.get() is None


def test_a_keychain_that_refuses_falls_back_to_the_file(monkeypatch):
    class Refusing(FakeKeyring):
        def set_password(self, service, user, value):
            raise RuntimeError("no backend")

    monkeypatch.setattr(creds, "_keyring", lambda: Refusing())
    c = PluginCredentials("claude")
    assert c.set("sk-1") == "file" and c.where() == "file"


def test_an_old_keychain_entry_that_cannot_be_removed_is_reported(monkeypatch):
    fake = FakeKeyring(broken_delete=True)
    fake.store[("SlideMage:claude", "key")] = "old"
    monkeypatch.setattr(creds, "_keyring", lambda: fake)
    with pytest.raises(OSError, match="keychain still holds"):
        PluginCredentials("claude").set("")


# -- the old Anthropic key -----------------------------------------------------------------------------------------

@pytest.fixture
def pctx(tmp_path):
    return ProjectContext.at(tmp_path)


def test_no_old_key(pctx, monkeypatch):
    monkeypatch.delenv(legacy.ENV_VAR, raising=False)
    monkeypatch.setattr(migrate, "_keyring", lambda: None)
    monkeypatch.setattr(legacy.app_settings, "get", lambda ctx, key: None)
    assert legacy_anthropic_key(pctx) is None


def test_old_key_places_in_order(pctx, monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(migrate, "_keyring", lambda: fake)
    monkeypatch.setattr(legacy.app_settings, "get", lambda ctx, key: "from-file" if key == legacy.FILE_SETTING_KEY else None)
    monkeypatch.delenv(legacy.ENV_VAR, raising=False)
    assert legacy_anthropic_key(pctx) == "from-file"
    fake.store[(legacy.KEYRING_SERVICE, legacy.KEYRING_USER)] = "from-keychain"
    assert legacy_anthropic_key(pctx) == "from-keychain"
    monkeypatch.setenv(legacy.ENV_VAR, "from-env")
    assert legacy_anthropic_key(pctx) == "from-env"


def test_old_key_is_left_where_it_is(pctx, monkeypatch):
    fake = FakeKeyring()
    fake.store[(legacy.KEYRING_SERVICE, legacy.KEYRING_USER)] = "k"
    monkeypatch.setattr(migrate, "_keyring", lambda: fake)
    monkeypatch.delenv(legacy.ENV_VAR, raising=False)
    legacy_anthropic_key(pctx)
    assert fake.store == {(legacy.KEYRING_SERVICE, legacy.KEYRING_USER): "k"}
