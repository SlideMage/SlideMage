# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat.py: warn about incompatible SlideMage changes when a project is opened,
and update the project where that can be done."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest


from slidemage import compat, compat_hooks, project, version
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


@pytest.mark.parametrize("last_version, app_version", [
    ("v5.30.0", "v5.30.0"),
    ("v5.28.1", "v5.29.0"),
])
def test_no_changes_pending_outside_the_release_range(tmp_path, last_version, app_version):
    root = make_project(tmp_path, last_version)
    assert not compat.evaluate(root, app_version, [BREAKING, LOOK]).everything


def test_loud_and_quiet_changes_are_told_apart(tmp_path):
    root = make_project(tmp_path)
    ev = compat.evaluate(root, "v5.30.0", [BREAKING, MANUAL_FIX, LOOK])
    assert [p.change.id for p in ev.loud] == ["old-to-new", "manual-only"]
    assert [p.change.id for p in ev.quiet] == ["looks"]
    assert len(ev.loud[0].findings) == 3 and ev.can_update


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


def test_derived_layout_names_detector_reports_settings_not_reads(tmp_path):
    root = make_project(tmp_path, "v10.6.0")
    (root / "SlideMage_template_inst.tex").write_text(
        "\\input{SlideMage_setup}\n"
        "\\setlength{\\SMTitleBarBottomAlign}{25.32pt}\n"
        "% \\setlength{\\SMContentTopAlign}{41pt}\n"
        "\\SMFooterRightShift=4pt\n"
        "\\newcommand{\\Foo}{\\vspace*{\\SMContentTopAlign}}\n", encoding="utf-8")
    (root / "SlideMage_layout_own.tex").write_text(
        "\\renewcommand{\\SMFootnoteRightShift}{3pt}\n", encoding="utf-8")
    (root / "slides" / "a-EN-A-current.tex").write_text(
        "\\setlength{\\SMContentTopAlign}{1pt}\n", encoding="utf-8")       # slides are not scanned
    found = [(f.file, f.line, f.message.split(" ")[0]) for f in compat._detect_derived_layout_names(root)]
    assert found == [("SlideMage_template_inst.tex", 2, "\\SMTitleBarBottomAlign"),
                     ("SlideMage_template_inst.tex", 4, "\\SMFooterRightShift"),
                     ("SlideMage_layout_own.tex", 1, "\\SMFootnoteRightShift")]
    assert any(c.id == "derived-layout-names" and c.since == "v0.10.7.0" for c in compat.CHANGES)


def test_font_measurement_detector_reports_definitions_and_settings_not_reads(tmp_path):
    root = make_project(tmp_path, "v10.7.0")
    (root / "SlideMage_layout_own.tex").write_text(
        "\\newlength{\\SMFooterTextDrop}\n"
        "\\setlength{\\SMFooterTextDrop}{-0.4pt}\n"
        "% \\newlength{\\SMLabelItemWidth}\n"
        "\\newlength{\\SMEnumerateTextExtra}\n"
        "\\newlength{\\SMContentTopShift}\n"
        "\\setlength{\\SMSectionframeHeightCorrection}{16pt}\n", encoding="utf-8")
    (root / "SlideMage_template_inst.tex").write_text(
        "\\input{SlideMage_setup}\n"
        "\\setlength{\\SMEnumerateTextExtra}{9pt}\n"                      # a hook now: fine
        "\\setlength{\\SMFootlineVOffset}{-3pt}\n"
        "\\newcommand{\\Foo}{\\hspace*{\\SMLabelItemWidth}}\n", encoding="utf-8")     # reading is fine
    (root / "slides" / "a-EN-A-current.tex").write_text(
        "\\setlength{\\SMLabelItemSep}{1pt}\n", encoding="utf-8")                      # slides are not scanned
    found = [(f.file, f.line, f.message.split(" ")[0]) for f in compat._detect_font_measurement_names(root)]
    assert found == [("SlideMage_layout_own.tex", 1, "\\SMFooterTextDrop"),
                     ("SlideMage_layout_own.tex", 2, "\\SMFooterTextDrop"),
                     ("SlideMage_layout_own.tex", 4, "\\SMEnumerateTextExtra"),
                     ("SlideMage_layout_own.tex", 6, "\\SMSectionframeHeightCorrection"),
                     ("SlideMage_template_inst.tex", 3, "\\SMFootlineVOffset")]
    assert any(c.id == "font-measurements-derived" and c.since == "v0.10.8.0" for c in compat.CHANGES)


