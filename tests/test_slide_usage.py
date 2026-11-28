# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Which decks use a slide, and moving them to the new version or keeping the old one."""
from dataclasses import replace
from pathlib import Path

import pytest

from slidemage import deck_language, slide_language, slide_usage, slide_versioning
from slidemage.deck_scan import read_deck, scan_decks
from slidemage.fileio import write_texts


DECK = (
    "\\documentclass{beamer}\n\\begin{document}\n"
    "\\slide{abc-EN-Demo}\n\\omitslide{abc-EN-Demo}\n\\slide{xyz-EN-Other}\n"
    "\\end{document}\n"
)


def capture_patch(ctx):
    current = ctx.slides_dir / "abc-EN-Demo-current.tex"
    current.parent.mkdir(exist_ok=True)
    current.write_text("\\setSlideVersion{1-1-0+}\nedited\n")
    (current.parent / "abc-EN-Demo-v1-1-0.tex").write_text("\\setSlideVersion{1-1-0}\nold\n")
    return slide_versioning.capture(ctx, "patch", [current])


@pytest.fixture
def project(tmp_path):
    decks = tmp_path / "decks"
    (decks / "archive").mkdir(parents=True)
    slides = tmp_path / "slides"
    slides.mkdir()
    (decks / "follows.tex").write_text(DECK, encoding="utf-8", newline="")
    (decks / "pinned.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n\\slideversion{abc-EN-Demo}{1-0-0}\n\\omitslideversion{abc-EN-Demo}{1-0-0}\n"
        "\\end{document}\n", encoding="utf-8", newline="")
    (decks / "steps.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n\\slidestep{abc-EN-Demo}[instructor]{2}\n\\end{document}\n",
        encoding="utf-8", newline="")
    (decks / "unrelated.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n\\slide{xyz-EN-Other}\n\\end{document}\n", encoding="utf-8")
    return decks


def test_usage_lists_decks_and_their_state(ctx, project):
    usages = {u.deck.name: u for u in slide_usage.find_usage(ctx, "abc-EN-Demo")}
    assert set(usages) == {"follows", "pinned", "steps"}
    assert usages["follows"].following and not usages["follows"].pinned_versions
    assert usages["pinned"].pinned_versions == ["1-0-0"]
    assert usages["steps"].only_unpinnable
    assert usages["follows"].positions == [1, 2] and usages["follows"].total == 3
    assert slide_usage.needs_dialog(list(usages.values()), [])
    assert not slide_usage.needs_dialog(slide_usage.find_usage(ctx, "xyz-EN-Other")[:1], [])


@pytest.mark.parametrize("before, after, frozen_after, outcome", [
    (r"\slide{abc-EN-Demo}", None, "old", "follows the edited current slide"),
    (r"\slide{abc-EN-Demo}", r"\slideversion{abc-EN-Demo}{1-0-0}", "old", "keeps v1.0.0 (unchanged)"),
    (r"\slideversion{abc-EN-Demo}{1-0-0}", None, "edited", "keeps v1.0.0: content replaced"),
    (r"\slide{abc-EN-Demo}", r"\slide{xyz-EN-Copy}", "old", "switches to new slide xyz-EN-Copy"),
])
def test_revision_outcomes(before, after, frozen_after, outcome):
    from slidemage.deck_scan import deck_from_text

    deck = Path("decks/course.tex")
    current = Path("slides/abc-EN-Demo-current.tex")
    frozen = Path("slides/abc-EN-Demo-v1-0-0.tex")
    calls = deck_language.resolve(deck_from_text(deck, before)).calls
    edits = {current: ("edited", "updated"), frozen: ("old", frozen_after)}
    if after is not None:
        edits[deck] = (before, after)
    proposal = slide_versioning.Proposal(edits, {deck: before, current: "edited", frozen: "old"},
                                        tuple((deck, call) for call in calls), frozenset({frozen}))

    assert slide_usage.revision_outcomes(proposal, current) == [(deck, outcome)]


def test_deck_choices_pin_followers_unpin_pins_and_leave_matching_calls(ctx, project):
    before = (project / "follows.tex").read_bytes()
    assert not slide_usage.choice_edits(capture_patch(ctx).usages,
                                       {project / "follows.tex": "current", project / "pinned.tex": "keep"}, "1-1-0")
    assert (project / "follows.tex").read_bytes() == before
    assert "{1-0-0}" in (project / "pinned.tex").read_text(encoding="utf-8")

    follows_path = project / "follows.tex"
    follows_path.write_text(DECK.replace(r"\end{document}", r"\slideversion{abc-EN-Demo}{1-0-0}" + "\n" + r"\end{document}"))
    choices = {project / f"{name}.tex": choice for name, choice in
               [("follows", "keep"), ("pinned", "current"), ("steps", "keep")]}
    edits = slide_usage.choice_edits(capture_patch(ctx).usages, choices, "1-1-0")
    write_texts(edits)

    assert len(edits) == 2
    follows = (project / "follows.tex").read_text(encoding="utf-8")
    assert "\\slideversion{abc-EN-Demo}{1-1-0}" in follows
    assert "\\omitslideversion{abc-EN-Demo}{1-1-0}" in follows
    assert r"\slideversion{abc-EN-Demo}{1-0-0}" in follows
    assert "\\slide{xyz-EN-Other}" in follows                 # other slides untouched
    pinned = (project / "pinned.tex").read_text(encoding="utf-8")
    assert "\\slide{abc-EN-Demo}" in pinned and "\\omitslide{abc-EN-Demo}" in pinned
    assert "slideversion" not in pinned.replace("\\omitslideversion", "")
    assert project / "steps.tex" not in edits


