# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Help → Check for updates also looks at the installed citation formats."""

from types import SimpleNamespace

from slidemage import updater
from slidemage.ui.workspace import maintenance


def make_window():
    window = SimpleNamespace(logged=[], toast=SimpleNamespace(shown=[]))
    window.log = window.logged.append
    window.toast.show_message = lambda text, *a, **k: window.toast.shown.append(text)
    return window


class Fetched:
    discarded = False

    def discard(self):
        self.discarded = True


def test_a_manual_check_says_when_the_formats_are_up_to_date():
    window = make_window()
    maintenance.on_citation_updates_done(window, ([], {}), manual=True)
    assert window.toast.shown == ["Your citation formats are up to date."]
    maintenance.on_citation_updates_done(window, ([], {}))        # the check at the start says nothing
    assert len(window.toast.shown) == 1


def test_a_manual_check_offers_an_update_even_when_updates_are_off(monkeypatch):
    updater.set_update_mode("off")
    window, offered = make_window(), []
    offer = SimpleNamespace(key="apa", name="APA", fetched=Fetched())
    monkeypatch.setattr(maintenance, "offer_citation_update", lambda win, o: offered.append(o))
    monkeypatch.setattr(maintenance, "install_citation_update", lambda *a, **k: offered.append("installed"))
    monkeypatch.setattr(maintenance, "_auto", lambda sources, key: True)       # even its own "automatic" only offers
    maintenance.on_citation_updates_done(window, ([offer], {}), manual=True)
    assert offered == [offer] and not offer.fetched.discarded
    offered.clear()
    maintenance.on_citation_updates_done(window, ([offer], {}))               # without a click: nothing, discarded
    assert offered == [] and offer.fetched.discarded


def test_a_failed_manual_check_is_said():
    window = make_window()
    maintenance.on_citation_updates_done(window, RuntimeError("offline"), manual=True)
    assert "offline" in window.toast.shown[0] and "offline" in window.logged[0]
