# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Language selection uses translations with independent ids and versions."""
from dataclasses import replace

import pytest

from slidemage import (
    compile_progress, compiler, deck_headers, deck_language, deck_outline, deck_scan,
    latex_lint, preview_target, slide_language, slide_usage, unused_content,
)
from conftest import EXAMPLE_PROJECT, write_test_file


@pytest.fixture
def project(tmp_path):
    slides = tmp_path / "slides"
    slides.mkdir()
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
    write_test_file(path, "\\documentclass{beamer}\n" + f"\\decklanguage[{language}]\n"
                    + "\\begin{document}\n" + body + "\\end{document}\n")
    return next(d for d in deck_scan.scan_dir(path.parent, False) if d.path == path)


def rows(ctx, d, language):
    return [r for section in deck_outline.build_outline(ctx, d, "instructor", language) for r in section.rows]


def test_partner_replaces_original_in_its_section_and_late_partner_is_folded(ctx, project):
    d = deck(project, "\\section{First}\n\\slide{aaa-EN-One}\n\\slide{bbb-EN-Two}\n"
                     "\\section{Last}\n\\slide{ddd-DE-Eins}\n\\slide{ccc-mult-Three}\n")
    german = rows(ctx, d, "DE")
    assert [(r.call.id, r.title, r.position) for r in german] == [
        ("ddd", "Deutscher Titel", 1), ("bbb", "No translation", 2), ("ccc", "Multilingual", 3)]
    assert german[0].call.chapter.title == "First"
    assert german[0].deck_call.id == "aaa" and german[0].folded_calls[0].id == "ddd"
    assert [r.missing_translation for r in german] == [False, True, False]
    assert [r.call.id for r in rows(ctx, d, "EN")] == ["aaa", "bbb", "ccc"]
    assert rows(ctx, d, "EN")[0].key == german[0].key
    for slide_id in ("aaa", "ddd"):
        assert deck_outline.slide_row(ctx, d, slide_id, "instructor", "DE").call.id == "ddd"


def test_english_pins_use_current_links_without_pinning_translations(ctx, project):
    frozen = ctx.slides_dir / "aaa-EN-One-v1-0-0.tex"
    frozen.write_text("%% DE translation: eee-DE-Old\nText\n")
    (ctx.slides_dir / "eee-DE-Old-current.tex").write_text("Text\n")
    d = deck(project, "\\slideversion{aaa-EN-One}{1-0-0}\n\\omitslideversion{aaa-EN-One}{1-0-0}\n")
    english, german = rows(ctx, d, "EN"), rows(ctx, d, "DE")
    assert [r.call.version for r in english] == ["1-0-0", "1-0-0"]
    assert [(r.call.macro, r.call.version) for r in german] == [("slide", None), ("omitslide", None)]
    target = preview_target.for_call(ctx, d, english[0].call, 1, "DE")
    assert target.source_path.name == "ddd-DE-Eins-current.tex" and target.version is None
    assert slide_language.translation_group(ctx, "aaa-EN-One", frozen)[0].partner == "ddd-DE-Eins"
    assert deck_outline.slide_row(ctx, d, "ddd", "instructor", "EN").call.id == "aaa"
    assert not slide_usage.find_usage(ctx, "ddd-DE-Eins", [d])
    used, = slide_usage.find_usage(ctx, "ddd-DE-Eins", [d], language="DE")
    assert used.positions == [1, 2] and used.following
    assert all(call.version is None for call in used.calls)
    assert slide_usage.find_usage(ctx, "aaa-EN-One", [d])[0].pinned_versions == ["1-0-0"]
    before = d.path.read_bytes()
    deck_headers.regenerate_headers(ctx)
    assert "%% Included in decks: course" in target.source_path.read_text()
    assert d.path.read_bytes() == before


def test_source_visibility_steps_and_repeated_occurrences_survive_resolution(ctx, project):
    d = deck(project, "\\slidestep{aaa-EN-One}[instructor]{1,2}\n"
                     "\\slidestep{aaa-EN-One}[during-course]{3}\n"
                     "\\slide{aaa-EN-One}\n\\conditionalslide[after-course]{ddd-DE-Eins}\n")
    slots = deck_language.deck_slots(ctx, d, "DE")
    assert [s.call.steps for s in slots] == ["1,2", "3", None]
    assert [r.hidden for section in deck_outline.build_outline(ctx, d, "during-course", "DE")
            for r in section.rows] == [True, False, False]
    assert compile_progress.count_job_slides(ctx, d, "during-course", None, "DE") == 2


