from slidemage.app_info import license_text


def test_license_found_outside_project():
    assert "Slidemaster" in license_text()


def test_relaunch_with_project_saves_and_spawns(monkeypatch, tmp_path):
    """2026-09-23: on a fresh machine's first real run, cli.py's discovery
    chain (env var / upward search / last project) can silently reuse a
    stale last-project pointer left over from unrelated testing, so the
    user never sees the folder picker they expected. The fix adds an
    explicit "Open Project..." action; this covers its
    underlying relaunch mechanism, since a live in-process project switch
    isn't possible (PROJECT_ROOT and everything derived from it are fixed
    at import time across the whole package)."""
    from slidemage import project

    new_root = tmp_path / "other-project"
    new_root.mkdir()
    (new_root / project.MARKER).write_text("id,slug\n", encoding="utf-8")
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")

    calls = []
    monkeypatch.setattr(
        project.subprocess, "Popen",
        lambda argv, env: calls.append((argv, env)),
    )

    project.relaunch_with_project(new_root)

    assert project.load_last_project() == new_root
    assert len(calls) == 1
    argv, env = calls[0]
    assert str(new_root) in argv
    assert env[project.ENV_VAR] == str(new_root)


def test_discover_ignores_unrelated_cwd_with_no_last_project(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.delenv(project.ENV_VAR, raising=False)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert project.discover() is None


def _make_project(root):
    from slidemage import project

    root.mkdir(parents=True, exist_ok=True)
    (root / project.MARKER).write_text("id,slug\n", encoding="utf-8")
    return root


def test_last_project_is_also_kept_beside_the_exe(monkeypatch, tmp_path):
    """A second PC running the same cloud-synced exe has no %APPDATA% pointer;
    the copy beside the exe lets it open the project without the picker."""
    import sys
    from slidemage import project

    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "SlideMage.exe"))
    root = _make_project(tmp_path / "Slidemaster")

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc1")
    project.save_last_project(root)
    assert (exe_dir / "last_project").read_text(encoding="utf-8") == str(root)

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "pc2")  # nothing there
    assert project.load_last_project() == root


def test_last_project_without_exe_writes_only_the_config_file(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    root = _make_project(tmp_path / "p")
    project.save_last_project(root)
    assert project.load_last_project() == root
    assert not (tmp_path / "last_project").exists()


def test_last_project_hint_is_nearest_existing_folder(monkeypatch, tmp_path):
    from slidemage import project

    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    root = _make_project(tmp_path / "cloud" / "Slidemaster")
    project.save_last_project(root)
    (root / project.MARKER).unlink()
    root.rmdir()
    assert project.load_last_project() is None
    assert project.last_project_hint() == tmp_path / "cloud"


def test_init_project_seeds_from_example_and_compiles(tmp_path):
    """2026-09-23, direct report: picked an intentionally empty folder on
    first startup, meant to become a brand-new project, and got only
    "has no slide_ids.csv" with no way to actually create one there.
    init_project() (wired into both cli.py's first-run picker and
    the "Open Project..." action) fixes that -- verifies the seeded copy
    is not just a valid project by marker, but an actually compilable one."""
    from slidemage import project

    assert project.has_example_template()
    target = tmp_path / "new_project"
    project.init_project(target, copy_example=True)
    assert project.is_project(target)
    assert (target.parent / "latex").is_dir()
    assert (target / "decks" / "slidemage-manual.tex").is_file()
    # No build output copied in -- a new project compiles its own.
    assert not (target / "decks" / "slidemage-manual.pdf").exists()
    assert not (target / ".build").exists()
    # The real logo asset (not build output) must still be there, or the
    # copy can't actually compile.
    assert (target / "schemes" / "scheme_uni_graz" /
            "Logo_Uni-Graz_4c-cropped.pdf").is_file()


def test_init_project_empty_fallback(tmp_path):
    from slidemage import project

    target = tmp_path / "blank_project"
    project.init_project(target, copy_example=False)
    assert project.is_project(target)
    assert (target / "slide_ids.csv").read_bytes() == b'"id"\r\n'
    for sub in ("slides", "decks", "media"):
        assert (target / sub).is_dir()


def test_init_project_never_overwrites_existing_latex_sibling(tmp_path):
    """A sibling latex/ several projects might already share must never
    be silently stomped by scaffolding a new project next to it."""
    from slidemage import project

    (tmp_path / "latex").mkdir()
    (tmp_path / "latex" / "sentinel.txt").write_text("do not touch")
    target = tmp_path / "new_project"
    project.init_project(target, copy_example=True)
    assert (tmp_path / "latex" / "sentinel.txt").read_text() == "do not touch"
