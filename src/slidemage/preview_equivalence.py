# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-render, image-sequence equivalence for the audited SlideMage framework.

This is evidence for the request scheduler, not a TeX interpreter. A group is
shared only when every known view-dependent operation has the same effective
signature and the remaining inputs are identical. Unclassified TeX is isolated.
The hashes below pin the framework source whose rules were audited; changing a
rule requires a fresh audit and a deliberate update of this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from . import compiler, slide_preview

CONTRACT = 2
AUDITED_GENERIC_PREAMBLE = "647999e566d666480aeee6e2649cc246499c79cdafb069418f59cb4d818b7249"
AUDITED_FRAMEWORK = {
    # v8.40.0: the slide canvas, card and code colors a template may set (dark mode); no view-dependent rule.
    # v8.62.0 (merged from develop): \SMQRCode in the base, an image and a caption in a box; no view-dependent rule.
    # v9.0.0: the setup layer (theme, palette and template settings with their defaults); no view-dependent rule.
    # v9.1.0 (step 2a): base, the Lua files and the example template only rename gotham... content names to SM...;
    # no rule, argument or view-dependent branch changed.
    # v9.1.0 (step 2b): the five Gotham theme files are replaced by beamerthemeSlideMage.sty, a pruned and renamed fork;
    # it holds no version, footer-hide or deck-label rule (checked by test_the_pins_are_the_frameworks_files...).
    # v9.2.0 (step 3): the parts of the theme that the base replaced move into the theme (colors, margins, bullets,
    # logo macro and frame title hook, footer box, footnote and block templates); the frame footer, which carries the
    # deck label, stays in the base. Re-audited: no version, footer-hide or deck-label rule left the base or entered
    # the theme (the theme test above still passes), the patches are the same, in the same order, and the setup file
    # only names the new theme version.
    # v9.3.0 (step 4): the font loading, the math-font handling and the font metrics move from the theme and the base into
    # the layout profile SlideMage_layout_fira.tex (new, pinned); the setup layer inputs it before the theme and gains
    # the Top Margin setting; the base hands the ascender and the Top Margin to SlideMage_measure.lua. Re-audited: no
    # version, footer-hide or deck-label rule entered the profile (test_the_pins_are_the_frameworks_files... checks it
    # for the theme and the profile), and the base lost only font code.
    # v9.4.0 (step 5): the design values become catalog hooks in the setup layer (lengths, ratios, text sizes, margins;
    # the theme and the base lose their definitions), the font calibrations move into the profile, four obsolete
    # corrections are 0pt. Re-audited: no version, footer-hide or deck-label rule entered the setup layer, the theme or
    # the profile (the theme test checks the last two); the base kept the frame footer and its deck-version text.
    # v9.6.0 (step 7): the layout profile SlideMage_layout_lmsans.tex (new, pinned: Latin Modern Sans, offered to users);
    # the base writes two more keys into the PDF info dictionary (the ascender and the title bar's bottom edge, for
    # tools/check_layout.py); the setup file only documents the profiles and the calibration recipe, the fira profile
    # only a comment. Re-audited: no version, footer-hide or deck-label rule entered either profile (the profile test
    # checks every profile the framework ships), and the base gained two \hypersetup lines.
    # v9.7.0 (step 8): the overlay coordinate, the title bar's bottom edge and the footnotes' and the footer number's right
    # edges are derived in the base (the setup layer guards the four names with an error, both profiles lose the two right
    # shifts, the theme changes in comments and its version only). Re-audited: no version, footer-hide or deck-label rule
    # entered or moved; the frame footer gained one \setlength before its \hspace*, the deck-version text is untouched.
    # v9.8.0 (step 9): the font measurements the profiles held (footer text drop, list label and numeral boxes, footnote
    # offset, section frame corrections) are evaluated in the font where they are used, in the base, with design hooks in the
    # setup layer; both profiles keep fonts, metrics and the three top pull-ups; the setup layer guards twelve more names. Re-audited: no
    # version, footer-hide or deck-label rule entered the base, the setup layer or the profiles; the frame footer gained one call
    # (the text drop) before its first \vspace*, the deck-version text is untouched, and the theme is unchanged.
    # v9.9.0 (step 10): the top pull-ups leave both profiles; the base measures where each top-aligned frame's body
    # begins (a second marker for SlideMage_measure.lua and a reference list typeset in a box that never reaches the
    # page) and reads \SMContentTopShift back from \jobname.top; a columns environment at the top of a frame the
    # measurement does not correct measures its correction the same way; the setup layer guards three more names.
    # Re-audited: no version, footer-hide or deck-label rule entered the base, the Lua file, the setup layer or the
    # profiles; the .top mechanism adds none (the value is the one most frames of the deck share, and a page compile
    # keeps the deck's while one of its frames agrees), the frame footer and the theme are unchanged.
    "SlideMage_setup.tex": "a202b75b023ed1305192c99e43d3760c1254332689f811dcdaf5cad4544cb7ce",
    "SlideMage_layout_fira.tex": "0f44c15ff57f6c71def59b1421ca15c8653657a29711e4bace1ba8b36bd8ae67",
    "SlideMage_layout_lmsans.tex": "8266f2aa8bf9f7d69946239f6010b5b4ae850935729ec63760db52f04402ee17",
    "SlideMage_base.tex": "ea5024a6d47ec78d98ad38061cbb1e5825b4068577a109b831df7ba1c500457b",
    "SlideMage_template_slidemage.tex": "bedc4688cefb15bee860c792937422a8d3f97d02b30002e97e723e1078c9800e",
    "beamerthemeSlideMage.sty": "0afea7c0abf1f38c52aec6666c67e8b21692c2051e96f3bb7b969b8a945b7e11",
    "SlideMage_alt.lua": "f07491335b836762daf485b6e7fb94f435217fadf6b48b9b0d6f3dd9fbed465c",
    "SlideMage_measure.lua": "0e0d9e7a0d5a6837850178176b2c269413b2f7de784a5086e02f5206ef8db163",
}
# SHA-256 of the project-root institution templates (SlideMage_template_<key>.tex) whose rules were audited; a
# template with another digest is isolated (rendered on its own), never shared between views.
AUDITED_PROJECT_TEMPLATES = frozenset({
    "fb8bcd1fea2a69ec2086dc8df7843ec336e5801f5ccc467e291095643f578338",
    "13c039dcf2d7e9bdc38363ee782ccd5a34e14fc6786322950bd0cb22f6e11ff8",   # the same with its "template name" line
    "527fa4a6337be2226e7f2badfa3040b9982d95f9c1e5ba760acb6febbf06fafa",   # v8.40.0: \SMDarkMode colors, per deck, not per view
    "aac9269f3197775e95ffb081672a637f07aae8128b10acd4500d90d94e9b1a66",   # v9.0.0: the same, renamed to SlideMage (names and comments only)
    "8472abb845208dd1946034ce0dcc7acb160dae3626f0a4bd1483802e56fad20e",   # v9.0.0: that template as the project compatibility update leaves it
    "f11225e2236aafe1e426ead9eb73572c1fd2d4bb4fbc2a3fc61b17aafe52b38d",   # v9.0.0: the same on the setup layer (settings only, no view-dependent rule)
    "74e4d515f70f97274875457274acc7746894d40ba245a9e8ce2494f3db9712ff",   # v9.0.0: the v8.40.0 one as the project compatibility update leaves it
    "2952cf64c3057cfcc7e35c2f00e4398e5e96c032603aecf0945c8f22aaf60549",   # v9.1.0: the same with a comment that names \SMFrametitleRightPadding
})
AUDITED_LATEXMKRC = {
    ".latexmkrc": "8273d5f38c719ab1e1064fe07ea27a73de7d423ee7d70b2e7e82312b302a73bc",
    "decks/.latexmkrc": "03c0f5a0a7a825fd3802aeffbdbbd7be90a0bea52e3a1e38d2c127fa488cc0f7",
}

