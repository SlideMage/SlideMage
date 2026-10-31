# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_project_macros: the framework loads the project's macros itself (v0.12.0); the line in a template goes."""
from __future__ import annotations

from slidemage import compat_project_macros as cpm

BS = chr(92)
LINE = BS + "input{SlideMage_project_macros}"


def _root(tmp_path, template: bytes):
    (tmp_path / "SlideMage_template_acme.tex").write_bytes(template)
    return tmp_path


def test_a_template_without_the_line_is_left_alone(tmp_path):
    root = _root(tmp_path, (BS + "input{SlideMage_base}\n" + BS + "input{SlideMage_bibliography_default}\n").encode())
    assert cpm.detect(root) == [] and cpm.migrate(root) == {}


def test_a_commented_line_is_not_a_hit(tmp_path):
    root = _root(tmp_path, ("% " + LINE + "\n").encode())
    assert cpm.detect(root) == [] and cpm.migrate(root) == {}


def test_the_line_and_its_introducing_comment_are_found_and_removed_with_crlf_kept(tmp_path):
    text = ("% other note\r\n" + BS + "input{SlideMage_base}\r\n\r\n% This project's own macros.\r\n" + LINE
            + "\r\n\r\n" + BS + "input{SlideMage_bibliography_default}\r\n")
    root = _root(tmp_path, text.encode())
    found = cpm.detect(root)
    assert [(f.file, f.line) for f in found] == [("SlideMage_template_acme.tex", 5)]
    new = cpm.migrate(root)[__import__("pathlib").Path("SlideMage_template_acme.tex")].decode()
    assert "project_macros" not in new and "own macros" not in new
    assert new == ("% other note\r\n" + BS + "input{SlideMage_base}\r\n\r\n\r\n" + BS
                   + "input{SlideMage_bibliography_default}\r\n")


def test_a_comment_that_is_not_about_the_macros_stays_and_the_tex_suffix_form_is_found(tmp_path):
    text = "% unrelated\n" + BS + "input{SlideMage_project_macros.tex} % tail\nmore\n"
    root = _root(tmp_path, text.encode())
    assert len(cpm.detect(root)) == 1
    new = cpm.migrate(root)[__import__("pathlib").Path("SlideMage_template_acme.tex")].decode()
    assert new == "% unrelated\nmore\n"
