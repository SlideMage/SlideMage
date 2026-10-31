# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hook catalog of latex/SlideMage_setup.tex (v10.9.0): every hook is read by the framework, the shipped
templates and the stress-test template set catalog names only, the stress-test template sets every hook, and
every layout profile defines what the Fira profile defines."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"
BS = chr(92)
STRESS = ROOT / "tests" / "fixtures" / "template_stress"
SHIPPED_TEMPLATES = [LATEX / "SlideMage_template_slidemage.tex", LATEX / "SlideMage_template_greyscale.tex"]
# Names setup defines for its own bookkeeping, not for a template to set.
# The names that were hooks and are gone (v10.11.0): the setup layer holds an error-raising macro under each. The first three
# moved nothing; the other two were renamed.
REMOVED = {"SMFootlineHeight", "SMFootlineDepth", "SMRightFooterPadding"}
RENAMED = {"SMProgressStripHeight": "SMProgressStripRoom", "SMSideFootnoteTopSep": "SMSideFootnoteTitleBlockSep"}
NOT_HOOKS = {"SMSetupLoaded", "SM@derivedname", "SM@guardname", "SM@removedname", "SM@renamedname"} | REMOVED | set(RENAMED)
# The names the base derives (v10.7.0, v10.8.0, v10.9.0): the setup layer holds an error-raising macro under each, so a template or a
# profile that sets one is told; they are in the catalog's text but are not hooks.
DERIVED = {"SMContentTopAlign", "SMTitleBarBottomAlign", "SMFootnoteRightShift", "SMFooterRightShift",
           "SMFooterTextDrop", "SMFootlineVOffset", "SMLabelItemWidth", "SMLabelItemSep", "SMEnumerateNestedMinNumber",
           "SMEnumerateNestedLabelSep", "SMEnumerateNestedLeftMargin", "SMEnumerateLabelBox", "SMSectionframeRefDepth",
           "SMSectionframeBottomGap", "SMSectionframeBottomPadCorrection", "SMSectionframeHeightCorrection",
           "SMContentTopShift", "SMColumnsTopCorrection", "SMColumnsTTopCompensation"}
# What a layout profile defines besides its fonts (v10.9.0): the font's metrics, and no length (the three top pull-ups
# of v10.8.0 are measured on the page now). Nothing else is a number of the font.
PROFILE_LENGTHS: set[str] = set()
PROFILE_MACROS = {"SMFontAscender", "SMLinespread", "SMParskip", "SMCardHeadingFont"}
# Palette colors only slides read (the manual's slide 1pf shows them): a template still redefines them, but
# neither the base nor the theme uses them. Any other palette color nothing reads is a finding.
PALETTE_FOR_SLIDES = {"c_custom_brown", "c_custom_green", "c_secondary_yellow", "c_tertiary_blue", "c_tertiary_green",
                      "c_tertiary_orange", "c_tertiary_red", "c_tertiary_violet"}
# \newfontfamily names a profile may define (v10.9.0: a profile holds the code fonts besides its macros and
# the font files themselves -- nothing else is a font of the profile's own).
ALLOWED_PROFILE_FONT_NAMES = {"SMCodeFont", "SMInlineCodeFont"}
# The profile's own metrics and font macros a template never overrides (step 13). Since v10.17.0 that includes
# \SMCardHeadingFont: a template with another card heading weight sets the catalog's \SMCardHeadingStyle.
PROFILE_OWNED_NOT_FOR_TEMPLATES = PROFILE_MACROS | ALLOWED_PROFILE_FONT_NAMES


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code(text: str) -> str:
    """The TeX without its % comment lines (a % after code is rare in these files and kept)."""
    return "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("%"))


def defined(text: str, commands: tuple[str, ...]) -> set[str]:
    """Names given to `\\<command>{\\Name}` (or `{Name}` for a color) in the code of `text`."""
    pattern = r"\\(?:%s)\*?\s*\{\\?([A-Za-z_@]+)\}" % "|".join(commands)
    return set(re.findall(pattern, code(text)))


def catalog() -> dict[str, set[str]]:
    setup = read(LATEX / "SlideMage_setup.tex")
    return {
        "lengths": defined(setup, ("newlength",)) - NOT_HOOKS,
        "macros": defined(setup, ("newcommand",)) - NOT_HOOKS - DERIVED,
        "colors": defined(setup, ("definecolor",)),
    }


def optional_colors() -> set[str]:
    """The colors the catalog documents as optional (SMCanvasColor ...): comment lines "%   SMXxxColor   text"."""
    return set(re.findall(r"^%\s{2,}(SM[A-Za-z]+Color)\b", read(LATEX / "SlideMage_setup.tex"), re.M))


