# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Revision transforms, archive ordering and slide saves."""
import pytest

from slidemage import slide_versioning as sv
from slidemage.slide_source import read_slide_source
from slidemage.fileio import write_texts

HEADER = "%% Included in decks: talk\n%%\n\n"


def _slide(tmp_path, current, frozen):
    slides = tmp_path / "slides"
    (slides / ".backups").mkdir(parents=True, exist_ok=True)
    (slides / "abc-EN-Demo-current.tex").write_text(current, encoding="utf-8", newline="")
    for version, text in frozen.items():
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(text, encoding="utf-8", newline="")
    return slides


def restore(ctx, current, selected):
    cap = sv.capture(ctx, "restore", [current, selected])
    edits = sv.restore(cap, current, selected)
    write_texts(edits)
    return next(iter(edits)), sv.parse_version(edits[current][1])


def update(ctx, current, level):
    cap = sv.capture(ctx, level, [current])
    edits = sv.patch_edits(cap, current, level, {})
    write_texts(edits)
    return next(iter(edits)), *cap.update(current, level)


def test_marker_edits_replace_all_live_markers_and_preserve_comments():
    text = "% \\setSlideVersion{9-9-9}\n\\setSlideVersion{1-2-3}\nbody\n\\setSlideVersion{4-5-6}\n"
    assert sv.parse_version(text) == (1, 2, 3)
    assert sv.parse_version(r"\% \setSlideVersion{1-2-3}") == (1, 2, 3)
    assert sv.strip_marker(text) == "% \\setSlideVersion{9-9-9}\nbody\n"
    assert sv.set_marker(text, (2, 0, 0)) == "% \\setSlideVersion{9-9-9}\n\\setSlideVersion{2-0-0}\nbody\n"


def test_restore_refuses_identical_content_and_taken_archive_name(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nsame\n",
                    {"1-0-0": HEADER + "same\n"})
    current = slides / "abc-EN-Demo-current.tex"
    with pytest.raises(sv.RestoreError):
        restore(ctx, current, slides / "abc-EN-Demo-v1-0-0.tex")

    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew\n",
                    {"1-0-0": "old\n", "1-1-0": "something else\n"})
    with pytest.raises(sv.RestoreError):
        restore(ctx, current, slides / "abc-EN-Demo-v1-0-0.tex")
    assert "new" in current.read_text(encoding="utf-8")        # nothing changed


