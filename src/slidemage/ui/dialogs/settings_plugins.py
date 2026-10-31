# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Plugins: the plugins on this computer, the catalogue's, and installing from a file.

* Installed: one row per plugin SlideMage found at start (session.loaded(), failed and disabled ones too) with its
  state, what it needs and what it contacts on the network, an enable switch, Remove (a plugin installed through
  SlideMage, not a development copy) and Update (when the cached catalogue has a newer release this SlideMage can
  run). A plugin installed or removed since the start has a row too, saying it begins or ends with the next start.
* Available: the catalogue's plugins that are not installed, with Install. The list comes from the cache when the
  tab is built; "Check for plugins" fetches it on a thread. Building the tab never touches the network.
* Themes: the theme packages installed on this computer (themes.py, docs/THEME_PACKAGE.md: a template packaged on
  its own), each with Remove. A theme takes effect at once, no restart: it is a template a deck chooses by its key.
* Install from file…: a .smplugin that is not from the catalogue. It is read first (installer.peek) and the user is
  asked, with the plugin's name, version and network lines, because the plugin runs with their rights. The same
  button takes a .smtheme (install_theme_file): its theme.toml is shown first, then themes.install_file checks it.

Every change takes effect after a restart (the plugins load once, before the window exists), so the tab says so and
offers "Restart now". Failures are captions, never exceptions: InstallError and CatalogueError have sentences meant
for the user, and anything else a worker raises is shown the same way.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout, QWidget

from ... import themes
from ...plugins import catalogue, installer, loader, session, updates
from ...plugins.catalogue import Catalogue, CataloguePlugin, CatalogueError, CatalogueTooNew, Release
from ...plugins.loader import LoadedPlugin
from ...plugins.manifest import Manifest, parse_version
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, Card, Chip, ModalSheet, Page, Surface, caption, clear_layout, row

log = logging.getLogger(__name__)

PLUGINS_PAGE = "https://slidemage.org/plugins/"
WITHDRAWN_NOTE = "Withdrawn from the plugin list: update or remove it"
STATE_TONES = {"loaded": "ok", "disabled": "muted", "failed": "error", "incompatible": "warning"}


class Job(QThread):
    """`work()` on a thread; `done(result, error)` arrives on the GUI thread."""

    done = Signal(object, object)

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as exc:        # shown as a caption; a worker must not end the thread with a traceback
            self.done.emit(None, exc)
        else:
            self.done.emit(result, None)


class TextSheet(ModalSheet):
    """A read-only text in a sheet: the traceback of a plugin that failed to load."""

    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent, width=640)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setMinimumHeight(240)
        self._root.insertWidget(2, self.view, 1)
        self.add_button("Close", kind="primary", role="accept")


def download_release(release: Release) -> Path:
    """Download `release` into a folder of its own (a worker thread's job). The folder is the result; the caller
    hands it to install_downloaded, which deletes it."""
    folder = Path(tempfile.mkdtemp(prefix="slidemage-plugin-"))
    try:
        installer.download(release.url, folder / "plugin.smplugin", expected_size=release.size)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def install_downloaded(folder: Path, release: Release) -> Manifest:
    """Install what download_release fetched when its SHA-256 is the one the catalogue promised, then delete the
    folder. Raises InstallError."""
    try:
        return installer.install(folder / "plugin.smplugin", expected_sha256=release.sha256)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def install_file(parent: QWidget, path: Path, say: Callable[[str, bool], None]) -> bool:
    """Install the .smplugin `path` after the user has seen what it is (the plugin is not from the catalogue and
    runs with their rights), or the .smtheme `path` (install_theme_file). `say(text, error)` receives what to tell
    the user. Whether it was installed."""
    if path.suffix.lower() == themes.PACKAGE_SUFFIX:
        return install_theme_file(parent, path, say)
    try:
        manifest = installer.peek(path)
        expected = _sidecar_sha256(path)
    except (installer.InstallError, OSError) as exc:
        say(str(exc), True)
        return False
    if not _confirm_file(parent, manifest):
        say("", False)
        return False
    try:
        installer.install(path, expected_sha256=expected)
    except installer.InstallError as exc:
        say(str(exc), True)
        return False
    say(f"{manifest.name} {manifest.version} is installed. It starts after a restart.", False)
    return True


