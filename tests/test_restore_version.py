"""Making a frozen version the current one again (slide_versioning.restore_version)."""
import pytest

from slidemage import slide_versioning as sv
from slidemage.slide_source import read_slide_source

HEADER = "%% Included in decks: talk\n%%\n\n"


def _slide(tmp_path, current, frozen):
    slides = tmp_path / "slides"
    (slides / ".backups").mkdir(parents=True, exist_ok=True)
    (slides / "abc-EN-Demo-current.tex").write_text(current, encoding="utf-8")
    for version, text in frozen.items():
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(text, encoding="utf-8")
    return slides


@pytest.fixture(autouse=True)
def _backup_root(tmp_path, monkeypatch):
    from slidemage import slide_source
    monkeypatch.setattr(slide_source, "PROJECT_ROOT", tmp_path)


def test_restore_archives_current_and_bumps_the_version(tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew text\n",
                    {"1-0-0": "%% Included in decks: stale\n%%\n\nold text\n"})
    current = slides / "abc-EN-Demo-current.tex"
    archived, version = sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    assert version == (1, 2, 0)                       # 1.1.0 is not reused
    assert archived == slides / "abc-EN-Demo-v1-1-0.tex"
    assert "new text" in archived.read_text(encoding="utf-8")
    text, _ = read_slide_source(current)
    assert "old text" in text and "new text" not in text
    assert "\\setSlideVersion{1-2-0}" in text
    assert text.startswith("%% Included in decks: talk\n")   # the current header is kept
    assert (slides / "abc-EN-Demo-v1-0-0.tex").read_text(encoding="utf-8").endswith("old text\n")


def test_restore_refuses_identical_content_and_taken_archive_name(tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nsame\n",
                    {"1-0-0": HEADER + "same\n"})
    current = slides / "abc-EN-Demo-current.tex"
    with pytest.raises(sv.RestoreError):
        sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew\n",
                    {"1-0-0": "old\n", "1-1-0": "something else\n"})
    with pytest.raises(sv.RestoreError):
        sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")
    assert "new" in current.read_text(encoding="utf-8")        # nothing changed
