# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The compatibility changes of bibliography_house.py / compat_bibliography.py:

- "bibliography-in-template": decks that carry their own copy of the house
  citation format move to SMUseBibliography, and the format goes into the
  deck's template file -- as bibliography_house.BLOCK (the one line that
  \\input{}s latex/SlideMage_bibliography_default.tex) since v10.14.0; a
  template already carrying the pre-v10.14.0 full copy is left as it is.
- "bibliography-default-file": the separate, optional change that offers to
  shorten a project template still carrying that full copy."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from slidemage import bibliography_house, compat, compat_bibliography, project

BS = chr(92)
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 7, 12, 0, 0)

FULL_TEXT = bibliography_house.FULL_TEXT
BLOCK = bibliography_house.BLOCK


def deck_copy(extra_comment: str = "% Bibliography (biblatex + biber) -- copied from FM2.\n") -> str:
    """What a course deck used to carry: the options, the lookup, the style."""
    lines = compat_bibliography._house_deck_code()
    return extra_comment + "\n".join(lines) + "\n"


def deck(template: str, body: str) -> str:
    return (BS + "documentclass{beamer}\n" + BS + "input{SlideMage_template_" + template + "}\n\n"
            + body + "\n" + BS + "newcommand{" + BS + "FooterText}{x}\n" + BS + "begin{document}\n"
            + BS + "end{document}\n")


def make(tmp_path: Path, framework_ready=True) -> Path:
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    project.write_project_json(root, {
        "format": project.PROJECT_FORMAT, "last_app_version": "v5.31.1",
        "highest_app_version": "v5.31.1", "compat": {"checked_version": "v5.31.1"}})
    latex = tmp_path / "latex"
    latex.mkdir()
    base = BS + "newcommand{" + BS + "x}{}\n"
    if framework_ready:
        base += BS + "newcommand{" + BS + "SMUseBibliography}[1][SlideMage.bib]{}\n"
    (latex / "SlideMage_base.tex").write_text(base, encoding="utf-8")
    (latex / "SlideMage_template_slidemage.tex").write_text(
        BS + "input{SlideMage_base}\n\n" + FULL_TEXT, encoding="utf-8")
    (root / "SlideMage_template_acme.tex").write_bytes(
        (BS + "usetheme{gotham}\r\n" + BS + "input{SlideMage_base}\r\n"
         + "% This project's own macros.\r\n"
         + BS + "input{SlideMage_project_macros}\r\nmore\r\n").encode())
    d = root / "decks"
    (d / "a.tex").write_bytes(deck("acme", deck_copy()).replace("\n", "\r\n").encode())
    (d / "b.tex").write_text(deck("acme", deck_copy().replace(BS + "addperiod", BS + "addsemicolon", 1)),
                             encoding="utf-8")
    (d / "c.tex").write_text(deck("slidemage", deck_copy("")), encoding="utf-8")
    (d / "d.tex").write_text(deck("acme", "% no references here"), encoding="utf-8")
    return root


def test_a_deck_with_the_house_copy_is_found_and_a_variant_is_not(tmp_path):
    root = make(tmp_path)
    findings = compat_bibliography.detect(root)
    assert [f.file for f in findings] == ["decks/a.tex", "decks/c.tex"]
    assert findings[0].line > 1 and "copy of the house citation format" in findings[0].message


def test_it_is_a_dialog_change_that_updates_automatically(tmp_path):
    root = make(tmp_path)
    ev = compat.evaluate(root, "v5.32.0")
    ids = [p.change.id for p in ev.loud]
    assert "bibliography-in-template" in ids and ev.can_update
    assert not [p for p in ev.quiet if p.change.id == "bibliography-in-template"]
    # a project that was last used with this release is not told
    project.write_project_json(root, {**project.read_project_json(root),
                                      "compat": {"checked_version": "v5.32.0"}})
    assert not compat.evaluate(root, "v5.32.0").everything


def test_update_replaces_the_copy_adds_the_format_to_the_template_and_backs_up(tmp_path):
    root = make(tmp_path)
    before_b = (root / "decks" / "b.tex").read_bytes()
    before_a = (root / "decks" / "a.tex").read_bytes()
    ev = compat.evaluate(root, "v5.32.0")
    pending = [p for p in ev.loud if p.change.id == "bibliography-in-template"]

    done = compat.run_update(root, pending, now=NOW)
    assert not done.errors
    assert sorted(done.changed) == ["SlideMage_template_acme.tex", "decks/a.tex", "decks/c.tex"]

    a = (root / "decks" / "a.tex").read_bytes().decode()
    assert a.count(BS + "SMUseBibliography") == 2            # once in the comment, once as the call
    assert "DeclareBibliographyDriver" not in a and BS + "usepackage[style" not in a
    assert "\r\n" in a and "\n" not in a.replace("\r\n", "")  # line endings kept
    assert (root / "decks" / "b.tex").read_bytes() == before_b          # the variant is left alone
    tpl = (root / "SlideMage_template_acme.tex").read_bytes().decode()
    assert tpl.index("SlideMage_project_macros") < tpl.index(BS + "input{SlideMage_bibliography_default}") < tpl.index("more")
    assert "\r\n" in tpl and BLOCK.rstrip("\n") in tpl
    assert "DeclareBibliographyDriver" not in tpl           # the one line, not the full copy
    assert (done.backup / "decks" / "a.tex").read_bytes() == before_a
    assert (done.backup / "SlideMage_template_acme.tex").is_file()
    assert not (done.backup / "decks" / "b.tex").exists()

    # idempotent, and nothing is pending any more
    assert not compat.run_update(root, pending, now=NOW).changed
    assert not [f for f in compat_bibliography.detect(root)]
    assert not compat.evaluate(root, "v5.32.0").everything


