# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import json

from slidemage import deck_context


def test_read_inputs_accepts_utf8_names_and_rejects_missing_or_broken_records(tmp_path):
    pdf = tmp_path / "deck.pdf"
    assert deck_context.read_inputs(pdf) is None
    for broken in ("{not json", "{}", "[1, 2]"):
        deck_context.inputs_path(pdf).write_text(broken, encoding="utf-8")
        assert deck_context.read_inputs(pdf) is None
    deck_context.inputs_path(pdf).write_bytes(b"\xff\xfe\x00bad")
    assert deck_context.read_inputs(pdf) is None

    names = ["C:/Folien/Übersicht.tex", "b.tex"]
    deck_context.inputs_path(pdf).write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    assert deck_context.inputs_path(pdf).name == "deck.inputs.json"
    assert deck_context.read_inputs(pdf) == names


def test_a_failing_compile_listener_is_logged_with_its_traceback(caplog, tmp_path):
    from slidemage import compiler

    def broken(ctx, job, pdf):
        raise RuntimeError("listener boom")

    with caplog.at_level("ERROR", logger="slidemage.compile"):
        compiler._notify_listener(broken, None, None, tmp_path / "a.pdf")
    assert any(r.exc_info and "listener boom" in str(r.exc_info[1]) for r in caplog.records)
