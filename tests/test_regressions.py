from slidemage.app_info import license_text


def test_license_found_outside_project():
    assert "Slidemaster" in license_text()


def test_stale_translation_is_not_written_as_in_sync(monkeypatch, tmp_path):
    """A batch translation whose English text has since been edited must
    not be saved with a translated_from_hash that makes translation_state()
    call it 'in sync' -- see alt_draft.apply_one_translation's own comment
    for the full scenario (a long-running 'Translate all' batch snapshots
    its queue once up front)."""
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="original english", takeaway_default="t1")
    original_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    # The batch translates from a queue snapshot taken before this edit.
    stale_result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated from the OLD text",
        takeaway_de="t1-de", model="test", source_hash=original_hash,
    )

    # ... then, while that translation was in flight, the user edits the
    # English text (e.g. via the review tab, on the GUI thread).
    def edit_english(entries):
        entries["media/x.png"].long = "edited english"
        return True

    alt_images.update_store(edit_english)

    written = alt_draft.apply_one_translation("media/x.png", stale_result, "test")
    assert written is False

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == ""  # stale translation was NOT written
    assert current.translated_from_hash == ""


def test_fresh_translation_is_written_normally(monkeypatch, tmp_path):
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="english text", takeaway_default="t1")
    current_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated text",
        takeaway_de="t1-de", model="test", source_hash=current_hash,
    )
    written = alt_draft.apply_one_translation("media/x.png", result, "test")
    assert written is True

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == "translated text"
    assert current.translated_from_hash == current_hash


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


def test_ollama_host_setting_overrides_default(monkeypatch, tmp_path):
    """2026-09-23 review finding: the Ollama host was a hardcoded constant
    duplicated in alt_draft.py and ai_draft.py, with no way to point this
    app at a non-default Ollama server. app_settings.get_ollama_host()
    resolves it; OllamaProvider reads it when constructed instead of
    freezing a constant at class-definition time."""
    from slidemage import app_settings
    from slidemage.ai.providers import OllamaProvider

    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    assert app_settings.get_ollama_host() == "http://localhost:11434"

    app_settings.set_ollama_host("http://gpu-box:9999")
    assert app_settings.get_ollama_host() == "http://gpu-box:9999"
    assert OllamaProvider("m").host == "http://gpu-box:9999"

    # An explicit host= still wins over the saved setting.
    assert OllamaProvider("m", host="http://explicit").host == "http://explicit"

    # Clearing it falls back through $OLLAMA_HOST, then the plain default.
    app_settings.set_ollama_host("")
    assert app_settings.get_ollama_host() == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://from-env:8000")
    assert app_settings.get_ollama_host() == "http://from-env:8000"


def test_draft_prompt_is_customizable_and_persists(monkeypatch, tmp_path):
    """2026-09-23 review finding: alt_draft.py's image-description prompt
    was a hardcoded SYSTEM_PROMPT constant -- unlike translation_prompts.py's
    already-customizable prompts, there was no way to tune it without
    editing source."""
    from slidemage import alt_draft, draft_prompts
    from slidemage.ai.providers import OllamaProvider

    monkeypatch.setattr(draft_prompts, "STORE_PATH", tmp_path / "draft_prompts.json")

    assert alt_draft.effective_system_prompt() == alt_draft.SYSTEM_PROMPT

    draft_prompts.set_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT, "Custom draft prompt.")
    assert alt_draft.effective_system_prompt() == "Custom draft prompt."

    # A freshly constructed backend with no explicit system_prompt picks
    # up the current custom default; an explicit one still overrides it.
    provider = OllamaProvider("m")
    assert alt_draft.ModelBackend(provider).system_prompt == "Custom draft prompt."
    assert alt_draft.ModelBackend(provider, system_prompt="one-off").system_prompt == "one-off"

    # Clearing (empty string) reverts to the hardcoded default.
    draft_prompts.set_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT, "")
    assert alt_draft.effective_system_prompt() == alt_draft.SYSTEM_PROMPT
    assert draft_prompts.get_custom_prompt(draft_prompts.KIND_IMAGE_DRAFT) is None


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
