# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/preview_bench.py: the argument parsing and the pure statistics and table helpers (no LaTeX is run)."""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "tools" / "preview_bench.py"
_SPEC = importlib.util.spec_from_file_location("preview_bench", _PATH)
bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)


def render(total, *, rules=(), timers=None, counters=None, hit=False):
    return {"total": total, "stages": {"latexmk": total / 2}, "rules": [{"rule": r, "number": 1, "seconds": s} for r, s in rules],
            "timers": timers or {}, "counters": counters or {}, "cache_hit": hit, "error": ""}


def test_defaults_and_overrides():
    args = bench.parse_args([])
    assert (args.repeat, args.view, args.in_place, args.keep, args.json) == (3, "instructor", False, False, None)
    assert args.project == bench.REPO / "example" and args.framework == bench.REPO / "latex"
    assert args.scenarios == ["cold", "unchanged", "edit", "view-switch"]
    args = bench.parse_args(["--scenarios", "fill-cache,cold", "--repeat", "5", "--view", "during-course", "--slide", "1b2",
                             "--in-place", "--json", "out.json"])
    assert args.scenarios == ["cold", "fill-cache"]  # in running order
    assert (args.repeat, args.view, args.slide, args.in_place, args.json) == (5, "during-course", "1b2", True, Path("out.json"))


@pytest.mark.parametrize("argv", [["--scenarios", "cold,bogus"], ["--repeat", "0"], ["--view", "nope"], ["--scenarios", ","]])
def test_bad_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        bench.parse_args(argv)


def test_median_helpers():
    assert bench.median([3, 1, 2]) == 2 and bench.median([1, 2, 3, 4]) == 2.5 and bench.median([]) == 0.0
    assert bench.median_by_key([{"a": 1, "b": 4}, {"a": 3}, {"a": 2}]) == {"a": 2, "b": 0}


def test_summarize_takes_medians_per_rule_timer_and_counter():
    runs = [render(2.0, rules=[("lualatex", 1.0), ("biber /tmp/x/preview-1", 0.5)], timers={"x": {"calls": 2, "seconds": .2}}, counters={"content_bytes_read": 10}),
            render(3.0, rules=[("lualatex", 1.5), ("biber", 0.7)], timers={"x": {"calls": 4, "seconds": .4}}, counters={"content_bytes_read": 30}),
            render(9.0, rules=[("lualatex", 1.1), ("lualatex", 1.2)], timers={}, counters={})]
    summary = bench.summarize(runs)
    assert summary["runs"] == 3 and summary["total"] == 3.0 and summary["stages"] == {"latexmk": 1.5}
    assert summary["rules"]["lualatex"] == {"runs": 1, "seconds": 1.5} and summary["rules"]["biber"] == {"runs": 1, "seconds": 0.5}
    assert summary["timers"]["x"] == {"calls": 2, "seconds": pytest.approx(.2)}
    assert summary["counters"] == {"content_bytes_read": 10} and summary["cache_hit"] is False
    assert bench.summarize([render(.05, hit=True)])["cache_hit"] is True


def test_tables():
    assert bench.format_table(["name", "n"], [["a", 1], ["longer", 22]]).splitlines() == [
        "name     n", "------  --", "a        1", "longer  22"]
    groups = {"edit": bench.summarize([render(2.4, rules=[("lualatex", 1.4), ("lualatex", 0.6), ("biber", 0.5)],
                                              timers={"cache.store": {"calls": 1, "seconds": .133}},
                                              counters={"content_bytes_read": 3_000_000})]),
              "hit": bench.summarize([render(.05, hit=True)])}
    summary = bench.summary_table(groups).splitlines()
    assert summary[0].split() == ["render", "n", "total", "s", "latexmk", "s", "latexmk", "rules", "(s)", "content", "MB", "dep", "MB", "cache"]
    assert "lualatex" in summary[2] and "biber 0.50" in summary[2] and "3.0" in summary[2] and summary[3].rstrip().endswith("hit")
    timers = bench.timer_table(groups)
    assert "cache.store" in timers and "1x 133 ms" in timers and timers.splitlines()[2].rstrip().endswith("-")
    assert bench.timer_table({"none": bench.summarize([render(1.0)])}) == ""
