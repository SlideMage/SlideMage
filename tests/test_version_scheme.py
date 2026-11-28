# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The numbering before v0.11.0 (vX.Y.Z, X from 2 to 10) is no longer read as 0.x anywhere (v1.0 plan, step 3), except
once per project file: project.json written before v1.1 (no version_scheme key) is converted on reading and on the
next open, so an old project neither reads as "used by a newer SlideMage" nor makes a real SlideMage 2 read as 0.2."""
from __future__ import annotations

import json

import pytest

from slidemage import compat, project, updater
from slidemage.plugins.manifest import matches, parse_app_version
from slidemage.version import parse_history, release_key


# -- versions, updates and requirements: plain numbers ------------------------------------------------------------

def test_two_point_oh_is_newer_than_every_one_x():
    assert updater.parse_version("v2.0.0") == (2, 0, 0)
    assert updater.is_newer("v2.0.0", "v1.9.9") and not updater.is_newer("v1.9.9", "v2.0.0")
    assert release_key("v2.0.0") > release_key("v1.0.0") > release_key("v0.18.8")
    assert release_key("v2.0.0-beta.1") > release_key("v1.9.0")


def test_a_requirement_in_the_old_numbering_now_asks_for_that_version():
    assert parse_app_version("v10.19.0") == (10, 19, 0, 0)
    assert not matches(">=9.0", "v1.0.0") and matches(">=0.9", "v1.0.0")
    assert matches(">=1.0, <2", "v1.4.0") and not matches(">=1.0, <2", "v2.0.0")


def test_the_history_reads_in_order():
    """CHANGELOG.md holds the old releases in four-part 0.x form, so the history sorts without any conversion."""
    keys = [release_key(entry.version) for entry in parse_history()]
    assert all(key is not None for key in keys)
    assert release_key("v0.10.19.0") < release_key("v0.11.0") < release_key("v1.0.0")


# -- project.json: converted once ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("v10.19.0", "v0.10.19.0"), ("v2.0.0", "v0.2.0.0"), ("10.17", "0.10.17"), ("V5.28.1", "V0.5.28.1"),
    ("v0.18.8", "v0.18.8"), ("v1.0.0", "v1.0.0"), ("v11.0.0", "v11.0.0"), ("v1.1.0-beta.2", "v1.1.0-beta.2"),
    ("", ""), ("unknown", "unknown"), (None, None),
])
def test_a_file_from_before_one_point_one_is_read_in_zero_x(text, expected):
    assert project.stored_version({}, text) == expected


def test_a_converted_file_is_read_as_written():
    marked = {project.VERSION_SCHEME_KEY: project.VERSION_SCHEME}
    assert project.stored_version(marked, "v2.0.0") == "v2.0.0"
    assert project.stored_version(marked, "v10.19.0") == "v10.19.0"


def _project(root, **data):
    info = root / project.PROJECT_INFO_PATH
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text(json.dumps({"format": project.PROJECT_FORMAT, **data}), encoding="utf-8")
    return info


def test_an_old_project_is_not_newer_before_or_after_its_first_open(tmp_path):
    for last in ("v10.19.0", "v5.28.1"):
        root = tmp_path / last
        info = _project(root, last_app_version=last, highest_app_version=last, compat={"checked_version": last})
        assert project.project_status(root, "v1.1.0").newer is False
        assert compat.evaluate(root, "v1.1.0", []).newer_notice == ""
        project.record_project_open(root, "v1.1.0")
        data = json.loads(info.read_text(encoding="utf-8"))
        assert data[project.VERSION_SCHEME_KEY] == project.VERSION_SCHEME
        assert data["compat"]["checked_version"] == "v0." + last[1:]
        assert data["highest_app_version"] == "v1.1.0"
        assert project.project_status(root, "v1.1.0").newer is False


def test_after_the_conversion_a_two_point_oh_is_newer(tmp_path):
    _project(tmp_path, last_app_version="v1.1.0", highest_app_version="v1.1.0")
    project.record_project_open(tmp_path, "v1.1.0")
    project.record_project_open(tmp_path, "v2.0.0")       # a SlideMage 2 opens it
    data = json.loads((tmp_path / project.PROJECT_INFO_PATH).read_text(encoding="utf-8"))
    assert data["highest_app_version"] == "v2.0.0"
    assert project.project_status(tmp_path, "v1.1.0").newer is True
    assert compat.evaluate(tmp_path, "v1.1.0", []).newer_notice == "v2.0.0"
