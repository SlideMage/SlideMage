# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Folder updates select an asset, stage it and protect projects during the swap."""
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from slidemage import updater
from conftest import make_zip, write_test_file


def test_a_source_checkout_or_a_single_file_is_not_a_folder_installation(monkeypatch):
    monkeypatch.delenv(updater.FLAVOUR_ENV_VAR, raising=False)
    assert updater.install_flavour() == updater.SINGLE


def test_the_update_is_unpacked_next_to_the_folder_without_touching_it(tmp_path):
    install = tmp_path / "SlideMage-folder"
    write_test_file(install / "SlideMage.exe", b"old")
    zip_path = make_zip(tmp_path / "u.zip", {"SlideMage-folder/SlideMage.exe": b"new",
                                             "SlideMage-folder/_internal/lib.dll": b"dll"})
    staging = updater.stage_folder_update(zip_path, install, "SlideMage.exe")
    assert staging == tmp_path / "SlideMage-folder.update"
    assert (staging / "SlideMage.exe").read_bytes() == b"new" and (staging / "_internal" / "lib.dll").read_bytes() == b"dll"
    assert (install / "SlideMage.exe").read_bytes() == b"old"
    zip_flat = make_zip(tmp_path / "f.zip", {"SlideMage.exe": b"flat", "_internal/x": b"x"})
    assert (updater.stage_folder_update(zip_flat, install, "SlideMage.exe") / "SlideMage.exe").read_bytes() == b"flat"


def test_a_zip_without_the_binary_or_with_unsafe_paths_is_refused(tmp_path):
    install = tmp_path / "app"
    install.mkdir()
    with pytest.raises(updater.UpdateError, match="doesn't contain"):
        updater.stage_folder_update(make_zip(tmp_path / "a.zip", {"app/readme.txt": b"x"}), install, "SlideMage.exe")
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater.stage_folder_update(make_zip(tmp_path / "b.zip", {"../evil.exe": b"x"}), install, "SlideMage.exe")
    assert not (tmp_path / "app.update").exists() and not (tmp_path / "evil.exe").exists()


def make_project(folder):
    write_test_file(folder / "slide_ids.csv", "id\n")
    return folder


@pytest.mark.parametrize("where", ["SlideMage-folder/SlideMage-linux", "SlideMage-folder.old/deep/course"])
def test_an_update_is_refused_while_a_project_lies_in_the_folders_it_replaces(tmp_path, where):
    # Issue #85: the swap moved a project inside the program folder to "<folder>.old", and the next start deleted it.
    install = tmp_path / "SlideMage-folder"
    install.mkdir()
    project = make_project(tmp_path / where)
    zip_path = make_zip(tmp_path / "u.zip", {"app/SlideMage.exe": b"new"})
    with pytest.raises(updater.UpdateError, match="Move the projects") as caught:
        updater.stage_folder_update(zip_path, install, "SlideMage.exe")
    assert str(project) in str(caught.value)
    assert not (tmp_path / "SlideMage-folder.update").exists()


def test_the_bundled_example_is_no_project_but_one_next_to_it_is(tmp_path):
    install = tmp_path / "SlideMage-folder"
    example = "_internal/slidemage_template/example"
    make_project(install / example)
    zip_path = make_zip(tmp_path / "u.zip", {"app/SlideMage.exe": b"new"})
    assert updater.stage_folder_update(zip_path, install, "SlideMage.exe") == tmp_path / "SlideMage-folder.update"
    make_project(tmp_path / "SlideMage-folder.old" / example)
    assert updater.remove_leftover_folder(install) == []
    assert not (tmp_path / "SlideMage-folder.old").exists()
    project = make_project(install / "course")
    assert updater.projects_in(install) == [project]


def test_the_leftover_folder_is_kept_while_it_holds_a_project(tmp_path):
    install = tmp_path / "SlideMage-folder"
    old = tmp_path / "SlideMage-folder.old"
    project = make_project(old / "SlideMage-linux")
    (project / "slides").mkdir()
    assert updater.remove_leftover_folder(install) == [project]
    assert (project / "slide_ids.csv").is_file() and (project / "slides").is_dir()
    (project / "slide_ids.csv").unlink()
    assert updater.remove_leftover_folder(install) == []
    assert not old.exists()


def test_the_helper_script_waits_for_the_process_swaps_and_starts_the_new_version(tmp_path):
    install, staging = tmp_path / "SlideMage-folder", tmp_path / "SlideMage-folder.update"
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 4242, ["--project", "D:/p"], windows=True)
    assert name.endswith(".cmd") and 'PID eq 4242' in text and "SlideMage-folder.old" in text
    assert f'cd /d "{install}"\r\nstart "" "{install / "SlideMage.exe"}" "--project" "D:/p"' in text
    _name, quiet = updater.swap_script(install, staging, "SlideMage.exe", 4242, None, windows=True)
    assert "start " not in quiet
    name, text = updater.swap_script(install, staging, "SlideMage", 4242, ["--project", "/p"], windows=False)
    assert name.endswith(".sh") and "kill -0 4242" in text and "'--project' '/p'" in text


@pytest.mark.skipif(os.name != "nt", reason="runs the Windows helper")
def test_the_windows_helper_really_swaps_the_folders_once_the_process_is_gone(tmp_path):
    install = tmp_path / "SlideMage-folder"
    staging = tmp_path / "SlideMage-folder.update"
    write_test_file(install / "SlideMage.exe", b"old")
    write_test_file(staging / "SlideMage.exe", b"new")
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 2_999_999, None, windows=True)   # no such process
    script = write_test_file(tmp_path / name, text)
    # Started as the app starts it: v8.33.0 to v8.39.1 started it detached, without handles, and it ended at once.
    assert updater.start_helper(script).wait(timeout=60) == 0
    assert (install / "SlideMage.exe").read_bytes() == b"new"
    assert (tmp_path / "SlideMage-folder.old" / "SlideMage.exe").read_bytes() == b"old"
    assert not staging.exists()
    updater.remove_leftover_folder(install)
    assert not (tmp_path / "SlideMage-folder.old").exists()


