# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI task requests and validation of model answers."""
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


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)


def test_translation_request_includes_language_address_and_glossary():
    glossary = "slide = Folie\ndeck = Foliensatz\n"
    request = ai_tasks.translate_request("A slide.", "EN", "DE", "du", glossary)
    assert "from English to German" in request and "Address the audience informally." in request
    assert request.endswith(glossary + "<slide>\nA slide.\n</slide>")
    request = ai_tasks.translate_request("Ouvrir.", "FR", "EN")
    assert "from French to English" in request and "Address the audience formally." in request
    assert request.endswith("<slide>\nOuvrir.\n</slide>")


def test_a_fix_request_names_the_errors_and_not_the_warnings(ctx):
    text = BROKEN.replace("First point", "a_b")                # an error and a warning (underscore)
    request = ai_tasks.fix_request(text, latex_lint.lint_text(ctx, text))
    assert "(braces)" in request and "(underscore)" not in request and request.endswith(f"<slide>\n{text}\n</slide>")


def test_a_repair_request_shows_the_refused_answer_and_why():
    request = ai_tasks.repair_request("THE REQUEST", {"body": "x"}, ["first problem", "second"])
    assert request.startswith("THE REQUEST") and '{"body": "x"}' in request
    assert "- first problem\n- second" in request


def test_edits_are_applied_to_the_captured_text_together(ctx):
    answer = edits(("{Hello", "{Hello}"), ("First point", "1st point"), ("\\item Second point", "\\item 2nd"))
    assert check(ctx, FIX_LATEX, BROKEN, answer) == (
        LF.replace("First point", "1st point").replace("Second point", "2nd"), [])


@pytest.mark.parametrize("answer, task", [
    (None, TRANSLATE), ({"body": ""}, TRANSLATE), ({"body": 3}, TRANSLATE),
    ({"edits": "x"}, FIX_LATEX), ({"edits": [{"before": "First"}]}, FIX_LATEX),
    ({"edits": [{"before": 1, "after": "x"}]}, FIX_LATEX),
    ({"edits": ["x"]}, FIX_LATEX),
])
def test_an_answer_of_the_wrong_shape_is_refused(ctx, answer, task):
    text, problems = check(ctx, task, LF, answer)
    assert text == LF and len(problems) == 1 and problems[0].startswith("the answer must be")


def test_all_bad_edits_are_reported_and_nothing_is_applied(ctx):
    answer = edits(("not in the slide", "x"), ("point", "p"), ("", "x"), ("First point", "1st"),
                   ("point\n\t\t\\item Second", "x"))
    text, problems = check(ctx, FIX_LATEX, LF, answer)
    assert text == LF and len(problems) == 4
    for problem, expected in zip(problems, ("does not occur", "more than once", "is empty", "overlap")):
        assert expected in problem


@pytest.mark.parametrize("task, old, new", [
    (FIX_LATEX, "\\setSlideVersion{1-0-0}", "\\setSlideVersion{9-9-9}"),
    (TRANSLATE, "%% Included in decks: test\n%%\n", ""),
    (ai_tasks.UPDATE_TRANSLATION, "\\setSlideVersion{1-0-0}", "\\setSlideVersion{2-0-0}"),
])
def test_protected_parts_must_not_change(ctx, task, old, new):
    answer = edits((old, new)) if task == FIX_LATEX else {"body": LF.replace(old, new)}
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


def test_an_update_request_has_the_source_the_translation_and_the_rules():
    request = ai_tasks.update_request("New text.", "Alter Text.", "EN", "DE", "du", "slide = Folie")
    assert request.startswith("Update this German translation to match the current English source.\n")
    assert "Address the audience informally." in request and "slide = Folie\n<source>\nNew text.\n</source>" in request
    assert request.endswith("<slide>\nAlter Text.\n</slide>")


def test_a_proofread_request_names_the_language_and_keeps_the_german_address():
    german = ai_tasks.proofread_request("Text.", "DE", "informal")
    assert "German slide" in german and "addressed informally" in german and german.endswith("<slide>\nText.\n</slide>")
    assert "French slide" in ai_tasks.proofread_request("Texte.", "FR")


