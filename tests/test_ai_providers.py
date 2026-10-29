# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral response parsing and transport behavior."""
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

from slidemage.ai.providers import Cancelled, ProviderError, _HttpProvider, _shutdown_socket, parse_json_object

from fake_http import TEST_TLS_CERT, ConnectProxy, Server, StallingServer, wait_for_first_piece


class HttpProvider(_HttpProvider):
    service = "Fake"
    is_local = False

    def request(self, base_url="http://provider.test", timeout=1):
        return self._send("POST", base_url, "/chat", headers={"x-api-key": "test-key"}, payload={}, timeout=timeout)


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
    provider = HttpProvider()
    with pytest.raises(ProviderError, match="dropped the connection"):
        provider.request()
    assert seen == [marker] and provider._sock is None
    Connection.fail = "connect"
    with pytest.raises(ProviderError, match="Fake unreachable"):
        HttpProvider().request()


def test_abort_interrupts_tcp_connect_polling(monkeypatch):
    p = HttpProvider()
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
            p.request("http://192.0.2.1", timeout=60)
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
    p = HttpProvider()
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
    p = HttpProvider()
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
def test_https_uses_connect_proxy(https_server, proxy, monkeypatch, variable):
    monkeypatch.setenv(variable, proxy.url)
    https_server.body = {"answer": "via proxy"}
    p = HttpProvider()
    # This name cannot resolve directly: only the local proxy routes it to the API.
    status, body = p.request("https://api.anthropic.test")
    assert status == 200 and b"via proxy" in body
    assert len(proxy.requests) == 1 and proxy.requests[0]["path"] == "api.anthropic.test:443"
    assert "proxy-authorization" not in proxy.requests[0]["headers"]
    assert https_server.requests[0]["headers"]["host"] == "api.anthropic.test"
    assert https_server.requests[0]["headers"]["x-api-key"] == "test-key"


@pytest.mark.parametrize("variable", ["NO_PROXY", "no_proxy"])
def test_no_proxy_bypasses_connect(https_server, proxy, monkeypatch, variable):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    monkeypatch.setenv(variable, "127.0.0.1")
    https_server.body = {"answer": "direct"}
    status, body = HttpProvider().request(https_server.url)
    assert status == 200 and b"direct" in body
    assert not proxy.requests


@pytest.mark.parametrize("bypass", ["", "localhost,127.0.0.1,::1"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "::1"])
def test_local_provider_loopback_is_never_proxied(proxy_environment, monkeypatch, bypass, host):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:8080")
    monkeypatch.setenv("NO_PROXY", bypass)
    authority = f"[{host}]" if ":" in host else host
    provider = HttpProvider()
    provider.is_local = True
    conn = provider._connection(urllib.parse.urlsplit(f"https://{authority}:11434"), 1)
    try:
        assert conn.host == host and conn._tunnel_host is None
    finally:
        conn.close()


@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"])
def test_https_proxy_connection_configuration(proxy_environment, monkeypatch, variable):
    monkeypatch.setenv(variable, "http://user%40name:p%3Ass@proxy.test:8080")
    parts = urllib.parse.urlsplit("https://api.anthropic.test:8443")
    for is_local in (False, True):
        provider = HttpProvider()
        provider.is_local = is_local
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
    conn = HttpProvider()._connection(urllib.parse.urlsplit("https://api.anthropic.test"), 10)
    try:
        assert conn.host == "api.anthropic.test" and conn._tunnel_host is None
    finally:
        conn.close()


def test_proxy_basic_auth_is_only_sent_to_the_proxy(https_server, proxy, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url.replace("http://", "http://user%40name:p%3Ass@"))
    https_server.body = {"answer": "ok"}
    status, body = HttpProvider().request("https://api.anthropic.test:8443")
    assert status == 200 and b"ok" in body
    assert proxy.requests[0]["path"] == "api.anthropic.test:8443"
    assert proxy.requests[0]["headers"]["proxy-authorization"] == "Basic " + base64.b64encode(b"user@name:p:ss").decode()
    assert "proxy-authorization" not in https_server.requests[0]["headers"]


def test_abort_ends_a_stream_through_the_connect_proxy(https_server, proxy, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    https_server.body = "first piece\nsecond piece\n"
    https_server.stall_after = len("first piece\n")
    p = HttpProvider()
    texts, outcome = [], []

    def run():
        try:
            with p._request("POST", "https://api.anthropic.test", "/chat", headers={}, payload={}, timeout=60) as response:
                for line in response:
                    texts.append(line)
                # TLS shutdown can end the stream with EOF instead of an error.
                p._check_cancelled()
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


def test_abort_ends_a_running_request(server):
    server.hold = True
    provider = HttpProvider()
    outcome = []

    def run():
        try:
            provider.request(server.url, timeout=60)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while not server.requests and worker.is_alive() and time.monotonic() < deadline:
            worker.join(0.01)
        assert server.requests
        provider.abort()
        worker.join(1)
        assert not worker.is_alive()
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
    finally:
        provider.abort()
        server.delay.set()
        worker.join(2)


def test_abort_before_the_request_ends_it_without_connecting(monkeypatch):
    provider = HttpProvider()
    provider.abort()

    def unexpected_connect(_conn):
        pytest.fail("a cancelled request must not connect")

    monkeypatch.setattr(provider, "_connect", unexpected_connect)
    with pytest.raises(Cancelled):
        provider.request()


@pytest.mark.parametrize("stage", ["connect_tunnel", "tls_handshake"])
def test_abort_interrupts_https_connection_setup(proxy_environment, monkeypatch, stage):
    stall = StallingServer()
    p = HttpProvider()
    if stage == "connect_tunnel":
        monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{stall.address[1]}")
        url = "https://api.anthropic.test"
    else:
        url = f"https://127.0.0.1:{stall.address[1]}"
    outcome = []

    def run():
        try:
            p.request(url, timeout=60)
        except ProviderError as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert stall.received.wait(2)
        assert p._sock is not None
        started = time.monotonic()
        p.abort()
        worker.join(1)
        assert not worker.is_alive() and time.monotonic() - started < 1
        assert len(outcome) == 1 and isinstance(outcome[0], Cancelled)
        assert p._sock is None
    finally:
        p.abort()
        stall.close()
        worker.join(2)


def test_parse_json_object_tolerates_fences_think_blocks_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('<think>x</think>{"a": 1}') == {"a": 1}
    assert parse_json_object('Sure! {"a": 1} done') == {"a": 1}
    assert parse_json_object("[1]") is None and parse_json_object("") is None

