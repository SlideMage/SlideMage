# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image descriptions per language (content languages plan, 2.4): store version 3, its conversion from
version 2, the compile CSV's columns, the fallback chain and translations into any language."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess

import pytest

from slidemage import alt_draft, alt_images, image_review, languages
from slidemage.alt_images import ImageEntry, ImageText, SlideUse

IMG = "media/photo-a.png"
VERSION_2 = {"version": 2, "images": {IMG: {
    "role": "informative", "status": "reviewed", "short": "A chart.", "long": "A long chart.",
    "source": "Source: Own.", "takeaway_default": "Rates rise.", "drafted_by": "qwen",
    "short_de": "Ein Diagramm.", "long_de": "Ein langes Diagramm.", "takeaway_default_de": "Zinsen steigen.",
    "translated_from_hash": "abc123abc123",
    "used_on": {"s1": {"takeaway": "Here.", "reviewed": "2026-10-01", "hash": "h1", "takeaway_de": "Hier."}},
}}, "slides": {"s1": {"summary": "About rates."}}}


@pytest.fixture
def ctx(tmp_path):
    from slidemage.project import ProjectContext
    context = ProjectContext.at(tmp_path)
    context.media_dir.mkdir(parents=True)
    return context


def write_store(ctx, raw) -> None:
    (ctx.media_dir / "alt-text.json").write_text(json.dumps(raw), encoding="utf-8")


def test_a_version_2_entry_reads_as_english_and_german(ctx):
    write_store(ctx, VERSION_2)
    entry = alt_images.load_store(ctx)[IMG]
    assert entry.texts["en"] == ImageText("A chart.", "A long chart.", "Rates rise.", "Source: Own.", "reviewed")
    assert entry.texts["de"] == ImageText("Ein Diagramm.", "Ein langes Diagramm.", "Zinsen steigen.", "", "auto",
                                          "en", "abc123abc123")
    assert (entry.short_de, entry.translated_from_hash, entry.drafted_by) == ("Ein Diagramm.", "abc123abc123", "qwen")
    assert entry.used_on["s1"].takeaways == {"en": "Here.", "de": "Hier."}


def test_conversion_writes_version_3_keeps_a_backup_and_reads_back_the_same(ctx):
    write_store(ctx, VERSION_2)
    before = alt_images.load_store(ctx)
    assert alt_images.convert_store(ctx)
    raw = json.loads((ctx.media_dir / "alt-text.json").read_text(encoding="utf-8"))
    assert raw["version"] == 3 and raw["slides"] == VERSION_2["slides"]
    assert raw["images"][IMG]["text"]["de"]["translated_from"] == "en"
    assert raw["images"][IMG]["used_on"]["s1"]["takeaway"] == {"de": "Hier.", "en": "Here."}
    assert "short_de" not in raw["images"][IMG]
    assert json.loads((ctx.media_dir / "alt-text.v2.json").read_text(encoding="utf-8")) == VERSION_2
    assert alt_images.load_store(ctx) == before
    assert not alt_images.convert_store(ctx)          # once only


def test_the_backup_is_never_overwritten(ctx):
    write_store(ctx, VERSION_2)
    (ctx.media_dir / "alt-text.v2.json").write_text("older backup", encoding="utf-8")
    alt_images.convert_store(ctx)
    assert (ctx.media_dir / "alt-text.v2.json").read_text(encoding="utf-8") == "older backup"


def test_the_text_falls_back_along_its_chain():
    entry = ImageEntry(IMG, texts={
        "en": ImageText("EN short", "EN long", source="EN source"),
        "fr": ImageText("FR short", "FR long", translated_from="en"),
        "it": ImageText(source="IT source", translated_from="fr"),
    })
    assert entry.text_for("fr").short == "FR short"
    assert entry.text_for("it").short == "FR short"                 # it was translated from French
    assert entry.text_for("es", main="fr").short == "FR short"      # no Spanish: the main language
    assert entry.text_for("es").short == "EN short"
    assert (entry.source_in("fr"), entry.source_in("it"), entry.source_in("es")) == ("EN source", "IT source", "EN source")


def test_a_takeaway_is_per_language_and_falls_back_only_to_its_own_default():
    entry = ImageEntry(IMG, texts={"en": ImageText(takeaway_default="EN"), "fr": ImageText(takeaway_default="FR")},
                       used_on={"s1": SlideUse(takeaways={"fr": "FR here"}), "s2": SlideUse()})
    assert (entry.takeaway_in("s1", "fr"), entry.takeaway_in("s2", "fr"), entry.takeaway_in("s1", "en")) == (
        "FR here", "FR", "EN")
    assert entry.takeaway_in("s1", "it") == ""


def test_a_translation_into_french_is_stale_once_the_english_changes(ctx):
    entry = ImageEntry(IMG, short="A chart.", long="A long chart.")
    assert alt_images.translation_state(entry, "fr") == alt_images.STATE_NONE
    alt_images.save_store(ctx, {IMG: entry})
    result = alt_draft.TranslationResult("Un graphique.", "Un long graphique.", "", source_hash=alt_images.en_text_hash(entry),
                                         language="fr")
    assert alt_draft.apply_one_translation(ctx, IMG, result, "model")
    stored = alt_images.load_store(ctx)[IMG]
    assert stored.texts["fr"].short == "Un graphique." and stored.texts["fr"].translated_from == "en"
    assert alt_images.translation_state(stored, "fr") == alt_images.STATE_REVIEWED
    assert alt_images.translation_state(stored, "de") == alt_images.STATE_NONE
    stored.long = "A changed chart."
    assert alt_images.translation_state(stored, "fr") == alt_images.STATE_STALE


