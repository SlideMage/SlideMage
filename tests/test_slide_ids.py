import pytest

from slidemage import alt_images, deck_headers, slide_ids, slide_rename, slide_snapshot


@pytest.fixture
def project(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    slides.mkdir()
    (tmp_path / "slide_ids.csv").write_bytes(b'"id"\r\n')
    monkeypatch.setattr(slide_ids, "SLIDES_DIR", slides)
    monkeypatch.setattr(slide_ids, "SLIDE_IDS_CSV", tmp_path / "slide_ids.csv")
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


def test_minted_ids_start_with_a_letter(project):
    for _ in range(300):
        new_id = slide_ids.mint_slide_id()
        assert new_id[0] in slide_ids.ID_FIRST_ALPHABET
        assert slide_ids.regular_id_reason(new_id) is None


def test_minted_reserved_ids(project):
    for _ in range(100):
        new_id = slide_ids.mint_slide_id(reserved="1")
        assert new_id[0] == "1" and new_id[1].isalpha()
        assert slide_ids.reserved_id_reason(new_id) is None
    with pytest.raises(ValueError):
        slide_ids.mint_slide_id(reserved="5")


def test_mint_collision_check_ignores_case(project, monkeypatch):
    (project / "slides" / "ZZH-EN-Demo-current.tex").write_text("x", encoding="utf-8")
    draws = iter(["z", "z", "h", "a", "b", "c"])
    monkeypatch.setattr(slide_ids.random, "choice", lambda _alphabet: next(draws))
    assert slide_ids.mint_slide_id() == "abc"


@pytest.fixture
def rename_project(project, monkeypatch):
    decks = project / "decks"
    decks.mkdir()
    (decks / "d.tex").write_text("\\slide{2du-EN-Old}\n", encoding="utf-8", newline="")
    (project / "slides" / "2du-EN-Old-current.tex").write_text("old", encoding="utf-8")
    previews = project / ".previews" / "slide_previews"
    previews.mkdir(parents=True)
    (previews / "2du-EN-UniGraz-1920-1080.png").write_bytes(b"png")
    monkeypatch.setattr(slide_rename, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(slide_rename, "PROJECT_ROOT", project)
    monkeypatch.setattr(slide_rename, "_REFERENCE_DIRS", (decks,))
    monkeypatch.setattr(slide_rename, "WORKDECK_PATH", decks / "#workdeck.tex")
    monkeypatch.setattr(slide_rename, "is_git_repo", lambda _root: False)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda: None)
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda: None)
    monkeypatch.setattr(alt_images, "update_store", lambda fn: None)
    monkeypatch.setattr(alt_images, "update_slide_notes", lambda fn: None)
    monkeypatch.setattr(slide_snapshot, "SNAPSHOT_DIR", previews)
    return project


def test_rename_to_letter_first_id(rename_project):
    mapping = slide_rename.rename_slide_id("2du", "k7m")
    assert mapping == {"2du-EN-Old": "k7m-EN-Old"}
    assert (rename_project / "slides" / "k7m-EN-Old-current.tex").is_file()
    assert (rename_project / "decks" / "d.tex").read_text(encoding="utf-8") == "\\slide{k7m-EN-Old}\n"
    assert (rename_project / ".previews" / "slide_previews" / "k7m-EN-UniGraz-1920-1080.png").is_file()
    assert '"k7m"' in (rename_project / "slide_ids.csv").read_text(encoding="utf-8")


def test_rename_refuses_digit_first_unless_reserved(rename_project):
    with pytest.raises(ValueError, match="digit"):
        slide_rename.rename_slide_id("2du", "3ab")
    assert slide_rename.rename_slide_id("2du", "1ab", reserved=True) == {"2du-EN-Old": "1ab-EN-Old"}


def test_rename_collision_check_ignores_case(rename_project):
    (rename_project / "slides" / "ZZH-EN-Demo-current.tex").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        slide_rename.rename_slide_id("2du", "zzh")