def test_renamed_partner_is_found_by_id_and_deleted_partner_falls_back_to_the_pin(ctx, project):
    d = deck(project, "\\slideversion{aaa-EN-One}{1-0-0}\n")
    old = project / "slides" / "ddd-DE-Eins-current.tex"
    new = old.with_name("ddd-DE-Umbenannt-current.tex")
    old.rename(new)
    assert rows(ctx, d, "DE")[0].call.id_slug == "ddd-DE-Umbenannt"
    new.unlink()
    row = rows(ctx, d, "DE")[0]
    assert (row.call.id, row.call.version, row.missing_translation) == ("aaa", "1-0-0", True)


@pytest.mark.parametrize("slug,header", [
    ("aaa-EN-One", ""),
    ("ddd-DE-Eins", ""),
    ("aaa-EN-One", "%% DE translation: bbb-EN-Two\n%% DE translation: ddd-DE-Eins\n"),
])
def test_partial_links_resolve_in_the_outline_and_badge(ctx, project, slug, header):
    (ctx.slides_dir / f"{slug}-current.tex").write_text(header + "Text\n")
    d = deck(project, "\\slide{aaa-EN-One}\n")
    assert [r.call.id for r in rows(ctx, d, "DE")] == ["ddd"]
    assert rows(ctx, d, "EN")[0].badge == "[EN + DE]"
    assert slide_language.translation_group(ctx, "ddd-DE-Eins")[0].partner == "aaa-EN-One"


def test_conflicting_reverse_links_have_no_partner_in_either_reader(ctx, project):
    slides = project / "slides"
    (slides / "aaa-EN-One-current.tex").write_text("Text\n")
    (slides / "eee-DE-Andere-current.tex").write_text("%% Translation of: aaa-EN-One\nText\n")
    d = deck(project, "\\slide{aaa-EN-One}\n")
    assert deck_language.deck_slots(ctx, d, "DE")[0].call.id_slug == "aaa-EN-One"
    assert slide_language.translation_group(ctx, "aaa-EN-One") == []
    assert slide_language.translated_languages(ctx, "aaa-EN-One") == ()
    assert slide_language.badge_for(ctx, "aaa-EN-One").text() == "[EN]"


def test_wrappers_resolve_full_chapter_and_appendix_without_writing_deck(ctx, project):
    d = deck(project, "\\section{First}\n\\slide{aaa-EN-One}\n"
                     "\\section{Last}\n\\slide{ddd-DE-Eins}\n\\slide{bbb-EN-Two}\n", "de")
    before = d.path.read_bytes()
    job = compiler.CompileJob(d, "instructor", None)
    german, english, untranslated = (rf"\slide{{{slug}}}" for slug in ("ddd-DE-Eins", "aaa-EN-One", "bbb-EN-Two"))
    wrapper = compiler.wrapper_text(ctx, job)
    assert wrapper.count(german) == 1 and english not in wrapper and untranslated in wrapper
    assert r"\decklanguage[de]" in wrapper and job.jobname == "course-instructor"
    assert replace(job, language="EN").jobname == "course-instructor-en"
    chapter = compiler.wrapper_text(ctx, replace(job, chapter=d.chapters[0]))
    assert german in chapter and untranslated not in chapter
    appendix = compiler.wrapper_text(ctx, replace(job, appendix_toc=True))
    assert r"\hyperlink{ddd}" in appendix and r"\hyperlink{aaa}" not in appendix
    independent = compiler.wrapper_text(ctx, replace(job, resolve_translations=False))
    assert german in independent and english in independent
    assert d.path.read_bytes() == before


