r"""Which decks use a slide, and moving them to the new version or keeping the old one."""
from pathlib import Path

import pytest

from slidemage import deck_scan, slide_usage


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
    for module in (deck_scan,):
        monkeypatch.setattr(module, "DECKS_DIR", decks)
        monkeypatch.setattr(module, "ARCHIVE_DIR", decks / "archive")
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


def test_usage_lists_decks_and_their_state(project):
    usages = {u.deck.name: u for u in slide_usage.find_usage("abc-EN-Demo")}
    assert set(usages) == {"follows", "pinned", "steps"}
    assert usages["follows"].following and not usages["follows"].pinned_versions
    assert usages["pinned"].pinned_versions == ["1-0-0"]
    assert usages["steps"].only_unpinnable
    assert slide_usage.needs_dialog(list(usages.values()), [])
    assert not slide_usage.needs_dialog(slide_usage.find_usage("xyz-EN-Other")[:1], [])


def test_usage_knows_where_each_call_stands_and_how_it_is_called(project):
    usages = {u.deck.name: u for u in slide_usage.find_usage("abc-EN-Demo")}
    assert usages["follows"].positions == [1, 2] and usages["follows"].total == 3
    assert [slide_usage.call_text(c) for c in usages["follows"].calls] == [
        "\\slide, follows the current version", "\\omitslide, follows the current version"]
    assert slide_usage.call_text(usages["pinned"].calls[0]) == "\\slideversion, frozen v1.0.0"
    assert slide_usage.call_text(usages["steps"].calls[0]) == "\\slidestep, steps 2"


def test_set_pin_pins_unpins_and_repins_only_the_calls_that_can(project):
    follows = slide_usage.find_usage("abc-EN-Demo")[0]
    new = slide_usage.set_pin(follows.deck.path, follows.deck.text, follows.calls, "1-1-0")
    assert "\\slideversion{abc-EN-Demo}{1-1-0}" in new and "\\omitslideversion{abc-EN-Demo}{1-1-0}" in new
    assert "\\slide{xyz-EN-Other}" in new
    again = next(u for u in slide_usage.find_usage("abc-EN-Demo") if u.deck.name == "follows")
    slide_usage.set_pin(again.deck.path, again.deck.text, again.calls, "1-2-0")      # a pinned call moves on
    assert (project / "follows.tex").read_text(encoding="utf-8").count("{1-2-0}") == 2
    again = next(u for u in slide_usage.find_usage("abc-EN-Demo") if u.deck.name == "follows")
    slide_usage.set_pin(again.deck.path, again.deck.text, again.calls, None)
    assert (project / "follows.tex").read_text(encoding="utf-8") == DECK
    steps = next(u for u in slide_usage.find_usage("abc-EN-Demo") if u.deck.name == "steps")
    assert slide_usage.set_pin(steps.deck.path, steps.deck.text, steps.calls, "1-0-0") == steps.deck.text


def test_move_to_current_unpins_and_keep_pins(project):
    choices = {"follows": "keep", "pinned": "current", "steps": "keep"}
    log = slide_usage.apply_choices("abc-EN-Demo", choices, "1-1-0")

    assert len(log) == 2
    follows = (project / "follows.tex").read_text(encoding="utf-8")
    assert "\\slideversion{abc-EN-Demo}{1-1-0}" in follows
    assert "\\omitslideversion{abc-EN-Demo}{1-1-0}" in follows
    assert "\\slide{xyz-EN-Other}" in follows                 # other slides untouched
    pinned = (project / "pinned.tex").read_text(encoding="utf-8")
    assert "\\slide{abc-EN-Demo}" in pinned and "\\omitslide{abc-EN-Demo}" in pinned
    assert "slideversion" not in pinned.replace("\\omitslideversion", "")
    assert "\\slidestep{abc-EN-Demo}" in (project / "steps.tex").read_text(encoding="utf-8")


def test_current_leaves_followers_and_keep_leaves_pins_alone(project):
    before = (project / "follows.tex").read_bytes()
    slide_usage.apply_choices("abc-EN-Demo", {"follows": "current", "pinned": "keep"}, "1-1-0")
    assert (project / "follows.tex").read_bytes() == before
    assert "{1-0-0}" in (project / "pinned.tex").read_text(encoding="utf-8")


def test_dialog_defaults_to_moving_every_deck_to_the_current_version(project):
    from PySide6.QtWidgets import QApplication
    from slidemage.ui.dialogs.slide_usage_dialog import SlideUsageDialog

    app = QApplication.instance() or QApplication([])
    usages = slide_usage.find_usage("abc-EN-Demo")
    translation = slide_usage.Translation("abc-DE-Demo", "DE", Path("x.tex"), ["follows"])
    dialog = SlideUsageDialog(None, "abc-EN-Demo", "1.1.0", "1.0.0", usages, [translation])

    assert dialog.choices() == {"follows": "current", "pinned": "current"}   # \slidestep: no choice
    assert not dialog.open_translation()
    combo = dialog._combos["follows"]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Move to current (v1.1.0)", "Keep v1.0.0"]
    assert app is not None


def test_ask_and_apply_deck_versions_are_the_two_halves_of_the_save_time_question(project, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from slidemage.ui.dialogs import slide_usage_dialog as dialogs

    QApplication.instance() or QApplication([])
    # no deck calls it, no translation: nothing to ask
    assert dialogs.ask_deck_versions(None, "zzz-EN-None", "text", (1, 1, 0), (1, 0, 0)) == dialogs.DeckVersions({}, None)
    # several decks: the dialog's answer; cancelling gives None
    answers = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    monkeypatch.setattr(dialogs.SlideUsageDialog, "exec", lambda self: next(answers))
    asked = dialogs.ask_deck_versions(None, "abc-EN-Demo", "text", (1, 1, 0), (1, 0, 0))
    assert asked.choices == {"follows": "current", "pinned": "current"} and asked.open_translation is None
    assert dialogs.ask_deck_versions(None, "abc-EN-Demo", "text", (1, 1, 0), (1, 0, 0)) is None

    class App:
        logged = []
        refreshed = 0

        def log(self, line):
            self.logged.append(line)

        def refresh_open_deck_editors(self):
            self.refreshed += 1

    app = App()
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {}, (1, 0, 0))
    assert app.logged == [] and app.refreshed == 0
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {"follows": "keep"}, (1, 0, 0))
    assert app.logged == ["    follows: 2 call(s) changed -- stays on v1.0.0"] and app.refreshed == 1
    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: told.append(args[2]))
    monkeypatch.setattr(dialogs.slide_usage, "apply_choices", lambda *a: (_ for _ in ()).throw(ValueError("nope")))
    dialogs.apply_deck_versions(app, "abc-EN-Demo", {"follows": "keep"}, (1, 0, 0))
    assert "nope" in told[0]
