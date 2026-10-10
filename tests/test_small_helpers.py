"""The small shared helpers: plural(), version_label(), current_name() and is_current_file()."""
from __future__ import annotations

from pathlib import Path

from slidemage import slide_language, slide_versioning
from slidemage.ui.text import plural


def test_plural_counts_and_inflects():
    assert [plural(n, "slide") for n in (0, 1, 2)] == ["0 slides", "1 slide", "2 slides"]


def test_a_version_in_file_name_form_is_shown_with_dots():
    assert slide_versioning.version_label("1-2-3") == "v1.2.3"


def test_the_current_file_of_a_slide_is_named_in_one_place():
    assert slide_language.current_name("abc-EN-Demo") == "abc-EN-Demo-current.tex"
    assert slide_language.is_current_file(Path("slides/abc-EN-Demo-current.tex"))
    assert not slide_language.is_current_file(Path("slides/abc-EN-Demo-v1-0-0.tex"))
