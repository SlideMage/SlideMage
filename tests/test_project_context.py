"""Two projects side by side in one process: every module takes the ProjectContext it works on, so
needs no module reload, no patched path globals and no "current project"."""
from __future__ import annotations

from slidemage import (
    alt_images, app_settings, compiler, deck_scan, housekeeping, image_review, slide_ids, slide_rename, transcript,
    unused_content,
)
from slidemage.ai import ai_profile
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ai.tools import edits
from slidemage.ai.tools.base import ToolContext
from slidemage.ai.workspace import Workspace
from slidemage.project import ProjectContext

DECK = "\\documentclass{beamer}\n\\begin{document}\n\\slide{aaa-EN-Used}\n\\end{document}\n"


def make(root, deck_name, slides):
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / "pdf").mkdir()
    (root / "slide_ids.csv").write_text('"id"\n', encoding="utf-8")
    (root / "decks" / f"{deck_name}.tex").write_text(DECK, encoding="utf-8")
    for name in slides:
        (root / "slides" / f"{name}-current.tex").write_text("slide\n", encoding="utf-8")
    return ProjectContext.at(root)


def test_the_context_names_the_places_inside_one_project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    assert ctx.slides_dir == tmp_path / "slides" and ctx.archive_dir == tmp_path / "decks" / "archive"
    assert ctx.build_dir == tmp_path / ".build" and ctx.settings_dir == tmp_path / ".slidemage"
    assert ctx.slide_backups_dir == tmp_path / "slides" / ".backups"
    assert ProjectContext(tmp_path, tmp_path / "elsewhere").build_dir == tmp_path / "elsewhere"


def test_settings_decks_and_housekeeping_follow_the_context_they_are_given(tmp_path):
    one = make(tmp_path / "one", "first", ["aaa-EN-Used", "bbb-EN-Spare"])
    two = make(tmp_path / "two", "second", ["aaa-EN-Used"])
    (two.pdf_dir / "a.pdf").write_bytes(b"x")

    app_settings.set(one, "dark_mode", False)
    assert app_settings.get(one, "dark_mode") is False and app_settings.get(two, "dark_mode") is None
    assert (one.settings_dir / "app_settings.json").is_file() and not two.settings_dir.exists()

    assert [d.name for d in deck_scan.scan_decks(one)] == ["first"]
    assert [d.name for d in deck_scan.scan_decks(two)] == ["second"]

    assert [p.name for p in unused_content.find_unused_slides(one)] == ["bbb-EN-Spare-current.tex"]
    assert unused_content.find_unused_slides(two) == []
    assert housekeeping.pdf_files(one) == [] and [p.name for p in housekeeping.pdf_files(two)] == ["a.pdf"]


BIB = "@book{key2020,\n  author = {%s, Ann},\n  title = {A book},\n  year = {2020}\n}\n"
FRAME = "\\begin{standardframe}{T}\n\\begin{itemize}\n\\item See \\textcite{key2020}.\n\\end{itemize}\n\\end{standardframe}\n"


def test_the_editing_and_ai_layers_run_two_projects_side_by_side(tmp_path):
    one = make(tmp_path / "one", "first", ["aaa-EN-Used"])
    two = make(tmp_path / "two", "second", ["aaa-EN-Used"])
    one.bibliography_path.write_text(BIB % "Smith", encoding="utf-8")
    two.bibliography_path.write_text(BIB % "Jones", encoding="utf-8")

    # ids are minted and registered per project
    fresh = slide_ids.mint_slide_id(one)
    slide_ids.append_slide_id(one, fresh)
    assert fresh in slide_ids.existing_ids_from_csv(one) and fresh not in slide_ids.existing_ids_from_csv(two)
    assert slide_ids.list_id_slugs(one) == slide_ids.list_id_slugs(two) == ["aaa-EN-Used"]

    # a rename rewrites the files and deck calls of its own project only
    slide_rename.rename_slide_slug(one, "aaa-EN-Used", "Renamed")
    assert (one.slides_dir / "aaa-EN-Renamed-current.tex").is_file()
    assert (two.slides_dir / "aaa-EN-Used-current.tex").is_file() and not (two.slides_dir / "aaa-EN-Renamed-current.tex").exists()
    assert "aaa-EN-Renamed" in (one.decks_dir / "first.tex").read_text(encoding="utf-8")
    assert "aaa-EN-Used" in (two.decks_dir / "second.tex").read_text(encoding="utf-8")

    # a transcript cites from the bibliography of the project it renders for
    for ctx, author in ((one, "Smith"), (two, "Jones")):
        assert author in transcript.generate_single_slide(ctx, FRAME, "aaa", "during-course", "en").markdown

    # image descriptions and media names live in the project they were stored in
    alt_images.save_slide_image(one, "media/a.png", "aaa", one.slides_dir / "aaa-EN-Renamed-current.tex",
                                role="informative", short="one", long="one", reviewed=False)
    assert list(alt_images.load_store(one)) == ["media/a.png"] and alt_images.load_store(two) == {}
    assert image_review.media_destination(one, "x.png") == one.media_dir / "x.png"
    assert image_review.media_destination(two, "x.png") == two.media_dir / "x.png"

    # an agent tool edits the file of the workspace it runs in
    tool = ToolContext(two, Workspace(two), lambda _event: None, compiler.CancelToken(), EDIT_AUTO)
    edits.edit_file.run(tool, {"path": "slides/aaa-EN-Used-current.tex", "old_text": "slide", "new_text": "changed"})
    assert "changed" in (two.slides_dir / "aaa-EN-Used-current.tex").read_text(encoding="utf-8")
    assert "changed" not in (one.slides_dir / "aaa-EN-Renamed-current.tex").read_text(encoding="utf-8")

    # the AI settings are per project too
    ai_profile.set_policy(one, ai_profile.CLOUD)
    assert ai_profile.policy(one) == ai_profile.CLOUD and ai_profile.policy(two) == ai_profile.LOCAL
