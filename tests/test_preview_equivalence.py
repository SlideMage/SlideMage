# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The classifier proves only the audited framework rules it understands."""
from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from slidemage.preview_equivalence import classify_views
from slidemage.preview_requests import PreviewRequest, RenderOptions, SourceRevision
from slidemage.preview_target import PreviewTarget
from slidemage.project import ProjectContext


PREAMBLE = r"""\documentclass{beamer}
\usetheme{gotham}
\input{SlideMage_template_slidemage}
\newcommand{\FooterText}{Equivalence probe}
\def\SMFooterHide{deck}
\begin{document}
"""
VIEWS = ("instructor", "during-course", "after-course")
REPO = Path(__file__).resolve().parents[1]


def specs(tmp_path, body, *, preamble=PREAMBLE, frames=(1, 1, 1), steps=None,
          macro="slide", hidden=(False, False, False), versions=(None, None, None)):
    root = tmp_path / "project"
    (root / "slides").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "example" / ".latexmkrc", root / ".latexmkrc")
    (root / "slide_ids.csv").touch()
    ctx = ProjectContext.at(root)
    result = []
    for view, frame, hide, version in zip(VIEWS, frames, hidden, versions):
        target = PreviewTarget(ctx, macro, "aaa-EN-Probe", version, None, steps, frame, preamble,
                               hidden=hide)
        revision = SourceRevision.capture(target.source_path, body)
        result.append(PreviewRequest(target, revision, view, "EN", RenderOptions(saved=True)))
    return tuple(result)


def groups(result):
    return [decision.group for decision in result.decisions]


def test_plain_slide_shares_when_deck_label_is_hidden(tmp_path):
    classified = classify_views(specs(tmp_path, r"\begin{standardframe}{Plain}Text\end{standardframe}"))
    assert len(set(groups(classified))) == 1
    assert all(d.certain for d in classified.decisions)
    assert classified.evidence and classified.dependencies


def test_footer_label_and_frame_numbers_split(tmp_path):
    labeled = classify_views(specs(tmp_path, "Text", preamble=PREAMBLE.replace(r"\def\SMFooterHide{deck}", "")))
    assert len(set(groups(labeled))) == 3
    assert all("footer deck label" in " ".join(d.reasons) for d in labeled.decisions)
    numbered = classify_views(specs(tmp_path / "numbered", "Text", frames=(3, 2, 2)))
    assert groups(numbered)[0] != groups(numbered)[1] == groups(numbered)[2]


def test_conditional_pause_and_reveal_signatures(tmp_path):
    pauses = classify_views(specs(tmp_path, r"Text\conditionalpause[instructor] More"))
    assert groups(pauses)[0] != groups(pauses)[1] == groups(pauses)[2]
    reveal = classify_views(specs(tmp_path / "reveal", r"Text\deckreveal[2]{Answer}"))
    assert len(set(groups(reveal))) == 3
    final = classify_views(specs(tmp_path / "final", r"Text\deckrevealfinal[2]{Answer}"))
    assert groups(final)[0] != groups(final)[1] == groups(final)[2]
    slidefinal = classify_views(specs(tmp_path / "slidefinal", r"Text\conditionalpause[instructor] More", macro="slidefinal"))
    assert len(set(groups(slidefinal))) == 1


def test_included_rules_and_comments(tmp_path):
    request = specs(tmp_path, r"\input{parts/rules}\% literal percent % \deckreveal{ignored}")
    extra = request[0].target.context.root / "parts" / "rules.tex"
    extra.parent.mkdir()
    extra.write_text(r"\conditionalpause[instructor] Included")
    result = classify_views(request)
    assert groups(result)[0] != groups(result)[1] == groups(result)[2]
    assert any(str(extra.resolve()) == path for path, _ in result.dependencies)
    comments = classify_views(specs(tmp_path / "comments", "% \\deckreveal{ignored}\nPlain"))
    assert len(set(groups(comments))) == 1


