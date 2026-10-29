from . import helper


def activate(host):
    host.add_command("relative.value", helper.TITLE, lambda deck: None)
