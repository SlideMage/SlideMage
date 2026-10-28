# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""ChatProvider implementations against a throwaway local HTTP server (no
external network): request shape, response parsing, error mapping; plus the
API-key sources. (The route resolver and its settings are in test_ai_profile.py.)"""
from __future__ import annotations

import base64
import ctypes
import errno
import socket
import ssl
import threading
import time
import urllib.parse
from types import SimpleNamespace

import pytest

from slidemage import app_settings
from slidemage.ai import credentials
from slidemage.ai.anthropic_provider import AnthropicProvider
from slidemage.ai.providers import (
    Cancelled,
    OllamaProvider,
    ProviderError,
    _shutdown_socket,
    parse_json_object,
)

from fake_http import TEST_TLS_CERT, ConnectProxy, Server, api_key_of, message_sse, wait_for_first_piece

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Isolated app_settings.json and project root (the tests run against
    the example project, whose files must stay untouched)."""
    return tmp_path


def anthropic(server, **kwargs):
    provider = AnthropicProvider(api_key=kwargs.pop("api_key", "sk-test"), **kwargs)
    provider.base_url = server.url
    provider.max_retries = 0     # an error answer is the test; the backoff would only slow it
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
    # Regression (1c7e047): cache successful capabilities, but retry unknown models.
    server.body = {"capabilities": ["completion", "vision"]}
    provider = OllamaProvider("m", host=server.url)
    assert provider.capabilities() == ("completion", "vision") and provider.capabilities() == ("completion", "vision")
    assert len([r for r in server.requests if r["path"] == "/api/show"]) == 1
    assert server.requests[0]["body"] == {"model": "m"}
    server.body = {}
    assert provider.capabilities("other") == () and provider.capabilities("other") == ()      # not kept: asked again
    assert len([r for r in server.requests if r["path"] == "/api/show"]) == 3
    server.status, server.body = 404, {"error": "model 'm' not found"}
    assert OllamaProvider("m", host=server.url).capabilities() == ()
    assert OllamaProvider("m", host="http://127.0.0.1:9").capabilities() == ()


@pytest.mark.parametrize("service", ["anthropic", "ollama"])
def test_abort_interrupts_tcp_connect_polling(monkeypatch, service):
    p = AnthropicProvider(api_key="sk-test") if service == "anthropic" else OllamaProvider("m")
    p.base_url = p.host = "http://192.0.2.1"
    entered, closed = threading.Event(), threading.Event()
    outcome = []

    class Socket:
        def setblocking(self, _blocking):
            pass

        def connect_ex(self, _address):
            assert p._sock is self  # abort can reach even the first connect attempt
            entered.set()
            return errno.EINPROGRESS

        def shutdown(self, _how):
            closed.set()

        def close(self):
            closed.set()

    def select_pending(_read, _write, _exception, timeout):
        assert timeout <= 0.05
        closed.wait(timeout)
        return [], [], []

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 80))])
    monkeypatch.setattr(socket, "socket", lambda *_args: Socket())
    monkeypatch.setattr("slidemage.ai.providers.select.select", select_pending)
    # These are Python socket doubles; the real Winsock path is checked separately.
    monkeypatch.setattr("slidemage.ai.providers._shutdown_socket", lambda sock: sock.close() if sock else None)

    def run():
        try:
            p.chat([{"role": "user", "content": "hi"}], timeout=60)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and time.monotonic() - started < 1
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
        assert closed.is_set() and p._sock is None
    finally:
        p.abort()
        closed.set()
        worker.join(2)


def test_connect_falls_back_from_unavailable_ipv6_and_restores_the_timeout(monkeypatch):
    p = OllamaProvider()
    calls = []

    class Socket:
        def setblocking(self, value):
            calls.append(("blocking", value))

        def connect_ex(self, target):
            assert p._sock is self
            calls.append(("connect", target))
            return errno.EINPROGRESS

        def getsockopt(self, *_args):
            return 0

        def settimeout(self, value):
            calls.append(("timeout", value))

        def close(self):
            calls.append("close")

    sock = Socket()

    def create(family, *_args):
        if family == socket.AF_INET6:
            raise OSError(errno.EAFNOSUPPORT, "IPv6 disabled")
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 80, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80))])
    monkeypatch.setattr(socket, "socket", create)
    monkeypatch.setattr("slidemage.ai.providers.select.select", lambda _r, w, _e, _t: ([], w, []))
    assert p._create_socket(("localhost", 80), 60) is sock
    assert calls == [("blocking", False), ("connect", ("127.0.0.1", 80)), ("timeout", 60)]


