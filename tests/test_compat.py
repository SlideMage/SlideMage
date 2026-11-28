# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility notices and project migrations."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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


def converted(root: Path) -> list[Finding]:
    return [Finding("media/store.json", 0, "converted")] if (root / "media" / "store.json").is_file() else []


AUTO = Change("store-format", "v5.29.0", compat.LAYOUT, "The store has a new format", "Converted on open.",
              detect=converted, automatic=True)


def test_dont_ask_again_is_per_change_and_remembered(tmp_path):
    root = make_project(tmp_path)
    compat.dismiss(root, ["old-to-new", "looks"])
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX, LOOK])
    assert [p.change.id for p in ev.everything] == ["manual-only"]
    project.record_project_open(root, "v5.31.0")         # other keys survive later opens
    assert compat.dismissed_ids(root) == {"old-to-new", "looks"}


def test_an_open_does_not_acknowledge_changes_or_show_future_migrations(tmp_path):
    root = make_project(tmp_path)
    assert not compat.evaluate(root, "v5.29.0", [BREAKING]).everything
    project.record_project_open(root, "v5.30.0")
    assert compat.evaluate(root, "v5.30.0", [BREAKING]).loud
    assert compat.checked_version(root) == "v0.5.28.1"     # the open rewrote the old-scheme v5.28.1
    compat.acknowledge(root, "v5.30.0")
    assert not compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX]).everything


def test_update_backs_up_writes_atomically_and_includes_the_workdeck(tmp_path):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING])
    dry = compat.run_update(root, ev.loud, dry_run=True, now=NOW)
    assert sorted(dry.changed) == ["decks/#workdeck.tex", "decks/course.tex"] and dry.backup is None
    assert b"\\old" in (root / "decks" / "course.tex").read_bytes()      # nothing written

    seen = []
    done = compat.run_update(root, ev.loud, now=NOW, on_progress=seen.append)
    assert [p.text for p in seen] == [f"{action} ({n} of 2)" for action in ("Backing up", "Updating") for n in (1, 2)]
    assert [p.fraction for p in seen] == [0.5, 1.0, 0.5, 1.0]
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
    assert [p.change.id for p in ev.loud] == ["old-to-new"] and ev.can_update
    assert [p.change.id for p in ev.quiet] == ["looks"] and len(ev.loud[0].findings) == 3
    md = compat.write_report(root, ev, "v5.30.0")
    text = md.read_text(encoding="utf-8")
    assert "## For an AI tool" in text and "`decks/course.tex:1`" in text
    assert "Replace \\old by \\new." in text and "automatic update: yes" in text
    data = json.loads((root / compat.REPORT_JSON).read_text(encoding="utf-8"))
    assert [c["id"] for c in data["changes"]] == ["old-to-new", "looks"]
    assert data["changes"][0]["findings"][0] == {"file": "decks/#workdeck.tex", "line": 1, "message": "uses \\old"}


def test_command_line_exit_code(tmp_path, monkeypatch):
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


def test_changes_slidemage_made_itself_are_a_notice_not_an_update(tmp_path):
    root = make_project(tmp_path)
    assert not compat.evaluate(root, "v5.30.0", [AUTO, BREAKING]).applied      # not converted: nothing to tell
    (root / "media").mkdir()
    (root / "media" / "store.json").write_text("{}", encoding="utf-8")
    ev = compat.evaluate(root, "v5.30.0", [AUTO, MANUAL_FIX, LOOK])
    assert [p.change.id for p in ev.applied] == ["store-format"]
    assert [p.change.id for p in ev.loud] == ["manual-only"] and not ev.can_update
    assert [p.change.id for p in ev.everything] == ["manual-only", "store-format", "looks"]
    assert ev.readable_from == "v5.29.0"
    assert "automatic update: done by SlideMage" in compat.report_markdown(root, ev, "v5.30.0")
    assert compat.report_data(ev, "v5.30.0")["changes"][1]["applied_by_slidemage"] is True
    compat.dismiss(root, ["store-format"])
    assert not compat.evaluate(root, "v5.30.0", [AUTO]).everything


def test_decks_with_topic_blocks_or_appendix_views_get_a_one_time_notice(tmp_path):
    root = make_project(tmp_path, "v0.17.5")
    (root / "decks" / "course.tex").write_text(
        "\\slide{a}\n\\slideblock{methods}\n% \\slideblock{old}\n\\deckappendixtoc[instructor]\n\\deckappendixtoc\n",
        encoding="utf-8")
    change = next(c for c in compat.CHANGES if c.id == "topic-blocks-and-appendix-views")
    ev = compat.evaluate(root, "v0.17.20", [change])
    assert change.automatic and change.since == "v0.17.20" and not ev.loud
    assert [(f.file, f.line) for f in ev.applied[0].findings] == [("decks/course.tex", 2), ("decks/course.tex", 4)]
    assert "topic block" in ev.applied[0].findings[0].message
    (root / "decks" / "course.tex").write_text("\\slide{a}\n\\deckappendixtoc\n", encoding="utf-8")
    assert not compat.evaluate(root, "v0.17.20", [change]).applied      # nothing an older SlideMage cannot compile
