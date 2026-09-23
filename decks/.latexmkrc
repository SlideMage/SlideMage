# Same content as the project root's .latexmkrc -- see that file's own
# comment for why. Duplicated here (not just relied on from the root) so
# compiling from inside decks/ picks it up too.
$pdf_mode = 4;
$lualatex = 'lualatex -synctex=1 -interaction=nonstopmode -file-line-error %O %S';

# Same aux/log/etc. redirection as the project root's .latexmkrc -- see that
# file's own comment for why $do_cd is needed and why $aux_dir must be an
# absolute path built from latexmk's own $abs_rc variable rather than a
# plain relative string. '/../.build' (not '/.build'): decks/ shares the one
# .build/ directory at the project root, same as root's own compiles do.
use File::Basename 'dirname';
$do_cd = 1;
$aux_dir = dirname($abs_rc) . '/../.build';

# Same TEXINPUTS fix as the project root's .latexmkrc -- see that file's own
# comment for why TeX Live needs this, MiKTeX doesn't, and it's gated to
# non-Windows. '/../' (not '/'): from decks/, the project root -- and
# beamerthemegotham.sty -- is one directory up, same as $aux_dir above.
$ENV{'TEXINPUTS'} = dirname($abs_rc) . '/../:' . ($ENV{'TEXINPUTS'} // '')
	unless $^O eq 'MSWin32';

# Same BIBINPUTS fix as the project root's .latexmkrc -- see that file's own
# comment for why biber needs this separately from TEXINPUTS above. '/../'
# (not '/'): from decks/, the project root -- and Slidemaster.bib -- is one
# directory up, same as TEXINPUTS above.
$ENV{'BIBINPUTS'} = dirname($abs_rc) . '/../:' . ($ENV{'BIBINPUTS'} // '')
	unless $^O eq 'MSWin32';
