# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import io
import json
import urllib.error

import pytest
from slidemage.project import ProjectContext
from conftest import EXAMPLE_PROJECT


def _install_ollama(monkeypatch, show_body, *, create_error=None):
    from slidemage.ai import ollama_admin

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

    monkeypatch.setattr(ollama_admin.urllib.request, "urlopen", fake_urlopen)
    return requests


@pytest.mark.parametrize(
    ("takeaway", "german_long", "german_takeaway", "translated_takeaway", "edited"),
    [
        ("", "", "Old German takeaway", "", False),
        ("t1", "", "", "t1-de", False),
        ("t1", "", "", "t1-de", True),
        ("English takeaway", "Previous German", "Previous takeaway", "", True),
    ],
    ids=["clear-empty-takeaway", "fresh", "stale-empty-german", "stale-existing-german"],
)
def test_applying_translation_checks_source_hash_and_updates_german(
    tmp_path, monkeypatch, takeaway, german_long, german_takeaway, translated_takeaway, edited
):
    """A Translate all snapshot must not overwrite German after the English changes."""
    from slidemage import alt_draft, alt_images

    ctx = ProjectContext.at(tmp_path)
    entry = alt_images.ImageEntry(
        image="media/chart.png", short="English short", long="Original English",
        takeaway_default=takeaway, long_de=german_long, takeaway_default_de=german_takeaway,
    )
    source_hash = alt_images.en_text_hash(entry)
    alt_images.save_store(ctx, {entry.image: entry})
    if edited:
        # The batch took its source hash before this edit (regression: 34cdbd7).
        alt_images.update_store(ctx, lambda entries: setattr(entries[entry.image], "long", "Edited English") or True)
    result = alt_draft.TranslationResult(
        short_de="Kurzer Text", long_de="translated text", takeaway_de=translated_takeaway,
        model="test", source_hash=source_hash,
    )
    written = alt_draft.apply_one_translation(ctx, entry.image, result, "test model")
    current = alt_images.load_store(ctx)[entry.image]
    assert written is (not edited)
    if edited:
        assert current.long_de == german_long
        assert current.takeaway_default_de == german_takeaway
        assert current.translated_from_hash == ""
    else:
        assert current.long_de == "translated text"
        assert current.takeaway_default_de == translated_takeaway
        assert current.translated_from_hash == source_hash
        assert alt_images.translation_state(current) == alt_images.STATE_REVIEWED


