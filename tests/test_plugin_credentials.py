# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host.credentials(): a plugin's secrets by namespace (environment, keychain or a 0600 file), and the lookup of the
Anthropic key in its old places for the Claude plugin."""
from __future__ import annotations

import json
import os
import stat

import pytest

from slidemage import project
from slidemage.plugins import credentials as creds
from slidemage.plugins.credentials import PluginCredentials


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(creds, "_keyring", lambda: None)
    monkeypatch.delenv("FIX_KEY", raising=False)
    return tmp_path / "config"


def test_file_credentials_round_trip_and_keep_names_separate(config):
    c = PluginCredentials("claude")
    assert c.get() is None and c.where() == ""
    assert c.set("sk-1") == "file"
    assert (c.get(), c.where()) == ("sk-1", "file")
    path = config / "plugins" / "secrets" / "claude.json"
    c.set("sk-2", name="admin")
    assert json.loads(path.read_text()) == {"key": "sk-1", "admin": "sk-2"}
    assert (c.get(), c.get("admin")) == ("sk-1", "sk-2")
    c.clear("admin")
    assert (c.get(), c.get("admin")) == ("sk-1", None)
    c.clear()
    assert c.get() is None and not path.exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX permission bits")
def test_the_secret_is_owner_only_before_replacement(monkeypatch):
    c = PluginCredentials("claude")
    real_replace = os.replace
    modes = []

    def replace(source, target):
        modes.append(stat.S_IMODE(os.stat(source).st_mode))
        assert modes[-1] == 0o600
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    c.set("sk-1")
    c.path.chmod(0o644)      # A replacement must be private even if an older file was not.
    c.set("sk-2")
    assert modes == [0o600, 0o600]
    assert stat.S_IMODE(c.path.stat().st_mode) == 0o600
    assert c.get() == "sk-2" and not list(c.path.parent.glob("*.tmp"))


def test_plugins_do_not_share_secrets():
    PluginCredentials("claude").set("a")
    PluginCredentials("ollama").set("b")
    assert PluginCredentials("claude").get() == "a" and PluginCredentials("ollama").get() == "b"
    assert PluginCredentials("third").get() is None


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
