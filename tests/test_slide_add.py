"""Everything the Add slide sheet needs besides widgets: new slide files from the frames, copies and
translations, the deck call for a way of loading a slide, and the slides to pick from."""
from __future__ import annotations

import pytest

from slidemage import alt_blocks, deck_editor, project, slide_add, slide_ids, slide_import, slide_versioning
from slidemage.ai.providers import ChatReply, ProviderError

from conftest import TEMPLATE, use_new_slide_files


@pytest.fixture
def relinked(tmp_path, monkeypatch):
    """The throwaway project; how often the translation links were regenerated."""
    return use_new_slide_files(monkeypatch, tmp_path)


@pytest.fixture
def files(tmp_path, relinked):
    return tmp_path / "slides"


class Translator:
    """A model that answers every request with `reply` (or fails with it, if an exception)."""

    is_local = True
    model = "fake"
    label = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.asked = []

    def chat(self, messages, **kwargs):
        self.asked.append(messages[0]["content"])
        if isinstance(self.reply, Exception):
            raise self.reply
        return ChatReply(text=self.reply)

    def abort(self):
        pass


# -- frames --------------------------------------------------------------------------------

def test_every_frame_has_a_thumbnail_and_a_body_with_the_title():
    assert slide_add.FRAMES[0] == slide_add.STANDARD_FRAME
    for frame in slide_add.FRAMES:
        assert slide_add.frame_thumbnail(frame).is_file(), frame
    for frame in slide_add.FRAMES[1:]:
        body = slide_add.frame_body(frame, "Growth & R_D")
        assert "{Growth \\& R\\_D}" in body or "Growth \\& R\\_D" in body, frame
        assert "\n" not in body.replace("\r\n", ""), frame


def test_the_frame_environments_are_the_ones_the_app_recognises():
    for frame in ("standardframe", "figureframe", "sideimageframe", "highlightframe", "sectionframe",
                  "titleframe"):
        assert alt_blocks.frame_type(slide_add.frame_body(frame, "Hello")) == frame


def test_the_standard_frame_is_the_projects_template(files):
    assert slide_add.frame_body("standardframe", "") == TEMPLATE
    assert slide_add.frame_body("standardframe", " My title ") == TEMPLATE.replace("{Title}", "{My title}")


@pytest.mark.parametrize("custom_template", [None, TEMPLATE + "% Custom template\r\n"])
def test_empty_project_can_add_a_standard_slide(tmp_path, monkeypatch, custom_template):
    target = tmp_path / "empty-project"
    project.init_project(target, copy_example=False)
    relative = ".scripts/R_Slidemaster/inst/templates/slide-template.tex"
    template = target / relative
    monkeypatch.setattr(slide_ids, "TEMPLATE_PATH", template)
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", target / "slides")
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", target / "slide_ids.csv")
    expected = (project.template_dir("example") / relative).read_bytes().decode("utf-8")
    if custom_template is not None:
        template.parent.mkdir(parents=True)
        template.write_bytes(custom_template.encode("utf-8"))
        expected = custom_template

    assert slide_ids.read_template() == expected
    created = slide_add.create_new("First", "EN")
    assert created.path.read_bytes().decode("utf-8") == slide_ids.build_new_slide_header() + expected
    assert template.exists() == (custom_template is not None)


@pytest.mark.parametrize("bundled_available", [False, True])
def test_missing_project_and_bundled_templates_raise(tmp_path, monkeypatch, bundled_available):
    monkeypatch.setattr(slide_ids, "TEMPLATE_PATH", tmp_path / "missing-template.tex")
    monkeypatch.setattr(project, "template_dir", lambda _name: tmp_path if bundled_available else None)

    with pytest.raises(FileNotFoundError, match="No slide template found"):
        slide_ids.read_template()


# -- new files -------------------------------------------------------------------------------

def test_a_new_slide_gets_a_fresh_id_a_header_and_the_frames_text(files):
    created = slide_add.create_new("My-Slide", "DE", "quoteframe", "Hello")
    bare, language, slug = created.id_slug.split("-", 2)
    assert (language, slug) == ("DE", "My-Slide") and created.path == files / f"{created.id_slug}-current.tex"
    text = created.path.read_bytes().decode("utf-8")
    assert text.startswith("%% Included in decks: (none)\r\n%%\r\n\r\n")
    assert "\\quoteframe{" in text and "\\SMAgendaTitle{Hello}" in text
    assert f'"{bare}"' in (files.parent / "slide_ids.csv").read_text()
    with pytest.raises(ValueError):
        slide_add.create_new("Bad", "FR")


def test_a_duplicate_keeps_the_language_and_does_not_link(files, relinked):
    (files / "abc-DE-Demo-current.tex").write_bytes(
        b"%% Included in decks: talk\r\n%%\r\n\r\n\\begin{standardframe}{Demo}\r\nText\r\n\\end{standardframe}\r\n")
    created = slide_add.create_copy("abc-DE-Demo", "Demo-Copy")
    assert created.id_slug.endswith("-DE-Demo-Copy")
    text = created.path.read_bytes().decode("utf-8")
    assert text == "%% Included in decks: (none)\r\n%%\r\n\r\n\\begin{standardframe}{Demo}\r\nText\r\n\\end{standardframe}\r\n"
    assert "translation" not in (files / "abc-DE-Demo-current.tex").read_text() and relinked == []
    legacy = files / "old-slide-current.tex"
    legacy.write_bytes(b"body")
    assert slide_add.create_copy("old-slide", "Copy").id_slug.endswith("-EN-Copy")   # never left untagged