@pytest.mark.skipif(os.name != "nt", reason="runs the Windows helper")
def test_the_windows_helper_swaps_the_folder_the_app_was_started_in(tmp_path):
    # Started from Explorer, the app's working folder is the installation. Up to v8.51.0 the helper inherited it,
    # so it could never move that folder and started the old version again.
    install = tmp_path / "SlideMage-folder"
    staging = tmp_path / "SlideMage-folder.update"
    write_test_file(install / "SlideMage.exe", b"old")
    write_test_file(staging / "SlideMage.exe", b"new")
    app = textwrap.dedent(f"""
        import os, sys
        from pathlib import Path
        sys.path.insert(0, {str(Path(updater.__file__).parents[1])!r})
        from slidemage import updater
        name, text = updater.swap_script(Path({str(install)!r}), Path({str(staging)!r}), "SlideMage.exe", os.getpid(), None)
        script = Path({str(tmp_path)!r}) / name
        script.write_text(text, encoding="utf-8", newline="")
        updater.start_helper(script)
    """)
    subprocess.run([sys.executable, "-c", app], cwd=install, check=True, timeout=60)
    deadline = time.monotonic() + 60
    while _bytes_or_none(install / "SlideMage.exe") != b"new" or staging.exists():
        assert time.monotonic() < deadline, "the helper did not swap the folders"
        time.sleep(0.2)
    assert (tmp_path / "SlideMage-folder.old" / "SlideMage.exe").read_bytes() == b"old"


def _bytes_or_none(path):
    """The file's bytes, or None while the helper is between its two moves: the installation folder is then briefly
    gone, or the file is held by the move. Under load (-n auto) the poll landed in that moment."""
    try:
        return path.read_bytes()
    except (FileNotFoundError, PermissionError):
        return None


@pytest.mark.skipif(os.name != "nt", reason="runs the Windows helper")
def test_the_windows_helper_gives_up_on_a_folder_it_cannot_move_and_starts_the_old_one(tmp_path):
    install = tmp_path / "SlideMage-folder"
    install.mkdir()
    staging = tmp_path / "SlideMage-folder.update"
    staging.mkdir()
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 2_999_999, None, windows=True)
    # Every move fails and the waits take no time: the count must reach its limit and end the script.
    text = text.replace("ping -n 3 127.0.0.1 >NUL", "rem").replace(f'move "{install}"', 'move "nothing-here"')
    script = write_test_file(tmp_path / name, text)
    assert updater.start_helper(script).wait(timeout=60) == 0
    assert install.is_dir() and staging.is_dir() and not script.exists()


@pytest.mark.parametrize("flavour, suffix", [("single", ""), ("folder", "-folder")])
def test_the_asset_digest_and_signature_follow_the_installation_flavour(monkeypatch, flavour, suffix):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, flavour)
    assert updater.asset_names() == (f"SlideMage-windows{suffix}.zip", "SlideMage.exe")
    data = {"tag_name": "v9", "assets": [
        {"name": "SlideMage-windows.zip", "url": "single", "size": 1, "digest": "sha256:" + "1" * 64},
        {"name": "SlideMage-windows.zip.sig", "url": "single-sig"},
        {"name": "SlideMage-windows-folder.zip", "url": "folder", "size": 2, "digest": "sha256:" + "2" * 64},
        {"name": "SlideMage-windows-folder.zip.sig", "url": "folder-sig"},
    ]}
    release = updater._release_from(data)
    assert release.asset_name == f"SlideMage-windows{suffix}.zip"
    assert (release.asset_url, release.signature_url) == (flavour, f"{flavour}-sig")
    assert release.asset_digest == "sha256:" + ("2" if suffix else "1") * 64


# -- the setup's uninstall entry (packaging/slidemage.iss) --------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="the Windows registry")
def test_sync_setup_version_updates_only_its_own_entry(tmp_path, monkeypatch):
    import winreg

    key_path = r"Software\SlideMageTests\SetupEntry"
    monkeypatch.setattr(updater, "SETUP_UNINSTALL_KEY", key_path)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(tmp_path) + "\\")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "0.18.5")
    try:
        assert updater.sync_setup_version(tmp_path, "v0.19.0")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            assert winreg.QueryValueEx(key, "DisplayVersion")[0] == "0.19.0"
        assert not updater.sync_setup_version(tmp_path, "v0.19.0")            # already right
        assert not updater.sync_setup_version(tmp_path / "other", "v0.20.0")  # another folder's SlideMage
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SlideMageTests")


def test_sync_setup_version_without_an_entry_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "SETUP_UNINSTALL_KEY", r"Software\SlideMageTests\NoSuchEntry")
    assert not updater.sync_setup_version(tmp_path, "v1.0.0")


def test_setup_key_matches_the_setup_scripts_app_id():
    iss = (Path(__file__).resolve().parents[1] / "packaging" / "slidemage.iss").read_text(encoding="utf-8")
    app_id = re.search(r"^AppId=\{(\{[0-9A-F-]+\})", iss, re.MULTILINE).group(1)
    assert updater.SETUP_UNINSTALL_KEY.endswith("\\" + app_id + "_is1")