_VIEWS = ("instructor", "during-course", "after-course")
_INPUT = re.compile(r"\\(?:input|include)(?![A-Za-z@])\s*(?:\{([^{}]+)\}|([^\s{}%]+))")
_CONTROL = re.compile(r"\\([A-Za-z@]+|.)")
_DEFINITION = re.compile(r"\\(?:def|gdef|edef|xdef|let|newcommand|renewcommand|providecommand|DeclareRobustCommand|NewDocumentCommand|RenewDocumentCommand|newenvironment|renewenvironment|catcode)\b")
_DYNAMIC = re.compile(r"\\(?:csname|expandafter|ifSMInstructorVersion|ifSMDuringCourseVersion|ifSMAfterCourseVersion|ifdeckversioninlist|SMDeckVersion|SMDeckVersionText|beamer@currentmode|studentversion|deckversion)\b")
_FOOTER_HIDE = re.compile(r"\\def\s*\\SMFooterHide\s*\{([^{}]*)\}")
_SAFE_FOOTER = re.compile(r"\\(?:newcommand|renewcommand|providecommand)\s*\{\\FooterText\}\s*\{[^{}\\]*\}")
_SAFE_VERSION_GUARD = re.compile(r"\\ifdefined\s*\\deckversionoverride\s*\\deckversion\s*\[\\deckversionoverride\]\s*\\else\s*\\deckversion\s*\[[^\]]*\]\s*\\fi")
_SAFE_LANGUAGE_GUARD = re.compile(r"\\ifdefined\s*\\decklanguageoverride\s*\\decklanguage\s*\[\\decklanguageoverride\]\s*\\else\s*\\decklanguage\s*\[[^\]]*\]\s*\\fi")
_SOURCE_SAFE = {
    # Ordinary TeX/Beamer layout and literal content controls. New controls
    # require an audit; unknown controls never establish equivalence.
    "begin", "end", "input", "setSlideVersion", "setSlideID", "setSlideLanguageFromSlug",
    "includegraphics", "graphicspath", "item", "pause", "only", "uncover", "visible",
    "onslide", "alt", "textcolor", "color", "textbf", "textit", "emph", "underline",
    "texttt", "textsf", "textrm", "tiny", "scriptsize", "footnotesize", "small",
    "normalsize", "large", "Large", "vspace", "hspace", "vfill", "hfill",
    "centering", "raggedright", "raggedleft", "linewidth", "textwidth", "paperwidth",
    "paperheight", "newpage", "par", "quad", "qquad", "url", "href", "hyperlink",
    "hypertarget", "frametitle", "framesubtitle", "footnote", "caption", "label",
    "ref",
    "alert", "structure", "enumerate", "multilingualtext", "SMCode", "SMCmd",
    "SMCodeFile", "shrinklists", "setlength", "dimexpr", "relax", "vskip",
    "hskip", "medskip", "smallskip", "bigskip", "newline", "linebreak",
    "SMChapterAgenda", "SMAgendaTitle", "SMLink", "sectionfigure",
    "titleframe", "chapterlogo", "SMFinalStateForStudents", "fullbleedframe",
    "progressstrip", "SMBulletEllipsis", "SMCodeFont", "SMQRCode",
    "deckonly", "deckuncover", "deckvisible", "conditionalpause", "deckreveal",
    "deckrevealfinal", "deckitem", "SMFullBleedLayers", "SMImage", "SMAltImage",
    "SMAltText", "SI", "frac", "sqrt", "left", "right", "times", "cdot",
    "fboxsep", "fcolorbox", "textbackslash", "fontsize", "selectfont",
    "toprule", "midrule", "bottomrule", "node", "fill", "sbox",
    "mathrm", "mathbf", "mathsf", "mathit", "text", "sum", "int", "infty",
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu", "pi",
    "sigma", "phi", "omega", "leq", "geq", "neq", "approx", "rightarrow",
    "Rightarrow", "longrightarrow", "mapsto", "partial", "nabla", "bullet",
    "ldots", "cdots", "dots", "pm", "mp", "percent", "&", "%", "_", "#", "$",
    "{", "}", " ", "\\", ",", ";", ":", "!", "[", "]", "(", ")",
}
_SOURCE_SAFE_ENVIRONMENTS = {
    "frame", "standardframe", "sideimageframe", "figureframe", "quoteframe",
    "sectionframe", "chapterframe", "fullbleedframe", "itemize", "enumerate",
    "columns", "column", "minipage", "center", "flushleft", "flushright",
    "tabular", "tabularx", "SMTable", "tikzillustration", "SMNumItemize",
    "infoblock", "table", "figure", "tikzpicture", "equation",
    "align", "align*", "block", "alertblock", "exampleblock", "overlayarea",
}
_PREAMBLE_SAFE = {
    "documentclass", "input", "begin", "usepackage", "addbibresource",
    "FooterText", "SMFooterHide", "makeatletter", "makeatother", "graphicspath",
    "deckversion", "decklanguage", "hypersetup",
    "SMUseBibliography", "SMBiblatexOptions", "SMBibliographyStyle", "setlength",
    "definecolor", "colorlet", "setbeamercolor", "setbeamerfont", "setbeamertemplate",
}


