# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_color_cut (v0.16.0): the dark switch \\SMDarkMode becomes the mode line; installed themes that still use it
are refused."""
from __future__ import annotations

from pathlib import Path

import pytest

from slidemage import compat, compat_color_cut as m, packages, project, themes
from slidemage.compat import Pending

OLD = r"\newcommand{\SMDarkMode}{}"
NEW = r"\newcommand{\SMModeOverride}{dark}"
TEMPLATE = r"\input{SlideMage_template_uni-graz}"


@pytest.mark.parametrize("before, after", [
    (OLD + "\n" + TEMPLATE + "\n", NEW + "\n" + TEMPLATE + "\n"),
    (r"\def\SMDarkMode{}" + "\r\n" + TEMPLATE + "\r\n", NEW + "\r\n" + TEMPLATE + "\r\n"),
    (r"\providecommand\SMDarkMode{x} \def\x{y}" + "\n" + TEMPLATE, NEW + r" \def\x{y}" + "\n" + TEMPLATE),
    # a mode line was already there and always won: the switch just goes, with its line
    (r"\newcommand{\SMModeOverride}{gray}" + "\n" + OLD + "\n" + TEMPLATE,
     r"\newcommand{\SMModeOverride}{gray}" + "\n" + TEMPLATE),
    # two switches: one mode line
    (OLD + "\n" + OLD + "\n" + TEMPLATE, NEW + "\n" + TEMPLATE),
    # a comment stays as it is
    ("% " + OLD + "\n" + TEMPLATE, "% " + OLD + "\n" + TEMPLATE),
])
def test_a_deck_gets_the_mode_line(before, after):
    assert m.rewrite_deck(before) == after
    assert m.rewrite_deck(after) == after


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for sub in ("decks/archive", "slides", "snippets"):
        (root / sub).mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\n', encoding="utf-8")
    deck = OLD + "\n" + TEMPLATE + "\n\\begin{document}\n\\end{document}\n"
    for rel in ("decks/a.tex", "decks/archive/b.tex", "decks/_slidemage_preview.tex"):
        (root / rel).write_text(deck, encoding="utf-8")
    (root / "SlideMage_template_mine.tex").write_text(
        "% SlideMage dark mode: true\n\\input{SlideMage_setup}\n\\ifdefined\\SMDarkMode\n\\colorlet{c_primary_dark}{white}\n"
        "\\fi\n\\input{SlideMage_base}\n", encoding="utf-8")
    (root / "slides" / "aaa-EN-A-current.tex").write_text("% \\SMDarkMode in a comment\n", encoding="utf-8")
    return root


def test_detect_lists_decks_and_reports_templates_by_line(tmp_path):
    root = make_project(tmp_path)
    found = {(f.file, f.line) for f in m.detect(root)}
    assert found == {("decks/a.tex", 1), ("decks/archive/b.tex", 1),
                     ("SlideMage_template_mine.tex", 1), ("SlideMage_template_mine.tex", 3)}


def test_update_project_rewrites_decks_and_leaves_the_template_reported(tmp_path):
    root = make_project(tmp_path)
    change = next(c for c in compat.CHANGES if c.id == m.CHANGE_ID)
    assert change.since == "v0.16.0" and change.severity == compat.BREAKS
    compat.run_update(root, [Pending(change, m.detect(root))])
    assert (root / "decks/a.tex").read_text(encoding="utf-8").startswith(NEW + "\n")
    assert (root / "decks/archive/b.tex").read_text(encoding="utf-8").startswith(NEW + "\n")
    assert OLD in (root / "decks/_slidemage_preview.tex").read_text(encoding="utf-8")   # regenerated, untouched
    assert not m.migrate(root)
    assert {f.file for f in m.detect(root)} == {"SlideMage_template_mine.tex"}


def theme_folder(base: Path, template: str) -> Path:
    folder = base / "uni-x"
    folder.mkdir(parents=True)
    (folder / "theme.toml").write_text(
        'id = "uni-x"\nname = "X"\nversion = "1.0.0"\nrequires_slidemage = ">=0.1.0"\nsummary = "x"\n'
        'author = "a"\nhomepage = "https://example.org"\nlicense = "MIT"\nlayout = "fira"\n', encoding="utf-8")
    (folder / "SlideMage_template_uni-x.tex").write_text(template, encoding="utf-8")
    for name in ("README.md", "CHANGELOG.md", "LICENSE"):
        (folder / name).write_text("x\n", encoding="utf-8")
    return folder


def test_an_installed_theme_that_still_uses_the_switch_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "themes_dir", lambda: tmp_path / "themes")
    monkeypatch.setattr(themes, "KIND", themes.KIND.__class__(**{**vars(themes.KIND), "folder": lambda: tmp_path / "themes"}))
    folder = theme_folder(tmp_path / "themes", "\\input{SlideMage_setup}\n\\ifdefined\\SMDarkMode\\fi\n")
    listed = packages.installed(themes.KIND)
    assert listed[0].needs_update and "before v0.16.0" in listed[0].problem
    assert packages.installed_dirs(themes.KIND) == []
    with pytest.raises(themes.ThemeError, match="before v0.16.0"):
        packages.check_folder(themes.KIND, folder)
    # the updated theme (a comment may still name the switch)
    (folder / "SlideMage_template_uni-x.tex").write_text(
        "% no \\SMDarkMode any more\n\\input{SlideMage_setup}\n\\SMDeclareMode{light}{}\n", encoding="utf-8")
    listed = packages.installed(themes.KIND)
    assert not listed[0].problem and not listed[0].needs_update
    assert packages.installed_dirs(themes.KIND) == [folder]
    packages.check_folder(themes.KIND, folder)
