# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The error log (diagnostics.py): where SlideMage's own logging goes, its format, rotation and masking."""
import logging
import subprocess
import sys
import threading

import pytest

from slidemage import diagnostics, project


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setenv(diagnostics.DIR_ENV, str(tmp_path / "logs"))
    diagnostics.reset()
    yield tmp_path / "logs"
    diagnostics.reset()


def test_warnings_reach_the_error_log_in_columns_and_info_does_not(logs):
    diagnostics.setup("app")
    logging.getLogger("slidemage.plugins.installer").warning("could not restore %s", "x.zip")
    logging.getLogger("slidemage.themes").info("only in the debug log")
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("slidemage.themes").exception("theme check failed")
    text = (logs / diagnostics.ERROR_LOG).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "WARNING  plugins.installer" in lines[0] and "could not restore x.zip" in lines[0]
    assert f" app:{__import__('os').getpid()} MainThread  " in lines[0]
    assert "only in the debug log" not in text
    assert "ERROR    themes" in text and "    Traceback (most recent call last):" in text
    assert "    ValueError: boom" in text


def test_nothing_is_written_until_something_is_logged(logs):
    diagnostics.setup("hook")
    assert not logs.exists()
    assert diagnostics.error_log_path() == logs / diagnostics.ERROR_LOG


def test_setup_runs_once_and_reset_undoes_it(logs):
    hook = sys.excepthook
    diagnostics.setup("app")
    diagnostics.setup("app")
    assert len(logging.getLogger("slidemage").handlers) == 2 - (sys.stderr is None)
    assert sys.excepthook is not hook
    diagnostics.reset()
    assert logging.getLogger("slidemage").handlers == [] and sys.excepthook is hook


def test_the_default_folder_is_logs_in_the_cache_folder(monkeypatch):
    monkeypatch.delenv(diagnostics.DIR_ENV, raising=False)
    assert diagnostics.log_dir() == project.cache_dir() / "logs"


def test_a_full_file_moves_to_dot_1_and_the_oldest_drops_off(tmp_path):
    path = tmp_path / "x.log"
    handler = diagnostics.RotatingFile(path, max_bytes=50, backups=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for number in range(8):
        handler.emit(logging.makeLogRecord({"msg": f"line {number} " + "x" * 30}))
    handler.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.log", "x.log.1", "x.log.2"]
    # A file takes lines until it holds max_bytes: two of these each, the newest in x.log, lines 0 and 1 dropped.
    assert path.read_text().splitlines()[0].startswith("line 6")
    assert (tmp_path / "x.log.1").read_text().startswith("line 4")
    assert (tmp_path / "x.log.2").read_text().startswith("line 2")


def test_keys_and_tokens_are_masked(logs, monkeypatch):
    monkeypatch.setenv("SLIDEMAGE_GITHUB_TOKEN", "plain-secret-value-123")
    diagnostics.setup("app")
    diagnostics.add_secret("short")             # too short to mask safely: left alone
    diagnostics.add_secret("stored-credential-xyz")
    logging.getLogger("slidemage.update").warning(
        "key sk-ant-api03-abcdefghijklmnop, token ghp_%s, header Bearer abc.def-ghi_jkl, %s, %s, short",
        "A" * 36, "plain-secret-value-123", "stored-credential-xyz")
    text = (logs / diagnostics.ERROR_LOG).read_text(encoding="utf-8")
    for secret in ("sk-ant-api03", "ghp_", "abc.def-ghi_jkl", "plain-secret-value-123", "stored-credential-xyz"):
        assert secret not in text
    assert text.count(diagnostics.REDACTED) == 5 and text.rstrip().endswith("short")


def test_uncaught_exceptions_in_threads_are_logged(logs, monkeypatch):
    diagnostics.setup("app")
    seen = []
    monkeypatch.setitem(diagnostics._state, "threading_excepthook", seen.append)
    worker = threading.Thread(target=lambda: 1 / 0, name="Worker-7")
    worker.start()
    worker.join()
    text = (logs / diagnostics.ERROR_LOG).read_text(encoding="utf-8")
    assert "CRITICAL" in text and "uncaught exception in thread Worker-7" in text and "ZeroDivisionError" in text
    assert len(seen) == 1                       # and the previous hook still runs


def test_an_uncaught_exception_of_a_process_is_logged_and_still_printed(tmp_path):
    code = ("import sys; from slidemage import diagnostics; diagnostics.setup('app');"
            "import logging; logging.getLogger('slidemage.x').warning('before'); raise RuntimeError('at the top')")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                          env={**__import__("os").environ, diagnostics.DIR_ENV: str(tmp_path)})
    text = (tmp_path / diagnostics.ERROR_LOG).read_text(encoding="utf-8")
    assert "WARNING  x" in text and "CRITICAL" in text and "RuntimeError: at the top" in text
    assert done.stderr.count("RuntimeError: at the top") == 1   # printed once, by Python's own hook
    assert "before" in done.stderr


