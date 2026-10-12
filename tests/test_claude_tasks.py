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
    assert FIX_LATEX.schema["required"] == ["edits"] and FIX_LATEX.edits and not TRANSLATE.edits