def test_tcp_connect_timeout_closes_the_published_socket(monkeypatch):
    p = OllamaProvider()
    closed = []

    class Socket:
        def setblocking(self, _value):
            pass

        def connect_ex(self, _target):
            return errno.EINPROGRESS

        def close(self):
            closed.append(True)

    clock = iter([0, 2])
    monkeypatch.setattr("slidemage.ai.providers.time.monotonic", lambda: next(clock))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 80))])
    monkeypatch.setattr(socket, "socket", lambda *_args: Socket())
    with pytest.raises(TimeoutError):
        p._create_socket(("192.0.2.1", 80), 1)
    assert closed == [True] and p._sock is None


def test_windows_abort_closes_the_detached_socket_handle(monkeypatch):
    calls = []

    class Socket:
        def detach(self):
            calls.append("detach")
            return 12345

        def close(self):
            calls.append("close")

    def closesocket(handle):
        calls.append(("closesocket", handle.value))

    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(ws2_32=SimpleNamespace(closesocket=closesocket)), raising=False)
    monkeypatch.setattr("slidemage.ai.providers.sys.platform", "win32")
    _shutdown_socket(Socket())
    assert calls == ["detach", ("closesocket", 12345), "close"]


# -- HTTPS proxies -----------------------------------------------------------

@pytest.fixture
def proxy_environment(monkeypatch):
    # Exercise the real environment resolver, with no developer proxy settings.
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "")
    context = ssl.create_default_context(cafile=str(TEST_TLS_CERT))
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda: context)


@pytest.fixture
def https_server(proxy_environment):
    srv = Server(tls=True)
    yield srv
    srv.close()


@pytest.fixture
def proxy(https_server):
    relay = ConnectProxy(https_server.httpd.server_address)
    yield relay
    relay.close()


@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY"])
def test_anthropic_https_uses_connect_proxy(https_server, proxy, monkeypatch, variable):
    monkeypatch.setenv(variable, proxy.url)
    answer_with(https_server, [{"type": "text", "text": "via proxy"}])
    p = anthropic(https_server)
    # This name cannot resolve directly: only the local proxy routes it to the API.
    p.base_url = "https://api.anthropic.test"
    assert p.chat([{"role": "user", "content": "hi"}]).text == "via proxy"
    assert len(proxy.requests) == 1 and proxy.requests[0]["path"] == "api.anthropic.test:443"
    assert "proxy-authorization" not in proxy.requests[0]["headers"]
    assert https_server.requests[0]["headers"]["host"] == "api.anthropic.test"
    assert api_key_of(https_server.requests[0]) == "sk-test"


@pytest.mark.parametrize("variable", ["NO_PROXY", "no_proxy"])
def test_anthropic_no_proxy_bypasses_connect(https_server, proxy, monkeypatch, variable):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    monkeypatch.setenv(variable, "127.0.0.1")
    answer_with(https_server, [{"type": "text", "text": "direct"}])
    assert anthropic(https_server).chat([{"role": "user", "content": "hi"}]).text == "direct"
    assert not proxy.requests


@pytest.mark.parametrize("bypass", ["", "localhost,127.0.0.1,::1"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "::1"])
def test_local_ollama_is_never_proxied(proxy_environment, monkeypatch, bypass, host):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:8080")
    monkeypatch.setenv("NO_PROXY", bypass)
    authority = f"[{host}]" if ":" in host else host
    conn = OllamaProvider()._connection(urllib.parse.urlsplit(f"https://{authority}:11434"), 1)
    try:
        assert conn.host == host and conn._tunnel_host is None
    finally:
        conn.close()


@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"])
def test_https_proxy_connection_configuration(proxy_environment, monkeypatch, variable):
    monkeypatch.setenv(variable, "http://user%40name:p%3Ass@proxy.test:8080")
    parts = urllib.parse.urlsplit("https://api.anthropic.test:8443")
    for provider in (AnthropicProvider(), OllamaProvider()):
        conn = provider._connection(parts, 10)
        try:
            assert (conn.host, conn.port) == ("proxy.test", 8080)
            assert (conn._tunnel_host, conn._tunnel_port) == ("api.anthropic.test", 8443)
            assert conn._tunnel_headers["Proxy-Authorization"] == "Basic dXNlckBuYW1lOnA6c3M="
        finally:
            conn.close()


@pytest.mark.parametrize("variable", ["NO_PROXY", "no_proxy"])
def test_proxy_bypass_connection_configuration(proxy_environment, monkeypatch, variable):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:8080")
    monkeypatch.setenv(variable, ".anthropic.test")
    conn = AnthropicProvider()._connection(urllib.parse.urlsplit("https://api.anthropic.test"), 10)
    try:
        assert conn.host == "api.anthropic.test" and conn._tunnel_host is None
    finally:
        conn.close()


