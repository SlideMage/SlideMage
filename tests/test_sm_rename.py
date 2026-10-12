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
