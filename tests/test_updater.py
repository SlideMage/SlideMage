# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
import urllib.error
from dataclasses import replace

import pytest

from conftest import make_zip
from signed_release import OTHER_PUBLIC_HEX, OTHER_SEED, PUBLIC_HEX, make_release, serve, sign, zip_bytes
from slidemage import release_signing, updater


def test_version_comparison():
    assert updater.parse_version("v0.3.29.5") == (0, 3, 29, 5)   # old scheme reads as 0.<old>
    assert updater.is_newer("v0.11.0", "v0.10.19.0")
    assert updater.is_breaking(_release("v0.12.0"), "v0.11.1") and not updater.is_breaking(_release("v0.11.2"), "v0.11.1")
    assert updater.parse_version("v3.29.5-beta") is None
    assert updater.is_newer("v0.3.29.10", "v0.3.29.9")
    assert not updater.is_newer("v0.3.29.5", "v0.3.29.5")
    assert not updater.is_newer("nightly", "v0.3.29.5")


def test_install_replaces_binary_and_extra_files(tmp_path):
    install_dir, exe, zip_path = _three_files(
        tmp_path, name="MySlideMage", extra={"../escape.txt": "flat"})

    updater.install_zip(zip_path, exe, "SlideMage")

    assert not (tmp_path / "escape.txt").exists()
    if os.name != "nt":
        assert os.access(exe, os.X_OK)
    assert _state(install_dir) == {
        "MySlideMage": b"new binary", "MySlideMage.old": b"old binary",
        "escape.txt": b"flat", "icon.svg": b"new icon", "slidemage.desktop.template": b"new template",
    }

    updater.remove_leftover_binary(exe)
    assert not (install_dir / "MySlideMage.old").exists()


def test_install_refuses_zip_without_binary(tmp_path):
    exe = tmp_path / "SlideMage"
    exe.write_bytes(b"old binary")
    zip_path = make_zip(tmp_path / "update.zip", {"readme.txt": "nothing useful"})
    with pytest.raises(updater.UpdateError):
        updater.install_zip(zip_path, exe, "SlideMage")
    assert exe.read_bytes() == b"old binary"


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


@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_token_does_not_block_the_apps_own_update(tmp_path, monkeypatch, caplog, code):
    # An expired private-theme token used to block public app updates.
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path)
    monkeypatch.delenv(updater.TOKEN_ENV_VAR, raising=False)
    updater.save_token("github_pat_expired")
    payload = [{"tag_name": "v0.3.30.0", "html_url": "https://example.invalid/r", "assets": []}]
    sent = []

    def urlopen(request, **_k):
        sent.append(request.get_header("Authorization"))
        if request.get_header("Authorization"):
            raise urllib.error.HTTPError(updater.RELEASES_URL, code, "Refused", {}, None)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    with caplog.at_level("WARNING", logger="slidemage.update"):
        assert [r.tag for r in updater.fetch_releases()] == ["v0.3.30.0"]
    assert sent == ["Bearer github_pat_expired", None]
    assert "refused the saved token" in caplog.text and "Settings → General" in caplog.text

    sent.clear()
    updater.fetch_releases()
    assert sent == [None]                                   # the rest of the run asks without it

    updater.save_token("github_pat_new")                    # a new token is tried again
    sent.clear()
    updater.fetch_releases()
    assert sent == ["Bearer github_pat_new", None]
    updater.save_token("")


@pytest.mark.parametrize("code, match", [(403, "GitHub answered 403 rate limit exceeded"),
                                         (404, "No published release found")])
