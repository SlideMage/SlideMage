# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The persistent image process, including error recovery and frozen dispatch."""

import os
import subprocess
import sys

import pymupdf
import pytest

from slidemage import cli, preview_raster, preview_raster_client


def pdf_bytes(text="one"):
    with pymupdf.open() as doc:
        page = doc.new_page(width=320, height=180)
        page.insert_text((30, 30), text)
        return doc.tobytes()


@pytest.mark.parametrize("failure", ["bad_pdf", "crash"])
def test_helper_reuses_one_process_and_recovers_from_failure(failure):
    client = preview_raster_client._shared
    client.close()
    data = pdf_bytes()
    first = client.render(data, ((160, 90), (160, None)), (160, 90))
    process = client._process
    assert process.pid != os.getpid()
    assert first[0] == first[1]
    assert client.render(data, ((160, 90),), (160, 90))[0] == first[0]
    assert client._process is process
    if failure == "bad_pdf":
        with pytest.raises(RuntimeError, match="Cannot prepare preview images"):
            client.render(b"not a pdf", ((160, None),), (160, 90))
        assert client._process is None
        assert client.render(data, ((160, 90),), (160, 90))[0] == first[0]
    else:
        process.kill()
        process.wait()
        assert client.render(pdf_bytes("different"), ((160, 90),), (160, 90))
    assert client._process is not process


def test_image_process_flag_dispatches_before_gui_or_project_setup(monkeypatch):
    seen = []
    monkeypatch.setattr(preview_raster, "serve", lambda: seen.append("raster"))
    monkeypatch.setattr(cli, "_prepare_gui", lambda root: pytest.fail("opened GUI"))
    cli.main(["--preview-raster"])
    assert seen == ["raster"]


def test_frozen_dispatch_uses_the_same_executable_without_starting_a_window(tmp_path):
    from types import SimpleNamespace
    import base64
    import io
    import json
    from unittest.mock import patch

    client = preview_raster_client._shared
    client.close()
    image = preview_raster.raster(pdf_bytes(), ((160, 90),), (160, 90))[0]
    commands = []

    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(
            stdin=io.StringIO(),
            stdout=io.StringIO(
                json.dumps(dict(ok=True, images=[base64.b64encode(image).decode()]))
                + "\n"
            ),
            poll=lambda: None,
            wait=lambda **kw: 0,
            kill=lambda: None,
        )

    with (
        patch.object(sys, "frozen", True, create=True),
        patch.object(client.subprocess, "Popen", popen),
    ):
        assert client.render(pdf_bytes(), ((160, 90),), (160, 90)) == (image,)
        client.close()
    assert commands[0][0] == [sys.executable, "--preview-raster"]
    assert commands[0][1]["env"]["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] == "1"


def test_windowed_helper_restores_redirected_pipes_when_standard_streams_are_none(
    monkeypatch,
):
    import base64
    import io
    import json

    request = (
        json.dumps(
            dict(
                pdf=base64.b64encode(pdf_bytes()).decode(),
                sizes=[[160, 90]],
                full_size=[160, 90],
            )
        )
        + "\n"
    )
    incoming, outgoing = io.StringIO(request), io.StringIO()
    monkeypatch.setattr(
        preview_raster,
        "_pipe_stream",
        lambda fd, mode: incoming if fd == 0 else outgoing,
    )
    # Monkeypatch context restores pytest's streams before it reports results.
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", None)
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        preview_raster.serve()
    response = json.loads(outgoing.getvalue())
    assert response["ok"] and len(response["images"]) == 1


@pytest.mark.parametrize("reads_input", [True, False])
def test_unresponsive_helper_is_killed_reaped_and_next_request_recovers(monkeypatch, reads_input):
    client = preview_raster_client._shared
    client.close()
    # Exercise both a stalled response and a full request pipe.
    script = "import sys,time; " + ("sys.stdin.readline(); " if reads_input else "") + "time.sleep(60)"
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    )
    client._process = process
    monkeypatch.setattr(client, "REQUEST_TIMEOUT", .15)
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            client.render(b"x" * (1024 * 1024), ((160, 90),), (160, 90))
        assert process.poll() is not None and client._process is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
    monkeypatch.setattr(client, "REQUEST_TIMEOUT", 15)
    assert client.render(pdf_bytes(), ((160, 90),), (160, 90))


@pytest.mark.parametrize("response", [
    [], {"ok": "yes", "images": []}, {"ok": True, "images": []},
    {"ok": True, "images": ["not base64"]},
    {"ok": True, "images": ["bm90IGEgcG5n"]},
])
def test_invalid_protocol_response_is_rejected_and_helper_closed(monkeypatch, response):
    from types import SimpleNamespace
    import io
    import json
    client = preview_raster_client._shared
    client.close()
    client._process = SimpleNamespace(
        stdin=io.StringIO(), stdout=io.StringIO(json.dumps(response) + "\n"),
        poll=lambda: None, wait=lambda **kw: 0, kill=lambda: None,
    )
    with pytest.raises(RuntimeError, match="Cannot prepare preview images"):
        client.render(pdf_bytes(), ((160, 90),), (160, 90))
    assert client._process is None


def sequence_pdf(pages):
    with pymupdf.open() as doc:
        for text, width, height in pages:
            page = doc.new_page(width=width, height=height)
            page.insert_text((30, 30), text)
        return doc.tobytes()


def test_sequence_signature_checks_all_reveals_order_count_and_dimensions():
    base = [('first', 320, 180), ('last', 320, 180)]
    first = preview_raster_client.render_sequence(sequence_pdf(base))
    assert len(first['images']) == len(first['pages']) == 2
    assert preview_raster_client.render_sequence(sequence_pdf(base)) == first
    assert first['pages'][0]['size'] == [320.0, 180.0]
    for other in (
        [('changed first', 320, 180), base[-1]],
        list(reversed(base)),
        [base[-1]],
        [('first', 321, 180), base[-1]],
        [('first footer during-course 2', 320, 180), base[-1]],
    ):
        rendered = preview_raster_client.render_sequence(sequence_pdf(other))
        assert rendered['signature'] != first['signature']
        # Same last-page pixels cannot establish complete-preview equality.
        if other[-1] == base[-1]:
            assert rendered['images'][-1] == first['images'][-1]


@pytest.mark.parametrize('field,value', [('schema', 999), ('dpi', 72), ('alpha', True)])
def test_sequence_client_rejects_incompatible_configuration(monkeypatch, field, value):
    response = preview_raster.sequence(pdf_bytes())
    response['configuration'][field] = value
    monkeypatch.setattr(preview_raster_client, '_ask', lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match='configuration'):
        preview_raster_client.render_sequence(pdf_bytes())


def test_fit_size_keeps_the_page_aspect_inside_the_box():
    import io
    from PIL import Image

    with pymupdf.open() as doc:
        doc.new_page(width=200, height=400)         # taller than the 16:9 box
        data = doc.tobytes()
    wide, tall = preview_raster.raster(pdf_bytes(), [(320, 180, "fit")], (1920, 1080)), \
        preview_raster.raster(data, [(320, 180, "fit")], (1920, 1080))
    assert Image.open(io.BytesIO(wide[0])).size == (320, 180)
    assert Image.open(io.BytesIO(tall[0])).size == (90, 180)
