# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing, removing and cleaning up plugins from zip archives."""
from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from slidemage.plugins import installer, loader

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
HELLO_TOML = (FIXTURES / "hello" / "plugin.toml").read_text(encoding="utf-8")
HELLO_INIT = (FIXTURES / "hello" / "hello" / "__init__.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.project, "config_dir", lambda: tmp_path / "config")
    installer._changed.clear()
    yield
    installer._changed.clear()


def make_zip(tmp_path, *, toml=HELLO_TOML, files=None, extra=(), name="p.zip"):
    files = {"hello/__init__.py": HELLO_INIT} if files is None else files
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        if toml is not None:
            zf.writestr("plugin.toml", toml)
        for n, data in files.items():
            zf.writestr(n, data)
        for info, data in extra:
            zf.writestr(info, data)
    return path


def assert_no_staging():
    staging = loader.plugins_dir() / ".staging"
    assert not staging.exists() or not any(staging.iterdir())


def fails(archive, match, **kw):
    with pytest.raises(installer.InstallError, match=match):
        installer.install(archive, **kw)
    assert_no_staging()
    assert not (loader.plugins_dir() / "hello").exists()


def test_install_success(tmp_path):
    m = installer.install(make_zip(tmp_path))
    assert m.id == "hello"
    assert (loader.plugins_dir() / "hello" / "plugin.toml").is_file()
    assert (loader.plugins_dir() / "hello" / "hello" / "__init__.py").is_file()
    assert_no_staging()
    assert installer.changed_ids() == {"hello"} and installer.pending_restart()


def test_correct_hash_accepted(tmp_path):
    z = make_zip(tmp_path)
    installer.install(z, expected_sha256=installer.sha256_of(z).upper())


def test_wrong_hash(tmp_path):
    fails(make_zip(tmp_path), "checksum", expected_sha256="0" * 64)


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_text("nope")
    fails(p, "zip")


def test_zip_slip(tmp_path):
    fails(make_zip(tmp_path, extra=[("../x", "bad")]), "unsafe")


def test_absolute_path(tmp_path):
    fails(make_zip(tmp_path, extra=[("/etc/x", "bad")]), "unsafe")


def test_drive_letter_and_backslash(tmp_path):
    fails(make_zip(tmp_path, extra=[("C:/x", "bad")]), "unsafe")
    fails(make_zip(tmp_path, extra=[("a\\b", "bad")], name="q.zip"), "unsafe")


def test_symlink(tmp_path):
    info = zipfile.ZipInfo("hello/link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    fails(make_zip(tmp_path, extra=[(info, "/etc/passwd")]), "symbolic link")


@pytest.mark.parametrize("name", ["hello/a.pyc", "hello/a.so", "hello/a.PYD", "hello/a.dll", "x.exe", "hello/a.dylib"])
def test_compiled_member(tmp_path, name):
    fails(make_zip(tmp_path, extra=[(name, "x")]), "compiled")


def test_too_many_members(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_MEMBERS", 2)
    fails(make_zip(tmp_path, files={"hello/__init__.py": "", "hello/a.py": ""}), "too many")


def test_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MAX_MEMBER_BYTES", 10)
    fails(make_zip(tmp_path, files={"hello/__init__.py": "x" * 11}), "too large")
    monkeypatch.setattr(installer, "MAX_MEMBER_BYTES", 1000)
    monkeypatch.setattr(installer, "MAX_TOTAL_BYTES", 15)
    fails(make_zip(tmp_path, files={"hello/__init__.py": "x" * 10, "hello/a.py": "y" * 10}, name="q.zip"), "too large")


def test_missing_manifest(tmp_path):
    fails(make_zip(tmp_path, toml=None), "plugin.toml")


def test_manifest_not_at_root(tmp_path):
    fails(make_zip(tmp_path, toml=None, files={"sub/plugin.toml": HELLO_TOML, "hello/__init__.py": ""}), "plugin.toml")


def test_bad_manifest(tmp_path):
    fails(make_zip(tmp_path, toml=HELLO_TOML.replace('id = "hello"', 'id = "Hello!"')), "not valid")


def test_missing_package(tmp_path):
    fails(make_zip(tmp_path, files={"other/__init__.py": ""}), "package folder")


def test_wrong_api_version(tmp_path):
    fails(make_zip(tmp_path, toml=HELLO_TOML.replace("api_version = 1", "api_version = 99")), "interface 99")


def test_requires_newer_slidemage(tmp_path):
    fails(make_zip(tmp_path, toml=HELLO_TOML.replace(">=8.0", ">=99.0")), "needs SlideMage")


def test_reinstall_moves_old_and_cleanup_removes(tmp_path):
    installer.install(make_zip(tmp_path))
    (loader.plugins_dir() / "hello" / "marker").write_text("old")
    installer.install(make_zip(tmp_path, name="again.zip"))
    base = loader.plugins_dir()
    assert not (base / "hello" / "marker").exists()
    olds = list((base / ".old").iterdir())
    assert len(olds) == 1 and (olds[0] / "marker").is_file()
    installer.cleanup()
    assert not (base / ".old").exists()
    assert (base / "hello" / "plugin.toml").is_file()


def test_swap_failure_restores_old(tmp_path, monkeypatch):
    installer.install(make_zip(tmp_path))
    final = loader.plugins_dir() / "hello"
    (final / "marker").write_text("old")
    real = installer.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:      # staging -> final
            raise OSError("boom")
        real(src, dst)

    monkeypatch.setattr(installer.os, "replace", flaky)
    with pytest.raises(installer.InstallError, match="put in place"):
        installer.install(make_zip(tmp_path, name="again.zip"))
    assert (final / "marker").read_text() == "old"
    assert_no_staging()


def test_remove(tmp_path):
    installer.install(make_zip(tmp_path))
    installer._changed.clear()
    installer.remove("hello")
    base = loader.plugins_dir()
    assert not (base / "hello").exists()
    assert len(list((base / ".old").iterdir())) == 1
    assert installer.changed_ids() == {"hello"}


def test_remove_unknown():
    with pytest.raises(installer.InstallError, match="not installed"):
        installer.remove("nothing")
    with pytest.raises(installer.InstallError):
        installer.remove("../etc")


def test_cleanup_never_raises(tmp_path, monkeypatch):
    installer.cleanup()      # nothing there
    base = loader.plugins_dir()
    (base / ".old" / "x").mkdir(parents=True)
    (base / ".staging" / "y").mkdir(parents=True)
    installer.cleanup()
    assert not (base / ".old").exists() and not (base / ".staging").exists()

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(installer.shutil, "rmtree", boom)
    (base / ".old").mkdir()
    installer.cleanup()


def test_read_sha256_file(tmp_path):
    good = "ab" * 32
    f = tmp_path / "a.sha256"
    f.write_text(f"{good.upper()}  p.zip\n")
    assert installer.read_sha256_file(f) == good
    f.write_text("xyz  p.zip\n")
    assert installer.read_sha256_file(f) is None
    f.write_text("")
    assert installer.read_sha256_file(f) is None
    assert installer.read_sha256_file(tmp_path / "missing") is None


def test_sha256_of(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"abc")
    assert installer.sha256_of(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
