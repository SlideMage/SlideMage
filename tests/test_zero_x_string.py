# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""version.zero_x_string: stored old-scheme versions in their 0.x form (v1.0 plan, step 3)."""
from __future__ import annotations

import pytest

from slidemage.version import release_key, zero_x_string


@pytest.mark.parametrize("text, expected", [
    ("v10.19.0", "v0.10.19.0"),
    ("v2.0.0", "v0.2.0.0"),
    ("10.17", "0.10.17"),
    ("V5.28.1", "V0.5.28.1"),
    ("v0.18.8", "v0.18.8"),
    ("v1.0.0", "v1.0.0"),
    ("v1.1.0-beta.2", "v1.1.0-beta.2"),
    ("", ""),
    ("unknown", "unknown"),
])
def test_zero_x_string(text, expected):
    assert zero_x_string(text) == expected


def test_the_rewritten_string_sorts_where_the_old_one_did():
    for old in ("v10.19.0", "v2.0.0", "v9.4.2"):
        assert release_key(zero_x_string(old)) == release_key(old)


def test_non_strings_are_left_alone():
    assert zero_x_string(None) is None


# Every reader of a stored app version, so a rewritten string is known to mean what the old one meant (user,
# 2026-11-28: "ascertain that four-part version numbers are compatible with everything").
def _old_versions():
    """Every release before v0.11.0, in its old form ("v10.19.0") and its 0.x form ("v0.10.19.0")."""
    from slidemage.version import parse_history
    for entry in parse_history():
        parts = entry.version.lstrip("v").split(".")
        if len(parts) == 4 and parts[0] == "0":
            yield "v" + ".".join(parts[1:]), entry.version


def test_the_history_has_old_versions():
    old = list(_old_versions())
    assert len(old) > 300 and ("v10.19.0", "v0.10.19.0") in old and ("v2.10.0", "v0.2.10.0") in old


def test_every_reader_reads_a_rewritten_version_like_the_old_one():
    from slidemage import updater
    from slidemage.plugins.manifest import matches, parse_app_version
    for old, new in _old_versions():
        assert zero_x_string(old) == new
        assert updater.parse_version(new) == updater.parse_version(old)
        assert release_key(new) == release_key(old)
        assert parse_app_version(new) == parse_app_version(old)
        assert updater.major_key(updater.parse_version(new)) == updater.major_key(updater.parse_version(old))
        assert matches(">=9.0", new) == matches(">=9.0", old)


def test_a_rewritten_version_sorts_below_every_later_release_and_one_point_zero():
    from slidemage import updater
    later = ["v0.11.0", "v0.17.38", "v0.18.8", "v1.0.0-beta.1", "v1.0.0", "v1.2.3", "v2.0.0-beta.1"]
    for old, new in _old_versions():
        for tag in later[:-1]:
            assert updater.parse_version(new) < updater.parse_version(tag)
            assert release_key(new) < release_key(tag)
            assert updater.is_newer(tag, new) and not updater.is_newer(new, tag)


def test_project_status_and_compat_read_a_migrated_project_as_before(tmp_path):
    import json
    from slidemage import compat, project
    for last in ("v10.19.0", "v5.28.1"):
        root = tmp_path / last
        info = root / project.PROJECT_INFO_PATH
        info.parent.mkdir(parents=True)
        info.write_text(json.dumps({"format": project.PROJECT_FORMAT, "last_app_version": last,
                                    "highest_app_version": last, "compat": {"checked_version": last}}),
                        encoding="utf-8")
        before = (project.project_status(root, "v0.18.9").newer, compat.evaluate(root, "v0.18.9", []).newer_notice)
        project.record_project_open(root, "v0.18.9")
        data = json.loads(info.read_text(encoding="utf-8"))
        assert data["compat"]["checked_version"] == zero_x_string(last)
        assert before == (False, "")
        assert (project.project_status(root, "v0.18.9").newer, compat.evaluate(root, "v0.18.9", []).newer_notice) \
            == (False, "")