def test_proxy_basic_auth_is_only_sent_to_the_proxy(https_server, proxy, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url.replace("http://", "http://user%40name:p%3Ass@"))
    answer_with(https_server, [{"type": "text", "text": "ok"}])
    p = anthropic(https_server)
    p.base_url = "https://api.anthropic.test:8443"
    assert p.chat([{"role": "user", "content": "hi"}]).text == "ok"
    assert proxy.requests[0]["path"] == "api.anthropic.test:8443"
    assert proxy.requests[0]["headers"]["proxy-authorization"] == "Basic " + base64.b64encode(b"user@name:p:ss").decode()
    assert "proxy-authorization" not in https_server.requests[0]["headers"]


def test_abort_ends_a_stream_through_the_connect_proxy(https_server, proxy, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    answer_with(https_server, [{"type": "text", "text": "Hello there"}])
    body = https_server.body
    https_server.stall_after = body.index("event: content_block_delta", body.index("content_block_delta") + 1)
    p = anthropic(https_server)
    p.base_url = "https://api.anthropic.test"
    texts, outcome = [], []

    def run():
        try:
            p.stream_turn("", [], [], texts.append)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        wait_for_first_piece(worker, texts)
        assert p._sock is not None and len(proxy.requests) == 1
        started = time.monotonic()
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and time.monotonic() - started < 1
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
    finally:
        p.abort()
        https_server.delay.set()
        worker.join(2)


# -- Anthropic ---------------------------------------------------------------

def test_abort_before_the_request_ends_it_without_connecting(server):
    provider = anthropic(server)
    provider.abort()
    with pytest.raises(Cancelled):
        provider.chat([{"role": "user", "content": "hi"}])
    assert not server.requests


def test_anthropic_request_shape_with_image_and_json_mode(server):
    answer_with(server, [{"type": "text", "text": "{\"a\": 1}"}])
    provider = anthropic(server)
    reply = provider.chat(
        [{"role": "user", "content": "describe"}], system="sys", images=[PNG],
        schema={"type": "object"}, max_tokens=123, temperature=0.9, think=True, num_ctx=1)
    request = server.requests[0]
    assert (request["method"], request["path"]) == ("POST", "/v1/messages")
    assert api_key_of(request) == "sk-test"
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


def test_anthropic_list_models_follows_the_pages(server):
    server.routes = {
        "/v1/models?limit=1000": (200, {"data": [{"id": "a"}, {"id": "b"}], "has_more": True, "last_id": "b"}),
        "/v1/models?limit=1000&after_id=b": (200, {"data": [{"id": "c"}], "has_more": False, "last_id": "c"}),
    }
    provider = anthropic(server)
    assert provider.list_models() == ["a", "b", "c"]
    assert [r["path"] for r in server.requests] == list(server.routes)
    assert server.requests[0]["headers"]["x-api-key"] == "sk-test"
    assert anthropic(server, api_key="").list_models() == []


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


def test_api_key_source_precedence(ctx, settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    assert credentials.get_api_key(ctx) is None

    app_settings.set(ctx, credentials.FILE_SETTING_KEY, "file-key")
    assert credentials.get_api_key(ctx) == credentials.ApiKey("file-key", "settings file")
    keyring.set_password("SlideMage", "anthropic-api-key", "ring-key")
    assert credentials.get_api_key(ctx) == credentials.ApiKey("ring-key", "keychain")
    monkeypatch.setenv("ANTHROPIC_API_KEY", " env-key ")
    assert credentials.get_api_key(ctx) == credentials.ApiKey("env-key", "environment")


def test_set_api_key_prefers_the_keychain_and_keeps_one_copy(ctx, settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: keyring)
    app_settings.set(ctx, credentials.FILE_SETTING_KEY, "stale")
    assert credentials.set_api_key(ctx, "k1") == "keychain"
    assert credentials.get_api_key(ctx) == credentials.ApiKey("k1", "keychain")
    assert app_settings.get(ctx, credentials.FILE_SETTING_KEY) is None
    assert credentials.set_api_key(ctx, "") == ""
    assert credentials.get_api_key(ctx) is None


def test_set_api_key_falls_back_to_the_settings_file(ctx, settings, monkeypatch):
    # No keyring installed...
    assert credentials.set_api_key(ctx, "k2") == "settings file"
    assert credentials.get_api_key(ctx) == credentials.ApiKey("k2", "settings file")
    credentials.set_api_key(ctx, "")
    assert credentials.get_api_key(ctx) is None
    # ...or one with no usable backend.
    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring(fail=True))
    assert credentials.set_api_key(ctx, "k3") == "settings file"


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
