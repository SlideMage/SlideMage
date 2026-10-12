"""The Claude Code tasks (ai/claude_tasks.py): the request text, and the check that decides whether an answer
may be applied: well formed, every edit's `before` found exactly once, protected parts of the slide unchanged,
no lint error the captured text did not have."""
from __future__ import annotations

import pytest
from conftest import SLIDE_TEXT

from slidemage import latex_lint
from slidemage.ai import claude_tasks
from slidemage.ai.claude_tasks import FIX_LATEX, TRANSLATE, check

LF = SLIDE_TEXT.replace("\r\n", "\n")
BROKEN = LF.replace("{Hello}", "{Hello")           # an unclosed brace: a lint error


def edits(*pairs: tuple[str, str]) -> dict:
    return {"edits": [{"before": before, "after": after} for before, after in pairs]}


# -- requests ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("address, line", [("Sie", 'with "Sie" (formal)'), ("du", 'with "du" (informal)')])
def test_a_translation_into_german_says_how_to_address_the_audience(address, line):
    request = claude_tasks.translate_request("Open the file.", "EN", "DE", address)
    assert "from English to German" in request and line in request
    assert request.endswith("<slide>\nOpen the file.\n</slide>")


def test_a_translation_into_english_has_no_form_of_address():
    request = claude_tasks.translate_request("Datei öffnen.", "DE", "EN", "Sie")
    assert "from German to English" in request and "Sie" not in request


def test_the_glossary_goes_into_the_request_as_it_is():
    glossary = "slide = Folie\ndeck = Foliensatz\n"
    request = claude_tasks.translate_request("A slide.", "EN", "DE", glossary=glossary)
    assert "slide = Folie\ndeck = Foliensatz\n<slide>" in request
    assert "Glossary" not in claude_tasks.translate_request("A slide.", "EN", "DE")


def test_a_fix_request_names_the_errors_and_not_the_warnings():
    text = BROKEN.replace("First point", "a_b")                # an error and a warning (underscore)
    request = claude_tasks.fix_request(text, latex_lint.lint_text(text))
    assert "(braces)" in request and "(underscore)" not in request and request.endswith(f"<slide>\n{text}\n</slide>")


def test_a_repair_request_shows_the_refused_answer_and_why():
    request = claude_tasks.repair_request("THE REQUEST", {"body": "x"}, ["first problem", "second"])
    assert request.startswith("THE REQUEST") and '{"body": "x"}' in request
    assert "- first problem\n- second" in request


# -- answers that may be applied ---------------------------------------------------------------------

def test_a_body_is_the_new_text():
    assert check(TRANSLATE, LF, {"body": LF.replace("Hello", "Hallo")}) == (LF.replace("Hello", "Hallo"), [])


def test_edits_are_applied_to_the_captured_text_together():
    answer = edits(("{Hello", "{Hello}"), ("First point", "1st point"), ("\\item Second point", "\\item 2nd"))
    assert check(FIX_LATEX, BROKEN, answer) == (
        LF.replace("First point", "1st point").replace("Second point", "2nd"), [])


def test_no_edits_or_edits_that_change_nothing_leave_the_text_alone():
    assert check(FIX_LATEX, LF, {"edits": []}) == (LF, [])
    assert check(FIX_LATEX, LF, edits(("First", "First"))) == (LF, [])
    assert check(TRANSLATE, LF, {"body": LF}) == (LF, [])


@pytest.mark.parametrize("answer, task", [
    (None, TRANSLATE), ({}, TRANSLATE), ({"body": ""}, TRANSLATE), ({"body": 3}, TRANSLATE),
    ({"edits": []}, TRANSLATE), ({"body": "x"}, FIX_LATEX), ({"edits": "x"}, FIX_LATEX),
    ({"edits": [{"before": "First"}]}, FIX_LATEX), ({"edits": [{"before": 1, "after": "x"}]}, FIX_LATEX),
    ({"edits": ["x"]}, FIX_LATEX),
])
def test_an_answer_of_the_wrong_shape_is_refused(answer, task):
    text, problems = check(task, LF, answer)
    assert text == LF and len(problems) == 1 and problems[0].startswith("the answer must be")


