# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Beta versions (vX.Y.Z-beta.N): ordering, the "Offer beta versions" setting, the update check, plugin
requirements, the release tools, and the step to 1.0.0."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from slidemage import updater, version
from slidemage.plugins import manifest

_PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PACKAGING / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_release = _load("make_release")
release_notes = _load("release_notes")


# -- versions -------------------------------------------------------------------------------------------------------

def test_split_and_base():
    assert version.split_beta("v1.1.0-beta.2") == ("v1.1.0", 2)
    assert version.split_beta("v1.1.0") == ("v1.1.0", None)
    assert version.base_version("v1.1.0-beta.12") == "v1.1.0"
    assert version.is_beta("v1.1.0-beta.1") and not version.is_beta("v1.1.0") and not version.is_beta("v1.1.0-rc.1")


def test_betas_come_before_their_release_and_after_the_one_before():
    ordered = ["v0.10.19.0", "v0.18.5", "v1.0.0-beta.1", "v1.0.0-beta.2", "v1.0.0-beta.10", "v1.0.0", "v1.0.1",
               "v1.1.0-beta.1", "v1.1.0"]
    keys = [version.release_key(tag) for tag in ordered]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert version.release_key("not a version") is None and version.release_key("v1.0.0-rc.1") is None


def test_is_newer_with_betas():
    assert updater.is_newer("v1.1.0-beta.1", "v1.0.0")
    assert updater.is_newer("v1.1.0-beta.2", "v1.1.0-beta.1")
    assert updater.is_newer("v1.1.0", "v1.1.0-beta.2")             # the release after its betas
    assert not updater.is_newer("v1.1.0-beta.3", "v1.1.0")
    assert updater.parse_version("v1.1.0-beta.2") == (1, 1, 0)       # what the build can do: the release's


def test_history_reads_beta_entries():
    text = ("v1.1.0-beta.1 (2026-12-01, release of 2 changes): First beta.\n\nNEW:\n- A.\n\n"
            "v1.0.0 (2026-11-30, x): One.\n\nNEW:\n- B.\n")
    assert [e.version for e in version.parse_history(text)] == ["v1.1.0-beta.1", "v1.0.0"]


def test_plugin_requirements_admit_the_betas_of_a_version():
    assert manifest.matches(">=1.1", "v1.1.0-beta.2")
    assert not manifest.matches(">=1.2", "v1.1.0-beta.2")
    assert manifest.parse_app_version("v1.1.0-beta.2") == (1, 1, 0, 0)


# -- 1.0.0 ----------------------------------------------------------------------------------------------------------

def _release(tag: str, body: str = "") -> updater.Release:
    return updater.Release(tag=tag, page_url="", asset_url="u", asset_size=1, body=body)


def test_one_point_oh_is_not_a_break_by_its_number():
    assert not updater.is_breaking(_release("v1.0.0"), "v0.18.5")
    assert not updater.is_breaking(_release("v1.0.0-beta.1"), "v0.18.5")
    assert updater.is_breaking(_release("v1.2.0"), "v0.18.5")          # skipping past 1.0 stays a major step
    assert updater.is_breaking(_release("v2.0.0"), "v1.4.0")          # a real major step
    assert updater.is_breaking(_release("v1.0.0", "BREAKING: something."), "v0.18.5")
    assert release_notes.check("v1.0.0", "v0.18.5", ["Text."]) == []
    assert release_notes.check("v1.2.0", "v0.18.5", ["Text."])


# -- the setting and the update check ----------------------------------------------------------------------------

def test_the_setting_is_off_until_switched_on(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")
    assert updater.get_beta_updates() is False
    updater.set_beta_updates(True)
    assert updater.get_beta_updates() is True
    updater.set_beta_updates(False)
    assert updater.get_beta_updates() is False


def test_which_releases_are_offered():
    assert updater.offered("v1.0.0", False, betas=False)
    assert not updater.offered("v1.1.0-beta.1", True, betas=False)
    assert updater.offered("v1.1.0-beta.1", True, betas=True)
    assert not updater.offered("v1.1.0-beta.1", False, betas=False)     # a beta tag even if not marked pre-release
    assert not updater.offered("v1.1.0-rc.1", True, betas=True)         # a pre-release that is not a beta: never


def _github(*items):
    return [{"tag_name": tag, "prerelease": pre, "draft": draft, "html_url": "", "assets": [], "body": ""}
            for tag, pre, draft in items]


def test_fetch_releases_follows_the_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(updater, "_get_json", lambda url, timeout: _github(
        ("v1.1.0-beta.1", True, False), ("v1.0.1", False, False), ("v1.2.0", False, True)))
    assert [r.tag for r in updater.fetch_releases()] == ["v1.0.1"]
    updater.set_beta_updates(True)
    assert [r.tag for r in updater.fetch_releases()] == ["v1.1.0-beta.1", "v1.0.1"]
    assert [r.tag for r in updater.fetch_releases(betas=False)] == ["v1.0.1"]


def test_a_beta_user_is_offered_the_release_after_the_beta():
    releases = [_release("v1.1.0"), _release("v1.1.0-beta.2"), _release("v1.0.1")]
    assert updater.plan_update(releases, "v1.1.0-beta.2").latest.tag == "v1.1.0"
    assert updater.plan_update(releases, "v1.0.1").latest.tag == "v1.1.0"
    assert updater.plan_update([_release("v1.1.0-beta.1"), _release("v1.0.1")], "v1.0.1").latest.tag == "v1.1.0-beta.1"


# -- release tools --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("previous, kinds, beta, explicit, expected", [
    ("v1.0.0", ["new"], True, "", "v1.1.0-beta.1"),
    ("v1.1.0-beta.1", ["fixed"], True, "", "v1.1.0-beta.2"),
    ("v1.1.0-beta.2", ["fixed"], False, "", "v1.1.0"),
    ("v1.1.0-beta.2", [], False, "", "v1.1.0"),
    ("v1.0.0", ["fixed"], False, "", "v1.0.1"),
    ("v0.18.5", ["new"], False, "v1.0.0", "v1.0.0"),
    ("v0.18.5", ["new"], True, "1.0.0", "v1.0.0-beta.1"),
    ("v1.0.0-beta.1", ["new"], False, "v1.0.0", "v1.0.0"),
])
def test_choose_number(previous, kinds, beta, explicit, expected):
    assert make_release.choose_number(previous, kinds, beta=beta, explicit=explicit) == expected


