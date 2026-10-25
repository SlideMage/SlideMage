# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_names: the project files and names of the Slidemaster -> SlideMage rename."""
from __future__ import annotations

from pathlib import Path

from slidemage import compat, compat_names, fileio, project
from slidemage.compat import Pending

OLD_TEMPLATE = (
    "% SlideMage template name: University of Graz\n"
    "% Slidemaster preamble variant for Graz\n"
    "\\definecolor{c_primary_dark}{HTML}{3A4A5A}\n"
    "\\input{Slidemaster_preamble_base}\n"
    "\\input{Slidemaster_project_macros}\n")
OLD_DECK = (
    "\\documentclass[aspectratio=169]{beamer}\n"
    "\\usetheme{gotham}\n"
    "\\input{Slidemaster_preamble_uni-graz}\n"
    "\\SMUseBibliography[Slidemaster.bib]\n"
    "\\IfFileExists{Slidemaster.bib}{\\addbibresource{Slidemaster.bib}}{\\addbibresource{../Slidemaster.bib}}\n"
    "\\begin{document}\n\\end{document}\n")
OLD_RC = (
    "# the Slidemaster framework (Slidemaster_alt.lua) lives in $SLIDEMASTER_LATEX\n"
    "my $slidemaster_latex = $ENV{'SLIDEMASTER_LATEX'} // (dirname($abs_rc) . '/../SlideMage/latex');\n")
BIB = "% Master bibliography for Slidemaster decks\r\n@book{a, title={T}}\r\n"


def make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for sub in ("decks", "decks/archive", "slides", ".slidemage"):
        (root / sub).mkdir(parents=True)
    (root / project.MARKER).write_text('"id"\r\n', encoding="utf-8")
    (root / "Slidemaster_preamble_uni-graz.tex").write_bytes(OLD_TEMPLATE.replace("\n", "\r\n").encode())
    (root / "Slidemaster_project_macros.tex").write_bytes(b"\\newcommand{\\X}{x}\n")
    (root / "Slidemaster.bib").write_bytes(BIB.encode())
    (root / "decks" / "course.tex").write_bytes(OLD_DECK.encode())
    (root / "decks" / "archive" / "old.tex").write_bytes(OLD_DECK.replace("uni-graz", "slidemage").encode())
    (root / "decks" / "_slidemage_preview-x.tex").write_bytes(OLD_DECK.encode())
    (root / "decks" / ".latexmkrc").write_bytes(OLD_RC.encode())
    (root / ".latexmkrc").write_bytes(OLD_RC.encode())
    (root / ".slidemage" / "extra.json").write_text('{"bibliography": "Slidemaster.bib"}', encoding="utf-8")
    (root / ".scripts").mkdir()
    (root / ".scripts" / "add_deck_headers.py").write_text('os.environ.setdefault("SLIDEMASTER_PROJECT", "x")\n', encoding="utf-8")
    (root / "slides" / "1aa-EN-Slide-current.tex").write_bytes(b"% see Slidemaster_preamble_base.tex\n")
    return root


def update(root: Path):
    return compat.run_update(root, [Pending(compat_names.CHANGE)])


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".slidemage/backups" not in p.as_posix()}


def test_change_is_registered_as_breaking():
    change = next(c for c in compat.CHANGES if c.id == "slidemage-names-and-setup-layer")
    assert change.severity == compat.BREAKS and change.since == "v9.0.0"
    assert change.detect is not None and change.migrate is not None


def test_detect_names_every_file_that_changes(tmp_path):
    root = make_project(tmp_path)
    files = {f.file for f in compat_names.detect(root)}
    assert files == {"Slidemaster_preamble_uni-graz.tex", "Slidemaster_project_macros.tex", "Slidemaster.bib",
                     "decks/course.tex", "decks/archive/old.tex", "decks/.latexmkrc", ".latexmkrc",
                     ".slidemage/extra.json", ".scripts/add_deck_headers.py"}
    # regenerated wrappers and slides are not part of it
    assert not any("_slidemage_preview" in f or f.startswith("slides/") for f in files)


def test_migrate_renames_and_rewrites(tmp_path):
    root = make_project(tmp_path)
    done = update(root)
    assert not done.errors and done.backup is not None
    after = tree(root)
    assert "Slidemaster_preamble_uni-graz.tex" not in after and "Slidemaster.bib" not in after
    assert "Slidemaster_project_macros.tex" not in after
    assert after["SlideMage.bib"] == BIB.encode()                  # a bibliography moves byte for byte
    assert after["SlideMage_project_macros.tex"] == b"\\newcommand{\\X}{x}\n"
    template = after["SlideMage_template_uni-graz.tex"].decode()
    assert "\\input{SlideMage_base}\r\n\\input{SlideMage_project_macros}\r\n" in template   # CRLF kept
    assert "% Slidemaster preamble variant" in template                                     # comments stay
    deck = after["decks/course.tex"].decode()
    assert "\\input{SlideMage_template_uni-graz}" in deck and "\\usetheme{gotham}" in deck
    assert "\\SMUseBibliography[SlideMage.bib]" in deck
    assert "\\IfFileExists{SlideMage.bib}{\\addbibresource{SlideMage.bib}}{\\addbibresource{../SlideMage.bib}}" in deck
    assert "\\input{SlideMage_template_slidemage}" in after["decks/archive/old.tex"].decode()
    rc = after[".latexmkrc"].decode()
    assert "$ENV{'SLIDEMAGE_LATEX'}" in rc and "$slidemage_latex" in rc and "SlideMage_alt.lua" in rc
    assert b'"SLIDEMAGE_PROJECT"' in after[".scripts/add_deck_headers.py"]
    assert after[".slidemage/extra.json"] == b'{"bibliography": "SlideMage.bib"}'
    assert after["decks/_slidemage_preview-x.tex"].decode() == OLD_DECK               # left to be regenerated
    assert after["slides/1aa-EN-Slide-current.tex"] == b"% see Slidemaster_preamble_base.tex\n"
    assert compat_names.detect(root) == []