@pytest.mark.parametrize("answer, expected", [
    (edits(("not in the slide", "x")), "does not occur"),
    (edits(("point", "p")), "more than once"),
    (edits(("", "x")), "is empty"),
    (edits(("First point", "1st"), ("point\n\t\t\\item Second", "x")), "overlap"),
])
def test_an_edit_whose_before_is_not_found_exactly_once_is_refused(answer, expected):
    text, problems = check(FIX_LATEX, LF, answer)
    assert text == LF and any(expected in problem for problem in problems)


def test_every_bad_edit_is_reported():
    _, problems = check(FIX_LATEX, LF, edits(("nowhere", "x"), ("point", "p")))
    assert len(problems) == 2 and problems[0].startswith("edit 1") and problems[1].startswith("edit 2")


# -- protected parts, lint ---------------------------------------------------------------------------

@pytest.mark.parametrize("old, new", [
    ("\\setSlideVersion{1-0-0}", "\\setSlideVersion{9-9-9}"),
    ("\t\\vbox to 0pt{\\vss\\hbox{overlay}}\n", ""),
    ("%% Included in decks: test\n%%\n", ""),
], ids=["version-line", "overlay-block", "deck-header"])
def test_protected_parts_must_not_change(old, new):
    for task, answer in ((FIX_LATEX, edits((old, new))), (TRANSLATE, {"body": LF.replace(old, new)})):
        text, problems = check(task, LF, answer)
        assert text == LF and len(problems) == 1 and "protected part" in problems[0]


def test_an_edit_may_not_add_a_lint_error():
    text, problems = check(FIX_LATEX, LF, edits(("First point", "First {point")))
    assert text == LF and len(problems) == 1 and "(braces)" in problems[0]


def test_a_fix_may_leave_the_old_errors_and_remove_them():
    other = edits(("First point", "1st point"))
    assert check(FIX_LATEX, BROKEN, other)[1] == []               # the old error stays: not a new one
    assert check(FIX_LATEX, BROKEN, edits(("{Hello", "{Hello}")))[0] == LF


def test_a_translation_may_not_cite_a_key_that_is_not_in_the_bibliography():
    cited = LF.replace("First point", "\\cite{old2000}")
    assert check(TRANSLATE, cited, {"body": cited.replace("old2000", "older")})[1][0].startswith(
        "the new text has a LaTeX error (citation)")


def test_every_task_has_a_schema_that_names_its_answer():
    assert TRANSLATE.schema["required"] == ["body"]
    assert FIX_LATEX.schema["required"] == ["edits"] and FIX_LATEX.answer == "edits" and TRANSLATE.answer == "body"


# -- the other tasks: requests ----------------------------------------------------------------------

def test_an_update_request_has_the_source_the_translation_and_the_rules():
    request = claude_tasks.update_request("New text.", "Alter Text.", "EN", "DE", "du", "slide = Folie")
    assert request.startswith("Update this German translation to match the current English source.\n")
    assert 'with "du" (informal)' in request and "slide = Folie\n<source>\nNew text.\n</source>" in request
    assert request.endswith("<slide>\nAlter Text.\n</slide>")
    assert "Address" not in claude_tasks.update_request("Neu.", "New.", "DE", "EN")


def test_a_proofread_request_names_the_language_and_keeps_the_german_address():
    german = claude_tasks.proofread_request("Text.", "DE", "du")
    assert "German slide" in german and '"du"' in german and german.endswith("<slide>\nText.\n</slide>")
    assert '"Sie"' not in claude_tasks.proofread_request("Text.", "EN") and "English slide" in claude_tasks.proofread_request("T", "EN")


def test_title_and_note_requests_carry_the_slide_and_the_current_title():
    assert claude_tasks.title_request(LF).splitlines()[:2] == ["Write a better title for this slide.", "Current title: Hello"]
    assert claude_tasks.note_request(LF).endswith(f"<slide>\n{LF}\n</slide>")
    assert claude_tasks.concise_request(LF).endswith(f"<slide>\n{LF}\n</slide>")


# -- the other tasks: answers --------------------------------------------------------------------------

def test_a_title_replaces_the_frame_title_only():
    new, problems = check(claude_tasks.TITLE, LF, {"title": " A better title "})
    assert problems == [] and new == LF.replace("{Hello}", "{A better title}")


