r"""\SMFinalStateForStudents that no deck needs any longer is taken out of the slide, silently: no version, no "+",
no frozen file, and one undo."""
from __future__ import annotations

import hashlib

import pytest

from slidemage import reveal_steps, slide_versioning
from test_workspace_window import window  # noqa: F401 -- fixture
# ruff: noqa: F811 -- the window fixture is used by name

ID = "abc-EN-Demo"
FLAG_SLIDE = ("%% Included in decks: a, b\n\\setSlideVersion{1-0-0}\n\\SMFinalStateForStudents\n"
              "\\begin{standardframe}{T}\nA\\pause B\n\\end{standardframe}\n")
FROZEN = "%% Included in decks: a, b\n\\setSlideVersion{1-0-0}\n\\SMFinalStateForStudents\n\\begin{standardframe}{T}\nA\\pause B\n\\end{standardframe}\n"


def deck(body: str) -> str:
    return "\\documentclass{beamer}\n\\begin{document}\n" + body + "\\end{document}\n"


@pytest.fixture
def project(ctx):
    (ctx.decks_dir).mkdir(parents=True, exist_ok=True)
    ctx.archive_dir.mkdir(parents=True, exist_ok=True)
    ctx.slides_dir.mkdir(parents=True, exist_ok=True)
    (ctx.slides_dir / f"{ID}-current.tex").write_text(FLAG_SLIDE, encoding="utf-8", newline="")
    (ctx.slides_dir / f"{ID}-v1-0-0.tex").write_text(FROZEN, encoding="utf-8", newline="")
    return ctx


def write_deck(ctx, name, body, archived=False):
    folder = ctx.archive_dir if archived else ctx.decks_dir
    (folder / f"{name}.tex").write_text(deck(body), encoding="utf-8", newline="")


STEPS_BOTH = f"\\slidestep{{{ID}}}[instructor]{{1-}}\n\\slidestep{{{ID}}}[during-course,after-course]{{2}}\n"


def test_the_flag_is_dead_when_every_call_in_every_deck_overrides_or_skips_it(project):
    write_deck(project, "one", STEPS_BOTH)
    write_deck(project, "two", f"\\conditionalslide[instructor]{{{ID}}}\n\\slideversion{{{ID}}}{{1-0-0}}\n")
    assert reveal_steps.final_flag_is_dead(project, ID)


@pytest.mark.parametrize("extra", [
    f"\\slide{{{ID}}}\n",                                       # a plain call: the flag decides for students
    f"\\conditionalslide[instructor,during-course]{{{ID}}}\n",  # in a student version without steps
    f"\\slidefinal{{{ID}}}\n",
    f"\\slidestep{{{ID}}}[instructor,during-course]{{1}}\n",    # after-course is left to the flag... not typeset: fine
])
def test_one_call_that_still_needs_the_flag_keeps_it(project, extra):
    write_deck(project, "one", STEPS_BOTH)
    write_deck(project, "two", extra)
    dead = reveal_steps.final_flag_is_dead(project, ID)
    # the last case has no call that typesets a student version without steps: it is not needed there
    assert dead is (extra.startswith("\\slidestep"))


def test_an_archived_deck_counts_too(project):
    write_deck(project, "one", STEPS_BOTH)
    write_deck(project, "old", f"\\slide{{{ID}}}\n", archived=True)
    assert not reveal_steps.final_flag_is_dead(project, ID)


def test_a_slide_no_deck_calls_keeps_its_flag_and_so_does_an_unreadable_situation(project, monkeypatch):
    assert not reveal_steps.final_flag_is_dead(project, ID)
    write_deck(project, "one", STEPS_BOTH)
    monkeypatch.setattr("slidemage.slide_usage.find_usage", lambda *a, **k: 1 / 0)
    assert not reveal_steps.final_flag_is_dead(project, ID)


def test_removing_the_flag_changes_nothing_else_and_makes_no_version_marker_or_frozen_file(project):
    write_deck(project, "one", STEPS_BOTH)
    current = project.slides_dir / f"{ID}-current.tex"
    frozen = project.slides_dir / f"{ID}-v1-0-0.tex"
    frozen_bytes = frozen.read_bytes()
    before_files = sorted(p.name for p in project.slides_dir.iterdir() if p.name != ".backups")
    changed = reveal_steps.drop_dead_final_flag(project, ID)
    assert changed is not None and changed[0] == current
    assert current.read_text(encoding="utf-8") == FLAG_SLIDE.replace("\\SMFinalStateForStudents\n", "")
    assert "+" not in current.read_text(encoding="utf-8").split("setSlideVersion{")[1].split("}")[0]
    assert frozen.read_bytes() == frozen_bytes                          # a frozen version is never touched
    assert sorted(p.name for p in project.slides_dir.iterdir() if p.name != ".backups") == before_files  # no frozen file
    assert reveal_steps.drop_dead_final_flag(project, ID) is None       # nothing left to remove


def test_a_slide_that_already_has_the_plus_keeps_it_and_one_without_does_not_get_it(project):
    write_deck(project, "one", STEPS_BOTH)
    current = project.slides_dir / f"{ID}-current.tex"
    current.write_text(FLAG_SLIDE.replace("1-0-0}", "1-0-0+}"), encoding="utf-8", newline="")
    reveal_steps.drop_dead_final_flag(project, ID)
    assert "setSlideVersion{1-0-0+}" in current.read_text(encoding="utf-8")


