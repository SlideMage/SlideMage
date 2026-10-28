# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider-neutral response parsing and transport behavior."""
import pytest

from slidemage.ai.providers import ProviderError, _HttpProvider, parse_json_object


class HttpProvider(_HttpProvider):
    service = "Fake"

    def request(self):
        return self._send("POST", "http://provider.test", "/chat", headers={}, payload={}, timeout=1)


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



def test_parse_json_object_tolerates_fences_think_blocks_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('<think>x</think>{"a": 1}') == {"a": 1}
    assert parse_json_object('Sure! {"a": 1} done') == {"a": 1}
    assert parse_json_object("[1]") is None and parse_json_object("") is None

