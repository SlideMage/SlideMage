"""The Claude Code backends of the image pipeline (ai/claude_images.py) with the fake `claude -p`: a description
and a translation go through alt_draft's own apply_one_draft / apply_one_translation and batches, the image
reaches the process inline, and a draft is labelled "Claude <model>". The project is a throwaway one."""
from __future__ import annotations

import base64
import json
import struct
import threading
import zlib

from test_claude_runner import claude  # noqa: F401 -- a fixture

from conftest import use_project
from slidemage import alt_blocks, alt_draft, alt_images, translation_prompts
from slidemage.ai import claude_images



def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


# a 1x1 grey picture
PNG = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
       + _png_chunk(b"IDAT", zlib.compress(b"\x00\x80")) + _png_chunk(b"IEND", b""))
ANSWER = {"short": "A bar chart.", "long": "Two bars: A is higher than B.", "takeaway": "A beats B.",
          "role_suggestion": "informative"}
GERMAN = {"short_de": "Ein Balkendiagramm.", "long_de": "Zwei Balken: A ist höher als B.", "takeaway_de": "A schlägt B."}


def add_pictures(monkeypatch, root, **entries):
    """Put the images `entries` (name -> fields of the store entry) into the throwaway project: the files in media/,
    the store and the text of slide abc. Returns the slide's file."""
    use_project(monkeypatch, root)
    (root / "media").mkdir(exist_ok=True)
    slide = root / "slides" / "abc-EN-Hello-current.tex"
    text = slide.read_bytes().decode()
    for name, fields in entries.items():
        (root / "media" / f"{name}.png").write_bytes(PNG)
        text = text.replace("\\end{standardframe}", f"\t\\includegraphics{{media/{name}.png}}\r\n\\end{{standardframe}}")
        alt_images.update_store(lambda e, n=name, f=fields: e.update({f"media/{n}.png": alt_images.ImageEntry(
            image=f"media/{n}.png", **f)}) or True)
    slide.write_bytes(text.encode())
    return slide


