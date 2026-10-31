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
# Windows is 'MSWin32' for a native Perl but 'cygwin'/'msys' for the Perl
# bundled with Git for Windows -- the one MiKTeX's latexmk usually runs on --
# and MiKTeX wants ';' either way (a ':' would split at every drive letter).
my $slidemage_windows = $^O =~ /^(?:MSWin32|cygwin|msys)$/;
my $slidemage_sep = $slidemage_windows ? ';' : ':';
# That same Perl also reports its own paths ($abs_rc and everything built from
# it) in POSIX form, /d/... or /cygdrive/d/..., which it translates for
# command-line arguments but not inside TEXINPUTS -- MiKTeX then can't find
# anything on it. Convert to D:/... form before joining.
sub slidemage_native_path {
	my ($path) = @_;
	if ($^O eq 'cygwin' || $^O eq 'msys') {
		$path =~ s{^/cygdrive/([a-zA-Z])/}{$1:/} or $path =~ s{^/([a-zA-Z])/}{$1:/};
	}
	return $path;
}
my $slidemage_latex = $ENV{'SLIDEMAGE_LATEX'} // (dirname($abs_rc) . '/../../../../latex');
$ENV{'TEXINPUTS'} = join($slidemage_sep,
	map({ slidemage_native_path($_) } dirname($abs_rc) . '/..', $slidemage_latex),
	$ENV{'TEXINPUTS'} // '');

$ENV{'BIBINPUTS'} = join($slidemage_sep,
	slidemage_native_path(dirname($abs_rc) . '/..'), $ENV{'BIBINPUTS'} // '');