def test_commented_and_verbatim_calls_are_preserved_and_do_not_hide_a_real_partner(ctx, project):
    d = deck(project, "% \\slide{aaa-EN-One}\n"
                     "\\begin{verbatim}\n\\slide{aaa-EN-One}\n\\end{verbatim}\n"
                     "\\slide{ddd-DE-Eins}\n")
    assert len(deck_language.deck_slots(ctx, d, "DE")) == 1
    assert deck_language.resolved_text(ctx, d, "DE") == d.text

    from slidemage import slide_branch, slide_versioning

    # The live call and both masked examples now name the same slide.
    gap = " % example: " + r"\slide{aaa-EN-One}" + "\r\n"
    live = r"\slide" + gap + "{aaa-EN-One}"
    raw = d.text.replace(r"\end{verbatim}", "\\slide{\n" + r"\end{verbatim}")
    raw = raw.replace(r"\slide{ddd-DE-Eins}", live + r"  \verb|\slide{aaa-EN-One}|")
    d.path.write_bytes(raw.encode())
    current = ctx.slides_dir / "aaa-EN-One-current.tex"
    base = ctx.slides_dir / "aaa-EN-One-v7-3-1.tex"
    base.write_bytes(current.read_bytes())
    current.write_bytes(current.read_bytes() + b"% changed\n")
    cap = slide_versioning.capture(ctx, "new_slide", [current])
    patch = slide_versioning.patch_edits(cap, current, "patch", {d.path: "keep"})
    assert patch[d.path] == (raw, raw.replace(live, r"\slideversion" + gap + "{aaa-EN-One}{7-3-1}"))
    branch = slide_branch.branch(cap, current, ctx.slide_ids_csv, "Copy", [d.path])
    assert branch.edits[d.path] == (raw, raw.replace(live, r"\slide" + gap + f"{{{branch.created.id_slug}}}"))


@pytest.mark.parametrize("command", ["includegraphics", "includeonly", "includepdf", "inputencoding"])
def test_other_commands_are_not_body_fragments(ctx, project, command):
    (project / "decks" / "x.tex").write_text("\\slide{aaa-EN-One}\n")
    d = deck(project, f"\\{command}{{x}}\n")
    resolved, dependencies = deck_language.compile_deck(ctx, d, "DE")
    assert resolved.text == d.text and dependencies == []
    assert compile_progress.count_job_slides(ctx, d, "instructor", None, "DE") == 0
    assert latex_lint.check_deck_job(ctx, d, language="DE").files_checked == 1


def test_precompile_check_checks_the_german_file_instead_of_the_english_file(ctx, project):
    (project / "slides" / "ddd-DE-Eins-current.tex").write_text(
        "%% Translation of: aaa-EN-One\n\\begin{standardframe}{Titel}{broken\\end{standardframe}\n")
    d = deck(project, "\\slide{aaa-EN-One}\n")
    en = latex_lint.check_jobs(ctx, [compiler.CompileJob(d, None, None, language="EN")])
    de = latex_lint.check_jobs(ctx, [compiler.CompileJob(d, None, None, language="DE")])
    assert not en.errors
    assert de.errors and all(i.path.name == "ddd-DE-Eins-current.tex" for i in de.errors)


# Each call form once; the gap rotates through space, tab and newline.
@pytest.mark.parametrize("source,suffix", [
    ("\\slide\n{bbb-EN-Two}", "current"),
    ("\\omitslideversion\t{bbb-EN-Two} {1-0-0}", "v1-0-0"),
    ("\\slidestep {bbb-EN-Two}\n[instructor]\t{1}", "current"),
])
def test_spaced_calls_keep_slides_used_and_update_headers(ctx, project, source, suffix):
    deck(project, source + "\n")
    filename = f"bbb-EN-Two-{suffix}.tex"
    (ctx.slides_dir / filename).write_text("Slide content\n")
    assert unused_content.find_used_slide_filenames(ctx) == {filename}
    assert filename not in {p.name for p in unused_content.find_unused_slides(ctx)}
    deck_headers.regenerate_headers(ctx)
    assert "%% Included in decks: course" in (ctx.slides_dir / "bbb-EN-Two-current.tex").read_text()


