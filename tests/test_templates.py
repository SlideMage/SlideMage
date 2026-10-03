"""The generic SlideMage template is a known template like the institution
ones: detected from a deck's preamble, previews named after it, the
"Update previews" preamble built from it, and shipped in example/."""
from pathlib import Path

from slidemage import slide_snapshot, update_all_previews

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


def test_slidemage_template_detected():
    preamble = "\\usetheme{gotham}\n\\input{Slidemaster_preamble_slidemage}\n"
    assert slide_snapshot.detect_template(preamble) == "slidemage"
    assert slide_snapshot.TEMPLATES["slidemage"] == "SlideMage"


def test_institution_templates_unchanged():
    for key in ("uni-graz", "uni-ibk", "mci"):
        assert slide_snapshot.detect_template(
            f"\\input{{Slidemaster_preamble_{key}}}") == key
    assert slide_snapshot.detect_template("no template here") == "uni-graz"


def test_update_previews_preamble_uses_slidemage_template():
    preamble = update_all_previews._preamble_for("slidemage")
    assert "\\input{Slidemaster_preamble_slidemage}" in preamble
    assert "\\input{Slidemaster_preamble_uni-graz}" not in preamble


def test_preview_filenames_recognized():
    assert update_all_previews._SNAPSHOT_FILENAME_RE.match("ZZZ-EN-SlideMage-1920-1080.png")


def test_example_ships_the_template_and_its_logo():
    tex = (EXAMPLE / "Slidemaster_preamble_slidemage.tex").read_text(encoding="utf-8")
    assert "\\input{Slidemaster_preamble_base}" in tex
    logo = "schemes/scheme_slidemage/Logo_SlideMage-cropped.pdf"
    assert logo in tex
    assert (EXAMPLE / logo).is_file()
