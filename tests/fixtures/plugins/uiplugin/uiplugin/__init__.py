"""Fixture plugin: a command, a Deck menu entry, a Deck settings tab with a footer action, a settings tab, a box."""
from PySide6.QtWidgets import QLineEdit

from slidemage.plugin_api import FooterAction

CALLS = []      # what ran, for the tests (the module is imported once per load)


def activate(host):
    def run(deck):
        CALLS.append(("run", deck.name if deck else None))
        host.show_message("ran")

    def boom(deck):
        raise RuntimeError("kaboom")

    host.add_command("uiplugin.run", "Run fixture", run, enabled=lambda deck: deck is not None)
    host.add_command("uiplugin.boom", "Break fixture", boom)
    host.add_menu_entry("deck", "uiplugin.run")
    host.add_menu_entry("deck", "uiplugin.boom")

    def deck_tab(deck):
        page = host.Page()
        page.edit = QLineEdit()
        page.body.addWidget(host.Field("Name", page.edit))
        page.edit.textChanged.connect(page.changed)
        return page

    def go(page):
        CALLS.append(("footer", page.edit.text()))

    host.add_deck_settings_tab(
        "Fixture", deck_tab, FooterAction("Do it", go, enabled=lambda page: bool(page.edit.text())))

    def failing_tab(deck):
        raise RuntimeError("no tab")

    host.add_deck_settings_tab("Broken", failing_tab, FooterAction("Never", go))

    def settings_tab():
        page = host.Page()
        page.body.addWidget(host.caption("fixture settings"))
        return page

    host.add_settings_tab("Fixture", settings_tab)

    def box(deck):
        page = host.Page()
        page.body.addWidget(host.caption(f"box for {deck.name}"))
        return page

    host.add_sidebar_box("main", "Fixture box", box, when=lambda deck: deck.name != "hidden")

    host.add_render_priority(lambda deck: deck.name == "test")