def test_title_and_note_requests_carry_the_slide_and_the_current_title():
    assert ai_tasks.title_request(LF).splitlines()[:2] == ["Write a better title for this slide.", "Current title: Hello"]
    assert ai_tasks.note_request(LF).endswith(f"<slide>\n{LF}\n</slide>")
    assert ai_tasks.concise_request(LF).endswith(f"<slide>\n{LF}\n</slide>")


def test_a_title_replaces_the_frame_title_only(ctx):
    new, problems = check(ctx, ai_tasks.TITLE, LF, {"title": " A better title "})
    assert problems == [] and new == LF.replace("{Hello}", "{A better title}")


@pytest.mark.parametrize("answer, task, text", [
    ({"title": "two\nlines"}, ai_tasks.TITLE, LF), ({"note": " "}, ai_tasks.NOTE, LF),
    ({"title": "T"}, ai_tasks.TITLE, "no frame here\n")])
def test_a_bad_title_or_note_is_refused(ctx, answer, task, text):
    new, problems = check(ctx, task, text, answer)
    assert new == text and len(problems) == 1


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
    translated = text.replace("<2->", "")
    assert check(ctx, TRANSLATE, text, {"body": translated}) == (translated, [])


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


def finding(cls="body", severity="error", measured=2.8, threshold=3.3, template_level=False, rule="text_size"):
    return readability.Finding("abc", 1, rule, cls, severity, measured, threshold, "min", "% of slide height",
                               (0.1, 0.3, 0.9, 0.6), "First point", "Enlarge it.", count=2, file="abc-EN-Hello-current.tex",
                               template_level=template_level)


def readable_report(*findings):
    slide = readability.SlideReport("abc", 1, "abc-EN-Hello-current.tex", list(findings), height_pt=272.0)
    return readability.Report([slide]).to_dict(fixable_only=True)


def test_readable_request_includes_fixable_findings_and_point_sizes():
    report = readable_report(finding(), finding("image", "warning", 12.0, 25.0, rule="image_size"),
                             finding("citation", "error", 1.25, 2.2, template_level=True))
    request = ai_tasks.readable_request(LF, report)
    assert "272 pt high" in request and "body text and headings 9.0 pt (3.3 %)" in request
    assert "sources and footnotes 6.0 pt" in request
    data = json.loads(request.split("Findings (JSON):\n")[1].split("\n<slide>")[0])
    assert [f["rule"] for f in data["findings"]] == ["text_size", "image_size"]
    body = data["findings"][0]
    assert (body["measured"], body["threshold"], body["unit"], body["needs"]) == (2.8, 3.3, "% of slide height", "min")
    assert not {"slide_id", "file", "template_level"} & body.keys()
    assert request.endswith(f"<slide>\n{LF}\n</slide>")


def test_a_relaid_out_slide_is_checked_like_any_body(ctx):
    bigger = LF.replace("\\begin{itemize}", "\\begin{columns}\\column{0.5\\textwidth}\\small\n\t\\begin{itemize}", 1) \
        .replace("\\end{itemize}", "\\end{itemize}\\end{columns}", 1)
    assert check(ctx, ai_tasks.READABLE, LF, {"body": bigger, "note": "Split it."}) == (bigger, [])
    assert "protected part" in check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("1-0-0", "2-0-0")})[1][0]
    assert check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("{overlay}", "{moved}")})[1] == []
    new, problems = check(ctx, ai_tasks.READABLE, LF, {"body": LF.replace("{Hello}", "{Hello")})
    assert new == LF and "LaTeX error" in problems[0]
    assert check(ctx, ai_tasks.READABLE, LF, {"body": LF, "note": "Split it."}) == (LF, [])


def test_the_note_is_the_models_remark_for_readable_only():
    assert ai_tasks.answer_note(ai_tasks.READABLE, {"body": "x", "note": " Split after the table. "}) == "Split after the table."
    assert ai_tasks.answer_note(ai_tasks.READABLE, None) == ""
    assert ai_tasks.answer_note(ai_tasks.NOTE, {"note": "a speaker note"}) == ""
