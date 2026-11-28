# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from slidemage import compat, version
from slidemage.compat_types import BREAKS, Change

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "make_release.py"
_spec = importlib.util.spec_from_file_location("make_release", _PATH)
make_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_release)

FIX = """kind: fixed
reason: direct request: the scan was slow

render_evidence looks the framework up once.

NEW: Background previews start sooner.
- The scan is faster.
"""
FEATURE = """kind: new
reason: issue #9

A new button in ui/dialogs/x.py.
Wrapped line.

Second technical paragraph.

NEW:
- A new button.
- And a second bullet.
"""
BREAK = """kind: breaking
reason: issue #10
compat: renamed-macro

\\old is \\new.

NEW:
- The macro is renamed.

BREAKING: Use \\new instead of \\old.
"""
ORDER = {"fix.md": 1, "feature.md": 2, "break.md": 3}


def tree(tmp_path: Path, fragments: dict[str, str]) -> Path:
    nl = "\r\n"
    package = tmp_path / "src" / "slidemage"
    package.mkdir(parents=True)
    (package / "CHANGELOG.md").write_bytes(
        f"# History{nl}{nl}v0.17.38 (2026-11-19, x): Old entry.{nl}{nl}NEW:{nl}- Old bullet.{nl}".encode())
    (package / "version.py").write_text('X = 1\nVERSION_NUMBER = "v0.17.38"\n', encoding="utf-8")
    (package / "compat_sample.py").write_text('CHANGE = Change(id="renamed-macro", since="NEXT")\n'
                                              "OTHER = Change(id='x', since='v0.1.0')\n", encoding="utf-8")
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "README.md").write_text("# Fragments\n", encoding="utf-8")
    for name, text in fragments.items():
        (tmp_path / "changes" / name).write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(compat, "CHANGES", [Change("renamed-macro", "NEXT", BREAKS, "Renamed", "Renamed.")])


def prepare(root: Path, summary: str = ""):
    return make_release.prepare(root, summary, "2026-11-21", when=lambda f: ORDER[f.path.name])


def test_several_fragments_give_one_entry_biggest_kind_first(tmp_path, registry):
    root = tree(tmp_path, {"fix.md": FIX, "feature.md": FEATURE, "break.md": BREAK})
    _previous, number, entry, fragments = prepare(root, "Renamed macro, a new button, a faster scan.")
    assert number == "v0.18.0"
    assert [f.path.name for f in fragments] == ["break.md", "feature.md", "fix.md"]
    parsed = make_release.history_entry(entry)
    assert parsed.meta == "2026-11-21, release of 3 changes"
    assert entry.startswith("v0.18.0 (2026-11-21, release of 3 changes): Renamed macro, a new button, a faster scan.")
    assert "\n\nNew (issue #9): A new button in ui/dialogs/x.py.\nWrapped line.\n\nSecond technical paragraph." in entry
    assert parsed.summary == "Renamed macro, a new button, a faster scan."
    assert parsed.news == ["The macro is renamed.", "A new button.", "And a second bullet.", "The scan is faster."]
    assert parsed.paragraphs[-1] == "BREAKING: Use \\new instead of \\old."

    notes = make_release.notes(number, "v0.17.38", entry)
    assert "## Breaking changes" in notes and "This release covers" not in notes

    make_release.apply(root, number, entry, fragments)
    package = root / "src" / "slidemage"
    changelog = (package / "CHANGELOG.md").read_bytes().decode()
    assert changelog.endswith("- Old bullet.\r\n\r\n" + entry.replace("\n", "\r\n") + "\r\n")
    assert "\n" not in changelog.replace("\r\n", "")
    assert [e.version for e in version.parse_history(changelog.replace("\r\n", "\n"))] == ["v0.17.38", number]
    assert f'VERSION_NUMBER = "{number}"' in (package / "version.py").read_text(encoding="utf-8")
    assert [p.name for p in (root / "changes").iterdir()] == ["README.md"]
    sample = (package / "compat_sample.py").read_text(encoding="utf-8")
    assert 'since="v0.18.0"' in sample and "since='v0.1.0'" in sample and "NEXT" not in sample


def test_without_a_summary_the_counts_stand_in(tmp_path):
    root = tree(tmp_path, {"fix.md": FIX, "feature.md": FEATURE})
    _previous, number, entry, _fragments = prepare(root)
    assert number == "v0.17.39"
    assert entry.startswith("v0.17.39 (2026-11-21, release of 2 changes): This release has 1 new, 1 fixed changes.")
    # the one fragment with a summary gives the release's NEW: summary
    assert make_release.history_entry(entry).summary == "Background previews start sooner."


def test_no_fragments_or_a_bad_fragment_stop_the_release(tmp_path):
    with pytest.raises(make_release.ReleaseError, match="nothing to release"):
        prepare(tree(tmp_path / "a", {}))
    with pytest.raises(make_release.ReleaseError, match="kind is"):
        prepare(tree(tmp_path / "b", {"fix.md": FIX.replace("kind: fixed", "kind: patch")}))


def test_a_breaking_release_without_breaking_paragraph_is_refused():
    entry = "v0.18.0 (2026-11-21, x): Text.\n\nNEW:\n- Bullet."
    with pytest.raises(make_release.ReleaseError, match="BREAKING"):
        make_release.notes("v0.18.0", "v0.17.38", entry)


def _repo_with_origin(tmp_path, branch):
    import subprocess

    def git(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", branch, cwd=origin)
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x",
        cwd=origin)
    git("clone", "-q", str(origin), str(tmp_path / "clone"), cwd=tmp_path)
    return tmp_path / "clone"


@pytest.mark.parametrize("branch", ["develop", "main"])
def test_releases_use_the_default_branch_of_origin(tmp_path, branch):
    assert make_release.default_branch(_repo_with_origin(tmp_path, branch)) == branch


def test_without_origin_head_releases_use_develop(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    assert make_release.default_branch(tmp_path) == "develop"
