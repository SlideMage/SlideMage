# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Help for SlideMage's LaTeX commands, for the Source view's hover tooltips (docs/plans/latex-hover-help.md).

`COMMANDS` and `ENVIRONMENTS` hold what a user needs to call each command: how it is written, what it does, its
keys and an example. The text is condensed from README.md, docs/SlideMageCommands.md and the comments in
latex/SlideMage_base.tex, without their history and implementation notes. tests/test_latex_help.py keeps the
catalogue in step with latex/: every entry is defined there, every command of the manual's Quick Reference slides
has an entry, and the keys match the commands' pgfkeys.

`help_at(text, offset)` finds what is under the pointer: a command's name, an environment's name in
\\begin{...}/\\end{...}, or a key in a command's [...] options. `help_html()` turns the result into the tooltip.
No Qt here: the editor (ui/workspace/source_editor.py) passes Qt positions on text from `utf16_units()`, which this
module's ASCII-only matching reads the same way.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Optional

# app_settings key: Settings -> General, "Show help for LaTeX commands on hover" (on by default).
HOVER_HELP_SETTING_KEY = "latex_hover_help"

@dataclass(frozen=True)
class KeyHelp:
    name: str           # "corner"
    values: str         # "ne | nw | se | sw | e | w"; "" for a flag such as border
    text: str


@dataclass(frozen=True)
class CommandHelp:
    name: str                           # "cornerfigure" (without the backslash) or "besidefigure"
    signature: str                      # how it is called
    summary: str
    keys: tuple[KeyHelp, ...] = ()
    example: str = ""
    environment: bool = False

    def key(self, name: str) -> Optional[KeyHelp]:
        return next((k for k in self.keys if k.name == name), None)


@dataclass(frozen=True)
class HelpHit:
    help: CommandHelp
    key: Optional[str]      # the hovered key, if the pointer is on one in the options
    start: int              # the hovered token, as offsets into the text
    end: int


def _versions(*extra: KeyHelp) -> tuple[KeyHelp, ...]:
    return (
        KeyHelp("instructor", "", "the instructor deck (the presenter PDF compiles as this version too)"),
        KeyHelp("during-course", "", "the student deck handed out at the start of the course"),
        KeyHelp("after-course", "", "the student deck handed out at the end of the course"),
    ) + extra


_FIGURE_KEYS = (
    KeyHelp("width", "<length>", "the image's width; with width or height the argument is an image file and the "
                                 "other size follows from the aspect ratio (both: fitted inside)."),
    KeyHelp("height", "<length>", "the image's height (see width). Without width and height the argument is any "
                                  "content: a block, a \\parbox, an \\includegraphics with its own options."),
    KeyHelp("border", "", "the image border (TikZ style SMImageBorder); its outer edge sits on the margins."),
    KeyHelp("corner", "ne | nw | se | sw | e | w", "which corner of the content area (default ne). e and w sit on "
                                                   "the Right or Left Margin, centred between Top and Bottom Margin."),
    KeyHelp("block", "", "the content is an SMFloatingInfoBlock: lifted by its top padding, its right edge "
                         "aligned with the logo."),
    KeyHelp("xshift", "<length>", "a deliberate offset from the corner, to the right (negative: left)."),
    KeyHelp("yshift", "<length>", "a deliberate offset from the corner, up (negative: down)."),
    KeyHelp("node", "{<TikZ options>}", "extra options for the TikZ node that holds the figure."),
)

_FLOATING_KEYS = (
    KeyHelp("top", "<length>", "space between the title bar and the body (default 2mm; 0pt for none)."),
    KeyHelp("bottom", "<length>", "space between the body and the block's bottom edge (default 1.2mm)."),
)

_ITEMIZE = "{} list: \\begin{{{env}}} \\item[\\{item}] ... \\end{{{env}}}. Each item's label is written with " \
           "\\{item}, which counts by itself."


def _c(name: str, signature: str, summary: str, *keys: KeyHelp, example: str = "") -> CommandHelp:
    return CommandHelp(name, signature, summary, tuple(keys), example)


def _e(name: str, signature: str, summary: str, *keys: KeyHelp, example: str = "") -> CommandHelp:
    return CommandHelp(name, signature, summary, tuple(keys), example, environment=True)


