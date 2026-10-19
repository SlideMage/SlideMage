# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite selection and Proofread selection, the parts without a window (Claude Code reviews plan, step R1): the
capture of a selection (selection.py), the requests, and claude_tasks.check on a range of the file: every character
outside the range stays, the protected parts and the lint errors are the whole file's, an edit's `before` must occur
exactly once in the selection."""
from __future__ import annotations

import pytest
from conftest import SLIDE_TEXT
from slidemage.project import ProjectContext

from slidemage import protected_regions, selection
from slidemage.ai import claude_runner, claude_tasks, provider_tasks
from slidemage.ai.claude_tasks import PROOFREAD_SELECTION, REWRITE, check

LF = SLIDE_TEXT.replace("\r\n", "\n")
FIRST = LF.index("First point")
SPAN = (FIRST, FIRST + len("First point"))


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)


def rewritten(text: str, **kwargs):
    return check(kwargs.pop("ctx"), REWRITE, LF, {"text": text}, SPAN)


# -- the capture ------------------------------------------------------------------------------------

def test_a_selection_in_the_text_of_a_slide_is_captured_with_the_whole_file():
    chosen = selection.capture("x.tex", LF, *SPAN)
    assert chosen.selected == "First point" and chosen.text == LF and (chosen.start, chosen.end) == SPAN


@pytest.mark.parametrize("start, end", [(5, 5), (FIRST + 5, FIRST + 6), (LF.index("\t\t\\item"), LF.index("\\item"))])
def test_nothing_or_blanks_selected_is_no_selection(start, end):
    with pytest.raises(selection.SelectionError, match="Select some text"):
        selection.capture("x.tex", LF, start, end)


@pytest.mark.parametrize("piece", ["%% Included in decks: test", "\\setSlideVersion{1-0-0}", "\\vbox to 0pt{\\vss\\hbox{overlay}}"])
def test_a_selection_that_touches_a_protected_part_is_refused(piece):
    first = LF.index(piece)
    for start, end in ((first, first + len(piece)), (first + 2, first + 6), (FIRST, first + 3 if first > FIRST else first + 8)):
        if start >= end:
            continue
        with pytest.raises(selection.SelectionError, match="protected part"):
            selection.capture("x.tex", LF, min(start, end), max(start, end))


def test_a_selection_next_to_a_protected_part_is_fine():
    (start, end), = protected_regions.protected_spans(LF)[-1:]
    assert selection.capture("x.tex", LF, end, end + len("\n\\end{standardframe}")).selected.endswith("\\end{standardframe}")


# -- the requests -----------------------------------------------------------------------------------

def test_a_rewrite_request_has_the_instruction_the_selection_and_its_context():
    request = claude_tasks.rewrite_request(LF, *SPAN, "Simplify the wording.")
    assert request.startswith("Rewrite the selection of this slide. Instruction: Simplify the wording.\n<before>\n")
    assert "\n<selection>\nFirst point\n</selection>\n<after>\n\n\t\t\\item Second point" in request
    assert request.index("\\begin{itemize}") < request.index("<selection>")
    assert claude_tasks.rewrite_request(LF, *SPAN, "  as a question  ").splitlines()[0].endswith("Instruction: as a question")


def test_the_context_of_a_long_slide_is_cut():
    text = "x" * 5000 + "SELECTED" + "y" * 5000
    request = claude_tasks.rewrite_request(text, 5000, 5008, "Shorten")
    assert request.count("x") == request.count("y") == selection.CONTEXT_CHARS
    assert "<selection>\nSELECTED\n</selection>" in request


def test_a_proofread_request_names_the_language_and_keeps_the_german_address():
    de = claude_tasks.proofread_selection_request(LF, *SPAN, "DE", "du")
    assert "German slide" in de and '"du"' in de and "<selection>\nFirst point\n</selection>" in de
    assert '"S' not in claude_tasks.proofread_selection_request(LF, *SPAN, "EN")


# -- check: a rewrite replaces the range only -------------------------------------------------------------

def test_a_rewrite_replaces_exactly_the_range_and_nothing_outside_it_changes(ctx):
    new, problems = check(ctx, REWRITE, LF, {"text": "Opening remark"}, SPAN)
    assert problems == [] and new == LF.replace("First point", "Opening remark")
    assert new[:SPAN[0]] == LF[:SPAN[0]] and new.endswith(LF[SPAN[1]:])


def test_the_whitespace_at_the_ends_of_the_selection_stays(ctx):
    start, end = LF.index("\t\t\\item First"), LF.index("\t\\end{itemize}")      # a tab and a line break at the ends
    selected = LF[start:end]
    assert selected.startswith("\t\t") and selected.endswith("point\n")
    new, problems = check(ctx, REWRITE, LF, {"text": "  \\item Only this  "}, (start, end))
    assert problems == [] and new == LF[:start] + "\t\t\\item Only this\n" + LF[end:]


def test_a_rewrite_that_changes_nothing_is_the_text_unchanged(ctx):
    assert check(ctx, REWRITE, LF, {"text": "First point"}, SPAN) == (LF, [])


@pytest.mark.parametrize("answer", [None, {"body": "x"}, {"text": ""}, {"text": "  "}, {"text": 3}])
def test_a_rewrite_answer_must_be_a_nonempty_text(ctx, answer):
    new, problems = check(ctx, REWRITE, LF, answer, SPAN)
    assert new == LF and problems == ['the answer must be {"text": "..."} with the text']


def test_a_rewrite_that_breaks_a_protected_part_is_refused(ctx):
    new, problems = check(ctx, REWRITE, LF, {"text": "x\n\\setSlideVersion{9-9-9}"}, SPAN)
    assert new == LF and problems and "protected" in problems[0]


def test_a_rewrite_with_a_new_latex_error_is_refused_as_a_whole_file_check(ctx):
    new, problems = check(ctx, REWRITE, LF, {"text": "First {point"}, SPAN)
    assert new == LF and "LaTeX error" in problems[0]
    new, problems = check(ctx, REWRITE, LF, {"text": "First \\textbf{point}"}, SPAN)
    assert problems == [] and "\\textbf{point}" in new


def test_an_error_the_file_already_had_is_not_the_rewrites(ctx):
    broken = LF.replace("{Hello}", "{Hello")
    start = broken.index("First point")
    new, problems = check(ctx, REWRITE, broken, {"text": "Opening"}, (start, start + 11))
    assert problems == [] and "Opening" in new


# -- check: a proofread is an edit list of the selection ---------------------------------------------------

def test_proofread_edits_are_found_in_the_selection_only(ctx):
    text = LF.replace("First point", "First pont and Second point")
    start = text.index("First pont")
    span = (start, start + len("First pont and Second point"))
    new, problems = check(ctx, PROOFREAD_SELECTION, text, {"edits": [{"before": "pont and", "after": "point and"}]}, span)
    assert problems == [] and new == text.replace("First pont and", "First point and")
    new, problems = check(ctx, PROOFREAD_SELECTION, text, {"edits": [{"before": "Hello", "after": "Hallo"}]}, span)
    assert new == text and 'does not occur in the source' in problems[0]            # in the file, but not in the selection
    new, problems = check(ctx, PROOFREAD_SELECTION, text, {"edits": [{"before": "po", "after": "Po"}]}, span)
    assert new == text and "occurs more than once" in problems[0]


def test_a_proofread_with_nothing_to_fix_changes_nothing(ctx):
    assert check(ctx, PROOFREAD_SELECTION, LF, {"edits": []}, SPAN) == (LF, [])


def test_a_proofread_edit_outside_the_selection_is_not_possible(ctx):
    new, problems = check(ctx, PROOFREAD_SELECTION, LF, {"edits": [{"before": "Second", "after": "2nd"}]}, SPAN)
    assert new == LF and problems


# -- the runners pass the range ---------------------------------------------------------------------------

class Provider:
    is_local, model, label = True, "m", "m"

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def chat(self, messages, **kwargs):
        from slidemage.ai.providers import ChatReply
        self.requests.append(messages[0]["content"])
        return ChatReply(self.replies.pop(0))

    def abort(self):
        pass


def test_the_provider_runner_returns_the_whole_file_with_only_the_range_replaced_and_repairs_once(ctx):
    provider = Provider(['{"text": "First {point"}', '{"text": "Opening"}'])
    request = claude_tasks.rewrite_request(LF, *SPAN, "Shorten")
    outcome = provider_tasks.run_task(ctx, provider, REWRITE, LF, request, span=SPAN)
    assert outcome.status == claude_runner.DONE and outcome.attempts == 2
    assert outcome.text == LF.replace("First point", "Opening")
    assert "Your previous answer was refused" in provider.requests[1]


def test_the_judge_says_nothing_to_change_for_an_unchanged_range(ctx):
    outcome = claude_runner.Outcome(claude_runner.FAILED)
    assert claude_runner.judge(ctx, PROOFREAD_SELECTION, LF, {"edits": []}, outcome, span=SPAN) == []
    assert outcome.status == claude_runner.NOTHING
