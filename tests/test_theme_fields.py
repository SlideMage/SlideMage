# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme form's field list (theme_fields.FIELDS) against the hook catalog in latex/SlideMage_setup.tex
(docs/plans/theme-editor.md, section 3.1): every catalog name has a field, every field names something the catalog has,
and the details the writer relies on (arguments, length hooks that are macros, the roles' hook macros) match it. A
hook added to the catalog without a field fails here, so the form and the framework cannot drift apart."""
import re
from pathlib import Path

from slidemage import theme_fields, theme_file
from test_template_catalog import catalog as independent_catalog, optional_colors

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "latex" / "SlideMage_setup.tex").read_text(encoding="utf-8")
CATALOG = theme_fields.catalog(SETUP)
HEADERS = {"header:name", "header:modes"}


def covered(name: str) -> bool:
    return name in theme_fields.BY_NAME or name in theme_fields.ROLE_OF_HOOK


def test_every_catalog_name_has_a_field():
    missing = sorted(name for name in CATALOG if not covered(name))
    assert not missing, f"catalog settings the theme form has no field for: {missing}"


def test_every_field_names_something_the_catalog_has():
    stale = sorted(field.name for field in theme_fields.FIELDS if field.name not in HEADERS and field.name not in CATALOG)
    assert not stale, f"fields whose setting the catalog no longer has: {stale}"


def test_the_catalog_reader_agrees_with_the_catalog_tests_own_reading():
    """theme_fields.catalog() is checked against the independent reading of tests/test_template_catalog.py, so a hook
    the form's reader overlooks still fails."""
    other = independent_catalog()
    names = other["lengths"] | other["macros"] | other["colors"] | optional_colors()
    assert names <= set(CATALOG), sorted(names - set(CATALOG))
    assert all(covered(name) for name in names)


def test_every_role_of_the_mode_layer_has_a_field():
    roles = set(re.findall(r"\\SM@role(?:colour|hook)\{(\w+)\}", SETUP))
    assert len(roles) > 40
    fields = {field.name[5:] for field in theme_fields.FIELDS if field.name.startswith("role:")}
    assert roles == fields, (sorted(roles - fields), sorted(fields - roles))


def test_a_roles_hook_is_the_macro_the_mode_layer_replaces():
    for field in theme_fields.FIELDS:
        if field.hook:
            assert CATALOG[field.name].source == field.hook, field.name
            assert CATALOG[field.hook].kind == "macro", field.hook


def test_macro_arguments_match_the_catalog():
    with_args = dict(re.findall(r"\\newcommand\{\\(SM[A-Za-z]+)\}\[(\d)\]", SETUP))
    for name in CATALOG:
        field = theme_fields.BY_NAME.get(name)
        if field and CATALOG[name].kind == "macro":
            assert field.args == int(with_args.get(name, 0)), name


def test_length_fields_that_are_macros_are_known_to_the_writer():
    """A length the catalog defines with \\newcommand must be written with \\renewcommand, not \\setlength."""
    macros = {f.name for f in theme_fields.FIELDS if f.kind == "length" and CATALOG.get(f.name)
              and CATALOG[f.name].kind == "macro"}
    assert macros == set(theme_file.MACRO_LENGTHS)


def test_fields_are_well_formed():
    names = [field.name for field in theme_fields.FIELDS]
    assert len(names) == len(set(names))
    for field in theme_fields.FIELDS:
        assert field.kind in theme_fields.KINDS, field
        assert field.group in theme_fields.GROUPS, field
        assert field.tier in (1, 2, 3), field
        assert field.label, field
    tier1 = {f.group for f in theme_fields.FIELDS if f.tier == 1}
    assert {"identity", "palette", "roles", "code", "logo", "footnotes"} <= tier1


def test_defaults_and_help_come_from_the_setup_file():
    assert CATALOG["SMTopMargin"].default == "41.58bp"
    assert CATALOG["SMLogoHeight"].default == "3ex" and "logo height" in CATALOG["SMLogoHeight"].help
    assert CATALOG["c_primary_highlight"].default == "0066cc" and "accent" in CATALOG["c_primary_highlight"].help
    assert CATALOG["SMCanvasColor"].kind == "optional_colour" and CATALOG["SMCanvasColor"].default == "white"
    assert CATALOG["SMLayoutProfile"].kind == "profile" and CATALOG["SMLayoutProfile"].default == "fira"
    assert CATALOG["role:text"].source == "c_primary_dark"
    assert CATALOG["SMMiniFramesPosition"].kind == "command"
    # bookkeeping and the error macros of removed or renamed hooks are no settings
    for name in ("SMSetupLoaded", "SMFootlineHeight", "SMProgressStripHeight", "SMDeclareMode", "SMSetRole"):
        assert name not in CATALOG


def test_the_order_puts_a_themes_own_colours_after_the_palette():
    assert theme_fields.order("c_primary_dark") < theme_fields.order("c_my_own") < theme_fields.order("SMLogoHeight")
    assert theme_fields.order("SMTitleBoxColor") == theme_fields.order("role:title_fill")
