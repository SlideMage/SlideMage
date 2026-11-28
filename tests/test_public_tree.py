# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "public_tree.py"
_spec = importlib.util.spec_from_file_location("public_tree", _PATH)
public_tree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(public_tree)


def test_the_internal_documents_and_claude_folder_are_left_out():
    keep, drop = public_tree.split(["src/slidemage/app.py", "docs/SlideMage.md", "docs/plans/x.md",
                                    "docs/Code_Review_2026-11-24-v1.0.md", ".claude/skills/finish/SKILL.md",
                                    "docs/design-handbook/README.md", "docs/handover_list.py", "README.md"])
    assert keep == ["src/slidemage/app.py", "docs/SlideMage.md", "docs/design-handbook/README.md", "README.md"]
    assert drop == ["docs/plans/x.md", "docs/Code_Review_2026-11-24-v1.0.md", ".claude/skills/finish/SKILL.md",
                    "docs/handover_list.py"]


def test_every_kept_document_exists():
    tracked = public_tree.tracked()
    for keep in public_tree.DOCS_KEPT:
        assert any(p == keep or (keep.endswith("/") and p.startswith(keep)) for p in tracked), keep


def test_private_paths_are_found_and_placeholders_are_not():
    text = "a D:/Out/Handout.pdf\nb D:/Dropbox/repos/x\nc D:/uniCLOUD/x\nd D:/Cloud/x\ne D:\\Dropbox\\repos\\y\n"
    assert [hit.split(":")[1] for hit in public_tree.private_hits("f.md", text)] == ["2", "3", "5"]


def test_personal_patterns_come_from_the_git_folder(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".git" / "public_tree_patterns.txt").write_text("# mine\nhost42\n", encoding="utf-8")
    pattern = public_tree.private_pattern(tmp_path)
    assert pattern.search("on HOST42 today") and pattern.search("D:/uniCLOUD") and not pattern.search("D:/Out")
    assert not pattern.search("# mine")


def test_links_to_left_out_files_are_found():
    dropped, kept = {"docs/plans/a.md", "docs/x.json"}, {"docs/SlideMage.md", "docs/design-handbook/README.md"}
    text = ("[a](plans/a.md) [b](SlideMage.md#top) [c](x.json) [d](https://example.org/plans/a.md) "
            "[e](plans/) [f](design-handbook/)")
    assert public_tree.broken_links("docs/PROJECT_OVERVIEW.md", text, dropped, kept) == [
        "docs/PROJECT_OVERVIEW.md: links to left-out docs/plans/a.md",
        "docs/PROJECT_OVERVIEW.md: links to left-out docs/x.json",
        "docs/PROJECT_OVERVIEW.md: links to left-out docs/plans"]


def test_export_writes_only_the_kept_files(tmp_path):
    repo = tmp_path / "repo"
    for name in ("README.md", "docs/SlideMage.md", "docs/plans/p.md", ".claude/skills/s.md"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=repo, check=True)
    assert public_tree.export(tmp_path / "out", root=repo) == 2
    written = sorted(p.relative_to(tmp_path / "out").as_posix() for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert written == ["README.md", "docs/SlideMage.md"]