def test_nothing_is_changed_while_the_framework_lacks_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("SLIDEMAGE_LATEX", raising=False)
    root = make(tmp_path, framework_ready=False)
    findings = compat_bibliography.detect(root)
    assert findings and "update it first" in findings[0].message
    assert compat_bibliography.migrate(root) == {}


def test_a_template_with_another_format_keeps_its_decks(tmp_path):
    root = make(tmp_path)
    (root / "SlideMage_template_acme.tex").write_text(
        BS + "input{SlideMage_base}\n" + BS + "renewcommand{" + BS + "SMBibliographyStyle}{" + BS
        + "relax}\n", encoding="utf-8")
    findings = compat_bibliography.detect(root)
    assert "another citation format" in findings[0].message
    plan = compat_bibliography.migrate(root)
    assert Path("decks/a.tex") not in plan and Path("decks/c.tex") in plan


def test_a_framework_template_using_the_default_input_line_is_also_ready(tmp_path):
    # Since v10.14.0 the shipped SlideMage template says the one line instead of
    # carrying the full copy (see tests/test_bibliography_template.py); detect/migrate
    # must treat that as "ready" just like the full copy.
    root = make(tmp_path)
    (tmp_path / "latex" / "SlideMage_template_slidemage.tex").write_text(
        BS + "input{SlideMage_base}\n\n" + BLOCK, encoding="utf-8")
    findings = compat_bibliography.detect(root)
    assert [f.file for f in findings] == ["decks/a.tex", "decks/c.tex"]
    plan = compat_bibliography.migrate(root)
    assert sorted(str(p) for p in plan) == sorted(
        ["SlideMage_template_acme.tex", str(Path("decks/a.tex")), str(Path("decks/c.tex"))])
    assert BS + "SMUseBibliography" in plan[Path("decks/c.tex")].decode()


def test_shorten_finds_a_project_templates_full_copy_and_migrate_replaces_it(tmp_path):
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    tpl = root / "SlideMage_template_acme.tex"
    tpl.write_bytes((BS + "input{SlideMage_base}\r\n\r\n" + FULL_TEXT).replace("\n", "\r\n").encode())

    findings = compat_bibliography.detect_shorten(root)
    assert len(findings) == 1
    assert findings[0].file == "SlideMage_template_acme.tex" and findings[0].line > 1
    assert "full house citation format" in findings[0].message

    plan = compat_bibliography.migrate_shorten(root)
    assert list(plan) == [Path("SlideMage_template_acme.tex")]
    new_text = plan[Path("SlideMage_template_acme.tex")].decode()
    assert "\r\n" in new_text
    assert BS + "input{SlideMage_bibliography_default}" in new_text
    assert "DeclareBibliographyDriver" not in new_text and BS + "renewcommand{" + BS + "SMBiblatexOptions}" not in new_text
    assert new_text.startswith(BS + "input{SlideMage_base}")

    tpl.write_bytes(new_text.encode())
    assert compat_bibliography.detect_shorten(root) == []    # idempotent
    assert compat_bibliography.migrate_shorten(root) == {}


def test_shorten_leaves_a_template_with_no_format_or_another_format_alone(tmp_path):
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    (root / "SlideMage_template_acme-two.tex").write_text(
        BS + "input{SlideMage_base}\nmore\n", encoding="utf-8")                # no format at all
    (root / "SlideMage_template_other.tex").write_text(
        BS + "input{SlideMage_base}\n" + BS + "renewcommand{" + BS + "SMBiblatexOptions}{x}\n"
        + BS + "renewcommand{" + BS + "SMBibliographyStyle}{" + BS + "relax}\n", encoding="utf-8")
    (root / "SlideMage_template_slidemage.tex").write_text(
        BS + "input{SlideMage_base}\n\n" + BLOCK, encoding="utf-8")            # already the one line
    assert compat_bibliography.detect_shorten(root) == []
    assert compat_bibliography.migrate_shorten(root) == {}


def test_shorten_is_registered_as_its_own_dialog_change(tmp_path):
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    project.write_project_json(root, {
        "format": project.PROJECT_FORMAT, "last_app_version": "v10.13.0",
        "highest_app_version": "v10.13.0", "compat": {"checked_version": "v10.13.0"}})
    (root / "SlideMage_template_acme.tex").write_text(
        BS + "input{SlideMage_base}\n\n" + FULL_TEXT, encoding="utf-8")

    ev = compat.evaluate(root, "v10.14.0")
    ids = [p.change.id for p in ev.loud]
    assert "bibliography-default-file" in ids and ev.can_update

    pending = [p for p in ev.loud if p.change.id == "bibliography-default-file"]
    done = compat.run_update(root, pending, now=NOW)
    assert not done.errors and done.changed == ["SlideMage_template_acme.tex"]
    assert not compat_bibliography.detect_shorten(root)
    assert not compat.run_update(root, pending, now=NOW).changed    # idempotent


def test_the_shipped_templates_carry_the_house_format_one_way_or_the_other():
    slidemage = (ROOT / "latex" / "SlideMage_template_slidemage.tex").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert BLOCK.rstrip("\n") in slidemage and "DeclareBibliographyDriver" not in slidemage
    default_file = (ROOT / "latex" / "SlideMage_bibliography_default.tex").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert FULL_TEXT in default_file