def test_a_batch_translates_into_each_language_and_a_german_only_backend_refuses_french(ctx):
    alt_images.save_store(ctx, {IMG: ImageEntry(IMG, short="A chart.", long="A long chart.")})

    class Backend:          # a route's backend from before languages other than German: no target_lang
        label = "plugin"

        def translate(self, entry):
            return alt_draft.TranslationResult("Ein Diagramm.", "Ein langes Diagramm.", "",
                                               source_hash=alt_images.en_text_hash(entry))

    queues = alt_draft.translation_queues(ctx, ["de", "fr"])
    assert queues == {"de": [IMG], "fr": [IMG]}
    summary = alt_draft.run_translation_batches(ctx, queues, Backend())
    assert summary.written == 1 and summary.stopped_early and "German only" in summary.errors[0]
    assert set(alt_images.load_store(ctx)[IMG].texts) == {"en", "de"}


def test_a_model_backend_is_given_the_target_language(ctx):
    backend = alt_draft.ModelTranslationBackend(ctx, provider=None)
    assert alt_draft.for_language(backend, "fr").target_lang == "fr" and backend.target_lang == "de"


def test_the_compile_csv_appends_the_projects_other_languages(ctx):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    alt_images.save_store(ctx, {IMG: ImageEntry(IMG, texts={
        "en": ImageText("EN short", source="EN source"), "fr": ImageText("FR short", translated_from="en")})})
    rows = list(csv.reader((ctx.media_dir / "alt-text.csv").open(encoding="utf-8")))
    assert rows[0] == ["image", "role", "status_en", "short_alt_en", "source_en", "status_de", "short_alt_de",
                       "source_de", "status_fr", "short_alt_fr", "source_fr"]
    row = rows[1]
    assert (row[3], row[4], row[6], row[7]) == ("EN short", "EN source", "", "EN source")   # where an older Lua reads
    assert row[9:] == ["FR short", "EN source"]


@pytest.mark.skipif(shutil.which("texlua") is None, reason="needs texlua")
def test_the_lua_reads_the_columns_by_name(ctx, tmp_path):
    languages.set_project_languages(ctx, "en", ["de", "fr"])
    alt_images.save_store(ctx, {IMG: ImageEntry(IMG, texts={
        "en": ImageText("EN short", source="EN source"), "fr": ImageText("FR short", source="FR source")})})
    script = tmp_path / "check.lua"
    script.write_text(
        'tex = { sprint = function(s) print(s) end }\n'
        f'dofile([[{alt_images.__file__.rsplit("src", 1)[0]}latex/SlideMage_alt.lua]])\n'
        'slidemage_alt.load()\n'
        'slidemage_alt.altText("media/photo-a.png", "fr")\n'
        'slidemage_alt.altText("media/photo-a.png", "it")\n'
        'slidemage_alt.recordSource("media/photo-a.png", "fr")\n'
        'slidemage_alt.recordSource("media/photo-a.png", "it")\n'
        'print(table.concat(slidemage_alt.frame_sources, "|"))\n', encoding="utf-8")
    out = subprocess.run(["texlua", str(script)], cwd=ctx.root, capture_output=True, text=True, timeout=60).stdout
    assert out.splitlines() == ["\\SMAltHasTexttrue\\def\\SMAltShort{FR short}", "FR source|EN source"]


def test_the_review_filter_looks_for_the_language_shown():
    assert image_review.translation_languages(("en", "de", "fr"), "fr") == ("fr",)
    assert image_review.translation_languages(("en", "de", "fr"), "en") == ("de", "fr")
    entry = ImageEntry(IMG, short="A chart.", long="Long.", short_de="Ein Diagramm.", long_de="Lang.")
    assert not image_review.lacks_translation(entry, "de") and image_review.lacks_translation(entry, "fr")


def test_a_form_edits_the_second_language_it_shows():
    entry = ImageEntry(IMG, short="A chart.", long="Long.")
    baseline = image_review.form_baseline(entry, "s1", "fr")
    values = {**baseline, "short_tr": "Un graphique.", "long_tr": "Long.", "source_tr": "Source FR"}
    image_review.apply_form_edit(entry, "s1", image_review.FormEdit(IMG, values, baseline,
                                                                    alt_images.en_text_hash(entry), language="fr"))
    assert entry.texts["fr"].short == "Un graphique." and entry.texts["fr"].source == "Source FR"
    assert "de" not in entry.texts and alt_images.translation_state(entry, "fr") == alt_images.STATE_REVIEWED
    assert entry.source_status == alt_images.SOURCE_TO_REVIEW


def test_a_text_written_without_english_is_its_own_not_a_translation():
    entry = ImageEntry(IMG)
    baseline = image_review.form_baseline(entry, "s1", "fr")
    values = {**baseline, "short_tr": "Un graphique.", "long_tr": "Long."}
    image_review.apply_form_edit(entry, "s1", image_review.FormEdit(IMG, values, baseline,
                                                                    alt_images.en_text_hash(entry), language="fr"))
    assert (entry.texts["fr"].translated_from, entry.texts["fr"].from_hash) == ("", "")
    assert alt_images.translation_state(entry, "fr") == alt_images.STATE_REVIEWED
    entry.short, entry.long = "A chart.", "Long."           # English written later: the French stays its own
    assert alt_images.translation_state(entry, "fr") == alt_images.STATE_REVIEWED


def test_an_image_described_only_in_another_language_says_its_english_is_missing():
    none = alt_images.STATE_NONE
    assert alt_images.state_label(none, [ImageEntry(IMG), None]) == "No description"
    assert alt_images.state_label(none, [ImageEntry(IMG, texts={"fr": ImageText("Un graphique.")})]) == (
        "No English description")
    assert alt_images.state_label(alt_images.STATE_DRAFT, [ImageEntry(IMG, short="A chart.")]) == "Draft, unreviewed"