_COMMANDS = [
    # -- figures --
    _c("cornerfigure", r"\cornerfigure[keys]{image file or content}",
       "A figure in a corner of the content area, as an overlay that takes no space in the text. Name the image "
       "and one size; the other size follows from the aspect ratio. The figure's edge (or its border's outer "
       "edge) lands on the margins. Needs the usual second compile. For text that must not run under the "
       "figure, use the besidefigure environment.",
       *_FIGURE_KEYS,
       example=r"\cornerfigure[height=5.6cm, border]{media/chart-x.png}"),
    _c("fitfigure", r"\fitfigure[keys]{image file}",
       "An image as large as it fits, aspect ratio kept, from the current position (or the Top Margin) down to "
       "the Bottom Margin and from the Left to the Right Margin. Placed as an overlay; needs the second compile.",
       KeyHelp("top", "here | margin", "where the box starts: here (default) below the text so far, plus gap; "
                                       "margin at the Top Margin."),
       KeyHelp("gap", "<length>", "space below the text for top=here (default 6pt)."),
       KeyHelp("valign", "top | center | bottom", "vertical place in the box (default center)."),
       KeyHelp("halign", "left | center | right", "horizontal place in the box (default center)."),
       KeyHelp("bottom", "<length>", "the box's bottom, measured from the page's bottom edge (default "
                                     "\\SMContentBottomAlign, the Bottom Margin)."),
       KeyHelp("node", "{<TikZ options>}", "extra TikZ node options, for example SMImageBorder."),
       example=r"\fitfigure[top=margin]{media/diagram-x.png}"),
    _c("sectionfigure", r"\sectionfigure[includegraphics options]{image file}",
       "In a sectionframe: the side image from the title bar down to the footer, flush with the page's right "
       "edge. The frame's footnotes, the image source included, go into a rotated strip beside it. Call it last "
       "in the frame body.",
       example=r"\sectionfigure{media/photo-x.jpg}"),
    _c("figurecenter", r"\figurecenter",
       "Centres what follows horizontally (plain \\centering under a clearer name). Put it in the frame body, "
       "right before the figure, typically in a figureframe.",
       example="\\begin{figureframe}{Title}\n\t\\figurecenter\n\t\\includegraphics[width=0.6\\linewidth]{diagram}\n"
               "\\end{figureframe}"),
    _c("SMQRCode", r"\SMQRCode[height]{QR file}{caption}[link]",
       "A QR code with an optional caption centred under it ({} for none): the link, or a text such as QR 1 that "
       "the slide refers to. [height] defaults to 0.6\\textheight. An inline box, so several codes sit side by "
       "side; \\cornerfigure{\\SMQRCode{...}{...}} puts one in a corner. The Source view's QR button makes the "
       "file.",
       example=r"\SMQRCode[3cm]{media/qr-course.pdf}{QR 1}"),
    _c("SMMugshot", r"\SMMugshot{coordinate}{image file}{diameter}{caption}",
       "A round portrait photo with its caption on an arc, centred on a TikZ coordinate you placed before (its "
       "name, not a point expression). The photo is scaled to fill the circle.",
       example=r"\SMMugshot{personCenter}{media/photo-x.jpeg}{2.6cm}{Some Person, NP 2013}"),

    # -- frames that are commands --
    _c("titleframe", r"\titleframe{title}{second line}",
       "The deck's title slide: a yellow box with the title and a second line (author, term; \\\\ for line "
       "breaks), no footer. A command, not an environment.",
       example=r"\titleframe{Financial Markets}{Stefan Palan\\Summer term 2026}"),
    _c("quoteframe", r"\quoteframe{quote}{attribution}",
       "A quote slide: the quote large and italic on a yellow block (the quotation marks are added), the "
       "attribution below it ({} for none). Put \\quotesource{...} before it for a source line.",
       example="\\quoteframe{Every time one person buys, another sells.}%\n\t{William Feather, 1889-1981}"),
    _c("quotesource", r"\quotesource{text}",
       "The source line of the next \\quoteframe. Call it before \\quoteframe: a \\source{} after it lands "
       "outside the frame and makes an extra page.",
       example=r"\quotesource{Source: Feather (1955).}"),
    _c("fullbleedframe", r"\fullbleedframe{image file}",
       "A slide that is only the image, as large as it fits with its aspect ratio kept, on black: no title, "
       "footer or logo.",
       example=r"\fullbleedframe{media/photo-x.png}"),
    _c("progressstrip", r"\progressstrip{step,step,...}{current}",
       "A strip below the title bar listing steps joined by arrows, the current one (counted from 1) "
       "underlined. The very first thing in a standardframe.",
       example=r"\progressstrip{Field,Topic,Question}{1}"),

    # -- before a frame --
    _c("chapterlogo", r"\chapterlogo{image file}",
       "An extra logo (a chapter icon) next to the institute logo, for the next frame only. Call it before "
       "\\begin{standardframe}.",
       example=r"\chapterlogo{media/icon-x.png}"),
    _c("sidefootnotes", r"\sidefootnotes",
       "The next frame's footnotes, \\source{} lines included, go into a strip along the right edge, rotated to "
       "read bottom to top. Call it before \\begin{standardframe}."),
    _c("SMFinalStateForStudents", r"\SMFinalStateForStudents",
       "In the student decks the next frame shows only the final state of all its reveal steps; the instructor "
       "deck is unchanged. Put it in the slide file before the frame. Takes effect on the second compile."),
    _c("SMManualTopMargin", r"\SMManualTopMargin",
       "The next frame keeps its default position: no automatic Top Margin correction for what it starts with. "
       "Put it before the frame."),
    _c("SMAgendaTitle", r"\SMAgendaTitle{text}",
       "This slide's entry in the chapter agendas (\\SMChapterAgenda), instead of its frame title. Put it before "
       "the frame.",
       example=r"\SMAgendaTitle{Exercise 3}"),
    _c("setSlideVersion", r"\setSlideVersion{X-Y-Z}",
       "The slide's version, shown in the footer next to its id. SlideMage writes and updates it when it "
       "saves a slide; there is no need to edit it.",
       example=r"\setSlideVersion{1-0-0+}"),

    # -- navigation --
    _c("SMDeckAgenda", r"\SMDeckAgenda",
       "Marks the deck's contents slide (in its body, next to \\tableofcontents) as the target of the navigation "
       "bar's first link."),
    _c("SMChapterAgenda", r"\SMChapterAgenda[width]",
       "Lists the slides of the current chapter, each linked, in two columns, as large as fits. For a chapter's "
       "sectionframe. [width] (default \\linewidth) leaves room for a \\sectionfigure. Fills in on the rerun.",
       example=r"\SMChapterAgenda[0.6\linewidth]"),
    _c("SMSubsectionAgenda", r"\SMSubsectionAgenda[width]",
       "Like \\SMChapterAgenda, but one entry per \\subsection of the current chapter, linked to its first "
       "slide."),
    _c("SMLink", r"\SMLink{slide id}{text}",
       "A link to a slide in running text, underlined like a web link. Keep the text short (one line). For "
       "buttons use \\hyperlink with \\beamergotobutton.",
       example=r"\SMLink{1gr}{spacing}"),
    _c("SMNavigationBar", r"\SMNavigationBar[deck,chapter,previews]",
       "In the deck preamble: the footer gets three links, to the \\SMDeckAgenda slide, the current chapter's "
       "\\SMChapterAgenda and the generated appendix with slide previews. The optional labels replace "
       "Contents, Chapter contents, Slide previews."),
    _c("SMOrigHref", r"\SMOrigHref{URL}{text}",
       "A web link without the underline that \\href gets in SlideMage."),

    # -- text --
    _c("source", r"\source{text}",
       "A source line (Source: ..., Image source: ...) that looks and sits like a footnote, without a marker. "
       "Write the label yourself.",
       example=r"\source{Source: Own illustration, data from Yahoo! Finance, 24.02.2026.}"),
    _c("multilingualtext", r"\multilingualtext{EN text}{DE text}  or  \multilingualtext*{EN={...}, DE={...}}",
       "Text that follows the deck's language, for a light multilingual slide (language segment mult). The "
       "starred form takes any number of languages, keyed by the \\decklanguage code; a deck in another language "
       "gets the main language's text. Commas and equals signs inside a value need braces.",
       example=r"\multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}}"),
    _c("SMCode", r"\SMCode{text}",
       "Code in running text, in Fira Mono at 90%. The argument is typeset, so write \\_, \\{, \\} as in any text.",
       example=r"\SMCode{standardframe[c]}"),
    _c("SMCmd", r"\SMCmd{name}",
       "A LaTeX command's name in running text, in code style with its backslash: \\SMCmd{slide} prints \\slide.",
       example=r"\SMCmd{cornerfigure}"),
    _c("SMCodeFile", r"\SMCodeFile[listings keys]{file}",
       "LaTeX source on a slide, read from its own file (the frame needs no [fragile]), with commands and "
       "comments in colour on a light panel. The keys go to \\lstinputlisting (firstline=, lastline=, ...). Name "
       "the files snippets/<slide id>-<n>.tex and write them in ASCII.",
       example=r"\SMCodeFile{snippets/1c9-1.tex}"),
    _c("EUR", r"\EUR", "The euro sign in the slide font, in text and in math alike.", example=r"5\,\EUR"),
    _c("SMUnderbrace", r"\SMUnderbrace{math}{label}",
       "A brace under a formula, drawn in one piece (no seam at narrow widths), with a label below it. The first "
       "argument is set in math mode: don't wrap the call in $...$.",
       example=r"\SMUnderbrace{r_f}{risk-free\\rate}"),
    _c("SMTikzword", r"\SMTikzword{name}{text}",
       "Typesets the text as a named TikZ node, so an overlay arrow can point at the word, (name.south) and so "
       "on, and follows it when the layout moves.",
       example=r"\SMTikzword{price}{price}"),
    _c("SMTikzmark", r"\SMTikzmark{name}",
       "A zero-size named TikZ node at the current text position, for arrows and braces that point at a place "
       "in the text.",
       example=r"\SMTikzmark{a}"),
    _c("SMWarningSign", r"\SMWarningSign[color]{x}{y}{text}{aspect ratio}{rotation}",
       "A warning sign: a box with the text, centred at (x, -y) pt from the page's top-left corner, sized to "
       "the text wrapped at the width:height aspect ratio, rotated counterclockwise by the angle in degrees.",
       example=r"\SMWarningSign{600}{120}{Not a bond!}{2}{10}"),
    _c("SMLineTop", r"\SMLineTop",
       "A strut as tall as a text line's box. Start the first line of a text column beside a figure (both in "
       "top-aligned minipages) with it, so text and figure both start on the Top Margin.",
       example=r"\begin{minipage}[t]{0.4\linewidth}\vspace{0pt}\SMLineTop First line ..."),

    # -- lists --
    _c("tallitem", r"\tallitem[factor]",
       "An \\item with extra room above it, for a stacked fraction (\\dfrac). Use it on the fraction's line and "
       "on the item right after it. [factor] multiplies the extra room (default 1); an optional argument that is "
       "not a number is the item's label instead.",
       example=r"\tallitem $\dfrac{a}{b} = c$"),
    _c("tallitemnobullet", r"\tallitemnobullet[factor]",
       "Like \\tallitem, but without a bullet (\\item[]): for a display formula that continues the previous "
       "item."),
    _c("SMBulletEllipsis", r"\SMBulletEllipsis",
       "An ellipsis as an item's label, starting where a bullet starts: \\item[\\SMBulletEllipsis].",
       example=r"\item[\SMBulletEllipsis] how you contribute"),
    _c("SMBulletEllipsisScript", r"\SMBulletEllipsisScript",
       "A small ellipsis as a list's bullet, at the bullet's place: "
       "\\setbeamertemplate{itemize subitem}{\\SMBulletEllipsisScript}."),
    _c("SMAlphaItem", r"\SMAlphaItem", "The next label of an SMAlphaItemize list: a), b), c) ..."),
    _c("SMNumItem", r"\SMNumItem", "The next label of an SMNumItemize list: 1), 2), 3) ..."),
    _c("SMAlphaPeriodItem", r"\SMAlphaPeriodItem", "The next label of an SMAlphaPeriodItemize list: a., b., c. ..."),
    _c("SMNumPeriodItem", r"\SMNumPeriodItem", "The next label of an SMNumPeriodItemize list: 1., 2., 3. ..."),
    _c("shrinklists", r"\shrinklists{1|2|3}",
       "All list levels of this frame one, two or three font sizes smaller, for a slide with more text than "
       "fits; 3 is \\scriptsize throughout. Put it inside the frame.",
       example=r"\shrinklists{1}"),
    _c("SMTightDisplaySkips", r"\SMTightDisplaySkips",
       "Less space above and below a display formula in a list, so it reads as part of the list. Wrap it with "
       "the formula in a group: {\\SMTightDisplaySkips\\begin{flalign*} ... \\end{flalign*}}."),

    # -- reveals and deck versions --
    _c("conditionalpause", r"\conditionalpause[versions]",
       "A \\pause only in the listed deck versions (default instructor); in the others the content is shown at "
       "once.",
       *_versions(), example=r"\conditionalpause[instructor,after-course]"),
    _c("deckitem", r"\deckitem<step->",
       "An \\item revealed at that step in the instructor deck and a plain \\item in the student decks. Without "
       "<...> it is a plain \\item.",
       example=r"\deckitem<3-> The answer"),
    _c("deckonly", r"\deckonly<overlay>[versions]{content}",
       "Beamer's \\only, but only in the listed deck versions; without [versions] in all of them. Wraps a whole "
       "\\item, text and all.",
       *_versions(), example=r"\deckonly<3>[instructor]{\item Instructor only}"),
    _c("deckuncover", r"\deckuncover<overlay>[versions]{content}",
       "Beamer's \\uncover (the content keeps its space), but only in the listed deck versions.", *_versions()),
    _c("deckvisible", r"\deckvisible<overlay>[versions]{content}",
       "Beamer's \\visible, but only in the listed deck versions.", *_versions()),
    _c("deckreveal", r"\deckreveal[step]{content}  or  \deckreveal*[step]{content}",
       "A hidden answer: revealed from that step (default 2) in the instructor deck, left out of the "
       "during-course deck, shown at once in the after-course deck. The starred form keeps the content's space "
       "on the earlier steps, so nothing jumps when it appears.",
       example=r"\deckreveal{\item The answer}"),
    _c("deckrevealfinal", r"\deckrevealfinal[step]{content}  or  \deckrevealfinal*[step]{content}",
       "Revealed from that step (default 2) in the instructor deck; every other version shows it at once, "
       "without extra pages. The starred form keeps the content's space on the earlier steps. For plain \\pause "
       "steps use \\conditionalpause[instructor].",
       example=r"\deckrevealfinal[3]{\node at (2,1) {Result};}"),
    _c("ifSMInstructorVersion", r"\ifSMInstructorVersion ... \else ... \fi",
       "True when the deck compiles as the instructor version (the presenter PDF too)."),
    _c("ifSMDuringCourseVersion", r"\ifSMDuringCourseVersion ... \else ... \fi",
       "True when the deck compiles as the during-course student version."),
    _c("ifSMAfterCourseVersion", r"\ifSMAfterCourseVersion ... \else ... \fi",
       "True when the deck compiles as the after-course student version."),

    # -- rarely --
    _c("SMArtifactBegin", r"\SMArtifactBegin{properties} ... \SMArtifactEnd",
       "Marks what lies between as decorative (a PDF Artifact), so screen readers skip it. Images are marked by "
       "SlideMage from their image description already.",
       example=r"\SMArtifactBegin{/Type /Layout}"),
    _c("SMArtifactEnd", r"\SMArtifactEnd", "Ends what \\SMArtifactBegin started."),
    _c("slideID", r"\slideID",
       "The id of the slide being typeset (the part of its id-slug before the first hyphen)."),
    _c("SMTocLabelFlushLeft", r"\SMTocLabelFlushLeft{label width}",
       "Left-aligns an enumerate's labels within the given label width, as on an agenda slide built from "
       "\\tableofcontents."),
    _c("SMEnumerateLabelFlushLeftShifted", r"\SMEnumerateLabelFlushLeftShifted{label width}{shift}",
       "Like \\SMTocLabelFlushLeft, with the labels moved right by the shift."),
    _c("SMTocLabelExtraGap", r"\setlength{\SMTocLabelExtraGap}{length}",
       "A length: extra space between the labels and the entries of a \\tableofcontents agenda."),

    # -- in the deck --
    _c("deckversion", r"\deckversion[versions]",
       "The deck version(s) this compile makes. SlideMage sets it from the top bar's version choice; in the "
       "deck it sits in the \\ifdefined\\deckversionoverride block.",
       *_versions(), example=r"\deckversion[instructor]"),
    _c("decklanguage", r"\decklanguage[code]",
       "The deck's language (en, de, fr, ...): which language version of each slide and of "
       "\\multilingualtext it uses, the hyphenation and the PDF's language.",
       example=r"\decklanguage[de]"),
    _c("deckoutputfolder", r"\deckoutputfolder[version]{path}",
       "Where SlideMage puts this deck's PDF, for all versions or for the one named. Read by SlideMage, not by "
       "LaTeX.",
       *_versions(KeyHelp("presenter", "", "the presenter PDF (the instructor version with notes)"),
                  KeyHelp("transcript", "", "the deck's transcript")),
       example=r"\deckoutputfolder[after-course]{C:/Courses/Finance/PDF}"),
    _c("deckappendixtoc", r"\deckappendixtoc",
       "In the deck preamble: SlideMage generates the appendix with the slide previews on every whole-deck "
       "compile, whatever the toolbar checkbox says."),
    _c("decktags", r"\decktags{tag,tag}",
       "The deck's tags (work, course, research, test), by which SlideMage groups its decks. Written by "
       "SlideMage's Tags button; read by SlideMage, not by LaTeX.",
       example=r"\decktags{course}"),
    _c("setfootnotesymbols", r"\setfootnotesymbols{symbol,symbol,...}",
       "The footnote markers, in order, for every \\footnote and \\source from here on. The list may be any "
       "length; it starts over past its end.",
       example=r"\setfootnotesymbols{*,+,\S}"),
    _c("SMSetFootnoteMarkers", r"\SMSetFootnoteMarkers{symbols|boxed|dice}",
       "How footnote markers look: symbols (the default), the number in a small rounded box, or die faces.",
       example=r"\SMSetFootnoteMarkers{boxed}"),
    _c("SMAutoTopMarginfalse", r"\SMAutoTopMarginfalse",
       "In the deck preamble: no automatic Top Margin; every frame sits at its default position, as with "
       "\\SMManualTopMargin."),
    _c("slide", r"\slide{id-slug}",
       "Includes the slide's current version in the deck, in all deck versions.",
       example=r"\slide{k7f-EN-Standard-content}"),
    _c("slideversion", r"\slideversion{id-slug}{X-Y-Z}",
       "Includes a frozen version of the slide instead of its current one.",
       example=r"\slideversion{k7f-EN-Standard-content}{1-0-0}"),
    _c("slidefinal", r"\slidefinal{id-slug}",
       "Includes the slide fully revealed, in every deck version, the instructor deck included: its "
       "\\conditionalpause steps do nothing here."),
    _c("conditionalslide", r"\conditionalslide[versions]{id-slug}",
       "Includes the slide only in the listed deck versions. The slide numbers stay the same in all versions.",
       *_versions(), example=r"\conditionalslide[instructor,after-course]{xyz-Answer-key}"),
    _c("slidestep", r"\slidestep{id-slug}[versions]{steps}",
       "Includes the slide showing only some of its reveal steps (an overlay specification without the angle "
       "brackets: 1,2 or 2-), in the listed deck versions; a call for another version does nothing. Shows the "
       "same slide at several places with different steps.",
       *_versions(), example=r"\slidestep{egk-EN-Paper-Overview}[instructor]{1,2}"),
    _c("omitslide", r"\omitslide{id-slug}",
       "Includes the slide in the instructor deck only; the student decks skip it (their slide numbers keep the "
       "gap, so they match the instructor deck's).",
       example=r"\omitslide{q4m-EN-Answer-key}"),
    _c("omitslideversion", r"\omitslideversion{id-slug}{X-Y-Z}",
       "\\omitslide for a frozen version of the slide: instructor deck only."),
]

