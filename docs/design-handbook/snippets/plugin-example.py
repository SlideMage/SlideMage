def refresh(theme):
    panel.setStyleSheet(
        f"QWidget#myPanel {{ background: {theme.surface}; "
        f"color: {theme.text}; }}")
    panel.update()  # paintEvent reads current tokens

refresh(host.theme())
unsubscribe = host.on_theme_changed(refresh)
