# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""sm_rename: this project's \\gotham... names become \\SM..., the Gotham theme's stay."""
from slidemage import sm_rename


def test_project_names_renamed_theme_names_kept():
    src = (r"\setlength{\gothamContentTopAlign}{1pt}\ifgothamInstructorVersion x\fi"
           r"\gothamset{x}\gothamFrametitleLeftpading \gotham@cf@x \gotham@block"
           r"\begin{gothamtable}{l}\end{gothamtable} \node[gothamImageBorder]{};"
           r"\csname gotham@topcorr@1\endcsname Gotham theme")
    out = sm_rename.rename_text(src)
    assert r"\SMContentTopAlign" in out and r"\ifSMInstructorVersion" in out
    assert r"\SM@cf@x" in out and "SMImageBorder" in out and r"\csname SM@topcorr@1" in out
    # theme names, environments and prose unchanged
    for kept in (r"\gothamset{x}", r"\gothamFrametitleLeftpading", r"\gotham@block",
                 r"\begin{gothamtable}", "Gotham theme"):
        assert kept in out
    assert sm_rename.rename_text(r'tex.sprint("\\gothamAltShort{")') == r'tex.sprint("\\SMAltShort{")'
    assert sm_rename.rename_text(r're.compile(r"\\gothamTikz(?:mark|word)")') == \
        r're.compile(r"\\SMTikz(?:mark|word)")'


def test_theme_renames_follow_the_naming_rule():
    for old, new in sm_rename.THEME_RENAMES.items():
        assert old.lower().startswith(("gotham", "_gotham", "thegotham", "g_gotham")), old
        assert new.startswith(("SM", "theSM", "g_SM", "_SM", "slidemage")), new
    tex_names = [new for new in sm_rename.THEME_RENAMES.values() if new.startswith("SM")]
    assert all(name[2].isupper() for name in tex_names)
    # the theme's own names are the remainder: nothing is both mapped and reserved for later
    assert not sm_rename.THEME_NAMES_REMAINING & set(sm_rename.THEME_RENAMES)


def test_rename_identifiers_handles_names_in_every_position():
    src = (r"\begin{gothamtable}[gap=1pt]{l}\end{gothamtable} \def\gothamtable@spec{} "
           r"\node[gotham arrow, gotham dotted highlight] \setbeamertemplate{section in toc}[gotham plain enumerate] "
           r"\stepcounter{gothamnumitem}\thegothamnumitem \begin{gothamnumitemize}\end{gothamnumitemize} "
           r"\pgfqkeys{/gothamfit}{} (gothamfit@top) gothamfit3 \edef\x{gothamfit\the\n} "
           r"\g_gotham_footnote_symbols_seq \directlua{gothamalt.load() gotham_layout.top_end(1)} "
           r"\gothamFrametitleRightpading")
    out = sm_rename.rename_identifiers(src)
    assert out == (r"\begin{SMTable}[gap=1pt]{l}\end{SMTable} \def\SMTable@spec{} "
                   r"\node[SMArrow, SMDottedHighlight] \setbeamertemplate{section in toc}[SMPlainEnumerate] "
                   r"\stepcounter{SMNumItemCounter}\theSMNumItemCounter \begin{SMNumItemize}\end{SMNumItemize} "
                   r"\pgfqkeys{/SMFit}{} (SMFit@top) SMFit3 \edef\x{SMFit\the\n} "
                   r"\g_SM_footnote_symbols_seq \directlua{slidemage_alt.load() slidemage_measure.top_end(1)} "
                   r"\SMFrametitleRightPadding")
    assert sm_rename.rename_identifiers(out) == out


def test_rename_identifiers_leaves_prose_and_the_themes_own_names():
    src = (r"The gotham theme, Gotham, \gothamset{x} \gotham@block \gothamFootlineVOffset \usetheme{gotham} "
           r"gothamtables mygothamtable gothamfitx")
    assert sm_rename.rename_identifiers(src) == src


def test_unknown_names_are_the_ones_nothing_maps():
    found = sm_rename.unknown_names("gothamfloating... \\gothamset \\gothamtable \\gotham@block gothamfoo\ngothamtable@x")
    assert found == [(1, "gothamfloating"), (1, "gothamfoo"), (2, "gothamtable@x")]
