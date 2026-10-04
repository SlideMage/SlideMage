"""The progress bar's pass count comes from the deck's last compile (v5.15.0)."""
from types import SimpleNamespace

from slidemage import compile_passes, compile_progress


def _job(name="deck", version="instructor", chapter=None, presenter=False, biblatex=True):
    deck = SimpleNamespace(name=name, uses_biblatex=biblatex, text="", chapters=[],
                           preamble_end=None)
    return SimpleNamespace(deck=deck, version=version, chapter=chapter, presenter=presenter)


def test_remembered_per_deck_and_job_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(compile_passes, "STORE_PATH", tmp_path / "compile_passes.json")
    instructor = _job()
    chapter = _job(version="after-course", chapter=object())
    presenter = _job(presenter=True)

    assert compile_passes.expected(instructor) is None
    compile_passes.remember(instructor, 6)
    compile_passes.remember(chapter, 5)
    compile_passes.remember(presenter, 7)
    assert compile_passes.expected(instructor) == 6
    assert compile_passes.expected(chapter) == 5
    assert compile_passes.expected(presenter) == 7
    assert compile_passes.expected(_job(version="during-course")) is None
    assert compile_passes.expected(_job(name="other")) is None
    assert compile_passes.job_kind(chapter) == "after-course-chapter"


def test_progress_uses_the_remembered_count(tmp_path, monkeypatch):
    monkeypatch.setattr(compile_passes, "STORE_PATH", tmp_path / "compile_passes.json")
    job = _job()
    assert compile_progress.spec_for_job(job).passes == compile_progress.PASSES_WITH_BIBLIOGRAPHY
    compile_passes.remember(job, 6)
    assert compile_progress.spec_for_job(job).passes == 6


def test_run_lines_are_latexmk_passes():
    assert compile_passes.RUN_RE.match("Run number 6 of rule 'lualatex'").group(1) == "6"
    assert compile_passes.RUN_RE.match("Run number 1 of rule 'biber x'") is None


def test_unreadable_store_is_no_prediction(tmp_path, monkeypatch):
    store = tmp_path / "compile_passes.json"
    store.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(compile_passes, "STORE_PATH", store)
    assert compile_passes.expected(_job()) is None
    compile_passes.remember(_job(), 5)
    assert compile_passes.expected(_job()) == 5
