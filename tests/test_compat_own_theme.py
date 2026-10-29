# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_own_theme: the project files of the gotham... -> SM... rename (content names and the theme's own names)."""
from __future__ import annotations

from pathlib import Path

from slidemage import compat, compat_names, compat_own_theme, project
from slidemage.compat import Pending

SLIDE = ("\\begin{standardframe}{T}\n\\begin{gothamtable}[gap=12pt]{lcc}\\end{gothamtable}\n"
         "\\begin{tikzpicture}[gotham arrow, gotham highlight]\\end{tikzpicture}\n"
         "\\begin{gothamnumitemize}\\item a\\end{gothamnumitemize}\n"
         "\\fill (0,0) rectangle (2\\gothamFrametitleRightpading,1);\n\\end{standardframe}\n")
NEW_SLIDE = ("\\begin{standardframe}{T}\n\\begin{SMTable}[gap=12pt]{lcc}\\end{SMTable}\n"
             "\\begin{tikzpicture}[SMArrow, SMHighlight]\\end{tikzpicture}\n"
             "\\begin{SMNumItemize}\\item a\\end{SMNumItemize}\n"
             "\\fill (0,0) rectangle (2\\SMFrametitleRightPadding,1);\n\\end{standardframe}\n")
MIGRATED = ("slides/1aa-EN-Slide-current.tex", "slides/1aa-EN-Slide-v1-0-0.tex", "snippets/1aa-1.tex",
            "decks/course.tex", "decks/archive/old.tex", "SlideMage_template_x.tex", "SlideMage_project_macros.tex")


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for sub in ("decks/archive", "slides/.backups", "snippets", ".slidemage/backups/x"):
        (root / sub).mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    for rel in MIGRATED:
        (root / rel).write_bytes(SLIDE.replace("\n", "\r\n").encode())
    for rel in ("slides/.backups/1aa-EN-Slide-current.tex", "decks/_slidemage_preview-x.tex",
                ".slidemage/backups/x/s.tex"):
        (root / rel).write_bytes(SLIDE.encode())
    (root / "slides" / "1bb-EN-Clean-current.tex").write_bytes(NEW_SLIDE.encode())
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".slidemage/backups" not in p.as_posix()}


def update(root: Path):
    return compat.run_update(root, [Pending(compat_own_theme.CHANGE)])


def test_change_is_registered_as_breaking():
    change = next(c for c in compat.CHANGES if c.id == "own-theme-and-content-names")
    assert change.severity == compat.BREAKS and change.since == "v10.1.0"
    assert change.detect is not None and change.migrate is not None


def test_detect_lists_current_frozen_snippet_deck_and_template_files(tmp_path):
    root = make_project(tmp_path)
    assert {f.file for f in compat_own_theme.detect(root)} == set(MIGRATED)


def test_migrate_renames_everywhere_keeping_line_endings_and_skipped_files(tmp_path):
    root = make_project(tmp_path)
    before = tree(root)
    result = update(root)
    assert not result.errors and len(result.changed) == len(MIGRATED)
    after = tree(root)
    for rel in MIGRATED:
        assert after[rel] == NEW_SLIDE.replace("\n", "\r\n").encode()
    for rel in ("slides/.backups/1aa-EN-Slide-current.tex", "decks/_slidemage_preview-x.tex",
                "slides/1bb-EN-Clean-current.tex"):
        assert after[rel] == before[rel]
    assert compat_own_theme.detect(root) == []


def test_migrate_is_idempotent(tmp_path):
    root = make_project(tmp_path)
    update(root)
    once = tree(root)
    assert update(root).changed == []
    assert compat_own_theme.migrate(root) == {}
    assert tree(root) == once


def test_a_file_that_already_uses_a_new_name_is_reported_not_rewritten(tmp_path):
    root = make_project(tmp_path)
    path = root / "slides" / "1aa-EN-Slide-current.tex"
    mixed = SLIDE + "\\begin{SMTable}{l}\\end{SMTable}\n"
    path.write_text(mixed, encoding="utf-8")
    findings = [f for f in compat_own_theme.detect(root) if f.file == "slides/1aa-EN-Slide-current.tex"]
    assert len(findings) == 1 and "SMTable" in findings[0].message and "not rewritten" in findings[0].message
    update(root)
    assert path.read_text(encoding="utf-8") == mixed
    # a comment that names a new name is no collision
    path.write_text("% was SMTable\n" + SLIDE, encoding="utf-8")
    update(root)
    assert path.read_text(encoding="utf-8") == "% was SMTable\n" + NEW_SLIDE


def test_unknown_gotham_names_are_reported_and_the_rest_migrated(tmp_path):
    root = make_project(tmp_path)
    path = root / "slides" / "1aa-EN-Slide-current.tex"
    path.write_text(SLIDE + "\\SMCode{gothamfloating...block}\n% gothamwhatever\n", encoding="utf-8")
    messages = [(f.line, f.message) for f in compat_own_theme.detect(root) if f.file == "slides/1aa-EN-Slide-current.tex"]
    assert any(line == 7 and "gothamfloating" in msg for line, msg in messages)
    assert not any("gothamwhatever" in msg for _line, msg in messages)       # commented
    update(root)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(NEW_SLIDE) and "gothamfloating..." in text
    assert any("gothamfloating" in f.message for f in compat_own_theme.detect(root))   # stays reported