@dataclass(frozen=True)
class ViewDecision:
    view: str
    group: str | None
    hidden: bool
    certain: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Classification:
    decisions: tuple[ViewDecision, ...]
    evidence: str
    dependencies: tuple[tuple[str, str], ...]

    def group_for(self, view: str) -> str | None:
        return next(d.group for d in self.decisions if d.view == view)


def _digest(data: bytes) -> str:
    # Line endings do not change what TeX reads, and a checkout may give a file either (Git's autocrlf):
    # the audited files are compared without them, or Windows and macOS would never share a render.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _without_comments(source: str) -> str:
    """Remove unescaped TeX comments, retaining line boundaries and offsets."""
    lines = []
    for line in source.splitlines(keepends=True):
        for index, char in enumerate(line):
            if char == "%":
                # Count immediately preceding backslashes, not all earlier ones.
                backslashes = 0
                while index > backslashes and line[index - backslashes - 1] == "\\":
                    backslashes += 1
                if backslashes % 2 == 0:
                    line = line[:index] + ("\n" if line.endswith("\n") else "")
                    break
        lines.append(line)
    return "".join(lines)


def _argument(text: str, offset: int, opening: str, closing: str):
    offset = _space(text, offset)
    if offset >= len(text) or text[offset] != opening:
        return None
    start, depth = offset + 1, 1
    offset += 1
    while offset < len(text):
        if text[offset] == "\\":
            offset += 2
            continue
        if text[offset] == opening:
            depth += 1
        elif text[offset] == closing:
            depth -= 1
            if not depth:
                return text[start:offset], offset + 1
        offset += 1
    return None


