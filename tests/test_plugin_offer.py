# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-start plugin sheet: shown once per machine, the order and content of its list, nothing ticked,
Not now and every other way of closing it write the flag, Install selected (hash checked) ends in Restart now,
offline and too-new texts. The catalogue and the download are replaced; nothing touches the network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

from conftest import qapp as qapp
from conftest import wait_until
from slidemage.plugins import catalogue, installer, loader, upgrade
from slidemage.ui.dialogs import plugin_offer
from slidemage.ui.dialogs.plugin_offer import PluginOfferSheet
from slidemage.ui.workspace import maintenance
from test_plugin_settings_tab import (answer, catalogue_json, entry, fake_download, isolated as isolated, load_dev,
                                      sha, zip_plugin)


def texts(widget):
    return "\n".join(label.text() for label in widget.findChildren(QLabel) if not label.isHidden())


def serve(monkeypatch, *entries, error=None):
    def fetch(timeout=10):
        if error is not None:
            raise error
        return catalogue.parse(catalogue_json(*entries))

    monkeypatch.setattr(catalogue, "fetch", fetch)


def open_sheet(qapp, **kwargs):
    sheet = PluginOfferSheet(**kwargs)
    sheet.show()
    wait_until(lambda: sheet._job is None)
    return sheet


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(PluginOfferSheet, "open_url", lambda self, url: opened.append(url))
    return opened


@pytest.fixture(autouse=True)
def cleanup_offer_sheets():
    """A shown modal sheet must not block windows in subsequent tests."""
    app = QApplication.instance()
    existing = set(app.topLevelWidgets()) if app is not None else set()
    yield
    app = QApplication.instance()
    if app is not None:
        for sheet in set(app.topLevelWidgets()) - existing:
            if isinstance(sheet, PluginOfferSheet):
                sheet.hide()  # close/reject would write the offer-seen flag
                sheet.deleteLater()
                QCoreApplication.sendPostedEvents(sheet, QEvent.Type.DeferredDelete)


CAT = catalogue.parse(catalogue_json(entry("alpha", "Alpha")))


# -- when it is shown

def window_with_log():
    return SimpleNamespace(project=SimpleNamespace(root="/p"), logged=[], log=lambda text: None)


def test_nothing_offerable_shows_no_sheet_and_writes_no_flag(monkeypatch, qapp):
    shown = []
    monkeypatch.setattr(maintenance, "PluginOfferSheet", lambda *a, **k: shown.append(1))
    for plugins in ((), (entry("future", requires=">=99"),)):
        maintenance.on_plugin_offer_fetched(window_with_log(), catalogue.parse(catalogue_json(*plugins)))
    load_dev(monkeypatch, "hello")
    maintenance.on_plugin_offer_fetched(window_with_log(), catalogue.parse(catalogue_json(entry("hello"))))
    assert shown == [] and not upgrade.offer_seen()


@pytest.mark.parametrize("error", [catalogue.CatalogueError("offline"), catalogue.CatalogueTooNew()])
def test_offline_or_too_new_shows_no_sheet_and_writes_no_flag(monkeypatch, qapp, error):
    monkeypatch.setattr(maintenance, "PluginOfferSheet", lambda *a, **k: pytest.fail("shown"))
    logged = []
    window = SimpleNamespace(project=None, log=logged.append)
    maintenance.on_plugin_offer_fetched(window, error)
    assert logged and not upgrade.offer_seen()


def test_offerable_opens_the_sheet_with_the_prefetched_catalogue(monkeypatch, qapp):
    def no_fetch(timeout=10):
        raise AssertionError("fetched again")

    monkeypatch.setattr(catalogue, "fetch", no_fetch)
    opened = []
    monkeypatch.setattr(PluginOfferSheet, "exec", lambda self: (opened.append(self), self.close_button.click()))
    real = PluginOfferSheet
    monkeypatch.setattr(maintenance, "PluginOfferSheet", lambda parent, **kw: real(None, **kw))
    maintenance.on_plugin_offer_fetched(window_with_log(), CAT)
    assert len(opened) == 1 and list(opened[0].rows) == ["alpha"] and upgrade.offer_seen()