def test_the_flag_stays_when_a_deck_needs_it(project):
    write_deck(project, "one", f"\\slide{{{ID}}}\n")
    current = project.slides_dir / f"{ID}-current.tex"
    assert reveal_steps.drop_dead_final_flag(project, ID) is None and current.read_text(encoding="utf-8") == FLAG_SLIDE


def test_crlf_files_keep_their_line_endings(project):
    write_deck(project, "one", STEPS_BOTH)
    current = project.slides_dir / f"{ID}-current.tex"
    current.write_bytes(FLAG_SLIDE.replace("\n", "\r\n").encode())
    assert reveal_steps.drop_dead_final_flag(project, ID) is not None
    raw = current.read_bytes()
    assert b"SMFinalState" not in raw and raw.count(b"\r\n") == raw.count(b"\n")


def test_undo_puts_the_slide_back_byte_for_byte_unless_it_changed_since(project):
    write_deck(project, "one", STEPS_BOTH)
    current = project.slides_dir / f"{ID}-current.tex"
    original = current.read_bytes()
    path, before, after = reveal_steps.drop_dead_final_flag(project, ID)
    assert reveal_steps.restore_final_flag(project, path, before, after)
    assert current.read_bytes() == original
    reveal_steps.drop_dead_final_flag(project, ID)
    current.write_text(current.read_text(encoding="utf-8") + "% edited meanwhile\n", encoding="utf-8", newline="")
    assert not reveal_steps.restore_final_flag(project, path, before, after)
    assert "edited meanwhile" in current.read_text(encoding="utf-8") and "SMFinalState" not in current.read_text(encoding="utf-8")


def test_only_a_flag_on_a_line_of_its_own_is_removed():
    assert reveal_steps.remove_final_flag("a\n  \\SMFinalStateForStudents % why\nb\n") == "a\nb\n"
    assert reveal_steps.remove_final_flag("a % \\SMFinalStateForStudents\nb\n") is None
    assert reveal_steps.remove_final_flag("\\SMFinalStateForStudents\\pause\n") is None
    assert reveal_steps.remove_final_flag("nothing\n") is None


def test_taking_the_flag_out_does_not_make_the_slide_look_changed_but_putting_it_in_does(project):
    write_deck(project, "one", STEPS_BOTH)
    current = project.slides_dir / f"{ID}-current.tex"
    frozen_text = (project.slides_dir / f"{ID}-v1-0-0.tex").read_text(encoding="utf-8")
    reveal_steps.drop_dead_final_flag(project, ID)
    text = current.read_text(encoding="utf-8")
    assert not slide_versioning._changed_since(frozen_text, text)
    assert slide_versioning._changed_since(frozen_text, text + "% more\n")
    assert slide_versioning._changed_since(text, frozen_text)               # adding the flag is a real change
    # plan_update agrees: nothing to make a version of
    with pytest.raises(ValueError, match="has not changed"):
        slide_versioning.plan_update(current, ID, text, "patch")
    assert slide_versioning.mark_external_edit(project, current) is False
    assert hashlib.sha256(current.read_bytes()).hexdigest()


# -- the slide list: the deck edit, the cleanup and one undo ------------------------------------------


def test_the_slide_lists_edit_runs_the_cleanup_and_one_undo_takes_back_deck_and_slide(window, monkeypatch, tmp_path):
    from test_workspace_window import WORK
    from slidemage import deck_editor

    sl = window.slide_list
    window.state.set_deck(WORK)
    seen = []
    monkeypatch.setattr(window, "after_deck_edit",
                        lambda path, summary, previous_text=None: (seen.append(summary),
                                                                   sl.deck_edited(path, summary, previous_text)))
    slide = tmp_path / "x-current.tex"
    restored = []
    monkeypatch.setattr(deck_editor, "restore_deck_text", lambda path, current, previous: restored.append(str(previous)))
    monkeypatch.setattr(reveal_steps, "restore_final_flag", lambda ctx, *args: restored.append(args) or True)
    assert sl.edit("Failed", "Set steps", lambda path, text: text + "x", cleanup=lambda: (slide, "before", "after"))
    assert "took \\SMFinalStateForStudents out of x-current.tex" in seen[0]
    sl.undo()
    assert restored == [WORK.text, (slide, "before", "after")]
    # an edit without a cleanup leaves a plain entry
    assert sl.edit("Failed", "Plain", lambda path, text: text + "y")
    assert getattr(sl._undo[WORK.path][-1], "slide", None) is None


def test_a_slide_with_edits_open_in_the_source_view_keeps_its_flag_until_they_are_written(window, monkeypatch):
    sl = window.slide_list
    asked = []
    monkeypatch.setattr(reveal_steps, "drop_dead_final_flag", lambda ctx, id_slug: asked.append(id_slug))
    monkeypatch.setattr(window.centre, "unsaved", lambda path: True)
    assert sl._flag_cleanup(["abc-EN-Demo"])() is None and asked == []
    monkeypatch.setattr(window.centre, "unsaved", lambda path: False)
    sl._flag_cleanup(["abc-EN-Demo", "xyz-EN-Other"])()
    assert asked == ["abc-EN-Demo", "xyz-EN-Other"]