def test_a_translation_is_linked_both_ways(files, relinked):
    source = files / "abc-EN-Demo-current.tex"
    source.write_bytes(b"%% Included in decks: talk\r\n%%\r\n\r\nText\r\n")
    created = slide_add.create_copy("abc-EN-Demo", "Demo", "DE")
    assert created.path.read_bytes().decode("utf-8").startswith(
        "%% Included in decks: (none)\r\n%%\r\n%% Translation of: abc-EN-Demo\r\n%%\r\n\r\nText")
    assert f"%% DE translation: {created.id_slug}" in source.read_text()
    assert relinked == [True]
    translated = slide_add.create_copy("abc-EN-Demo", "Demo-2", "DE", body="Text auf Deutsch\r\n")
    assert translated.path.read_bytes().decode("utf-8").endswith("\r\n\r\nText auf Deutsch\r\n")


@pytest.mark.parametrize("language", [None, "DE"])
@pytest.mark.parametrize("supplied_body", [False, True])
def test_copies_start_untracked_like_new_slides_without_changing_the_source_body(files, language, supplied_body):
    source = files / "abc-EN-Demo-current.tex"
    source_body = "\\setSlideVersion{1-1-0}\r\nText\r\n"
    source_bytes = (slide_ids.build_new_slide_header() + source_body).encode("utf-8")
    source.write_bytes(source_bytes)
    new = slide_add.create_new("New", "EN")
    copied = slide_add.create_copy("abc-EN-Demo", "Copy", language,
                                   body=source_body if supplied_body else None)

    assert slide_versioning.parse_version(new.path.read_text()) is None
    assert slide_versioning.parse_version(copied.path.read_text()) is None
    assert slide_ids.slide_body(copied.path) == "Text\r\n"
    assert slide_ids.slide_body(source) == source_body
    assert slide_versioning.parse_version(source.read_text()) == (1, 1, 0)
    if language is None:
        assert source.read_bytes() == source_bytes


def test_the_languages_a_slide_can_be_translated_into(files):
    assert slide_add.other_languages("abc-EN-Demo") == ["DE", "mult"]
    assert slide_add.other_languages("abc-DE-Demo") == ["EN", "mult"]
    assert slide_add.other_languages("abc-Demo") == ["EN", "DE", "mult"]
    assert slide_add.can_machine_translate("abc-EN-Demo", "DE")
    assert not slide_add.can_machine_translate("abc-DE-Demo", "EN")
    assert not slide_add.can_machine_translate("abc-EN-Demo", "mult")
    assert slide_add.slug_of("abc-EN-Demo-Two") == "Demo-Two" and slide_add.slug_of("abc-Demo") == "Demo"


def test_slugs():
    assert slide_import.slug_from_title("Growth of R&D spend (50% YoY)", "") == "Growth-of-R-D-spend-50-YoY"
    assert slide_import.slug_from_title("???", "") == ""
    assert all(slide_add.SLUG_RE.match(s) for s in ("MM-Theorem", "a", "A1-b2"))
    assert not any(slide_add.SLUG_RE.match(s) for s in ("", "-a", "a-", "a--b", "a b", "ä"))


# -- translating -----------------------------------------------------------------------------

def test_the_body_is_translated_as_one_block_and_keeps_its_line_ends():
    model = Translator("Hallo\nWelt")
    text, error = slide_add.translate_body(model, "Hello\r\nWorld\r\n")
    assert (text, error) == ("Hallo\r\nWelt", None) and len(model.asked) == 1 and "Hello\r\nWorld" in model.asked[0]
    assert slide_add.translate_body(Translator("Hallo\r\nWelt"), "Hello\nWorld")[0] == "Hallo\nWelt"


def test_a_failed_translation_is_reported_not_raised():
    text, error = slide_add.translate_body(Translator(ProviderError("rate limited")), "Hello")
    assert (text, error) == ("", "rate limited")


# -- the deck call -----------------------------------------------------------------------------

def test_the_call_follows_the_load_and_the_views():
    views = deck_editor.DEFAULT_CONDITIONS
    assert slide_add.call_spec("live", views) == slide_add.CallSpec("slide")
    assert slide_add.call_spec("live", ["after-course", "instructor"]) == slide_add.CallSpec(
        "conditionalslide", conditions=["instructor", "after-course"])
    assert slide_add.call_spec("frozen", [], "1-0-0") == slide_add.CallSpec("slideversion", "1-0-0")
    assert slide_add.call_spec("step", ["during-course"], steps=" 1, 2 ") == slide_add.CallSpec(
        "slidestep", conditions=["during-course"], steps="1,2")
    assert slide_add.call_spec("step", views).steps == "1"
    for bad in (lambda: slide_add.call_spec("live", []), lambda: slide_add.call_spec("step", views, steps="x"),
                lambda: slide_add.call_spec("frozen", views)):
        with pytest.raises(ValueError):
            bad()
    spec = slide_add.call_spec("step", views, steps="2-")
    assert deck_editor.format_call(spec.macro, "abc-EN-Demo", spec.version, spec.conditions, spec.steps) == \
        "\\slidestep{abc-EN-Demo}[instructor,during-course,after-course]{2-}"


# -- the slides to pick from -----------------------------------------------------------------------

def test_the_project_slides_with_title_and_language(files):
    (files / "bbb-DE-Zwei-current.tex").write_text("\\begin{standardframe}{Zwei}\nx\n\\end{standardframe}\n")
    (files / "aaa-EN-One-current.tex").write_text("\\begin{standardframe}{One}\nx\n\\end{standardframe}\n")
    (files / "aaa-EN-One-v1-0-0.tex").write_text("frozen")
    assert slide_add.project_slides() == [
        slide_add.ProjectSlide("aaa-EN-One", "One", "[EN]"), slide_add.ProjectSlide("bbb-DE-Zwei", "Zwei", "[DE]")]
