from __future__ import annotations

import io
import json
import urllib.error


def _install_ollama(monkeypatch, show_body, *, create_error=None):
    from slidemage import alt_draft

    requests = []

    class FakeResponse:
        def __init__(self, body):
            self.body = json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/api/show"):
            return FakeResponse(show_body)
        if request.full_url.endswith("/api/create"):
            if create_error is not None:
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=io.BytesIO(json.dumps({"error": create_error}).encode("utf-8")),
                )
            return FakeResponse({"status": "success"})
        raise AssertionError(f"unexpected Ollama endpoint: {request.full_url}")

    monkeypatch.setattr(alt_draft.urllib.request, "urlopen", fake_urlopen)
    return requests


def test_applying_translation_clears_empty_german_takeaway(tmp_path, monkeypatch):
    from slidemage import alt_draft, alt_images

    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(alt_images, "STORE_PATH", media / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", media / "alt-text.csv")

    entry = alt_images.ImageEntry(
        image="media/chart.png",
        short="English short",
        long="English long",
        takeaway_default="",
        takeaway_default_de="Old German takeaway",
    )
    source_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({entry.image: entry})

    written = alt_draft.apply_one_translation(
        entry.image,
        alt_draft.TranslationResult(
            short_de="Kurzer Text",
            long_de="Langer Text",
            takeaway_de="",
            source_hash=source_hash,
        ),
        "test model",
    )

    current = alt_images.load_store()[entry.image]
    assert written is True
    assert current.takeaway_default_de == ""
    assert current.translated_from_hash == source_hash
    assert alt_images.translation_state(current) == alt_images.STATE_REVIEWED


def test_applying_translation_still_rejects_a_stale_source_hash(tmp_path, monkeypatch):
    from slidemage import alt_draft, alt_images

    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(alt_images, "STORE_PATH", media / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", media / "alt-text.csv")

    entry = alt_images.ImageEntry(
        image="media/chart.png",
        short="English short",
        long="Original English",
        takeaway_default="English takeaway",
        long_de="Previous German",
        takeaway_default_de="Previous takeaway",
    )
    old_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({entry.image: entry})

    def edit_english(entries):
        entries[entry.image].long = "Edited English"
        return True

    alt_images.update_store(edit_english)

    written = alt_draft.apply_one_translation(
        entry.image,
        alt_draft.TranslationResult(
            short_de="Neuer kurzer Text",
            long_de="Neue deutsche Übersetzung",
            takeaway_de="",
            source_hash=old_hash,
        ),
        "test model",
    )

    current = alt_images.load_store()[entry.image]
    assert written is False
    assert current.long_de == "Previous German"
    assert current.takeaway_default_de == "Previous takeaway"
    assert current.translated_from_hash == ""


def test_relink_sends_structured_configuration_and_typed_parameters(monkeypatch):
    from slidemage import alt_draft

    system = "Line one\n\nLine three"
    template = "{{ .System }}\n{{ .Prompt }}\n"
    license_text = "License line one\n\nLicense line three"
    show = {
        "modelfile": "FROM /models/local/blob\n",
        "parameters": (
            "num_ctx 0\n"
            "use_mmap false\n"
            "temperature 0.25\n"
            'stop "0"\n'
            'stop "stop phrase with spaces"\n'
        ),
        "system": system,
        "template": template,
        "license": license_text,
        "renderer": "renderer-v1",
        "parser": "parser-v1",
        "messages": [{"role": "system", "content": "Message\ncontent"}],
        "requires": "0.14.0",
        "capabilities": ["completion"],
    }
    requests = _install_ollama(monkeypatch, show)

    ok, error = alt_draft.relink_derived_model(
        "slidemage/custom", "registry/base:latest", host="http://ollama.test"
    )

    assert (ok, error) == (True, "")
    assert [request.full_url for request, _timeout in requests] == [
        "http://ollama.test/api/show",
        "http://ollama.test/api/create",
    ]
    show_request = json.loads(requests[0][0].data)
    assert show_request == {"model": "slidemage/custom"}
    payload = json.loads(requests[1][0].data)
    assert payload == {
        "model": "slidemage/custom",
        "from": "registry/base:latest",
        "stream": False,
        "parameters": {
            "num_ctx": 0,
            "use_mmap": False,
            "temperature": 0.25,
            "stop": ["0", "stop phrase with spaces"],
        },
        "system": system,
        "template": template,
        "license": license_text,
        "renderer": "renderer-v1",
        "parser": "parser-v1",
        "messages": [{"role": "system", "content": "Message\ncontent"}],
        "requires": "0.14.0",
    }
    assert "modelfile" not in payload
    assert requests[1][1] == 120


def test_relink_fails_clearly_on_malformed_parameters_without_creating(monkeypatch):
    from slidemage import alt_draft

    requests = _install_ollama(
        monkeypatch,
        {"parameters": 'temperature "unterminated'},
    )

    ok, error = alt_draft.relink_derived_model(
        "slidemage/custom", "registry/base:latest", host="http://ollama.test"
    )

    assert ok is False
    assert "Could not preserve slidemage/custom's current configuration" in error
    assert "parameter line 1" in error
    assert len(requests) == 1
    assert requests[0][0].full_url.endswith("/api/show")


def test_relink_surfaces_create_api_error(monkeypatch):
    from slidemage import alt_draft

    requests = _install_ollama(
        monkeypatch,
        {"parameters": "temperature 0.2"},
        create_error="base model not found",
    )

    ok, error = alt_draft.relink_derived_model(
        "slidemage/custom", "registry/missing:latest", host="http://ollama.test"
    )

    assert ok is False
    assert error == "base model not found"
    assert len(requests) == 2
    assert requests[1][0].full_url.endswith("/api/create")