_ENVIRONMENTS = [
    _e("besidefigure", r"\begin{besidefigure}[keys]{image file or content} text \end{besidefigure}",
       "Text next to a corner figure: the text column is exactly as wide as the room left of the figure. The "
       "figure's top meets the cap height of the column's first line. Same keys as \\cornerfigure, plus gap.",
       *_FIGURE_KEYS,
       KeyHelp("gap", "<length>", "space between the text column and the figure (default 12pt)."),
       example="\\begin{besidefigure}[height=5cm, border]{media/chart-x.png}\n\t\\begin{itemize} ... "
               "\\end{itemize}\n\\end{besidefigure}"),
    _e("standardframe", r"\begin{standardframe}[t|c]{title} ... \end{standardframe}",
       "The usual content slide: title bar, logo, footer; content top-aligned on the Top Margin. [c] centres it "
       "vertically.",
       example="\\begin{standardframe}{Title}\n\t\\begin{itemize}\n\t\t\\item ...\n\t\\end{itemize}\n"
               "\\end{standardframe}"),
    _e("sectionframe", r"\begin{sectionframe}{title} ... \end{sectionframe}",
       "A chapter's overview slide: a standardframe with a taller title bar (a third of the page), larger text. "
       "Add \\sectionfigure for a side image, \\SMChapterAgenda for the chapter's slides."),
    _e("figureframe", r"\begin{figureframe}[t|c]{title} ... \end{figureframe}",
       "A slide that is just a figure: standardframe's layout; \\figurecenter centres the figure horizontally, "
       "[c] vertically.",
       example="\\begin{figureframe}{Title}\n\t\\figurecenter\n\t\\includegraphics[height=0.7\\textheight]{x}\n"
               "\\end{figureframe}"),
    _e("highlightframe", r"\begin{highlightframe}{title} ... \end{highlightframe}",
       "A standardframe whose title bar and footer are in the highlight colour, so the presenter notices it. "
       "The colour is SMHighlightColor (\\colorlet{SMHighlightColor}{...} in the deck)."),
    _e("sideimageframe", r"\begin{sideimageframe}{title}{image file} ... \end{sideimageframe}",
       "A standardframe with an image from the title bar down to the footer, flush with the right edge. Its "
       "footnotes go into a rotated strip left of the image.",
       example="\\begin{sideimageframe}{Title}{media/photo-x}\n\t...\n\\end{sideimageframe}"),
    _e("SMTable", r"\begin{SMTable}[gap=length]{column spec} ... \end{SMTable}",
       "A table with the theme's rules. With gap, the table's edges are flush with the text and the column gap "
       "is built in. Inside a block the rules are dark.",
       KeyHelp("gap", "<length>", "the space between columns (12pt is the usual look); the outer edges get "
                                  "none."),
       example="\\begin{SMTable}[gap=12pt]{lccc}\n\t\\toprule ... \\bottomrule\n\\end{SMTable}"),
    _e("SMFloatingBlock", r"\begin{SMFloatingBlock}[keys]{width}{title} ... \end{SMFloatingBlock}",
       "A block of the given width, to place freely: beside a table, in a TikZ overlay node, or with "
       "\\cornerfigure. Same colours and font as block.",
       *_FLOATING_KEYS, example=r"\begin{SMFloatingBlock}{5cm}{Title} ... \end{SMFloatingBlock}"),
    _e("SMFloatingExampleBlock", r"\begin{SMFloatingExampleBlock}[keys]{width}{title} ... "
                                 r"\end{SMFloatingExampleBlock}",
       "An exampleblock of the given width, to place freely (see SMFloatingBlock).", *_FLOATING_KEYS),
    _e("SMFloatingInfoBlock", r"\begin{SMFloatingInfoBlock}[keys]{width}{title} ... \end{SMFloatingInfoBlock}",
       "An infoblock of the given width, to place freely; usually in the top right corner with "
       "\\cornerfigure[block]{...}.",
       *_FLOATING_KEYS, example=r"\cornerfigure[block]{\begin{SMFloatingInfoBlock}{6cm}{Note} ... "
                                r"\end{SMFloatingInfoBlock}}"),
    _e("definitionblock", r"\begin{definitionblock}{title} ... \end{definitionblock}",
       "A block for a definition: like block, with a definition symbol at the right of its title bar."),
    _e("infoblock", r"\begin{infoblock}{title} ... \end{infoblock}",
       "A blue block for a supplementary aside, with a circled i at the right of its title bar."),
    _e("referenceblock", r"\begin{referenceblock}{title} ... \end{referenceblock}",
       "A block for references and citations."),
    _e("SMAlphaItemize", r"\begin{SMAlphaItemize} \item[\SMAlphaItem] ... \end{SMAlphaItemize}",
       _ITEMIZE.format("A lettered a), b), c)", env="SMAlphaItemize", item="SMAlphaItem")),
    _e("SMNumItemize", r"\begin{SMNumItemize} \item[\SMNumItem] ... \end{SMNumItemize}",
       _ITEMIZE.format("A numbered 1), 2), 3)", env="SMNumItemize", item="SMNumItem")),
    _e("SMAlphaPeriodItemize", r"\begin{SMAlphaPeriodItemize} \item[\SMAlphaPeriodItem] ... "
                               r"\end{SMAlphaPeriodItemize}",
       _ITEMIZE.format("A lettered a., b., c.", env="SMAlphaPeriodItemize", item="SMAlphaPeriodItem")),
    _e("SMNumPeriodItemize", r"\begin{SMNumPeriodItemize} \item[\SMNumPeriodItem] ... \end{SMNumPeriodItemize}",
       _ITEMIZE.format("A numbered 1., 2., 3.", env="SMNumPeriodItemize", item="SMNumPeriodItem")),
    _e("tikzillustration", r"\begin{tikzillustration}[TikZ options]{id} ... \end{tikzillustration}",
       "A tikzpicture that has an image description like an image file: SlideMage assigns the id and keeps the "
       "description on the Images page. Decorative ones are skipped by screen readers."),
]

