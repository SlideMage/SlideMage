# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Presenter PDF file associations and their start-window controls."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

import slidemage
from slidemage.presentation import open_with
from slidemage.ui.presentation.presenter_window import PresenterStartWindow

ROOT = Path(slidemage.__file__).resolve().parents[2]
EXE = "C:\\Program Files\\Slide Mage\\SlideMagePresenter.exe"
OTHER_PDF = open_with.OPEN_WITH_KEY      # .pdf\OpenWithProgids


class FakeRegistry:
    """A dict-backed stand-in for the HKCU calls open_with makes: values by (key, name), plus the set of keys."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], tuple[str, Optional[str]]] = {}     # (kind, text)

    def keys(self) -> set[str]:
        return {key for key, _name in self.values}

    def set_value(self, key, name, value):
        self.values[(key, name)] = ("REG_SZ", value)

    def set_empty_value(self, key, name):
        self.values[(key, name)] = ("REG_NONE", None)

    def get_value(self, key, name):
        kind, value = self.values.get((key, name), (None, None))
        return value if kind == "REG_SZ" else None

    def delete_value(self, key, name):
        self.values.pop((key, name), None)

    def delete_tree(self, key):
        for stored in [k for k in self.values if k[0] == key or k[0].startswith(key + "\\")]:
            del self.values[stored]


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(open_with, "_windows", lambda: True)
    registry = FakeRegistry()
    registry.set_empty_value(OTHER_PDF, "AcroExch.Document")      # someone else's entry, must survive
    registry.set_value("Software\\Classes\\Applications\\Other.exe\\shell\\open\\command", "", '"x" "%1"')
    return registry


@pytest.fixture
def linux(monkeypatch, tmp_path):
    monkeypatch.setattr(open_with, "_windows", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    calls: list[Path] = []
    return calls


@pytest.mark.parametrize("platform, expected", [("win32", True), ("linux", True), ("darwin", False)])
def test_supported_only_when_frozen_on_windows_or_linux(monkeypatch, platform, expected):
    monkeypatch.setattr(open_with.sys, "frozen", True, raising=False)
    monkeypatch.setattr(open_with.sys, "platform", platform)
    assert open_with.supported() is expected


def test_windows_registration_round_trips_without_touching_other_handlers(windows):
    before = dict(windows.values)
    assert open_with.status(EXE, registry=windows) == "off"
    notified = []
    open_with.register(EXE, registry=windows, notify=lambda: notified.append("register"))
    assert open_with.status(EXE.lower().replace("\\", "/"), registry=windows) == "on"
    assert open_with.status("D:\\Elsewhere\\SlideMagePresenter.exe", registry=windows) == "moved"
    assert windows.values[(OTHER_PDF, "SlideMage.Presenter.pdf")] == ("REG_NONE", None)
    assert all(windows.values[key] == value for key, value in before.items())
    assert (r"Software\Classes\.pdf", "") not in windows.values
    assert not any("FileExts" in key for key in windows.keys())
    open_with.unregister(registry=windows, notify=lambda: notified.append("unregister"))
    assert windows.values == before
    assert notified == ["register", "unregister"]
    assert open_with.status(EXE, registry=windows) == "off"
    open_with.unregister(registry=windows, notify=lambda: None)      # nothing left to remove is fine
    assert windows.values == before


def test_linux_status_and_unregister(linux, tmp_path):
    exe = "/opt/slide mage/SlideMagePresenter"
    assert open_with.status(exe) == "off"
    open_with.register(exe, runner=linux.append)
    path = tmp_path / "share/applications/slidemage-presenter.desktop"
    entry = path.read_text(encoding="utf-8")
    assert 'Exec="/opt/slide mage/SlideMagePresenter" %f' in entry and "MimeType=application/pdf;" in entry
    assert linux == [path.parent]
    assert open_with.status(exe) == "on"
    assert open_with.status("/home/me/SlideMagePresenter") == "moved"
    open_with.unregister(runner=linux.append)
    assert not path.exists()
    assert open_with.status(exe) == "off"
    assert len(linux) == 2
    open_with.unregister(runner=linux.append)          # already gone: fine, and nothing to refresh
    assert len(linux) == 2


def test_the_packaging_template_agrees_with_the_embedded_entry():
    def keys(text: str) -> dict[str, str]:
        found = {}
        for line in text.splitlines():
            if "=" in line and not line.startswith("#"):
                key, _sep, value = line.partition("=")
                found[key] = value
        return found

    template = keys((ROOT / "packaging" / "slidemage-presenter.desktop.template").read_text(encoding="utf-8"))
    embedded = keys(open_with.desktop_text("/x/SlideMagePresenter"))
    for key in ("Type", "Name", "Comment", "Terminal", "Categories", "MimeType", "StartupWMClass"):
        assert template[key] == embedded[key], key
    assert template["Exec"].endswith(" %f") and embedded["Exec"].endswith(" %f")
    assert embedded["MimeType"] == "application/pdf;"


def test_the_row_is_hidden_when_not_supported(qapp):
    win = PresenterStartWindow()
    assert win.open_with_bar.isHidden()


@pytest.fixture
def fake_backend(monkeypatch):
    state = {"value": "off", "calls": [], "fail": None}

    def register(executable):
        state["calls"].append(("register", executable))
        if state["fail"]:
            raise PermissionError(state["fail"])
        state["value"] = "on"

    def unregister():
        state["calls"].append(("unregister",))
        state["value"] = "off"

    monkeypatch.setattr(open_with, "supported", lambda: True)
    monkeypatch.setattr(open_with, "status", lambda executable: state["value"])
    monkeypatch.setattr(open_with, "register", register)
    monkeypatch.setattr(open_with, "unregister", unregister)
    return state


def test_the_button_follows_the_status(qapp, fake_backend):
    win = PresenterStartWindow()
    assert not win.open_with_bar.isHidden()
    assert win.open_with_button.text() == "Add to “Open with”"
    win.open_with_button.click()
    assert fake_backend["calls"][0][0] == "register"
    assert win.open_with_button.text() == "Remove from “Open with”"
    win.open_with_button.click()
    assert fake_backend["calls"][1] == ("unregister",)
    assert win.open_with_button.text() == "Add to “Open with”"


def test_an_error_is_shown_not_raised(qapp, fake_backend):
    fake_backend["fail"] = "access denied"
    win = PresenterStartWindow()
    win.open_with_button.click()
    assert "access denied" in win.open_with_label.text()
    assert win.open_with_button.text() == "Add to “Open with”"
