# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Which decks use a slide, and moving them to the new version or keeping the old one."""
from pathlib import Path

import pytest

from slidemage import slide_language, slide_usage
from slidemage.deck_scan import scan_decks


DECK = (
    "\\documentclass{beamer}\n\\begin{document}\n"
    "\\slide{abc-EN-Demo}\n\\omitslide{abc-EN-Demo}\n\\slide{xyz-EN-Other}\n"
    "\\end{document}\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
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


def test_set_pin_pins_unpins_and_repins_only_the_calls_that_can(ctx, project):
    follows = slide_usage.find_usage(ctx, "abc-EN-Demo")[0]
    new = slide_usage.set_pin(follows.deck.path, follows.deck.text, follows.calls, "1-1-0")
    assert "\\slideversion{abc-EN-Demo}{1-1-0}" in new and "\\omitslideversion{abc-EN-Demo}{1-1-0}" in new
    assert "\\slide{xyz-EN-Other}" in new
    again = next(u for u in slide_usage.find_usage(ctx, "abc-EN-Demo") if u.deck.name == "follows")
    slide_usage.set_pin(again.deck.path, again.deck.text, again.calls, "1-2-0")      # a pinned call moves on
    assert (project / "follows.tex").read_text(encoding="utf-8").count("{1-2-0}") == 2
    again = next(u for u in slide_usage.find_usage(ctx, "abc-EN-Demo") if u.deck.name == "follows")
    slide_usage.set_pin(again.deck.path, again.deck.text, again.calls, None)
    assert (project / "follows.tex").read_text(encoding="utf-8") == DECK
    steps = next(u for u in slide_usage.find_usage(ctx, "abc-EN-Demo") if u.deck.name == "steps")
    assert slide_usage.set_pin(steps.deck.path, steps.deck.text, steps.calls, "1-0-0") == steps.deck.text


def test_move_to_current_unpins_and_keep_pins(ctx, project):
    choices = {project / f"{name}.tex": choice for name, choice in
               [("follows", "keep"), ("pinned", "current"), ("steps", "keep")]}
    log = slide_usage.apply_choices(ctx, "abc-EN-Demo", choices, "1-1-0")

    assert len(log) == 2
    follows = (project / "follows.tex").read_text(encoding="utf-8")
    assert "\\slideversion{abc-EN-Demo}{1-1-0}" in follows
    assert "\\omitslideversion{abc-EN-Demo}{1-1-0}" in follows
    assert "\\slide{xyz-EN-Other}" in follows                 # other slides untouched
    pinned = (project / "pinned.tex").read_text(encoding="utf-8")
    assert "\\slide{abc-EN-Demo}" in pinned and "\\omitslide{abc-EN-Demo}" in pinned
    assert "slideversion" not in pinned.replace("\\omitslideversion", "")
    assert "\\slidestep{abc-EN-Demo}" in (project / "steps.tex").read_text(encoding="utf-8")


def test_current_leaves_followers_and_keep_leaves_pins_alone(ctx, project):
    before = (project / "follows.tex").read_bytes()
    slide_usage.apply_choices(ctx, "abc-EN-Demo", {project / "follows.tex": "current", project / "pinned.tex": "keep"}, "1-1-0")
    assert (project / "follows.tex").read_bytes() == before
    assert "{1-0-0}" in (project / "pinned.tex").read_text(encoding="utf-8")


def test_dialog_defaults_to_moving_every_deck_to_the_current_version(ctx, project):
    from PySide6.QtWidgets import QApplication
    from slidemage.ui.dialogs.slide_usage_dialog import SlideUsageDialog

    QApplication.instance() or QApplication([])
    usages = slide_usage.find_usage(ctx, "abc-EN-Demo")
    translation = slide_usage.Translation("abc-DE-Demo", "DE", Path("x.tex"), ["follows"])
    dialog = SlideUsageDialog(None, "abc-EN-Demo", "1.1.0", "1.0.0", usages, [translation])

    assert dialog.choices() == {project / "follows.tex": "current", project / "pinned.tex": "current"}   # \slidestep: no choice
    assert not dialog.open_translation()


def test_ask_and_apply_deck_versions_are_the_two_halves_of_the_save_time_question(ctx, project, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from slidemage.ui.dialogs import slide_usage_dialog as dialogs

    QApplication.instance() or QApplication([])
    # no deck calls it, no translation: nothing to ask
    assert dialogs.ask_deck_versions(None, ctx, "zzz-EN-None", "text", (1, 1, 0), (1, 0, 0)) == dialogs.DeckVersions({}, None)
    # several decks: the dialog's answer; cancelling gives None
    answers = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    monkeypatch.setattr(dialogs.SlideUsageDialog, "exec", lambda self: next(answers))
    asked = dialogs.ask_deck_versions(None, ctx, "abc-EN-Demo", "text", (1, 1, 0), (1, 0, 0))
    assert asked.choices == {project / "follows.tex": "current", project / "pinned.tex": "current"} and asked.open_translation is None
    assert dialogs.ask_deck_versions(None, ctx, "abc-EN-Demo", "text", (1, 1, 0), (1, 0, 0)) is None

    class App:
        project = ctx
        logged = []
        refreshed = 0

        def log(self, line):
            self.logged.append(line)

        def refresh_open_deck_editors(self):
            self.refreshed += 1

    app = App()
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {}, (1, 0, 0))
    assert app.logged == [] and app.refreshed == 0
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {project / "follows.tex": "keep"}, (1, 0, 0))
    assert app.refreshed == 1
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(dialogs.slide_usage, "apply_choices", lambda _ctx, *a: (_ for _ in ()).throw(ValueError("nope")))
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {project / "follows.tex": "keep"}, (1, 0, 0))
    assert "nope" in told[0]


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
    from slidemage import deck_language
    from slidemage.ui.dialogs import slide_usage_dialog as dialogs

    ctx.blocks_dir.mkdir()
    ctx.decks_dir.mkdir()
    block = ctx.root / folder / "Literaturrecherche.tex"
    block.write_text("\\slide{abc-EN-Demo}\n", encoding="utf-8")
    include = (r"\slideblock{Literaturrecherche}" if folder == "blocks" else
               r"\input{Literaturrecherche}")
    before = "\\documentclass{beamer}\n\\begin{document}\n" + include + "\n\\end{document}\n"
    # A deck and a block may have the same stem; only the block holds the call.
    names = ("Literaturrecherche" if folder == "blocks" else "wrapper", "course")
    for name in names:
        (ctx.decks_dir / f"{name}.tex").write_text(before, encoding="utf-8")
    usages = slide_usage.find_usage(ctx, "abc-EN-Demo")
    assert len(usages) == 1 and usages[0].deck.path == block
    assert {d.name for d in usages[0].decks} == set(names)
    assert slide_usage.needs_dialog(usages, [])
    visible = slide_usage.find_usage(ctx, "abc-EN-Demo", language="EN")
    assert {u.deck.name: u.calls[0].block for u in visible} == dict.fromkeys(
        names, "Literaturrecherche" if folder == "blocks" else None)
    deck = usages[0].decks[0]
    with pytest.raises(ValueError, match="source file"):
        slide_usage.set_pin(deck.path, deck.text, deck_language.active_calls(deck), "1-0-0")
    asked = []

    def keep(dialog):
        asked.append(dialog)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert "Literaturrecherche (used by 2 decks)" in labels
        assert any("Unlink" in label for label in labels)
        combos = dialog.findChildren(QComboBox)
        assert len(combos) == 1 and dialog.choices() == {block: dialogs.CURRENT}
        combo = combos[0]
        combo.setCurrentIndex(combo.findData(dialogs.KEEP))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.SlideUsageDialog, "exec", keep)
    answer = dialogs.ask_deck_versions(None, ctx, "abc-EN-Demo", "", (1, 1, 0), (1, 0, 0))
    assert len(asked) == 1 and answer.choices == {block: dialogs.KEEP}
    assert len(slide_usage.apply_choices(ctx, "abc-EN-Demo", answer.choices, "1-0-0")) == 1
    assert block.read_text(encoding="utf-8") == "\\slideversion{abc-EN-Demo}{1-0-0}\n"
    assert all(d.path.read_text(encoding="utf-8") == before for d in usages[0].decks)
