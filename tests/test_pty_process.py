# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A real terminal's I/O, size, exit, and process-group cleanup."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

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


def test_terminal_size_resize_input_output_and_exit_code(tmp_path):
    script = ("trap 'echo resized $(stty size); resized=yes' WINCH; stty size; "
              "while [ -z \"$resized\" ]; do sleep 0.05; done; read line; echo got:$line; exit 5")
    run = Run(sh(script), tmp_path, cols=97, rows=31)
    run.wait_for(lambda: "31 97" in run.text)
    run.process.resize(120, 40)
    run.wait_for(lambda: "resized 40 120" in run.text)
    run.process.write("héllo\n".encode())
    run.wait_for(lambda: run.codes)
    assert "got:héllo" in run.text
    assert run.codes == [5] and not run.process.alive


@pytest.mark.parametrize("script, grace, code", [
    ("echo up; sleep 60", 1.0, -15),
    ("trap '' TERM; echo up; while :; do sleep 0.05; done", 0.3, -9),
], ids=["sigterm", "sigkill"])
def test_stop_ends_the_process_and_reports_it_once(tmp_path, script, grace, code):
    run = Run(sh(script), tmp_path)
    run.wait_for(lambda: "up" in run.text)
    started = time.time()
    run.process.stop(grace=grace)
    assert time.time() - started < 3 and not run.process.alive
    assert run.codes == [code]
    run.process.stop()                   # again: nothing happens
    assert run.codes == [code]


def test_stop_ends_what_the_child_started_too(tmp_path):
    marker = tmp_path / "child.pid"
    run = Run(sh(f"sleep 60 & echo $! > {marker}; echo spawned; wait"), tmp_path)
    run.wait_for(lambda: marker.exists() and "spawned" in run.text)
    pid = int(marker.read_text())
    run.process.stop()
    run.wait_for(lambda: not _alive(pid), seconds=3)


def _alive(pid: int) -> bool:
    """Whether `pid` runs (a zombie, waiting to be reaped, does not)."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


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
    run.wait_for(lambda: not _alive(leader) and not _alive(child), seconds=3)


def test_stop_after_the_leader_ended_still_ends_what_it_started(tmp_path):
    marker = tmp_path / "child.pid"
    run = Run(sh(f"(trap '' HUP; exec sleep 60) > /dev/null 2>&1 < /dev/null & echo $! > {marker}; sleep 0.3; exit 0"), tmp_path)
    run.wait_for(lambda: run.codes)
    pid = int(marker.read_text())
    assert _alive(pid)
    run.process.stop()
    run.wait_for(lambda: not _alive(pid), seconds=3)