def test_top_pullup_detector_reports_definitions_and_settings_not_reads(tmp_path):
    root = make_project(tmp_path, "v10.8.0")
    (root / "SlideMage_layout_own.tex").write_text(
        "\\newlength{\\SMContentTopShift}\n"
        "\\setlength{\\SMContentTopShift}{11.5964pt}\n"
        "% \\newlength{\\SMColumnsTopCorrection}\n"
        "\\newlength{\\SMColumnsTTopCompensation}\\setlength{\\SMColumnsTTopCompensation}{13.76pt}\n"
        "\\newlength{\\SMContentTopShiftExtra}\n", encoding="utf-8")                   # another name: fine
    (root / "SlideMage_template_inst.tex").write_text(
        "\\input{SlideMage_setup}\n"
        "\\SMColumnsTopCorrection=10pt\n"
        "\\newcommand{\\Foo}{\\vspace*{-\\SMContentTopShift}}\n", encoding="utf-8")   # reading is fine
    (root / "slides" / "a-EN-A-current.tex").write_text(
        "\\setlength{\\SMContentTopShift}{1pt}\n", encoding="utf-8")                    # slides are not scanned
    found = [(f.file, f.line, f.message.split(" ")[0]) for f in compat._detect_top_pullup_names(root)]
    assert found == [("SlideMage_layout_own.tex", 1, "\\SMContentTopShift"),
                     ("SlideMage_layout_own.tex", 2, "\\SMContentTopShift"),
                     ("SlideMage_layout_own.tex", 4, "\\SMColumnsTTopCompensation"),
                     ("SlideMage_layout_own.tex", 4, "\\SMColumnsTTopCompensation"),
                     ("SlideMage_template_inst.tex", 2, "\\SMColumnsTopCorrection")]
    change = next(c for c in compat.CHANGES if c.id == "top-pullups-measured")
    assert change.since == "v0.10.9.0" and change.detect is compat._detect_top_pullup_names
    ev = compat.evaluate(root, "v10.9.0")
    assert change.id in [p.change.id for p in ev.loud]
    # the shipped profiles hold none of them any more
    shipped = Path(compat.__file__).resolve().parents[2] / "latex"
    for profile in sorted(shipped.glob("SlideMage_layout_*.tex")):
        assert not compat._SETS_V99_NAME.search(profile.read_text(encoding="utf-8")), profile.name


def test_titleframe_pad_detector_reports_templates_that_set_the_hook_not_reads(tmp_path):
    root = make_project(tmp_path, "v10.9.0")
    (root / "SlideMage_template_inst.tex").write_text(
        "\\input{SlideMage_setup}\n"
        "\\setlength{\\SMTitleframeBottomPad}{41pt}\n"
        "% \\setlength{\\SMTitleframeBottomPad}{50pt}\n"
        "\\SMTitleframeBottomPad=30pt\n"
        "\\newcommand{\\Foo}{\\vspace*{\\SMTitleframeBottomPad}}\n", encoding="utf-8")        # reading is fine
    (root / "slides" / "a-EN-A-current.tex").write_text(
        "\\setlength{\\SMTitleframeBottomPad}{1pt}\n", encoding="utf-8")                      # slides are not scanned
    found = [(f.file, f.line, f.message.split(" ")[0]) for f in compat._detect_titleframe_bottom_pad(root)]
    assert found == [("SlideMage_template_inst.tex", 2, "\\SMTitleframeBottomPad"),
                     ("SlideMage_template_inst.tex", 4, "\\SMTitleframeBottomPad")]
    change = next(c for c in compat.CHANGES if c.id == "titleframe-bottom-pad")
    assert change.since == "v0.10.10.0" and change.severity == compat.APPEARANCE
    assert change.detect is compat._detect_titleframe_bottom_pad
    ev = compat.evaluate(root, "v10.10.0")
    assert change.id in [p.change.id for p in ev.quiet] and change.id not in [p.change.id for p in ev.loud]
    # the shipped templates leave the hook at its default
    shipped = Path(compat.__file__).resolve().parents[2]
    for template in (shipped / "latex" / "SlideMage_template_slidemage.tex",):
        assert not compat._SETS_TITLEFRAME_PAD.search(template.read_text(encoding="utf-8")), template.name


def test_hook_renames_migrate_in_project_files_and_the_removed_names_are_reported(tmp_path):
    root = make_project(tmp_path, "v10.10.0")
    template = root / "SlideMage_template_inst.tex"
    template.write_bytes(
        b"\\input{SlideMage_setup}\r\n"
        b"\\setlength{\\SMProgressStripHeight}{12pt}\r\n"
        b"% \\setlength{\\SMSideFootnoteTopSep}{4pt}\r\n"
        b"\\setlength{\\SMSideFootnoteTopSep}{5pt}\r\n"
        b"\\setlength{\\SMFootlineHeight}{2ex}\r\n"
        b"\\setlength{\\SMFootlineDepth}{0.2ex}\r\n"
        b"\\setlength{\\SMRightFooterPadding}{4ex}\r\n")
    (root / "slides" / "a-EN-A-current.tex").write_text("\\SMProgressStripHeight\n", encoding="utf-8")   # slides are not scanned
    change = next(c for c in compat.CHANGES if c.id == "hook-renames-and-removals")
    assert change.since == "v0.10.11.0" and change.severity == compat.BREAKS
    found = [(f.line, f.message.split(" ")[0]) for f in change.detect(root)]
    assert found == [(2, "\\SMProgressStripHeight"), (4, "\\SMSideFootnoteTopSep"), (5, "\\SMFootlineHeight"),
                     (6, "\\SMFootlineDepth"), (7, "\\SMRightFooterPadding")]
    planned = change.migrate(root)
    assert list(planned) == [Path("SlideMage_template_inst.tex")]
    migrated = planned[Path("SlideMage_template_inst.tex")]
    assert b"\\SMProgressStripRoom}{12pt}\r\n" in migrated and migrated.count(b"\\SMSideFootnoteTitleBlockSep") == 2
    assert b"StripHeight" not in migrated and b"TopSep" not in migrated and migrated.count(b"\r\n") == 7
    assert b"\\SMFootlineHeight}{2ex}" in migrated                       # the removed names are left for the user
    template.write_bytes(migrated)
    assert change.migrate(root) == {}                                    # idempotent
    assert [f.message.split(" ")[0] for f in change.detect(root)] == [
        "\\SMFootlineHeight", "\\SMFootlineDepth", "\\SMRightFooterPadding"]
    # the shipped templates and profiles use none of the five
    shipped = Path(compat.__file__).resolve().parents[2]
    for path in [shipped / "latex" / "SlideMage_template_slidemage.tex",
                 *sorted((shipped / "latex").glob("SlideMage_layout_*.tex"))]:
        text = path.read_text(encoding="utf-8")
        assert not compat_hooks._RENAMED_RE.search(text) and not compat_hooks._REMOVED_RE.search(text), path.name


