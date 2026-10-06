"""compat.py: warn about incompatible SlideMage changes when a project is opened,
and update the project where that can be done."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from slidemage import compat, project, version
from slidemage.compat import APPEARANCE, BREAKS, Change, Finding

NOW = datetime(2026, 10, 6, 12, 0, 0)


def make_project(tmp_path: Path, last_version="v5.28.1", **extra) -> Path:
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    (root / "decks" / "#workdeck.tex").write_bytes(b"\\old{x}\r\n")
    (root / "decks" / "course.tex").write_bytes(b"\\old{y}\n\\old{z}\n")
    data = {"format": project.PROJECT_FORMAT, "last_app_version": last_version,
            "highest_app_version": last_version, "compat": {"checked_version": last_version}}
    data["compat"].update(extra)
    project.write_project_json(root, data)
    return root


def scan(root: Path) -> list[Finding]:
    out = []
    for path in sorted((root / "decks").glob("*.tex")):
        for n, line in enumerate(path.read_bytes().decode().splitlines(), start=1):
            if "\\old" in line:
                out.append(Finding(f"decks/{path.name}", n, "uses \\old"))
    return out


def rename(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes().replace(b"\\old", b"\\new")
            for p in (root / "decks").glob("*.tex")}


BREAKING = Change("old-to-new", "v5.30.0", BREAKS, "\\old is now \\new", "Renamed.",
                  fix="Replace \\old by \\new.", detect=scan, migrate=rename)
MANUAL_FIX = Change("manual-only", "v5.30.0", compat.LAYOUT, "Layout", "Hand work.",
                    fix="Edit it.")
LOOK = Change("looks", "v5.30.0", APPEARANCE, "Looks different", "Bars are lower.")


def test_nothing_pending_for_a_project_that_is_current(tmp_path):
    root = make_project(tmp_path, "v5.30.0")
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    assert not ev.everything                 # those changes came before this project's version


def test_loud_and_quiet_changes_are_told_apart(tmp_path):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX, LOOK])
    assert [p.change.id for p in ev.loud] == ["old-to-new", "manual-only"]
    assert [p.change.id for p in ev.quiet] == ["looks"]
    assert len(ev.loud[0].findings) == 3 and ev.can_update


def test_changes_of_a_later_release_are_not_pending_yet(tmp_path):
    root = make_project(tmp_path)
    assert not compat.evaluate(root, "v5.29.0", [BREAKING]).everything


def test_a_detector_that_finds_nothing_means_nothing_is_pending(tmp_path):
    root = make_project(tmp_path)
    (root / "decks" / "#workdeck.tex").write_bytes(b"\\new{x}\r\n")
    (root / "decks" / "course.tex").write_bytes(b"\\new{y}\n")
    assert not compat.evaluate(root, "v5.30.0", [BREAKING]).everything


def test_not_now_changes_nothing_so_it_comes_back(tmp_path):
    root = make_project(tmp_path)
    before = (root / project.PROJECT_INFO_PATH).read_text(encoding="utf-8")
    assert compat.evaluate(root, "v5.30.0", [BREAKING]).loud
    # the app records the open, as cli.check_project_format() does
    project.record_project_open(root, "v5.30.0")
    assert compat.evaluate(root, "v5.30.0", [BREAKING]).loud
    assert json.loads(before)["compat"]["checked_version"] == "v5.28.1"
    assert compat.checked_version(root) == "v5.28.1"


def test_dont_ask_again_is_per_change_and_remembered(tmp_path):
    root = make_project(tmp_path)
    compat.dismiss(root, ["old-to-new", "looks"])
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX, LOOK])
    assert [p.change.id for p in ev.everything] == ["manual-only"]
    project.record_project_open(root, "v5.31.0")         # other keys survive later opens
    assert compat.dismissed_ids(root) == {"old-to-new", "looks"}


def test_acknowledge_moves_the_baseline(tmp_path):
    root = make_project(tmp_path)
    compat.acknowledge(root, "v5.30.0")
    assert not compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).everything


def test_update_backs_up_writes_atomically_and_includes_the_workdeck(tmp_path):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING])
    dry = compat.run_update(root, ev.loud, dry_run=True, now=NOW)
    assert sorted(dry.changed) == ["decks/#workdeck.tex", "decks/course.tex"] and dry.backup is None
    assert b"\\old" in (root / "decks" / "course.tex").read_bytes()      # nothing written

    done = compat.run_update(root, ev.loud, now=NOW)
    assert sorted(done.changed) == ["decks/#workdeck.tex", "decks/course.tex"] and not done.errors
    assert (root / "decks" / "#workdeck.tex").read_bytes() == b"\\new{x}\r\n"   # CRLF kept
    assert (root / "decks" / "course.tex").read_bytes() == b"\\new{y}\n\\new{z}\n"
    assert (done.backup / "decks" / "course.tex").read_bytes() == b"\\old{y}\n\\old{z}\n"
    assert not list((root / "decks").glob("*.slidemage-tmp"))
    # idempotent, and the detector now finds nothing
    assert not compat.run_update(root, ev.loud, now=NOW).changed
    assert not compat.evaluate(root, "v5.30.0", [BREAKING]).everything


def test_a_failing_migration_is_reported_and_does_not_stop_the_rest(tmp_path):
    root = make_project(tmp_path)

    def broken(_root):
        raise ValueError("boom")

    bad = Change("bad", "v5.30.0", BREAKS, "Bad", "x", migrate=broken)
    ev = compat.evaluate(root, "v5.30.0", [bad, BREAKING])
    done = compat.run_update(root, ev.loud, now=NOW)
    assert done.errors == ["bad: boom"] and len(done.changed) == 2


def test_a_project_used_by_a_newer_slidemage_is_noticed_once(tmp_path):
    root = make_project(tmp_path, "v5.31.0")
    assert compat.evaluate(root, "v5.28.1", []).newer_notice == "v5.31.0"
    compat.ignore_newer(root, "v5.31.0")
    assert compat.evaluate(root, "v5.28.1", []).newer_notice == ""
    project.write_project_json(root, {**project.read_project_json(root), "highest_app_version": "v5.32.0"})
    assert compat.evaluate(root, "v5.28.1", []).newer_notice == "v5.32.0"


def test_report_for_people_and_tools(tmp_path):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, LOOK])
    md = compat.write_report(root, ev, "v5.30.0")
    text = md.read_text(encoding="utf-8")
    assert "## For an AI tool" in text and "`decks/course.tex:1`" in text
    assert "Replace \\old by \\new." in text and "automatic update: yes" in text
    data = json.loads((root / compat.REPORT_JSON).read_text(encoding="utf-8"))
    assert [c["id"] for c in data["changes"]] == ["old-to-new", "looks"]
    assert data["changes"][0]["findings"][0] == {"file": "decks/#workdeck.tex", "line": 1, "message": "uses \\old"}


def test_command_line_exit_code(tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path)
    monkeypatch.setattr(compat, "CHANGES", [BREAKING])
    monkeypatch.setattr(version, "VERSION_NUMBER", "v5.30.0")
    assert compat.main([str(root)]) == 1
    assert compat.main([str(root), "--fix", "--json"]) == 0
    assert b"\\new" in (root / "decks" / "course.tex").read_bytes()


def test_registry_ids_are_unique_and_every_breaking_release_has_an_entry():
    ids = [c.id for c in compat.CHANGES]
    assert len(ids) == len(set(ids))
    from slidemage.updater import parse_version
    registered = {c.since for c in compat.CHANGES}
    for entry in version.parse_history():
        number = parse_version(entry.version)
        if number is None or number < compat.REGISTRY_FROM:
            continue
        if any(p.startswith("BREAKING:") for p in entry.paragraphs):
            assert entry.version in registered, (
                f"{entry.version} has a BREAKING: paragraph but no slidemage.compat.CHANGES entry")
