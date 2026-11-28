# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Preview pane remembers, apart from what it draws (review item D1).

The pane (preview_view.PreviewPane) owns the widgets, the timers, the worker threads and the Qt signals that hand a
result from a worker back to the GUI thread. The state those results land in lives here, in plain Python classes
without widgets or timers (QImage and QPixmap stay in the values):

- `DisplayCache`: decoded pages of this session's saved renders, reusable after the selected lookup.
- `ReadAhead`: the stored pages of the deck's view, read ahead by a worker of its own.
- `StepState`: the page lists of all-steps renders, the step picked per slide, the scans of the slides.
- `Lookups`: the render store lookups out per slot, and the chooser's answer for the slide on show.
- `AdhocBuffer`: the latest render of the editor's buffer (a temporary page).

`PreviewModel` holds one of each and says what drops when the selection, the view or the language changes.

Threads: every method runs on the GUI thread, except `preload_page` (it runs on the read-ahead worker, and only
reads what it is given). Work the pane hands to its executors stays there; results come back by Qt signal, and
the signal's slot calls into this module on the GUI thread. No method locks: nothing here is shared with a worker.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from ... import reveal_steps, slide_snapshot

if TYPE_CHECKING:
    from .preview_view import _PageResult

DISPLAY_WIDTH = slide_snapshot.FULL_SIZE[0]   # a page held for display is at most a render's full width: a large or
# high-DPI pane shows that much, so a smaller copy would look softer than the current page
DISPLAY_ENTRIES = 12     # pages held decoded for display ...
DISPLAY_BYTES = 64 << 20 # ... and at most this much memory for them (width x height x 4 each)
PREFETCHED = 20          # stored pages of the nearest slides held decoded, ready for the next slide (about 8 MB each)
PRELOAD_BYTES = 512 << 20   # stored page images of the rest of the deck's view held compressed, decoded when shown
PRELOAD_PAUSE = 0.01     # seconds the read-ahead worker rests before each store lookup, so the GUI thread gets its turn
PRELOAD_RETRY = 120.0    # seconds before a slide whose store had no page is asked again
STEP_CACHE = 12          # page lists kept (each is a slide's steps as compressed images)
SCAN_CACHE = 64          # slide scans kept


@dataclass
class Shown:
    """A decoded whole-slide page of a saved render, as it was when it was made."""
    pixmap: QPixmap
    mtime: int | None               # of the slide's source file
    content_hash: Optional[str]     # of the text rendered (the saved file's)
    image_hash: str                 # of the bytes the pixels came from: the same image is never decoded twice


class DisplayCache:
    """Decoded pages for display, newest last: (target.key, view, language) -> Shown. GUI thread only. Only saved
    whole-slide renders go in (never a draft or a part of a slide), at display size and within a byte budget.
    A lookup provides the digest for reuse. The source hash can identify an older page after a lookup miss."""

    def __init__(self) -> None:
        self._items: OrderedDict[tuple, Shown] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    @property
    def bytes(self) -> int:
        return sum(item.pixmap.width() * item.pixmap.height() * 4 for item in self._items.values())

    def get(self, key: tuple) -> Optional[Shown]:
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
        return item

    def put(self, key: tuple, pixmap: QPixmap, mtime: int | None, content_hash: Optional[str], image_hash: str) -> QPixmap:
        """Keep `pixmap` at display size; the pixmap held (to show) is returned."""
        if pixmap.width() > DISPLAY_WIDTH:
            pixmap = pixmap.scaledToWidth(DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)
        self._items[key] = Shown(pixmap, mtime, content_hash, image_hash)
        self._items.move_to_end(key)
        while len(self._items) > 1 and (len(self._items) > DISPLAY_ENTRIES or self.bytes > DISPLAY_BYTES):
            self._items.popitem(last=False)
        return pixmap

    def clear(self) -> None:
        self._items.clear()


def display_pixmap(pixmap: QPixmap) -> QPixmap:
    """`pixmap` at most DISPLAY_WIDTH wide."""
    if pixmap.width() > DISPLAY_WIDTH:
        pixmap = pixmap.scaledToWidth(DISPLAY_WIDTH, Qt.TransformationMode.SmoothTransformation)
    return pixmap