def test_without_a_token_a_refusal_is_reported_and_not_retried(tmp_path, monkeypatch, code, match):
    monkeypatch.setattr(updater, "config_dir", lambda: tmp_path)
    monkeypatch.delenv(updater.TOKEN_ENV_VAR, raising=False)
    calls = []

    def forbidden(*_a, **_k):
        calls.append(1)
        raise urllib.error.HTTPError(updater.RELEASES_URL, code, "rate limit exceeded", {}, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", forbidden)
    with pytest.raises(updater.UpdateError, match=match):
        updater.plan_update(updater.fetch_releases(), "v0.3.29.0")
    assert len(calls) == 1


def _release(tag, body=""):
    return updater.Release(tag, f"https://example.invalid/{tag}", None, 0, body)


def test_breaking_notes_and_markers():
    marked = _release("v0.4.2.0", "Intro.\n\nBREAKING: projects need format 2.\nSecond line.\n\nOther.")
    assert updater.breaking_notes(marked) == ["BREAKING: projects need format 2.\nSecond line."]
    section = _release("v0.4.2.0", "## Breaking changes\n\n- one\n- two\n\n## Fixes\n\n- three")
    assert updater.breaking_notes(section) == ["- one\n- two"]
    assert updater.is_breaking(marked, "v0.4.1.0")
    assert updater.is_breaking(section, "v0.4.1.0")
    assert updater.is_breaking(_release("v0.5.0.0"), "v0.4.1.0")  # major bump without a marker
    assert not updater.is_breaking(_release("v0.4.2.0", "Mentions BREAKING: mid-line only"), "v0.4.1.0")


def test_fetch_releases_skips_unpublished_releases_and_picks_the_platform_asset(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    digest = "sha256:" + "A" * 64
    payload = [
        {"tag_name": "v0.4.2.0", "draft": True},
        {"tag_name": "v0.4.1.1", "prerelease": True},
        {"tag_name": "v0.4.1.0", "body": "BREAKING: x", "html_url": "u", "assets": [
            {"name": "SlideMage-windows.zip", "url": "win"},
            {"name": "SlideMage-linux.zip", "url": "lin", "size": 2, "digest": digest},
            {"name": "SlideMage-linux.zip.sig", "url": "sig"},
        ]},
    ]

    def urlopen(request, **_k):
        assert request.full_url == f"{updater.RELEASES_URL}?per_page=5"
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(updater.urllib.request, "urlopen", urlopen)
    [release] = updater.fetch_releases(limit=5)
    assert (release.tag, release.body, release.asset_url, release.asset_size) == ("v0.4.1.0", "BREAKING: x", "lin", 2)
    assert (release.asset_name, release.asset_digest, release.signature_url) == ("SlideMage-linux.zip", digest.lower(), "sig")


def test_a_release_without_this_installations_file_is_not_offered_yet():
    breaking = _release("v0.4.2.0", "BREAKING: x")
    built = replace(_release("v0.4.3.0"), asset_url="https://api.example.invalid/build")
    unbuilt = _release("v0.4.4.0")
    releases = [unbuilt, built, breaking]
    plan = updater.plan_update(releases, "v0.4.1.0", need_asset=True)
    assert plan.latest == built and plan.breaking == [breaking] and plan.safe is None
    assert updater.plan_update(releases, "v0.4.1.0").latest == unbuilt
    assert updater.plan_update([unbuilt], "v0.4.1.0", need_asset=True).latest is None
    plan = updater.plan_update(releases, "v0.4.2.0", need_asset=True)
    assert plan.latest == plan.safe == built and plan.breaking == []


def _progress(_done, _total):
    return True


def test_a_digest_mismatch_is_refused_and_the_file_deleted(tmp_path, monkeypatch):
    data = zip_bytes({"SlideMage.exe": b"new"})
    other = zip_bytes({"SlideMage.exe": b"NEW"})                        # same length, other content
    serve(monkeypatch, other, sign(data, "SlideMage-windows.zip"))
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateError, match="SHA-256") as error:
        updater.download(make_release(data), dest, _progress)
    assert "https://example.invalid/releases/v99.0.0" in str(error.value)
    assert not dest.exists()


def test_a_short_download_is_refused(tmp_path, monkeypatch):
    data = zip_bytes({"SlideMage.exe": b"new" * 100})
    serve(monkeypatch, data[:-10], sign(data, "SlideMage-windows.zip"), content_length=len(data))
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateError, match="ended early"):
        updater.download(make_release(data), dest, _progress)
    assert not dest.exists()


@pytest.mark.parametrize("overrides, reason", [
    ({"asset_digest": None}, "no checksum"),
    ({"asset_digest": "sha256:" + "z" * 64}, "no checksum"),
    ({"signature_url": None}, "no signature"),
])
def test_missing_or_invalid_release_metadata_is_refused_before_downloading(tmp_path, monkeypatch, overrides, reason):
    data = zip_bytes({"SlideMage.exe": b"new"})
    requested = serve(monkeypatch, data, None)
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateError, match=reason):
        updater.download(make_release(data, **overrides), dest, _progress)
    assert requested == [] and not dest.exists()


