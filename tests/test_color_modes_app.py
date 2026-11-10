# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The app side of colour modes: the modes a template declares, the deck's mode line, and the mode a view sees (no TeX)."""
from __future__ import annotations

import pytest

from slidemage import view_themes  # first: deck_editor must load before deck_settings (import cycle)
from slidemage import deck_settings

MODE = "\\newcommand{\\SMModeOverride}{grey}"
DARK = "\\newcommand{\\SMDarkMode}{}"
DECK = "\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n\\begin{document}\n\\end{document}\n"


def test_a_template_declares_its_modes_in_its_header(tmp_path):
    template = tmp_path / "SlideMage_template_acme.tex"
    template.write_text("% SlideMage modes: light, dark=Dark slides, grey, bad id, dark\n\\input{SlideMage_setup}\n")
    assert deck_settings.template_modes(tmp_path, "acme") == [("light", "Light"), ("dark", "Dark slides"), ("grey", "Grey")]
    assert deck_settings.template_supports_dark_mode(tmp_path, "acme")
    template.write_text("% SlideMage dark mode: true\n")
    assert deck_settings.template_modes(tmp_path, "acme") == [("light", "Light"), ("dark", "Dark")]
    template.write_text("% SlideMage modes: light, grey\n")
    assert not deck_settings.template_supports_dark_mode(tmp_path, "acme")
    template.write_text("nothing declared\n")
    assert deck_settings.template_modes(tmp_path, "acme") == []
    assert deck_settings.template_modes(tmp_path, "missing") == []


def test_a_mode_choice_becomes_the_dark_switch_or_the_override():
    modes = [("light", "Light"), ("dark", "Dark"), ("grey", "Grey")]
    assert deck_settings.mode_to_settings(modes, "light") == (False, "")
    assert deck_settings.mode_to_settings(modes, "dark") == (True, "")
    assert deck_settings.mode_to_settings(modes, "grey") == (False, "grey")
    assert deck_settings.mode_to_settings(modes, "") == (False, "")
    assert deck_settings.settings_mode(modes, False, "") == "light"
    assert deck_settings.settings_mode(modes, True, "") == "dark"
    assert deck_settings.settings_mode(modes, False, "grey") == "grey"
    assert deck_settings.settings_mode([], False, "") == ""


def test_the_mode_line_is_read_written_and_removed():
    written = deck_settings.set_mode(DECK, "grey")
    assert written.index(MODE) < written.index("\\input{SlideMage_template_acme}")
    assert deck_settings.read_settings(written).mode == "grey"
    assert deck_settings.set_mode(written, "grey") == written
    assert deck_settings.read_settings(deck_settings.set_mode(written, "cb")).mode == "cb"
    assert deck_settings.set_mode(written, "") == DECK
    assert deck_settings.read_settings(DECK).mode == ""
    # a line after the template does not count: the framework reads it before
    late = DECK.replace("\\begin{document}", MODE + "\n\\begin{document}")
    assert deck_settings.read_settings(late).mode == ""


def test_the_mode_line_keeps_other_commands_and_rejects_bad_names():
    deck = "\\documentclass{beamer}\n" + MODE + " \\def\\x{y}\n\\input{SlideMage_template_acme}\n"
    assert deck_settings.set_mode(deck, "") == "\\documentclass{beamer}\n \\def\\x{y}\n\\input{SlideMage_template_acme}\n"
    with pytest.raises(ValueError):
        deck_settings.set_mode(DECK, "a b")
    with pytest.raises(ValueError):
        deck_settings.set_mode("\\begin{document}\n", "grey")


def test_apply_settings_writes_a_changed_mode():
    old = deck_settings.read_settings(DECK)
    new = deck_settings.from_form(
        old, template="acme", language="en", footer_text="", output_folders={}, appendix_toc=False,
        open_pdf="instructor", mode="grey")
    assert deck_settings.read_settings(deck_settings.apply_settings(DECK, old, new)).mode == "grey"


def test_a_view_can_have_any_mode_of_its_theme():
    text = DECK.replace(
        "\\begin{document}", "% SlideMage view themes: instructor=acme:grey, after-course=acme:dark\n\\begin{document}")
    instructor = view_themes.preamble_for_view(text, "instructor")
    assert MODE in instructor and "SMDarkMode" not in instructor
    after = view_themes.preamble_for_view(text, "after-course")
    assert DARK in after and "SMModeOverride" not in after
    assert view_themes.preamble_for_view(instructor, "instructor") == instructor      # idempotent
    # no entry: the deck's own; an entry without a mode turns a deck default off
    base = DECK.replace("\\input", MODE + "\n\\input").replace(
        "\\begin{document}", "% SlideMage view themes: after-course=acme\n\\begin{document}")
    assert "SMModeOverride" not in view_themes.preamble_for_view(base, "after-course")
    assert MODE in view_themes.preamble_for_view(base, "instructor")