def _space(text: str, offset: int) -> int:
    while offset < len(text) and text[offset].isspace():
        offset += 1
    return offset


def _brace_depth(text: str, limit: int) -> int:
    depth = 0
    index = 0
    while index < limit:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    return depth


def _source_tree(text: str, root: Path, origin: Path, dependencies: dict[str, str], seen: set[Path]):
    """Read literal slide inputs using TeX's project/deck-relative candidates.

    Ambiguous or dynamic input fails closed. This intentionally does not guess
    TeX's macro expansion or filesystem search order.
    """
    clean = _without_comments(text)
    if "^^" in clean:
        raise ValueError("TeX character escape in slide/include")
    parts = [clean]
    for match in _INPUT.finditer(clean):
        name = (match[1] or match[2]).strip()
        if "\\" in name or "#" in name or ".." in Path(name).parts:
            raise ValueError(f"dynamic input {name}")
        relative = Path(name)
        if not relative.suffix:
            relative = relative.with_suffix(".tex")
        # latexmk's $do_cd runs the wrapper from decks/. The stock .latexmkrc
        # adds project root to TEXINPUTS. The source file's own directory is
        # not a TeX search root after an \input of that source.
        candidates = [base / relative for base in (root / "decks", root)]
        present = {path.resolve() for path in candidates if path.is_file()}
        if len(present) != 1:
            raise ValueError(f"missing or ambiguous input {name}")
        path = present.pop()
        if path in seen:
            raise ValueError(f"recursive input {name}")
        data = path.read_bytes()
        dependencies[str(path)] = _digest(data)
        parts.append(_source_tree(data.decode("utf-8"), root, path, dependencies, seen | {path}))
    # The actual input statement is retained; all included bodies follow it.
    return "\n".join(parts)