def test_show_fetches_on_a_thread_and_emits(monkeypatch, qapp):
    monkeypatch.setattr(catalogue, "fetch", lambda timeout=10: CAT)
    got = []
    window = SimpleNamespace(project=None, plugin_offer_fetched=SimpleNamespace(emit=got.append))
    maintenance.show_plugin_offer(window)
    wait_until(lambda: got)
    assert got == [CAT]
    upgrade.mark_offer_seen()
    maintenance.show_plugin_offer(window)
    import time
    time.sleep(0.1)
    assert got == [CAT]


def test_scheduled_only_while_the_flag_is_missing(monkeypatch):
    scheduled = []
    monkeypatch.setattr(maintenance.QTimer, "singleShot", lambda *a: scheduled.append(a))
    maintenance.schedule_plugin_offer(SimpleNamespace())
    assert len(scheduled) == 1 and scheduled[0][0] == maintenance.PLUGIN_OFFER_DELAY_MS
    upgrade.mark_offer_seen()
    maintenance.schedule_plugin_offer(SimpleNamespace())
    assert len(scheduled) == 1


def test_shown_on_the_first_start_and_not_again(monkeypatch, qapp):
    shown = []

    class FakeSheet:
        restart_requested = False

        def __init__(self, parent, *, preselected, catalogue_data, onboarding=True):
            shown.append(preselected)

        def exec(self):
            upgrade.mark_offer_seen()           # what closing the real sheet does

    monkeypatch.setattr(maintenance, "PluginOfferSheet", FakeSheet)
    window = SimpleNamespace(project=SimpleNamespace(root="/p"))
    maintenance.on_plugin_offer_fetched(window, CAT)
    maintenance.on_plugin_offer_fetched(window, CAT)
    assert shown == [{}]


def test_the_restart_the_sheet_asked_for(monkeypatch, qapp):
    class FakeSheet:
        restart_requested = True

        def __init__(self, parent, *, preselected, catalogue_data, onboarding=True):
            pass

        def exec(self):
            pass

    monkeypatch.setattr(maintenance, "PluginOfferSheet", FakeSheet)
    relaunched = []
    window = SimpleNamespace(project=SimpleNamespace(root="/p"), relaunch_with_project=relaunched.append)
    maintenance.on_plugin_offer_fetched(window, CAT)
    assert relaunched == ["/p"]


def test_a_failing_sheet_leaves_the_flag_alone(monkeypatch, qapp):
    def broken(parent, *, preselected, catalogue_data, onboarding=True):
        raise RuntimeError("no sheet")

    monkeypatch.setattr(maintenance, "PluginOfferSheet", broken)
    with pytest.raises(RuntimeError):
        maintenance.on_plugin_offer_fetched(SimpleNamespace(project=SimpleNamespace(root="/p")), CAT)
    assert not upgrade.offer_seen()


def migration_env(monkeypatch, used=None, release="v8.0.0"):
    monkeypatch.setattr(upgrade, "MIGRATIONS", [upgrade.Migration("alpha", release)])
    monkeypatch.setattr(upgrade, "used_features", lambda ctx: {"alpha": "Your decks use Alpha"} if used is None else used)
    opened = []

    class FakeSheet:
        restart_requested = False

        def __init__(self, parent, *, preselected, catalogue_data, onboarding=True):
            self.args = (dict(preselected), onboarding)
            opened.append(self.args)
            self.ids = dict(preselected)
            self.onboarding = onboarding

        def exec(self):                         # what closing the real sheet does
            if self.onboarding:
                upgrade.mark_offer_seen()
            upgrade.mark_migrations_seen(self.ids)

    monkeypatch.setattr(maintenance, "PluginOfferSheet", FakeSheet)
    return opened


def test_a_due_migration_shows_the_sheet_after_onboarding_and_is_marked_seen(monkeypatch, qapp):
    opened = migration_env(monkeypatch)
    upgrade.mark_offer_seen()
    window = window_with_log()
    maintenance.on_plugin_offer_fetched(window, CAT)
    maintenance.on_plugin_offer_fetched(window, CAT)
    assert opened == [({"alpha": "Your decks use Alpha"}, False)]
    assert upgrade.migrations_seen() == {"alpha"}


