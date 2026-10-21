# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Idle-time rendering of every slide of every deck, with all reveal steps (docs/plans/idle-background-rendering.md).

`BackgroundRenderer` joins the pieces: the store and the render key (what is current), the scheduler (what
runs when), the idle gate (when the machine is free), and a planner that lists what is outstanding in the
owner's order -- decks by recency (the open deck first), within a deck the instructor version, then the
other versions, within a version the slides from the last one looked at -- and feeds the scheduler a few
at a time. A render is one unrestricted latexmk run of the slide in the deck's preamble (every overlay step
is a page), rasterised by a raster process of its own and stored with the files it read. Units of one deck, view and
language are rendered several at a time in one document (`render_batch`) and split into the same records.

Free of Qt: the window supplies the gate's input events and the status chip reads `progress`.
"""
from __future__ import annotations

import os
import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import app_settings, course_schedule, deck_language, deck_settings, render_key, render_store, slide_language
from . import compile_records, parallel_runs, power_status, preview_build, preview_target, slide_preview, slide_snapshot
from .deck_editor import VIEWS, VIEW_INSTRUCTOR
from .deck_scan import Deck
from .dep_hash import HashCache, norm
from .idle_gate import CPU_LIMIT, IN_USE, PRESENTING, IdleGate
from .preview_raster_client import RasterClient
from .project import ProjectContext
from .render_scheduler import P_IDLE, P_NEIGHBOURS, Job, RenderScheduler
from .render_store import ORIGIN_BACKGROUND, ORIGIN_COMPILE, ORIGIN_REVEAL, RenderStore

STORE_WIDTH = 1920      # as wide as the Preview's own image (slide_snapshot.FULL_SIZE)
RASTER_CHUNK = 4                # pages per raster request, so another reader of a raster child never waits long
QUEUE_AHEAD = 12                # idle jobs handed to the scheduler at a time
STORE_FULL = "disk limit reached"            # Settings → Background previews → Disk limit
REPLAN_SECONDS = 120.0
MIN_REPLAN_SECONDS = 15.0
JOB_TIMEOUT = 180.0

ENABLED_KEY = "bg_previews_enabled"
ONLY_MAINS_KEY = "bg_previews_only_on_mains"
LIMIT_GB_KEY = "bg_previews_limit_gb"
PROFILE_KEY = "bg_previews_profile"
DECKS_OFF_KEY = "bg_previews_decks_off"
SECOND_LANGUAGE_KEY = "bg_previews_second_language"
KEEP_DAYS_KEY = "bg_previews_keep_days"
BATCH_SIZE_KEY = "bg_previews_batch_size"
DEFAULT_LIMIT_GB = 2.0
DEFAULT_BATCH_SIZE = 16         # slides rendered in one document (docs/findings.md, plan 5); 1: one document each
ALL_PAGES = 100000
# (processes at most, rest / job time). LaTeX runs on one core: "normal" may use a quarter of the cores, "fast" half
# (at most 16: about 300 MB of memory each). Each one beyond the first starts only while the CPU is below
# idle_gate.CPU_LIMIT, so the actual number settles at what the machine can spare.
_CORES = os.cpu_count() or 2
PROFILES = {"gentle": (1, 0.5), "normal": (max(1, _CORES // 4), 0.25),
            "fast": (parallel_runs.default_workers(), 0.0)}
DEFAULT_PROFILE = "fast"


def setting(ctx: ProjectContext, key: str, default):
    try:
        return app_settings.get(ctx, key, default)
    except OSError:
        return default


def batch_size(ctx: ProjectContext) -> int:
    """How many slides of a deck are rendered in one document (setting `bg_previews_batch_size`; 1: one each)."""
    try:
        return max(1, int(setting(ctx, BATCH_SIZE_KEY, DEFAULT_BATCH_SIZE)))
    except (TypeError, ValueError):
        return DEFAULT_BATCH_SIZE


def deck_language_code(deck: Deck) -> str:
    code = deck_settings.read_settings(deck.text).language.upper() if deck.preamble_end is not None else ""
    return code if code in slide_language.TRANSLATION_LANGUAGES else slide_language.TRANSLATION_LANGUAGES[0]


def deck_units(ctx: ProjectContext, deck: Deck, view: str, language: str, start_at: Optional[str] = None) -> list[render_key.Unit]:
    """The units of `deck` in `view` and `language` in deck order, beginning at the slide `start_at` (a bare id)
    and wrapping round; a call the view does not typeset, and one whose slide file is missing, have none."""
    if deck.preamble_end is None:
        return []
    links = slide_language.TranslationLinks(ctx.slides_dir)
    slots = deck_language._slots(deck_language.active_calls(deck), language, links)
    units: list[render_key.Unit] = []
    start_index = None
    for position, slot in enumerate(slots, start=1):
        call = slot.call
        if start_at and start_index is None and slot.matches(start_at):
            start_index = len(units)
        if not call.included_in(view) or not (ctx.slides_dir / call.source_filename).is_file():
            continue
        target = preview_target.for_call(ctx, deck, call, position)
        if target.needs_context:
            continue        # a contents or agenda slide is typeset with its deck when it is shown (deck_context), not here
        units.append(render_key.unit_for(target, view, language, deck.name))
    return units[start_index:] + units[:start_index] if start_index else units


@dataclass
class DeckProgress:
    deck: str
    total: int = 0
    fresh: int = 0
    failed: int = 0
    off: bool = False                               # the deck is left out of the background work
    views: dict = field(default_factory=dict)       # view -> [total, fresh, failed]

    @property
    def left(self) -> int:
        return self.total - self.fresh - self.failed

    @property
    def percent(self) -> float:
        return 100.0 * self.fresh / self.total if self.total else 100.0

    @property
    def up_to_date(self) -> bool:
        return not self.off and self.left == 0 and self.failed == 0

    def count(self, view: str, kind: int) -> None:
        """Count one unit of `view`: kind 0 = seen, 1 = fresh, 2 = failed."""
        self.views.setdefault(view, [0, 0, 0])[kind] += 1


@dataclass
class Progress:
    decks: list = field(default_factory=list)       # DeckProgress in priority order
    working: Optional[str] = None                   # label of the unit being rendered
    paused_because: Optional[str] = None            # why nothing runs (the gate's reason), if anything is left
    failures: int = 0
    scanned_at: float = 0.0

    @property
    def left(self) -> int:
        return sum(d.left for d in self.decks if not d.off)

    @property
    def total(self) -> int:
        return sum(d.total for d in self.decks if not d.off)

    @property
    def fresh(self) -> int:
        return sum(d.fresh for d in self.decks if not d.off)

    @property
    def percent(self) -> float:
        """The share of the renders of all prepared decks that are up to date (100 when there is nothing to render)."""
        return 100.0 * self.fresh / self.total if self.total else 100.0

    @property
    def decks_up_to_date(self) -> int:
        return sum(1 for d in self.decks if d.up_to_date)

    @property
    def decks_counted(self) -> int:
        return sum(1 for d in self.decks if not d.off)

    def deck(self, name: str) -> Optional[DeckProgress]:
        return next((d for d in self.decks if d.deck == name), None)


class Trace:
    """A small text file of what background rendering decided and when (focus, input, starts, stops, the chip), for
    finding out on a user's machine why it rendered or waited. Kept below MAX_BYTES: the older half goes to .1."""
    MAX_BYTES = 512 * 1024

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, line: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.is_file() and self.path.stat().st_size > self.MAX_BYTES:
                    os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))
                with open(self.path, "a", encoding="utf-8") as out:
                    out.write(f"{stamp} {line}\n")
            except OSError:
                pass


