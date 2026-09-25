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