def test_both_due_on_the_first_start_make_one_sheet(monkeypatch, qapp):
    opened = migration_env(monkeypatch)
    window = window_with_log()
    maintenance.on_plugin_offer_fetched(window, CAT)
    maintenance.on_plugin_offer_fetched(window, CAT)
    assert opened == [({"alpha": "Your decks use Alpha"}, True)]
    assert upgrade.offer_seen() and upgrade.migrations_seen() == {"alpha"}


def test_no_migration_sheet_when_not_used_installed_or_too_new(monkeypatch, qapp):
    upgrade.mark_offer_seen()
    opened = migration_env(monkeypatch, used={})
    maintenance.on_plugin_offer_fetched(window_with_log(), CAT)
    opened = migration_env(monkeypatch, release="v99.0.0")
    maintenance.on_plugin_offer_fetched(window_with_log(), CAT)
    assert opened == [] and upgrade.migrations_seen() == set()
    opened = migration_env(monkeypatch)
    monkeypatch.setattr(upgrade, "MIGRATIONS", [upgrade.Migration("hello", "v8.0.0")])
    monkeypatch.setattr(upgrade, "used_features", lambda ctx: {"hello": "why"})
    load_dev(monkeypatch, "hello")                      # installed: not due
    maintenance.on_plugin_offer_fetched(window_with_log(), catalogue.parse(catalogue_json(entry("hello"), entry("alpha"))))
    assert opened == [] and upgrade.migrations_seen() == set()


def test_offline_marks_no_migration(monkeypatch, qapp):
    upgrade.mark_offer_seen()
    opened = migration_env(monkeypatch)
    maintenance.on_plugin_offer_fetched(window_with_log(), catalogue.CatalogueError("offline"))
    assert opened == [] and upgrade.migrations_seen() == set()


def test_the_migration_sheet_lists_only_the_migrated_plugins_and_marks_them_seen(qapp, monkeypatch):
    serve(monkeypatch, entry("alpha", "Alpha"), entry("beta", "Beta"))
    upgrade.mark_offer_seen()
    sheet = open_sheet(qapp, preselected={"alpha": "Your decks use Alpha"}, onboarding=False)
    assert sheet.windowTitle() == plugin_offer.MIGRATION_TITLE or plugin_offer.MIGRATION_TITLE in texts(sheet)
    assert list(sheet.rows) == ["alpha"] and sheet.rows["alpha"].check.isChecked()
    assert "Your decks use Alpha" in texts(sheet)
    assert upgrade.migrations_seen() == set()           # opening alone writes nothing
    sheet.close_button.click()
    assert upgrade.migrations_seen() == {"alpha"}


# -- the list

def test_loading_text_then_sections_in_order_with_nothing_ticked(qapp, monkeypatch):
    serve(monkeypatch, entry("zeta", "Zeta"), entry("beta", "Beta", recommended=True, network=("api.b.org",)),
          entry("alpha", "Alpha", recommended=True), entry("future", "Future", requires=">=99"))
    sheet = PluginOfferSheet()
    assert plugin_offer.LOADING == "Loading the list of plugins…" and sheet.status.text() == plugin_offer.LOADING
    wait_until(lambda: sheet._job is None)
    sheet.show()
    assert list(sheet.rows) == ["alpha", "beta", "future", "zeta"]
    order = [label.text() for label in sheet.findChildren(QLabel)
             if label.text() in ("Recommended", "More plugins")]
    assert order == ["Recommended", "More plugins"]
    assert not any(box.isChecked() for box in sheet.findChildren(QCheckBox))
    beta = texts(sheet.rows["beta"])
    assert "Beta does things." in beta and "Needs: Ollama" in beta and "Contacts: api.b.org" in beta
    assert "Contacts nothing on the network" in texts(sheet.rows["alpha"])
    assert plugin_offer.INTRO in texts(sheet)
    assert sheet.page_button.text() == "See all plugins and what they do"
    assert sheet.install_button.text() == "Install selected" and sheet.close_button.text() == "Not now"
    assert not sheet.install_button.isEnabled()            # nothing ticked
    sheet.rows["alpha"].check.setChecked(True)
    assert sheet.install_button.isEnabled()


