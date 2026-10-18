"""The optional presentation timer (plan 4.5): a countdown to an end time of day, or for a duration.

Plain logic with an injected monotonic clock and time of day, so the tests never wait.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from datetime import time as time_of_day
from typing import Callable, Optional

from .settings import TIMER_DURATION, TIMER_END

FLASH_SECONDS = 10      # after time is up, the display flashes this long, then stays red
WARN_SECONDS = 300      # amber warning


class PresentationTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self._clock, self._now = clock, now
        self.mode: Optional[str] = None
        self._end: Optional[datetime] = None
        self._duration = 0.0
        self._elapsed = 0.0
        self._started_at: Optional[float] = None

    # -- setting ----------------------------------------------------------------------

    def set_end_time(self, when: time_of_day) -> bool:
        """Count down to `when` today; False (nothing changed) when that time has already passed."""
        now = self._now()
        end = now.replace(hour=when.hour, minute=when.minute, second=0, microsecond=0)
        if end <= now:
            return False
        self.mode, self._end = TIMER_END, end
        return True

    def set_duration(self, seconds: float) -> None:
        self.mode, self._duration, self._elapsed, self._started_at = TIMER_DURATION, float(seconds), 0.0, None

    def clear(self) -> None:
        self.mode, self._end, self._started_at, self._elapsed = None, None, None, 0.0

    # -- running ----------------------------------------------------------------------

    @property
    def is_set(self) -> bool:
        return self.mode is not None

    @property
    def running(self) -> bool:
        return self.mode == TIMER_END or (self.mode == TIMER_DURATION and self._started_at is not None)

    def start(self) -> None:
        if self.mode == TIMER_DURATION and self._started_at is None:
            self._started_at = self._clock()

    def pause(self) -> None:
        if self.mode == TIMER_DURATION and self._started_at is not None:
            self._elapsed += self._clock() - self._started_at
            self._started_at = None

    def toggle(self) -> None:
        self.pause() if self.running else self.start()

    def reset(self) -> None:
        """A duration timer back to the full duration, stopped; an end-time timer has nothing to reset."""
        if self.mode == TIMER_DURATION:
            self._elapsed, self._started_at = 0.0, None

    # -- reading ----------------------------------------------------------------------

    def remaining(self) -> Optional[float]:
        """Seconds left (negative once time is up); None when no timer is set."""
        if self.mode == TIMER_END:
            return (self._end - self._now()).total_seconds()
        if self.mode == TIMER_DURATION:
            elapsed = self._elapsed + (self._clock() - self._started_at if self._started_at is not None else 0.0)
            return self._duration - elapsed
        return None

    def level(self, warn: bool = True) -> str:
        """"off", "ok", "warn" (under five minutes) or "over"."""
        remaining = self.remaining()
        if remaining is None:
            return "off"
        if remaining <= 0:
            return "over"
        return "warn" if warn and remaining <= WARN_SECONDS else "ok"

    def flash_on(self, flash: bool = True) -> bool:
        """Whether the display is red right now: alternating each half second for the first seconds after
        time is up when `flash`, otherwise (and afterwards) solid."""
        remaining = self.remaining()
        if remaining is None or remaining > 0:
            return False
        overrun = -remaining
        return int(overrun * 2) % 2 == 0 if flash and overrun < FLASH_SECONDS else True

    def text(self) -> str:
        remaining = self.remaining()
        if remaining is None:
            return ""
        seconds = int(abs(remaining) if remaining < 0 else remaining + 0.999)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        body = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
        return f"+{body}" if remaining < 0 else body

    def target_text(self) -> str:
        """The end time as written, for the small text beside an end-time countdown."""
        return f"until {self._end:%H:%M}" if self.mode == TIMER_END and self._end else ""


def end_time_after(minutes: int, now: Optional[datetime] = None) -> time_of_day:
    """A time of day `minutes` from now, as the dialog's starting value."""
    return ((now or datetime.now()) + timedelta(minutes=minutes)).time().replace(second=0, microsecond=0)
