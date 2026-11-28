"""Optional titleframe keys and their effect on title editing, image references and spell checking."""
from pathlib import Path

from slidemage import alt_blocks, prose_spans, slide_source

KEYED = (
    "\\setSlideVersion{1-0-0}\n"
    "\\titleframe[author={Ann Author\\textsuperscript{a}, \\underline{Bo Second}\\textsuperscript{b}},\n"
    "\taffiliation={\\textsuperscript{a}First University\\\\[2pt]\\textsuperscript{b}Second Institute},\n"
    "\tlogos={media/logo-one.pdf, media/logo-two.png},\n"
    "\tvenue={Journal of Tests 1 (2026), 101}]{Research hooks}{The test deck}\n"
)
PLAIN = "\\setSlideVersion{1-0-0}\n\\titleframe{Research hooks}{The test deck}\n"


def test_the_keyed_title_can_be_read_and_replaced():
    start, end = slide_source.title_span(KEYED)
    assert KEYED[start:end] == "Research hooks"
    assert alt_blocks.slide_title(KEYED, Path("slides/ZR1-EN-Title-current.tex"), ("EN",)) == ("ZR1", "Research hooks")
    assert slide_source.set_title(KEYED, "New title") == KEYED.replace("Research hooks", "New title")


def test_the_logos_key_names_images_of_the_slide():
    assert alt_blocks.referenced_images(KEYED) == ["media/logo-one.pdf", "media/logo-two.png"]
    single = "\\titleframe[logos=media/logo.pdf, venue={X}]{T}{S}\n"
    assert alt_blocks.referenced_images(single) == ["media/logo.pdf"]
    assert alt_blocks.referenced_images(PLAIN) == []


def test_the_keys_are_not_prose_but_title_and_subtitle_are():
    spans = prose_spans.prose_spans(KEYED, "en")
    texts = [KEYED[s.start:s.end] for s in spans]
    assert any("Research hooks" in t for t in texts)
    assert any("The test deck" in t for t in texts)
    assert not any("First University" in t or "Journal of Tests" in t for t in texts)


def test_a_line_break_in_a_title_is_a_space_not_a_command():
    from slidemage.alt_blocks import clean_frame_title
    raw = r"Predicts investment behavior beyond\\general financial literacy"
    assert clean_frame_title(raw) == "Predicts investment behavior beyond general financial literacy"
    assert clean_frame_title(r"A\\[2mm]B\\*C") == "A B C"
