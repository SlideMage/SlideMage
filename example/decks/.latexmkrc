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

# Same search paths as the project root's .latexmkrc -- see that file's own
# comment. '/../' (not '/'): from decks/, the project root is one directory
# up, and the repo's latex/ framework folder two.
my $slidemaster_sep = $^O eq 'MSWin32' ? ';' : ':';
my $slidemaster_latex = $ENV{'SLIDEMASTER_LATEX'} // (dirname($abs_rc) . '/../../latex');
$ENV{'TEXINPUTS'} = join($slidemaster_sep, dirname($abs_rc) . '/..', $slidemaster_latex,
	$ENV{'TEXINPUTS'} // '');

$ENV{'BIBINPUTS'} = dirname($abs_rc) . '/../:' . ($ENV{'BIBINPUTS'} // '')
	unless $^O eq 'MSWin32';