def test_runs_after_the_setup_change_in_one_update(tmp_path):
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    (root / "Slidemaster_preamble_x.tex").write_text(
        "\\setlength{\\gothamFrametitleRightpading}{0.28cm}\n\\input{Slidemaster_preamble_base}\n"
        "\\begin{gothamtable}{l}\\end{gothamtable}\n", encoding="utf-8")
    (root / "decks" / "course.tex").write_text(
        "\\documentclass{beamer}\n\\usetheme{gotham}\n\\input{Slidemaster_preamble_x}\n" + SLIDE, encoding="utf-8")
    result = compat.run_update(root, [Pending(compat_names.CHANGE), Pending(compat_own_theme.CHANGE)])
    assert not result.errors
    assert not (root / "Slidemaster_preamble_x.tex").exists()
    template = (root / "SlideMage_template_x.tex").read_text(encoding="utf-8")
    assert "\\input{SlideMage_setup}" in template and "SMTable" in template and "gotham" not in template
    deck = (root / "decks" / "course.tex").read_text(encoding="utf-8")
    assert "\\usetheme" not in deck and "SlideMage_template_x" in deck and NEW_SLIDE in deck
    assert compat_names.detect(root) == [] and compat_own_theme.detect(root) == []


THEME_TEMPLATE = (
    "\\setlength{\\SMLogoHeight}{3ex}\n"
    "\\addtolength{\\gothamFootlineVOffset}{-1.3pt}\n"
    "\\renewcommand{\\gothamInstituteLogoSquare}[1][\\SMLogoHeight]{\\includegraphics[height=#1]{logo.pdf}}\n"
    "\\renewcommand{\\gothamFrameSubtitleSep}{ -- }\n"
    "\\setlength{\\gothamFramesubtitleStrutend}{2pt}\n"
    "\\rule{0pt}{\\gotham@frametitlestrut@start}\\gotham@frametitlestrut@end\n"
    "\\setlength{\\gothamFrametitleLeftpading}{1ex}\n")
NEW_THEME_TEMPLATE = (
    "\\setlength{\\SMLogoHeight}{3ex}\n"
    "\\addtolength{\\SMFootlineVOffset}{-1.3pt}\n"
    "\\renewcommand{\\SMInstituteLogo}[1][\\SMLogoHeight]{\\includegraphics[height=#1]{logo.pdf}}\n"
    "\\renewcommand{\\SMFrameSubtitleSep}{ -- }\n"
    "\\setlength{\\SMFrameSubtitleStrutEnd}{2pt}\n"
    "\\rule{0pt}{\\SM@frametitlestrut@start}\\SM@frametitlestrut@end\n"
    "\\setlength{\\SMFrametitleLeftPadding}{1ex}\n")


def test_the_themes_own_names_are_renamed_in_templates_and_slides(tmp_path):
    root = make_project(tmp_path)
    for rel in ("SlideMage_template_x.tex", "slides/1aa-EN-Slide-current.tex"):
        (root / rel).write_text(THEME_TEMPLATE, encoding="utf-8")
    result = update(root)
    assert not result.errors
    for rel in ("SlideMage_template_x.tex", "slides/1aa-EN-Slide-current.tex"):
        assert (root / rel).read_text(encoding="utf-8") == NEW_THEME_TEMPLATE
    assert compat_own_theme.detect(root) == []


def test_gothamset_and_the_other_removed_theme_names_are_reported_not_rewritten(tmp_path):
    root = make_project(tmp_path)
    path = root / "SlideMage_template_x.tex"
    path.write_text(THEME_TEMPLATE + "\\gothamset{progressbar position=footline}\n\\setlength{\\gothamFooterHOffset}{1pt}\n"
                    "% \\gothamreset{x} is only a comment\n", encoding="utf-8")
    messages = [(f.line, f.message) for f in compat_own_theme.detect(root) if f.file == "SlideMage_template_x.tex"]
    gone = {line: msg for line, msg in messages if "gone with the Gotham theme" in msg}
    assert sorted(gone) == [8, 9] and "gothamset" in gone[8] and "gothamFooterHOffset" in gone[9]
    update(root)
    text = path.read_text(encoding="utf-8")
    # the rest of the file is migrated; the removed names stay where they are, and stay reported
    assert text.startswith(NEW_THEME_TEMPLATE) and "\\gothamset{progressbar" in text and "\\gothamFooterHOffset" in text
    assert [f.line for f in compat_own_theme.detect(root) if f.file == "SlideMage_template_x.tex"] == [8, 9]


def test_the_new_names_are_the_ones_the_theme_defines():
    theme = (Path(__file__).resolve().parents[1] / "latex" / "beamerthemeSlideMage.sty").read_text(encoding="utf-8")
    renames = compat_own_theme.sm_rename.THEME_RENAMES
    theme_names = [old for old in renames if old in compat_own_theme.sm_rename.THEME_NAMES
                   or old.startswith("gothamFrametitle")]
    assert len(theme_names) > 25
    for old in theme_names:
        assert renames[old] in theme, (old, renames[old])
