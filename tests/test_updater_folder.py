# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Updating a folder installation: which asset, unpacking next to the folder, the helper that swaps the folders."""
import os
import sys
import zipfile

import pytest

from slidemage import updater


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_the_asset_follows_the_flavour_of_the_installation(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, "single")
    assert updater.asset_names() == ("SlideMage-windows.zip", "SlideMage.exe")
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, "folder")
    assert updater.asset_names() == ("SlideMage-windows-folder.zip", "SlideMage.exe")
    data = {"tag_name": "v9.0.0", "assets": [{"name": "SlideMage-windows.zip", "url": "single-url", "size": 1},
                                             {"name": "SlideMage-windows-folder.zip", "url": "folder-url", "size": 2}]}
    assert updater._release_from(data).asset_url == "folder-url"
    monkeypatch.setenv(updater.FLAVOUR_ENV_VAR, "single")
    assert updater._release_from(data).asset_url == "single-url"


def test_a_source_checkout_or_a_single_file_is_not_a_folder_installation(monkeypatch):
    monkeypatch.delenv(updater.FLAVOUR_ENV_VAR, raising=False)
    assert updater.install_flavour() == updater.SINGLE


def test_the_update_is_unpacked_next_to_the_folder_without_touching_it(tmp_path):
    install = tmp_path / "SlideMage-folder"
    install.mkdir()
    (install / "SlideMage.exe").write_bytes(b"old")
    zip_path = make_zip(tmp_path / "u.zip", {"SlideMage-folder/SlideMage.exe": b"new",
                                             "SlideMage-folder/_internal/lib.dll": b"dll"})
    staging = updater.stage_folder_update(zip_path, install, "SlideMage.exe")
    assert staging == tmp_path / "SlideMage-folder.update"
    assert (staging / "SlideMage.exe").read_bytes() == b"new" and (staging / "_internal" / "lib.dll").read_bytes() == b"dll"
    assert (install / "SlideMage.exe").read_bytes() == b"old"
    # a zip with the content at its top level works as well
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


def test_the_helper_script_waits_for_the_process_swaps_and_starts_the_new_version(tmp_path):
    install, staging = tmp_path / "SlideMage-folder", tmp_path / "SlideMage-folder.update"
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 4242, ["--project", "D:/p"], windows=True)
    assert name.endswith(".cmd") and 'PID eq 4242' in text and "SlideMage-folder.old" in text
    assert f'start "" "{install / "SlideMage.exe"}" "--project" "D:/p"' in text
    _name, quiet = updater.swap_script(install, staging, "SlideMage.exe", 4242, None, windows=True)
    assert "start " not in quiet
    name, text = updater.swap_script(install, staging, "SlideMage", 4242, ["--project", "/p"], windows=False)
    assert name.endswith(".sh") and "kill -0 4242" in text and "'--project' '/p'" in text


@pytest.mark.skipif(os.name != "nt", reason="runs the Windows helper")
def test_the_windows_helper_really_swaps_the_folders_once_the_process_is_gone(tmp_path):
    install = tmp_path / "SlideMage-folder"
    install.mkdir()
    (install / "SlideMage.exe").write_bytes(b"old")
    staging = tmp_path / "SlideMage-folder.update"
    staging.mkdir()
    (staging / "SlideMage.exe").write_bytes(b"new")
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 2_999_999, None, windows=True)   # no such process
    script = tmp_path / name
    script.write_text(text, encoding="utf-8", newline="")
    # Started as the app starts it: v8.33.0 to v8.39.1 started it detached, without handles, and it ended at once.
    assert updater.start_helper(script).wait(timeout=60) == 0
    assert (install / "SlideMage.exe").read_bytes() == b"new"
    assert (tmp_path / "SlideMage-folder.old" / "SlideMage.exe").read_bytes() == b"old"
    assert not staging.exists()
    updater.remove_leftover_folder(install)
    assert not (tmp_path / "SlideMage-folder.old").exists()


@pytest.mark.skipif(os.name != "nt", reason="runs the Windows helper")
def test_the_windows_helper_gives_up_on_a_folder_it_cannot_move_and_starts_the_old_one(tmp_path):
    install = tmp_path / "SlideMage-folder"
    install.mkdir()
    staging = tmp_path / "SlideMage-folder.update"
    staging.mkdir()
    name, text = updater.swap_script(install, staging, "SlideMage.exe", 2_999_999, None, windows=True)
    # Every move fails and the waits take no time: the count must reach its limit and end the script.
    text = text.replace("ping -n 3 127.0.0.1 >NUL", "rem").replace(f'move "{install}"', 'move "nothing-here"')
    script = tmp_path / name
    script.write_text(text, encoding="utf-8", newline="")
    assert updater.start_helper(script).wait(timeout=60) == 0
    assert install.is_dir() and staging.is_dir() and not script.exists()