def catalog_names() -> set[str]:
    """Every name the setup file mentions, code or documentation: what a template may set."""
    return set(re.findall(r"\bSM[A-Za-z]+|\bc_[a-z_]+", read(LATEX / "SlideMage_setup.tex")))


def settings_before_base(template: Path) -> str:
    """The part of a template between its start and \\input{SlideMage_base}: where hooks are set."""
    text = code(read(template))
    cut = text.find(BS + "input{SlideMage_base}")
    return text if cut < 0 else text[:cut]


def test_the_catalog_has_lengths_macros_and_colors():
    found = catalog()
    assert len(found["lengths"]) > 30 and len(found["macros"]) > 25 and len(found["colors"]) > 20
    assert {"SMTopMargin", "SMLogoHeight", "SMInstituteLogoPath"} <= found["lengths"] | found["macros"]
    assert {"SMCanvasColor", "SMCodeBackgroundColor"} <= optional_colors()


def test_every_catalog_hook_is_used_by_the_base_or_the_theme():
    reading = read(LATEX / "SlideMage_base.tex") + read(LATEX / "beamerthemeSlideMage.sty")
    found = catalog()
    unused = []
    for name in sorted(found["lengths"] | found["macros"]):
        if not re.search(re.escape(BS + name) + r"(?![A-Za-z@])", reading):
            unused.append(name)
    for name in sorted((found["colors"] - PALETTE_FOR_SLIDES) | optional_colors()):
        if not re.search(r"(?<![A-Za-z_])" + re.escape(name) + r"(?![A-Za-z_])", reading):
            unused.append(name)
    assert not unused, f"catalog hooks nothing reads: {unused}"


@pytest.mark.parametrize("template", SHIPPED_TEMPLATES + [STRESS / "SlideMage_template_stress-test.tex"],
                         ids=lambda p: p.name)
def test_templates_set_catalog_names_only_and_define_none_of_their_own(template):
    before = settings_before_base(template)
    # a template defines no length, macro or switch of its own before the base: it sets what the catalog has
    allowed_new = {"SMLayoutProfile", "SMDarkMode"}
    new = defined(before, ("newlength", "newcommand", "newif", "newcounter", "newbox", "providecommand"))
    assert new <= allowed_new, f"{template.name} defines names of its own: {sorted(new - allowed_new)}"
    # a color of the template's own (a palette extra, say c_true_black) is not a setting; the catalog names are
    names = catalog_names() | defined(before, ("definecolor",))
    setting = defined(before, ("setlength", "addtolength", "renewcommand", "colorlet", "definecolor"))
    assert setting <= names, f"{template.name} sets names the catalog does not have: {sorted(setting - names)}"
    assert BS + "input{SlideMage_setup}" in before


def test_the_stress_template_sets_every_hook_of_the_catalog():
    template = read(STRESS / "SlideMage_template_stress-test.tex")
    found = catalog()
    # the layout profile is picked by the template, the catalog's \providecommand is not a hook
    set_by_template = defined(template, ("setlength", "addtolength", "renewcommand", "colorlet", "definecolor"))
    missing = sorted((found["lengths"] | found["macros"] | found["colors"] | optional_colors()) - set_by_template)
    assert not missing, f"the stress-test template leaves hooks at their default: {missing}"
    assert BS + "newcommand{" + BS + "SMLayoutProfile}{lmsans}" in template


def test_the_stress_template_picks_lmsans_and_stays_out_of_the_apps_reach():
    assert (STRESS / "SlideMage_template_stress-test.tex").is_file()
    assert not (ROOT / "example" / "SlideMage_template_stress-test.tex").exists()
    assert not (LATEX / "SlideMage_template_stress-test.tex").exists()
    assert (STRESS / "slide_ids.csv").is_file() and (STRESS / ".latexmkrc").is_file()


def profile_names(path: Path) -> set[str]:
    text = read(path)
    return (defined(text, ("newlength", "newcommand")) | set(re.findall(r"\\newfontfamily\s*\\([A-Za-z]+)", code(text))))


def test_every_layout_profile_defines_what_the_fira_profile_defines():
    fira = profile_names(LATEX / "SlideMage_layout_fira.tex")
    assert {"SMFontAscender", "SMLinespread", "SMParskip",
            "SMCodeFont", "SMInlineCodeFont", "SMCardHeadingFont"} <= fira
    profiles = sorted(LATEX.glob("SlideMage_layout_*.tex"))
    assert {p.name for p in profiles} >= {"SlideMage_layout_fira.tex", "SlideMage_layout_lmsans.tex"}
    for path in profiles:
        lacking = fira - profile_names(path)
        assert not lacking, f"{path.name} lacks {sorted(lacking)}"
        # since v10.9.0 a profile holds fonts and the font's metrics, no other number
        lengths = defined(read(path), ("newlength",))
        macros = defined(read(path), ("newcommand",))
        assert lengths == PROFILE_LENGTHS, f"{path.name} defines lengths {sorted(lengths ^ PROFILE_LENGTHS)}"
        assert macros == PROFILE_MACROS, f"{path.name} defines macros {sorted(macros ^ PROFILE_MACROS)}"
        text = code(read(path))
        for command in ("setsansfont", "setmonofont", "usefonttheme[onlymath]{serif}"):
            assert BS + command in text, f"{path.name}: no {command}"


