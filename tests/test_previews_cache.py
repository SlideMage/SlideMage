"""TikZ pictures and rendered PDF pages live in this computer's cache folder, not in the project."""
from slidemage import preview_build, project
from slidemage.project import ProjectContext


def test_places_are_in_the_cache_folder_under_the_project_id(tmp_path):
    ctx = ProjectContext.at(tmp_path / "Proj")
    base = project.cache_dir() / "projects" / project.project_id(ctx.root) / "previews"
    assert ctx.previews_dir == base == project.previews_cache_dir(ctx.root)
    assert preview_build.maintenance_lock(ctx.root) == base / "preview-maintenance.lock"
    assert ctx.tikz_previews_dir == base / "tikz_illustration_previews"
    assert ctx.pdf_render_cache_dir == base / "pdf_render_cache"
    assert not any(p.is_relative_to(ctx.root) for p in (ctx.tikz_previews_dir, ctx.pdf_render_cache_dir))
    assert ProjectContext.at(tmp_path / "Other").previews_dir != base       # one folder per project