def _framework(ctx, dependencies: dict[str, str]):
    root = ctx.root.resolve()
    env = compiler.build_env(ctx)
    if env.get("TEXINPUTS"):
        return "custom TEXINPUTS search path"
    if env.get("LATEXMKRCSYS"):
        return "custom system latexmk configuration"
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    for user_rc in (home / ".latexmkrc", Path(env.get("XDG_CONFIG_HOME", str(home / ".config"))) / "latexmk" / "latexmkrc"):
        if user_rc.exists():
            return f"user latexmk configuration: {user_rc}"
    system_rc = Path("/etc/LatexMk")
    if system_rc.exists():
        try:
            system_text = system_rc.read_text().strip()
        except OSError:
            return "system latexmk configuration unreadable"
        if system_text not in ("", "$pdf_mode = 4;"):
            return "custom system latexmk configuration"
        dependencies[str(system_rc)] = _digest(system_rc.read_bytes())
    rc = root / ".latexmkrc"
    try:
        rc_digest = _digest(rc.read_bytes())
    except OSError:
        return "project latexmk search configuration unavailable"
    dependencies[str(rc)] = rc_digest
    if rc_digest != AUDITED_LATEXMKRC[".latexmkrc"]:
        return "unaudited project latexmk search configuration"
    deck_rc = root / "decks" / ".latexmkrc"
    if deck_rc.exists():
        deck_digest = _digest(deck_rc.read_bytes())
        dependencies[str(deck_rc)] = deck_digest
        if deck_digest != AUDITED_LATEXMKRC["decks/.latexmkrc"]:
            return "unaudited deck latexmk search configuration"
    # The pinned stock .latexmkrc uses this exact fallback when the variable
    # is absent. Path('') would instead inspect the process CWD.
    framework = Path(env["SLIDEMAGE_LATEX"]) if env.get("SLIDEMAGE_LATEX") else root.parent / "latex"
    if not framework.is_dir():
        return "audited framework directory unavailable"
    for name, expected in AUDITED_FRAMEWORK.items():
        path = framework / name
        for shadow in (root / name, root / "decks" / name):
            if shadow.is_file() and shadow.resolve() != path.resolve():
                return f"project shadows {name}"
        try:
            actual = _digest(path.read_bytes())
        except OSError:
            return f"framework file missing: {name}"
        dependencies[str(path.resolve())] = actual
        if actual != expected:
            return f"unaudited framework file: {name}"
    try:
        for base in (root / "decks", root, framework):
            for path in (*base.glob("*.sty"), *base.glob("*.cls")):
                if path.name not in AUDITED_FRAMEWORK:
                    return f"custom package/class in TeX search path: {path.name}"
    except OSError:
        return "TeX search path inventory unavailable"
    return None


def _preamble(spec, dependencies: dict[str, str]):
    target = spec.target
    root = target.context.root.resolve()
    try:
        default = slide_preview.default_preamble(target.context)
    except OSError:
        return False, "default template unavailable"
    text = target.preamble_text if target.preamble_text is not None else default
    clean = _without_comments(text)
    if "^^" in clean:
        return False, "TeX character escape in preamble"
    if _digest(slide_preview.GENERIC_PREAMBLE.encode()) != AUDITED_GENERIC_PREAMBLE:
        return False, "unaudited bundled generic preamble"
    if len(re.findall(r"\\documentclass\b", clean)) != 1:
        return False, "ambiguous document class"
    # Since v9.0.0 the template loads the theme (SlideMage_setup); a deck that loads one itself is unaudited.
    if re.search(r"\\use(?:theme|colortheme|fonttheme|innertheme|outertheme)\b", clean):
        return False, "deck loads a theme itself"
    class_match = re.search(r"\\documentclass(?:\[(?:aspectratio=169)?\])?\s*\{beamer\}", clean)
    if not class_match or _brace_depth(clean, class_match.start()) != 0:
        return False, "unclassified document class"
    hide = list(_FOOTER_HIDE.finditer(clean))
    if len(hide) > 1:
        return False, "multiple footer hide definitions"
    if hide and _brace_depth(clean, hide[0].start()) != 0:
        return False, "scoped or delayed footer hide definition"
    deck_hidden = bool(hide and "deck" in {x.strip() for x in hide[0][1].split(",")})
    # The wrapper calls deckversion/decklanguage after the preamble. The
    # standard preamble override doors are therefore safe; other conditional
    # or definition code may mutate a theme or version-sensitive macro.
    reduced = _SAFE_FOOTER.sub("", clean)
    reduced = _FOOTER_HIDE.sub("", reduced)
    reduced = _SAFE_VERSION_GUARD.sub("", reduced)
    reduced = _SAFE_LANGUAGE_GUARD.sub("", reduced)
    reduced = re.sub(r"\\documentclass(?:\[(?:aspectratio=169)?\])?\s*\{beamer\}", "", reduced)
    framework_imports = []
    for match in _INPUT.finditer(reduced):
        name = match[1] or match[2]
        if name.startswith("SlideMage_template_"):
            framework_imports.append(name)
            if _brace_depth(reduced, match.start()) != 0:
                return deck_hidden, "scoped or delayed framework import"
            if name != "SlideMage_template_slidemage":
                path = root / f"{name}.tex"
                if (root / "decks" / path.name).exists():
                    return deck_hidden, "deck shadows institution preamble"
                try:
                    digest = _digest(path.read_bytes())
                except OSError:
                    return deck_hidden, "institution preamble unavailable"
                dependencies[str(path.resolve())] = digest
                if digest not in AUDITED_PROJECT_TEMPLATES:
                    return deck_hidden, "unaudited institution preamble"
        else:
            return deck_hidden, f"custom preamble input {name}"
    if len(framework_imports) != 1:
        return deck_hidden, "expected one top-level audited framework import"
    if text == default:
        return deck_hidden, None
    # A custom package can patch the footer or any supported macro at load
    # time. Only the bundled generic bibliography import is audited here.
    for match in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\s*\{([^{}]*)\}", reduced):
        return deck_hidden, f"unclassified package {match[1]}"
    if re.search(r"\\(?:addbibresource|bibliography|SMUseBibliography)\b", reduced):
        return deck_hidden, "unclassified bibliography setup"
    if _DEFINITION.search(reduced) or _DYNAMIC.search(reduced):
        return deck_hidden, "custom preamble definition or version condition"
    if re.search(r"\\(?:if[A-Za-z@]*|else|fi)\b", reduced):
        return deck_hidden, "unclassified preamble conditional"
    for match in _CONTROL.finditer(reduced):
        if match[1] not in _PREAMBLE_SAFE:
            return deck_hidden, f"unclassified preamble command \\{match[1]}"
    return deck_hidden, None


