# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project format guard (v4.1.0): <project>/.slidemage/project.json."""
from __future__ import annotations

import json

import pytest

from slidemage import cli, project


def _info(root):
    return json.loads((root / project.PROJECT_INFO_PATH).read_text(encoding="utf-8"))


def _write(root, data):
    path = root / project.PROJECT_INFO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("previous", [None, "v4.0.0"])
def test_project_format_is_recorded_and_upgraded(tmp_path, monkeypatch, previous):
    if previous is not None:
        _write(tmp_path, {"format": project.PROJECT_FORMAT - 1, "last_app_version": previous})

    def no_dialog(*_args):
        raise AssertionError("no dialog expected")

    monkeypatch.setattr(cli, "_confirm_newer_project", no_dialog)
    assert cli.check_project_format(tmp_path, "v4.1.0")
    assert _info(tmp_path) == {
        "format": project.PROJECT_FORMAT, "last_app_version": "v4.1.0",
        "highest_app_version": "v4.1.0", "compat": {"checked_version": previous or "v4.1.0"}}


def test_newer_format_asks_and_is_left_alone(tmp_path, monkeypatch):
    newer = {"format": project.PROJECT_FORMAT + 1, "last_app_version": "v5.0.0"}
    _write(tmp_path, newer)
    asked = []

    monkeypatch.setattr(cli, "_confirm_newer_project",
                        lambda root, info: asked.append(info["last_app_version"]) or False)
    assert not cli.check_project_format(tmp_path, "v4.1.0")

    monkeypatch.setattr(cli, "_confirm_newer_project",
                        lambda root, info: asked.append(info["last_app_version"]) or True)
    assert cli.check_project_format(tmp_path, "v4.1.0")
    assert asked == ["v5.0.0", "v5.0.0"]
    assert _info(tmp_path) == newer  # never downgraded by the older app


def test_unreadable_file_counts_as_current_format(tmp_path):
    (tmp_path / ".slidemage").mkdir()
    (tmp_path / project.PROJECT_INFO_PATH).write_text("{not json", encoding="utf-8")
    assert project.read_project_info(tmp_path) == {
        "format": project.PROJECT_FORMAT, "last_app_version": ""}


def test_other_keys_stay_and_the_highest_version_never_goes_down(tmp_path):
    _write(tmp_path, {"format": project.PROJECT_FORMAT, "last_app_version": "v5.30.0",
                      "highest_app_version": "v5.30.0", "compat": {"dismissed": ["x"]},
                      "mine": 1})
    project.record_project_open(tmp_path, "v5.28.0")        # an older exe on a second PC
    data = _info(tmp_path)
    assert data["last_app_version"] == "v5.28.0" and data["highest_app_version"] == "v5.30.0"
    assert data["mine"] == 1 and data["compat"]["dismissed"] == ["x"]
    assert data["compat"]["checked_version"] == "v5.30.0"
