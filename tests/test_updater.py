# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
import urllib.error
import zipfile

import pytest

from slidemage import updater


def test_version_comparison():
    assert updater.parse_version("v3.29.5") == (3, 29, 5)
    assert updater.parse_version("v3.29.5-beta") is None
    assert updater.is_newer("v3.30.0", "v3.29.5")
    assert updater.is_newer("v3.29.10", "v3.29.9")
    assert not updater.is_newer("v3.29.5", "v3.29.5")
    assert not updater.is_newer("v0.0.11", "v3.29.5")
    assert not updater.is_newer("nightly", "v3.29.5")


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_install_replaces_binary_and_extra_files(tmp_path):
    install_dir = tmp_path / "app"
    install_dir.mkdir()
    exe = install_dir / "MySlideMage"  # renamed by the user
    exe.write_bytes(b"old binary")
    (install_dir / "icon.svg").write_text("old icon")
    zip_path = _zip(tmp_path / "update.zip", {
        "SlideMage": b"new binary", "icon.svg": "new icon", "../escape.txt": "flat",
    })

    updater.install_zip(zip_path, exe, "SlideMage")

    assert exe.read_bytes() == b"new binary"
    assert (install_dir / "icon.svg").read_text() == "new icon"
    assert (install_dir / "escape.txt").read_text() == "flat"
    assert not (tmp_path / "escape.txt").exists()
    assert (install_dir / "MySlideMage.old").read_bytes() == b"old binary"
    assert not (install_dir / "SlideMage").exists()
    if os.name != "nt":
        assert os.access(exe, os.X_OK)
    assert sorted(p.name for p in install_dir.iterdir()) == [
        "MySlideMage", "MySlideMage.old", "escape.txt", "icon.svg",
    ]

    updater.remove_leftover_binary(exe)
    assert not (install_dir / "MySlideMage.old").exists()


def test_install_refuses_zip_without_binary(tmp_path):
    exe = tmp_path / "SlideMage"
    exe.write_bytes(b"old binary")
    zip_path = _zip(tmp_path / "update.zip", {"readme.txt": "nothing useful"})
    with pytest.raises(updater.UpdateError):
        updater.install_zip(zip_path, exe, "SlideMage")
    assert exe.read_bytes() == b"old binary"


def test_fetch_picks_platform_asset_and_explains_404(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    payload = {
        "tag_name": "v3.30.0", "html_url": "https://example.invalid/r",
        "assets": [
            {"name": "SlideMage-windows.zip", "url": "win", "size": 1},
            {"name": "SlideMage-linux.zip", "url": "lin", "size": 2},
        ],
    }
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda *_a, **_k: io.BytesIO(json.dumps(payload).encode()),
    )
    release = updater.fetch_latest_release()
    assert (release.tag, release.asset_url, release.asset_size) == ("v3.30.0", "lin", 2)

    def not_found(*_a, **_k):
        raise urllib.error.HTTPError(updater.LATEST_RELEASE_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", not_found)
    with pytest.raises(updater.UpdateError, match=updater.TOKEN_ENV_VAR):
        updater.fetch_latest_release()


def test_token_saved_privately_and_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.delenv(updater.TOKEN_ENV_VAR, raising=False)
    assert updater.active_token() == ""

    updater.save_token("  ghp_saved \n")
    token_file = tmp_path / "cfg" / updater.TOKEN_FILENAME
    assert updater.saved_token() == updater.active_token() == "ghp_saved"
    if os.name != "nt":
        assert token_file.stat().st_mode & 0o777 == 0o600
    assert updater._request("https://example.invalid", "a").get_header("Authorization") == "Bearer ghp_saved"

    monkeypatch.setenv(updater.TOKEN_ENV_VAR, "ghp_env")
    assert updater.active_token() == "ghp_env"

    updater.save_token("")
    assert not token_file.exists()


def test_refused_token_names_the_missing_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path)
    monkeypatch.setenv(updater.TOKEN_ENV_VAR, "github_pat_x")

    def forbidden(*_a, **_k):
        raise urllib.error.HTTPError(updater.LATEST_RELEASE_URL, 403, "Forbidden", {}, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", forbidden)
    with pytest.raises(updater.UpdateError, match="Contents: Read-only"):
        updater.fetch_latest_release()


def _release(tag, body=""):
    return updater.Release(tag, f"https://example.invalid/{tag}", None, 0, body)


def test_breaking_notes_and_markers():
    marked = _release("v4.2.0", "Intro.\n\nBREAKING: projects need format 2.\nSecond line.\n\nOther.")
    assert updater.breaking_notes(marked) == ["BREAKING: projects need format 2.\nSecond line."]
    section = _release("v4.2.0", "## Breaking changes\n\n- one\n- two\n\n## Fixes\n\n- three")
    assert updater.breaking_notes(section) == ["- one\n- two"]
    assert updater.is_breaking(marked, "v4.1.0")
    assert updater.is_breaking(section, "v4.1.0")
    assert updater.is_breaking(_release("v5.0.0"), "v4.1.0")  # major bump without a marker
    assert not updater.is_breaking(_release("v4.2.0", "Mentions BREAKING: mid-line only"), "v4.1.0")


def test_plan_update_counts_every_release_in_between():
    releases = [
        _release("v5.0.0", "BREAKING: new layout."),
        _release("v4.3.0"),
        _release("v4.2.0"),
        _release("v4.0.0"),
    ]
    plan = updater.plan_update(releases, "v4.1.0")
    assert plan.latest.tag == "v5.0.0"
    assert [r.tag for r in plan.breaking] == ["v5.0.0"]
    assert plan.safe.tag == "v4.3.0"
    assert updater.newest_non_breaking(releases, "v4.1.0").tag == "v4.3.0"

    # A later unmarked release doesn't hide an earlier breaking one.
    releases = [_release("v4.3.0"), _release("v4.2.0", "BREAKING: x")]
    plan = updater.plan_update(releases, "v4.1.0")
    assert plan.latest.tag == "v4.3.0" and [r.tag for r in plan.breaking] == ["v4.2.0"]
    assert plan.safe is None

    plan = updater.plan_update([_release("v4.1.0")], "v4.1.0")
    assert plan.latest is None and plan.breaking == [] and plan.safe is None


def test_fetch_releases_skips_drafts_and_prereleases(monkeypatch):
    payload = [
        {"tag_name": "v4.2.0", "draft": True},
        {"tag_name": "v4.1.1", "prerelease": True},
        {"tag_name": "v4.1.0", "body": "BREAKING: x", "html_url": "u"},
    ]
    requested = []

    def fake_urlopen(request, **_k):
        requested.append(request.full_url)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    [release] = updater.fetch_releases(limit=5)
    assert (release.tag, release.body) == ("v4.1.0", "BREAKING: x")
    assert requested == [f"{updater.RELEASES_URL}?per_page=5"]