def _confirm_file(parent: QWidget, manifest: Manifest) -> bool:
    net = "\n".join(f"  {line}" for line in manifest.network) if manifest.network else "  nothing"
    text = (f"This plugin is not from the SlideMage plugin list. It runs with your rights.\n\n"
            f"{manifest.name} {manifest.version}\n{manifest.summary}\n\nIt contacts on the network:\n{net}\n\n"
            "Install it only if you trust where it came from.")
    return QMessageBox.question(parent, "Install plugin from file", text) == QMessageBox.StandardButton.Yes


def _sidecar_sha256(path: Path) -> str | None:
    """The SHA-256 of `path`'s `<name>.sha256` file when there is one, after checking `path` against it. Raises
    InstallError (no checksum in it, or a file that does not match)."""
    sidecar = Path(str(path) + ".sha256")
    if not sidecar.is_file():
        return None
    expected = installer.read_sha256_file(sidecar)
    if expected is None:
        raise installer.InstallError(f"{sidecar.name} does not hold a SHA-256 checksum.")
    if installer.sha256_of(path) != expected:
        raise installer.InstallError(f"{path.name} does not match {sidecar.name} (SHA-256); nothing was installed.")
    return expected


def install_theme_file(parent: QWidget, path: Path, say: Callable[[str, bool], None]) -> bool:
    """Install the theme package `path` (a .smtheme) after the user has seen its theme.toml. Whether it was
    installed."""
    try:
        manifest = themes.peek(path)
        expected = _sidecar_sha256(path)
    except (themes.ThemeError, installer.InstallError, OSError) as exc:
        say(str(exc), True)
        return False
    if not _confirm_theme(parent, manifest):
        say("", False)
        return False
    try:
        themes.install_file(path, expected_sha256=expected)
    except themes.ThemeError as exc:
        say(str(exc), True)
        return False
    say(f"The theme {manifest.name} {manifest.version} is installed. Choose the template {manifest.id!r} in a "
        "deck's settings to use it.", False)
    return True


def _confirm_theme(parent: QWidget, manifest: themes.ThemeManifest) -> bool:
    current = next((t for t in themes.installed() if t.key == manifest.id), None)
    replaces = (f"\n\nIt replaces the installed version {current.manifest.version}." if current and current.manifest
                else "\n\nIt replaces the installed theme of that key." if current else "")
    text = (f"Install the theme {manifest.name} {manifest.version}?\n{manifest.summary}\n\n"
            f"Template key: {manifest.id}\nAuthor: {manifest.author}\nLicence: {manifest.license}{replaces}\n\n"
            "A theme is a slide template; it runs no program. A project's own copy of the same template still wins.")
    return QMessageBox.question(parent, "Install theme from file", text) == QMessageBox.StandardButton.Yes


def pick_plugin_file(parent: QWidget) -> Path | None:
    path, _ = QFileDialog.getOpenFileName(
        parent, "Install a plugin or theme", "",
        "SlideMage plugins and themes (*.smplugin *.smtheme);;SlideMage plugins (*.smplugin);;"
        "SlideMage themes (*.smtheme)")
    return Path(path) if path else None


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def network_line(network: tuple[str, ...]) -> str:
    return "Contacts: " + "; ".join(network) if network else "Contacts nothing on the network"


def _newer(release: Release, installed: Manifest) -> bool:
    try:
        return parse_version(release.version) > parse_version(installed.version)
    except ValueError:
        return False