class ReadAhead:
    """The stored pages of the deck's view, read ahead outward from the slide on show: the nearest PREFETCHED decoded
    (ident -> (QPixmap, digest)), the others as compressed images (ident -> (bytes, digest), at most PRELOAD_BYTES).
    Keyed with the file's mtime for scheduling. The selected lookup authorizes reuse by image digest. One deck, view and language: `context`. GUI thread only; the reads themselves run on
    the pane's prefetch executor (`preload_page`), their futures are kept here to be cancelled."""

    def __init__(self) -> None:
        self.prefetched: OrderedDict = OrderedDict()
        self.compressed: dict = {}
        self.compressed_bytes = 0
        self.rank: dict = {}              # ident -> its place in the read-ahead order (0 = nearest)
        self.context: Optional[tuple] = None   # (deck name, view, language) the held pages are of
        self.missing: dict = {}           # ident -> when the store had no page for it
        self.prefetching: dict = {}       # ident -> Future, queued or running

    def drop(self) -> None:
        """Forget the pages read ahead (another deck, view or language; the pane closes). Python objects only."""
        for future in self.prefetching.values():
            future.cancel()
        self.prefetching.clear()
        self.prefetched.clear()
        self.compressed.clear()
        self.compressed_bytes = 0
        self.rank = {}
        self.missing = {}
        self.context = None

    def switch_context(self, context: tuple) -> None:
        """Another deck, view or language than the held pages' drops them all."""
        if context != self.context:
            self.drop()
            self.context = context

    def cancel_queued(self) -> None:
        """Reads queued for the order of before are dropped (the running one stays)."""
        for ident, future in list(self.prefetching.items()):
            if future.cancel():
                del self.prefetching[ident]

    def plan(self, order: list, now: float) -> list:
        """`order`: [(target, ident)], nearest first. Ranks them, lets go of the decoded pages that are no longer
        among the nearest PREFETCHED, and returns [(target, ident, decode, held bytes or None)] to read: what is
        not read, being read, or known missing (for PRELOAD_RETRY seconds). The caller submits them and records
        each future in `prefetching`."""
        self.missing = {i: at for i, at in self.missing.items() if now - at < PRELOAD_RETRY}
        self.rank = {ident: rank for rank, (_other, ident) in enumerate(order)}
        near = {ident for _other, ident in order[:PREFETCHED]}
        for ident in [i for i in self.prefetched if i not in near]:
            del self.prefetched[ident]
        reads, seen = [], set()
        for other, ident in order:
            decode = ident in near and ident not in self.prefetched
            held = self.compressed.get(ident)
            if (ident in self.prefetching or ident in seen or ident in self.missing
                    or not decode and held is not None):
                continue
            seen.add(ident)
            reads.append((other, ident, decode, held[0] if held is not None else None))
        return reads

    def arrived(self, context, ident, found) -> bool:
        """A read finished (its result is `found`: (bytes, digest, QImage or None) or None). True when a page was
        newly decoded and held for `ident`."""
        self.prefetching.pop(ident, None)
        if context != self.context:
            return False
        if found is None:
            self.missing[ident] = time.monotonic()
            return False
        data, digest, image = found
        self.keep_compressed(ident, data, digest)
        if image is None or ident in self.prefetched or self.rank.get(ident, PREFETCHED) >= PREFETCHED:
            return False
        self.hold_decoded(ident, display_pixmap(QPixmap.fromImage(image)), digest)
        return True

    def keep_compressed(self, ident, data: bytes, digest: str) -> None:
        """Hold the compressed image of `ident`; beyond PRELOAD_BYTES the pages farthest from the slide on show
        give way (or this one, when it is the farthest)."""
        if ident in self.compressed:
            return
        rank = self.rank.get(ident, len(self.rank))
        while self.compressed and self.compressed_bytes + len(data) > PRELOAD_BYTES:
            farthest = max(self.compressed, key=lambda i: self.rank.get(i, len(self.rank)))
            if self.rank.get(farthest, len(self.rank)) <= rank:
                return
            self.compressed_bytes -= len(self.compressed.pop(farthest)[0])
        self.compressed[ident] = (data, digest)
        self.compressed_bytes += len(data)

    def page(self, ident, context: tuple, digest: str) -> Optional[tuple]:
        """Pixels from read-ahead whose digest matches the selected lookup."""

        if self.context != context:
            return None
        if ident in self.prefetched:
            self.prefetched.move_to_end(ident)
            entry = self.prefetched[ident]
            if entry[1] == digest:
                return entry
        held = self.compressed.get(ident)
        if held is None or held[1] != digest:
            return None
        pixmap = QPixmap()
        if not pixmap.loadFromData(held[0]):
            return None
        entry = (display_pixmap(pixmap), held[1])
        self.hold_decoded(ident, *entry)
        return entry

    def hold_decoded(self, ident, pixmap: QPixmap, digest: str) -> None:
        """Keep a decoded page; at most PREFETCHED, the longest unused giving way (scrolling without a rest decodes
        page after page; the rest re-centres them on the slide on show)."""
        self.prefetched[ident] = (pixmap, digest)
        self.prefetched.move_to_end(ident)
        while len(self.prefetched) > PREFETCHED:
            self.prefetched.popitem(last=False)