def test_profiles_define_only_an_allowed_list_of_font_names():
    """A profile's own `\\newfontfamily`-declared names (step 13): only the code fonts the catalog reads
    (\\SMCodeFont, \\SMInlineCodeFont) -- a profile is fonts and the font's metrics, nothing a future profile
    might add a font family under its own name for."""
    for path in sorted(LATEX.glob("SlideMage_layout_*.tex")):
        fonts = set(re.findall(r"\\newfontfamily\s*\\([A-Za-z]+)", code(read(path))))
        extra = fonts - ALLOWED_PROFILE_FONT_NAMES
        assert not extra, f"{path.name} defines font names outside the allowed list: {sorted(extra)}"


def test_the_setup_header_says_a_profile_holds_no_measured_length_and_names_the_derived_ones():
    header = read(LATEX / "SlideMage_setup.tex").split(BS + "newcommand{" + BS + "SMSetupLoaded}")[0]
    fira = read(LATEX / "SlideMage_layout_fira.tex")
    assert not re.findall(r"\\newlength\{\\(SM[A-Za-z]+)\}", code(fira))
    missing = sorted(name for name in DERIVED if BS + name not in header)
    assert not missing, f"the setup header's list of derived names lacks {missing}"
    assert "calibrate_font_profile.py" in header and "lmsans" in header


def test_no_template_or_profile_sets_a_derived_name():
    """The derived names (v10.7.0-v10.9.0) are computed by the base from the hooks and the font; setting one would
    contradict the next change to a hook or to the font."""
    for template in SHIPPED_TEMPLATES + [STRESS / "SlideMage_template_stress-test.tex"]:
        touched = defined(settings_before_base(template),
                          ("setlength", "addtolength", "renewcommand", "newlength", "newcommand", "providecommand"))
        assert not touched & DERIVED, f"{template.name} sets {sorted(touched & DERIVED)}"
    for profile in sorted(LATEX.glob("SlideMage_layout_*.tex")):
        touched = defined(read(profile), ("setlength", "addtolength", "renewcommand", "newlength", "newcommand"))
        assert not touched & DERIVED, f"{profile.name} sets {sorted(touched & DERIVED)}"


def test_no_template_sets_a_name_the_profile_computes():
    """A template only picks a layout profile; it never overrides a single profile value (user decision, see the
    handover): the profile's own metrics (\\SMFontAscender, \\SMLinespread, \\SMParskip) and its code fonts are
    computed from the loaded font, not hook-settable, like the base's own derived names above, and so is its
    \\SMCardHeadingFont since v10.17.0 (the catalog's \\SMCardHeadingStyle picks another weight). Checked in the whole
    template: a renewal after \\input{SlideMage_base} would override the profile just the same."""
    for template in SHIPPED_TEMPLATES + [STRESS / "SlideMage_template_stress-test.tex"]:
        touched = defined(code(read(template)),
                          ("setlength", "addtolength", "renewcommand", "newlength", "newcommand", "providecommand"))
        assert not touched & PROFILE_OWNED_NOT_FOR_TEMPLATES, \
            f"{template.name} sets {sorted(touched & PROFILE_OWNED_NOT_FOR_TEMPLATES)}"


def test_the_base_derives_each_derived_name_and_the_setup_layer_guards_it():
    base, setup = read(LATEX / "SlideMage_base.tex"), read(LATEX / "SlideMage_setup.tex")
    for name in sorted(DERIVED):
        assert BS + "SM@derivedlength{" + name + "}" in base, name
        assert re.search(r"^" + re.escape(BS + "SM@guardname" + BS + name) + r"\s*$", setup, re.M), name
        assert BS + "newlength{" + BS + name + "}" not in setup, f"{name} is a length in the catalog again"
    assert "Derived, not set" in setup


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                    reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")
@pytest.mark.parametrize("setting", [BS + "setlength{" + BS + "SMContentTopAlign}{50bp}",
                                     BS + "renewcommand{" + BS + "SMFooterRightShift}{3pt}",
                                     BS + "setlength{" + BS + "SMFooterTextDrop}{1pt}",
                                     BS + "renewcommand{" + BS + "SMLabelItemWidth}{3pt}",
                                     BS + "setlength{" + BS + "SMFootlineVOffset}{-3pt}",
                                     BS + "setlength{" + BS + "SMContentTopShift}{11pt}"])
