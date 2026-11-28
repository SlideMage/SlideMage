# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from conftest import EXAMPLE_PROJECT

from slidemage import alt_images, cli, deck_editor, deck_headers, processes, project as project_module
from slidemage import slide_ids, slide_language, slide_rename


@pytest.fixture
def project(tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
    (tmp_path / "slide_ids.csv").write_bytes(b'"id"\r\n')
    return tmp_path


def test_regular_ids_start_with_a_letter():
    assert slide_ids.regular_id_reason("a2b") is None
    assert "digit" in slide_ids.regular_id_reason("2ab")
    assert slide_ids.regular_id_reason("838")  # still illegal for its own reason


def test_reserved_id_form():
    assert slide_ids.reserved_id_reason("1ab") is None
    assert slide_ids.reserved_id_reason("2k7") is None
    assert slide_ids.reserved_id_reason("3ab")  # only 1 (manual) and 2 (demo)
    assert slide_ids.reserved_id_reason("12b")  # second place must be a letter
    assert slide_ids.reserved_id_reason("abc")
    assert slide_ids.reserved_id_reason("1e5")  # scientific notation
    assert slide_ids.reserved_id_reason("1ex")  # never "e" second


def test_minted_reserved_ids(ctx, project):
    for _ in range(12):
        new_id = slide_ids.mint_slide_id(ctx, reserved="1")
        assert new_id[0] == "1" and new_id[1].isalpha()
        assert slide_ids.reserved_id_reason(new_id) is None
    with pytest.raises(ValueError):
        slide_ids.mint_slide_id(ctx, reserved="5")


def test_mint_uses_a_letter_and_rejects_case_insensitive_collisions(ctx, project, monkeypatch):
    (project / "slides" / "ZZH-EN-Demo-current.tex").write_text("x", encoding="utf-8")
    draws = iter(["z", "z", "h", "a", "b", "c"])
    alphabets = []

    def choose(alphabet):
        alphabets.append(alphabet)
        return next(draws)

    monkeypatch.setattr(slide_ids.random, "choice", choose)
    new_id = slide_ids.mint_slide_id(ctx)
    assert new_id == "abc" and all(alphabet.isalpha() for alphabet in alphabets[::3])


@pytest.fixture
def rename_project(project, monkeypatch):
    decks = project / "decks"
    decks.mkdir()
    (decks / "d.tex").write_text("\\SMReview{\\slide {2du-EN-Old}}\n", encoding="utf-8", newline="")
    (project / "slides" / "2du-EN-Old-current.tex").write_text("old", encoding="utf-8")
    monkeypatch.setattr(processes, "is_git_repo", lambda _root: False)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: None)
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    monkeypatch.setattr(alt_images, "update_store", lambda _ctx, fn: None)
    monkeypatch.setattr(alt_images, "update_slide_notes", lambda _ctx, fn: None)
    return project


def test_rename_refuses_digit_first_unless_reserved(ctx, rename_project):
    with pytest.raises(ValueError, match="digit"):
        slide_rename.rename_slide_id(ctx, "2du", "3ab")
    assert slide_rename.rename_slide_id(ctx, "2du", "1ab", reserved=True) == {"2du-EN-Old": "1ab-EN-Old"}


@pytest.mark.parametrize("new_id,reserved", [("k7m", False), ("1ab", True)])
def test_cli_renames_slide_id_without_opening_a_window(rename_project, new_id, reserved, monkeypatch, capsys):
    (rename_project / project_module.MARKER).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli.diagnostics, "setup", lambda *_a, **_k: None)
    args = ["--project", str(rename_project), "rename-slide-id", "2du", new_id]
    cli.main(args + (["--reserved"] if reserved else []))
    assert capsys.readouterr().out == f"2du-EN-Old -> {new_id}-EN-Old\n"
    assert f'"{new_id}"' in (rename_project / "slide_ids.csv").read_text(encoding="utf-8")
    assert (rename_project / "slides" / f"{new_id}-EN-Old-current.tex").is_file()
    assert (rename_project / "decks" / "d.tex").read_text(encoding="utf-8") == f"\\SMReview{{\\slide {{{new_id}-EN-Old}}}}\n"