def test_old_files_are_backed_up_before_they_go(tmp_path):
    root = make_project(tmp_path)
    done = update(root)
    assert (done.backup / "Slidemaster.bib").read_bytes() == BIB.encode()
    assert (done.backup / "Slidemaster_preamble_uni-graz.tex").is_file()
    assert (done.backup / "decks" / "course.tex").read_bytes() == OLD_DECK.encode()
    assert "Slidemaster.bib" in done.changed and "SlideMage.bib" in done.changed


def test_migration_is_idempotent(tmp_path):
    root = make_project(tmp_path)
    update(root)
    once = tree(root)
    assert compat_names.migrate(root) == {}
    again = update(root)
    assert again.changed == [] and again.backup is None and tree(root) == once


def test_dry_run_changes_nothing(tmp_path):
    root = make_project(tmp_path)
    before = tree(root)
    done = compat.run_update(root, [Pending(compat_names.CHANGE)], dry_run=True)
    assert "SlideMage.bib" in done.changed and tree(root) == before


def test_template_with_unknown_slidemaster_code_is_reported_and_left_alone(tmp_path):
    root = make_project(tmp_path)
    odd = root / "Slidemaster_preamble_odd.tex"
    odd.write_bytes(b"\\input{Slidemaster_preamble_base}\n\\input{Slidemaster_layout}\n")
    deck = root / "decks" / "odd.tex"
    deck.write_bytes(b"\\input{Slidemaster_preamble_odd}\n\\SMUseBibliography[Slidemaster.bib]\n")
    update(root)
    assert odd.is_file() and odd.read_bytes().startswith(b"\\input{Slidemaster_preamble_base}")
    assert not (root / "SlideMage_template_odd.tex").exists()
    assert deck.read_bytes().startswith(b"\\input{Slidemaster_preamble_odd}")        # its key stays
    assert b"SlideMage.bib" in deck.read_bytes()                                    # the rest of the deck does not
    reported = {(f.file, f.line) for f in compat_names.detect(root)}
    assert ("Slidemaster_preamble_odd.tex", 2) in reported and ("decks/odd.tex", 1) in reported
    assert (root / "SlideMage_template_uni-graz.tex").is_file()                      # other templates went through


def test_a_taken_new_name_blocks_that_rename(tmp_path):
    root = make_project(tmp_path)
    (root / "SlideMage.bib").write_bytes(b"@book{mine}\n")
    update(root)
    assert (root / "Slidemaster.bib").read_bytes() == BIB.encode()
    assert (root / "SlideMage.bib").read_bytes() == b"@book{mine}\n"
    assert b"Slidemaster.bib" in (root / "decks" / "course.tex").read_bytes()         # still points at the old file
    assert any("exists already" in f.message for f in compat_names.detect(root))
    assert (root / "SlideMage_template_uni-graz.tex").is_file()


def test_a_failed_write_puts_everything_back(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    before = tree(root)
    real, calls = fileio.atomic_write, []

    def failing(path, data, *args, **kwargs):
        calls.append(path)
        if len(calls) == 4:
            raise OSError("disk full")
        return real(path, data, *args, **kwargs)

    monkeypatch.setattr(compat, "atomic_write", failing)
    done = update(root)
    assert done.errors and "put back" in done.errors[0] and done.changed == []
    assert tree(root) == before


def test_command_line_fix_runs_the_rename(tmp_path, capsys):
    root = make_project(tmp_path)
    project.write_project_json(root, {"format": project.PROJECT_FORMAT, "last_app_version": "v8.0.0",
                                      "highest_app_version": "v8.0.0", "compat": {"checked_version": "v8.0.0"}})
    pending = compat.evaluate(root, "v9.0.0")
    assert [p.change.id for p in pending.loud] == ["slidemage-names-and-setup-layer"]
    assert compat.run_update(root, pending.loud).errors == []
    assert not compat.evaluate(root, "v9.0.0").loud


def test_old_environment_variables_are_reported_and_ignored(tmp_path, monkeypatch, capsys):
    root = make_project(tmp_path)
    for name in ("SLIDEMASTER_LATEX", "SLIDEMAGE_LATEX", "SLIDEMASTER_PROJECT", "SLIDEMAGE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(project, "_legacy_env_warned", False)
    assert project.legacy_env_notes() == []
    monkeypatch.setenv("SLIDEMASTER_LATEX", "D:/fw")
    monkeypatch.setenv("SLIDEMASTER_PROJECT", "D:/p")
    monkeypatch.setenv("SLIDEMAGE_PROJECT", str(root))              # the new name wins: nothing to report for it
    notes = compat.evaluate(root, "v9.0.0").environment_notes
    assert len(notes) == 1 and "$SLIDEMASTER_LATEX" in notes[0] and "$SLIDEMAGE_LATEX" in notes[0]
    assert "$SLIDEMASTER_LATEX" in compat.report_markdown(root, compat.evaluate(root, "v9.0.0"), "v9.0.0")
    assert project.discover() == root.resolve()
    project.warn_legacy_env_vars()
    project.warn_legacy_env_vars()
    assert capsys.readouterr().err.count("SLIDEMASTER_LATEX") == 1