def test_omitslide_detector_reports_live_calls_in_decks_and_archive(tmp_path):
    root = make_project(tmp_path, "v7.0.2")
    (root / "decks" / "course.tex").write_text(
        "\\omitslide{live}\n"
        "% \\omitslide{commented}\n"
        "\\slide{regular} % \\omitslideversion{commented}{1-0-0}\n"
        "\\omitslideversion{pinned}{1-0-0}\\omitslide{same-line}\n"
        "\\% escaped percent \\omitslide {escaped}\n", encoding="utf-8")
    archive = root / "decks" / "archive"
    archive.mkdir()
    (archive / "old.tex").write_text(
        "% \\omitslideversion{commented}{1-0-0}\n"
        "\\omitslideversion{archived}{1-0-0}\n", encoding="utf-8")
    (root / "slides" / "ignore.tex").write_text("\\omitslide{outside-decks}\n")
    change = next(c for c in compat.CHANGES if c.id == "omitslide-instructor-only")
    findings = change.detect(root)
    assert [(f.file, f.line) for f in findings] == [
        ("decks/course.tex", 1), ("decks/course.tex", 4), ("decks/course.tex", 4),
        ("decks/course.tex", 5), ("decks/archive/old.tex", 2)]
    ev = compat.evaluate(root, "v8.0.0")
    assert not ev.loud
    assert [(p.change.id, p.findings) for p in ev.quiet] == [(change.id, findings)]


def test_campusonline_plugin_change_is_noted_for_decks_with_a_course_link(tmp_path):
    root = make_project(tmp_path, "v8.68.0")
    (root / "decks" / "course.tex").write_text(
        "\\documentclass{beamer}\n%% SlideMage course URL: https://campus.example/c/1\n\\begin{document}\n",
        encoding="utf-8")
    (root / "decks" / "plain.tex").write_text(
        "\\begin{document}\n%% SlideMage course URL: https://campus.example/c/2\n", encoding="utf-8")
    change = next(c for c in compat.CHANGES if c.id == "campusonline-plugin")
    assert change.since == "v0.9.0.0" and change.migrate is None and "plugin" in change.fix
    assert [(f.file, f.line) for f in change.detect(root)] == [("decks/course.tex", 2)]
    assert [p.change.id for p in compat.evaluate(root, "v9.0.0").quiet] == ["campusonline-plugin"]


def test_old_scheme_versions_in_project_json_read_as_zero_x(tmp_path):
    # A project used with v10.19.0, last checked at v5.28.1, opened by v0.11.0 (the renumbering).
    root = make_project(tmp_path, "v10.19.0", checked_version="v5.28.1")
    assert project.project_status(root, "v0.11.0").newer is False
    ev = compat.evaluate(root, "v0.11.0", [BREAKING, LOOK])
    assert [p.change.id for p in ev.loud] == ["old-to-new"]        # since v5.30.0 > checked v5.28.1
    assert [p.change.id for p in ev.quiet] == ["looks"]
    assert ev.newer_notice == ""
    # A project last used with v0.12.0 is newer than v0.11.0.
    assert project.project_status(make_project(tmp_path / "n", "v0.12.0"), "v0.11.0").newer is True
    # Changes up to the old checked version stay dealt with
    root = make_project(tmp_path / "m", "v10.19.0", checked_version="v10.19.0")
    assert not compat.evaluate(root, "v0.11.0", [BREAKING]).everything


def test_version_order_across_the_renumbering():
    from slidemage.updater import parse_version as p
    assert p("v0.10.19.0") < p("v0.11.0") < p("v0.11.1") < p("v0.12.0") < p("v1.0.0")
    assert p("v10.19.0") == p("v0.10.19.0") and p("v0.9.4.0") > p("v8.69.0")
