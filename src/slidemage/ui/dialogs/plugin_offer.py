# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-start sheet: the plugins SlideMage offers, shown once per machine (plugins/offer_seen).

SlideMage ships without plugins and works without them, so the sheet is an offer, never a gate: nothing is ticked
(Claude sends slides to the cloud, Ollama does nothing without Ollama installed), the recommended plugins come
first, and "Not now" is always there. The list is fetched when the sheet opens, on a thread; offline it says so
and still offers "Install from file…". Installing reuses the Plugins tab's download and install steps
(settings_plugins), one plugin after the other, and ends with "Restart now" because plugins load once, at start.

`preselected` maps a plugin id to the reason it is ticked ("You have an Anthropic API key"): the upgrade check
(plugins/upgrade.py) fills it in the release that removes a feature from core. The flag is written when the sheet
closes, by any button; a sheet that never opened leaves it unwritten, so the next start tries again.

The start-up caller (workspace/maintenance.py) fetches the catalogue first and opens the sheet, with that
catalogue in `catalogue_data`, only when something is offerable; so offline and too-new never reach the sheet
there. Opened without `catalogue_data` the sheet fetches the list itself and keeps its own loading, offline
and too-new texts (a future caller, the tests).
"""
from __future__ import annotations

import logging
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from ...plugins import catalogue, installer, loader, session, upgrade
from ...plugins.catalogue import Catalogue, CataloguePlugin, CatalogueError, CatalogueTooNew, Release
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, Card, ModalSheet, Page, Surface, caption, clear_layout, row
from .settings_plugins import (PLUGINS_PAGE, Job, download_release, install_downloaded, install_file, network_line,
                               pick_plugin_file)

log = logging.getLogger(__name__)

INTRO = ("SlideMage works without plugins. These add features; you can add or remove them later in "
         "Settings → Plugins.")
LOADING = "Loading the list of plugins…"
OFFLINE = "The list of plugins could not be loaded."
NEEDS_NEWER = "Needs a newer SlideMage"
ALL_INSTALLED = "Every plugin of the list is installed."


class PluginRow(Card):
    """One plugin of the list: a checkbox with its name, what it does, needs and contacts, and More…."""

    def __init__(self, sheet: PluginOfferSheet, plugin: CataloguePlugin, release: Release | None,
                 reason: str = "") -> None:
        super().__init__()
        self.plugin_id = plugin.id
        self.release = release
        layout = self.layout()
        self.check = QCheckBox(plugin.name)
        self.check.setObjectName(q.ROW_NAME)
        self.check.setEnabled(release is not None)
        self.check.setChecked(release is not None and bool(reason))
        self.check.toggled.connect(sheet.update_buttons)
        layout.addWidget(self.check)
        layout.addWidget(caption(plugin.summary))
        if reason:
            layout.addWidget(caption(reason))
        if release is None:
            layout.addWidget(caption(NEEDS_NEWER, "error"))
        if plugin.needs:
            layout.addWidget(caption("Needs: " + "; ".join(plugin.needs)))
        layout.addWidget(caption(network_line(plugin.network)))
        self.more_button = Button("More…", kind="ghost", compact=True)
        self.more_button.clicked.connect(partial(sheet.open_url, plugin.homepage))
        layout.addWidget(row(Surface(), self.more_button))


class PluginOfferSheet(ModalSheet):
    def __init__(self, parent: QWidget | None = None, *, preselected: dict[str, str] | None = None,
                 catalogue_data: Catalogue | None = None) -> None:
        super().__init__("Plugins for SlideMage", parent, width=620)
        self.preselected = dict(preselected or {})
        self.catalogue: Catalogue | None = None
        self.rows: dict[str, PluginRow] = {}
        self.restart_requested = False
        self._job: Job | None = None
        self._queue: list[tuple[CataloguePlugin, Release]] = []
        self._current: tuple[CataloguePlugin, Release] | None = None
        self._total = 0
        self._installed: list[str] = []
        self._failed: list[str] = []
        self._busy = False
        self.finished.connect(self._remember)

        page = Page()
        self.intro = caption(INTRO)
        page.body.addWidget(self.intro)
        self.status = QLabel(LOADING)
        self.status.setWordWrap(True)
        page.body.addWidget(self.status)
        self._list = QVBoxLayout()
        self._list.setSpacing(8)
        page.body.addLayout(self._list)
        page.body.addStretch(1)
        self.add_tab("Plugins", page, scroll=True)

        self.page_button = Button("See all plugins and what they do", kind="ghost")
        self.page_button.clicked.connect(lambda: self.open_url(self._plugins_page()))
        self.add_footer_note(self.page_button)
        self.file_button = self.add_button("Install from file…")
        self.file_button.clicked.connect(self.install_from_dialog)
        self.file_button.hide()
        self.restart_button = self.add_button("Restart now", kind="primary")
        self.restart_button.clicked.connect(self.restart_now)
        self.restart_button.hide()
        self.install_button = self.add_button("Install selected", kind="primary")
        self.install_button.clicked.connect(self.install_selected)
        self.install_button.hide()
        self.close_button = self.add_button("Not now", role="reject")

        if catalogue_data is not None:
            self._on_catalogue(catalogue_data, None)
        else:
            self._start(catalogue.fetch, self._on_catalogue)

    # -- the flag and closing

    def _remember(self, _result: int) -> None:
        upgrade.mark_offer_seen()

    def reject(self) -> None:
        if not self._busy:      # a download in flight is not left behind a closed sheet
            super().reject()

    def restart_now(self) -> None:
        self.restart_requested = True
        self.accept()

    # -- the list

    def _plugins_page(self) -> str:
        return self.catalogue.plugins_page if self.catalogue else PLUGINS_PAGE

    def open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _on_catalogue(self, result: Catalogue | None, error: Exception | None) -> None:
        if isinstance(error, CatalogueTooNew):
            return self._show_message(str(error))
        if error is not None:
            if not isinstance(error, CatalogueError):
                log.error("plugin list failed", exc_info=error)
            return self._show_message(OFFLINE, offer_file=True)
        self.catalogue = result
        present = {p.id for p in session.loaded()} | {f.id for f in loader.discover()}
        todo = [c for c in result.plugins if c.id not in present]
        if not todo:
            return self._show_message(ALL_INSTALLED)
        self.status.hide()
        clear_layout(self._list)
        self.rows.clear()
        recommended = sorted((c for c in todo if c.recommended), key=lambda c: c.name.lower())
        more = sorted((c for c in todo if not c.recommended), key=lambda c: c.name.lower())
        for heading, group in (("Recommended", recommended), ("More plugins", more)):
            if not group:
                continue
            label = QLabel(heading)
            label.setObjectName(q.ROW_NAME)
            self._list.addWidget(label)
            for entry in group:
                plugin_row = PluginRow(self, entry, catalogue.best_release(entry), self.preselected.get(entry.id, ""))
                self.rows[entry.id] = plugin_row
                self._list.addWidget(plugin_row)
        self.install_button.show()
        self.update_buttons()

    def _show_message(self, text: str, *, offer_file: bool = False) -> None:
        self.status.setText(text)
        self.status.show()
        self.file_button.setVisible(offer_file)

    def checked(self) -> list[PluginRow]:
        return [r for r in self.rows.values() if r.check.isChecked() and r.release is not None]

    def update_buttons(self) -> None:
        self.install_button.setEnabled(not self._busy and bool(self.checked()))
        self.file_button.setEnabled(not self._busy)
        for plugin_row in self.rows.values():
            plugin_row.check.setEnabled(not self._busy and plugin_row.release is not None)

    # -- installing

    def install_selected(self) -> None:
        if self._busy:
            return
        self._queue = [(self.catalogue_entry(r.plugin_id), r.release) for r in self.checked()]
        self._total = len(self._queue)
        self._installed, self._failed = [], []
        if self._queue:
            self._set_busy(True)
            self._next()

    def catalogue_entry(self, plugin_id: str) -> CataloguePlugin:
        return next(c for c in self.catalogue.plugins if c.id == plugin_id)

    def _next(self) -> None:
        if not self._queue:
            return self._finish()
        self._current = self._queue.pop(0)
        plugin, release = self._current
        self._say(f"Downloading {plugin.name} ({self._total - len(self._queue)} of {self._total})…")
        self._start(partial(download_release, release), self._downloaded)

    def _downloaded(self, folder, error: Exception | None) -> None:
        plugin, release = self._current
        if error is None:
            try:
                manifest = install_downloaded(folder, release)
            except installer.InstallError as exc:
                error = exc
            else:
                self._installed.append(f"{manifest.name} {manifest.version}")
        if error is not None:
            if not isinstance(error, installer.InstallError):
                log.error("plugin job failed", exc_info=error)
            self._failed.append(f"{plugin.name}: {error}")
        self._next()

    def _finish(self) -> None:
        self._set_busy(False)
        lines = []
        if self._installed:
            lines.append("Installed: " + ", ".join(self._installed) + ". They start after a restart.")
        lines.extend(self._failed)
        self._say("\n".join(lines))
        self.install_button.hide()
        self.restart_button.setVisible(bool(self._installed))
        self.close_button.setText("Close")
        for plugin_row in self.rows.values():
            plugin_row.check.setEnabled(False)

    def install_from_dialog(self) -> None:
        path = pick_plugin_file(self)
        if path is None:
            return
        if install_file(self, path, self._say_file):
            self._installed.append(path.name)
            self.file_button.hide()
            self.restart_button.show()
            self.close_button.setText("Close")

    def _say_file(self, text: str, error: bool) -> None:
        self._say(text)

    # -- work on a thread

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.close_button.setEnabled(not busy)
        self.update_buttons()

    def _start(self, work, on_done) -> None:
        job = Job(work)
        self._job = job

        def finished(result, error) -> None:
            self._job = None
            on_done(result, error)

        job.done.connect(finished)
        background.start_detached(job)
