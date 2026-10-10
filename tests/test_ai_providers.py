"""ChatProvider implementations against a throwaway local HTTP server (no
external network): request shape, response parsing, error mapping; plus the
API-key sources, the task->provider resolver, settings migration, local-only
and consent state."""
from __future__ import annotations

import base64
import threading

import pytest

from slidemage import app_settings, project
from slidemage.ai import credentials, resolver
from slidemage.ai.providers import (
    ANTHROPIC_FALLBACK_MODELS,
    AnthropicProvider,
    Cancelled,
    OllamaProvider,
    ProviderError,
    parse_json_object,
)

from fake_http import Server, message_sse

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"


@pytest.fixture
def server():
    srv = Server()
    yield srv
    srv.close()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Isolated app_settings.json and project root (the tests run against
    the example project, whose files must stay untouched)."""
    monkeypatch.setattr(app_settings, "STORE_PATH", tmp_path / "app_settings.json")
    monkeypatch.setattr(resolver, "PROJECT_ROOT", tmp_path)
    return tmp_path


def anthropic(server, **kwargs):
    provider = AnthropicProvider(api_key=kwargs.pop("api_key", "sk-test"), **kwargs)
    provider.base_url = server.url
    provider.max_retries = 0     # an error answer is the test; the SDK's backoff would only slow it
    return provider


def answer_with(server, content, stop_reason="end_turn"):
    server.body = message_sse(content, stop_reason)
    server.content_type = "text/event-stream"


# -- Ollama ------------------------------------------------------------------

def test_ollama_chat_request_shape_and_parsing(server):
    server.body = {"message": {"content": "answer", "thinking": "hm"}, "done_reason": "length"}
    provider = OllamaProvider("qwen3", host=server.url)
    reply = provider.chat(
        [{"role": "user", "content": "hi"}], system="be brief", images=[PNG],
        schema={"type": "object"}, temperature=0.1, max_tokens=99, num_ctx=4096)
    request = server.requests[0]
    assert (request["method"], request["path"]) == ("POST", "/api/chat")
    assert request["body"] == {
        "model": "qwen3", "stream": False, "format": {"type": "object"},
        "options": {"temperature": 0.1, "num_predict": 99, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi", "images": [base64.b64encode(PNG).decode()]}]}
    assert (reply.text, reply.thinking, reply.truncated) == ("answer", "hm", True)


def test_ollama_sends_think_only_when_enabled(server):
    server.body = {"message": {"content": "x"}}
    provider = OllamaProvider("m", host=server.url)
    provider.chat([{"role": "user", "content": "a"}])
    provider.chat([{"role": "user", "content": "a"}], think=True)
    assert "think" not in server.requests[0]["body"]
    assert server.requests[1]["body"]["think"] is True


def test_ollama_errors_become_provider_errors(server):
    provider = OllamaProvider("m", host=server.url)
    server.status, server.body = 500, {"error": "model crashed"}
    with pytest.raises(ProviderError, match="Ollama returned HTTP 500: model crashed"):
        provider.chat([{"role": "user", "content": "a"}])
    dead = OllamaProvider("m", host="http://127.0.0.1:9")
    with pytest.raises(ProviderError, match="Ollama unreachable"):
        dead.chat([{"role": "user", "content": "a"}])


def test_ollama_lists_models_newest_first_and_filters_vision(server):
    server.body = {"models": [
        {"name": "old", "modified_at": "2026-01-01", "size": 5, "capabilities": ["vision"]},
        {"name": "new", "modified_at": "2026-06-01", "size": 7},
    ]}
    provider = OllamaProvider(host=server.url)
    assert provider.list_models() == ["new", "old"]
    assert provider.list_models(vision_only=True) == ["old"]
    assert [m.size_bytes for m in provider.installed()] == [7, 5]
    assert OllamaProvider(host="http://127.0.0.1:9").list_models() == []


def test_abort_ends_a_running_request(server):
    server.hold = True
    provider = OllamaProvider("m", host=server.url)
    outcome = []

    def run():
        try:
            provider.chat([{"role": "user", "content": "a"}])
        except ProviderError as exc:
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    while not server.requests:
        thread.join(0.01)
    provider.abort()
    thread.join(5)
    assert not thread.is_alive()
    assert isinstance(outcome[0], Cancelled)


def test_the_socket_is_known_before_the_body_goes_out_and_a_reset_is_not_unreachable(monkeypatch):
    marker = object()
    seen = []

    class Connection:
        fail = None

        def __init__(self, *_args, **_kwargs):
            self.sock = None

        def connect(self):
            if self.fail == "connect":
                raise ConnectionRefusedError("refused")
            self.sock = marker

        def request(self, *_args, **_kwargs):
            seen.append(provider._sock)             # what abort() would shut down while the upload runs
            raise ConnectionResetError("reset by peer")

        def close(self):
            pass

    monkeypatch.setattr("slidemage.ai.providers.http.client.HTTPConnection", Connection)
    provider = OllamaProvider("m", host="http://ollama.test")
    with pytest.raises(ProviderError, match="dropped the connection"):
        provider.chat([{"role": "user", "content": "a"}])
    assert seen == [marker] and provider._sock is None
    Connection.fail = "connect"
    with pytest.raises(ProviderError, match="Ollama unreachable"):
        OllamaProvider("m", host="http://ollama.test").chat([{"role": "user", "content": "a"}])


def test_capabilities_are_asked_once_per_model(server):
    server.body = {"capabilities": ["completion", "vision"]}
    provider = OllamaProvider("m", host=server.url)
    assert provider.capabilities() == ("completion", "vision") and provider.capabilities() == ("completion", "vision")
    assert len([r for r in server.requests if r["path"] == "/api/show"]) == 1
    server.body = {}
    assert provider.capabilities("other") == () and provider.capabilities("other") == ()      # not kept: asked again
    assert len([r for r in server.requests if r["path"] == "/api/show"]) == 3


# -- Anthropic ---------------------------------------------------------------

def test_abort_closes_the_client_so_a_request_not_yet_streaming_ends_too():
    class Closable:
        closed = False

        def close(self):
            self.closed = True

    provider = AnthropicProvider("claude-sonnet-5-5", api_key="k")
    provider._client = client = Closable()
    provider.abort()
    assert client.closed and provider._cancelled


def test_anthropic_request_shape_with_image_and_json_mode(server):
    answer_with(server, [{"type": "text", "text": "{\"a\": 1}"}])
    provider = anthropic(server)
    reply = provider.chat(
        [{"role": "user", "content": "describe"}], system="sys", images=[PNG],
        schema={"type": "object"}, max_tokens=123, temperature=0.9, think=True, num_ctx=1)
    request = server.requests[0]
    assert (request["method"], request["path"]) == ("POST", "/v1/messages")
    assert request["headers"]["x-api-key"] == "sk-test"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    assert request["headers"]["content-type"] == "application/json"
    body = request["body"]
    assert set(body) == {"model", "max_tokens", "system", "messages", "stream"}
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 123
    assert body["system"].startswith("sys\n\n") and '"type": "object"' in body["system"]
    assert body["messages"] == [{"role": "user", "content": [
        {"type": "image", "source": {
            "type": "base64", "media_type": "image/png",
            "data": base64.b64encode(PNG).decode()}},
        {"type": "text", "text": "describe"}]}]
    assert reply.text == '{"a": 1}' and not reply.truncated
    assert parse_json_object(reply.text) == {"a": 1}


def test_anthropic_plain_text_turn_has_no_system_and_flags_truncation(server):
    answer_with(server, [{"type": "text", "text": "cut"}], "max_tokens")
    reply = anthropic(server, model="claude-haiku-4-5-20251001").chat(
        [{"role": "user", "content": "hi"}])
    body = server.requests[0]["body"]
    assert "system" not in body and "output_config" not in body
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert reply.truncated


def test_anthropic_rejects_unsupported_image_formats(server):
    with pytest.raises(ProviderError, match="PNG, JPEG, GIF and WebP"):
        anthropic(server).chat([{"role": "user", "content": "x"}], images=[b"BM bitmap"])
    assert not server.requests


@pytest.mark.parametrize("status, text", [
    (401, "rejected the API key"), (429, "rate limit"), (529, "overloaded"),
    (400, "HTTP 400: bad request"),
])
def test_anthropic_http_errors_map_to_provider_errors(server, status, text):
    server.status = status
    server.body = {"type": "error", "error": {"type": "x", "message": "bad request"}}
    with pytest.raises(ProviderError, match=text):
        anthropic(server).chat([{"role": "user", "content": "hi"}])


def test_anthropic_network_error_and_missing_key(server):
    provider = AnthropicProvider(api_key="k")
    provider.base_url = "http://127.0.0.1:9"
    provider.max_retries = 0
    with pytest.raises(ProviderError, match="Anthropic unreachable"):
        provider.chat([{"role": "user", "content": "hi"}])
    with pytest.raises(ProviderError, match="No Anthropic API key"):
        AnthropicProvider(api_key="").chat([{"role": "user", "content": "hi"}])


def test_anthropic_lists_models(server):
    server.body = {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-sonnet-5-5"}]}
    assert anthropic(server).list_models() == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert server.requests[0]["path"].startswith("/v1/models")
    server.status = 401
    assert anthropic(server).list_models() == []


def test_labels_tell_local_from_cloud():
    assert OllamaProvider("qwen3", host="http://x").label == "qwen3"
    assert AnthropicProvider(api_key="k").label == "claude-sonnet-5-5 · cloud"


def test_parse_json_object_tolerates_fences_think_blocks_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('<think>x</think>{"a": 1}') == {"a": 1}
    assert parse_json_object('Sure! {"a": 1} done') == {"a": 1}
    assert parse_json_object("[1]") is None and parse_json_object("") is None


# -- API key -----------------------------------------------------------------

class FakeKeyring:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        if self.fail:
            raise RuntimeError("no backend")
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


def test_api_key_source_precedence(settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    assert credentials.get_api_key() is None

    app_settings.set(credentials.FILE_SETTING_KEY, "file-key")
    assert credentials.get_api_key() == credentials.ApiKey("file-key", "settings file")
    keyring.set_password("SlideMage", "anthropic-api-key", "ring-key")
    assert credentials.get_api_key() == credentials.ApiKey("ring-key", "keychain")
    monkeypatch.setenv("ANTHROPIC_API_KEY", " env-key ")
    assert credentials.get_api_key() == credentials.ApiKey("env-key", "environment")


def test_set_api_key_prefers_the_keychain_and_keeps_one_copy(settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    app_settings.set(credentials.FILE_SETTING_KEY, "stale")
    assert credentials.set_api_key("k1") == "keychain"
    assert credentials.get_api_key() == credentials.ApiKey("k1", "keychain")
    assert app_settings.get(credentials.FILE_SETTING_KEY) is None
    assert credentials.set_api_key("") == ""
    assert credentials.get_api_key() is None


def test_set_api_key_falls_back_to_the_settings_file(settings, monkeypatch):
    # No keyring installed...
    assert credentials.set_api_key("k2") == "settings file"
    assert credentials.get_api_key() == credentials.ApiKey("k2", "settings file")
    credentials.set_api_key("")
    assert credentials.get_api_key() is None
    # ...or one with no usable backend.
    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring(fail=True))
    assert credentials.set_api_key("k3") == "settings file"


def test_keychain_is_available_only_with_a_real_backend(monkeypatch):
    class Backend:
        def __init__(self, priority):
            self.priority = priority

    class Keyring:
        def __init__(self, backend):
            self.backend = backend

        def get_keyring(self):
            if isinstance(self.backend, Exception):
                raise self.backend
            return self.backend

    assert not credentials.keychain_available()                               # keyring not installed
    for backend, expected in ((Backend(5), True), (Backend(0), False), (RuntimeError("broken"), False)):
        monkeypatch.setattr(credentials, "_keyring", lambda backend=backend: Keyring(backend))
        assert credentials.keychain_available() is expected


# -- resolver, migration, local-only, consent ----------------------------------

def test_old_bare_model_names_read_as_ollama(settings):
    app_settings.set("drafting_model", "qwen3:8b")           # pre-provider settings file
    app_settings.set("translation_model", "sun_leaf/HY-MT:7b")
    app_settings.set("syntax_check_model", "anthropic:claude-opus-5-5")
    assert app_settings.default_model("image_description") == "ollama:qwen3:8b"
    assert app_settings.default_model("translation") == "ollama:sun_leaf/HY-MT:7b"
    assert app_settings.default_model("syntax_check") == "anthropic:claude-opus-5-5"
    assert app_settings.default_model("chat") == ""
    assert app_settings.get("drafting_model") == "qwen3:8b"  # file not rewritten


def test_provider_for_builds_the_right_provider(settings):
    local = resolver.provider_for("ollama:qwen3:8b")
    assert isinstance(local, OllamaProvider) and local.model == "qwen3:8b"
    assert resolver.provider_for("qwen3").model == "qwen3"   # bare name = Ollama
    cloud = resolver.provider_for("anthropic:claude-opus-5-5")
    assert isinstance(cloud, AnthropicProvider) and cloud.model == "claude-opus-5-5"

    app_settings.set("chat_model", "anthropic:claude-haiku-4-5-20251001")
    assert resolver.provider_for_task("chat").model == "claude-haiku-4-5-20251001"
    assert isinstance(resolver.provider_for_task("translation"), OllamaProvider)  # unset


def test_local_only_blocks_cloud_globally_and_per_project(settings):
    assert not resolver.local_only() and resolver.project_local_only() is None
    resolver.set_global_local_only(True)
    assert resolver.local_only()
    with pytest.raises(resolver.LocalOnlyError, match="Local AI only"):
        resolver.provider_for("anthropic:claude-sonnet-5-5")
    assert resolver.provider_for("ollama:x").is_local  # local still works

    resolver.set_project_local_only(False)               # project overrides the global switch
    assert not resolver.local_only()
    assert not resolver.provider_for("anthropic:claude-sonnet-5-5").is_local
    resolver.set_global_local_only(False)
    resolver.set_project_local_only(True)
    assert resolver.local_only()
    resolver.set_project_local_only(None)
    assert resolver.project_local_only() is None and not resolver.local_only()


def test_project_override_lives_in_project_json_next_to_other_keys(settings):
    project.write_project_json(settings, {"format": 1, "compat": {"x": 1}})
    resolver.set_project_local_only(True)
    data = project.read_project_json(settings)
    assert data["ai"] == {"local_only": True} and data["compat"] == {"x": 1}
    resolver.set_project_local_only(None)
    assert "ai" not in project.read_project_json(settings)


def test_cloud_models_on_offer_need_a_key_and_no_local_only(settings, monkeypatch):
    assert resolver.cloud_models() == []                       # no key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert resolver.cloud_models() == list(ANTHROPIC_FALLBACK_MODELS)
    resolver.set_global_local_only(True)
    assert resolver.cloud_models() == []


def test_cloud_consent_is_asked_once_and_only_for_cloud(settings):
    cloud, local = AnthropicProvider(api_key="k"), OllamaProvider("m", host="http://x")
    assert resolver.needs_cloud_consent(cloud)
    assert not resolver.needs_cloud_consent(local)
    resolver.record_cloud_consent()
    assert resolver.cloud_consent_given() and not resolver.needs_cloud_consent(cloud)