class InstalledRow(Card):
    """One plugin of the Installed list. The controls are attributes so the tab (and its tests) can reach them."""

    def __init__(self, tab: PluginsTab, plugin: LoadedPlugin | None, found: loader.Found | None,
                 update: tuple[CataloguePlugin, Release] | None, withdrawn: bool = False) -> None:
        super().__init__()
        manifest = plugin.manifest if plugin else found.manifest
        source = plugin.source if plugin else found.source
        self.plugin_id = plugin.id if plugin else found.id
        self.enable_check: QCheckBox | None = None
        self.remove_button: Button | None = None
        self.update_button: Button | None = None
        self.details_button: Button | None = None
        layout = self.layout()

        title = QLabel(f"{manifest.name}  {manifest.version}" if manifest else self.plugin_id)
        title.setObjectName(q.ROW_NAME)
        origin = "installed" if source == "installed" else "development copy"
        if plugin is not None:
            state, tone, details = self._state(plugin)
        else:       # put in place since the start
            state, tone, details = "Installed; it starts after a restart", "info", ""
        state, tone, details = installer.row_state(self.plugin_id, (state, tone, details))
        self.state_chip = Chip(state, tone)
        head = [title, caption(origin), self.state_chip]
        layout.addWidget(row(*head, stretch=0))
        self.title_label = title
        if manifest is not None:
            layout.addWidget(caption(manifest.summary))
            if manifest.needs:
                layout.addWidget(caption("Needs: " + "; ".join(manifest.needs)))
            layout.addWidget(caption(network_line(manifest.network)))
        self.withdrawn_label: QLabel | None = None
        if withdrawn:
            self.withdrawn_label = caption(WITHDRAWN_NOTE, "error")
            layout.addWidget(self.withdrawn_label)
        if plugin is not None and plugin.note:
            layout.addWidget(caption(_sentence(plugin.note)))
        if details:
            self.details_button = Button("Details…", compact=True)
            self.details_button.clicked.connect(partial(tab.show_details, self.plugin_id, details))

        buttons: list[QWidget] = []
        if manifest is not None:
            self.enable_check = QCheckBox("Enabled")
            self.enable_check.setChecked(loader.is_enabled(self.plugin_id))
            self.enable_check.toggled.connect(partial(tab.set_plugin_enabled, self.plugin_id))
            buttons.append(self.enable_check)
        if self.details_button is not None:
            buttons.append(self.details_button)
        if update is not None:
            catalogue_plugin, release = update
            self.update_button = Button(f"Update to {release.version}", compact=True)
            self.update_button.clicked.connect(partial(tab.install_release, catalogue_plugin, release))
            buttons.append(self.update_button)
        if source == "installed":
            self.remove_button = Button("Remove", compact=True)
            self.remove_button.clicked.connect(partial(tab.remove_plugin, self.plugin_id,
                                                       manifest.name if manifest else self.plugin_id))
            buttons.append(self.remove_button)
        if buttons:
            layout.addWidget(row(Surface(), *buttons))      # the empty first cell takes the width: buttons at the right

    @staticmethod
    def _state(plugin: LoadedPlugin) -> tuple[str, str, str]:
        """(the state line, its chip tone, the text behind "Details…" or "")."""
        if plugin.state == "failed":
            return "Failed to load", STATE_TONES["failed"], plugin.reason
        if plugin.state == "incompatible":
            return _sentence(plugin.reason), STATE_TONES["incompatible"], ""
        return plugin.state.capitalize(), STATE_TONES[plugin.state], ""


