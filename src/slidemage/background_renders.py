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
import logging
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import app_settings, deck_language, deck_settings, languages, render_evidence, render_key, render_lookup, render_store, slide_language
from . import compile_records, deck_context, parallel_runs, batch_render, power_status, preview_requests, preview_target, slide_snapshot, slide_templates
from .deck_editor import VIEWS, VIEW_INSTRUCTOR
from .deck_scan import Deck
from .dep_hash import HashCache, norm
from .fileio import text_sha256
from .idle_gate import CPU_LIMIT, IN_USE, PRESENTING, IdleGate
from .preview_raster_client import RasterClient
from .project import ProjectContext
from .render_scheduler import P_IDLE, Job, RenderScheduler
from .render_store import ORIGIN_COMPILE, RenderStore

STORE_WIDTH = 1920      # as wide as the Preview's own image (slide_snapshot.FULL_SIZE)
RASTER_CHUNK = 4                # pages per raster request, so another reader of a raster child never waits long
QUEUE_AHEAD = 12                # idle jobs handed to the scheduler at a time
STORE_FULL = "disk limit reached"            # Settings → Background previews → Disk limit
REPLAN_SECONDS = 120.0
MIN_REPLAN_SECONDS = 15.0
RENDER_OTHER_VIEWS = True

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
_trace_log = logging.getLogger("slidemage.background")
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


def deck_language_code(ctx: ProjectContext, deck: Deck) -> str:
    """The deck's `\\decklanguage`, upper case; the project's main language for a deck with no preamble."""
    if deck.preamble_end is None:
        return languages.project_languages(ctx).codes[0]
    return deck_settings.read_settings(deck.text).language.upper()


def deck_units(ctx: ProjectContext, deck: Deck, view: str, language: str, start_at: Optional[str] = None,
               context_ready: Optional[Callable[[], bool]] = None) -> list[render_key.Unit]:
    """The units of `deck` in `view` and `language` in deck order, beginning at the slide `start_at` (a bare id)
    and wrapping round; a call the view does not typeset, and one whose slide file is missing, have none. A slide
    that needs its deck (a contents or agenda slide, a section divider) is typeset in the deck's last compile, so it
    is a unit only when `context_ready()` says there is one to use; without it (the default) it is left out."""
    if deck.preamble_end is None:
        return []
    links = slide_language.links_for(ctx)
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
        if target.needs_context and not (context_ready is not None and context_ready()):
            continue        # no deck compile to typeset it in: the Preview renders it on its own when it is shown
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
    blocked: int = 0                                # its template is nowhere to be found: not rendered (see scan)

    @property
    def left(self) -> int:
        return self.total - self.fresh - self.failed - self.blocked

    @property
    def percent(self) -> float:
        return 100.0 * self.fresh / self.total if self.total else 100.0

    @property
    def up_to_date(self) -> bool:
        return not self.off and self.left == 0 and self.failed == 0 and self.blocked == 0

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
    missing_templates: dict = field(default_factory=dict)   # template key -> decks using it that cannot find it

    @property
    def blocked(self) -> int:
        """Renders held back because their deck's template is missing (not counted as left or failed)."""
        return sum(d.blocked for d in self.decks if not d.off)

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


class Cancelled(RuntimeError):
    pass


def _template_was_missing(failure: Optional[dict], template: str) -> bool:
    """Whether a stored failure is TeX not finding the template's file (the template is there now)."""
    error = (failure or {}).get("error") or ""
    return f"\\input{{{slide_templates.TEMPLATE_PREFIX}{template}}}" in error and "Emergency stop" in error