def test_recommended_come_before_the_rest_in_the_layout(qapp, monkeypatch):
    serve(monkeypatch, entry("zeta", "Zeta"), entry("alpha", "Alpha", recommended=True))
    sheet = open_sheet(qapp)
    assert [sheet._list.itemAt(i).widget().text() if isinstance(sheet._list.itemAt(i).widget(), QLabel)
            else sheet._list.itemAt(i).widget().plugin_id for i in range(sheet._list.count())] == [
        "Recommended", "alpha", "More plugins", "zeta"]


def test_a_plugin_without_a_fitting_release_is_greyed(qapp, monkeypatch):
    serve(monkeypatch, entry("future", "Future", requires=">=99"), entry("ok", "Ok"))
    sheet = open_sheet(qapp)
    future = sheet.rows["future"]
    assert not future.check.isEnabled() and "Needs a newer SlideMage" in texts(future)
    assert sheet.rows["ok"].check.isEnabled()
    assert sheet.checked() == []


def test_installed_plugins_are_not_offered(qapp, monkeypatch):
    load_dev(monkeypatch, "hello")
    serve(monkeypatch, entry("hello"), entry("other", "Other"))
    sheet = open_sheet(qapp)
    assert list(sheet.rows) == ["other"]
    serve(monkeypatch, entry("hello"))
    sheet = open_sheet(qapp)
    assert sheet.rows == {} and plugin_offer.ALL_INSTALLED in texts(sheet)


def test_more_and_the_footer_link_open_pages(qapp, monkeypatch, no_real_browser):
    serve(monkeypatch, entry("alpha", "Alpha"))
    sheet = open_sheet(qapp)
    sheet.rows["alpha"].more_button.click()
    sheet.page_button.click()
    assert no_real_browser == ["https://example.org/", "https://example.org/all/"]


def test_preselected_plugins_are_ticked_with_their_reason(qapp, monkeypatch):
    serve(monkeypatch, entry("claude", "Claude", recommended=True), entry("other", "Other"))
    sheet = open_sheet(qapp, preselected={"claude": "You have an Anthropic API key"})
    assert sheet.rows["claude"].check.isChecked() and not sheet.rows["other"].check.isChecked()
    assert "You have an Anthropic API key" in texts(sheet.rows["claude"])
    assert sheet.install_button.isEnabled()


# -- offline and too new

def test_offline_says_so_and_offers_a_file(qapp, monkeypatch, tmp_path):
    serve(monkeypatch, error=catalogue.CatalogueError("Could not load the plugin list: offline"))
    sheet = open_sheet(qapp)
    assert sheet.status.text() == "The list of plugins could not be loaded."
    assert sheet.file_button.isVisibleTo(sheet) and sheet.close_button.text() == "Not now"
    assert not sheet.install_button.isVisibleTo(sheet)
    archive = zip_plugin(tmp_path)
    monkeypatch.setattr(plugin_offer, "pick_plugin_file", lambda parent: archive)
    answer(monkeypatch, True)
    sheet.file_button.click()
    assert (loader.plugins_dir() / "hello" / "plugin.toml").is_file()
    assert sheet.restart_button.isVisibleTo(sheet) and "starts after a restart" in sheet.status.text()


def test_a_file_that_is_refused_installs_nothing(qapp, monkeypatch, tmp_path):
    serve(monkeypatch, error=catalogue.CatalogueError("offline"))
    sheet = open_sheet(qapp)
    monkeypatch.setattr(plugin_offer, "pick_plugin_file", lambda parent: zip_plugin(tmp_path))
    answer(monkeypatch, False)
    sheet.file_button.click()
    assert not (loader.plugins_dir() / "hello").exists() and not sheet.restart_button.isVisibleTo(sheet)


def test_a_catalogue_from_the_future(qapp, monkeypatch):
    serve(monkeypatch, error=catalogue.CatalogueTooNew())
    sheet = open_sheet(qapp)
    assert sheet.status.text() == "Update SlideMage to see plugins."
    assert not sheet.file_button.isVisibleTo(sheet) and not sheet.install_button.isVisibleTo(sheet)


# -- closing and the flag

