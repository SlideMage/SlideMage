# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The compatibility change "bibliography-in-template": decks that carry their
own copy of the house citation format move to SMUseBibliography, and the
format goes into the deck's template file."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from slidemage import bibliography_house, compat, compat_bibliography, project

BS = chr(92)
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 7, 12, 0, 0)

BLOCK = bibliography_house.BLOCK


def deck_copy(extra_comment: str = "% Bibliography (biblatex + biber) -- copied from FM2.\n") -> str:
    """What a course deck used to carry: the options, the lookup, the style."""
    lines = compat_bibliography._house_deck_code()
    return extra_comment + "\n".join(lines) + "\n"


def deck(template: str, body: str) -> str:
    return (BS + "documentclass{beamer}\n" + BS + "input{Slidemaster_preamble_" + template + "}\n\n"
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
        base += BS + "newcommand{" + BS + "SMUseBibliography}[1][Slidemaster.bib]{}\n"
    (latex / "Slidemaster_preamble_base.tex").write_text(base, encoding="utf-8")
    (latex / "Slidemaster_preamble_slidemage.tex").write_text(
        BS + "input{Slidemaster_preamble_base}\n\n" + BLOCK, encoding="utf-8")
    (root / "Slidemaster_preamble_uni-graz.tex").write_bytes(
        (BS + "usetheme{gotham}\r\n" + BS + "input{Slidemaster_preamble_base}\r\n"
         + "% This project's own macros.\r\n"
         + BS + "input{Slidemaster_project_macros}\r\nmore\r\n").encode())
    d = root / "decks"
    (d / "a.tex").write_bytes(deck("uni-graz", deck_copy()).replace("\n", "\r\n").encode())
    (d / "b.tex").write_text(deck("uni-graz", deck_copy().replace(BS + "addperiod", BS + "addsemicolon", 1)),
                             encoding="utf-8")
    (d / "c.tex").write_text(deck("slidemage", deck_copy("")), encoding="utf-8")
    (d / "d.tex").write_text(deck("uni-graz", "% no references here"), encoding="utf-8")
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
    assert sorted(done.changed) == ["Slidemaster_preamble_uni-graz.tex", "decks/a.tex", "decks/c.tex"]

    a = (root / "decks" / "a.tex").read_bytes().decode()
    assert a.count(BS + "SMUseBibliography") == 2            # once in the comment, once as the call
    assert "DeclareBibliographyDriver" not in a and BS + "usepackage[style" not in a
    assert "\r\n" in a and "\n" not in a.replace("\r\n", "")  # line endings kept
    assert (root / "decks" / "b.tex").read_bytes() == before_b          # the variant is left alone
    tpl = (root / "Slidemaster_preamble_uni-graz.tex").read_bytes().decode()
    assert tpl.index("Slidemaster_project_macros") < tpl.index(BS + "renewcommand{" + BS + "SMBibliographyStyle}") < tpl.index("more")
    assert "\r\n" in tpl and BLOCK.split("\n")[0] in tpl
    assert (done.backup / "decks" / "a.tex").read_bytes() == before_a
    assert (done.backup / "Slidemaster_preamble_uni-graz.tex").is_file()
    assert not (done.backup / "decks" / "b.tex").exists()

    # idempotent, and nothing is pending any more
    assert not compat.run_update(root, pending, now=NOW).changed
    assert not [f for f in compat_bibliography.detect(root)]
    assert not compat.evaluate(root, "v5.32.0").everything


def test_nothing_is_changed_while_the_framework_lacks_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("SLIDEMASTER_LATEX", raising=False)
    root = make(tmp_path, framework_ready=False)
    findings = compat_bibliography.detect(root)
    assert findings and "update it first" in findings[0].message
    assert compat_bibliography.migrate(root) == {}


def test_a_template_with_another_format_keeps_its_decks(tmp_path):
    root = make(tmp_path)
    (root / "Slidemaster_preamble_uni-graz.tex").write_text(
        BS + "input{Slidemaster_preamble_base}\n" + BS + "renewcommand{" + BS + "SMBibliographyStyle}{" + BS
        + "relax}\n", encoding="utf-8")
    findings = compat_bibliography.detect(root)
    assert "another citation format" in findings[0].message
    plan = compat_bibliography.migrate(root)
    assert Path("decks/a.tex") not in plan and Path("decks/c.tex") in plan


def test_the_shipped_templates_carry_exactly_the_block():
    for path in (ROOT / "latex" / "Slidemaster_preamble_slidemage.tex",
                 ROOT / "example" / "Slidemaster_preamble_uni-graz.tex"):
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert BLOCK in text, path.name
