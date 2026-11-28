# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Debug instrumentation and redaction."""
import io
import logging
import sys
import urllib.error
from types import SimpleNamespace

import pytest

from slidemage import app_settings, compile_log, compiler, diagnostics, updater
from slidemage.project import ProjectContext


def lines(caplog, area: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == f"slidemage.{area}"]


@pytest.fixture
def debug(caplog):
    caplog.set_level(logging.DEBUG, logger="slidemage")
    return caplog


def test_event_and_timed_build_nothing_while_the_log_is_off(caplog):
    caplog.set_level(logging.WARNING, logger="slidemage")

    class Loud:
        def __str__(self):
            raise AssertionError("formatted while off")

    log = logging.getLogger("slidemage.x")
    diagnostics.event(log, "job", value=Loud())
    with diagnostics.timed(log, "job", value=Loud()) as info:
        info["more"] = Loud()
    assert caplog.records == []


def test_logged_names_the_function_and_keeps_its_result(debug):
    @diagnostics.logged("maintenance")
    def check(value):
        return value + 1

    assert check(1) == 2 and check.__name__ == "check"
    assert lines(debug, "maintenance")[0].startswith("check seconds=")


def test_process_logging_covers_exit_and_spawn_failure(debug, tmp_path):
    code = compiler.run_streamed([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], cwd=tmp_path,
                                 env=None, log=lambda line: None)
    started, ended = lines(debug, "compile")
    assert code == 3
    assert started.startswith("process started cmd=") and "raise SystemExit(3)" in started
    assert " exit=3 seconds=" in ended

    with pytest.raises(FileNotFoundError):
        compiler.run_streamed(["no-such-program-here"], cwd=tmp_path, env=None, log=lambda line: None)
    assert "program=no-such-program-here exit=None" in lines(debug, "compile")[-1]


def test_a_job_logs_its_start_its_banners_and_its_result(debug):
    seen = []

    @compiler._logged_job
    def run(ctx, job, log, cancel=None):
        log(compile_log.compiling("micro", "micro-de"))
        log("Run number 1 of rule 'lualatex'")
        log(compile_log.failed("micro-de", "stopped by user"))
        return False

    job = SimpleNamespace(jobname="micro-de", pages=None, deck=SimpleNamespace(name="micro"))
    assert run(None, job, seen.append, cancel=None) is False
    assert len(seen) == 3                                       # the compile log is untouched
    said = lines(debug, "compile")
    assert said[0] == "job started deck=micro job=micro-de pages=None"
    assert "Compiling micro" in said[1] and "stopped by user" in said[2] and len(said) == 4    # no latexmk chatter
    assert said[3].startswith("job finished job=micro-de ok=False seconds=")


class _Response(io.BytesIO):
    status = 200


def test_update_logging_records_success_and_failure_without_the_token(debug, monkeypatch):
    monkeypatch.setenv(updater.TOKEN_ENV_VAR, "ghp_" + "A" * 36)
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Response(b"{}"))
    assert updater._get_json("https://api.github.com/x", 5) == {}
    [said] = lines(debug, "update")
    assert said.startswith("GET url=https://api.github.com/x status=200 seconds=") and "ghp_" not in debug.text

    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError("u", 404, "no", None, None)

    monkeypatch.setattr(updater.urllib.request, "urlopen", refuse)
    with pytest.raises(updater.UpdateError):
        updater._get_json("https://api.github.com/x", 5)
    assert "error='HTTPError 404'" in lines(debug, "update")[-1]


def test_a_changed_setting_logs_its_key_not_its_value(debug, tmp_path):
    project = ProjectContext.at(tmp_path)
    app_settings.set(project, "cloud_conn", "secret-value")
    assert lines(debug, "settings") == ["setting changed key=cloud_conn"] and "secret-value" not in debug.text


def test_the_terminal_logs_the_program_not_its_arguments_or_environment(debug, tmp_path, monkeypatch, qapp):
    from slidemage.ui.workspace.terminal import service

    class FakePty:
        alive = True

        def __init__(self, *args):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(service, "PtyProcess", FakePty)
    session = service.PtySession()
    session.start(["C:/x/claude.exe", "--prompt", "my slide text"], {"ANTHROPIC_API_KEY": "secret"}, tmp_path, 80, 24)
    session._on_ended(session._generation, 7)
    session.stop()
    said = lines(debug, "terminal")
    assert said[0].startswith("started program=claude.exe cwd=") and said[0].endswith("size=80x24")
    assert "exited code=7" in said and "stopped" in said
    assert "my slide text" not in debug.text and "secret" not in debug.text