def test_update_freezes_the_first_revision_and_bumps_it_only_after_changes(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\ntext\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    frozen, version, base = update(ctx, current, "major")
    assert version == base == (1, 1, 0) and frozen == slides / "abc-EN-Demo-v1-1-0.tex"
    with pytest.raises(ValueError, match="not changed since v1.1.0"):
        update(ctx, current, "major")
    current.write_text(HEADER + "\\setSlideVersion{1-1-0+}\nchanged\n", encoding="utf-8")
    frozen, version, base = update(ctx, current, "major")
    assert (version, base) == ((2, 0, 0), (1, 1, 0))
    assert frozen == slides / "abc-EN-Demo-v2-0-0.tex"
    assert current.read_text(encoding="utf-8") == frozen.read_text(encoding="utf-8") == (
        HEADER + "\\setSlideVersion{2-0-0}\nchanged\n")


def test_update_version_treats_an_untracked_slide_as_1_0_0_and_refuses_a_taken_version(ctx, tmp_path):
    slides = _slide(tmp_path, "plain\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    assert update(ctx, current, "minor")[1] == (1, 0, 0)
    assert "\\setSlideVersion{1-0-0}" in current.read_text(encoding="utf-8")
    current.write_text("\\setSlideVersion{1-0-0+}\nplain, changed\n", encoding="utf-8")
    (slides / "abc-EN-Demo-v1-0-1.tex").write_text("taken", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen already"):
        update(ctx, current, "patch")


def test_save_slide_freezes_the_version_first_and_marks_the_change(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-2-0}\nsaved the old way\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    before = read_slide_source(current)[0]
    written, backup, frozen = sv.save_slide(ctx, current, before.replace("old way", "new way"), "\n", before)

    assert frozen == slides / "abc-EN-Demo-v1-2-0.tex"
    assert frozen.read_text(encoding="utf-8") == before            # the version's content is kept
    assert "\\setSlideVersion{1-2-0+}\n" in written and current.read_text(encoding="utf-8") == written
    assert backup is not None

    # The exact last save is required, including the "+".
    from slidemage.fileio import StaleFileError
    with pytest.raises(StaleFileError):
        sv.save_slide(ctx, current, "stale edit", "\n", sv.without_plus(written))
    assert current.read_text(encoding="utf-8") == written and frozen.read_text(encoding="utf-8") == before
    again, backup, frozen = sv.save_slide(ctx, current, written.replace("new way", "third way"), "\n", written,
                                          backup=False)
    assert frozen is None and backup is None and "\\setSlideVersion{1-2-0+}" in again and "third way" in again


def test_save_slide_marks_an_untracked_slide_and_leaves_other_files_alone(ctx, tmp_path):
    slides = _slide(tmp_path, "plain\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    written = sv.save_slide(ctx, current, "plain, changed\n", "\n", "plain\n")[0]
    assert written == "\\setSlideVersion{1-0-0+}\nplain, changed\n"
    assert (slides / "abc-EN-Demo-v1-0-0.tex").read_text(encoding="utf-8") == "plain\n"

    deck = tmp_path / "talk.tex"
    deck.write_bytes(b"deck\n")
    assert sv.save_slide(ctx, deck, "deck, changed\n", "\n", "deck\n")[0] == "deck, changed\n"


def test_plus_helpers():
    plus, clean = "\\setSlideVersion{1-2-0+}\nx\n", "\\setSlideVersion{1-2-0}\ny\n"
    assert sv.parse_marker(plus) == ((1, 2, 0), True) and sv.version_text(plus) == "1.2.0+"
    assert sv.without_plus(plus) == "\\setSlideVersion{1-2-0}\nx\n"
    assert sv.carry_plus(plus, clean) == "\\setSlideVersion{1-2-0+}\ny\n"
    assert sv.carry_plus(clean, plus) == plus
    assert sv.strip_marker(plus) == "x\n"


@pytest.mark.parametrize("changed, archive_version", [(False, "1-1-0"), (True, "1-1-1")])
def test_restore_keeps_the_current_header_and_archives_the_displaced_revision(ctx, tmp_path, changed, archive_version):
    old = "%% Included in decks: stale\n%%\n\nold text\n"
    frozen = {"1-0-0": old}
    if changed:
        frozen["1-1-0"] = HEADER + "\\setSlideVersion{1-1-0}\nmiddle\n"
    marker = "1-1-0+" if changed else "1-1-0"
    slides = _slide(tmp_path, HEADER + f"\\setSlideVersion{{{marker}}}\nnew text\n", frozen)
    current = slides / "abc-EN-Demo-current.tex"
    selected = slides / "abc-EN-Demo-v1-0-0.tex"
    archived, version = restore(ctx, current, selected)
    assert archived == slides / f"abc-EN-Demo-v{archive_version}.tex" and version == (1, 2, 0)
    assert f"\\setSlideVersion{{{archive_version}}}\nnew text" in archived.read_text(encoding="utf-8")
    assert read_slide_source(current)[0] == HEADER + "\\setSlideVersion{1-2-0}\nold text\n"
    assert selected.read_text(encoding="utf-8") == old


def test_last_saved_sees_a_save_without_backup(ctx, tmp_path):
    from slidemage import slide_source
    slides = _slide(tmp_path, "a\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    slide_source.save_slide_source(ctx, current, "b\n", "\n", expected_text="a\n", backup=False)
    assert not list((ctx.slide_backups_dir / current.name).glob("*.tex"))
    assert slide_source.last_saved(ctx, current) is not None


@pytest.mark.parametrize("action", ["autosave", "overwrite"])
def test_failed_current_write_preserves_the_version_and_can_start_again(ctx, tmp_path, monkeypatch, action):
    from slidemage import fileio

    name = "abc-EN-Demo"
    raw = "\\setSlideVersion{1-0-0+}\nnew\n" if action == "overwrite" else "old\n"
    slides = _slide(tmp_path, raw, {"1-0-0": "pinned\n"} if action == "overwrite" else {})
    path, frozen = slides / f"{name}-current.tex", slides / f"{name}-v1-0-0.tex"

    def save():
        if action == "autosave":
            sv.save_slide(ctx, path, "edited\n", "\n", raw)
        else:
            write_texts(sv.overwrite_edits(sv.capture(ctx, "overwrite", [path]), path))

    replace = fileio.os.replace
    def fail(source, target):
        if target == path:
            raise OSError("disk full")
        replace(source, target)

    with monkeypatch.context() as m:
        m.setattr(fileio.os, "replace", fail)
        with pytest.raises(fileio.PartialWriteError):
            save()
    assert path.read_bytes() == raw.encode()
    if action == "overwrite":
        assert frozen.read_bytes() == b"pinned\n"
    else:
        assert not frozen.exists()
    save()
    assert frozen.read_bytes() == (path.read_bytes() if action == "overwrite" else raw.encode())


def test_revision_edits_are_computed_from_captured_text(tmp_path):
    current, frozen, selected = [tmp_path / p for p in ("current", "frozen", "selected")]
    raw = "\\setSlideVersion{1-0-0+}\r\nbody\r\n"
    marked, freeze = sv.prepare_autosave("original", "new", None)
    assert freeze and marked == "\\setSlideVersion{1-0-0+}\nnew"
    marked, freeze = sv.prepare_autosave(raw, "old", "old")
    assert not freeze and marked == "\\setSlideVersion{1-0-0}\nold"
    for before, number in ((None, (1, 0, 1)), ("pinned", (1, 0, 0))):
        after = f"\\setSlideVersion{{{sv.format_hyphen(number)}}}\r\nbody\r\n"
        assert list(sv.version_edits(current, raw, frozen, before, number).items()) == [
            (frozen, (before, after)), (current, (raw, after))]
    edits = sv.restore_edits(current, raw, selected, "old\n", frozen, None, (1, 0, 1), (1, 1, 0))
    assert list(edits.items()) == [
        (frozen, (None, "\\setSlideVersion{1-0-1}\r\nbody\r\n")),
        (selected, ("old\n", "old\n")),
        (current, (raw, "\\setSlideVersion{1-1-0}\r\nold\r\n"))]


def test_a_batch_can_overwrite_the_version_each_slide_is_based_on(ctx, tmp_path):
    slides = _slide(tmp_path, "\\setSlideVersion{1-0-0+}\nnew\n", {"1-0-0": "pinned\n"})
    current, frozen = slides / "abc-EN-Demo-current.tex", slides / "abc-EN-Demo-v1-0-0.tex"
    cap = sv.capture(ctx, "batch", [current])
    write_texts(sv.batch_edits(cap, [current], "overwrite"))
    assert frozen.read_bytes() == current.read_bytes() and "1-0-0+" not in current.read_text(encoding="utf-8")
    assert not (slides / "abc-EN-Demo-v1-0-1.tex").exists()
