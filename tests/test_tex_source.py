"""tex_source.py: the one place that knows where a comment starts and where a braced argument ends."""
from slidemage.protected_regions import mask_protected_regions
from slidemage.tex_source import blanked_verbatim, braced_argument, comment_start, masked_same_length


def test_comment_start_tells_an_escaped_percent_from_a_comment():
    assert comment_start("50\\% sure") == -1
    assert comment_start("line break\\\\% comment") == 12     # "\\" then "%": the percent starts a comment
    assert comment_start("x % y % z") == 2


def test_masking_keeps_offsets_and_line_breaks():
    text = "a % b\n\\% c\nd"
    masked = masked_same_length(text)
    assert masked == "a    \n\\% c\nd" and len(masked) == len(text)


def test_blanked_verbatim_keeps_line_breaks():
    text = "a \\verb|x%y| b\n\\begin{verbatim}\n{\n\\end{verbatim}\nc"
    blanked = blanked_verbatim(text)
    assert len(blanked) == len(text) and blanked.count("\n") == text.count("\n") and "{" not in blanked


def test_braced_argument_skips_escaped_braces_and_reports_unbalanced_groups():
    assert braced_argument("{a \\} {b} c} tail", 0) == ("a \\} {b} c", 12)
    assert braced_argument("{open", 0) == ("", 0)
    assert braced_argument("no brace", 0) == ("", 0)


def test_a_vbox_group_ends_at_its_real_brace_not_one_inside_a_comment():
    text = "\\vbox to 0pt {\n% a stray } in a comment\nx}\nafter"
    result = mask_protected_regions(text)
    assert result.masked_text.endswith("\nafter") and "x}" not in result.masked_text