class StepState:
    """The step bar's state: page lists of all-steps renders (a slide's steps as compressed images), the step picked
    per slide, and what is known about them. GUI thread only. Keys are `PreviewPane._steps_key`: a saved list's
    includes the pane's generation, so a list of before an invalidation is never found again."""

    def __init__(self) -> None:
        self.pages: OrderedDict[tuple, _PageResult] = OrderedDict()
        self.choice: dict[Path, int] = {}      # the step picked per slide; none: the last one
        self.pixmap: Optional[tuple[str, QPixmap]] = None   # last selected stored page, by image digest
        self.image: Optional[tuple[str, QImage]] = None    # a step decoded by the display worker
        self.scans: dict[tuple, reveal_steps.SlideScan] = {}
        self.failed: set[tuple] = set()        # page lists that did not render: not asked for again
        self.recheck: set[tuple] = set()       # saved page lists shown until the store confirms or replaces them
        self.stored: set[tuple] = set()        # page lists read from the store, not rendered in this session
        self.count_after: dict[tuple, Callable[[], None]] = {}   # steps key -> the render to queue if the store has none

    def invalidate(self) -> None:
        """The selection, view or language changed (or the slide was edited): the lists of before are not the
        pane's any more. What the user picked and what failed stay (a failure is asked again with a new key)."""
        self.count_after.clear()
        self.pages.clear()
        self.recheck.clear()
        self.stored.clear()
        self.pixmap = self.image = None

    def recheck_saved(self) -> None:
        """Ask the store again for the saved lists, but keep showing them until it answers."""
        self.recheck = {key for key in self.pages if key[0] != 'draft'}

    def keep(self, key: tuple, result: _PageResult) -> None:
        """Hold the list rendered here (not from the store); at most STEP_CACHE, the longest unused giving way."""
        self.pages[key] = result
        self.pages.move_to_end(key)
        self.stored.discard(key)
        while len(self.pages) > STEP_CACHE:
            old, _ = self.pages.popitem(last=False)
            self.stored.discard(old)

    def rendered(self, key: tuple, result: _PageResult | None, error: str) -> bool:
        """The step queue delivered a list (or its failure). True when `pages` was kept."""
        if error:
            self.failed.add(key)
            return False
        self.failed.discard(key)
        self.keep(key, result)
        return True

    def read(self, key: tuple, result: _PageResult | None) -> tuple[bool, Optional[Callable[[], None]]]:
        """Update the store's answer, returning whether the list needs refreshing and any render to queue."""
        render = self.count_after.pop(key, None)
        recheck = key in self.recheck
        self.recheck.discard(key)
        if result is None or not result.pages:
            if recheck and key in self.stored:
                self.pages.pop(key, None)
                self.stored.discard(key)
                return True, render
            return False, render
        self.keep(key, result)
        self.stored.add(key)
        return True, None

    def scan(self, key: tuple, make: Callable[[], reveal_steps.SlideScan]) -> reveal_steps.SlideScan:
        """The scan held for `key`, else `make()`; at most SCAN_CACHE, the oldest giving way."""
        scan = self.scans.get(key)
        if scan is None:
            scan = self.scans[key] = make()
            while len(self.scans) > SCAN_CACHE:
                self.scans.pop(next(iter(self.scans)))
        return scan


