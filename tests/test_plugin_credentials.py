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
from slidemage.plugins import credentials as creds
from slidemage.plugins.credentials import PluginCredentials
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


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX permission bits")
def test_the_secret_is_owner_only_before_replacement(config, monkeypatch):
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
    assert c.get() == "sk-2"


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


# -- the old Anthropic key -----------------------------------------------------------------------------------------

@pytest.fixture
def pctx(tmp_path):
    return ProjectContext.at(tmp_path)