class Cancelled(RuntimeError):
    pass


class BackgroundRenderer:
    def __init__(self, ctx: ProjectContext, store: RenderStore, *, gate: Optional[IdleGate] = None,
                 decks: Callable[[], list] = lambda: [], open_deck: Callable[[], Optional[Deck]] = lambda: None,
                 engine_fp: Optional[Callable[[], str]] = None, renderer: Optional[Callable] = None,
                 raster: Optional[RasterClient] = None, batch_renderer: Optional[Callable] = None,
                 on_change: Callable[[], None] = lambda: None,
                 soon: Optional[Callable[[Deck], bool]] = None, clock: Callable[[], float] = time.time) -> None:
        self.ctx, self.store = ctx, store
        self.hashes = HashCache(store.db, store.lock)
        self.resolver = render_key.Resolver(ctx, self.hashes, store, engine_fp=engine_fp)
        # One meter for the idle gate and the rule for one more parallel render (several workers ask at once).
        self._cpu = power_status.shared_cpu_meter()
        self.gate = gate or IdleGate(
            enabled=lambda: self.enabled, only_on_mains=lambda: bool(setting(ctx, ONLY_MAINS_KEY, True)),
            free_bytes=lambda: power_status.free_bytes(store.root), cpu_load=self._cpu.load)
        self._decks, self._open_deck = decks, open_deck
        self._soon = soon or (lambda deck: course_schedule.session_soon(deck.course_url))
        self._render = renderer or self._render_pdf
        self._render_batch = batch_renderer or self._render_batch_pdf
        self._raster = raster
        self._on_change = on_change
        self._clock = clock
        profile = setting(ctx, PROFILE_KEY, DEFAULT_PROFILE)
        workers, duty = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
        self.scheduler = RenderScheduler(self._work, can_start=self._may_start,
                                         on_change=self._changed, on_error=self._failed, workers=workers, duty=duty,
                                         may_add=self._cpu_has_room, budget=parallel_runs.BUDGET)
        self.progress = Progress()
        self._plan: list = []
        self._plan_lock = threading.RLock()
        self._planned_at = 0.0
        self._replan = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._working: list[str] = []
        self._working_lock = threading.Lock()
        self._outstanding: dict[str, tuple] = {}
        self._single: set[str] = set()          # labels of the units whose last render failed: each is rendered on its own
        self._counted: set[str] = set()         # labels the plan counts as fresh already (only their page number differs)

    # -- settings ------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(setting(self.ctx, ENABLED_KEY, True))

    def batch_size(self) -> int:
        return batch_size(self.ctx)

    def decks_off(self) -> set[str]:
        return set(setting(self.ctx, DECKS_OFF_KEY, []) or [])

    def limit_bytes(self) -> int:
        try:
            return int(float(setting(self.ctx, LIMIT_GB_KEY, DEFAULT_LIMIT_GB)) * 1024 ** 3)
        except (TypeError, ValueError):
            return render_store.DEFAULT_LIMIT_BYTES

    # -- life ------------------------------------------------------------------------------

    def start(self) -> None:
        self.store.rescan()
        self.scheduler.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._plan_loop, daemon=True, name="background-planner")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._replan.set()
        self.scheduler.stop()
        if self._thread is not None:
            self._thread.join(5)

    def settings_changed(self) -> None:
        profile = setting(self.ctx, PROFILE_KEY, DEFAULT_PROFILE)
        self.scheduler.workers, self.scheduler.duty = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
        if self._thread is not None:
            self.scheduler.start()          # more workers at once when the profile allows more
        self.replan()

    def _cpu_has_room(self) -> bool:
        """One more render beside the running ones only while the CPU is below idle_gate.CPU_LIMIT (unknown: yes)."""
        load = self._cpu.load()
        return load is None or load < CPU_LIMIT

    def replan(self) -> None:
        """Something that decides what is outstanding changed (a deck opened, a setting): look again soon."""
        self._replan.set()

    def sweeping(self) -> bool:
        """The sweep is at work: a job runs, or it is between two jobs (the rest after one, the next being queued)
        and nothing holds it back. The status chip shows that as one piece of work, not a flicker of "preparing" and
        "waiting"."""
        progress = self.progress
        if self.scheduler.running_jobs():
            # Renders told to stop are left out (running_jobs, as in the status window): one that takes a while to
            # end kept the chip at "Preparing previews" after the user came back (v8.52.5).
            return True
        return progress.left > 0 and not self.waiting_because() and self.gate.sweeping()

    def waiting_because(self) -> Optional[str]:
        """Why nothing renders: the user at the window or a presentation, asked now (the planner's
        `progress.paused_because` is up to a planner step old, and a step can take long when it rescans the decks:
        the chip said "Preparing previews" for that long after the renders had stopped), else the planner's reason."""
        if self.gate.presenting():
            return PRESENTING
        if self.gate.in_use():
            return IN_USE
        return self.progress.paused_because

    def user_active(self) -> None:
        """The user did something: no new background job starts for a while. In front of the window (the only place
        input reaches) the running ones stop too, so the app answers at once."""
        self.gate.note_input()
        if self.gate.in_front and not self.gate.forced():
            stopped = self.scheduler.interrupt(P_IDLE)
            if stopped:
                self.trace(f"input: stopped {stopped}")

    def presentation_started(self) -> None:
        """No background render during a presentation (idle_gate.PRESENTING): the running ones stop."""
        self.trace(f"presentation: stopped {self.scheduler.interrupt(P_IDLE)}")
        self._changed()

    def window_focus(self, active: bool) -> None:
        """SlideMage's window got or lost the focus. Coming to the front stops the running background renders (they
        are put back and run again later), so that the app answers at once; "Render now" keeps them going. In front,
        rendering may start again after idle_gate.IN_FRONT_IDLE without input; out of focus after LEAVE_GRACE."""
        self.gate.note_focus(active)
        stopped = self.scheduler.interrupt(P_IDLE) if active and not self.gate.forced() else 0
        self.trace(f"focus {'in' if active else 'out'}: stopped {stopped}")
        # No replan: what is outstanding did not change, and a rescan of every deck at each switch of windows
        # kept the planner (and the chip's reason) busy. The planner's next step, within 2 s, tops up again.
        self._changed()

    def _may_start(self, job) -> bool:
        if not self.gate.allowed():
            return False
        self.gate.note_started()
        return True

    def trace(self, event: str) -> None:
        """One line in the trace file (render_trace.Trace): the event and what the gate knows at that moment."""
        tracer = getattr(self, "_trace", None)
        if tracer is None:
            return
        gate = self.gate
        with self._working_lock:
            running = len(self._working)
        since = gate._clock() - gate.last_input
        tracer.write(f"{event} | in_front={gate.in_front} input {since:.0f} s ago forced={gate.forced()} "
                     f"running={running} planner={self.progress.paused_because!r}")

    # -- what is outstanding ---------------------------------------------------------------

    def ordered_decks(self) -> list[Deck]:
        """The decks to prepare, most important first: the open deck, those with a course session soon, the
        decks opened on this machine by recency, then the rest by the newest change to their file."""
        usage = {u["deck"]: u for u in self.store.deck_usage()}
        off = self.decks_off()
        decks = [d for d in self._decks() if not d.archived and not d.is_test_deck and d.name not in off and d.preamble_end is not None]
        open_deck = self._open_deck()

        def mtime(deck: Deck) -> float:
            try:
                return deck.path.stat().st_mtime
            except OSError:
                return 0.0

        def order(deck: Deck):
            opened = usage.get(deck.name, {}).get("last_opened")
            return (0 if open_deck is not None and deck.name == open_deck.name else 1,
                    0 if self._soon(deck) else 1,
                    0 if opened else 1, -(opened or 0), -mtime(deck))

        return sorted(decks, key=order)

    def versions_for(self, deck: Deck) -> list[str]:
        return list(VIEWS) if deck.supports_version else [VIEW_INSTRUCTOR]

    def languages_for(self, deck: Deck) -> list[str]:
        usage = next((u for u in self.store.deck_usage() if u["deck"] == deck.name), None)
        primary = (usage or {}).get("last_language") or deck_language_code(deck)
        languages = [primary.upper()]
        if setting(self.ctx, SECOND_LANGUAGE_KEY, False):
            languages += [l for l in slide_language.TRANSLATION_LANGUAGES if l not in languages]
        return languages

    def scan(self) -> list:
        """Everything outstanding, in the order it is rendered: [(sort key, unit)], and the progress counts.
        Units that are only out of step in their page number come after all the others."""
        decks_progress: list[DeckProgress] = []
        first: list = []
        numbering: list = []
        single: set[str] = set()
        usage = {u["deck"]: u for u in self.store.deck_usage()}
        for deck_rank, deck in enumerate(self.ordered_decks()):
            progress = DeckProgress(deck.name)
            decks_progress.append(progress)
            start_at = usage.get(deck.name, {}).get("last_slide")
            for language_rank, language in enumerate(self.languages_for(deck)):
                for view_rank, view in enumerate(self.versions_for(deck)):
                    try:
                        units = deck_units(self.ctx, deck, view, language, start_at)
                    except Exception:  # noqa: BLE001 -- a deck that cannot be read now is tried again next time
                        continue
                    for order, unit in enumerate(units):
                        progress.total += 1
                        progress.count(view, 0)
                        found = self.resolver.lookup(unit)
                        if found.final and found.state is not render_key.Freshness.FAILED:
                            progress.fresh += 1
                            progress.count(view, 1)
                        elif found.state is render_key.Freshness.FAILED:
                            if found.failure and self.store.may_retry(found.failure):
                                first.append(((deck_rank, language_rank, view_rank, order), unit))
                                single.add(unit.label)          # a batch holding it would fail again
                            else:
                                progress.failed += 1
                                progress.count(view, 2)
                        elif found.usable and found.record and found.record.get("origin") == ORIGIN_BACKGROUND:
                            progress.fresh += 1                  # right, apart from its page number: refreshed last
                            progress.count(view, 1)
                            numbering.append(((deck_rank, language_rank, view_rank, order), unit))
                        else:
                            first.append(((deck_rank, language_rank, view_rank, order), unit))
        off = self.decks_off()
        decks_progress += [DeckProgress(d.name, off=True) for d in self._decks()
                           if not d.archived and not d.is_test_deck and d.name in off]
        plan = first + [((1000 + k[0],) + k[1:], u) for k, u in numbering]
        self._single = single
        self._counted = {unit.label for _rank, unit in numbering}
        failures = self.store_failures_count()
        with self._working_lock:
            # What runs now, from the workers' own list under their lock: copied from the old progress, a render that
            # ended during the scan stayed "working" until the next one started, and in front of the window none does:
            # the chip said "Preparing previews" with nothing running (v8.52.4).
            self.progress = Progress(decks_progress, self._working[0] if self._working else None, None,
                                     failures, self._clock())
        return plan

    def store_failures_count(self) -> int:
        return len(self.store.failures())

    # -- planner thread --------------------------------------------------------------------

    def _plan_loop(self) -> None:
        while not self._stop.is_set():
            self._replan.wait(2.0)
            if self._stop.is_set():
                return
            try:
                self.tick()
            except Exception:  # noqa: BLE001 -- the planner must outlive any one bad deck
                time.sleep(5)

    def tick(self) -> None:
        """One planner step: replan when asked or stale, top up the scheduler while the gate allows."""
        now = self._clock()
        if not self.enabled:
            self.progress.paused_because = "switched off"
            self._changed()
            return
        if self._replan.is_set() or now - self._planned_at > REPLAN_SECONDS or (
                not self._plan and self.progress.left and not self.scheduler.pending() and now - self._planned_at > MIN_REPLAN_SECONDS):
            self._replan.clear()
            plan = self.scan()
            with self._plan_lock:
                self._plan = plan
                self._outstanding = {u.label: (k, u) for k, u in plan}
            self._planned_at = now
            self._evict()
        reason = self.gate.reason()
        if reason is None and self._top_up() and not self.scheduler.pending():
            reason = STORE_FULL
        before = self.progress.paused_because
        self.progress.paused_because = reason if (self._plan or self.scheduler.pending()) else None
        if self.progress.paused_because != before:
            self.trace(f"planner: {self.progress.paused_because or 'may render'}")
        self._changed()

    def _top_up(self) -> bool:
        """Hand the next units of the plan to the scheduler, up to `batch_size()` of a deck, view and language in
        one job. With the store at its limit, only those of the protected decks: another deck's render would push out
        a render the plan then counts as outstanding again, and the sweep would go round in circles. Returns whether
        units were held back for that."""
        keep = self._protected_decks() if self._store_full() else None
        size = self.batch_size()
        ahead = QUEUE_AHEAD if size == 1 else min(QUEUE_AHEAD, self.scheduler.workers + 2)      # a job is many units
        held = False
        with self._plan_lock:
            on_its_way = {u.label for job in self.scheduler.jobs(P_IDLE) for u in job.payload[0]} if size > 1 else set()
            i = 0
            while i < len(self._plan) and self.scheduler.pending(P_IDLE) < ahead:
                rank, unit = self._plan[i]
                if keep is not None and unit.deck not in keep:
                    held = True
                    i += 1
                    continue
                if unit.label in on_its_way:
                    del self._plan[i]
                    continue
                batch = self._take_batch(i, size, on_its_way)
                key = batch[0].label if len(batch) == 1 else f"{batch[0].label}+{len(batch) - 1}"
                self.scheduler.submit(key, (tuple(batch), ORIGIN_BACKGROUND), P_IDLE, rank, group=unit.deck)
            return held or (keep is not None and any(unit.deck not in keep for _rank, unit in self._plan[i:]))

    def _take_batch(self, i: int, size: int, on_its_way: set) -> list[render_key.Unit]:
        """Remove from the plan, beginning at index `i`, the unit there and the units after it that are rendered in one
        document with it: the same deck, view, language and preamble, the next ones in the plan (those on their way
        already are dropped), at most one per bare slide id, none that failed before. Call under `_plan_lock`."""
        first = self._plan.pop(i)[1]
        batch = [first]
        if first.label in self._single:
            return batch
        ids = {slide_language.bare_id(first.id_slug)}
        same = lambda u: (u.deck, u.view, u.language, u.preamble_text) == (first.deck, first.view, first.language, first.preamble_text)
        while len(batch) < size and i < len(self._plan) and same(self._plan[i][1]):
            unit = self._plan[i][1]
            bare = slide_language.bare_id(unit.id_slug)
            if unit.label in on_its_way:
                del self._plan[i]
            elif bare in ids or unit.label in self._single:
                i += 1                  # waits for a later batch, or for its own job
            else:
                ids.add(bare)
                batch.append(self._plan.pop(i)[1])
        return batch

    def _store_full(self) -> bool:
        """Whether one more render of the average size would take the store past its limit."""
        count = self.store.count()
        total = self.store.total_bytes()
        return bool(count) and total + total / count > self.limit_bytes()

    def _protected_decks(self) -> set[str]:
        """The decks whose renders the disk limit keeps: the open deck and the five opened most recently."""
        protected = {u["deck"] for u in self.store.deck_usage()[:5]}
        open_deck = self._open_deck()
        if open_deck is not None:
            protected.add(open_deck.name)
        return protected

    def _evict(self) -> None:
        names = {d.name for d in self._decks() if not d.archived}
        self.store.enforce_limit(self.limit_bytes(), protected_decks=self._protected_decks(),
                                 keep_days=int(setting(self.ctx, KEEP_DAYS_KEY, render_store.DEFAULT_KEEP_DAYS)),
                                 is_orphan=lambda decks: bool(decks) and not set(decks) & names)

    # -- foreground helpers ------------------------------------------------------------------

    def submit_neighbours(self, unit: render_key.Unit, rank: tuple = ()) -> None:
        """The reveal slider's render of a unit (class P_NEIGHBOURS): it runs before any idle job and never waits for one."""
        self.scheduler.submit(unit.label, ((unit,), ORIGIN_REVEAL), P_NEIGHBOURS, rank, group="reveal")

    def store_reveal(self, unit: render_key.Unit, pdf: Path, pages: list[bytes]) -> Optional[str]:
        """Keep the all-steps render the reveal bar made (its PDF and page images) as a provisional store object, so
        the next count of this slide, in this session or the next, is read from the store, not rendered."""
        key = self.resolver.fast_key(unit)
        if key is None:
            return None
        found = self.resolver.lookup(unit, key)
        if found.state is render_key.Freshness.FRESH and not (found.record or {}).get("partial"):
            return None
        manifest = self.resolver.build_manifest(self._recorded_inputs(pdf))
        if not manifest.stable or not pages:
            return None
        meta = dict(unit=unit.label, rendered_at=time.time(), duration_ms=0, manifest=manifest.entries,
                    tex_digest=manifest.tex_digest, tex_files=manifest.tex_files, machine=render_key.machine_id(),
                    engine_fp=self.resolver.engine_fp, frame_number=unit.frame_number, unstable=False, width=STORE_WIDTH)
        return self.store.put(key, ORIGIN_REVEAL, pdf, pages, meta, decks=[unit.deck] if unit.deck else [],
                              replace=bool((found.record or {}).get("partial")))        # the page of a compile gives way

    def ingest_compile(self, job, pdf: Path, record: dict) -> int:
        """Keep the slides of a whole-deck compile in the store: the last page of every slide the PDF shows, for the
        view and language the deck was compiled in, so the Preview shows it as a current render, with no note, for as
        long as what the slide depends on is unchanged. The dependencies are the compile record's (compile_records.py):
        every file the compile read, with its SHA-256, except the other slides, and media or snippets this slide
        does not mention. Returns how many slides were stored. Run off the GUI thread."""
        if job.chapter is not None or getattr(job, "pages", None) or job.presenter:
            return 0
        if compile_records.sha256(pdf) != record.get("pdf_sha256"):
            return 0                                    # not the PDF the record describes (another compile replaced it)
        view = job.version or VIEW_INSTRUCTOR
        language = (getattr(job, "language", None) or deck_language_code(job.deck)).upper()
        recorded = {norm(entry["path"]): (Path(entry["path"]), entry["sha256"])
                    for entry in record.get("inputs", []) if not entry.get("copy")}
        import pymupdf
        try:
            doc = pymupdf.open(pdf)
        except Exception:  # noqa: BLE001
            return 0
        try:
            runs: dict[str, list[int]] = {}
            for slide_id, pages in slide_snapshot.slide_runs([slide_snapshot.slide_id_of(page) for page in doc]):
                runs.setdefault(slide_id, pages)        # the first showing of a slide that appears twice
        finally:
            doc.close()
        raster, stored = self._raster or self._shared_raster(), 0
        for unit in deck_units(self.ctx, job.deck, view, language):
            pages = runs.get(slide_language.bare_id(unit.id_slug))
            known = recorded.get(norm(unit.source_path))
            if unit.macro == "slidestep" or not pages or known is None:
                continue
            key = self.resolver.fast_key(unit)
            if key is None or self.hashes.hash(unit.source_path) != known[1]:
                continue                                # the slide changed since the compile
            if self.resolver.lookup(unit, key).usable:
                continue                                # a render of it is current already
            entries = self._compile_manifest(recorded, unit)
            response = raster.read_document(pdf, "pdf_images", pages[-1] + 1, 1, width=STORE_WIDTH)
            if not response["images"]:
                continue
            meta = dict(unit=unit.label, rendered_at=time.time(), duration_ms=0, manifest=entries, tex_digest="",
                        machine=render_key.machine_id(), engine_fp=self.resolver.engine_fp,
                        frame_number=unit.frame_number, unstable=False, width=STORE_WIDTH, partial=True)
            self.store.put(key, ORIGIN_COMPILE, None, [response["images"][0]], meta,
                           decks=[unit.deck] if unit.deck else [])
            stored += 1
        return stored

    def _compile_manifest(self, recorded: dict, unit: render_key.Unit) -> list:
        """What a slide's page in a deck compile depends on, from the compile record's hashes."""
        entries = []
        for path in render_key.unit_inputs(self.ctx, [path for path, _sha in recorded.values()], unit.source_path):
            where = self.resolver._relative(path)
            if where is not None:
                entries.append([where[0], where[1], recorded[norm(path)][1]])
        entries.sort()
        return entries

    def deck_archived(self, deck: Deck) -> None:
        self.scheduler.cancel_group(deck.name)
        self.store.drop_deck(deck.name)
        self.replan()

    # -- the work ----------------------------------------------------------------------------

    def _work(self, job: Job, cancel) -> None:
        units, origin = job.payload
        self._set_working(job.key, True)
        self.trace(f"start {job.key}")
        try:
            if len(units) > 1:
                self.render_batch(units, job.rank, cancel)
            elif self.render_unit(units[0], origin, cancel) is not None:
                self._count_fresh(units[0])
        finally:
            self._set_working(job.key, False)
            self.trace(f"end {job.key}{' (stopped)' if cancel.is_set() else ''}")

    def _count_fresh(self, unit: render_key.Unit) -> None:
        if unit.label in self._counted:
            # Counted as fresh by the plan (right apart from its page number) and refreshed now: counted again, the
            # number left ran ahead by a batch and the next plan put it back up (582 -> 598, v8.52.4).
            self._counted.discard(unit.label)
            return
        counted = self.progress.deck(unit.deck)
        if counted is not None and counted.fresh < counted.total:
            counted.fresh += 1
            counted.count(unit.view, 1)

    def _set_working(self, label: str, on: bool) -> None:
        """`progress.working` names a unit that is rendering while any is (several run at once)."""
        with self._working_lock:
            (self._working.append if on else self._working.remove)(label)
            self.progress.working = self._working[0] if self._working else None

    def running(self) -> list[dict]:
        """What renders right now, one entry per render, the longest-running first: for the status window."""
        now = self.scheduler._clock()
        entries = []
        for job in self.scheduler.running_jobs():
            units, origin = job.payload
            unit = units[0]
            entries.append(dict(deck=unit.deck, slide=unit.id_slug if len(units) == 1 else f"{len(units)} slides",
                                view=unit.view, language=unit.language,
                                kind="reveal steps" if origin == ORIGIN_REVEAL else "background",
                                seconds=max(0.0, now - job.started)))
        return entries

    def capacity(self) -> tuple[int, Optional[float]]:
        """(how many may render at once, the processor's load now: None when unknown)."""
        return self.scheduler.workers, self._cpu.load()

    def render_unit(self, unit: render_key.Unit, origin: str, cancel) -> Optional[str]:
        """Render `unit` into the store unless a current render is there. Returns the object name, or None."""
        key = self.resolver.fast_key(unit)
        if key is None:
            raise _transient("the slide file is being written")
        found = self.resolver.lookup(unit, key)
        if found.state is render_key.Freshness.FAILED and not (found.failure and self.store.may_retry(found.failure)):
            return None
        if found.state is render_key.Freshness.FRESH and (origin == ORIGIN_REVEAL or found.final):
            self.store.link_decks(found.record["name"], [unit.deck])
            return found.record["name"]
        started = time.time()
        pdf: Optional[Path] = None
        try:
            pdf = self._render(unit, cancel)
            if cancel.is_set():
                raise Cancelled("Preview cancelled")
            manifest = self.resolver.build_manifest(self._recorded_inputs(pdf))
            pages = self._rasterise(pdf, cancel)
            if not pages:
                raise _deterministic("the render has no pages (the slide is not typeset in this view)")
            return self._store_render(unit, key, found, origin, pdf, pages, manifest, started)
        except BaseException as exc:
            if cancel.is_set():
                raise
            self._record_failure(key, exc, started, unit)
            raise
        finally:
            if pdf is not None and pdf.parent.name.startswith(preview_build.RENDER_FOLDER_PREFIX):
                shutil.rmtree(pdf.parent, ignore_errors=True)

    def _store_render(self, unit: render_key.Unit, key: str, found: render_key.Lookup, origin: str, pdf: Path,
                      pages: list[bytes], manifest: render_key.Manifest, started: float) -> str:
        meta = dict(unit=unit.label, rendered_at=time.time(), duration_ms=int((time.time() - started) * 1000),
                    manifest=manifest.entries, tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                    machine=render_key.machine_id(), engine_fp=self.resolver.engine_fp, frame_number=unit.frame_number,
                    unstable=not manifest.stable, width=STORE_WIDTH)
        replace = (found.record is not None and found.state is render_key.Freshness.FRESH_NUMBERING_DIFFERS
                   and found.record.get("origin") == origin)
        return self.store.put(key, origin, pdf, pages, meta, decks=[unit.deck], replace=replace)

    @staticmethod
    def _recorded_inputs(pdf: Path) -> list[str]:
        """The files the render of `pdf` read (preview_build.write_inputs)."""
        inputs_file = pdf.with_suffix(".inputs.json")
        return json.loads(inputs_file.read_text(encoding="utf-8")) if inputs_file.is_file() else []

    def render_batch(self, units: tuple, rank: tuple, cancel) -> None:
        """Render `units` (one deck, view, language and preamble, one per bare slide id) in one document and store
        each one's pages with the record `render_unit` would make. A unit that is current already is left out. If the
        document does not compile or its pages cannot be told apart, nothing is stored and the units are queued singly,
        so a broken slide is found and remembered by its own render. A unit edited meanwhile is left for the next plan."""
        todo, singly = [], []
        for unit in units:
            key = self.resolver.fast_key(unit)
            found = self.resolver.lookup(unit, key) if key is not None else None
            if found is None:
                singly.append(unit)                     # the file is being written: its own job raises "transient"
            elif found.state is render_key.Freshness.FAILED and not (found.failure and self.store.may_retry(found.failure)):
                continue
            elif found.state is render_key.Freshness.FRESH and found.final:
                self.store.link_decks(found.record["name"], [unit.deck])
                self._count_fresh(unit)
            else:
                todo.append((unit, key, found))
        if len(todo) == 1:
            singly += [todo.pop()[0]]
        done: set[str] = set()
        started, pdf = time.time(), None
        if todo:
            try:
                pdf = self._render_batch([unit for unit, _key, _found in todo], cancel)
                if cancel.is_set():
                    raise Cancelled("Preview cancelled")
                self._store_batch(pdf, todo, started, cancel, done)
            except Exception:  # noqa: BLE001 -- whatever went wrong, the units are tried one by one
                if cancel.is_set():
                    raise
            finally:
                if pdf is not None and pdf.parent.name.startswith(preview_build.RENDER_FOLDER_PREFIX):
                    shutil.rmtree(pdf.parent, ignore_errors=True)
            singly += [unit for unit, _key, _found in todo if unit.label not in done]
        for unit in singly:
            self.scheduler.submit(unit.label, ((unit,), ORIGIN_BACKGROUND), P_IDLE, rank, group=unit.deck)

    def _store_batch(self, pdf: Path, todo: list, started: float, cancel, done: set[str]) -> None:
        """Split the batch PDF by slide (the slide id on each page) and store every unit; `done` collects the labels
        of the units dealt with. RuntimeError when the pages are not the planned slides'."""
        raster = self._raster or self._shared_raster()
        response = raster.read_document(pdf, "pdf", 1, ALL_PAGES)
        runs = slide_snapshot.batch_runs(response["texts"], [slide_language.bare_id(unit.id_slug) for unit, _key, _found in todo])
        inputs = [Path(name) for name in self._recorded_inputs(pdf)]
        for number, ((unit, key, found), pages) in enumerate(zip(todo, runs)):
            if cancel.is_set():
                raise Cancelled("Preview cancelled")
            if self.resolver.fast_key(unit) != key:
                done.add(unit.label)                    # edited since it was planned
                continue
            own = pdf.parent / f"unit-{number}.pdf"
            raster.read_document(pdf, "extract_pages", pages[0] + 1, len(pages), out=own)
            images = self._rasterise(own, cancel)
            if len(images) != len(pages):
                raise RuntimeError("the pages of a slide were not all rendered")
            manifest = self.resolver.build_manifest([str(path) for path in render_key.unit_inputs(self.ctx, inputs, unit.source_path)])
            self._store_render(unit, key, found, ORIGIN_BACKGROUND, own, images, manifest, started)
            done.add(unit.label)
            self._count_fresh(unit)

    def _render_batch_pdf(self, units: list, cancel) -> Path:
        first = units[0]
        return slide_preview.render_slides_to_pdf(
            self.ctx, [(u.macro, u.id_slug, u.version, u.render_conditions, u.frame_number) for u in units],
            first.view, first.language.lower(), first.preamble_text, log=lambda line: None, cancel=cancel,
            workspace=self.store.work_dir)

    def _render_pdf(self, unit: render_key.Unit, cancel) -> Path:
        return slide_preview.render_slide_to_pdf(
            self.ctx, unit.macro, unit.id_slug, unit.version, unit.render_conditions, deck_version=unit.view,
            deck_language=unit.language.lower(), preamble_text=unit.preamble_text,
            frame_number=unit.frame_number, log=lambda line: None, steps=None, capture_snapshot=False, cancel=cancel,
            all_steps=True, workspace=self.store.work_dir)

    def _rasterise(self, pdf: Path, cancel) -> list[bytes]:
        raster = self._raster or self._shared_raster()
        pages: list[bytes] = []
        start, count = 1, None
        while count is None or start <= count:
            if cancel.is_set():
                raise Cancelled("Preview cancelled")
            response = raster.read_document(pdf, "pdf_images", start, RASTER_CHUNK, width=STORE_WIDTH)
            count = response["count"]
            pages += response["images"]
            if not response["images"]:
                break
            start += RASTER_CHUNK
        return pages

    def _shared_raster(self) -> RasterClient:
        if getattr(self, "_own_raster", None) is None:
            self._own_raster = RasterClient()
        return self._own_raster

    def _record_failure(self, key: str, exc: BaseException, started: float, unit: render_key.Unit) -> None:
        kind = getattr(exc, "kind", None) or (render_store.DETERMINISTIC if str(exc).startswith("Render failed") else render_store.TRANSIENT)
        inputs = [str(unit.source_path)] + self._failed_inputs(started)
        manifest = self.resolver.build_manifest(inputs).entries
        self.store.record_failure(key, kind, str(exc), manifest)

    def _failed_inputs(self, started: float) -> list[str]:
        """The files the failed run read, from the newest recorder file of the preview builds since `started`."""
        try:
            newest = max((p for p in (self.ctx.build_dir / "preview-cache").glob("*/*.fls") if p.stat().st_mtime >= started - 1),
                         key=lambda p: p.stat().st_mtime, default=None)
            if newest is None:
                return []
            return preview_build.recorded_inputs(newest, newest.with_suffix(".fdb_latexmk"), project_root=self.ctx.root,
                                                 cache=newest.parent)
        except OSError:
            return []

    def _failed(self, job: Job, exc: BaseException) -> None:
        self.progress.failures = self.store_failures_count()
        unit = job.payload[0][0]
        counted = self.progress.deck(unit.deck)
        if counted is not None and getattr(exc, "kind", None) == render_store.DETERMINISTIC or str(exc).startswith("Render failed"):
            if counted is not None:
                counted.failed += 1
                counted.count(unit.view, 2)

    def _changed(self) -> None:
        try:
            self._on_change()
        except Exception:  # noqa: BLE001 -- a broken indicator must not stop the work
            pass


def _transient(message: str) -> RuntimeError:
    error = RuntimeError(message)
    error.kind = render_store.TRANSIENT          # type: ignore[attr-defined]
    return error


def _deterministic(message: str) -> RuntimeError:
    error = RuntimeError(message)
    error.kind = render_store.DETERMINISTIC      # type: ignore[attr-defined]
    return error
