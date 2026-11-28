# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON store updates, cache invalidation and atomic directory swaps."""
import json
import os
import threading
import time

import pytest

from slidemage import app_settings, fileio, project
from slidemage.fileio import JsonStore, NewerFormatError, StaleFileError, UnreadableFileError
from slidemage.ui import layout_settings


@pytest.mark.parametrize("contents", [b"{broken", b"\xff", b"[]"])
def test_a_strict_update_refuses_a_damaged_file_and_leaves_it(tmp_path, contents):
    store = JsonStore(tmp_path / "s.json")
    assert store.read() == {}
    store.path.write_bytes(contents)
    assert store.read() == {}
    with pytest.raises(UnreadableFileError):
        store.update(lambda data: data.update(x=1))
    assert store.path.read_bytes() == contents
    store.update(lambda data: data.update(x=1), strict=False)
    assert json.loads(store.path.read_text()) == {"x": 1}


def test_the_stores_own_error_types_are_raised(tmp_path):
    class Damaged(Exception):
        pass

    class Newer(Exception):
        pass

    store = JsonStore(tmp_path / "s.json", version=2, newer=Newer, unreadable=lambda _error: Damaged())
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(Damaged):
        store.update(lambda data: None)
    store.path.write_text('{"version": 3}', encoding="utf-8")
    with pytest.raises(Newer):
        store.update(lambda data: None)
    with pytest.raises(NewerFormatError):
        JsonStore(store.path, version=2).read_strict()
    assert JsonStore(store.path, version=2).read() == {"version": 3}        # a newer file may still be read
    store.path.write_text('{"version": 2}', encoding="utf-8")
    assert store.update(lambda data: data.update(x=1))


@pytest.mark.parametrize("factory", [False, True], ids=["lock", "lock-factory"])
def test_update_holds_the_lock_and_calls_after_a_successful_write(tmp_path, factory):
    lock = threading.Lock()
    store = JsonStore(tmp_path / "sub" / "s.json", lock=(lambda: lock) if factory else lock, sort_keys=False)
    expected = '{\n  "b": 1,\n  "a": "é"\n}\n'
    seen = []

    def change(data):
        assert lock.locked() and not store.path.exists()
        data.update(b=1, a="é")

    def after(data):
        assert lock.locked()
        seen.append(store.path.read_text(encoding="utf-8"))

    assert store.update(change, after=after)
    assert not store.update(lambda data: False, after=after)
    assert seen == [expected] and not lock.locked()


def test_update_retries_an_outside_write_and_stops_at_the_attempt_limit(tmp_path):
    store = JsonStore(tmp_path / "s.json")
    store.update(lambda data: data.update(a=1))
    runs = []

    def change(data):
        runs.append(dict(data))
        if len(runs) == 1:
            fileio.write_json(store.path, {"a": 1, "other": True})
        data["b"] = 2

    assert store.update(change)
    assert runs == [{"a": 1}, {"a": 1, "other": True}]
    assert store.read() == {"a": 1, "b": 2, "other": True}

    def race_each_attempt(data):
        fileio.write_json(store.path, {"counter": data.get("counter", 0) + 1})
        data["b"] = 2

    with pytest.raises(StaleFileError):
        store.update(race_each_attempt, attempts=2)
    assert store.read() == {"counter": 2}


def test_reads_invalidate_cache_after_external_and_store_writes(tmp_path):
    path = tmp_path / "s.json"
    store = JsonStore(path, cache=True)
    fileio.write_json(path, {"a": 1})
    old = time.time() - 60  # older than the cache's racy timestamp window
    os.utime(path, (old, old))
    assert store.read() == {"a": 1}
    fileio.write_json(path, {"a": 2})  # same size, so the mtime detects the change
    os.utime(path, (old + 5, old + 5))
    assert store.read() == {"a": 2}
    first = store.read()
    first["a"] = 99
    assert store.read() == {"a": 2}  # the caller got a copy
    fileio.write_json(path, {"a": 3})
    os.utime(path, (old + 5, old + 5))
    assert store.read() == {"a": 2}
    fileio.clear_json_cache()
    assert store.read() == {"a": 3}
    store.update(lambda data: data.update(a=4))
    os.utime(path, (old + 5, old + 5))  # keep the old stamp to exercise write invalidation
    assert store.read() == {"a": 4}
    path.unlink()
    assert store.read() == {}


def test_swap_rolls_back_when_publishing_fails_and_retries_a_denied_rename(tmp_path, monkeypatch):
    staging, final, old = tmp_path / "staging", tmp_path / "final", tmp_path / ".old" / "backup"
    staging.mkdir()
    final.mkdir()
    (staging / "new").write_text("new")
    (final / "original").write_text("old")
    real, calls = os.replace, []
    monkeypatch.setattr(fileio.time, "sleep", lambda _seconds: None)

    def replace(source, target):
        calls.append((source, target))
        if len(calls) == 1:
            raise PermissionError("held by a virus scanner")
        if source == staging:
            raise OSError("cannot publish")
        real(source, target)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError, match="cannot publish"):
        fileio.swap_into_place(staging, final, old)
    assert calls == [(final, old), (final, old), (staging, final), (old, final)]
    assert (final / "original").read_text() == "old" and not old.exists()

    monkeypatch.setattr(os, "replace", real)
    fileio.swap_into_place(staging, final, old)
    assert (final / "new").read_text() == "new"
    assert (old / "original").read_text() == "old" and not staging.exists()


def test_settings_paths_follow_a_config_folder_set_after_import(tmp_path, monkeypatch):
    monkeypatch.undo()          # the autouse fixtures point both at a temporary file: undo them for this test
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    assert app_settings.machine_store_path() == tmp_path / "config" / "ai_settings.json"
    assert layout_settings.store_path() == tmp_path / "config" / "layout.json"
    layout_settings.set("k", 1)
    assert layout_settings.get("k") == 1 and (tmp_path / "config" / "layout.json").is_file()
