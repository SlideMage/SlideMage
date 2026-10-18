"""The presentation options (plan 4.11), kept in the project's app settings under one key. Every field has a
default, so presenting works with the settings page never opened."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from .. import app_settings
from ..project import ProjectContext

SETTINGS_KEY = "presentation"
TIMER_END, TIMER_DURATION = "end", "duration"


@dataclass
class PresentationSettings:
    profile: str = "Current large"
    laser_color: str = "#ff2020"
    pen_color: str = "#c0ffd400"       # a translucent yellow: a highlighter
    pen_width: float = 0.012           # fraction of the slide height
    confirm_links: bool = True
    audience_screen: str = ""          # ScreenInfo.key; "" is automatic
    timer_mode: str = TIMER_END
    timer_duration_minutes: int = 45
    timer_start_on_navigation: bool = True
    timer_flash: bool = True
    timer_warn: bool = True
    clock_format: str = "system"       # "system", "12" or "24"

    @classmethod
    def load(cls, ctx: ProjectContext) -> "PresentationSettings":
        stored = app_settings.get(ctx, SETTINGS_KEY, {})
        stored = stored if isinstance(stored, dict) else {}
        settings = cls()
        for field in fields(cls):
            value = stored.get(field.name)
            if isinstance(value, type(getattr(settings, field.name))):
                setattr(settings, field.name, value)
        return settings

    def save(self, ctx: ProjectContext) -> None:
        app_settings.set(ctx, SETTINGS_KEY, asdict(self))
