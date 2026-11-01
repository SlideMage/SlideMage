# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/debug_log.py: reading, merging and filtering debug-log files, and the timeline of the latest request."""
import importlib.util
import logging
import sys
from pathlib import Path

import pytest

from slidemage import diagnostics

spec = importlib.util.spec_from_file_location("debug_log", Path(__file__).parents[1] / "tools" / "debug_log.py")
tool = sys.modules.setdefault("debug_log", importlib.util.module_from_spec(spec))   # dataclasses look it up
spec.loader.exec_module(tool)

APP = """\
2026-11-01 10:00:00.000 +1.000s INFO     startup            app:10 MainThread  debug log started
    SlideMage v0.13.7, from source
2026-11-01 10:00:01.000 +2.000s DEBUG    timing             app:10 MainThread  prompt
2026-11-01 10:00:03.500 +4.500s DEBUG    timing             app:10 Worker-1  render_done file=a.tex
2026-11-01 10:00:04.000 +5.000s ERROR    plugins.hello      app:10 MainThread  box failed
    Traceback (most recent call last):
    ValueError: boom
"""
HOOK = """\
2026-11-01 10:00:00.500 +0.010s DEBUG    timing             hook:22 MainThread  prompt
2026-11-01 10:00:02.250 +0.020s DEBUG    timing             hook:23 MainThread  tool_start tool=modify_slide
"""


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "app_2026-11-01_100000_10.log").write_text(APP, encoding="utf-8")
    (tmp_path / "hook.log").write_text(HOOK, encoding="utf-8")
    return tmp_path


def test_files_are_merged_by_time_and_indented_lines_stay_with_their_record(folder):
    records = tool.read([folder])
    assert [r.role for r in records] == ["app", "hook", "app", "hook", "app", "app"]
    assert records[0].more == ["    SlideMage v0.13.7, from source"]
    assert records[-1].more[-1] == "    ValueError: boom"


def test_area_level_and_text_filters(folder):
    records = tool.read([folder])
    assert [r.area for r in tool.select(records, area="plugins")] == ["plugins.hello"]
    assert [r.level for r in tool.select(records, level="error")] == ["ERROR"]
    assert len(tool.select(records, grep="boom")) == 1
    assert len(tool.select(records, area="plug")) == 0           # a prefix of a name part is no match


def test_the_timeline_starts_at_the_last_prompt_and_names_the_process(folder):
    lines = tool.timeline(tool.read([folder]))
    assert len(lines) == 3
    assert lines[0].startswith("+  0.000 s  prompt") and lines[0].endswith("[app:10]")
    assert "+  1.250 s  tool_start tool=modify_slide  [hook:23]" == lines[1]
    assert lines[2].startswith("+  2.500 s  render_done file=a.tex")


def test_it_reads_what_diagnostics_writes(tmp_path, monkeypatch):
    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path))
    monkeypatch.setenv(diagnostics.DEBUG_ENV, "1")
    diagnostics.reset()
    try:
        diagnostics.setup("app")
        logging.getLogger("slidemage.compile").debug("job started deck=micro-01")
        try:
            raise KeyError("x")
        except KeyError:
            logging.getLogger("slidemage.compile").exception("job failed")
    finally:
        diagnostics.reset()
    records = tool.read([tmp_path / diagnostics.DEBUG_DIR])
    assert [r.area for r in records] == ["startup", "compile", "compile"]
    assert records[1].message == "job started deck=micro-01" and records[1].level == "DEBUG"
    assert records[2].more[-1] == "    KeyError: 'x'" and records[0].more[0].startswith("    SlideMage v")
    assert tool.main([str(tmp_path / diagnostics.DEBUG_DIR), "--area", "compile", "--level", "error"]) == 0