@pytest.mark.parametrize("how", ["not_now", "escape", "restart"])
def test_closing_writes_the_flag(qapp, monkeypatch, tmp_path, how):
    serve(monkeypatch, entry("alpha", "Alpha"))
    sheet = open_sheet(qapp)
    assert not upgrade.offer_seen()                         # opening alone writes nothing
    if how == "not_now":
        sheet.close_button.click()
    elif how == "escape":
        sheet.reject()
    else:
        sheet.restart_now()
        assert sheet.restart_requested
    assert upgrade.offer_seen()


def test_not_now_while_offline_writes_the_flag(qapp, monkeypatch):
    serve(monkeypatch, error=catalogue.CatalogueError("offline"))
    sheet = open_sheet(qapp)
    sheet.close_button.click()
    assert upgrade.offer_seen()


# -- installing

def test_install_selected_installs_the_checked_ones_and_offers_a_restart(qapp, monkeypatch, tmp_path):
    archive = zip_plugin(tmp_path)
    serve(monkeypatch, entry("hello", "Hello", sha256=sha(archive), size=archive.stat().st_size),
          entry("other", "Other"))
    calls = fake_download(monkeypatch, archive)
    sheet = open_sheet(qapp)
    sheet.rows["hello"].check.setChecked(True)
    sheet.install_button.click()
    assert not sheet.close_button.isEnabled() and not sheet.install_button.isEnabled()      # busy
    wait_until(lambda: not sheet._busy)
    assert calls == [("https://example.org/hello-0.1.0.smplugin", archive.stat().st_size)]
    assert (loader.plugins_dir() / "hello" / "plugin.toml").is_file()
    assert not (loader.plugins_dir() / "other").exists()
    assert "Installed: hello fixture 0.1.0" in sheet.status.text()
    assert sheet.restart_button.isVisibleTo(sheet) and not sheet.install_button.isVisibleTo(sheet)
    assert sheet.close_button.text() == "Close" and sheet.close_button.isEnabled()
    assert installer.pending_restart()
    sheet.restart_button.click()
    assert sheet.restart_requested and not sheet.isVisible()


def test_a_wrong_hash_installs_nothing_and_offers_no_restart(qapp, monkeypatch, tmp_path):
    archive = zip_plugin(tmp_path)
    serve(monkeypatch, entry("hello", "Hello", sha256="2" * 64))
    fake_download(monkeypatch, archive)
    sheet = open_sheet(qapp)
    sheet.rows["hello"].check.setChecked(True)
    sheet.install_button.click()
    wait_until(lambda: not sheet._busy)
    assert "checksum" in sheet.status.text() and "Hello" in sheet.status.text()
    assert not (loader.plugins_dir() / "hello").exists()
    assert not sheet.restart_button.isVisibleTo(sheet)


def test_one_failure_does_not_stop_the_rest(qapp, monkeypatch, tmp_path):
    archive = zip_plugin(tmp_path)
    serve(monkeypatch, entry("bad", "Bad", sha256="3" * 64),
          entry("hello", "Hello", sha256=sha(archive), size=archive.stat().st_size))
    fake_download(monkeypatch, archive)
    sheet = open_sheet(qapp)
    for plugin_row in sheet.rows.values():
        plugin_row.check.setChecked(True)
    sheet.install_button.click()
    wait_until(lambda: not sheet._busy)
    assert (loader.plugins_dir() / "hello").is_dir()
    assert "Installed: hello fixture" in sheet.status.text() and "Bad:" in sheet.status.text()


def test_the_sheet_does_not_close_while_installing(qapp, monkeypatch, tmp_path):
    archive = zip_plugin(tmp_path)
    serve(monkeypatch, entry("hello", "Hello", sha256=sha(archive), size=archive.stat().st_size))
    fake_download(monkeypatch, archive)
    sheet = open_sheet(qapp)
    sheet.rows["hello"].check.setChecked(True)
    sheet.install_button.click()
    sheet.reject()
    assert not upgrade.offer_seen() and sheet.isVisible()
    wait_until(lambda: not sheet._busy)


def test_help_plugins_still_opens_settings_not_the_sheet():
    from slidemage.ui.workspace.window import WorkspaceWindow
    assert "PluginOfferSheet" not in WorkspaceWindow.open_plugins.__code__.co_names
