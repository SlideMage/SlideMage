"""The snippets/ folder behind \\SMCodeFile, and the call and the citation search that use it."""
from __future__ import annotations

import pytest

from slidemage import bibliography, latex_edit, snippets


@pytest.fixture
def folder(tmp_path, monkeypatch):
    root = tmp_path / "snippets"
    root.mkdir()
    (root / "1ab-1.tex").write_text("x", encoding="utf-8")
    (root / "1ab-2.tex").write_text("x", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "demo.tex").write_text("x", encoding="utf-8")
    monkeypatch.setattr(snippets, "SNIPPETS_DIR", root)
    return root


def test_snippets_are_listed_as_project_relative_paths(folder, tmp_path, monkeypatch):
    assert snippets.list_snippets() == ["snippets/1ab-1.tex", "snippets/1ab-2.tex", "snippets/sub/demo.tex"]
    monkeypatch.setattr(snippets, "SNIPPETS_DIR", tmp_path / "none")
    assert snippets.list_snippets() == []


def test_the_next_snippet_of_a_slide_takes_the_lowest_free_number(folder):
    assert snippets.next_snippet("1ab") == "snippets/1ab-3.tex"
    (folder / "1ab-3.tex").write_text("", encoding="utf-8")
    assert snippets.next_snippet("1ab") == "snippets/1ab-4.tex"
    assert snippets.next_snippet("zzz") == "snippets/zzz-1.tex"


def test_a_snippet_must_lie_inside_the_folder_and_is_created_once(folder):
    with pytest.raises(ValueError):
        snippets.resolve("snippets/../Slidemaster.bib")
    with pytest.raises(ValueError):
        snippets.resolve("slides/x.tex")
    for folder_itself in ("snippets", "snippets/", "snippets/."):
        with pytest.raises(ValueError):
            snippets.resolve(folder_itself)
    (folder / "sub").mkdir(exist_ok=True)
    with pytest.raises(ValueError):
        snippets.resolve("snippets/sub")
    assert snippets.create("snippets/new/a.tex") and (folder / "new" / "a.tex").is_file()
    (folder / "new" / "a.tex").write_text("kept", encoding="utf-8")
    assert not snippets.create("snippets/new/a.tex")
    assert (folder / "new" / "a.tex").read_text(encoding="utf-8") == "kept"


def test_the_code_file_call_takes_optional_listings_keys():
    assert latex_edit.code_file_call(" snippets/1ab-1.tex ") == "\\SMCodeFile{snippets/1ab-1.tex}"
    assert latex_edit.code_file_call("snippets/a.tex", "firstline=3, lastline=9") == \
        "\\SMCodeFile[firstline=3, lastline=9]{snippets/a.tex}"
    for path, keys in (("", ""), ("snippets/a b.tex", ""), ("snippets/{a}.tex", ""), ("snippets/a.tex", "x}")):
        with pytest.raises(ValueError):
            latex_edit.code_file_call(path, keys)


def test_the_bibliography_search_wants_every_word_in_key_author_title_year_or_container():
    entries = {
        "markowitz1952": bibliography.BibEntry("markowitz1952", "article", {
            "author": "Markowitz, H.", "title": "Portfolio Selection", "year": "1952",
            "journaltitle": "Journal of Finance"}),
        "sharpe1964": bibliography.BibEntry("sharpe1964", "article", {
            "author": "Sharpe, W.", "title": "Capital Asset Prices", "year": "1964",
            "journaltitle": "Journal of Finance"}),
    }
    assert bibliography.search(entries, "") == ["markowitz1952", "sharpe1964"]
    assert bibliography.search(entries, "finance 1964") == ["sharpe1964"]
    assert bibliography.search(entries, "MARKOW portfolio") == ["markowitz1952"]
    assert bibliography.search(entries, "nobody") == []