def test_a_description_is_a_draft_of_the_existing_pipeline(root, claude, monkeypatch):  # noqa: F811
    slide = add_pictures(monkeypatch, root, chart={})
    claude.script({"answer": ANSWER})
    backend = claude_images.ClaudeDraftBackend(claude.path)
    context = alt_draft.build_context(slide, "media/chart.png")
    result = backend.draft(root / "media" / "chart.png", context)
    assert result.ok and backend.label == result.model == "Claude sonnet"
    assert alt_draft.apply_one_draft("media/chart.png", result, backend.label)
    entry = alt_images.load_store()["media/chart.png"]
    assert (entry.short, entry.long, entry.takeaway_default) == (ANSWER["short"], ANSWER["long"], ANSWER["takeaway"])
    assert entry.drafted_by == "Claude sonnet" and entry.status != alt_images.STATUS_REVIEWED
    (call,) = claude.calls()
    flags = call["argv"]
    assert call["request"] == alt_draft.build_prompt(context)
    assert call["images"] == [{"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()}]
    assert flags[flags.index("--system-prompt") + 1] == alt_draft.effective_system_prompt()
    assert json.loads(flags[flags.index("--json-schema") + 1]) == alt_draft.RESPONSE_SCHEMA


def test_a_reviewed_description_is_not_overwritten(root, claude, monkeypatch):  # noqa: F811
    slide = add_pictures(monkeypatch, root, chart=dict(short="mine", long="mine", status=alt_images.STATUS_REVIEWED))
    claude.script({"answer": ANSWER})
    backend = claude_images.ClaudeDraftBackend(claude.path, "haiku")
    result = backend.draft(root / "media" / "chart.png", alt_draft.build_context(slide, "media/chart.png"))
    assert not alt_draft.apply_one_draft("media/chart.png", result, backend.label)
    assert alt_images.load_store()["media/chart.png"].long == "mine"
    assert claude.calls()[0]["argv"][:3] == ["-p", "--model", "haiku"]


def test_a_value_table_that_looks_interpolated_is_removed(root, claude, monkeypatch):  # noqa: F811
    slide = add_pictures(monkeypatch, root, chart={})
    table = "\n".join(f"| Country {i} | {5 * i}% |" for i in range(1, 11))
    claude.script({"answer": {**ANSWER, "long": "Bars by country.\n\n" + table}})
    result = claude_images.ClaudeDraftBackend(claude.path).draft(
        root / "media" / "chart.png", alt_draft.build_context(slide, "media/chart.png"))
    assert result.suspected_fabrication and "Country 3" not in result.long and "removed automatically" in result.long


def test_a_failed_process_and_an_unreadable_format_are_errors_of_the_draft(root, claude, monkeypatch):  # noqa: F811
    slide = add_pictures(monkeypatch, root, chart={})
    claude.script({"error": "Not logged in · Please run /login"})
    backend = claude_images.ClaudeDraftBackend(claude.path)
    context = alt_draft.build_context(slide, "media/chart.png")
    result = backend.draft(root / "media" / "chart.png", context)
    assert not result.ok and "not logged in" in result.error
    bitmap = root / "media" / "scan.bmp"
    bitmap.write_bytes(PNG)
    result = backend.draft(bitmap, context)
    assert not result.ok and ".bmp" in result.error and len(claude.calls()) == 1


def test_stop_ends_the_running_process_and_the_batch(root, claude, monkeypatch, tmp_path):  # noqa: F811
    slide = add_pictures(monkeypatch, root, a={}, b={})
    claude.script({"answer": ANSWER, "delay": 3, "marker": str(tmp_path / "late")})
    backend = claude_images.ClaudeDraftBackend(claude.path)
    jobs = alt_draft.slide_jobs(alt_blocks.SlideRow(slide, "abc", "", ["media/a.png", "media/b.png"]), alt_images.load_store())
    threading.Timer(0.5, backend.cancel.set).start()
    summary = alt_draft.run_batch(jobs, backend, should_stop=backend.cancel.is_set)
    assert (summary.written, summary.attempted, summary.stopped_early) == (0, 1, True)
    assert len(claude.calls()) == 1 and not (tmp_path / "late").exists()
    assert not alt_images.load_store()["media/a.png"].short


def test_a_batch_over_a_slide_counts_what_failed(root, claude, monkeypatch):  # noqa: F811
    slide = add_pictures(monkeypatch, root, a={}, b={})
    claude.script({"answer": ANSWER}, {"error": "overloaded"})
    jobs = alt_draft.slide_jobs(alt_blocks.SlideRow(slide, "abc", "", ["media/a.png", "media/b.png"]), alt_images.load_store())
    summary = alt_draft.run_batch(jobs, claude_images.ClaudeDraftBackend(claude.path))
    assert (summary.attempted, summary.written, summary.errors) == (2, 1, ["media/b.png: overloaded"])


def test_a_translation_is_a_draft_of_the_existing_pipeline(root, claude, monkeypatch):  # noqa: F811
    add_pictures(monkeypatch, root, chart=dict(short="A bar chart.", long="Two bars.", takeaway_default="A wins."))
    claude.script({"answer": GERMAN})
    backend = claude_images.ClaudeTranslationBackend(claude.path)
    entry = alt_images.load_store()["media/chart.png"]
    result = backend.translate(entry)
    assert result.ok and result.source_hash == alt_images.en_text_hash(entry)
    assert alt_draft.apply_one_translation("media/chart.png", result, backend.label)
    entry = alt_images.load_store()["media/chart.png"]
    assert (entry.short_de, entry.long_de, entry.takeaway_default_de) == tuple(GERMAN.values())
    assert alt_images.translation_state(entry) == alt_images.STATE_REVIEWED
    (call,) = claude.calls()
    flags = call["argv"]
    assert "--input-format" not in flags and call["images"] == []
    assert all(text in call["request"] for text in ("A bar chart.", "Two bars.", "A wins."))
    assert flags[flags.index("--system-prompt") + 1] == translation_prompts.get_effective_prompt("sonnet", "en", "de").prompt


def test_a_translation_of_text_that_changed_meanwhile_is_not_written(root, claude, monkeypatch):  # noqa: F811
    add_pictures(monkeypatch, root, chart=dict(short="s", long="Two bars."))
    claude.script({"answer": GERMAN})
    result = claude_images.ClaudeTranslationBackend(claude.path).translate(alt_images.load_store()["media/chart.png"])
    alt_images.update_store(lambda e: setattr(e["media/chart.png"], "long", "Three bars.") or True)
    assert not alt_draft.apply_one_translation("media/chart.png", result, "Claude sonnet")


def test_a_translation_batch_counts_what_failed(root, claude, monkeypatch):  # noqa: F811
    add_pictures(monkeypatch, root, a=dict(long="One."), b=dict(long="Two."))
    claude.script({"answer": GERMAN}, {"exit": 1})
    summary = alt_draft.run_translation_batch(
        ["media/a.png", "media/b.png"], claude_images.ClaudeTranslationBackend(claude.path))
    assert (summary.attempted, summary.written) == (2, 1) and "media/b.png" in summary.errors[0]