class AvailableRow(Card):
    """One catalogue plugin that is not installed."""

    def __init__(self, tab: PluginsTab, plugin: CataloguePlugin, release: Release | None) -> None:
        super().__init__()
        self.plugin_id = plugin.id
        layout = self.layout()
        title = QLabel(f"{plugin.name}  {release.version}" if release else plugin.name)
        title.setObjectName(q.ROW_NAME)
        items: list[QWidget] = [title]
        if plugin.recommended:
            items.append(Chip("Recommended", "info"))
        layout.addWidget(row(*items))
        layout.addWidget(caption(plugin.summary))
        if plugin.needs:
            layout.addWidget(caption("Needs: " + "; ".join(plugin.needs)))
        layout.addWidget(caption(network_line(plugin.network)))
        self.install_button = Button("Install", compact=True)
        self.installable = release is not None
        if release is None:
            self.install_button.setEnabled(False)
            layout.addWidget(caption("No release of this plugin works with this SlideMage."))
        else:
            self.install_button.clicked.connect(partial(tab.install_release, plugin, release))
        layout.addWidget(row(Surface(), self.install_button))


class ThemeRow(Card):
    """One installed theme package: its name, version, key and summary, and Remove."""

    def __init__(self, tab: PluginsTab, theme: themes.InstalledTheme) -> None:
        super().__init__()
        self.key = theme.key
        layout = self.layout()
        manifest = theme.manifest
        title = QLabel(f"{manifest.name}  {manifest.version}" if manifest else theme.key)
        title.setObjectName(q.ROW_NAME)
        layout.addWidget(row(title, caption(f"template {theme.key}"), stretch=0))
        if manifest is not None:
            layout.addWidget(caption(manifest.summary))
            layout.addWidget(caption(f"{manifest.author}, {manifest.license}"))
        if theme.problem:
            layout.addWidget(caption(_sentence(f"not usable: {theme.problem}"), "error"))
        self.remove_button = Button("Remove", compact=True)
        self.remove_button.clicked.connect(partial(tab.remove_theme, theme.key,
                                                   manifest.name if manifest else theme.key))
        layout.addWidget(row(Surface(), self.remove_button))