def _events(text: str, view: str, *, final: bool):
    """Return the audited view-dependent operations in source order."""
    events = []
    for match in re.finditer(r"\\(?:begin|end)\s*\{([^{}]+)\}", text):
        if match[1] not in _SOURCE_SAFE_ENVIRONMENTS:
            raise ValueError(f"unclassified environment {match[1]}")
        if match[0].startswith("\\begin") and match[1] == "fullbleedframe":
            images = _argument(text, match.end(), "{", "}")
            if images is None or "\\" in images[0]:
                raise ValueError("dynamic fullbleedframe image list")
            if len(images[0].split(",")) > 1:
                events.append(("fullbleedframe", "instructor" if view == "instructor" else "student"))
    for match in _CONTROL.finditer(text):
        name, end = match[1], match.end()
        if name not in _SOURCE_SAFE:
            raise ValueError(f"unclassified source command \\{name}")
        if name == "conditionalpause":
            arg = _argument(text, end, "[", "]")
            versions = _versions(arg[0]) if arg else {"instructor"}
            if versions is None:
                raise ValueError("dynamic conditionalpause version list")
            events.append((name, "noop" if final else ("pause" if view in versions else "noop")))
        elif name in ("deckonly", "deckuncover", "deckvisible"):
            overlay = _argument(text, end, "<", ">")
            pos = overlay[1] if overlay else end
            versions = _argument(text, pos, "[", "]")
            listed = _versions(versions[0]) if versions else set(_VIEWS)
            if listed is None:
                raise ValueError(f"dynamic {name} version list")
            events.append((name, overlay[0] if overlay else "1-", "emit" if view == "instructor" or view in listed else "omit"))
        elif name == "deckreveal":
            events.append((name, ("overlay" if view == "instructor" else "omit" if view == "during-course" else "content")))
        elif name in ("deckrevealfinal", "deckitem", "SMFullBleedLayers", "SMFinalStateForStudents"):
            events.append((name, "instructor" if view == "instructor" else "student"))
        elif name == "fullbleedframe":
            images = _argument(text, end, "{", "}")
            if images is None or "\\" in images[0]:
                raise ValueError("dynamic fullbleedframe image list")
            if len(images[0].split(",")) > 1:
                events.append((name, "instructor" if view == "instructor" else "student"))
        elif name in ("ifSMInstructorVersion", "ifSMDuringCourseVersion", "ifSMAfterCourseVersion",
                      "ifdeckversioninlist", "SMDeckVersion", "SMDeckVersionText", "studentversion",
                      "deckversion", "csname", "expandafter", "inputlineno"):
            raise ValueError(f"unclassified source command \\{name}")
    return tuple(events)