def test_unknown_overrides_and_inputs_fail_closed(tmp_path):
    custom = classify_views(specs(tmp_path, r"\renewcommand{\deckreveal}[1]{#1} Text"))
    assert len(set(groups(custom))) == 3
    assert all(not d.certain and "definition" in d.reasons[0] for d in custom.decisions)
    dynamic = classify_views(specs(tmp_path / "dynamic", r"\input{\pickedfile} Text"))
    assert len(set(groups(dynamic))) == 3
    assert all(not d.certain for d in dynamic.decisions)
    escaped = classify_views(specs(tmp_path / "escaped", "^^5cifSMInstructorVersion A^^5celse B^^5cfi"))
    assert all(not d.certain and "escape" in d.reasons[0] for d in escaped.decisions)


def test_hidden_version_and_steps_boundaries(tmp_path):
    hidden = classify_views(specs(tmp_path, "Text", hidden=(False, True, True)))
    assert groups(hidden)[0] is not None and groups(hidden)[1:] == [None, None]
    pinned = classify_views(specs(tmp_path / "pinned", "Text", versions=(None, "1-0-0", "1-0-0")))
    assert groups(pinned)[0] != groups(pinned)[1] == groups(pinned)[2]
    changed_steps = list(specs(tmp_path / "steps", "Text", steps="1"))
    changed_steps[2] = replace(changed_steps[2], target=replace(changed_steps[2].target, steps="2"))
    selected = classify_views(changed_steps)
    assert groups(selected)[0] == groups(selected)[1] != groups(selected)[2]


def test_project_macro_override_and_framework_change_fail_closed(tmp_path, monkeypatch):
    preamble = PREAMBLE.replace(r"\begin{document}", r"\renewcommand{\deckonly}[1]{#1}" + "\n" + r"\begin{document}")
    custom = classify_views(specs(tmp_path, "Text", preamble=preamble))
    assert all(not d.certain for d in custom.decisions)
    framework = tmp_path / "framework"
    framework.mkdir()
    (framework / "SlideMage_base.tex").write_text("changed")
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(framework))
    changed = classify_views(specs(tmp_path / "changed", "Text"))
    assert all(not d.certain and "unaudited framework" in d.reasons[0] for d in changed.decisions)


def test_footer_body_class_theme_and_conditional_preamble_are_not_proofs(tmp_path):
    footer = PREAMBLE.replace(r"\newcommand{\FooterText}{Equivalence probe}",
                              r"\newcommand{\FooterText}{\SMDeckVersion}")
    custom = classify_views(specs(tmp_path, "Text", preamble=footer))
    assert all(not d.certain for d in custom.decisions)
    theme = PREAMBLE.replace(r"\usetheme{gotham}", r"\usetheme{mytheme}")
    assert all(not d.certain for d in classify_views(specs(tmp_path / "theme", "Text", preamble=theme)).decisions)
    conditional = PREAMBLE.replace(r"\def\SMFooterHide{deck}",
                                   r"\ifdefined\FLAG\def\SMFooterHide{deck}\fi")
    assert all(not d.certain for d in classify_views(specs(tmp_path / "conditional", "Text", preamble=conditional)).decisions)
    grouped = PREAMBLE.replace(r"\def\SMFooterHide{deck}", r"{\def\SMFooterHide{deck}}")
    assert all(not d.certain for d in classify_views(specs(tmp_path / "grouped", "Text", preamble=grouped)).decisions)
    delayed = PREAMBLE.replace(r"\def\SMFooterHide{deck}",
                               r"\setbeamertemplate{unused}{\def\SMFooterHide{deck}}")
    assert all(not d.certain for d in classify_views(specs(tmp_path / "delayed", "Text", preamble=delayed)).decisions)


def test_fullbleed_image_list_changes_instructor_sequence(tmp_path):
    one = classify_views(specs(tmp_path, r"\fullbleedframe{media/one.png}"))
    assert len(set(groups(one))) == 1
    many = classify_views(specs(tmp_path / "many", r"\fullbleedframe{media/one.png,media/two.png}"))
    assert groups(many)[0] != groups(many)[1] == groups(many)[2]


