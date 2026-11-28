"""Fixture plugin like the website's sample."""


def activate(host):
    def say(deck):
        host.show_message("Hello")

    host.add_command("hello.say", "Say hello", say)
    host.add_menu_entry("deck", "hello.say")
