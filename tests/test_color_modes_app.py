# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The app side of colour modes: the modes a template declares, the deck's mode line, and the mode a view sees (no TeX)."""
from __future__ import annotations

import pytest

from slidemage import view_themes  # first: deck_editor must load before deck_settings (import cycle)
from slidemage import deck_settings

MODE = "\\newcommand{\\SMModeOverride}{grey}"
DARK = "\\newcommand{\\SMModeOverride}{dark}"
DECK = "\\documentclass{beamer}\n\\input{SlideMage_template_acme}\n\\begin{document}\n\\end{document}\n"


def test_a_template_declares_its_modes_in_its_header(tmp_path):
    template = tmp_path / "SlideMage_template_acme.tex"
    template.write_text("% SlideMage modes: light, dark=Dark slides, grey, bad id, dark\n\\input{SlideMage_setup}\n")
    assert deck_settings.template_modes(tmp_path, "acme") == [("light", "Light"), ("dark", "Dark slides"), ("grey", "Grey")]
    assert deck_settings.template_supports_dark_mode(tmp_path, "acme")
    template.write_text("% SlideMage dark mode: true\n")                     # removed in v0.16.0
    assert deck_settings.template_modes(tmp_path, "acme") == []
    template.write_text("% SlideMage modes: light, grey\n")
    assert not deck_settings.template_supports_dark_mode(tmp_path, "acme")
    template.write_text("nothing declared\n")
    assert deck_settings.template_modes(tmp_path, "acme") == []
    assert deck_settings.template_modes(tmp_path, "missing") == []


def test_a_mode_choice_becomes_the_override_and_the_base_mode_none():
    modes = [("light", "Light"), ("dark", "Dark"), ("grey", "Grey")]
    assert deck_settings.mode_to_settings(modes, "light") == ""
    assert deck_settings.mode_to_settings(modes, "dark") == "dark"
    assert deck_settings.mode_to_settings(modes, "grey") == "grey"
    assert deck_settings.mode_to_settings(modes, "") == ""
    assert deck_settings.settings_mode(modes, "") == "light"
    assert deck_settings.settings_mode(modes, "dark") == "dark"
    assert deck_settings.settings_mode(modes, "grey") == "grey"
    assert deck_settings.settings_mode([], "") == ""
    written = deck_settings.set_mode(DECK, "dark")
    assert DARK in written and "SMDarkMode" not in written


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
    assert DARK in after and MODE not in after and "SMDarkMode" not in after
    assert view_themes.preamble_for_view(instructor, "instructor") == instructor      # idempotent
    # no entry: the deck's own; an entry without a mode turns a deck default off
    base = DECK.replace("\\input", MODE + "\n\\input").replace(
        "\\begin{document}", "% SlideMage view themes: after-course=acme\n\\begin{document}")
    assert "SMModeOverride" not in view_themes.preamble_for_view(base, "after-course")
    assert MODE in view_themes.preamble_for_view(base, "instructor")


@pytest.mark.parametrize("key", ["slidemage", "greyscale"])
def test_the_shipped_templates_offer_light_and_dark(key, tmp_path):
    """v0.16.2: both templates in latex/ declare light (the base) and dark, in the header the app reads and to the
    framework; every data line is for dark, so the light PDFs do not change."""
    import re
    from pathlib import Path

    assert deck_settings.template_modes(tmp_path, key) == [("light", "Light"), ("dark", "Dark slides")]
    text = (Path(__file__).resolve().parents[1] / "latex" / f"SlideMage_template_{key}.tex").read_text(encoding="utf-8")
    assert re.findall(r"^\\SMDeclareMode\{(\w+)\}\{(\w*)\}", text, re.MULTILINE) == [("light", ""), ("dark", "dark")]
    lines = re.findall(r"^\\SMSet(?:Role|Color)\{\w+\}\{(\w+)\}", text, re.MULTILINE)
    assert lines and set(lines) == {"dark"}


@pytest.mark.parametrize("key", ["slidemage", "greyscale"])
def test_the_text_accents_of_the_shipped_templates_read_on_the_dark_canvas(key, tmp_path):
    """v0.16.5: the palette colours slides write as text keep at least 4.4:1 on the dark canvas (they were 1.0:1 to
    2.2:1 before the templates gave them dark-mode values); in light mode they are the template's own."""
    from slidemage import theme_colors

    def luminance(value):
        channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def contrast(a, b):
        high, low = sorted((luminance(a), luminance(b)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    dark = theme_colors.theme_colors(key, tmp_path, "dark")
    light = theme_colors.theme_colors(key, tmp_path, "")
    accents = ["c_primary_highlight", "c_custom_red", "c_custom_green", "c_custom_brown", "c_text", "c_link"]
    low = {name: round(contrast(dark[name], dark["c_canvas"]), 2) for name in accents
           if contrast(dark[name], dark["c_canvas"]) < 4.4}
    assert not low, low
    assert all(light[name] != dark[name] for name in accents[:4])