def test_cleanup_keeps_explicit_pins_of_folded_translations(ctx, project):
    filename = "ddd-DE-Eins-v2-0-0.tex"
    (ctx.slides_dir / filename).write_text("Pinned German slide\n")
    deck(project, "\\slideversion {aaa-EN-One} {1-0-0}\n\\omitslideversion\n{ddd-DE-Eins}\n{2-0-0}\n")
    assert unused_content.find_used_slide_filenames(ctx) == {
        "aaa-EN-One-v1-0-0.tex", "aaa-EN-One-current.tex", "ddd-DE-Eins-current.tex", filename}
    assert filename not in {p.name for p in unused_content.find_unused_slides(ctx)}


@pytest.mark.parametrize("location,command,suffix", [
    (0, "input", ""), (1, "include", ".tex"), (2, "input", ".tex"),
])
def test_nested_fragments_preserve_lookup_order_sources_and_dependencies(ctx, project, location, command, suffix):
    nested = ctx.decks_dir / "nested"
    nested.mkdir()
    fragment = nested / "list.tex"
    fragment_text = rf"\{command}{{choice{suffix}}}" + "\n"
    fragment.write_text(fragment_text)
    candidates = [ctx.decks_dir / "choice.tex", project / "choice.tex", nested / "choice.tex"]
    for i, path in enumerate(candidates[location:], location):
        path.write_text(rf"\section{{Choice {i}}}\slide{{aaa-EN-One}}\slide{{ddd-DE-Eins}}" + "\n")
    include = rf"\{command}{{nested/list{suffix}}}"
    d = deck(project, "\\slide{ccc-mult-Three}\n" + include + "\n")

    resolved, dependencies = deck_language.compile_deck(ctx, d, "DE")
    assert f"\\section{{Choice {location}}}" in resolved.text
    assert resolved.text.count(r"\slide{ddd-DE-Eins}") == 1 and include not in resolved.text
    assert set(dependencies) == {
        fragment, candidates[location], ctx.slides_dir / "aaa-EN-One-current.tex",
        ctx.slides_dir / "ddd-DE-Eins-current.tex",
    }
    assert fragment.read_text() == fragment_text
    assert compile_progress.count_job_slides(ctx, d, "instructor", None, "DE") == 2
    wrapper = compiler.wrapper_text(ctx, compiler.CompileJob(d, "after-course", None, resolve_translations=False))
    assert include in wrapper and r"\slide{ddd-DE-Eins}" not in wrapper


def test_slidestep_slide_counts_as_used():
    unused = {p.name for p in unused_content.find_unused_slides(EXAMPLE_PROJECT)}
    assert "1mu-EN-Slidestep-Demo-current.tex" not in unused


def test_slideblock_expands_to_the_same_calls_as_inline(ctx, project):
    ctx.slide_ids_csv.write_text('"id"\n')
    ctx.blocks_dir.mkdir()
    calls = (
        "\\slide{aaa-EN-One}\n"
        "\\slideversion{aaa-EN-One}{1-0-0}\n"
        "\\omitslide{bbb-EN-Two}\n"
        "\\omitslideversion{aaa-EN-One}{1-0-0}\n"
        "\\slidefinal{ccc-mult-Three}\n"
        "\\conditionalslide[instructor]{bbb-EN-Two}\n"
        "\\slidestep{ccc-mult-Three}[during-course]{1,2}"
    )
    block = ctx.blocks_dir / "topic.tex"
    write_test_file(block, calls + "% trailing comment")
    inline = deck(project, "\\section{Topic}\n" + calls + "\n")
    path = ctx.archive_dir / "linked.tex"
    path.parent.mkdir(exist_ok=True)
    write_test_file(path, inline.text.replace(calls, r"\slideblock{topic}"))
    linked = deck_scan.read_deck(path)
    before = path.read_bytes(), block.read_bytes()

    expanded, dependencies = deck_language.expand_fragments(linked, strict_includes=True)

    assert [(deck_language.call_text(c), c.chapter.title) for c in deck_language.active_calls(expanded)] == [
        (deck_language.call_text(c), c.chapter.title) for c in deck_language.active_calls(inline)]
    assert dependencies == [block]
    for language in ("EN", "DE"):
        assert [deck_language.call_text(s.call) for s in deck_language.deck_slots(ctx, expanded, language)] == [
            deck_language.call_text(s.call) for s in deck_language.deck_slots(ctx, inline, language)]
    assert (path.read_bytes(), block.read_bytes()) == before