class PluginsTab(Page):
    """`app` is the window (its project and relaunch_with_project); `leave(action)` closes the sheet and then runs
    `action` (SettingsSheet.close_then), which is how "Restart now" gets the modal sheet out of the way first."""

    def __init__(self, app, leave: Callable[[Callable[[], None]], None] | None = None) -> None:
        super().__init__()
        self.app = app
        self._leave = leave
        self.catalogue: Catalogue | None = catalogue.cached()      # never fetched while the tab is built
        self._job: QThread | None = None
        self.rows: dict[str, InstalledRow] = {}
        self.available: dict[str, AvailableRow] = {}
        self.theme_rows: dict[str, ThemeRow] = {}
        layout = self.body

        self.banner = Card()
        banner_text = caption("Changes take effect after a restart.")
        self.restart_button = Button("Restart now", kind="primary", compact=True)
        self.restart_button.clicked.connect(self.restart_now)
        self.banner.layout().addWidget(row(banner_text, self.restart_button))
        layout.addWidget(self.banner)

        self.status = caption("")
        layout.addWidget(self.status)

        layout.addWidget(self._heading("Installed"))
        self._installed_box = QVBoxLayout()
        self._installed_box.setSpacing(8)
        layout.addLayout(self._installed_box)

        layout.addWidget(self._heading("Available"))
        self._available_box = QVBoxLayout()
        self._available_box.setSpacing(8)
        layout.addLayout(self._available_box)
        self.available_note = caption("")
        layout.addWidget(self.available_note)

        layout.addWidget(self._heading("Themes"))
        self._themes_box = QVBoxLayout()
        self._themes_box.setSpacing(8)
        layout.addLayout(self._themes_box)

        self.check_button = Button("Check for plugins", compact=True)
        self.check_button.clicked.connect(self.check_catalogue)
        self.file_button = Button("Install from file…", compact=True)
        self.file_button.clicked.connect(self.install_from_dialog)
        self.page_button = Button("See all plugins and what they do", kind="ghost", compact=True)
        self.page_button.clicked.connect(self.open_plugins_page)
        layout.addWidget(row(self.check_button, self.file_button, self.page_button, stretch=2))
        layout.addStretch(1)
        self.refresh()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(q.ROW_NAME)
        return label

    # -- what is shown

    def refresh(self) -> None:
        """Rebuild both lists and the banner from the session, the disk and the cached catalogue."""
        clear_layout(self._installed_box)
        clear_layout(self._available_box)
        self.rows.clear()
        self.available.clear()
        known = {p.id: p for p in session.loaded()}
        changed = installer.changed_ids()
        entries = {c.id: c for c in self.catalogue.plugins} if self.catalogue else {}
        for plugin in session.loaded():
            if plugin.source == "installed" and plugin.id in changed and not plugin.folder.is_dir():
                continue            # removed since the start: no row until the next start
            withdrawn = updates.is_withdrawn(plugin, entries.get(plugin.id))
            self._add_installed(InstalledRow(self, plugin, None, self._update_for(plugin, entries, changed),
                                             withdrawn), plugin.id)
        found_now = loader.discover()
        for found in found_now:
            if found.id not in known and found.source == "installed":
                self._add_installed(InstalledRow(self, None, found, None), found.id)
        present = set(known) | {f.id for f in found_now}
        if self.catalogue is None:
            self.available_note.setText("The plugin list has not been loaded yet. Check for plugins to see it.")
        else:
            todo = [c for c in self.catalogue.plugins if c.id not in present]
            for entry in sorted(todo, key=lambda c: (not c.recommended, c.name.lower())):
                available_row = AvailableRow(self, entry, catalogue.best_release(entry))
                self.available[entry.id] = available_row
                self._available_box.addWidget(available_row)
            self.available_note.setText("" if todo else "Every plugin of the list is installed.")
        if not self.rows:
            self._installed_box.addWidget(caption("No plugins are installed."))
        self.refresh_themes()
        self.banner.setVisible(installer.pending_restart())
        self._set_busy(self._job is not None)

    def refresh_themes(self) -> None:
        clear_layout(self._themes_box)
        self.theme_rows.clear()
        for theme in themes.installed():
            self.theme_rows[theme.key] = ThemeRow(self, theme)
            self._themes_box.addWidget(self.theme_rows[theme.key])
        if not self.theme_rows:
            self._themes_box.addWidget(caption("No themes are installed. A theme is a slide template packaged on its "
                                               "own (.smtheme); install one from a file."))

    def remove_theme(self, key: str, name: str) -> None:
        if QMessageBox.question(self, "Remove theme", f"Remove the theme {name}? Decks that use the template "
                                f"{key!r} need a copy of it in their project to compile."
                                ) != QMessageBox.StandardButton.Yes:
            return
        try:
            themes.remove(key)
        except themes.ThemeError as exc:
            self._say(str(exc), error=True)
            return
        self._say(f"The theme {name} is removed.")
        self.refresh_themes()

    def _add_installed(self, installed_row: InstalledRow, plugin_id: str) -> None:
        self.rows[plugin_id] = installed_row
        self._installed_box.addWidget(installed_row)

    @staticmethod
    def _update_for(plugin: LoadedPlugin, entries: dict[str, CataloguePlugin],
                    changed: frozenset[str]) -> tuple[CataloguePlugin, Release] | None:
        """The catalogue's release that would update `plugin`: an installed one (not a development copy, not one
        changed this session) with a newer release this SlideMage can run."""
        entry = entries.get(plugin.id)
        if entry is None or plugin.source != "installed" or plugin.manifest is None or plugin.id in changed:
            return None
        release = catalogue.best_release(entry)
        return (entry, release) if release is not None and _newer(release, plugin.manifest) else None

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("tone", "error" if error else "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _set_busy(self, busy: bool) -> None:
        """While a download or a check runs, the buttons that start another one wait."""
        self.check_button.setEnabled(not busy)
        self.file_button.setEnabled(not busy)
        for available_row in self.available.values():
            available_row.install_button.setEnabled(not busy and available_row.installable)
        for installed_row in self.rows.values():
            if installed_row.update_button is not None:
                installed_row.update_button.setEnabled(not busy)

    # -- installed plugins

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        try:
            loader.set_enabled(plugin_id, enabled)
        except OSError as exc:
            self._say(f"The choice could not be saved: {exc}", error=True)
            return
        installer.mark_changed(plugin_id)
        self._say("")
        self.banner.setVisible(True)

    def remove_plugin(self, plugin_id: str, name: str) -> None:
        if QMessageBox.question(self, "Remove plugin", f"Remove {name}? It is gone after the next start."
                                ) != QMessageBox.StandardButton.Yes:
            return
        try:
            installer.remove(plugin_id)
        except installer.InstallError as exc:
            self._say(str(exc), error=True)
            return
        self._say(f"{name} is removed. It stops with the next start.")
        self.refresh()

    def show_details(self, plugin_id: str, text: str) -> None:
        TextSheet(f"Why {plugin_id} did not load", text, self).exec()

    # -- the catalogue

    def check_catalogue(self) -> None:
        self._start(catalogue.fetch, self._on_catalogue, "Checking for plugins…")

    def _on_catalogue(self, result: Catalogue | None, error: Exception | None) -> None:
        if isinstance(error, CatalogueTooNew):
            self._say(str(error))
        elif isinstance(error, CatalogueError):
            self._say(f"{error}" + (" The last list is shown." if self.catalogue else ""), error=True)
        elif error is not None:
            log.error("plugin list failed", exc_info=error)
            self._say(f"Could not load the plugin list: {error}", error=True)
        else:
            self.catalogue = result
            self._say("The plugin list is up to date.")
        self.refresh()

    def open_plugins_page(self) -> None:
        page = self.catalogue.plugins_page if self.catalogue else PLUGINS_PAGE
        QDesktopServices.openUrl(QUrl(page))

    def install_release(self, plugin: CataloguePlugin, release: Release) -> None:
        """Download `release`, then install it when its SHA-256 is the one the catalogue promised."""
        def done(folder: Path | None, error: Exception | None) -> None:
            if error is not None:
                self._fail(error)
                return self.refresh()
            try:
                manifest = install_downloaded(folder, release)
            except installer.InstallError as exc:
                self._say(str(exc), error=True)
            else:
                self._say(f"{manifest.name} {manifest.version} is installed. It starts after a restart.")
            self.refresh()

        self._start(partial(download_release, release), done, f"Downloading {plugin.name}…")

    # -- a file

    def install_from_dialog(self) -> None:
        path = pick_plugin_file(self)
        if path is not None:
            self.install_from_file(path)

    def install_from_file(self, path: Path) -> bool:
        """Install `path` after the user has seen what it is. Whether it was installed."""
        installed = install_file(self, path, lambda text, error: self._say(text, error))
        if installed:
            self.refresh()
        return installed

    # -- restart

    def restart_now(self) -> None:
        """Start SlideMage again and close this window: the plugins load once, before the window exists."""
        restart = partial(self.app.relaunch_with_project, self.app.project.root)
        if self._leave is not None:
            self._leave(restart)        # the sheet is modal: it closes first
        else:
            restart()

    # -- work on a thread

    def _start(self, work: Callable[[], object], on_done: Callable[[object, Exception | None], None],
               message: str) -> None:
        if self._job is not None:
            return
        self._say(message)
        job = Job(work)
        self._job = job

        def finished(result: object, error: Exception | None) -> None:
            self._job = None
            on_done(result, error)

        job.done.connect(finished)
        self._set_busy(True)
        background.start_detached(job)

    def _fail(self, error: Exception) -> None:
        if not isinstance(error, installer.InstallError):
            log.error("plugin job failed", exc_info=error)
        self._say(str(error), error=True)
