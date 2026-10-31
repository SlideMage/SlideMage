# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check a SlideMage layout profile against a compiled calibration deck.

A layout profile (latex/SlideMage_layout_<name>.tex) holds the font files and the font's metrics, and since v10.9.0
no length measured against the rendered PDF: everything follows from the font where it is used, from the page, or is
a hook of the catalog (v10.7.0-v10.9.0): where the title bar ends, the right edges of the frame number and the
footnotes, where the footer number sits in its box, the label and numeral boxes of the lists, the footnotes' offset,
the section frame's corrections and the pull-up of the frames the automatic Top Margin does not correct by their
content (\\SMContentTopShift and the two columns corrections, measured from where the frame's body begins). This tool
compiles the calibration deck (tests/fixtures/template_stress/decks/calibration.tex) with the profile under the
SlideMage template, whose hooks are the catalog's defaults, measures the PDF and checks each derived value against
the geometry its hooks ask for (the footer number's ink centred in the box, the label gap, the numeral slot and gap,
the footnotes' clearance above the footer, the section bar's height, the first line of the three manual-top frames
on the Top Margin). tools/check_layout.py then says whether the profile is clean.

Recipe for a new profile (the header of latex/SlideMage_setup.tex has it too):
  1. copy latex/SlideMage_layout_fira.tex to latex/SlideMage_layout_<name>.tex and change the fonts;
  2. python tools/calibrate_font_profile.py --profile <name>
     every check should read "ok" (within the tolerance of the measurement, 0.3pt unless the check says);
  3. python tools/check_layout.py on the PDF of the deck compiled with a template that picks the profile
     (the project's stress-test template does); then adjust until the report is clean.
The last section of the output reports what the base derives from the font and the template, read back from
the PDF: the title bar's bottom edge, the Top Margin, the ascender, and how far the frame number's and the
footnotes' right edges are from the logo's visible edge.

usage: python tools/calibrate_font_profile.py --profile NAME [--template slidemage] [--project DIR]
           [--deck decks/calibration.tex] [--framework DIR] [--pdf FILE] [--keep-pdf FILE]
With --pdf the compile is skipped and FILE is measured (the profile's current values are still read from
--framework). Exit code 0 when every check is ok, 1 when one fails.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_layout as cl  # noqa: E402  (the measuring code: Page, pdf_info, the PDF's own margins)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO / "tests" / "fixtures" / "template_stress"
DEFAULT_DECK = "decks/calibration.tex"
PT = 72.27 / 72                  # TeX points per PDF point (bp)
TOLERANCE = 0.3                  # pt: below this a measurement says "ok"
EDGE_INSET = 0.15                # bp: the footer number's pixel scan keeps this far inside the box's edges
SECTION_BOX_HEIGHT = "SMSectionframeBoxHeight"
TEMPLATE_INPUT_RE = re.compile(r"\\input\{SlideMage_template_[^}]+\}")
SET_RE = r"\\setlength\{\\%s\}\{([^}]*)\}"
COMPILE_TIMEOUT_SECONDS = 600


@dataclass
class Check:
    """A derived value against the geometry its hooks ask for: `measured` and `expected` in pt."""
    name: str            # what is checked, e.g. "footnote clearance above the footer"
    measured: float | None
    expected: float | None
    note: str
    tolerance: float = TOLERANCE

    @property
    def ok(self) -> bool:
        return self.measured is None or self.expected is None or abs(self.measured - self.expected) <= self.tolerance


# ---------------------------------------------------------------- reading values out of the TeX files

def tex_length(text: str, name: str) -> float | None:
    """The value in pt of `\\setlength{\\name}{<number>pt}` in `text` (the last one), None if absent."""
    found = re.findall(SET_RE % re.escape(name), text)
    if not found:
        return None
    m = re.fullmatch(r"\s*(-?[\d.]+)\s*(pt|bp)\s*", found[-1])
    if not m:
        return None
    return float(m.group(1)) * (PT if m.group(2) == "bp" else 1.0)


def profile_text(framework: Path, profile: str) -> str:
    path = framework / f"SlideMage_layout_{profile}.tex"
    if not path.is_file():
        raise SystemExit(f"no layout profile {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- writing a new profile (--new, v10.18.0)

ASCENDER_RE = re.compile(r"(\\newcommand\{\\SMFontAscender\}\{)([^}]*)(\})")


@dataclass
class ProfileFonts:
    """The font files of a new profile: the text font's four faces and the mono font's three."""
    regular: str
    italic: str
    bold: str
    bold_italic: str
    mono: str = "lmmono10-regular.otf"
    mono_italic: str = "lmmono10-italic.otf"
    mono_bold: str = "lmmonolt10-bold.otf"
    inline_code_scale: str = "0.95"


def font_on_path(name: str) -> bool:
    """Whether `name` is a font file TeX finds (kpsewhich), so a typo stops here, not in a compile's log."""
    try:
        found = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True                    # no kpsewhich to ask: the compile's own font check reports it
    return bool(found)


def new_profile_text(name: str, fonts: ProfileFonts, description: str, linespread: str, parskip: str,
                     ascender: str = "0.8") -> str:
    """The text of a new layout profile with these fonts, structured like the shipped ones. The text font is
    beamer's sans family whatever its design: beamer typesets frames in \\sffamily, so a serif font goes there too
    (and to \\rmfamily, for \\textrm). \\SMFontAscender starts as a placeholder that `--new` replaces with the value
    the base reads from the loaded font."""
    faces = ", ".join((fonts.regular, fonts.italic, fonts.bold, fonts.bold_italic))
    mono_faces = ", ".join((fonts.mono, fonts.mono_italic, fonts.mono_bold))
    header = "\n".join(textwrap.wrap(f'SlideMage layout profile "{name}": {description}'.rstrip(": "), 96,
                                     initial_indent="% ", subsequent_indent="% "))
    family = (f"[\n            ItalicFont = {{ {fonts.italic} }},\n            BoldFont = {{ {fonts.bold} }},\n"
              f"            BoldItalicFont = {{ {fonts.bold_italic} }}\n          ]\n          {{ {fonts.regular} }}")
    return f"""% SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
% SPDX-License-Identifier: LPPL-1.3c+
{header}
%
% Written by tools/calibrate_font_profile.py --new, which also read \\SMFontAscender from
% the compiled font and checked the profile against the calibration deck. A template picks it with
%
%   \\newcommand{{\\SMLayoutProfile}}{{{name}}}   % before \\input{{SlideMage_setup}}
%
% See SlideMage_layout_fira.tex for what a profile is and what it has to define; the
% header of SlideMage_setup.tex has the recipe for a new one.

\\RequirePackage{{etoolbox}}

\\ExplSyntaxOn
\\makeatletter

\\msg_new:nnn {{ SlideMage }} {{ font-not-found }}
  {{ Could~not~find~font~'#1'.\\c_space_tl }}
\\msg_new:nnn {{ SlideMage }} {{ fonts-not-available }}
  {{ No~suitable~fonts~found.~Using~fallback~fonts. }}
\\msg_new:nnn {{ SlideMage }} {{ requires-lualatex }}
  {{ The~SlideMage~layout~profile~needs~LuaLaTeX~(OpenType~fonts~and~Lua~code). }}

\\int_new:N \\g__SM_fonts_not_found_int

\\cs_new_protected:Nn \\__SM_check_font:n
  {{
    \\fontspec_font_if_exist:nF {{ #1 }}
      {{
        \\fontspec_font_if_exist:nF {{ #1~Regular }}
          {{
            \\int_incr:N \\g__SM_fonts_not_found_int
            \\msg_warning:nnn {{ SlideMage }} {{ font-not-found }} {{ #1 }}
          }}
      }}
  }}

\\cs_new_protected:Nn \\__SM_if_fonts_available:nnn
  {{
    \\int_zero:N \\g__SM_fonts_not_found_int
    \\clist_map_function:nN {{ #1 }} \\__SM_check_font:n
    \\int_compare:nTF {{ \\g__SM_fonts_not_found_int = 0 }} {{ #2 }} {{ #3 }}
  }}

% Text and code fonts. fontspec loads with no-math, so that the text font is in charge of
% text only; the math fonts are restored further down. Beamer typesets a frame in its sans
% family, so the text font is \\setsansfont whatever its design, and \\setmainfont as well, so
% that \\textrm and \\rmfamily give the same face.
\\sys_if_engine_luatex:TF
  {{
    \\@ifpackageloaded {{ fontspec }}
      {{ \\PassOptionsToPackage {{ no-math }} {{ fontspec }} }}
      {{ \\RequirePackage [ no-math ] {{ fontspec }} }}
    \\__SM_if_fonts_available:nnn
      {{ {faces} }}
      {{
        \\setsansfont
          {family}
        \\setmainfont
          {family}
        \\renewcommand {{ \\ttdefault }} {{ lmtt }}
      }}
      {{ \\msg_warning:nn {{ SlideMage }} {{ fonts-not-available }} }}
    \\__SM_if_fonts_available:nnn
      {{ {mono_faces} }}
      {{
        \\setmonofont
          [
            ItalicFont = {{ {fonts.mono_italic} }},
            BoldFont = {{ {fonts.mono_bold} }}
          ]
          {{ {fonts.mono} }}
      }}
      {{ \\msg_warning:nn {{ SlideMage }} {{ fonts-not-available }} }}
  }}
  {{ \\msg_warning:nn {{ SlideMage }} {{ requires-lualatex }} }}

\\makeatother
\\ExplSyntaxOff

% Metrics -----------------------------------------------------------------------
% The ascender of the text font in em. SlideMage_base.tex reads it from the loaded font
% (luaotfload's OpenType metrics) and keeps this number only where the font gives none;
% calibrate_font_profile.py --new wrote the value the base read.
\\newcommand{{\\SMFontAscender}}{{{ascender}}}
% Running text: \\linespread and \\parskip. The theme applies them where it is loaded, with
% the normal font in force, so the em is this font's.
\\newcommand{{\\SMLinespread}}{{{linespread}}}
\\newcommand{{\\SMParskip}}{{{parskip}}}

% Code fonts ----------------------------------------------------------------------
% \\SMCodeFile (listings) and the like; the theme's \\ttfamily is the same font.
\\newfontfamily\\SMCodeFont{{{fonts.mono}}}[BoldFont={fonts.mono_bold}]
% Code in running text (\\SMCode, \\SMCmd), Ligatures=TeXOff so that -- and `` show as typed
% (see the Fira profile).
\\newfontfamily\\SMInlineCodeFont{{{fonts.mono}}}[Scale={fonts.inline_code_scale}, Ligatures=TeXOff]
% The heading of a card in a diagram (\\SMCard).
\\newcommand{{\\SMCardHeadingFont}}{{\\bfseries}}

% Math ------------------------------------------------------------------------------
% Genuine Computer Modern math next to the text, and \\text{{}} upright in Computer Modern,
% as in the Fira profile (SlideMage_layout_fira.tex has the reasons).
\\usefonttheme[onlymath]{{serif}}
\\let\\SMOrigText\\text
\\renewcommand{{\\text}}[1]{{\\SMOrigText{{\\usefont{{OT1}}{{cmr}}{{m}}{{n}}#1}}}}
"""


def write_new_profile(args: argparse.Namespace, framework: Path, project: Path) -> Path:
    """`--new`: write latex/SlideMage_layout_<name>.tex from the font files given, compile the calibration deck with
    it once to read the ascender the base takes from the font, and write that into the profile."""
    fonts = ProfileFonts(args.text_regular, args.text_italic, args.text_bold, args.text_bold_italic,
                         args.mono, args.mono_italic, args.mono_bold, args.inline_code_scale)
    missing = [f for f in (fonts.regular, fonts.italic, fonts.bold, fonts.bold_italic, fonts.mono,
                           fonts.mono_italic, fonts.mono_bold) if not font_on_path(f)]
    if missing:
        raise SystemExit(f"TeX finds no font file {', '.join(missing)} (kpsewhich)")
    path = framework / f"SlideMage_layout_{args.profile}.tex"
    if path.exists() and not args.force:
        raise SystemExit(f"{path} exists; --force overwrites it")
    text = new_profile_text(args.profile, fonts, args.description, args.linespread, args.parskip)
    path.write_text(text, encoding="utf-8", newline="\r\n")   # CRLF, as the shipped profiles
    probe = Path(tempfile.mkdtemp(prefix="calibrate-new-")) / "ascender.pdf"
    compile_deck(project, args.deck, args.template, args.profile, framework, probe)
    doc = fitz.open(probe)
    ascender = info_bp(doc, "SMFontAscender")
    doc.close()
    if ascender is None:
        raise SystemExit("the compiled deck has no SMFontAscender key; the profile keeps the placeholder 0.8")
    path.write_text(ASCENDER_RE.sub(lambda m: f"{m.group(1)}{ascender:g}{m.group(3)}", text, count=1),
                    encoding="utf-8", newline="\r\n")
    print(f"wrote {path} (ascender {ascender:g}em, read from {fonts.regular})")
    return path


# ---------------------------------------------------------------- compiling

def compile_deck(project: Path, deck: str, template: str, profile: str | None, framework: Path, out_pdf: Path) -> None:
    """Compile `deck` with its template input swapped for `template` under `profile` (None: the template picks its
    own, as the stress-test template does); leave the PDF at out_pdf."""
    deck_path = project / deck
    text = deck_path.read_text(encoding="utf-8")
    pick = f"\\newcommand{{\\SMLayoutProfile}}{{{profile}}}" if profile else ""
    swapped, n = TEMPLATE_INPUT_RE.subn(lambda _m: f"{pick}\\input{{SlideMage_template_{template}}}", text, count=1)
    if n != 1:
        raise SystemExit(f"{deck}: no \\input{{SlideMage_template_<key>}} line to swap")
    jobname = f"calibrate-{profile or 'own'}-{template}"
    # The wrapper sits beside the deck (its \input paths are the deck's); a name of its own per call, so that two
    # compiles of the same deck at once (the tests run in parallel) do not share it. The job name stays.
    wrapper = deck_path.parent / f"_{jobname}-{uuid.uuid4().hex[:8]}.tex"
    wrapper.write_text(swapped, encoding="utf-8", newline="")
    build = Path(tempfile.mkdtemp(prefix="calibrate-"))
    env = dict(os.environ, SLIDEMAGE_LATEX=str(framework), SOURCE_DATE_EPOCH="1700000000")
    cmd = ["latexmk", "-f", "-interaction=nonstopmode", f"-jobname={jobname}", f"-outdir={build.as_posix()}",
           f"-auxdir={build.as_posix()}", wrapper.relative_to(project).as_posix()]
    try:
        subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, errors="replace",
                       timeout=COMPILE_TIMEOUT_SECONDS)
    finally:
        wrapper.unlink(missing_ok=True)
    pdf = build / f"{jobname}.pdf"
    if not pdf.is_file():
        log = build / f"{jobname}.log"
        tail = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.is_file() else "no log"
        raise SystemExit(f"the calibration deck did not compile; end of the log:\n{tail}")
    shutil.copy2(pdf, out_pdf)
    shutil.rmtree(build, ignore_errors=True)


# ---------------------------------------------------------------- measuring

class Deck:
    """A compiled calibration deck: its pages by slide id, and the numbers its PDF carries."""

    def __init__(self, path: Path):
        self.doc = fitz.open(path)
        self.info = cl.pdf_info(self.doc)
        self.pages: dict[str, list[fitz.Page]] = {}
        for page in self.doc:
            m = cl.ID_RE.search(page.get_text())
            if m:
                self.pages.setdefault(m.group(1), []).append(page)

    def page(self, slide_id: str) -> fitz.Page | None:
        pages = self.pages.get(slide_id)
        return pages[-1] if pages else None

    def chrome(self, page: fitz.Page) -> cl.Page:
        i = self.info
        return cl.Page(page, i["top_margin"], i["left_margin"], i["ascender"], i["title_bar_bottom"])

    def first_line_top(self, slide_id: str) -> float | None:
        """The top of the first body text line of a slide, in bp (the checker's measure: baseline minus ascender)."""
        page = self.page(slide_id)
        if page is None:
            return None
        texts = [r.y0 for kind, r, _ in self.chrome(page).items if kind == "text"]
        return min(texts) if texts else None


def words(page: fitz.Page) -> list[tuple[float, float, float, float, str]]:
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def spans(page: fitz.Page) -> list[dict]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            out.extend(s for s in line["spans"] if s["text"].strip())
    return out


def frame_number_span(page: fitz.Page, chrome: cl.Page) -> dict | None:
    """The frame number: the rightmost digits inside the footer box."""
    found = [s for s in spans(page) if s["bbox"][1] >= chrome.footer_top - 1 and s["text"].strip().isdigit()]
    return max(found, key=lambda s: s["bbox"][2]) if found else None


def footer_text_gaps(page: fitz.Page, chrome: cl.Page, number: dict) -> tuple[float, float]:
    """The gap (bp) above and below the ink of the frame number inside the footer box, from pixels."""
    dpi = 1152
    x0, x1 = number["bbox"][0] - 0.3, min(number["bbox"][2] + 0.3, chrome.w - 0.3)
    # The clip stays EDGE_INSET inside the box: its edge rows are antialiased against the canvas, and with a
    # mid-grey box (the greyscale template's, v10.18.0) they differ from the box colour by more than the threshold,
    # which put "ink" on the box's edges and made the check pass whatever the number did.
    clip = fitz.Rect(x0, chrome.footer_top + EDGE_INSET, x1, chrome.h - EDGE_INSET)
    pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
    samples, n = pix.samples, pix.n
    background = samples[0:3]
    rows = [y for y in range(pix.height)
            if any(max(abs(samples[(y * pix.width + x) * n + k] - background[k]) for k in range(3)) > 60
                   for x in range(pix.width))]
    if not rows:
        raise SystemExit("no ink found in the footer's frame number")
    top = clip.y0 + rows[0] * 72 / dpi
    bottom = clip.y0 + (rows[-1] + 1) * 72 / dpi
    return top - chrome.footer_top, chrome.h - bottom


def info_bp(doc: fitz.Document, key: str) -> float | None:
    """A number the base wrote into the PDF's info dictionary (in bp), None if the PDF lacks it."""
    try:
        kind, ref = doc.xref_get_key(-1, "Info")
        if kind != "xref":
            return None
        kind, value = doc.xref_get_key(int(ref.split()[0]), key)
        return float(value) if kind in ("string", "real", "int") else None
    except (ValueError, RuntimeError):
        return None


def em_default(text: str, name: str) -> float | None:
    """`\\name`'s value in em, from `\\newcommand{\\name}{<number>em}` (the catalog's default) or
    `\\renewcommand{\\name}{<number>em}` (a template's override of it, e.g. the stress template's)."""
    found = re.findall(r"\\(?:re)?newcommand\{\\%s\}\{(-?[\d.]+)em\}" % re.escape(name), text)
    return float(found[-1]) if found else None


def template_text(project: Path, framework: Path, template: str) -> str:
    """The named template's own file (the project's, else a shipped one), empty if there is none: a template
    can override a catalog hook (`\\renewcommand`/`\\setlength`), which the expected geometry must then follow
    instead of the catalog's default -- the stress template changes every hook this tool checks (plan section F)."""
    name = f"SlideMage_template_{template}.tex"
    for base in (project, framework):
        path = base / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def label_gap(page: fitz.Page, body_top: float = 0.0) -> list[tuple[str, float, float]]:
    """(label, gap in pt, label size in pt) for each list label that has the item's text in a span of its own after it.
    `body_top` excludes the title bar: its running text can coincidentally split into a span that reads as a label
    (e.g. a title ending "...1. and a. labels" split by justification spacing) -- a false match in a different font
    at a different size, nothing to do with \\SMLabelItemGap, which skewed a profile's "worst" label picked below."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            sp = [s for s in line["spans"] if s["text"].strip()]
            for first, second in zip(sp, sp[1:]):
                if first["bbox"][1] < body_top:
                    continue
                if re.fullmatch(r"[a-z0-9][).]", first["text"].strip()):
                    out.append((first["text"].strip(), (second["bbox"][0] - first["bbox"][2]) * PT, first["size"] * PT))
                    break
    return out


FONT_FILE_RE = re.compile(r"([\w-]+)\.(?:otf|ttf)\b")
# TeX's math fonts; LM Roman italic is the math letters' font under some profiles (E, R in $E[R]$), and Times-Roman an
# empty font entry of the SlideMage logo's PDF
MATH_FONT_RE = re.compile(r"^(?:CM|LMMath|LMRoman\d+-Italic$|MSAM|MSBM|EUSM|EUFM|EUEX|LASY|Times-Roman$|Symbol$)")


def fonts_outside_profile(doc: fitz.Document, framework: Path, profile: str) -> list[str]:
    """The fonts the pages themselves use (not those inside an included PDF figure, which brings its own) that are
    neither a font file the profile names nor TeX's math fonts: a text font that still comes from somewhere else, e.g.
    a Fira name left in the framework, shows here (v10.18.0)."""
    named = {m.lower().replace("-", "") for m in FONT_FILE_RE.findall(profile_text(framework, profile))}
    seen: set[str] = set()
    for page in doc:
        for _xref, _ext, _type, basefont, _name, _enc, referencer in page.get_fonts(full=True):
            if referencer:             # used by a form XObject: an included figure's own font
                continue
            font = basefont.split("+", 1)[-1]
            if MATH_FONT_RE.match(font) or font.lower().replace("-", "") in named:
                continue
            seen.add(font)
    return sorted(seen)


def measure(deck: Deck, profile: str, framework: Path, template: str, project: Path = DEFAULT_PROJECT
            ) -> tuple[list[Check], list[str]]:
    profile_text(framework, profile)       # the profile exists
    setup = (framework / "SlideMage_setup.tex").read_text(encoding="utf-8")
    tmpl = template_text(project, framework, template)
    pdf_hooks = cl.pdf_hooks(deck.doc)     # the base's own derived values, where it writes them (preferred: they
                                            # reflect what actually compiled, a template's override included)
    checks: list[Check] = []
    hooks: list[str] = []
    edges: list[str] = []

    # -- the footer and the right edge ------------------------------------------------------------
    probe = deck.page("ZC3")
    if probe is not None:
        chrome = deck.chrome(probe)
        number = frame_number_span(probe, chrome)
        if number is not None:
            above, below = footer_text_gaps(probe, chrome, number)
            # \SMFooterTextDrop is derived from the digits' ink: the ink sits as far from the box's top edge as from its bottom
            checks.append(Check("footer number centred in its box (gap above less gap below)", (above - below) * PT, 0.0,
                                f"the ink sits {above:.2f}pt below the box's top edge and {below:.2f}pt above its bottom",
                                tolerance=2 * 0.15))
            edges.append(f"the frame number ends {(chrome.logo_right - number['bbox'][2]) * PT:+.2f}pt inside the logo's "
                         f"visible right edge (\\SMFooterRightShift, derived)")
        if chrome.footnotes:
            edges.append(f"the footnote lines end {(chrome.logo_right - max(r.x1 for r in chrome.footnotes)) * PT:+.2f}pt inside "
                         f"the logo's visible right edge (\\SMFootnoteRightShift, derived)")

    # -- the footnotes' clearance above the footer box (\SMFootlineVOffset, derived) ---------------------------
    notes = deck.page("ZC8")
    gap_key = info_bp(deck.doc, "SMFootnoteFooterGap")
    descender = info_bp(deck.doc, "SMFootnoteDescender")
    box_height = info_bp(deck.doc, "SMFooterBoxHeight")
    if notes is not None and None not in (gap_key, descender, box_height):
        chrome = deck.chrome(notes)
        baselines = [s["origin"][1] for s in spans(notes)
                     if s["size"] < 4.6 and s["origin"][1] > chrome.footer_top - 40 and s["origin"][1] < chrome.footer_top]
        if baselines:
            above = chrome.h - max(baselines)         # the last footnote line's baseline above the page's bottom edge
            checks.append(Check("footnote descenders above the footer box (\\SMFootnoteFooterGap)",
                                (above - descender - box_height) * PT, gap_key * PT,
                                f"the last baseline is {above:.2f}bp above the page's bottom, the descender {descender:.2f}bp, "
                                f"the footer box {box_height:.2f}bp high"))

    # -- the top of the frames the automatic Top Margin does not correct by their content -----------------
    # (v10.9.0: \SMContentTopShift is measured from the frames' body origin, the two columns corrections against a list
    # where the columns begin; a manual-top frame's first line sits on the Top Margin whatever the font and template)
    top_margin = deck.info["top_margin"]
    for slide_id, what, derived in (("ZCI", "a list", "\\SMContentTopShift"),
                                    ("ZCJ", "a columns[t]", "\\SMColumnsTopCorrection"),
                                    ("ZCK", "a columns[T]", "\\SMColumnsTTopCompensation")):
        y = deck.first_line_top(slide_id)
        if y is not None:
            checks.append(Check(f"manual-top frame, {what} first, on the Top Margin ({derived}, derived)",
                                (y - top_margin) * PT, 0.0,
                                f"the first line sits at {y:.2f}bp, the Top Margin is {top_margin:.2f}bp"))

    # -- the section frame: the bar is as high as the hook says ------------------------------------------------
    section = deck.page("ZC2")
    # the PDF's own key, the hook as it actually compiled (a template's \setlength overrides the catalog's
    # default); only a PDF from before v10.10.0 lacks it, where the template's own text (then the catalog's) stands in
    if SECTION_BOX_HEIGHT in pdf_hooks:
        target = pdf_hooks[SECTION_BOX_HEIGHT] * PT
    else:
        tmpl_value = tex_length(tmpl, SECTION_BOX_HEIGHT)
        target = tmpl_value if tmpl_value is not None else tex_length(setup, SECTION_BOX_HEIGHT)
    if section is not None and target is not None:
        bar = deck.chrome(section).bar_bottom
        checks.append(Check(f"section bar height (\\{SECTION_BOX_HEIGHT})", bar * PT, target,
                            f"the bar ends at {bar:.2f}bp = {bar * PT:.2f}pt, \\{SECTION_BOX_HEIGHT} is {target:.2f}pt",
                            tolerance=0.1))

    # -- lists with labels: the gap between a label and the item's text (\SMLabelItemGap) --------------------------
    labelled = deck.page("ZC5")
    gap_em = em_default(tmpl, "SMLabelItemGap")
    if gap_em is None:
        gap_em = em_default(setup, "SMLabelItemGap")
    if labelled is not None and gap_em is not None:
        found = label_gap(labelled, deck.chrome(labelled).bar_bottom)
        if found:
            worst = max(found, key=lambda f: abs(f[1] - gap_em * f[2]))
            checks.append(Check("label to item text (\\SMLabelItemGap)", worst[1], gap_em * worst[2],
                                f"{len(found)} labels, the worst {worst[0]!r}: {worst[1]:.2f}pt against {gap_em:g}em of {worst[2]:.2f}pt"))

    # -- numerals of a nested enumerate: slot and gap (\SMEnumerateNestedSlotExtra, \SMEnumerateNestedLabelGap) ----
    nested = deck.page("ZCL")
    extra_em = em_default(tmpl, "SMEnumerateNestedSlotExtra")
    if extra_em is None:
        extra_em = em_default(setup, "SMEnumerateNestedSlotExtra")
    label_em = em_default(tmpl, "SMEnumerateNestedLabelGap")
    if label_em is None:
        label_em = em_default(setup, "SMEnumerateNestedLabelGap")
    if nested is not None and extra_em is not None and label_em is not None:
        ws = words(nested)
        numerals = [w for w in ws if re.fullmatch(r"\d\.", w[4]) and w[0] > 20]
        sizes = [s["size"] for s in spans(nested) if re.fullmatch(r"\d\.", s["text"].strip())]
        if numerals and sizes:
            widest = max(numerals, key=lambda w: w[2] - w[0])
            following = [w for w in ws if abs(w[1] - widest[1]) < 2 and w[0] > widest[2] and not re.fullmatch(r"\d\.", w[4])]
            checks.append(Check("nested numerals share a left edge", (max(w[0] for w in numerals) - min(w[0] for w in numerals)) * PT, 0.0,
                                f"{len(numerals)} numerals"))
            if following:
                width = (widest[2] - widest[0]) * PT
                size = sizes[0] * PT
                offset = (min(following, key=lambda w: w[0])[0] - widest[0]) * PT
                checks.append(Check("numeral to item text (widest numeral, slot extra, gap)", offset,
                                    width + (extra_em + label_em) * size,
                                    f"the widest numeral {widest[4]!r} is {width:.2f}pt, the text starts {offset:.2f}pt after its left edge"))

    # -- hooks of the catalog that follow from the font -------------------------------------------------
    section_info = deck.info
    bars = [deck.chrome(p).bar_bottom for p in (deck.page("ZC3"), deck.page("ZC4")) if p is not None]
    if bars:
        hooks.append(f"\\SMTitleBarBottomAlign (derived) = {section_info['title_bar_bottom'] * PT:.2f}pt: the PDF records "
                     f"{section_info['title_bar_bottom']:.2f}bp, the title bar is drawn to {bars[0]:.2f}bp")
    hooks.append(f"\\SMTopMargin = {section_info['top_margin']:.2f}bp; \\SMContentTopAlign (derived) is that distance in pt")
    hooks.extend(edges)
    foreign = fonts_outside_profile(deck.doc, framework, profile)
    hooks.append("fonts on the pages that are not the profile's or TeX's math fonts (a figure's own fonts are not "
                 "counted): " + (", ".join(foreign) if foreign else "none"))
    hooks.append(f"text font ascender read from the font: {section_info['ascender']}em "
                 f"(the profile's \\SMFontAscender is only the fallback)")
    return checks, hooks


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", required=True, help="the layout profile's name, e.g. lmsans")
    ap.add_argument("--template", default="slidemage", help="the template key to compile under (default slidemage)")
    ap.add_argument("--project", default=str(DEFAULT_PROJECT), help="the project holding the calibration deck")
    ap.add_argument("--deck", default=DEFAULT_DECK, help="the calibration deck, relative to the project")
    ap.add_argument("--framework", default=str(REPO / "latex"), help="the framework's latex/ folder")
    ap.add_argument("--pdf", help="measure this PDF instead of compiling")
    ap.add_argument("--keep-pdf", help="also copy the compiled PDF here")
    new = ap.add_argument_group("a new profile (--new): write latex/SlideMage_layout_<profile>.tex, then check it")
    new.add_argument("--new", action="store_true", help="write the profile from the font files below first")
    new.add_argument("--force", action="store_true", help="with --new: overwrite an existing profile")
    new.add_argument("--text-regular", help="the text font's regular face, e.g. lmroman10-regular.otf")
    new.add_argument("--text-italic", help="its italic face")
    new.add_argument("--text-bold", help="its bold face")
    new.add_argument("--text-bold-italic", help="its bold italic face")
    new.add_argument("--mono", default="lmmono10-regular.otf", help="the code font (Latin Modern Mono unless given)")
    new.add_argument("--mono-italic", default="lmmono10-italic.otf")
    new.add_argument("--mono-bold", default="lmmonolt10-bold.otf")
    new.add_argument("--inline-code-scale", default="0.95", help="the inline code font's scale (0.95)")
    new.add_argument("--linespread", default="1.15", help="the profile's line spread (1.15, the shipped profiles')")
    new.add_argument("--parskip", default="0.5em", help="the profile's paragraph gap (0.5em)")
    new.add_argument("--description", default="", help="the profile's one-line description for its header")
    args = ap.parse_args(argv)
    project, framework = Path(args.project).resolve(), Path(args.framework).resolve()
    if args.new:
        faces = (args.text_regular, args.text_italic, args.text_bold, args.text_bold_italic)
        if not all(faces) or args.pdf:
            ap.error("--new needs --text-regular, --text-italic, --text-bold and --text-bold-italic, and no --pdf")
        write_new_profile(args, framework, project)
    if args.pdf:
        pdf = Path(args.pdf)
    else:
        pdf = Path(tempfile.mkdtemp(prefix="calibrate-pdf-")) / "calibration.pdf"
        compile_deck(project, args.deck, args.template, args.profile, framework, pdf)
        if args.keep_pdf:
            shutil.copy2(pdf, args.keep_pdf)
    checks, hooks = measure(Deck(pdf), args.profile, framework, args.template, project)

    print(f"profile {args.profile}, template {args.template}")
    print("derived from the font and the hooks, measured in the PDF against what they ask for (pt):")
    for c in checks:
        measured = "-" if c.measured is None else f"{c.measured:.2f}"
        expected = "-" if c.expected is None else f"{c.expected:.2f}"
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: measured {measured}, expected {expected}   {c.note}")
    print("derived by the base, read back from the PDF:")
    for line in hooks:
        print(f"  {line}")
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
