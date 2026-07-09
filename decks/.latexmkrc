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