@pytest.mark.parametrize("problem", ["tampered-zip", "wrong-asset", "untrusted-key", "garbled-signature"])
def test_an_invalid_signature_is_refused_and_the_file_deleted(tmp_path, monkeypatch, problem):
    data = zip_bytes({"SlideMage.exe": b"new"})
    if problem == "garbled-signature":
        signature = "not base64 at all!!"
    elif problem == "untrusted-key":
        signature = sign(data, "SlideMage-windows.zip", OTHER_SEED)
    else:
        name = "SlideMage-windows-folder.zip" if problem == "wrong-asset" else "SlideMage-windows.zip"
        signature = sign(data, name)
    if problem == "tampered-zip":
        data = zip_bytes({"SlideMage.exe": b"evil"})
    serve(monkeypatch, data, signature)
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateError, match="signature is not valid"):
        updater.download(make_release(data), dest, _progress)
    assert not dest.exists()


def test_any_of_several_trusted_keys_will_do(tmp_path, monkeypatch):
    data = zip_bytes({"SlideMage.exe": b"new"})
    serve(monkeypatch, data, sign(data, "SlideMage-windows.zip", OTHER_SEED))
    monkeypatch.setattr(release_signing, "TRUSTED_PUBLIC_KEYS", (PUBLIC_HEX, OTHER_PUBLIC_HEX))
    updater.download(make_release(data), tmp_path / "update.zip", _progress)
    assert (tmp_path / "update.zip").read_bytes() == data


def test_the_placeholder_key_refuses_every_download(tmp_path, monkeypatch):
    data = zip_bytes({"SlideMage.exe": b"new"})
    requested = serve(monkeypatch, data, sign(data, "SlideMage-windows.zip"))
    monkeypatch.setattr(release_signing, "TRUSTED_PUBLIC_KEYS", (release_signing.PLACEHOLDER,))
    with pytest.raises(updater.UpdateError, match="no release signing key"):
        updater.download(make_release(data), tmp_path / "update.zip", _progress)
    assert requested == []


def test_the_shipped_key_list_holds_a_placeholder_or_real_keys_only():
    for key in release_signing.TRUSTED_PUBLIC_KEYS:
        assert key == release_signing.PLACEHOLDER or len(bytes.fromhex(key)) == 32


def test_cancel_removes_the_partial_file(tmp_path, monkeypatch):
    data = zip_bytes({"SlideMage.exe": b"new"})
    serve(monkeypatch, data, sign(data, "SlideMage-windows.zip"))
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateError, match="canceled"):
        updater.download(make_release(data), dest, lambda *_a: False)
    assert not dest.exists()


def _three_files(tmp_path, name="SlideMage", extra=None):
    install_dir = tmp_path / "app"
    install_dir.mkdir()
    exe = install_dir / name
    exe.write_bytes(b"old binary")
    (install_dir / "icon.svg").write_bytes(b"old icon")
    (install_dir / "slidemage.desktop.template").write_bytes(b"old template")
    zip_path = make_zip(tmp_path / "update.zip", {
        "SlideMage": b"new binary", "icon.svg": b"new icon", "slidemage.desktop.template": b"new template",
        **(extra or {}),
    })
    return install_dir, exe, zip_path


def _state(install_dir):
    return {p.name: p.read_bytes() for p in sorted(install_dir.iterdir())}


@pytest.mark.parametrize("failing_call, new_icon", [
    (1, False), (2, False), (3, False), (4, False), (5, False), (6, False),
    pytest.param(4, True, id="remove-new-icon-after-later-failure"),
])
def test_a_failed_swap_puts_every_file_back(tmp_path, monkeypatch, failing_call, new_icon):
    install_dir, exe, zip_path = _three_files(tmp_path)
    if new_icon:
        (install_dir / "icon.svg").unlink()
    before = _state(install_dir)
    real = updater.fileio.replace_with_retry
    calls = []

    def flaky(source, target, *args, **kwargs):
        calls.append(target.name)
        if len(calls) == failing_call:
            raise PermissionError("locked by a virus scanner")
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(updater.fileio, "replace_with_retry", flaky)
    with pytest.raises(updater.UpdateError, match="previous version is intact"):
        updater.install_zip(zip_path, exe, "SlideMage")
    assert _state(install_dir) == before                                 # old bytes back, no leftovers, no staging


def test_two_members_with_the_same_file_name_are_refused(tmp_path):
    install_dir, exe, _ = _three_files(tmp_path)
    before = _state(install_dir)
    zip_path = make_zip(tmp_path / "dup.zip", {"SlideMage": b"x", "a/icon.svg": b"1", "b/icon.svg": b"2"})
    with pytest.raises(updater.UpdateError, match="icon.svg"):
        updater.install_zip(zip_path, exe, "SlideMage")
    assert _state(install_dir) == before
