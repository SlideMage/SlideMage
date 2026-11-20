# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""slidemage.change_fragments: the changes/ files a PR adds instead of a version bump (issue #247)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from slidemage import change_fragments as cf
from slidemage import compat
from slidemage.compat_types import BREAKS, Change

FIXED = """kind: fixed
reason: direct request: Render now did nothing

render_queue.run_now() now starts the job.
Second line of the same paragraph.

Another technical paragraph.

NEW: Render now works again.
- Clicking Render now renders the slide.
- A second bullet
  that wraps.
"""

BREAKING = """kind: breaking
reason: issue #1
compat: renamed-macro

\\old is \\new now.

NEW:
- The macro has a new name.

BREAKING: Decks that use \\old must use \\new.
"""

RENAMED = Change("renamed-macro", cf.NEXT, BREAKS, "Renamed", "Renamed.")


def parse(text: str) -> cf.Fragment:
    return cf.parse(Path("x.md"), text)


def test_a_fragment_is_parsed_into_header_technical_text_and_news():
    fragment = parse(FIXED)
    assert (fragment.kind, fragment.reason) == ("fixed", "direct request: Render now did nothing")
    assert fragment.technical == ["render_queue.run_now() now starts the job.\nSecond line of the same paragraph.",
                                  "Another technical paragraph."]
    assert fragment.summary == "Render now works again."
    assert fragment.news == ["Clicking Render now renders the slide.", "A second bullet that wraps."]
    assert cf.problems(fragment, []) == []


def test_crlf_files_parse_the_same():
    assert parse(FIXED.replace("\n", "\r\n")).news == parse(FIXED).news


def test_a_breaking_fragment_names_its_compat_change():
    fragment = parse(BREAKING)
    assert fragment.compat == ["renamed-macro"]
    assert fragment.breaking == ["BREAKING: Decks that use \\old must use \\new."]
    assert cf.problems(fragment, [RENAMED]) == []
    assert any("not in slidemage.compat.CHANGES" in p for p in cf.problems(fragment, []))
    released = Change("renamed-macro", "v0.17.3", BREAKS, "Renamed", "Renamed.")
    assert any("since=" in p for p in cf.problems(fragment, [released]))


@pytest.mark.parametrize("text, expected", [
    (FIXED.replace("kind: fixed", "kind: minor"), "kind is"),
    (FIXED.replace("reason: direct request: Render now did nothing\n", ""), "reason"),
    (FIXED.replace("kind: fixed", "kind: fixed\nversion: v1"), "header line"),
    (FIXED.split("NEW:")[0], "NEW:"),
    (FIXED + "\nNEW:\n- twice\n", "NEW:"),
    (FIXED.replace("NEW: Render now works again.\n- Clicking Render now renders the slide.\n- A second bullet\n"
                   "  that wraps.\n", "NEW: Only a summary.\n"), "NEW:"),
    ("kind: new\nreason: r\n\nNEW:\n- only news\n", "technical"),
    (BREAKING.replace("BREAKING: Decks that use \\old must use \\new.\n", ""), "BREAKING:"),
    (BREAKING.replace("compat: renamed-macro\n", ""), "compat:"),
    (BREAKING.replace("kind: breaking", "kind: new"), "kind: breaking"),
    (FIXED.replace("Another technical paragraph.", "v0.1.2 (old): looks like an entry"), "CHANGELOG entry"),
])
def test_problems_are_reported(text, expected):
    assert any(expected in p for p in cf.problems(parse(text), [RENAMED])), cf.problems(parse(text), [RENAMED])


@pytest.mark.parametrize("last, kinds, expected", [
    ("v0.17.38", ["fixed"], "v0.17.39"),
    ("v0.17.38", ["fixed", "new", "fixed"], "v0.17.39"),
    ("v0.17.38", ["new", "breaking"], "v0.18.0"),
    ("v0.17.38", [], "v0.17.39"),
    ("v1.2.3", ["fixed"], "v1.2.4"),
    ("v1.2.3", ["fixed", "new"], "v1.3.0"),
    ("v1.2.3", ["breaking", "fixed"], "v2.0.0"),
])
def test_the_release_version_comes_from_the_biggest_change(last, kinds, expected):
    assert cf.next_version(last, kinds) == expected


def test_next_resolves_to_the_running_build():
    assert cf.resolve("v0.17.20", "v0.17.38") == "v0.17.20"
    assert cf.resolve(cf.NEXT, "v0.17.38") == "v0.17.38"


def test_a_next_compat_change_applies_in_a_build_between_releases(tmp_path):
    root = tmp_path / "p"
    (root / ".slidemage").mkdir(parents=True)
    (root / ".slidemage" / "project.json").write_text('{"format": 1, "last_app_version": "v0.17.30"}',
                                                     encoding="utf-8")
    pending = compat.evaluate(root, "v0.17.38", [RENAMED])
    assert [p.change.id for p in pending.loud] == ["renamed-macro"]


def test_folder_listing_skips_the_readme(tmp_path):
    (tmp_path / "README.md").write_text("# x", encoding="utf-8")
    (tmp_path / "b.md").write_text(FIXED, encoding="utf-8")
    (tmp_path / "a.md").write_text(FIXED, encoding="utf-8")
    assert [p.name for p in cf.paths(tmp_path)] == ["a.md", "b.md"]
    assert cf.paths(tmp_path / "missing") == []


def test_every_fragment_in_the_repository_is_fine():
    for fragment in cf.read_all():
        assert cf.problems(fragment) == [], fragment.path


def test_next_is_only_used_in_the_compat_registry():
    src = Path(cf.__file__).resolve().parent
    allowed = re.compile(r"^(compat(_\w+)?|change_fragments)\.py$")
    for path in src.rglob("*.py"):
        if allowed.match(path.name):
            continue
        assert not re.search(r"""since\s*=\s*["']NEXT["']""", path.read_text(encoding="utf-8")), path
