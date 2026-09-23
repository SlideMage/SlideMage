# latexmk configuration for this project.
#
# Required engine: lualatex, not the default pdflatex -- the Gotham theme
# loads Fira Sans via fontspec, which pdflatex can't handle (fails
# *silently*, falling back to Computer Modern instead of erroring; see
# README.md's "Compiling" section). $pdf_mode = 4 selects lualatex as the
# engine that generates the PDF directly, via the $lualatex command below
# (pdf_mode 4 uses $lualatex, not $pdflatex -- unlike pdf_mode 1/pdflatex).
#
# With this in place, latexmk handles the whole compile loop by itself,
# including the extra biber step decks/t-Uni-FM2-2027s.tex needs (biblatex+
# biber is opt-in per deck, not used by every deck in this project) --
# latexmk auto-detects from the .bcf file whether a given deck needs biber
# at all, and how many lualatex/biber reruns are actually needed, rather
# than blindly chaining a fixed sequence on every compile of every deck.
#
# A copy of this same file also lives in decks/, so the same behavior
# applies whether compiling from the project root or from inside decks/
# (matching the \input@path/\graphicspath fallback the deck files
# themselves already use for the same reason) -- latexmk's own rc-file
# directory search isn't consistent enough across versions to rely on one
# copy being found from both locations.
$pdf_mode = 4;
$lualatex = 'lualatex -synctex=1 -interaction=nonstopmode -file-line-error %O %S';

# Keep aux/log/bbl/bcf/synctex/etc. clutter out of the project root and
# decks/ -- everything *except* the final PDF (and the .fls source-file
# record, which latexmk itself needs to find next to the PDF on the next
# run) goes into one shared .build/ at the project root instead. This relies
# on MiKTeX's engine-level -aux-directory flag (this project is MiKTeX-only
# already, see README.md's "Compiling" section) -- latexmk inserts it
# automatically via the %O placeholder above once $aux_dir is set, no
# separate flag needed here.
#
# $do_cd makes latexmk change into the *compiled file's own* directory
# before doing anything (rather than using whatever directory latexmk itself
# was invoked from) -- without it, `latexmk decks/foo.tex` run from the
# project root puts the PDF in the *project root*, not next to foo.tex in
# decks/ (confirmed directly: that's the exact "build files show up in the
# wrong folder" behavior this whole setup exists to fix). $out_dir is left
# at its default (the now-`cd`-ed-into compiled-file directory) so the PDF
# lands next to its source either way.
#
# $aux_dir is computed as an *absolute* path rather than a plain relative
# '.build' -- a relative path here is read relative to whatever directory is
# current *at the moment latexmk applies it*, which thanks to $do_cd is the
# compiled file's own directory, not this rc file's directory. A relative
# path would therefore silently create a second, empty .build/ *inside
# decks/* when compiling a decks/ file from the project root (confirmed
# directly), instead of sharing this one .build/. $abs_rc is latexmk's own
# variable holding this rc file's absolute path -- set as a lexical `my` in
# latexmk's rc-loading code and visible here because latexmk loads rc files
# via `eval` of the file's text (not Perl's `do`), which runs in that
# enclosing lexical scope (confirmed directly: a one-line rc file that just
# warns "$abs_rc" prints this file's own real path, not "(eval N)" the way
# __FILE__ does inside an evaled string). Same expression (adjusted for its
# own location) is duplicated in decks/.latexmkrc, for the same
# compile-from-either-location reason as the rest of this file -- both
# resolve to this exact same directory regardless of which copy actually
# gets used or what $do_cd does afterwards.
use File::Basename 'dirname';
$do_cd = 1;
$aux_dir = dirname($abs_rc) . '/.build';

# beamerthemegotham.sty and friends live at the project root, right next to
# this file. On MiKTeX that's enough by itself -- its package search also
# covers the current working directory's own tree without help. TeX Live's
# kpathsea doesn't do that: once $do_cd above moves into decks/ for a
# decks/*.tex compile, `\usetheme{gotham}` fails with "File
# `beamerthemegotham.sty' not found" because the theme's one directory up
# is simply not on TeX Live's search path (confirmed directly). Prepending
# it to TEXINPUTS fixes that on TeX Live. Gated to non-Windows ($^O ne
# 'MSWin32', i.e. not MiKTeX): MiKTeX doesn't need it (see above), and
# kpathsea's TEXINPUTS separator is ':' on Unix but ';' on Windows, so an
# unconditional unix-style assignment would silently break MiKTeX's own
# search path rather than just being a no-op there.
$ENV{'TEXINPUTS'} = dirname($abs_rc) . ':' . ($ENV{'TEXINPUTS'} // '')
	unless $^O eq 'MSWin32';

# Same reasoning as TEXINPUTS above, but for Slidemaster.bib: biber resolves
# .bib files via BIBINPUTS, not TEXINPUTS, so a deck's
# \IfFileExists{Slidemaster.bib}{\addbibresource{Slidemaster.bib}}{...}
# fallback (see decks/test.tex) can find the file via the TEXINPUTS fix
# above (kpathsea's generic file search checks it too) and take the
# bare-filename branch, while biber -- using BIBINPUTS alone -- then fails
# to find that same file, vetoing the biber run entirely and leaving
# \fullcite{} calls unresolved. Confirmed directly: without this, a
# decks/*.tex compile logs "Bib file(s) not found in search path:
# Slidemaster.bib" and the resulting broken \fullcite{} expansion cascades
# into spurious "missing \item" errors on unrelated later slides.
$ENV{'BIBINPUTS'} = dirname($abs_rc) . ':' . ($ENV{'BIBINPUTS'} // '')
	unless $^O eq 'MSWin32';