class Lookups:
    """The render store's lookups that are out, and the answer for the slide on show. One pending lookup per slot
    ('page', ('steps', key), 'pdf'): a newer one for the slot replaces it, and a selection change drops them all.
    The lookups run on the pane's display executor; their futures are kept here to be cancelled. The identity of a
    lookup has the pane's generation first, so an answer that arrives after an invalidation is not the pane's.
    GUI thread only."""

    def __init__(self) -> None:
        self.slots: dict = {}                 # slot -> (identity with the generation first, Future)
        self.stored: Optional[_PageResult] = None
        self.asked = None                     # what the page was last looked up for; the poll asks again

    def __contains__(self, slot) -> bool:
        return slot in self.slots

    def begin(self, slot, identity: tuple) -> bool:
        """False: a lookup for this slot and identity is out already. Else the slot's older lookup is cancelled and
        the caller starts the new one (`add`)."""
        held = self.slots.get(slot)
        if held is not None and held[0] == identity:
            return False
        if held is not None:
            held[1].cancel()
        return True

    def add(self, slot, identity: tuple, future) -> None:
        self.slots[slot] = (identity, future)

    def arrive(self, slot, identity: tuple) -> bool:
        """An answer came for (slot, identity): True (and the lookup is done) unless it was replaced or dropped."""
        held = self.slots.get(slot)
        if held is None or held[0] != identity:
            return False
        del self.slots[slot]
        return True

    def cancel_all(self) -> None:
        for _identity, future in self.slots.values():
            future.cancel()
        self.slots.clear()

    def close(self) -> None:
        self.slots.clear()
        self.stored = None


class AdhocBuffer:
    """The latest render made for the pane, held while the store cannot supply its page."""

    def __init__(self) -> None:
        self.value: Optional[_PageResult] = None
        self.text: Optional[str] = None
        self.note = ""
        self.full = False

    @property
    def spec(self):
        return self.value.request if self.value is not None else None

    def holds(self, key: tuple) -> bool:
        return self.value is not None and self.value.key == key

    def forget(self) -> None:
        self.value = None
        self.full = False

    def hold(self, result: _PageResult, text: str, note: str = "", *, full: bool = False) -> None:
        self.value, self.text, self.note, self.full = result, text, note, full


class PreviewModel:
    """The state of one Preview pane. The pane calls the `invalidate_*` method that says what changed."""

    def __init__(self) -> None:
        # Decoded pages of this session's saved renders, reusable after the selected lookup.
        self.pixmaps = DisplayCache()
        self.ahead = ReadAhead()
        self.steps = StepState()
        self.lookups = Lookups()
        self.adhoc = AdhocBuffer()

    def invalidate_selection(self) -> None:
        """The slide on show was edited, or its view or language changed, or it is rendered again: lookups out are
        dropped (their answers are not the pane's any more), as are the step lists and the chooser's answer. Kept for
        a return visit: the pages held for display and read ahead, the step picked per slide, the temporary page."""
        self.lookups.cancel_all()
        self.lookups.stored = None
        self.steps.invalidate()

    def invalidate_slide(self) -> None:
        """Another slide is on show: the temporary page of the one before is no longer its page."""
        self.adhoc.forget()

    def close(self) -> None:
        """The pane closes: let go of everything held. Python objects only (the C++ widget may be gone)."""
        self.ahead.drop()
        self.lookups.close()
        self.pixmaps.clear()
        self.steps.invalidate()
        self.adhoc.forget()
