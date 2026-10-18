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
AUDITED_GENERIC_PREAMBLE = "8ba8bfb858ab149ed9d40ba4b04ba659154d8cfea514d6ca4f16af76e2a479d3"
AUDITED_FRAMEWORK = {
    "Slidemaster_preamble_base.tex": "6c5eae1bb83825875b2307663379f2241a1abfb974ec3ddd160f8d33e935c381",
    "Slidemaster_preamble_slidemage.tex": "8eee5a8bad196bac2ed4c423bae1042865d43146b049d2a4500e6623c840fd51",
    "beamerthemegotham.sty": "7f0fb3fb09c9e0279fa41baba4660b247bc3cfd1cf9ba9fc7dab10ed1426b230",
    "beamerouterthemegotham.sty": "a80d1db0bd836b16b598631094ce58a3102ef81c1b3a216cf6176a55e7301ac0",
    "beamerinnerthemegotham.sty": "8d8e222da0a03c3515a6e61c0f03784c91e232c73675eacd3327dc3b09aaa8a1",
    "beamercolorthemegotham.sty": "8ee739f7b46eaf04e03223c188ea49d287db9a891ab1da3b3f57f8d7e0fee573",
    "beamerfontthemegotham.sty": "3a6cc4900c36f0cc783e02d23244a1ac24d78ca8af5ae8e6d650eea5ec423952",
    "Slidemaster_alt.lua": "d623ebee0117d3e47ae885d7176dfafd9015bb32f9b3814b7d5f3d173f976ece",
    "Slidemaster_layout.lua": "59b553f969a7acd937295554c988af5f691837831911bfaa1d43f5e3b009a04b",
}
AUDITED_PROJECT_TEMPLATES = {
    "Slidemaster_preamble_uni-graz.tex": "b9be6f396344cd3c65c0b3fb7160891b451ebef0e8f0e69cbbaacc7237c4401e",
}
AUDITED_LATEXMKRC = {
    ".latexmkrc": "9ba59a7e4bf3f71f68bb7e1383177293d6ed26be71272a250c99cde3068f14d5",
    "decks/.latexmkrc": "cfc5d6cacec9d655398f5f6c441fc626d240851dfa64ae74eb6f8d5cddb1e85f",
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
    "progressstrip", "SMBulletEllipsis", "SMCodeFont",
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
    "tabular", "tabularx", "gothamtable", "tikzillustration", "gothamnumitemize",
    "infoblock", "table", "figure", "tikzpicture", "equation",
    "align", "align*", "block", "alertblock", "exampleblock", "overlayarea",
}
_PREAMBLE_SAFE = {
    "documentclass", "usetheme", "input", "begin", "usepackage", "addbibresource",
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
    return hashlib.sha256(data).hexdigest()


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
    framework = Path(env["SLIDEMASTER_LATEX"]) if env.get("SLIDEMASTER_LATEX") else root.parent / "latex"
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
    if len(re.findall(r"\\usetheme\b", clean)) != 1:
        return False, "ambiguous theme"
    class_match = re.search(r"\\documentclass(?:\[(?:aspectratio=169)?\])?\s*\{beamer\}", clean)
    if not class_match or _brace_depth(clean, class_match.start()) != 0:
        return False, "unclassified document class"
    theme_match = re.search(r"\\usetheme\s*\{gotham\}", clean)
    if not theme_match or _brace_depth(clean, theme_match.start()) != 0:
        return False, "unclassified theme"
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
    reduced = re.sub(r"\\usetheme\s*\{gotham\}", "", reduced)
    framework_imports = []
    for match in _INPUT.finditer(reduced):
        name = match[1] or match[2]
        if name.startswith("Slidemaster_preamble_"):
            framework_imports.append(name)
            if _brace_depth(reduced, match.start()) != 0:
                return deck_hidden, "scoped or delayed framework import"
            if name not in ("Slidemaster_preamble_slidemage", "Slidemaster_preamble_uni-graz"):
                return deck_hidden, f"unclassified preamble {name}"
            if name == "Slidemaster_preamble_uni-graz":
                path = root / "Slidemaster_preamble_uni-graz.tex"
                if (root / "decks" / path.name).exists():
                    return deck_hidden, "deck shadows institution preamble"
                try:
                    digest = _digest(path.read_bytes())
                except OSError:
                    return deck_hidden, "institution preamble unavailable"
                dependencies[str(path.resolve())] = digest
                if digest != AUDITED_PROJECT_TEMPLATES[path.name]:
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
                  spec.options.footer_timestamp,
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