@pytest.mark.parametrize("answer, task, text", [
    ({"title": "two\nlines"}, claude_tasks.TITLE, LF), ({"title": " "}, claude_tasks.TITLE, LF),
    ({"title": 3}, claude_tasks.TITLE, LF), ({"note": ""}, claude_tasks.NOTE, LF), ({"body": "x"}, claude_tasks.NOTE, LF),
    ({"title": "T"}, claude_tasks.TITLE, "no frame here\n")])
def test_a_bad_title_or_note_is_refused(answer, task, text):
    new, problems = check(task, text, answer)
    assert new == text and len(problems) == 1


def test_a_note_is_added_before_the_frames_end():
    new, problems = check(claude_tasks.NOTE, LF, {"note": "Say hello."})
    assert problems == [] and new.endswith("\t\\note{Say hello.}\n\\end{standardframe}\n")


def test_a_note_or_title_may_not_add_a_lint_error():
    assert "(braces)" in check(claude_tasks.NOTE, LF, {"note": "a { b"})[1][0]
    assert "(braces)" in check(claude_tasks.TITLE, LF, {"title": "a { b"})[1][0]


def test_proofreading_answers_with_edits_and_an_empty_list_changes_nothing():
    assert check(claude_tasks.PROOFREAD, LF, {"edits": []}) == (LF, [])
    assert check(claude_tasks.PROOFREAD, LF, edits(("First point", "First points")))[0] == LF.replace("First point", "First points")


def test_a_shortened_text_keeps_environments_overlays_and_citations():
    text = LF.replace("First point", "\\only<2->{First point} \\fullcite{old2000}")
    shorter = text.replace("First point", "First")
    assert check(claude_tasks.CONCISE, text, {"body": shorter}) == (shorter, [])
    for lost in (text.replace("<2->", ""), text.replace(" \\fullcite{old2000}", ""),
                 text.replace("\t\\end{itemize}\n", "").replace("\t\\begin{itemize}\n", "")):
        new, problems = check(claude_tasks.CONCISE, text, {"body": lost})
        assert new == text and len(problems) == 1 and "must keep every environment" in problems[0]
    assert "<2->" in check(claude_tasks.CONCISE, text, {"body": text.replace("<2->", "")})[1][0]
    # the other body task does not look at the structure
    assert check(TRANSLATE, text, {"body": text.replace("<2->", "")})[0] != text


def test_an_updated_translation_is_a_body_with_the_protected_parts_unchanged():
    assert check(claude_tasks.UPDATE_TRANSLATION, LF, {"body": LF.replace("Hello", "Hallo")})[1] == []
    assert "protected part" in check(claude_tasks.UPDATE_TRANSLATION, LF, {"body": LF.replace("1-0-0", "2-0-0")})[1][0]


def test_every_task_names_its_answer():
    assert [t.answer for t in (claude_tasks.UPDATE_TRANSLATION, claude_tasks.PROOFREAD, claude_tasks.CONCISE,
                               claude_tasks.TITLE, claude_tasks.NOTE)] == ["body", "edits", "body", "title", "note"]


def test_a_summary_is_read_not_checked_against_the_text_it_summarises():
    sent = "<slide>\n% a comment\n\\setSlideVersion{1-0-0}\n</slide>"
    assert check(claude_tasks.SUMMARISE, sent, {"summary": "A short deck."}) == ("A short deck.", [])
    assert check(claude_tasks.SUMMARISE, sent, {"summary": " "})[1] and check(claude_tasks.SUMMARISE, sent, {})[1]


def test_the_summary_request_cuts_each_slide_and_the_whole():
    cut = claude_tasks.summarise_request(["x" * (claude_tasks.SLIDE_CHARS + 500)])
    assert cut.count("x") == claude_tasks.SLIDE_CHARS
    many = claude_tasks.summarise_request(["y" * claude_tasks.SLIDE_CHARS] * 50)
    assert len(many) <= claude_tasks.DECK_CHARS + 100 and many.endswith("more slides are not shown.)")
    assert many.count("<slide>") == claude_tasks.DECK_CHARS // (claude_tasks.SLIDE_CHARS + len("<slide>\n\n</slide>"))
