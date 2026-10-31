# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""compat_setup: the setup-layer rewrites of templates and decks (v10.0.0)."""
from __future__ import annotations

from slidemage import compat_setup

TEMPLATE = (
    "% SlideMage template name: Test\n"
    "\n"
    "% Colors of the test university.\n"
    "\\definecolor{c_primary_dark}{HTML}{000000}\n"
    "\\newcommand{\\SMInstituteLogoPath}{logo.pdf}\n"
    "\\newcommand*\\SMTitleBoxColor{c_primary_dark}\n"
    "\\newlength\\SMLogoHeight % the logo\n"
    "\\setlength{\\SMLogoHeight}{2ex}\n"
    "\\setlength{\\gothamFrametitleRightpading}{0.3cm}\n"
    "%\\newcommand{\\SMBulletColor}{c_primary_dark}\n"
    "\\newcommand{\\MyOwnMacro}{x}\n"
    "\\input{SlideMage_base}\n")


def test_template_gets_the_setup_line_and_changes_settings_instead_of_creating_them():
    new, problem = compat_setup.template(TEMPLATE)
    assert problem is None
    assert new.startswith("% SlideMage template name: Test\n\n\\input{SlideMage_setup}\n\n% Colors of the test")
    assert "\\renewcommand{\\SMInstituteLogoPath}{logo.pdf}" in new
    assert "\\renewcommand*\\SMTitleBoxColor{c_primary_dark}" in new
    assert "\\newlength" not in new and "\\setlength{\\SMLogoHeight}{2ex}" in new
    assert "\\setlength{\\SMFrametitleRightPadding}{0.3cm}" in new
    assert "%\\newcommand{\\SMBulletColor}" in new              # comments are left alone
    assert "\\newcommand{\\MyOwnMacro}{x}" in new               # so are the template's own macros
    assert compat_setup.template(new) == (new, None)            # idempotent


def test_dark_mode_setting_stays_before_the_setup_line_and_crlf_is_kept():
    text = "\\newcommand{\\SMDarkMode}{}\r\n\\definecolor{c_primary_dark}{HTML}{000000}\r\n\\input{SlideMage_base}\r\n"
    new, problem = compat_setup.template(text)
    assert problem is None
    assert new == ("\\newcommand{\\SMDarkMode}{}\r\n\\input{SlideMage_setup}\r\n"
                   "\\definecolor{c_primary_dark}{HTML}{000000}\r\n\\input{SlideMage_base}\r\n")


def test_template_without_base_is_reported_not_rewritten():
    text = "\\newcommand{\\SMBulletColor}{red}\n\\input{my_own_base}\n"
    new, problem = compat_setup.template(text)
    assert new == text and "SlideMage_base" in problem


def test_deck_loses_only_its_gotham_theme_line():
    deck = ("\\documentclass[aspectratio=169]{beamer}\n\\usetheme{gotham} % the theme\n"
            "%\\usetheme{gotham}\n\\input{SlideMage_template_acme}\n")
    new = compat_setup.deck(deck)
    assert new == "\\documentclass[aspectratio=169]{beamer}\n%\\usetheme{gotham}\n\\input{SlideMage_template_acme}\n"
    assert not compat_setup.deck_has_theme(new)
    inline = "\\documentclass{beamer}\\usetheme{gotham}\\input{SlideMage_template_x}\n"
    assert compat_setup.deck(inline) == "\\documentclass{beamer}\\input{SlideMage_template_x}\n"