def _versions(value: str):
    parts = {part.strip() for part in value.split(",")}
    return parts if parts <= set(_VIEWS) and "" not in parts else None


def classify_views(requests) -> Classification:
    """Classify resolved requests; one signature means identical ordered images.

    Call this after capture/resolution and again whenever any dependency or the
    contract changes. Unknown inputs receive a unique per-view group.
    """
    requests = tuple(requests)
    dependencies: dict[str, str] = {}
    frameworks = {}
    signatures = []
    decisions = []
    for spec in requests:
        if spec.target.hidden and not spec.options.presenter:
            signatures.append(None)
            decisions.append(ViewDecision(spec.view, None, True, True, ("hidden by resolved deck call",)))
            continue
        reasons = []
        local_dependencies = {}
        root = spec.target.context.root.resolve()
        if root not in frameworks:
            framework_dependencies = {}
            try:
                framework_problem = _framework(spec.target.context, framework_dependencies)
            except OSError as exc:
                framework_problem = f"framework search failed: {exc}"
            frameworks[root] = framework_problem, framework_dependencies
        problem, framework_dependencies = frameworks[root]
        local_dependencies.update(framework_dependencies)
        if problem is None:
            try:
                deck_hidden, problem = _preamble(spec, local_dependencies)
            except OSError as exc:
                deck_hidden, problem = False, f"preamble inspection failed: {exc}"
        else:
            deck_hidden = False
        text = _without_comments(spec.revision.text)
        try:
            source = _source_tree(text, root, spec.revision.path, local_dependencies,
                                  {spec.revision.path.resolve()})
            if _DEFINITION.search(source):
                raise ValueError("custom slide/include definition")
            events = _events(source, spec.view, final=spec.target.macro == "slidefinal")
        except (OSError, UnicodeError, ValueError) as exc:
            events = ()
            problem = problem or str(exc)
        if spec.capture_error:
            problem = problem or spec.capture_error
        if spec.options.presenter or spec.options.mode != "slide":
            problem = problem or "unsupported preview scope"
        if problem:
            reasons.append(problem)
        else:
            reasons.extend(f"{event[0]}: {event[-1]}" for event in events)
            reasons.append("deck label hidden" if deck_hidden else "view-specific footer deck label")
        # Do not compare target.key: it contains logical call/occurrence data
        # that can differ even when all effective rendering inputs are equal.
        try:
            preamble = spec.target.preamble_text if spec.target.preamble_text is not None else slide_preview.default_preamble(spec.target.context)
        except OSError:
            preamble = ""
            if not problem:
                problem = "default template unavailable"
                reasons.append(problem)
        dependencies.update(local_dependencies)
        common = (str(root), str(spec.revision.path), spec.revision.content_hash, spec.language,
                  spec.target.id_slug, spec.target.version, spec.target.frame_number,
                  spec.target.steps, spec.target.macro == "slidefinal",
                  spec.target.macro in ("omitslide", "omitslideversion"),
                  spec.target.occurrence_key,
                  preamble, tuple(sorted(local_dependencies.items())),
                  spec.options.mode, spec.options.overlay)
        signature = (common, events, None if deck_hidden else spec.view)
        if problem:
            signature += ("unknown", spec.view, str(spec.target.occurrence_key))
        signatures.append(signature)
        decisions.append(ViewDecision(spec.view, "", False, not bool(problem), tuple(reasons)))
    groups = {}
    final = []
    for decision, signature in zip(decisions, signatures):
        if signature is None:
            final.append(decision)
            continue
        key = json.dumps(signature, sort_keys=True, default=str)
        group = groups.setdefault(key, "group-" + _digest(key.encode())[:16])
        final.append(ViewDecision(decision.view, group, False, decision.certain, decision.reasons))
    evidence = _digest(json.dumps((CONTRACT, sorted(dependencies.items()),
            [(s.view, s.revision.content_hash, s.revision.path.as_posix(),
              {k: v for k, v in s.options.__dict__.items() if k not in ("force", "render_stamp", "saved")})
             for s in requests]), sort_keys=True, default=str).encode())
    return Classification(tuple(final), evidence, tuple(sorted(dependencies.items())))
