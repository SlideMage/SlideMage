# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The terminal service (ui/workspace/terminal/service.py, Host.terminal()): a short command on a pty, with and
without the xterm view, the window requirement of the host, and the external-edit watch."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import make_project, wait_until
from PySide6.QtCore import QCoreApplication

from slidemage import project
from slidemage.plugins.host import PluginHost
from slidemage.plugins.manifest import read_manifest
from slidemage.ui.workspace.terminal.service import PtySession, TerminalService

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the commands are POSIX shell")
FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture
def service(qapp, tmp_path):
    return TerminalService(tmp_path)


def test_a_short_command_reports_output_and_exit(service, tmp_path):
    out, codes = [], []
    session = service.start(["sh", "-c", "echo hello; pwd; exit 3"], with_widget=False,
                            on_output=out.append, on_exit=codes.append)
    wait_until(lambda: codes)
    assert codes == [3]
    text = b"".join(out).decode()
    assert "hello" in text and str(tmp_path.resolve()) in text
    assert not session.running and session.widget is None
    session.stop()
    session.stop()          # twice is fine


def test_input_reaches_the_program_and_stop_ends_it(service):
    out, codes = [], []
    session = service.start(["cat"], with_widget=False, on_output=out.append, on_exit=codes.append)
    session.write(b"ping\n")
    wait_until(lambda: b"ping" in b"".join(out))
    session.resize(100, 30)
    assert session.running
    session.stop()
    QCoreApplication.processEvents()
    assert not session.running
    assert codes == []      # a stopped program's late exit is not reported


def test_env_and_cwd_are_used(service, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    out = []
    codes = []
    service.start(["sh", "-c", "echo $FIXTURE_VAR; pwd"], {"FIXTURE_VAR": "yes", "PATH": "/usr/bin:/bin"}, other,
                  with_widget=False, on_output=out.append, on_exit=codes.append)
    wait_until(lambda: codes)
    text = b"".join(out).decode()
    assert "yes" in text and str(other.resolve()) in text


def test_a_program_that_cannot_start_raises(service):
    with pytest.raises(OSError):
        service.start(["/nonexistent/program"], with_widget=False)


def test_restart_drops_the_old_programs_late_output(qapp, tmp_path):
    session = PtySession()
    out = []
    session.output.connect(out.append)
    session.start(["sh", "-c", "sleep 5; echo OLD"], {"PATH": "/usr/bin:/bin"}, tmp_path, 80, 24)
    session.start(["sh", "-c", "echo NEW"], {"PATH": "/usr/bin:/bin"}, tmp_path, 80, 24)
    wait_until(lambda: b"NEW" in b"".join(out))
    session.stop()
    assert b"OLD" not in b"".join(out)


def test_with_a_view_the_program_starts_when_the_view_has_a_size(service):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    out, codes = [], []
    session = service.start(["sh", "-c", "echo viewed"], with_widget=True, on_output=out.append, on_exit=codes.append)
    try:
        assert session.widget is not None and not session.running
        session.widget.show()
        session.widget.ready.emit(90, 20)           # what the page reports once xterm.js has its size
        wait_until(lambda: codes)
        assert b"viewed" in b"".join(out)
    finally:
        session.close()
    assert session.widget is None


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    ctx = project.ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))
    return PluginHost(read_manifest(FIXTURES / "hello"), ctx)


def test_the_host_needs_a_window_for_the_terminal(host):
    with pytest.raises(RuntimeError, match="no window"):
        host.terminal()


def test_the_host_hands_out_the_service(host, tmp_path):
    class Ui:
        def terminal_tokens(self):
            from slidemage.ui.kit.tokens import tokens_for
            return tokens_for(True)

    host.ui = Ui()
    service = host.terminal()
    assert isinstance(service, TerminalService) and service.root == host.ctx.root


def test_watch_external_edits(host, qapp):
    seen = []
    watch = host.watch_external_edits(seen.append)
    new = host.ctx.slides_dir / "zzz-EN-New-current.tex"
    with watch:
        new.write_text("x", encoding="utf-8")
        watch.poll()
        assert [c.added for c in seen] == [(new,)]
        (host.ctx.slides_dir / "abc-EN-Hello-current.tex").write_text("changed", encoding="utf-8")
    assert seen[-1].modified          # leaving the with takes a last look
    count = len(seen)
    watch.stop()
    assert len(seen) == count


def test_a_failing_callback_is_offered_the_changes_again(host, qapp):
    calls = []

    def flaky(changes):
        calls.append(changes)
        if len(calls) == 1:
            raise RuntimeError("not yet")

    watch = host.watch_external_edits(flaky)
    watch.start()
    (host.ctx.slides_dir / "zzz-EN-New-current.tex").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError):
        watch.poll()
    watch.poll()
    watch.stop(last_look=False)
    assert len(calls) == 2 and calls[0] == calls[1]



def test_created_view_can_be_attached_after_it_is_ready(service):
    from PySide6.QtCore import QObject, Signal

    class View(QObject):
        input_data = Signal(bytes)
        resized = Signal(int, int)
        ready = Signal(int, int)

        def __init__(self):
            super().__init__()
            self.terminal_size = (90, 25)
            self.output = []

        def write(self, data):
            self.output.append(data)

        def shutdown(self):
            pass

    view = View()
    view.write(b"startup error")
    codes = []
    session = service.start(["sh", "-c", "echo hello"], widget=view, on_exit=codes.append)
    wait_until(lambda: codes)
    assert session.widget is view
    assert b"startup error" in view.output and b"hello" in b"".join(view.output)
    session.close()
    with pytest.raises(ValueError):
        service.start(["cat"], with_widget=False, widget=view)