def test_a_template_that_sets_a_derived_name_gets_an_error_that_names_it(setting, tmp_path):
    (tmp_path / "template.tex").write_text(
        BS + "input{SlideMage_setup}\n" + setting + "\n" + BS + "input{SlideMage_base}\n", encoding="utf-8")
    (tmp_path / "deck.tex").write_text(
        BS + "documentclass[aspectratio=169]{beamer}\n" + BS + "input{template}\n" + BS + "begin{document}"
        + BS + "end{document}\n", encoding="utf-8")
    env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), str(tmp_path), ""]))
    subprocess.run(["lualatex", "-interaction=nonstopmode", "deck.tex"], cwd=tmp_path, env=env,
                   capture_output=True, timeout=300)
    log = (tmp_path / "deck.log").read_text(encoding="utf-8", errors="replace").replace("\n", "")
    name = re.search(r"(SM[A-Za-z]+)\}", setting).group(1)
    assert "is derived, not set" in log and BS + name + " is derived" in log


def test_every_geometric_hook_has_a_check_in_test_hook_geometry():
    """tests/test_hook_geometry.py measures each length hook of the catalog against the compiled PDF, or says why
    it cannot be read back (its own MEASURED/NOT_READ_BACK table, checked there against its own reading of the
    catalog); cross-referenced here too (step 13), against this file's own catalog() -- so a hook added without
    being added to either table is caught from this file as well, not only from that one."""
    from test_hook_geometry import MEASURED, NOT_READ_BACK
    lengths = catalog()["lengths"]
    covered = set(MEASURED) | set(NOT_READ_BACK)
    missing = sorted(lengths - covered)
    assert not missing, f"catalog hooks with no entry in test_hook_geometry.py: {missing}"


def test_the_removed_and_renamed_names_are_errors_in_the_setup_layer_and_no_template_sets_them():
    setup = read(LATEX / "SlideMage_setup.tex")
    for name in sorted(REMOVED | set(RENAMED)):
        assert re.search(re.escape(BS + "newcommand{" + BS + name + "}"), code(setup)), name
    for new in RENAMED.values():
        assert new in catalog()["lengths"]
    for template in SHIPPED_TEMPLATES + [STRESS / "SlideMage_template_stress-test.tex"]:
        text = code(read(template))
        for name in sorted(REMOVED | set(RENAMED)):
            assert not re.search(re.escape(BS + name) + r"(?![A-Za-z@])", text), f"{template.name} sets {name}"
    for name in sorted(REMOVED | set(RENAMED)):
        for part in (read(LATEX / "SlideMage_base.tex"), read(LATEX / "beamerthemeSlideMage.sty")):
            assert not re.search(re.escape(BS + name) + r"(?![A-Za-z@])", code(part)), name


def test_the_body_size_table_matches_beamers_size_files():
    """\\SMBodyFontSize (v10.19.0): at 10pt, 11pt and 12pt the base's sizes and baseline skips are those of
    size10/11/12.clo (what beamer loads for its class option), except \\tiny at 10pt, which stays the 11pt option's
    (v10.18.1's greyscale stopgap left it there). The other values follow the rule the setup file documents."""
    base = read(LATEX / "SlideMage_base.tex")
    blocks = re.findall(
        r"\\ifdim\\SMBodyFontSize=(\d+)pt\s*((?:\\def\\SM@b[sl]@[nsfct]\{[\d.]+\}%?\s*)+)", base)
    assert [pt for pt, _ in blocks] == ["10", "11", "12"]
    names = {"n": "normalsize", "s": "small", "f": "footnotesize", "c": "scriptsize", "t": "tiny"}
    for pt, body in blocks:
        values = {(kind, step): value for kind, step, value in re.findall(r"\\def\\SM@b([sl])@([nsfct])\{([\d.]+)\}", body)}
        clo = shutil.which("kpsewhich") and subprocess.run(["kpsewhich", f"size{pt}.clo"], capture_output=True, text=True).stdout.strip()
        if not clo:
            pytest.skip("no TeX distribution")
        text = Path(clo).read_text(encoding="utf-8")
        roman = {"vpt": 5, "vipt": 6, "viipt": 7, "viiipt": 8, "ixpt": 9, "xpt": 10, "xipt": 10.95, "xiipt": 12}
        for step, name in names.items():
            found = re.search(r"\\@setfontsize\\%s\\@(\w+)\s*(?:\{([\d.]+)\}|\\@(\w+))" % name, text)
            size = roman[found.group(1)]
            skip = found.group(2) or roman[found.group(3)]
            if pt == "10" and step == "t":
                assert (values[("s", step)], values[("l", step)]) == ("6", "7")
                continue
            assert (values[("s", step)], values[("l", step)]) == (f"{size:g}", f"{skip:g}" if isinstance(skip, float) else str(skip)), f"{pt}pt {name}"