def test_qt_warnings_are_logged_with_their_area(logs, qapp):
    from PySide6.QtCore import qWarning

    diagnostics.setup("app")
    diagnostics.install_qt_message_handler()
    qWarning("a Qt warning")
    text = (logs / diagnostics.ERROR_LOG).read_text(encoding="utf-8")
    assert "WARNING  qt" in text and "a Qt warning" in text


# -- the debug log (step 2) -------------------------------------------------------------------------------------


@pytest.fixture
def no_debug_env(monkeypatch):
    monkeypatch.delenv(diagnostics.DEBUG_ENV, raising=False)


def _sessions(logs):
    return sorted((logs / diagnostics.DEBUG_DIR).glob("app_*.log"))


def test_debug_is_off_unless_asked_for(logs, no_debug_env):
    diagnostics.setup("app")
    logging.getLogger("slidemage.compile").debug("job started")
    assert not diagnostics.debug_enabled() and diagnostics.debug_log_path() is None
    assert not (logs / diagnostics.DEBUG_DIR).exists()


def test_the_environment_turns_it_on_with_a_header_and_debug_lines(logs, monkeypatch):
    monkeypatch.setenv(diagnostics.DEBUG_ENV, "1")
    diagnostics.setup("app")
    logging.getLogger("slidemage.compile").debug("job started deck=%s", "micro-01")
    [session] = _sessions(logs)
    assert diagnostics.debug_log_path() == session
    text = session.read_text(encoding="utf-8")
    assert "INFO     startup" in text and "debug log started" in text
    assert "    SlideMage v" in text and "    Python " in text and "    lualatex: " in text
    assert f"    ${diagnostics.DEBUG_ENV} = 1" in text
    assert "DEBUG    compile" in text and "job started deck=micro-01" in text
    assert not (logs / diagnostics.ERROR_LOG).exists()         # no warning: the error log stays empty


def test_secrets_in_the_environment_are_named_not_shown(logs, monkeypatch):
    monkeypatch.setenv(diagnostics.DEBUG_ENV, "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abcdefghijklmnopqrstuvwxyz")
    diagnostics.setup("app")
    text = _sessions(logs)[0].read_text(encoding="utf-8")
    assert f"$ANTHROPIC_API_KEY = {diagnostics.REDACTED}" in text and "abcdefghijkl" not in text


def test_the_saved_setting_holds_for_later_processes_and_the_environment_overrides_it(logs, no_debug_env,
                                                                                     monkeypatch):
    diagnostics.setup("app")
    diagnostics.set_debug(True)
    assert diagnostics.debug_enabled() and diagnostics.saved()
    diagnostics.reset()
    diagnostics.setup("hook")                       # a later process, say a Claude Code hook
    logging.getLogger("slidemage.plugins.hook").debug("hook ran")
    assert "hook ran" in (logs / diagnostics.DEBUG_DIR / "hook.log").read_text(encoding="utf-8")
    diagnostics.reset()
    monkeypatch.setenv(diagnostics.DEBUG_ENV, "0")
    diagnostics.setup("app")
    assert not diagnostics.debug_enabled()


def test_turning_it_off_at_runtime_stops_the_file_and_the_debug_records(logs, no_debug_env):
    diagnostics.setup("app")
    diagnostics.set_debug(True)
    path = diagnostics.debug_log_path()
    diagnostics.set_debug(False)
    logging.getLogger("slidemage.compile").debug("after it was turned off")
    text = path.read_text(encoding="utf-8")
    assert "debug log turned off" in text and "after it was turned off" not in text
    assert not diagnostics.saved() and not logging.getLogger("slidemage").isEnabledFor(logging.DEBUG)


def test_debug_flag_is_passed_on_until_it_is_turned_off(logs, no_debug_env):
    diagnostics.setup("app", debug=True)
    assert diagnostics.debug_enabled() and __import__("os").environ[diagnostics.DEBUG_ENV] == "1"
    assert not diagnostics.saved()                  # --debug is for this run only
    diagnostics.set_debug(False, persist=False)
    assert diagnostics.DEBUG_ENV not in __import__("os").environ


def test_the_oldest_files_go_beyond_the_session_count_and_the_size(tmp_path):
    import os

    for number in range(6):
        path = tmp_path / f"app_2026-10-0{number}_120000_1.log"
        path.write_text("x" * 10)
        os.utime(path, (1000 + number, 1000 + number))
    big = tmp_path / "hook.log"
    big.write_text("y" * 100)
    os.utime(big, (900, 900))
    diagnostics.clean_up(tmp_path, keep_sessions=4, keep_bytes=1000)
    assert sorted(p.name[:14] for p in tmp_path.glob("app_*")) == [f"app_2026-10-0{n}" for n in (2, 3, 4, 5)]
    assert big.exists()
    diagnostics.clean_up(tmp_path, keep_sessions=4, keep_bytes=45)
    assert not big.exists() and len(list(tmp_path.glob("app_*"))) == 4


def test_the_cli_takes_the_debug_flag():
    from slidemage import cli

    assert cli._role(["--claude-hook"]) == "hook" and cli._role([]) == "app"