COMMANDS: dict[str, CommandHelp] = {h.name: h for h in _COMMANDS}
ENVIRONMENTS: dict[str, CommandHelp] = {h.name: h for h in _ENVIRONMENTS}


# -- what is under the pointer -----------------------------------------------------------------

_COMMAND_RE = re.compile(r"\\([A-Za-z]+)\*?")
_ENV_RE = re.compile(r"\\(?:begin|end)\{([A-Za-z*]+)\}")
# Before an option list's "[": a command, possibly followed by its earlier arguments (a braced id, an overlay
# spec, an earlier [...]): \cornerfigure[, \begin{SMTable}[, \deckonly<3>[, \slidestep{id}[.
_OPTIONS_OWNER_RE = re.compile(
    r"\\(?:begin\{(?P<env>[A-Za-z*]+)\}|(?P<cmd>[A-Za-z]+)\*?)(?:\{[^{}]*\}|<[^<>]*>|\[[^\[\]]*\])*\s*$")
_LOOKBACK = 600                 # characters searched back for the "[" of an option list


def _escaped(text: str, index: int) -> bool:
    backslashes = 0
    while index - backslashes - 1 >= 0 and text[index - backslashes - 1] == "\\":
        backslashes += 1
    return backslashes % 2 == 1


def _in_comment(text: str, offset: int) -> bool:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line = text[line_start:len(text) if line_end < 0 else line_end]
    for match in re.finditer(r"%", line):
        if not _escaped(line, match.start()):
            return line_start + match.start() <= offset
    return False