def test_relink_sends_structured_configuration_and_typed_parameters(monkeypatch):
    from slidemage.ai import ollama_admin

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

    ok, error = ollama_admin.relink_derived_model(
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


def test_relink_fails_clearly_on_malformed_parameters_without_creating(monkeypatch):
    from slidemage.ai import ollama_admin

    requests = _install_ollama(
        monkeypatch,
        {"parameters": 'temperature "unterminated'},
    )

    ok, error = ollama_admin.relink_derived_model(
        "slidemage/custom", "registry/base:latest", host="http://ollama.test"
    )

    assert ok is False
    assert "Could not preserve slidemage/custom's current configuration" in error
    assert "parameter line 1" in error
    assert len(requests) == 1
    assert requests[0][0].full_url.endswith("/api/show")


def test_relink_surfaces_create_api_error(monkeypatch):
    from slidemage.ai import ollama_admin

    requests = _install_ollama(
        monkeypatch,
        {"parameters": "temperature 0.2"},
        create_error="base model not found",
    )

    ok, error = ollama_admin.relink_derived_model(
        "slidemage/custom", "registry/missing:latest", host="http://ollama.test"
    )

    assert ok is False
    assert error == "base model not found"
    assert len(requests) == 2
    assert requests[1][0].full_url.endswith("/api/create")


def _install_ollama_models(monkeypatch, models, *, registry):
    """A fake Ollama server for update_model(): `models` maps a local model
    name to (parent_model, weights blob digest); `registry` names the
    models a pull finds. Records (endpoint, model) per request."""
    from slidemage.ai import ollama_admin

    calls = []

    class FakeResponse:
        def __init__(self, lines):
            self.lines = [json.dumps(line).encode("utf-8") + b"\n" for line in lines]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(self.lines)

        def read(self):
            return b"".join(self.lines)

    def fake_urlopen(request, timeout):
        endpoint = request.full_url.rsplit("/", 1)[-1]
        model = json.loads(request.data)["model"]
        calls.append((endpoint, model))
        if endpoint == "pull":
            if model in registry:
                return FakeResponse([{"status": "pulling manifest"}, {"status": "success"}])
            return FakeResponse([{"error": "pull model manifest: file does not exist"}])
        if endpoint == "show":
            parent, blob = models[model]
            return FakeResponse([{
                "modelfile": f"# FROM {model}\nFROM D:\\models\\blobs\\{blob}\nPARAMETER num_ctx 16384\n",
                "parameters": "num_ctx 16384",
                "details": {"parent_model": parent},
            }])
        if endpoint == "create":
            return FakeResponse([{"status": "success"}])
        raise AssertionError(f"unexpected Ollama endpoint: {request.full_url}")

    monkeypatch.setattr(ollama_admin.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_update_pulls_a_registry_model_directly(monkeypatch):
    from slidemage.ai import ollama_admin

    calls = _install_ollama_models(monkeypatch, {}, registry={"gemma4:latest"})

    assert ollama_admin.update_model("gemma4:latest", host="http://ollama.test") == (True, "")
    assert calls == [("pull", "gemma4:latest")]


@pytest.mark.parametrize(("model", "base", "blob", "base_blob"), [
    ("Claude_Gemma4_16k:latest", "gemma4:latest", "a", "b"),
    ("Claude_Llama31_8b_16k:latest", "llama3.1:8b", "c", "c"),
])
def test_update_rebuilds_a_custom_model_only_when_its_base_changed(monkeypatch, model, base, blob, base_blob):
    # v5.35.3: custom models use Ollama's recorded parent, not a name table.
    from slidemage.ai import ollama_admin

    calls = _install_ollama_models(monkeypatch, {
        model: (base, "sha256-" + blob * 64),
        base: ("", "sha256-" + base_blob * 64),
    }, registry={base})
    progress = []
    ok, error = ollama_admin.update_model(model, host="http://ollama.test", on_progress=progress.append)
    assert (ok, error) == (True, "")
    if blob != base_blob:
        assert ("pull", base) in calls
        assert calls[-1] == ("create", model)
        assert any(f"built from {base}" in line for line in progress)
    else:
        assert ("create", model) not in calls
        assert progress[-1] == f"{model}: already uses the current {base}"


def test_update_reports_a_custom_model_without_a_recorded_base(monkeypatch):
    from slidemage.ai import ollama_admin

    calls = _install_ollama_models(monkeypatch, {
        "mystery:latest": ("", "sha256-" + "d" * 64),
    }, registry=set())

    ok, error = ollama_admin.update_model("mystery:latest", host="http://ollama.test")

    assert ok is False
    assert "file does not exist" in error and "does not record the model it was built from" in error
    assert [endpoint for endpoint, _model in calls] == ["pull", "show"]


def test_update_does_not_look_for_a_base_after_other_pull_errors(monkeypatch):
    from slidemage.ai import ollama_admin

    def offline(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(ollama_admin.urllib.request, "urlopen", offline)

    ok, error = ollama_admin.update_model("gemma4:latest", host="http://ollama.test")

    assert ok is False and "connection refused" in error


def test_the_admin_calls_never_raise_whatever_the_server_does(monkeypatch):
    import http.client

    from slidemage.ai import ollama_admin

    class Lines:
        def __init__(self, lines):
            self.lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(self.lines)

        def read(self):
            return b""

    failures = [http.client.IncompleteRead(b"par"), http.client.RemoteDisconnected("closed"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
                urllib.error.HTTPError("u", 500, "Server Error", hdrs=None, fp=io.BytesIO(b'["not", "a dict"]')),
                urllib.error.HTTPError("u", 500, "Server Error", hdrs=None, fp=io.BytesIO(b"\xff\xfe"))]
    for failure in failures:
        def broken(request, timeout, failure=failure):
            raise failure

        monkeypatch.setattr(ollama_admin.urllib.request, "urlopen", broken)
        for ok, error in (ollama_admin.delete_model("m", host="http://x"), ollama_admin.pull_model("m", host="http://x"),
                          ollama_admin.relink_derived_model("m", "b", host="http://x")):
            assert ok is False and isinstance(error, str) and error
        assert ollama_admin.get_modelfile("m", host="http://x") is None

    # a reply that stops half way, odd events in a pull stream
    monkeypatch.setattr(ollama_admin.urllib.request, "urlopen", lambda request, timeout: Lines(
        [b"[1]\n", b'{"status": "pulling", "total": "big", "completed": 3}\n', b"\xff\n"]))
    progress = []
    ok, error = ollama_admin.pull_model("m", host="http://x", on_progress=progress.append)
    assert ok is False and error                         # the undecodable line ends the pull with a message
    assert progress == ["m: pulling"]


def test_ollama_host_setting_overrides_default(monkeypatch, tmp_path):
    """2026-09-23 review finding: the Ollama host was a hardcoded constant
    duplicated in alt_draft.py and ai_draft.py, with no way to point this
    app at a non-default Ollama server. app_settings.get_ollama_host(EXAMPLE_PROJECT)
    resolves it; OllamaProvider reads it when constructed instead of
    freezing a constant at class-definition time."""
    from slidemage import app_settings
    from slidemage.ai.providers import OllamaProvider

    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    assert app_settings.get_ollama_host(EXAMPLE_PROJECT) == "http://localhost:11434"

    app_settings.set_ollama_host(EXAMPLE_PROJECT, "http://gpu-box:9999")
    assert app_settings.get_ollama_host(EXAMPLE_PROJECT) == "http://gpu-box:9999"
    assert OllamaProvider.for_project(EXAMPLE_PROJECT, "m").host == "http://gpu-box:9999"

    # An explicit host= still wins over the saved setting.
    assert OllamaProvider("m", host="http://explicit").host == "http://explicit"

    # Clearing it falls back through $OLLAMA_HOST, then the plain default.
    app_settings.set_ollama_host(EXAMPLE_PROJECT, "")
    assert app_settings.get_ollama_host(EXAMPLE_PROJECT) == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://from-env:8000")
    assert app_settings.get_ollama_host(EXAMPLE_PROJECT) == "http://from-env:8000"


def test_draft_prompt_is_customizable_and_persists(ctx, monkeypatch, tmp_path):
    """2026-09-23 review finding: alt_draft.py's image-description prompt
    was a hardcoded SYSTEM_PROMPT constant -- unlike translation_prompts.py's
    already-customizable prompts, there was no way to tune it without
    editing source."""
    from slidemage import alt_draft, draft_prompts
    from slidemage.ai.providers import OllamaProvider


    assert alt_draft.effective_system_prompt(ctx) == alt_draft.SYSTEM_PROMPT

    draft_prompts.set_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT, "Custom draft prompt.")
    assert alt_draft.effective_system_prompt(ctx) == "Custom draft prompt."

    # A freshly constructed backend with no explicit system_prompt picks
    # up the current custom default; an explicit one still overrides it.
    provider = OllamaProvider("m")
    assert alt_draft.ModelBackend(ctx, provider).system_prompt == "Custom draft prompt."
    assert alt_draft.ModelBackend(ctx, provider, system_prompt="one-off").system_prompt == "one-off"

    # Clearing (empty string) reverts to the hardcoded default.
    draft_prompts.set_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT, "")
    assert alt_draft.effective_system_prompt(ctx) == alt_draft.SYSTEM_PROMPT
    assert draft_prompts.get_custom_prompt(ctx, draft_prompts.KIND_IMAGE_DRAFT) is None