class BackgroundRenderer:
    def __init__(self, ctx: ProjectContext, store: RenderStore, *, gate: Optional[IdleGate] = None,
                 decks: Callable[[], list] = lambda: [], open_deck: Callable[[], Optional[Deck]] = lambda: None,
                 engine_fp: Optional[Callable[[], str]] = None, renderer: Optional[Callable] = None,
                 raster: Optional[RasterClient] = None,
                 renders: Optional[preview_requests.RenderService] = None,
                 on_change: Callable[[], None] = lambda: None,
                 plugin_soon: Optional[Callable[[Deck], bool]] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.ctx, self.store = ctx, store
        self.hashes = HashCache(store.db, store.lock)
        self.resolver = render_key.Resolver(ctx, self.hashes, store, engine_fp=engine_fp)
        # One meter for the idle gate and the rule for one more parallel render (several workers ask at once).
        self._cpu = power_status.shared_cpu_meter()
        self.gate = gate or IdleGate(
            enabled=lambda: self.enabled, only_on_mains=lambda: bool(setting(ctx, ONLY_MAINS_KEY, True)),
            free_bytes=lambda: power_status.free_bytes(store.root), cpu_load=self._cpu.load)
        self._decks, self._open_deck = decks, open_deck
        self.plugin_soon = plugin_soon          # the loaded plugins' rule (plugins.host.plugin_render_priority); settable
        self._render = renderer
        self.renders = renders or preview_requests.RenderService()
        self.renders._background, self.renders._owns_background = self, False   # the window owns the store
        self._raster = raster
        self._on_change = on_change
        self._clock = clock
        profile = setting(ctx, PROFILE_KEY, DEFAULT_PROFILE)
        workers, duty = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
        self.scheduler = RenderScheduler(self._work, can_start=self._may_start,
                                         on_change=self._changed, on_error=lambda job, exc: self._failed(job.payload[0][0], exc),
                                         workers=workers, duty=duty,
                                         may_add=self._cpu_has_room, budget=parallel_runs.BUDGET)
        self.progress = Progress()
        self._plan: list = []
        self._plan_lock = threading.RLock()
        self._planned_at = 0.0
        self._replan = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.rescanning = False                 # the store's rescan runs (start() .. the planner's first step)
        self._working: list[str] = []
        self._working_lock = threading.Lock()
        self._outstanding: dict[str, tuple] = {}
        self._single: set[str] = set()          # labels of the units whose last render failed: each is rendered on its own
        self._counted: set[str] = set()         # labels the progress counts as fresh already: each is counted once
        self._last_try: set[str] = set()        # labels of failed units tried once more now that the rest is rendered
        self._failure_keys: set[str] = set()    # failures that the current decks still use, with unchanged inputs
        self._failure_slides: dict[str, set] = {}   # failure key -> the slides (deck, id) whose units have that key
        self._current: Optional[_CurrentKeys] = None    # what the last scan found current (stale renders go, _drop_stale)

    def _soon(self, deck: Deck) -> bool:
        """A loaded plugin's rule (a session soon, say)."""
        return bool(self.plugin_soon is not None and self.plugin_soon(deck))

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
        # The store's rescan (6000 folders: seconds warm, most of a minute with a cold file cache) runs first on the
        # planner's thread, not here: the window opened only after it (2026-10-29, direct request: SlideMage took
        # about a minute to open). Until it ends the index holds what it held at the last run, which is what the
        # readers use; `rescanning` lets the status say so.
        self.scheduler.start()
        self._stop.clear()
        self.rescanning = True
        self._thread = threading.Thread(target=self._plan_loop, daemon=True, name="background-planner")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._replan.set()
        self.scheduler.stop()
        self.renders.close()
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

    def user_active(self, scroll: bool = False) -> None:
        """The user did something: no new background job starts for a while. In front of the window (the only place
        input reaches) the running ones stop too, so the app answers at once. A wheel turn (scroll) also stops them
        when another program has the focus."""
        self.gate.note_input()
        if scroll:
            self.gate.note_scroll()
        if (self.gate.in_front or scroll) and not self.gate.forced():
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

    def submit_other_views(self, spec: preview_requests.PreviewRequest) -> None:
        """Prepare the focused revision's other views through the idle queue, ahead of the sweep."""
        if (not RENDER_OTHER_VIEWS or spec.options.presenter or spec.options.mode != 'slide'
                or spec.options.overlay is not None):
            return
        target = spec.target
        views = self.versions_for(target.deck) if target.deck is not None else VIEWS
        requests = batch_render.plan_slide(
            self.ctx, target.deck, target.source_path, 'all', spec.language,
            occurrence_key=target.occurrence_key,
            options=preview_requests.RenderOptions(saved=spec.options.saved, all_steps=True),
            read_source=lambda path: spec.revision.text if path == spec.revision.path else None)
        group = f"other:{spec.revision.path}"
        for other in requests:
            if other.view == spec.view or other.view not in views or other.target.hidden or other.capture_error:
                continue
            unit = other.unit
            if unit.context and not deck_context.in_deck_ready(self.ctx, other.target.deck, other.view, other.language):
                continue
            key = f"{group}:{unit.label}:{other.revision.content_hash}"
            self.scheduler.submit(key, ((unit,), (other,)), P_IDLE, (-1,), group=group)

    def trace(self, event: str) -> None:
        """What background rendering decided and when (focus, input, starts, stops, the chip), for finding out on a
        user's machine why it rendered or waited: one debug line (area `background`) with what the gate knows at
        that moment. Until v0.13.7 this was background-trace.log in the cache folder, always written."""
        if not _trace_log.isEnabledFor(logging.DEBUG):
            return
        gate = self.gate
        with self._working_lock:
            running = len(self._working)
        since = gate._clock() - gate.last_input
        _trace_log.debug("%s | in_front=%s input %.0f s ago forced=%s running=%d planner=%r", event, gate.in_front,
                         since, gate.forced(), running, self.progress.paused_because)

    # -- what is outstanding ---------------------------------------------------------------

    def ordered_decks(self) -> list[Deck]:
        """The decks to prepare, most important first: the open deck, those a plugin says are needed soon, the
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
        found = [deck_language_code(self.ctx, deck)]
        if setting(self.ctx, SECOND_LANGUAGE_KEY, False):
            found += [code for code in languages.project_languages(self.ctx).codes if code not in found]
        return found

    def scan(self) -> list:
        """Everything outstanding, in the order it is rendered: [(sort key, unit)], and the progress counts.
        Units that are only out of step in their page number come after all the others, unless another unit has the
        same key: a slide called twice in one deck with one key keeps one render, with whichever page number it has
        (docs/plans/render-store-cleanup.md, D3); refreshing it would make the other call's render out of step, and so
        on for ever. A slide that failed and is not tried again by itself is tried once more, on its own, when nothing
        else is outstanding.

        It also notes the key of every unit of the decks it could read in full, and removes the renders those decks no
        longer use (_drop_stale; docs/plans/render-store-cleanup.md, step 2)."""
        started = time.time()               # the renders' own clock (meta "rendered_at"), not the injected one
        validation = render_evidence.ValidationPass()
        validation.inventory(self.ctx.root, validation.build_env(self.ctx), force=True)
        keys_now: set[str] = set()          # every unit's key, of the decks read in full
        clean_decks: set[str] = set()       # the decks read in full: every view and language, every unit's key
        rendered: dict[str, bool] = {}      # label -> each of its units has a render of its own current key
        scopes: set[tuple] = set()          # (deck, view, language) read
        decks_progress: list[DeckProgress] = []
        first: list = []
        numbering: list = []
        key_count: dict[str, int] = {}      # how many units of the scan have each key
        last: list = []                     # failed, not tried after the others yet: (rank, unit, progress, view)
        single: set[str] = set()
        counted: set[str] = set()
        failure_keys: set[str] = set()
        failure_slides: dict[str, set] = {}
        usage = {u["deck"]: u for u in self.store.deck_usage()}
        # A deck whose template file is in neither the project, the framework nor an installed theme fails every
        # render at its \input (a theme installed on another computer, a template file deleted): its units are held
        # back and the template is named, instead of piling up failures (v0.14.1).
        templates = set(slide_templates.available_templates(self.ctx.root))
        missing: dict[str, list[str]] = {}
        for deck_rank, deck in enumerate(self.ordered_decks()):
            progress = DeckProgress(deck.name)
            decks_progress.append(progress)
            start_at = usage.get(deck.name, {}).get("last_slide")
            deck_clean = True
            for language_rank, language in enumerate(self.languages_for(deck)):
                for view_rank, view in enumerate(self.versions_for(deck)):
                    ready = _Once(lambda deck=deck, view=view, language=language:
                                  deck_context.in_deck_ready(self.ctx, deck, view, language))
                    try:
                        units = deck_units(self.ctx, deck, view, language, start_at, ready)
                    except Exception:  # noqa: BLE001 -- a deck that cannot be read now is tried again next time
                        deck_clean = False          # and none of its renders is deleted
                        continue
                    scopes.add((deck.name, view, language))
                    for order, unit in enumerate(units):
                        if unit.context:
                            single.add(unit.label)      # typeset in its deck's compile, not in a batch with the others
                        progress.total += 1
                        progress.count(view, 0)
                        if unit.template not in templates:
                            deck_clean = self._note_key(unit, self.resolver.fast_key(unit, validation=validation), False, keys_now, rendered) and deck_clean
                            progress.blocked += 1
                            decks = missing.setdefault(unit.template, [])
                            if deck.name not in decks:
                                decks.append(deck.name)
                            continue
                        found = render_lookup.select(dict(resolver=self.resolver, unit=unit, validation=validation, state_only=True),
                                                     strict=False)
                        if found.state is render_key.Freshness.FAILED and _template_was_missing(found.failure, unit.template):
                            self.store.forget_failure(found.key)       # it failed only for want of the template
                            found = render_lookup.select(dict(resolver=self.resolver, unit=unit, validation=validation, state_only=True),
                                                         strict=False)
                        if found.key is not None:
                            key_count[found.key] = key_count.get(found.key, 0) + 1
                        own = found.usable and found.record is not None and found.record.get("key") == found.key
                        deck_clean = self._note_key(unit, found.key, own, keys_now, rendered) and deck_clean
                        if found.final and found.state is not render_key.Freshness.FAILED:
                            progress.fresh += 1
                            progress.count(view, 1)
                            counted.add(unit.label)
                        elif found.state is render_key.Freshness.FAILED:
                            failure_keys.add(found.key)
                            failure_slides.setdefault(found.key, set()).add((unit.deck, unit.id_slug))
                            if found.failure and self.store.may_retry(found.failure):
                                first.append(((deck_rank, language_rank, view_rank, order), unit))
                                single.add(unit.label)          # a batch holding it would fail again
                            elif not self.store.tried_last(found.key):
                                last.append(((deck_rank, language_rank, view_rank, order), unit, progress, view))
                            else:
                                progress.failed += 1
                                progress.count(view, 2)
                        elif found.usable:
                            progress.fresh += 1                  # right, apart from its page number: refreshed last
                            progress.count(view, 1)
                            counted.add(unit.label)
                            numbering.append(((deck_rank, language_rank, view_rank, order), unit, found.key))
                        else:
                            first.append(((deck_rank, language_rank, view_rank, order), unit))
            if deck_clean:
                clean_decks.add(deck.name)
        self._clear_stale(_CurrentKeys(frozenset(keys_now), frozenset(clean_decks), frozenset(rendered),
                                       frozenset(scopes), started),
                          rendered, all_clean=len(clean_decks) == len(decks_progress))
        off = self.decks_off()
        decks_progress += [DeckProgress(d.name, off=True) for d in self._decks()
                           if not d.archived and not d.is_test_deck and d.name in off]
        plan = first + [((1000 + k[0],) + k[1:], u) for k, u, key in numbering if key_count.get(key) == 1]
        last_try: set[str] = set()
        for rank, unit, progress, view in last:
            if plan:                        # the others first: until then it counts as failed
                progress.failed += 1
                progress.count(view, 2)
            else:                           # outstanding again, rendered on its own
                plan.append(((2000 + rank[0],) + rank[1:], unit))
                single.add(unit.label)
                last_try.add(unit.label)
        self._last_try = last_try
        self._single = single
        self._counted = counted
        with self._working_lock:
            self._failure_keys = failure_keys
            self._failure_slides = failure_slides
        failures = self.store_failures_count()
        with self._working_lock:
            # What runs now, from the workers' own list under their lock: copied from the old progress, a render that
            # ended during the scan stayed "working" until the next one started, and in front of the window none does:
            # the chip said "Preparing previews" with nothing running (v8.52.4).
            self.progress = Progress(decks_progress, self._working[0] if self._working else None, None,
                                     failures, self._clock(), missing)
        return plan

    @staticmethod
    def _note_key(unit: render_key.Unit, key: Optional[str], own: bool, keys_now: set, rendered: dict) -> bool:
        """Note the current `key` of `unit` for _clear_stale; `own`: a render of that key is stored. False when the key
        cannot be known now (the slide file is being written): then its deck counts as not read in full."""
        if key is None:
            return False
        keys_now.add(key)
        rendered[unit.label] = rendered.get(unit.label, True) and own
        return True

    def _clear_stale(self, current: "_CurrentKeys", rendered: dict, all_clean: bool) -> None:
        """After a scan: remember what it found current, for the renders stored until the next scan (_drop_stale),
        and delete the renders the decks read in full no longer use, of every label each of whose units has a render
        of its own current key (until then the old one is the Preview's "outdated" image). Once per store, when every
        deck was read in full, also every render no current key needs of a deck, view and language the scan read: of slides
        no longer in it, and of every label as above (renders left over from before v0.14.2). Nothing here may stop
        the scan."""
        self._current = current
        with self.store.lock:
            self.store.current_keys = current.keys
        keep, decks = set(current.keys), set(current.decks)
        try:
            done = {label for label, ok in rendered.items() if ok}
            self.store.drop_stale(done.__contains__, keep, decks, current.at)
            if all_clean and current.decks and not self.store.flag(render_store.LEFTOVERS_CLEARED):
                # A slide still in its deck keeps its old render as the "outdated" image until the new one is stored.
                removed = self.store.drop_stale(lambda label: _scope_of(label) in current.scopes and rendered.get(label, True),
                                                keep, decks, current.at)
                self.store.set_flag(render_store.LEFTOVERS_CLEARED)
                _trace_log.info("render store: %d renders no deck uses any more were deleted", removed)
        except Exception:  # noqa: BLE001 -- a store that cannot be written now is cleaned at a later scan
            _trace_log.debug("render store: stale renders not cleared", exc_info=True)

    def _drop_stale(self, unit: render_key.Unit, key: str) -> None:
        """A render of `unit` under `key` was stored: delete the renders of its label whose key its deck no longer uses,
        by what the last scan found (render_store.RenderStore.drop_stale). Nothing for a deck that scan could not read,
        nor for a unit it did not see (a language or view it does not sweep: their other current keys are unknown)."""
        current = self._current
        if current is None or unit.deck not in current.decks or unit.label not in current.labels:
            return
        try:
            self.store.drop_stale(lambda label: True, set(current.keys) | {key}, set(current.decks), current.at,
                                  label=unit.label)
        except Exception:  # noqa: BLE001 -- the render is stored; the next scan clears what is left
            _trace_log.debug("render store: stale renders of %s not cleared", unit.label, exc_info=True)

    def current_failures(self) -> list[dict]:
        """Failures still used by the current decks, rather than every failure ever stored."""
        with self._working_lock:
            keys = self._failure_keys.copy()
        return [failure for failure in self.store.failures() if failure['key'] in keys]

    def failed_slide_count(self) -> int:
        """How many slides have a current failure: a failure is one render unit (slide x view x language), so a
        slide failing in two views counts once."""
        with self._working_lock:
            slides = self._failure_slides.copy()
        return len({slide for failure in self.current_failures() for slide in slides.get(failure['key'], ())})

    def store_failures_count(self) -> int:
        return len(self.current_failures())

    # -- planner thread --------------------------------------------------------------------

    def _plan_loop(self) -> None:
        try:
            self.store.rescan(self._stop.is_set)
        except Exception:  # noqa: BLE001 -- a store closed under it, or one that cannot be read: the index stays as it is
            pass
        self.rescanning = False
        self._changed()
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
                self.scheduler.submit(key, (tuple(batch), ()), P_IDLE, rank, group=unit.deck)
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

    def ingest_compile(self, job, pdf: Path, record: dict) -> int:
        """Keep the slides of a whole-deck compile in the store: every page of each slide's run (every reveal step
        the PDF shows), for the view and language the deck was compiled in, so the Preview shows it as a finished
        render, with no note, for as long as what the slide depends on is unchanged -- the background sweep then has
        nothing left to do for it (render_key.Lookup.final). That also covers a slide that needs its deck (a contents
        or agenda slide, a section divider, docs/plans/render-store-cleanup.md D2: `deck_units` is asked for them
        too, this compile being their context) and one with \\SMFinalStateForStudents (D1): its run in a student
        view is one page already, the macro's own doing, so it is stored, and is finished, like any other.
        A `\\slidestep` or `\\slidefinal` call is left out: its run is only a selection of the slide's steps (a
        \\slidestep's own restriction, or \\slidefinal's single collapsed page), never every one, so it stays with
        the sweep. The dependencies are the compile record's (compile_records.py): every file the compile read, with
        its SHA-256, except the other slides, and media or snippets this slide does not mention. Returns how many
        slides were stored. Run off the GUI thread."""
        if "inventory" not in record or "started" not in record or "configuration" not in record:
            return 0
        if job.chapter is not None or getattr(job, "pages", None) or job.presenter:
            return 0
        if compile_records.sha256(pdf) != record.get("pdf_sha256"):
            return 0                                    # not the PDF the record describes
        validation = render_evidence.ValidationPass()
        configuration = validation.configuration(self.ctx.root, validation.build_env(self.ctx))
        if render_evidence.digest(configuration) != record["configuration"]:
            return 0
        view = job.version or VIEW_INSTRUCTOR
        language = (getattr(job, "language", None) or deck_language_code(self.ctx, job.deck)).upper()
        recorded = {norm(entry["path"]): entry
                    for entry in record.get("inputs", []) if not entry.get("copy")}
        inputs = [Path(entry["path"]) for entry in recorded.values()]
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
        units = deck_units(self.ctx, job.deck, view, language, context_ready=lambda: True)
        counts = Counter(slide_language.bare_id(unit.id_slug) for unit in units)
        for unit in units:
            slide_id = slide_language.bare_id(unit.id_slug)
            if counts[slide_id] != 1:
                continue                                # footers cannot distinguish repeated calls or versions
            pages = runs.get(slide_id)
            known = recorded.get(norm(unit.source_path))
            if unit.macro in ("slidestep", "slidefinal") or not pages or known is None:
                continue
            text = unit.source_path.read_text(encoding="utf-8", errors="replace")
            if known.get("text_sha256") != text_sha256(text):
                continue                                # a frozen file or metadata-only read cannot vouch for this text
            key = self.resolver.fast_key(unit, text, validation=validation)
            found = self.resolver.lookup(unit, key, validation=validation)
            if found.final:
                continue                                # nothing more for the sweep, or this compile, to do for it
            paths = render_key.unit_inputs(self.ctx, inputs, unit.source_path, {unit.source_path: text})
            try:
                if any(compile_records.sha256(path) != recorded[norm(path)]["sha256"] for path in paths):
                    continue
            except OSError:
                continue
            manifest = self.resolver.build_manifest([str(path) for path in paths])
            response = raster.read_document(pdf, "pdf_images", pages[0] + 1, len(pages), width=STORE_WIDTH)
            if len(response["images"]) != len(pages):
                continue
            evidence = dict(started=record["started"], inventory=record["inventory"], key=key)
            with tempfile.TemporaryDirectory(prefix="slidemage_compile_") as folder:
                own = Path(folder) / "slide.pdf"
                raster.read_document(pdf, "extract_pages", pages[0] + 1, len(pages), out=own)
                if self._store_render(unit, ORIGIN_COMPILE, own, response["images"], manifest, evidence) is not None:
                    stored += 1
        return stored

    def deck_archived(self, deck: Deck) -> None:
        self.scheduler.cancel_group(deck.name)
        self.store.drop_deck(deck.name)
        self.replan()

    # -- the work ----------------------------------------------------------------------------

    def _work(self, job: Job, cancel) -> None:
        units, requests = job.payload
        self._set_working(job.key, True)
        self.trace(f"start {job.key}")
        try:
            cancel.low_priority = True
            requests = requests or tuple(self.request_for(unit) for unit in units)
            results = batch_render.render_batch(self.renders, requests, cancel=cancel, batch_size=self.batch_size())
            for unit, result in zip(units, results):
                if result.status in ('rendered', 'cached'):
                    found = self.resolver.lookup(unit)
                    if found.state is render_key.Freshness.FRESH:
                        self.store.link_decks(found.record['name'], [unit.deck])
                        self._count_fresh(unit)
                elif result.status == 'failed':
                    self._failed(unit, RuntimeError(result.error))
            if cancel.is_set():
                raise Cancelled('Preview cancelled')
        finally:
            self._set_working(job.key, False)
            self.trace(f"end {job.key}{' (stopped)' if cancel.is_set() else ''}")

    def _count_fresh(self, unit: render_key.Unit) -> None:
        # Each slide counts once per plan. Counted twice were a slide the plan found right apart from its page number,
        # when that was refreshed (582 -> 598 left, v8.52.4), and a slide a job found current: a batch the plan still
        # held when the same batch, on its way already, had finished; a batch stopped part-way and run again; a reveal
        # render of a current slide. A view then showed more renders than it has (268 / 252, v8.66.0).
        with self._working_lock:
            if unit.label in self._counted:
                return
            self._counted.add(unit.label)
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
            units = job.payload[0]
            unit = units[0]
            entries.append(dict(deck=unit.deck, slide=unit.id_slug if len(units) == 1 else f"{len(units)} slides",
                                view=unit.view, language=unit.language,
                                kind="background",
                                seconds=max(0.0, now - job.started)))
        return entries

    def capacity(self) -> tuple[int, Optional[float]]:
        """(how many may render at once, the processor's load now: None when unknown)."""
        return self.scheduler.workers, self._cpu.load()

    def request_for(self, unit: render_key.Unit) -> preview_requests.PreviewRequest:
        """Capture a saved sweep unit, retaining its deck and unrestricted reveal steps."""
        try:
            revision = preview_requests.SourceRevision.capture(unit.source_path)
            error = None
        except OSError:
            revision = preview_requests.SourceRevision.capture(unit.source_path, '')
            error = 'the slide file is being written'
        deck = next((deck for deck in self._decks() if deck.name == unit.deck), None)
        target = preview_target.PreviewTarget(
            self.ctx, unit.macro, unit.id_slug, unit.version, unit.conditions, None,
            unit.frame_number, unit.preamble_text, deck=deck, needs_context=(unit.context,) if unit.context else ())
        return preview_requests.PreviewRequest(target, revision, unit.view, unit.language,
                                              preview_requests.RenderOptions(saved=True, all_steps=True), error)

    def _store_render(self, unit: render_key.Unit, origin: str, pdf: Path,
                      pages: list[bytes], manifest: render_key.Manifest, evidence: dict) -> Optional[str]:
        if not pages or not self.resolver.publishable(unit, evidence, manifest):
            return None
        key = evidence["key"]
        paths = [unit.source_path, *[rel for _kind, rel, _sha in manifest.entries]]
        meta = dict(unit=unit.label, rendered_at=time.time(), duration_ms=int((time.time() - evidence["started"]) * 1000),
                    manifest=manifest.entries, tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                    inventory=render_evidence.inventory_state(evidence["inventory"], paths),
                    machine=render_key.machine_id(), engine_fp=self.resolver.engine_fp, frame_number=unit.frame_number,
                    width=STORE_WIDTH, template=unit.template)
        if self.store.failure(key) is not None:
            self.store.forget_failure(key)      # rendered after all: no longer among the slides that cannot be
        with self._working_lock:
            self._failure_keys.discard(key)
            self._failure_slides.pop(key, None)
        self.progress.failures = self.store_failures_count()
        name = self.store.put(key, origin, pdf, pages, meta, decks=[unit.deck] if unit.deck else [])
        self._drop_stale(unit, key)
        return name

    def _render_in_deck(self, unit: render_key.Unit, cancel) -> Path:
        """A slide that needs its deck, typeset in the deck's last whole-deck compile (deck_context.render_in_deck)."""
        deck = next((d for d in self._decks() if d.name == unit.context), None)
        pdf = None if deck is None else deck_context.render_in_deck(
            self.ctx, deck, unit.view, slide_language.bare_id(unit.id_slug), unit.id_slug, lambda line: None, cancel,
            all_steps=True, language=unit.language)
        if pdf is None:
            raise _transient("the deck has no compile to typeset the slide in")
        return pdf

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

    def _failed(self, unit: render_key.Unit, exc: BaseException) -> None:
        self.progress.failures = self.store_failures_count()
        counted = self.progress.deck(unit.deck)
        if counted is not None and (getattr(exc, "kind", None) == render_store.DETERMINISTIC or str(exc).startswith("Render failed")):
            counted.failed += 1
            counted.count(unit.view, 2)

    def _changed(self) -> None:
        try:
            self._on_change()
        except Exception:  # noqa: BLE001 -- a broken indicator must not stop the work
            pass


@dataclass(frozen=True)
class _CurrentKeys:
    """What one scan found: the keys of every unit of the decks it read in full, those decks, the labels of those
    units, the (deck, view, language) it read, and when it began."""
    keys: frozenset
    decks: frozenset
    labels: frozenset
    scopes: frozenset
    at: float


def _scope_of(label: str) -> tuple:
    """(deck, view, language) of a unit's label (render_key.Unit.label: "deck:id-slug:view:language")."""
    head, view, language = (label.rsplit(":", 2) + ["", ""])[:3]
    return head.rsplit(":", 1)[0], view, language


class _Once:
    """A yes/no question asked at most once, when it is first needed."""

    def __init__(self, ask: Callable[[], bool]) -> None:
        self._ask, self._answer = ask, None

    def __call__(self) -> bool:
        if self._answer is None:
            try:
                self._answer = bool(self._ask())
            except Exception:  # noqa: BLE001 -- unknown counts as not ready; the next plan asks again
                self._answer = False
        return self._answer


def _transient(message: str) -> RuntimeError:
    error = RuntimeError(message)
    error.kind = render_store.TRANSIENT          # type: ignore[attr-defined]
    return error
