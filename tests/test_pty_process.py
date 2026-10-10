"""The pseudo-terminal wrapper (pty_process.py): a child gets a terminal of the asked size, its output
arrives in order, input reaches it, the exit code is reported, and stop() ends it politely, then by force."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
from fake_claude import make_fake_claude

from slidemage.pty_process import PtyProcess

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake program is a POSIX script")


class Run:
    def __init__(self, argv, cwd, env=None, cols=80, rows=24):
        self.chunks: list[bytes] = []
        self.codes: list[int] = []
        self.process = PtyProcess(argv, cwd, env or {"PATH": "/usr/bin:/bin", "TERM": "xterm"},
                                  self.chunks.append, self.codes.append, cols, rows)

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", "replace")

    def wait_for(self, condition, seconds=10):
        end = time.time() + seconds
        while not condition() and time.time() < end:
            time.sleep(0.01)
        assert condition(), self.text


def sh(script: str):
    """A shell script: starts in milliseconds, where a Python child takes a third of a second."""
    return ["/bin/sh", "-c", script]


def test_output_input_size_and_the_exit_code(tmp_path):
    run = Run(sh("stty size; read line; echo got:$line; exit 5"), tmp_path, cols=97, rows=31)
    run.wait_for(lambda: "31 97" in run.text)                       # the terminal has the asked size
    run.process.write("héllo\n".encode())                            # input reaches the child
    run.wait_for(lambda: run.codes)
    assert "got:héllo" in run.text and run.codes == [5] and not run.process.alive


def test_a_resize_reaches_the_child(tmp_path):
    run = Run(sh("trap 'echo size $(stty size)' WINCH; echo ready; while :; do sleep 0.05; done"), tmp_path)
    run.wait_for(lambda: "ready" in run.text)
    run.process.resize(120, 40)
    run.wait_for(lambda: "size 40 120" in run.text)
    run.process.stop()


def test_stop_ends_the_process_politely_and_reports_it_once(tmp_path):
    run = Run(sh("echo up; sleep 60"), tmp_path)
    run.wait_for(lambda: "up" in run.text)
    started = time.time()
    run.process.stop()
    assert time.time() - started < 3 and not run.process.alive
    assert run.codes == [-15]            # SIGTERM
    run.process.stop()                   # again: nothing happens
    assert run.codes == [-15]


def test_stop_kills_a_process_that_ignores_sigterm(tmp_path):
    run = Run(sh("trap '' TERM; echo stubborn; while :; do sleep 0.05; done"), tmp_path)
    run.wait_for(lambda: "stubborn" in run.text)
    run.process.stop(grace=0.3)
    assert not run.process.alive and run.codes == [-9]


def test_stop_ends_what_the_child_started_too(tmp_path):
    marker = tmp_path / "child.pid"
    run = Run(sh(f"sleep 60 & echo $! > {marker}; echo spawned; wait"), tmp_path)
    run.wait_for(lambda: marker.exists() and "spawned" in run.text)
    pid = int(marker.read_text())
    run.process.stop()
    end = time.time() + 3
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError("the grandchild is still running")


def _alive(pid: int) -> bool:
    """Whether `pid` runs (a zombie, waiting to be reaped, does not)."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_the_fake_claude_runs_in_the_given_folder_with_the_given_environment(tmp_path):
    fake = make_fake_claude(tmp_path)
    log = tmp_path / "log.json"
    env = {"PATH": "/usr/bin:/bin", "FAKE_CLAUDE_LOG": str(log), "TERM": "xterm-256color"}
    run = Run([str(fake), "--flag"], tmp_path, env)
    run.wait_for(lambda: "> " in run.text)
    run.process.write(b"/exit\r")
    run.wait_for(lambda: run.codes)
    assert run.codes == [3] and "bye" in run.text
    assert '"--flag"' in log.read_text() and str(tmp_path) in log.read_text()


def test_a_process_that_outlives_its_terminal_is_killed_with_what_it_started(tmp_path, monkeypatch):
    import ptyprocess

    monkeypatch.setattr("slidemage.pty_process.REAP_WAIT_S", 0.3)

    def lost_terminal(self, size):      # the reader's view of a terminal that went away under a running program
        raise EOFError

    monkeypatch.setattr(ptyprocess.PtyProcess, "read", lost_terminal)
    marker = tmp_path / "pids"
    # the child ignores the hangup, so that only the kill of the whole group can end it
    run = Run(sh(f"(trap '' HUP; exec sleep 60) > /dev/null 2>&1 < /dev/null & echo $$ $! > {marker}; sleep 60"),
              tmp_path)
    run.wait_for(lambda: run.codes, seconds=10)
    assert run.codes == [-1] and not run.process.alive
    leader, child = (int(pid) for pid in marker.read_text().split())
    end = time.time() + 3
    while time.time() < end and any(_alive(pid) for pid in (leader, child)):
        time.sleep(0.05)
    assert not _alive(leader) and not _alive(child)


def test_stop_after_the_leader_ended_still_ends_what_it_started(tmp_path):
    marker = tmp_path / "child.pid"
    run = Run(sh(f"(trap '' HUP; exec sleep 60) > /dev/null 2>&1 < /dev/null & echo $! > {marker}; sleep 0.3; exit 0"), tmp_path)
    run.wait_for(lambda: run.codes)
    pid = int(marker.read_text())
    assert _alive(pid)
    run.process.stop()
    end = time.time() + 3
    while time.time() < end and _alive(pid):
        time.sleep(0.05)
    assert not _alive(pid)