def test_dialog_defaults_to_leaving_calls_as_written(ctx, project, qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from slidemage.ui.dialogs import slide_usage_dialog as dialogs
    follows = project / "follows.tex"
    follows.write_text(DECK.replace(r"\omitslide{abc-EN-Demo}", r"\omitslideversion{abc-EN-Demo}{1-0-0}"))
    current = ctx.slides_dir / "abc-EN-Demo-current.tex"
    cap = capture_patch(ctx)
    translation = slide_usage.Translation("abc-DE-Demo", "DE", Path("x.tex"), ["follows"])
    dialog = dialogs.SlideUsageDialog(None, ctx.root, replace(cap, translations=[translation]), current, "patch")

    assert dialog.choices() == {}
    combo = dialog._combos[follows]
    assert combo.findData(dialogs.KEEP) != -1
    missing = dialogs.SlideUsageDialog(None, ctx.root, replace(cap, frozen=frozenset()), current, "patch")
    assert all(combo.findData("keep") == -1 for combo in missing._combos.values())
    assert not dialog.open_translation()

    # no deck calls it, no translation: nothing to ask
    assert dialogs.ask_deck_versions(None, ctx.root, replace(cap, usages=[]), current, "patch") == dialogs.DeckVersions({}, None)
    # several decks: the dialog's answer; cancelling gives None
    answers = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    monkeypatch.setattr(dialogs.SlideUsageDialog, "exec", lambda self: next(answers))
    asked = dialogs.ask_deck_versions(None, ctx.root, cap, current, "patch")
    assert asked.choices == {} and asked.open_translation is None
    assert dialogs.ask_deck_versions(None, ctx.root, cap, current, "patch") is None


def test_the_decks_already_scanned_are_not_scanned_again_and_one_translation_scan_serves_them_all(ctx, project, monkeypatch):
    (project / "archive" / "old.tex").write_text(DECK, encoding="utf-8", newline="")
    decks = scan_decks(ctx)
    expected = [(u.deck.name, u.deck.archived, u.positions, u.total) for u in slide_usage.find_usage(ctx, "abc-EN-Demo", language="EN")]
    scans, folder = [], []

    class Counting(slide_language.TranslationLinks):
        def __init__(self, *args, **kwargs):
            scans.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(slide_language, "TranslationLinks", Counting)
    monkeypatch.setattr(slide_usage, "scan_decks", lambda _ctx: folder.append(1) or [])
    usages = slide_usage.find_usage(ctx, "abc-EN-Demo", decks, language="EN")
    assert [(u.deck.name, u.deck.archived, u.positions, u.total) for u in usages] == expected
    assert ("old", True, [1, 2], 3) in expected                        # archived decks count, too
    assert folder == [] and scans == [1]                               # five decks, one scan of the slides folder


@pytest.mark.parametrize("folder", ["blocks", "decks", "."])
def test_block_version_asks_once_for_two_decks_and_pins_the_block(ctx, qapp, monkeypatch, folder):
    from PySide6.QtWidgets import QComboBox, QDialog, QLabel
    from slidemage.ui.dialogs import slide_usage_dialog as dialogs

    ctx.blocks_dir.mkdir()
    ctx.decks_dir.mkdir()
    block = ctx.root / folder / "Literaturrecherche.tex"
    block.write_text("\\slide{abc-EN-Demo}\n", encoding="utf-8")
    include = (r"\slideblock{Literaturrecherche}" if folder == "blocks" else
               r"\input{Literaturrecherche}")
    before = "\\documentclass{beamer}\n\\begin{document}\n" + include + "\n\\end{document}\n"
    names = ("Literaturrecherche" if folder == "blocks" else "wrapper", "course")
    wrapper, course = (ctx.decks_dir / f"{name}.tex" for name in names)
    wrapper.write_bytes(before.replace(include, "\\slide{abc-EN-Demo}\n" + include).encode())
    course.write_bytes(before.replace(include, r"\input{nested}").encode())
    (ctx.root / "nested.tex").write_bytes((include + "\n" + include).encode())
    cap = capture_patch(ctx)
    current = ctx.slides_dir / "abc-EN-Demo-current.tex"
    usages = cap.usages
    by_path = {u.deck.path: u for u in usages}
    assert set(by_path) == {wrapper, block}
    assert len(by_path[block].calls) == 1 and {d.path for d in by_path[block].decks} == {wrapper, course}
    assert slide_usage.needs_dialog(usages, [])
    deck = read_deck(wrapper)
    with pytest.raises(ValueError, match="source file"):
        slide_usage.set_pin(deck.path, deck.text, deck_language.active_calls(deck), "1-0-0")
    asked = []

    def keep(dialog):
        asked.append(dialog)
        def text():
            return "\n".join(label.text() for label in dialog.findChildren(QLabel))

        assert "Literaturrecherche (used by 2 decks)" in text()
        assert ("Unlink" in text()) == (folder == "blocks")
        assert text().count("follows the edited current slide") == 4
        assert len(dialog.findChildren(QComboBox)) == 2 and dialog.choices() == {}
        combo = dialog._combos[block]
        combo.setCurrentIndex(combo.findData(dialogs.KEEP))
        assert text().count("keeps v1.1.0 (unchanged)") == 3
        assert text().count("follows the edited current slide") == 1
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.SlideUsageDialog, "exec", keep)
    answer = dialogs.ask_deck_versions(None, ctx.root, cap, current, "patch")
    assert len(asked) == 1 and answer.choices == {block: dialogs.KEEP}
    edits = slide_usage.choice_edits(usages, answer.choices, "1-1-0")
    assert list(edits) == [block]
    write_texts(edits)
    assert block.read_text(encoding="utf-8") == "\\slideversion{abc-EN-Demo}{1-1-0}\n"
    assert wrapper.read_text() == by_path[wrapper].deck.text and course.read_text() == before.replace(include, r"\input{nested}")
