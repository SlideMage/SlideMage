"""Fixture plugin: a Deck settings tab with its own Save button (edit_deck_text, a marker comment) and a footer
action that inserts one slide (insert_slides). Errors are kept on the page for the tests to read."""
from slidemage.plugin_api import FooterAction


def activate(host):
    def build(deck):
        from PySide6.QtWidgets import QLabel, QPushButton

        page = host.Page()
        page.deck = deck
        page.error = ""
        page.save_button = QPushButton("Save marker")
        page.label = QLabel("")
        page.body.addWidget(page.save_button)
        page.body.addWidget(page.label)

        def save():
            try:
                host.edit_deck_text(page.deck, lambda t: t.replace("\\begin{document}",
                                                                   "%% marker: set\r\n\\begin{document}", 1))
            except Exception as exc:
                page.error = f"{type(exc).__name__}: {exc}"
                page.label.setText(page.error)
            else:
                page.error = ""

        page.save_button.clicked.connect(save)
        page.insert = lambda: insert(page)
        return page

    def insert(page):
        try:
            position = host.insert_positions(page.deck)[-1]
            host.insert_slides(page.deck, position, [("Fixture", "\\begin{frame}Fixture\\end{frame}")], "en")
        except Exception as exc:
            page.error = f"{type(exc).__name__}: {exc}"
        else:
            page.error = ""

    host.add_deck_settings_tab("Edit", build, FooterAction("Insert one", lambda page: page.insert()))