def test_default_template_and_stock_framework_fallback(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    shutil.copy2(REPO / "example" / "SlideMage_template_uni-graz.tex",
                 root / "SlideMage_template_uni-graz.tex")
    try:
        (tmp_path / "latex").symlink_to(REPO / "latex", target_is_directory=True)
    except OSError as exc:      # Windows lets only privileged users (or Developer Mode) create symlinks
        pytest.skip(f"cannot create a symlink here: {exc}")
    monkeypatch.delenv("SLIDEMAGE_LATEX")
    classified = classify_views(specs(tmp_path, "Plain", preamble=None))
    assert all(d.certain for d in classified.decisions)
    assert len(set(groups(classified))) == 3  # the default footer shows deck labels
    assert any("SlideMage_template_slidemage.tex" in path for path, _ in classified.dependencies)


def test_actual_institution_shadow_and_non_top_level_imports_fail_closed(tmp_path):
    root = tmp_path / "shadow" / "project"
    root.mkdir(parents=True)
    shutil.copy2(REPO / "example" / "SlideMage_template_uni-graz.tex",
                 root / "SlideMage_template_uni-graz.tex")
    requests = specs(tmp_path / "shadow", "Plain", preamble=PREAMBLE.replace("slidemage", "uni-graz"))
    (root / "decks").mkdir(exist_ok=True)
    (root / "decks" / "SlideMage_template_uni-graz.tex").write_text("custom")
    shadow = classify_views(requests)
    assert all(not d.certain and "shadows institution" in d.reasons[0] for d in shadow.decisions)
    grouped = PREAMBLE.replace(r"\input{SlideMage_template_slidemage}",
                               r"{\input{SlideMage_template_slidemage}}")
    result = classify_views(specs(tmp_path / "grouped", "Plain", preamble=grouped))
    assert all(not d.certain and "framework import" in d.reasons[0] for d in result.decisions)
    delayed = PREAMBLE.replace(r"\input{SlideMage_template_slidemage}",
                               r"\AtBeginDocument{\input{SlideMage_template_slidemage}}")
    result = classify_views(specs(tmp_path / "delayed", "Plain", preamble=delayed))
    assert all(not d.certain for d in result.decisions)


def test_single_view_group_stability_and_include_dependency_change(tmp_path):
    requests = specs(tmp_path, r"\input{parts/body}")
    included = requests[0].target.context.root / "parts" / "body.tex"
    included.parent.mkdir()
    included.write_text("First")
    all_views = classify_views(requests)
    one_view = classify_views((requests[1],))
    assert all_views.group_for("during-course") == one_view.group_for("during-course")
    included.write_text("Changed")
    changed = classify_views(requests)
    assert changed.evidence != all_views.evidence
    assert changed.group_for("during-course") != all_views.group_for("during-course")


def test_mixed_projects_are_classified_independently_and_io_fails_closed(tmp_path, monkeypatch):
    first = specs(tmp_path / "one", "Plain")
    second = specs(tmp_path / "two", "Plain")
    mixed = classify_views((first[0], second[1]))
    assert all(d.certain for d in mixed.decisions)
    assert mixed.decisions[0].group != mixed.decisions[1].group
    original = Path.read_bytes
    def failing_read(path):
        if path.name == ".latexmkrc":
            raise OSError("raced with config edit")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", failing_read)
    uncertain = classify_views(first)
    assert all(not d.certain for d in uncertain.decisions)


def test_custom_bibliography_and_citation_inputs_fail_closed(tmp_path):
    custom = PREAMBLE.replace(r"\begin{document}",
                              r"\usepackage[style=myhouse]{biblatex}" + "\n" +
                              r"\addbibresource{references.bib}" + "\n" +
                              r"\begin{document}")
    configured = classify_views(specs(tmp_path, "Plain", preamble=custom))
    assert all(not d.certain and "package" in d.reasons[0] for d in configured.decisions)
    cited = classify_views(specs(tmp_path / "cited", r"\fullcite{example}"))
    assert all(not d.certain and "fullcite" in d.reasons[0] for d in cited.decisions)