def test_cli_rejects_an_invalid_rename_without_changing_the_slide(rename_project, monkeypatch, capsys):
    (rename_project / project_module.MARKER).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli.diagnostics, "setup", lambda *_a, **_k: None)
    with pytest.raises(SystemExit) as error:
        cli.main(["rename-slide-id", "2du", "3ab", "--project", str(rename_project)])
    assert error.value.code == 2 and "digit" in capsys.readouterr().err
    assert (rename_project / "slides" / "2du-EN-Old-current.tex").is_file()


def test_rename_collision_check_ignores_case(ctx, rename_project):
    (rename_project / "slides" / "ZZH-EN-Demo-current.tex").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        slide_rename.rename_slide_id(ctx, "2du", "zzh")


def test_raw_reads_work_below_python_313():
    slide_language.translated_languages(EXAMPLE_PROJECT, "1vn-EN-Languages")
    assert "slidemage-manual" in slide_rename.deck_names_referencing(EXAMPLE_PROJECT, "1mu-EN-Slidestep-Demo")


# Every form of a call the deck parser reads: SlideMage's own review wrapper, spaces before a brace, a trailing
# comment, a call sharing its line. A delete or rename that missed one left a deck loading a file that is gone.
FORMS = (
    "\\SMReview{\\slide{gone-EN-B}}\r\n"
    "\\SMReview[check the chart]{\\slide{gone-EN-B}}\n"
    "\\slide {gone-EN-B}\n"
    "\\conditionalslide [instructor] {gone-EN-B}\n"
    "  \\slide{gone-EN-B} % note\n"
    "\\slidestep {gone-EN-B} [instructor] {1}\n"
)


def test_removal_takes_every_form_the_parser_reads():
    kept = "\\slide{keep-EN-A}\r\n\\slide{gone-EN-B-longer}\r\n"
    deck = kept + FORMS + "\\slideversion{gone-EN-B}{1-0-0}\r\n\\only<2>{\\slide{gone-EN-B}} kept\n% \\slide{gone-EN-B}\n"
    new, n = deck_editor.remove_call_references(deck, "gone-EN-B")
    assert n == 8
    # Commented-out calls load nothing and stay; a call sharing its line goes, the rest of the line stays.
    assert new == kept + "\\only<2>{} kept\n% \\slide{gone-EN-B}\n"
    assert all(call.id_slug != "gone-EN-B" or deck_editor.is_commented_out(new, call)
               for call in deck_editor.calls_in_text(new))


def test_rewrite_takes_every_form_the_parser_reads():
    deck = FORMS + "\\slideversion {gone-EN-B} {1-0-0}\n\\slide{gone-EN-B-longer}\n% \\slide{gone-EN-B}\n"
    new, n = deck_editor.rewrite_call_references(deck, {"gone-EN-B": "new-EN-C"})
    assert n == 8                                   # the commented-out call too: uncommenting it must still work
    assert "gone-EN-B}" not in new and "\\slide{gone-EN-B-longer}" in new
    assert new.count("new-EN-C") == 8
    assert "\\SMReview[check the chart]{\\slide{new-EN-C}}" in new
    assert "\\slideversion {new-EN-C} {1-0-0}" in new


def test_delete_removes_a_review_wrapped_call(ctx, project, monkeypatch):
    decks = project / "decks"
    decks.mkdir()
    deck = decks / "d.tex"
    deck.write_text("\\slide{keep-EN-A}\r\n\\SMReview[check]{\\slide{gne-EN-B}}\r\n\\slide {gne-EN-B}\r\n",
                    encoding="utf-8", newline="")
    (project / "slides" / "gne-EN-B-current.tex").write_text("x", encoding="utf-8")
    monkeypatch.setattr(processes, "is_git_repo", lambda _root: False)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: None)
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    assert slide_rename.deck_names_referencing(ctx, "gne-EN-B") == ["d"]
    assert slide_rename.count_references(ctx, "gne-EN-B") == 2
    result = slide_rename.delete_slide_id(ctx, "gne-EN-B")
    assert result["deck_references_removed"] == 2
    assert deck.read_bytes() == b"\\slide{keep-EN-A}\r\n"