def _line_bounds(text: str, offset: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return start, len(text) if end < 0 else end


def _token_at(text: str, offset: int) -> Optional[HelpHit]:
    """A known command or environment name under `offset`."""
    start, end = _line_bounds(text, offset)
    line = text[start:end]
    column = offset - start
    for match in _ENV_RE.finditer(line):
        if match.start() <= column < match.end():
            help_ = ENVIRONMENTS.get(match.group(1))
            return None if help_ is None else HelpHit(help_, None, start + match.start(), start + match.end())
    for match in _COMMAND_RE.finditer(line):
        if match.start() <= column < match.end() and not _escaped(line, match.start()):
            help_ = COMMANDS.get(match.group(1))
            return None if help_ is None else HelpHit(help_, None, start + match.start(), start + match.end())
    return None


def _option_at(text: str, offset: int) -> Optional[HelpHit]:
    """A known key in the [...] options of a known command, under `offset`."""
    if text[offset] in ",=[]{}":
        return None
    depth = 0
    opener = -1
    for i in range(offset - 1, max(-1, offset - _LOOKBACK), -1):
        char = text[i]
        if _escaped(text, i):
            continue
        if char in "]}":
            depth += 1
        elif char == "{":
            if depth == 0:
                return None             # inside a braced value such as node={...}
            depth -= 1
        elif char == "[":
            if depth == 0:
                opener = i
                break
            depth -= 1
    if opener < 0:
        return None
    owner = _OPTIONS_OWNER_RE.search(text, max(0, opener - 300), opener)
    if owner is None:
        return None
    help_ = ENVIRONMENTS.get(owner.group("env")) if owner.group("env") else COMMANDS.get(owner.group("cmd"))
    if help_ is None or not help_.keys:
        return None
    # The entry of the option list that holds `offset`: from the comma before it to the comma after it.
    seg_start, depth = opener + 1, 0
    for i in range(opener + 1, offset):
        if text[i] in "{[" and not _escaped(text, i):
            depth += 1
        elif text[i] in "}]" and not _escaped(text, i):
            depth -= 1
        elif text[i] == "," and depth == 0:
            seg_start = i + 1
    seg_end, depth = offset, 0
    while seg_end < len(text) and seg_end - offset < _LOOKBACK:
        char = text[seg_end]
        if char in "{[":
            depth += 1
        elif char in "}]":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            break
        seg_end += 1
    entry = text[seg_start:seg_end]
    name = entry.split("=", 1)[0].strip()
    if help_.key(name) is None:
        return None
    lead = len(entry) - len(entry.lstrip())
    return HelpHit(help_, name, seg_start + lead, seg_start + len(entry.rstrip()))


def help_at(text: str, offset: int) -> Optional[HelpHit]:
    """The help for what is at `offset` (the character under the pointer), or None: plain text, a comment, a
    command SlideMage has no help for."""
    if not 0 <= offset < len(text) or text[offset] in "\n\r" or _in_comment(text, offset):
        return None
    return _token_at(text, offset) or _option_at(text, offset)


# -- the tooltip ----------------------------------------------------------------------------------

def _code(text: str, mono: str) -> str:
    escaped = html.escape(text).replace("\n", "<br>").replace("\t", "&nbsp;&nbsp;")
    return f'<span style="font-family: \'{mono}\', monospace;">{escaped}</span>'


def help_html(hit: HelpHit, mono: str = "monospace") -> str:
    """The tooltip for `hit` as Qt rich text: how it is called, what it does, its keys (the hovered one bold) and
    an example."""
    help_ = hit.help
    parts = [f"<qt><p style='margin:0'><b>{_code(help_.signature, mono)}</b></p>",
             f"<p>{html.escape(help_.summary)}</p>"]
    if help_.keys:
        rows = []
        for key in help_.keys:
            # The values go with the description, so the name column stays narrow.
            name = _code(key.name, mono)
            text = (f"{_code('=' + key.values, mono)}&nbsp; " if key.values else "") + html.escape(key.text)
            if key.name == hit.key:
                name, text = f"<b>{name}</b>", f"<b>{text}</b>"
            rows.append(f"<tr><td style='padding-right:8px' valign='top'>{name}</td><td>{text}</td></tr>")
        title = "Keys" if any(key.values for key in help_.keys) else "Values"     # a version list has values only
        parts.append(f"<p style='margin-bottom:2px'>{title}:</p><table cellspacing='0'>{''.join(rows)}</table>")
    if help_.example:
        parts.append(f"<p style='margin-bottom:0'>Example:<br>{_code(help_.example, mono)}</p>")
    parts.append("</qt>")
    return "".join(parts)
