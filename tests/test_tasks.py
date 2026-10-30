# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude Code tasks (ai/ai_tasks.py): the request text, and the check that decides whether an answer
may be applied: well formed, every edit's `before` found exactly once, protected parts of the slide unchanged,
no lint error the captured text did not have."""
from __future__ import annotations

import json

import pytest
from slidemage.project import ProjectContext
from conftest import SLIDE_TEXT

from slidemage import latex_lint, readability
from slidemage.ai import tasks as ai_tasks
from slidemage.ai.tasks import FIX_LATEX, TRANSLATE, check

LF = SLIDE_TEXT.replace("\r\n", "\n")
BROKEN = LF.replace("{Hello}", "{Hello")           # an unclosed brace: a lint error


def edits(*pairs: tuple[str, str]) -> dict:
    return {"edits": [{"before": before, "after": after} for before, after in pairs]}


# -- requests ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("address, line", [("Sie", 'with "Sie" (formal)'), ("du", 'with "du" (informal)')])
def test_a_translation_into_german_says_how_to_address_the_audience(address, line):
    request = ai_tasks.translate_request("Open the file.", "EN", "DE", address)
    assert "from English to German" in request and line in request
    assert request.endswith("<slide>\nOpen the file.\n</slide>")


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)


def test_a_translation_into_english_has_no_form_of_address():
    request = ai_tasks.translate_request("Datei öffnen.", "DE", "EN", "Sie")
    assert "from German to English" in request and "Sie" not in request


def test_the_glossary_goes_into_the_request_as_it_is():
    glossary = "slide = Folie\ndeck = Foliensatz\n"
    request = ai_tasks.translate_request("A slide.", "EN", "DE", glossary=glossary)
    assert "slide = Folie\ndeck = Foliensatz\n<slide>" in request
    assert "Glossary" not in ai_tasks.translate_request("A slide.", "EN", "DE")


def test_a_fix_request_names_the_errors_and_not_the_warnings(ctx):
    text = BROKEN.replace("First point", "a_b")                # an error and a warning (underscore)
    request = ai_tasks.fix_request(text, latex_lint.lint_text(ctx, text))
    assert "(braces)" in request and "(underscore)" not in request and request.endswith(f"<slide>\n{text}\n</slide>")


def test_a_repair_request_shows_the_refused_answer_and_why():
    request = ai_tasks.repair_request("THE REQUEST", {"body": "x"}, ["first problem", "second"])
    assert request.startswith("THE REQUEST") and '{"body": "x"}' in request
    assert "- first problem\n- second" in request


# -- answers that may be applied ---------------------------------------------------------------------

def test_a_body_is_the_new_text(ctx):
    assert check(ctx, TRANSLATE, LF, {"body": LF.replace("Hello", "Hallo")}) == (LF.replace("Hello", "Hallo"), [])


def test_edits_are_applied_to_the_captured_text_together(ctx):
    answer = edits(("{Hello", "{Hello}"), ("First point", "1st point"), ("\\item Second point", "\\item 2nd"))
    assert check(ctx, FIX_LATEX, BROKEN, answer) == (
        LF.replace("First point", "1st point").replace("Second point", "2nd"), [])


def test_no_edits_or_edits_that_change_nothing_leave_the_text_alone(ctx):
    assert check(ctx, FIX_LATEX, LF, {"edits": []}) == (LF, [])
    assert check(ctx, FIX_LATEX, LF, edits(("First", "First"))) == (LF, [])
    assert check(ctx, TRANSLATE, LF, {"body": LF}) == (LF, [])


@pytest.mark.parametrize("answer, task", [
    (None, TRANSLATE), ({}, TRANSLATE), ({"body": ""}, TRANSLATE), ({"body": 3}, TRANSLATE),
    ({"edits": []}, TRANSLATE), ({"body": "x"}, FIX_LATEX), ({"edits": "x"}, FIX_LATEX),
    ({"edits": [{"before": "First"}]}, FIX_LATEX), ({"edits": [{"before": 1, "after": "x"}]}, FIX_LATEX),
    ({"edits": ["x"]}, FIX_LATEX),
])
def test_an_answer_of_the_wrong_shape_is_refused(ctx, answer, task):
    text, problems = check(ctx, task, LF, answer)
    assert text == LF and len(problems) == 1 and problems[0].startswith("the answer must be")


@pytest.mark.parametrize("answer, expected", [
    (edits(("not in the slide", "x")), "does not occur"),
    (edits(("point", "p")), "more than once"),
    (edits(("", "x")), "is empty"),
    (edits(("First point", "1st"), ("point\n\t\t\\item Second", "x")), "overlap"),
])
def test_an_edit_whose_before_is_not_found_exactly_once_is_refused(ctx, answer, expected):
    text, problems = check(ctx, FIX_LATEX, LF, answer)
    assert text == LF and any(expected in problem for problem in problems)


def test_every_bad_edit_is_reported(ctx):
    _, problems = check(ctx, FIX_LATEX, LF, edits(("nowhere", "x"), ("point", "p")))
    assert len(problems) == 2 and problems[0].startswith("edit 1") and problems[1].startswith("edit 2")


# -- protected parts, lint ---------------------------------------------------------------------------

@pytest.mark.parametrize("old, new", [
    ("\\setSlideVersion{1-0-0}", "\\setSlideVersion{9-9-9}"),
    ("%% Included in decks: test\n%%\n", ""),
], ids=["version-line", "deck-header"])
def test_protected_parts_must_not_change(ctx, old, new):
    for task, answer in ((FIX_LATEX, edits((old, new))), (TRANSLATE, {"body": LF.replace(old, new)})):
        text, problems = check(ctx, task, LF, answer)
        assert text == LF and len(problems) == 1 and "protected part" in problems[0]


def test_an_edit_may_not_add_a_lint_error(ctx):
    text, problems = check(ctx, FIX_LATEX, LF, edits(("First point", "First {point")))
    assert text == LF and len(problems) == 1 and "(braces)" in problems[0]


def test_a_fix_may_leave_the_old_errors_and_remove_them(ctx):
    other = edits(("First point", "1st point"))
    assert check(ctx, FIX_LATEX, BROKEN, other)[1] == []               # the old error stays: not a new one
    assert check(ctx, FIX_LATEX, BROKEN, edits(("{Hello", "{Hello}")))[0] == LF


def test_a_translation_may_not_cite_a_key_that_is_not_in_the_bibliography(ctx):
    cited = LF.replace("First point", "\\cite{old2000}")
    assert check(ctx, TRANSLATE, cited, {"body": cited.replace("old2000", "older")})[1][0].startswith(
        "the new text has a LaTeX error (citation)")


def test_every_task_has_a_schema_that_names_its_answer():
    assert TRANSLATE.schema["required"] == ["body"]
    assert FIX_LATEX.schema["required"] == ["edits"] and FIX_LATEX.answer == "edits" and TRANSLATE.answer == "body"


# -- the other tasks: requests ----------------------------------------------------------------------

def test_an_update_request_has_the_source_the_translation_and_the_rules():
    request = ai_tasks.update_request("New text.", "Alter Text.", "EN", "DE", "du", "slide = Folie")
    assert request.startswith("Update this German translation to match the current English source.\n")
    assert 'with "du" (informal)' in request and "slide = Folie\n<source>\nNew text.\n</source>" in request
    assert request.endswith("<slide>\nAlter Text.\n</slide>")
    assert "Address" not in ai_tasks.update_request("Neu.", "New.", "DE", "EN")


def test_a_proofread_request_names_the_language_and_keeps_the_german_address():
    german = ai_tasks.proofread_request("Text.", "DE", "du")
    assert "German slide" in german and '"du"' in german and german.endswith("<slide>\nText.\n</slide>")
    assert '"Sie"' not in ai_tasks.proofread_request("Text.", "EN") and "English slide" in ai_tasks.proofread_request("T", "EN")


def test_title_and_note_requests_carry_the_slide_and_the_current_title():
    assert ai_tasks.title_request(LF).splitlines()[:2] == ["Write a better title for this slide.", "Current title: Hello"]
    assert ai_tasks.note_request(LF).endswith(f"<slide>\n{LF}\n</slide>")
    assert ai_tasks.concise_request(LF).endswith(f"<slide>\n{LF}\n</slide>")


# -- the other tasks: answers --------------------------------------------------------------------------

def test_a_title_replaces_the_frame_title_only(ctx):
    new, problems = check(ctx, ai_tasks.TITLE, LF, {"title": " A better title "})
    assert problems == [] and new == LF.replace("{Hello}", "{A better title}")


@pytest.mark.parametrize("answer, task, text", [
    ({"title": "two\nlines"}, ai_tasks.TITLE, LF), ({"title": " "}, ai_tasks.TITLE, LF),
    ({"title": 3}, ai_tasks.TITLE, LF), ({"note": ""}, ai_tasks.NOTE, LF), ({"body": "x"}, ai_tasks.NOTE, LF),
    ({"title": "T"}, ai_tasks.TITLE, "no frame here\n")])
def test_a_bad_title_or_note_is_refused(ctx, answer, task, text):
    new, problems = check(ctx, task, text, answer)
    assert new == text and len(problems) == 1


def test_a_note_is_added_before_the_frames_end(ctx):
    new, problems = check(ctx, ai_tasks.NOTE, LF, {"note": "Say hello."})
    assert problems == [] and new.endswith("\t\\note{Say hello.}\n\\end{standardframe}\n")


def test_a_note_or_title_may_not_add_a_lint_error(ctx):
    assert "(braces)" in check(ctx, ai_tasks.NOTE, LF, {"note": "a { b"})[1][0]
    assert "(braces)" in check(ctx, ai_tasks.TITLE, LF, {"title": "a { b"})[1][0]


def test_proofreading_answers_with_edits_and_an_empty_list_changes_nothing(ctx):
    assert check(ctx, ai_tasks.PROOFREAD, LF, {"edits": []}) == (LF, [])
    assert check(ctx, ai_tasks.PROOFREAD, LF, edits(("First point", "First points")))[0] == LF.replace("First point", "First points")


def test_a_shortened_text_keeps_environments_overlays_and_citations(ctx):
    text = LF.replace("First point", "\\only<2->{First point} \\fullcite{old2000}")
    shorter = text.replace("First point", "First")
    assert check(ctx, ai_tasks.CONCISE, text, {"body": shorter}) == (shorter, [])
    for lost in (text.replace("<2->", ""), text.replace(" \\fullcite{old2000}", ""),
                 text.replace("\t\\end{itemize}\n", "").replace("\t\\begin{itemize}\n", "")):
        new, problems = check(ctx, ai_tasks.CONCISE, text, {"body": lost})
        assert new == text and len(problems) == 1 and "must keep every environment" in problems[0]
    assert "<2->" in check(ctx, ai_tasks.CONCISE, text, {"body": text.replace("<2->", "")})[1][0]
    # the other body task does not look at the structure
    assert check(ctx, TRANSLATE, text, {"body": text.replace("<2->", "")})[0] != text


def test_an_updated_translation_is_a_body_with_the_protected_parts_unchanged(ctx):
    assert check(ctx, ai_tasks.UPDATE_TRANSLATION, LF, {"body": LF.replace("Hello", "Hallo")})[1] == []
    assert "protected part" in check(ctx, ai_tasks.UPDATE_TRANSLATION, LF, {"body": LF.replace("1-0-0", "2-0-0")})[1][0]


def test_every_task_names_its_answer():
    assert [t.answer for t in (ai_tasks.UPDATE_TRANSLATION, ai_tasks.PROOFREAD, ai_tasks.CONCISE,
                               ai_tasks.TITLE, ai_tasks.NOTE)] == ["body", "edits", "body", "title", "note"]


def test_a_summary_is_read_not_checked_against_the_text_it_summarises(ctx):
    sent = "<slide>\n% a comment\n\\setSlideVersion{1-0-0}\n</slide>"
    assert check(ctx, ai_tasks.SUMMARISE, sent, {"summary": "A short deck."}) == ("A short deck.", [])
    assert check(ctx, ai_tasks.SUMMARISE, sent, {"summary": " "})[1] and check(ctx, ai_tasks.SUMMARISE, sent, {})[1]


def test_the_summary_request_cuts_each_slide_and_the_whole():
    cut = ai_tasks.summarise_request(["x" * (ai_tasks.SLIDE_CHARS + 500)])
    assert cut.count("x") == ai_tasks.SLIDE_CHARS
    many = ai_tasks.summarise_request(["y" * ai_tasks.SLIDE_CHARS] * 50)
    assert len(many) <= ai_tasks.DECK_CHARS + 100 and many.endswith("more slides are not shown.)")
    assert many.count("<slide>") == ai_tasks.DECK_CHARS // (ai_tasks.SLIDE_CHARS + len("<slide>\n\n</slide>"))


# -- Make readable --------------------------------------------------------------------------------------

def finding(cls="body", severity="error", measured=2.8, threshold=3.3, template_level=False, rule="text_size"):
    return readability.Finding("abc", 1, rule, cls, severity, measured, threshold, "min", "% of slide height",
                               (0.1, 0.3, 0.9, 0.6), "First point", "Enlarge it.", count=2, file="abc-EN-Hello-current.tex",
                               template_level=template_level)


def readable_report(*findings):
    slide = readability.SlideReport("abc", 1, "abc-EN-Hello-current.tex", list(findings), height_pt=272.0)
    return readability.Report([slide]).to_dict(fixable_only=True)


def test_a_readable_request_carries_the_slide_the_findings_and_the_floors_in_points():
    request = ai_tasks.readable_request(LF, readable_report(finding(), finding("image", "warning", 12.0, 25.0, rule="image_size")))
    head, rest = request.split("Findings (JSON):\n")
    assert head.startswith("Make this slide readable.") and "272 pt high" in head
    assert "body text and headings 9.0 pt (3.3 %)" in head and "sources and footnotes 6.0 pt" in head
    data = json.loads(rest.split("\n<slide>")[0])
    assert [f["rule"] for f in data["findings"]] == ["text_size", "image_size"]
    assert data["findings"][0]["measured"] == 2.8 and data["findings"][0]["threshold"] == 3.3
    assert data["findings"][0]["unit"] == "% of slide height" and data["findings"][0]["needs"] == "min"
    assert data["thresholds"]["body_pct"] == 3.3 and data["thresholds"]["image_min_area_pct"] == 25.0
    assert not {"slide_id", "file", "template_level"} & set(data["findings"][0])
    assert request.endswith(f"<slide>\n{LF}\n</slide>")


def test_findings_set_by_the_template_are_not_in_the_request():
    report = readable_report(finding(), finding("citation", "error", 1.25, 2.2, template_level=True))
    request = ai_tasks.readable_request(LF, report)
    data = json.loads(request.split("Findings (JSON):\n")[1].split("\n<slide>")[0])
    assert [f["cls"] for f in data["findings"]] == ["body"] and "1.25" not in request
    assert all(f["cls"] == "body" for f in report["slides"][0]["findings"])


def test_the_readable_rules_say_what_may_change_and_what_to_do_when_it_cannot_fit():
    rules = ai_tasks.READABLE.rules
    for phrase in ("columns", "\\includegraphics", "\\small", "rather than \\fontsize", "itemize", "trim wording only",
                   "never change what a statement says", "preamble", "split the slide", "`note`", "\\setSlideVersion"):
        assert phrase in rules, phrase
    assert ai_tasks.READABLE.answer == "body" and ai_tasks.READABLE.schema["required"] == ["body"]
    assert set(ai_tasks.READABLE.schema["properties"]) == {"body", "note"}


def test_a_relaid_out_slide_is_checked_like_any_body(ctx):
    bigger = LF.replace("\\begin{itemize}", "\\begin{columns}\\column{0.5\\textwidth}\\small\n\t\\begin{itemize}", 1) \
        .replace("\\end{itemize}", "\\end{itemize}\\end{columns}", 1)
    assert check(ctx, ai_tasks.READABLE, LF, {"body": bigger, "note": "Split it."}) == (bigger, [])
    assert "protected part" in check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("1-0-0", "2-0-0")})[1][0]
    assert check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("{overlay}", "{moved}")})[1] == []
    new, problems = check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("{Hello}", "{Hello")})
    assert new == LF and "LaTeX error" in problems[0]
    assert check(ctx, ai_tasks.READABLE, LF, {"body": " "})[1] and check(ctx, ai_tasks.READABLE, LF, {})[1]
    assert check(ctx, ai_tasks.READABLE, LF, {"body": LF, "note": "Split it."}) == (LF, [])


def test_the_note_is_the_models_remark_for_readable_only():
    assert ai_tasks.answer_note(ai_tasks.READABLE, {"body": "x", "note": " Split after the table. "}) == "Split after the table."
    assert ai_tasks.answer_note(ai_tasks.READABLE, {"body": "x"}) == ""
    assert ai_tasks.answer_note(ai_tasks.READABLE, None) == ""
    assert ai_tasks.answer_note(ai_tasks.NOTE, {"note": "a speaker note"}) == ""