@pytest.mark.parametrize("previous, explicit", [("v1.0.0", "v0.19.0"), ("v1.0.0", "v1.0.0"), ("v0.18.5", "v1.0")])
def test_choose_number_refuses_a_version_that_does_not_come_after(previous, explicit):
    with pytest.raises(make_release.ReleaseError):
        make_release.choose_number(previous, ["new"], explicit=explicit)


def _tree(tmp_path: Path, current: str, changelog: str, fragments: dict[str, str]) -> Path:
    package = tmp_path / "src" / "slidemage"
    package.mkdir(parents=True)
    (package / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (package / "version.py").write_text(f'VERSION_NUMBER = "{current}"\n', encoding="utf-8")
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "README.md").write_text("# Fragments\n", encoding="utf-8")
    for name, text in fragments.items():
        (tmp_path / "changes" / name).write_text(text, encoding="utf-8")
    return tmp_path


FIX = "kind: fixed\nreason: issue #1\n\nA fix.\n\nNEW:\n- Fixed a thing.\n"
BETAS = ("# History\n\n"
         "v1.1.0-beta.2 (2026-12-02, issue #2): Second.\n\nNEW:\n- Second beta bullet.\n\n"
         "v1.1.0-beta.1 (2026-12-01, issue #1): First.\n\nNEW:\n- First beta bullet.\n\n"
         "v1.0.0 (2026-11-30, x): One.\n\nNEW:\n- Old bullet.\n")


def test_a_beta_from_fragments(tmp_path):
    root = _tree(tmp_path, "v1.0.0", "# History\n\nv1.0.0 (2026-11-30, x): One.\n\nNEW:\n- B.\n", {"fix.md": FIX})
    previous, number, entry, fragments = make_release.prepare(root, "", "2026-12-01", when=lambda f: 0, beta=True)
    assert (previous, number) == ("v1.0.0", "v1.0.1-beta.1")
    assert entry.startswith("v1.0.1-beta.1 (2026-12-01, issue #1): A fix.")


def test_the_release_after_betas_without_fragments_gathers_their_bullets(tmp_path):
    root = _tree(tmp_path, "v1.1.0-beta.2", BETAS, {})
    previous, number, entry, fragments = make_release.prepare(root, "", "2026-12-05", when=lambda f: 0)
    assert (previous, number, fragments) == ("v1.1.0-beta.2", "v1.1.0", [])
    parsed = make_release.history_entry(entry)
    assert parsed.version == "v1.1.0" and "v1.1.0-beta.1, v1.1.0-beta.2" in parsed.meta
    assert parsed.news == ["First beta bullet.", "Second beta bullet."]


def test_no_fragments_and_no_betas_is_still_nothing_to_release(tmp_path):
    root = _tree(tmp_path, "v1.0.0", "# History\n\nv1.0.0 (2026-11-30, x): One.\n\nNEW:\n- B.\n", {})
    with pytest.raises(make_release.ReleaseError, match="nothing to release"):
        make_release.prepare(root, "", "2026-12-01", when=lambda f: 0)
    with pytest.raises(make_release.ReleaseError, match="nothing to release"):
        make_release.prepare(_tree(tmp_path / "b", "v1.1.0-beta.1", BETAS, {}), "", "2026-12-01", beta=True)


def test_the_notes_of_a_release_cover_its_betas(monkeypatch):
    history = "# History\n\nv1.1.0 (2026-12-05, release of the betas): R.\n\nNEW: R.\n- R.\n\n" + BETAS[len("# History\n\n"):]
    entries = version.parse_history(history)
    monkeypatch.setattr(version, "parse_history", lambda text=None: entries)
    covered = [e.version for e in release_notes.history_since("v1.1.0", "v1.0.0")]
    assert covered == ["v1.1.0", "v1.1.0-beta.2", "v1.1.0-beta.1"]
    assert [e.version for e in release_notes.history_since("v1.1.0-beta.2", "v1.1.0-beta.1")] == ["v1.1.0-beta.2"]
