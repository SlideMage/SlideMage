# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Continue where the last talk stopped (docs/plans/presenter-app.md, 5c). The place is stored per user and machine
(ui/layout_settings.py) as the slide number plus a fingerprint of that slide, so after a recompile the slide is
found again even when slides were added or removed before it. No Qt and no project here."""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from ..ui import layout_settings

STORE_KEY = "presentation_resume"
MAX_PLACES = 50
MAX_AGE_DAYS = 30


@dataclass(frozen=True)
class Place:
    slide: int          # 1-based; a page number + 1 when the PDF has no frame map
    count: int          # slides in the deck then
    title: str
    fingerprint: str
    saved: float        # time.time()


@dataclass(frozen=True)
class Offer:
    slide: int
    title: str
    moved_from: Optional[int] = None    # the stored number, when the slide was found elsewhere
    changed: bool = False               # the slide could not be found again


def fingerprint(title: str, text: str) -> str:
    """Digits are left out: footers carry slide numbers and dates, which shift when slides are added."""
    cleaned = " ".join(re.sub(r"\d+", "", f"{title}\n{text}").lower().split())
    return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:16]


def deck_key_for_pdf(path) -> str:
    return "pdf:" + os.path.normcase(str(Path(path).resolve()))


def deck_key_for_deck(path) -> str:
    return "deck:" + os.path.normcase(str(Path(path).resolve()))


def _stored() -> dict:
    stored = layout_settings.get(STORE_KEY, {})
    return stored if isinstance(stored, dict) else {}


def _to_place(raw) -> Optional[Place]:
    if not isinstance(raw, dict):
        return None
    try:
        place = Place(**{field.name: raw[field.name] for field in fields(Place)})
    except (KeyError, TypeError):
        return None
    ok = (isinstance(place.slide, int) and isinstance(place.count, int) and isinstance(place.title, str)
          and isinstance(place.fingerprint, str) and isinstance(place.saved, (int, float))
          and not isinstance(place.slide, bool) and not isinstance(place.count, bool))
    return place if ok else None


def load(key: str) -> Optional[Place]:
    return _to_place(_stored().get(key))


def save(key: str, place: Place) -> None:
    places = {k: v for k, v in _stored().items() if k != key and _to_place(v) is not None}
    places[key] = asdict(place)
    newest = sorted(places, key=lambda k: places[k]["saved"], reverse=True)[:MAX_PLACES]
    layout_settings.set(STORE_KEY, {k: places[k] for k in newest})


def too_old(place: Place, now: float) -> bool:
    return now - place.saved > MAX_AGE_DAYS * 86400


def worth_offering(place: Optional[Place], now: float) -> bool:
    """False for no place, an old one, the start, or a talk that was finished: nothing to ask then."""
    return place is not None and not too_old(place, now) and 1 < place.slide < place.count


def offer(place: Optional[Place], fingerprints: list[str], titles: list[str], now: float) -> Optional[Offer]:
    """What to offer for the deck as it is now: fingerprints[i] and titles[i] belong to slide i + 1."""
    if not worth_offering(place, now) or not fingerprints:
        return None
    if place.slide <= len(fingerprints) and fingerprints[place.slide - 1] == place.fingerprint:
        return Offer(place.slide, titles[place.slide - 1])
    found = [number for number, value in enumerate(fingerprints, 1) if value == place.fingerprint]
    if found:
        nearest = min(found, key=lambda number: (abs(number - place.slide), number))
        return Offer(nearest, titles[nearest - 1], moved_from=place.slide)
    slide = min(place.slide, len(fingerprints))
    return Offer(slide, titles[slide - 1], changed=True) if slide > 1 else None
