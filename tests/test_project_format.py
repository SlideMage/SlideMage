# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project format guard (v4.1.0): <project>/.slidemage/project.json."""
from __future__ import annotations

import json

from slidemage import cli, project


def _info(root):
    return json.loads((root / project.PROJECT_INFO_PATH).read_text(encoding="utf-8"))


def _write(root, data):
    path = root / project.PROJECT_INFO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_newer_format_asks_and_is_left_alone(tmp_path, monkeypatch):
    newer = {"format": project.PROJECT_FORMAT + 1, "last_app_version": "v5.0.0"}
    _write(tmp_path, newer)
    for answer in (False, True):
        def confirm(root, info):
            assert root == tmp_path and info == newer
            return answer

        monkeypatch.setattr(cli, "_confirm_newer_project", confirm)
        assert cli.check_project_format(tmp_path, "v4.1.0") is answer
        assert _info(tmp_path) == newer


def test_other_keys_stay_and_the_highest_version_never_goes_down(tmp_path):
    _write(tmp_path, {"format": project.PROJECT_FORMAT, "last_app_version": "v0.15.30",
                      "highest_app_version": "v0.15.30", "compat": {"dismissed": ["x"]},
                      "mine": 1})
    project.record_project_open(tmp_path, "v0.15.28")        # an older exe on a second PC
    data = _info(tmp_path)
    assert data["last_app_version"] == "v0.15.28" and data["highest_app_version"] == "v0.15.30"
    assert data["mine"] == 1 and data["compat"]["dismissed"] == ["x"]
    assert data["compat"]["checked_version"] == "v0.15.30"


def test_old_scheme_versions_are_rewritten_once_to_zero_x(tmp_path):
    """v1.0 plan step 3: so version.to_zero_x can retire before 2.0, an open rewrites old-numbered versions."""
    _write(tmp_path, {"format": project.PROJECT_FORMAT, "last_app_version": "v10.19.0",
                      "highest_app_version": "v10.20.1",
                      "compat": {"checked_version": "v10.18.0", "ignore_newer": "v10.20.1", "dismissed": ["x"]}})
    project.record_project_open(tmp_path, "v0.18.9")
    data = _info(tmp_path)
    assert data["last_app_version"] == "v0.18.9"
    assert data["highest_app_version"] == "v0.18.9"          # v0.10.20.1 < v0.18.9
    assert data["compat"] == {"checked_version": "v0.10.18.0", "ignore_newer": "v0.10.20.1", "dismissed": ["x"]}


def test_an_old_scheme_last_version_seeds_checked_version_in_zero_x(tmp_path):
    _write(tmp_path, {"format": project.PROJECT_FORMAT, "last_app_version": "v9.4.2"})
    project.record_project_open(tmp_path, "v0.18.9")
    assert _info(tmp_path)["compat"]["checked_version"] == "v0.9.4.2"
