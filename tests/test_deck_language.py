"""Language selection uses translations with independent ids and versions."""
from dataclasses import replace

import pytest

from slidemage import compile_progress, compiler, deck_language, deck_outline, deck_scan, latex_lint, preview_target
from conftest import use_slides_folder


@pytest.fixture
def project(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    slides.mkdir()
    use_slides_folder(monkeypatch, slides)
    monkeypatch.setattr(latex_lint, "DECKS_DIR", tmp_path / "decks")
    (tmp_path / "decks").mkdir()
    for slug, header, title in (
        ("aaa-EN-One", "%% DE translation: ddd-DE-Eins\n", "English title"),
        ("ddd-DE-Eins", "%% Translation of: aaa-EN-One\n", "Deutscher Titel"),
        ("bbb-EN-Two", "", "No translation"),
        ("ccc-mult-Three", "", "Multilingual"),
    ):
        (slides / f"{slug}-current.tex").write_text(
            header + f"\\setSlideVersion{{7-3-1}}\n\\begin{{standardframe}}{{{title}}}Text\\end{{standardframe}}\n")
    (slides / "aaa-EN-One-v1-0-0.tex").write_text(
        "\\begin{standardframe}{English pinned}Old text\\end{standardframe}\n")
    return tmp_path


def deck(root, body, language="en"):
    path = root / "decks" / "course.tex"
    path.write_text("\\documentclass{beamer}\n" + f"\\decklanguage[{language}]\n"
                    + "\\begin{document}\n" + body + "\\end{document}\n")
    return next(d for d in deck_scan.scan_dir(path.parent, False) if d.path == path)


def rows(d, language):
    return [r for section in deck_outline.build_outline(d, "instructor", language) for r in section.rows]


def test_partner_replaces_original_in_its_section_and_late_partner_is_folded(project):
    d = deck(project, "\\section{First}\n\\slide{aaa-EN-One}\n\\slide{bbb-EN-Two}\n"
                     "\\section{Last}\n\\slide{ddd-DE-Eins}\n\\slide{ccc-mult-Three}\n")
    german = rows(d, "DE")
    assert [(r.call.id, r.title, r.position) for r in german] == [
        ("ddd", "Deutscher Titel", 1), ("bbb", "No translation", 2), ("ccc", "Multilingual", 3)]
    assert german[0].call.chapter.title == "First"
    assert german[0].deck_call.id == "aaa" and german[0].folded_calls[0].id == "ddd"
    assert [r.missing_translation for r in german] == [False, True, False]
    assert [r.call.id for r in rows(d, "EN")] == ["aaa", "bbb", "ccc"]
    assert rows(d, "EN")[0].key == german[0].key
    for slide_id in ("aaa", "ddd"):
        assert deck_outline.slide_row(d, slide_id, "instructor", "DE").call.id == "ddd"


def test_a_partner_need_not_have_a_deck_call_and_both_ids_find_its_slot(project):
    d = deck(project, "\\slide{aaa-EN-One}\n")
    assert rows(d, "DE")[0].call.id == "ddd"
    assert deck_outline.slide_row(d, "ddd", "instructor", "EN").call.id == "aaa"


def test_translation_versions_are_independent_of_english_pins(project):
    d = deck(project, "\\slideversion{aaa-EN-One}{1-0-0}\n\\omitslideversion{aaa-EN-One}{1-0-0}\n")
    english, german = rows(d, "EN"), rows(d, "DE")
    assert [r.call.version for r in english] == ["1-0-0", "1-0-0"]
    assert [(r.call.macro, r.call.version) for r in german] == [("slide", None), ("omitslide", None)]
    assert all(r.call.source_filename == "ddd-DE-Eins-current.tex" for r in german)
    target = preview_target.for_call(d, english[0].call, 1, "DE")
    assert target.source_path.name == "ddd-DE-Eins-current.tex" and target.version is None


def test_missing_translation_keeps_the_original_pin(project):
    d = deck(project, "\\slideversion{bbb-EN-Two}{1-0-0}\n")
    row = rows(d, "DE")[0]
    assert row.call.version == "1-0-0" and row.missing_translation


def test_source_visibility_steps_and_repeated_occurrences_survive_resolution(project):
    d = deck(project, "\\slidestep{aaa-EN-One}[instructor]{1,2}\n"
                     "\\slidestep{aaa-EN-One}[during-course]{3}\n"
                     "\\slide{aaa-EN-One}\n\\conditionalslide[after-course]{ddd-DE-Eins}\n")
    slots = deck_language.deck_slots(d, "DE")
    assert len(slots) == 3
    assert [s.call.steps for s in slots] == ["1,2", "3", None]
    assert [s.call.included_in("during-course") for s in slots] == [False, True, True]
    assert [r.hidden for section in deck_outline.build_outline(d, "during-course", "DE")
            for r in section.rows] == [True, False, False]
    assert compile_progress.count_job_slides(d, "during-course", None, "DE") == 2


def test_a_translation_only_deck_resolves_back_to_english(project):
    d = deck(project, "\\slide{ddd-DE-Eins}\n", "de")
    assert rows(d, "EN")[0].call.id == "aaa"
    assert rows(d, "DE")[0].call.id == "ddd"


def test_deleted_partner_falls_back_and_renamed_partner_is_found_by_id(project):
    d = deck(project, "\\slide{aaa-EN-One}\n")
    old = project / "slides" / "ddd-DE-Eins-current.tex"
    new = old.with_name("ddd-DE-Umbenannt-current.tex")
    old.rename(new)
    assert rows(d, "DE")[0].call.id_slug == "ddd-DE-Umbenannt"
    new.unlink()
    row = rows(d, "DE")[0]
    assert row.call.id == "aaa" and row.missing_translation and row.badge == "[EN]"


def test_links_with_wrong_language_or_self_reference_are_not_used(project):
    (project / "slides" / "ddd-DE-Eins-current.tex").unlink()
    source = project / "slides" / "aaa-EN-One-current.tex"
    source.write_text("%% DE translation: bbb-EN-Two\nText\n")
    d = deck(project, "\\slide{aaa-EN-One}\n")
    assert rows(d, "DE")[0].call.id == "aaa"
    source.write_text("%% DE translation: aaa-EN-One\nText\n")
    assert rows(d, "DE")[0].call.id == "aaa"


@pytest.mark.parametrize("missing_header", ["aaa-EN-One", "ddd-DE-Eins"])
def test_one_sided_links_resolve_in_both_directions(project, missing_header):
    path = project / "slides" / f"{missing_header}-current.tex"
    path.write_text(path.read_text().split("\n", 1)[1])
    d = deck(project, "\\slide{aaa-EN-One}\n\\slide{ddd-DE-Eins}\n")
    assert [r.call.id for r in rows(d, "DE")] == ["ddd"]
    assert [r.call.id for r in rows(d, "EN")] == ["aaa"]
    assert rows(d, "EN")[0].badge == "[EN + DE]"


def test_wrappers_resolve_full_chapter_and_appendix_without_writing_deck(project):
    d = deck(project, "\\section{First}\n\\slide{aaa-EN-One}\n"
                     "\\section{Last}\n\\slide{ddd-DE-Eins}\n\\slide{bbb-EN-Two}\n")
    before = d.path.read_bytes()
    job = compiler.CompileJob(d, "instructor", None, language="DE")
    wrapper = compiler.wrapper_text(job)
    assert wrapper.count("\\slide{ddd-DE-Eins}") == 1 and "\\slide{aaa-EN-One}" not in wrapper
    assert "\\slide{bbb-EN-Two}" in wrapper and "\\decklanguage[de]" in wrapper
    assert job.jobname == "course-instructor-de"
    chapter = compiler.wrapper_text(replace(job, chapter=d.chapters[0]))
    assert "\\slide{ddd-DE-Eins}" in chapter and "\\slide{bbb-EN-Two}" not in chapter
    appendix = compiler.wrapper_text(replace(job, appendix_toc=True))
    assert "\\hyperlink{ddd}" in appendix and "\\hyperlink{aaa}" not in appendix
    assert d.path.read_bytes() == before


def test_a_german_deck_resolves_partners_without_an_explicit_override(project):
    d = deck(project, "\\slide{aaa-EN-One}\n", "de")
    wrapper = compiler.wrapper_text(compiler.CompileJob(d, None, None))
    assert "\\slide{ddd-DE-Eins}" in wrapper


def test_commented_and_verbatim_calls_are_preserved_and_do_not_hide_a_real_partner(project):
    d = deck(project, "% \\slide{aaa-EN-One}\n"
                     "\\begin{verbatim}\n\\slide{aaa-EN-One}\n\\end{verbatim}\n"
                     "\\slide{ddd-DE-Eins}\n")
    assert len(deck_language.deck_slots(d, "DE")) == 1
    assert deck_language.resolved_text(d, "DE") == d.text


@pytest.mark.parametrize("command", ["input", "include"])
@pytest.mark.parametrize("suffix", ["", ".tex"])
def test_nested_body_fragments_are_resolved_and_kept_as_dependencies(project, command, suffix):
    fragment = project / "decks" / "slides.tex"
    nested = project / "decks" / "nested.tex"
    fragment_text = f"\\{command}{{nested{suffix}}}\n\\slide{{bbb-EN-Two}}\n"
    fragment.write_text(fragment_text)
    nested.write_text("\\slide{aaa-EN-One}\n\\slide{ddd-DE-Eins}\n")
    d = deck(project, f"\\{command}{{slides{suffix}}}\n")
    resolved, dependencies = deck_language.compile_deck(d, "DE")
    assert f"\\{command}{{slides{suffix}}}" not in resolved.text
    assert resolved.text.count("\\slide{ddd-DE-Eins}") == 1
    assert {fragment, nested, project / "slides/aaa-EN-One-current.tex",
            project / "slides/ddd-DE-Eins-current.tex"} == set(dependencies)
    assert fragment.read_text() == fragment_text
    assert compile_progress.count_job_slides(d, "instructor", None, "EN") == 2
    assert compile_progress.count_job_slides(d, "instructor", None, "DE") == 2


@pytest.mark.parametrize("command", ["includegraphics", "includeonly", "includepdf", "inputencoding"])
def test_other_commands_are_not_body_fragments(project, command):
    (project / "decks" / "x.tex").write_text("\\slide{aaa-EN-One}\n")
    d = deck(project, f"\\{command}{{x}}\n")
    resolved, dependencies = deck_language.compile_deck(d, "DE")
    assert resolved.text == d.text and dependencies == []
    assert compile_progress.count_job_slides(d, "instructor", None, "DE") == 0
    assert latex_lint.check_deck_job(d, language="DE").files_checked == 1


def test_precompile_check_checks_the_german_file_instead_of_the_english_file(project):
    (project / "slides" / "ddd-DE-Eins-current.tex").write_text(
        "%% Translation of: aaa-EN-One\n\\begin{standardframe}{Titel}{broken\\end{standardframe}\n")
    d = deck(project, "\\slide{aaa-EN-One}\n")
    en = latex_lint.check_jobs([compiler.CompileJob(d, None, None, language="EN")])
    de = latex_lint.check_jobs([compiler.CompileJob(d, None, None, language="DE")])
    assert not en.errors
    assert de.errors and all(i.path.name == "ddd-DE-Eins-current.tex" for i in de.errors)


def test_cleanup_preserves_partners_and_link_headers_of_an_english_pin(project, monkeypatch):
    from slidemage import unused_content

    deck(project, "\\slideversion{aaa-EN-One}{1-0-0}\n")
    monkeypatch.setattr(unused_content, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(unused_content, "DECKS_DIR", project / "decks")
    monkeypatch.setattr(unused_content, "ARCHIVE_DIR", project / "decks/archive")
    used = unused_content.find_used_slide_filenames()
    assert {"aaa-EN-One-v1-0-0.tex", "aaa-EN-One-current.tex", "ddd-DE-Eins-current.tex"} <= used
    assert {p.name for p in unused_content.find_unused_slides()} == {
        "bbb-EN-Two-current.tex", "ccc-mult-Three-current.tex"}


@pytest.mark.parametrize("gap", [" ", "\t", "\n"])
@pytest.mark.parametrize("source,filename", [
    (r"\slide{bbb-EN-Two}", "bbb-EN-Two-current.tex"),
    (r"\slidefinal{bbb-EN-Two}", "bbb-EN-Two-current.tex"),
    (r"\omitslide{bbb-EN-Two}", "bbb-EN-Two-current.tex"),
    (r"\slideversion{bbb-EN-Two}{1-0-0}", "bbb-EN-Two-v1-0-0.tex"),
    (r"\omitslideversion{bbb-EN-Two}{1-0-0}", "bbb-EN-Two-v1-0-0.tex"),
    (r"\conditionalslide[instructor]{bbb-EN-Two}", "bbb-EN-Two-current.tex"),
    (r"\slidestep{bbb-EN-Two}[instructor]{1}", "bbb-EN-Two-current.tex"),
])
def test_spaced_calls_keep_slides_used_and_update_headers(project, monkeypatch, gap, source, filename):
    from slidemage import deck_headers, unused_content

    deck(project, source.replace("{", gap + "{").replace("[", gap + "[") + "\n")
    (project / "slides" / filename).write_text("Slide content\n")
    monkeypatch.setattr(unused_content, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(unused_content, "DECKS_DIR", project / "decks")
    monkeypatch.setattr(unused_content, "ARCHIVE_DIR", project / "decks/archive")
    assert unused_content.find_used_slide_filenames() == {filename}
    assert filename not in {p.name for p in unused_content.find_unused_slides()}
    monkeypatch.setattr(deck_headers, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(deck_headers, "DECKS_GLOBS", [project / "decks"])
    deck_headers.regenerate_headers()
    assert "%% Included in decks: course" in (project / "slides/bbb-EN-Two-current.tex").read_text()


@pytest.mark.parametrize("macro", ["slideversion", "omitslideversion"])
def test_cleanup_keeps_explicit_pins_of_folded_translations(project, monkeypatch, macro):
    from slidemage import unused_content

    filename = "ddd-DE-Eins-v2-0-0.tex"
    (project / "slides" / filename).write_text("Pinned German slide\n")
    deck(project, f"\\{macro} {{aaa-EN-One}} {{1-0-0}}\n"
                  f"\\{macro}\n{{ddd-DE-Eins}}\n{{2-0-0}}\n")
    monkeypatch.setattr(unused_content, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(unused_content, "DECKS_DIR", project / "decks")
    monkeypatch.setattr(unused_content, "ARCHIVE_DIR", project / "decks/archive")
    assert unused_content.find_used_slide_filenames() == {
        "aaa-EN-One-v1-0-0.tex", "aaa-EN-One-current.tex", "ddd-DE-Eins-current.tex", filename}
    assert filename not in {p.name for p in unused_content.find_unused_slides()}


def test_usage_scans_preserve_comment_policy_and_legacy_slides(project, monkeypatch):
    from slidemage import deck_headers, unused_content

    legacy = project / "slides/eee-Legacy-current.tex"
    legacy.write_text("Legacy slide\n")
    deck(project, "\\slide {eee-Legacy}\n% \\slide{bbb-EN-Two}\n"
                  "\\% \\slide\n{ccc-mult-Three}\n")
    monkeypatch.setattr(unused_content, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(unused_content, "DECKS_DIR", project / "decks")
    monkeypatch.setattr(unused_content, "ARCHIVE_DIR", project / "decks/archive")
    assert unused_content.find_used_slide_filenames() == {legacy.name, "ccc-mult-Three-current.tex"}
    assert "bbb-EN-Two-current.tex" in {p.name for p in unused_content.find_unused_slides()}
    monkeypatch.setattr(deck_headers, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(deck_headers, "DECKS_GLOBS", [project / "decks"])
    deck_headers.regenerate_headers()
    for filename in (legacy.name, "bbb-EN-Two-current.tex", "ccc-mult-Three-current.tex"):
        assert "%% Included in decks: course" in (project / "slides" / filename).read_text()


def test_preview_maintenance_renders_both_files_independently(project, monkeypatch):
    from slidemage import update_all_previews

    d = deck(project, "\\slide{aaa-EN-One}\n")
    monkeypatch.setattr(update_all_previews, "scan_decks", lambda: [d])
    assert next(iter(update_all_previews.needed_slides_by_template().values())) == {
        "aaa-EN-One", "ddd-DE-Eins"}
    d = deck(project, "\\slide{aaa-EN-One}\n\\slide{ddd-DE-Eins}\n")
    job = compiler.CompileJob(d, None, None, language="DE", resolve_translations=False)
    wrapper = compiler.wrapper_text(job)
    assert "\\slide{aaa-EN-One}" in wrapper and "\\slide{ddd-DE-Eins}" in wrapper


def test_usage_panel_can_find_implicit_translation_use_without_transferring_pins(project):
    from slidemage import slide_usage

    d = deck(project, "\\slideversion{aaa-EN-One}{1-0-0}\n")
    assert slide_usage.find_usage("ddd-DE-Eins", [d]) == []
    used = slide_usage.find_usage("ddd-DE-Eins", [d], language="DE")
    assert len(used) == 1 and used[0].calls[0].version is None
    assert used[0].positions == [1] and used[0].following
    assert slide_usage.find_usage("aaa-EN-One", [d])[0].pinned_versions == ["1-0-0"]


def test_header_sync_lists_decks_that_use_a_partner_implicitly(project, monkeypatch):
    from slidemage import deck_headers

    d = deck(project, "\\slide{aaa-EN-One}\n")
    before = d.path.read_bytes()
    monkeypatch.setattr(deck_headers, "SLIDES_DIR", project / "slides")
    monkeypatch.setattr(deck_headers, "DECKS_GLOBS", [project / "decks"])
    deck_headers.regenerate_headers()
    assert "%% Included in decks: course" in (project / "slides/ddd-DE-Eins-current.tex").read_text()
    assert d.path.read_bytes() == before


@pytest.mark.parametrize("location", ["deck", "project", "fragment"])
@pytest.mark.parametrize("command", ["input", "include"])
def test_fragment_expansion_keeps_compiler_sources_and_tex_lookup_order(project, location, command):
    nested = project / "decks/nested"
    nested.mkdir()
    fragment = nested / "list.tex"
    fragment.write_text(rf"\{command}{{choice}}" + "\n")
    candidates = [project / "decks/choice.tex", project / "choice.tex", nested / "choice.tex"]
    locations = ["deck", "project", "fragment"]
    for title, path in zip(locations, candidates):
        if locations.index(title) >= locations.index(location):
            path.write_text(rf"\section{{{title}}}\slide{{bbb-EN-Two}}" + "\n")
    d = deck(project, "\\slide{ccc-mult-Three}\n" + rf"\{command}{{nested/list}}" + "\n")

    expanded, dependencies = deck_language.expand_fragments(d, strict_includes=True)
    calls = deck_language.active_calls(expanded)

    assert [(c.id, c.chapter.title if c.chapter else None) for c in calls] == [
        ("ccc", None), ("bbb", location)]
    assert set(dependencies) == {fragment, candidates[locations.index(location)]}
    resolved, dependencies = deck_language.compile_deck(d, "EN")
    assert resolved is d and dependencies == []
    wrapper = compiler.wrapper_text(compiler.CompileJob(d, "after-course", None))
    assert r"\input{course.tex}" in wrapper and r"\slide{bbb-EN-Two}" not in wrapper
