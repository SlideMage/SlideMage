"""Idle-time rendering of every slide of every deck, with all reveal steps (docs/plans/idle-background-rendering.md).

`BackgroundRenderer` joins the pieces: the store and the render key (what is current), the scheduler (what
runs when), the idle gate (when the machine is free), and a planner that lists what is outstanding in the
owner's order -- decks by recency (the open deck first), within a deck the instructor version, then the
other versions, within a version the slides from the last one looked at -- and feeds the scheduler a few
at a time. A render is one unrestricted latexmk run of the slide in the deck's preamble (every overlay step
is a page), rasterised by a raster process of its own and stored with the files it read.

Free of Qt: the window supplies the gate's input events and the status chip reads `progress`.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import app_settings, course_schedule, deck_language, deck_settings, render_key, render_store, slide_language
from . import power_status, preview_build, preview_target, slide_preview
from .deck_editor import VIEWS, VIEW_INSTRUCTOR
from .deck_scan import Deck
from .dep_hash import HashCache
from .idle_gate import IdleGate
from .preview_raster_client import RasterClient
from .project import ProjectContext
from .render_scheduler import P_IDLE, P_NEIGHBOURS, Job, RenderScheduler
from .render_store import ORIGIN_BACKGROUND, ORIGIN_REVEAL, RenderStore

STORE_WIDTH = 1280
RASTER_CHUNK = 4                # pages per raster request, so another reader of a raster child never waits long
QUEUE_AHEAD = 12                # idle jobs handed to the scheduler at a time
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
DEFAULT_LIMIT_GB = 2.0
PROFILES = {"gentle": (1, 0.5), "normal": (1, 0.25), "fast": (2, 0.0)}      # (processes, rest / job time)
DEFAULT_PROFILE = "normal"


def setting(ctx: ProjectContext, key: str, default):
    try:
        return app_settings.get(ctx, key, default)
    except OSError:
        return default


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


class Cancelled(RuntimeError):
    pass


class BackgroundRenderer:
    def __init__(self, ctx: ProjectContext, store: RenderStore, *, gate: Optional[IdleGate] = None,
                 decks: Callable[[], list] = lambda: [], open_deck: Callable[[], Optional[Deck]] = lambda: None,
                 engine_fp: Optional[Callable[[], str]] = None, renderer: Optional[Callable] = None,
                 raster: Optional[RasterClient] = None, on_change: Callable[[], None] = lambda: None,
                 soon: Optional[Callable[[Deck], bool]] = None, clock: Callable[[], float] = time.time) -> None:
        self.ctx, self.store = ctx, store
        self.hashes = HashCache(store.db, store.lock)
        self.resolver = render_key.Resolver(ctx, self.hashes, store, engine_fp=engine_fp)
        self.gate = gate or IdleGate(
            enabled=lambda: self.enabled, only_on_mains=lambda: bool(setting(ctx, ONLY_MAINS_KEY, True)),
            free_bytes=lambda: power_status.free_bytes(store.root))
        self._decks, self._open_deck = decks, open_deck
        self._soon = soon or (lambda deck: course_schedule.session_soon(deck.course_url))
        self._render = renderer or self._render_pdf
        self._raster = raster
        self._on_change = on_change
        self._clock = clock
        profile = setting(ctx, PROFILE_KEY, DEFAULT_PROFILE)
        workers, duty = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
        self.scheduler = RenderScheduler(self._work, can_start=lambda job: self.gate.allowed(),
                                         on_change=self._changed, on_error=self._failed, workers=workers, duty=duty)
        self.progress = Progress()
        self._plan: list = []
        self._plan_lock = threading.RLock()
        self._planned_at = 0.0
        self._replan = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._outstanding: dict[str, tuple] = {}

    # -- settings ------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(setting(self.ctx, ENABLED_KEY, True))

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
        self.replan()

    def replan(self) -> None:
        """Something that decides what is outstanding changed (a deck opened, a setting): look again soon."""
        self._replan.set()

    def user_active(self) -> None:
        self.gate.note_input()
        self.scheduler.user_active()

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
        self.progress = Progress(decks_progress, self.progress.working, None,
                                 self.store_failures_count(), self._clock())
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
        self.progress.paused_because = reason if (self._plan or self.scheduler.pending()) else None
        if reason is None:
            self._top_up()
        self._changed()

    def _top_up(self) -> None:
        with self._plan_lock:
            while self._plan and self.scheduler.pending(P_IDLE) < QUEUE_AHEAD:
                rank, unit = self._plan.pop(0)
                self.scheduler.submit(unit.label, (unit, ORIGIN_BACKGROUND), P_IDLE, rank, group=unit.deck)

    def _evict(self) -> None:
        recent = {u["deck"] for u in self.store.deck_usage()[:5]}
        names = {d.name for d in self._decks() if not d.archived}
        self.store.enforce_limit(self.limit_bytes(), protected_decks=recent,
                                 keep_days=int(setting(self.ctx, KEEP_DAYS_KEY, render_store.DEFAULT_KEEP_DAYS)),
                                 is_orphan=lambda decks: bool(decks) and not set(decks) & names)

    # -- foreground helpers ------------------------------------------------------------------

    def submit_neighbours(self, unit: render_key.Unit, rank: tuple = ()) -> None:
        """The reveal slider's render of a unit (class P_NEIGHBOURS): it runs before any idle job and never waits for one."""
        self.scheduler.submit(unit.label, (unit, ORIGIN_REVEAL), P_NEIGHBOURS, rank, group="reveal")

    def deck_archived(self, deck: Deck) -> None:
        self.scheduler.cancel_group(deck.name)
        self.store.drop_deck(deck.name)
        self.replan()

    # -- the work ----------------------------------------------------------------------------

    def _work(self, job: Job, cancel) -> None:
        unit, origin = job.payload
        self.progress.working = unit.label
        try:
            if self.render_unit(unit, origin, cancel) is not None:
                counted = self.progress.deck(unit.deck)
                if counted is not None and counted.fresh < counted.total:
                    counted.fresh += 1
                    counted.count(unit.view, 1)
        finally:
            self.progress.working = None

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
            inputs = json.loads(pdf.with_suffix(".inputs.json").read_text(encoding="utf-8")) if pdf.with_suffix(".inputs.json").is_file() else []
            manifest = self.resolver.build_manifest(inputs)
            pages = self._rasterise(pdf, cancel)
            if not pages:
                raise _deterministic("the render has no pages (the slide is not typeset in this view)")
            meta = dict(unit=unit.label, rendered_at=time.time(), duration_ms=int((time.time() - started) * 1000),
                        manifest=manifest.entries, tex_digest=manifest.tex_digest, tex_files=manifest.tex_files,
                        machine=render_key.machine_id(), engine_fp=self.resolver.engine_fp, frame_number=unit.frame_number,
                        unstable=not manifest.stable, width=STORE_WIDTH)
            replace = (found.record is not None and found.state is render_key.Freshness.FRESH_NUMBERING_DIFFERS
                       and found.record.get("origin") == origin)
            return self.store.put(key, origin, pdf, pages, meta, decks=[unit.deck], replace=replace)
        except BaseException as exc:
            if cancel.is_set():
                raise
            self._record_failure(key, exc, started, unit)
            raise
        finally:
            if pdf is not None and pdf.parent.name.startswith(preview_build.RENDER_FOLDER_PREFIX):
                shutil.rmtree(pdf.parent, ignore_errors=True)

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
        counted = self.progress.deck(job.payload[0].deck)
        if counted is not None and getattr(exc, "kind", None) == render_store.DETERMINISTIC or str(exc).startswith("Render failed"):
            if counted is not None:
                counted.failed += 1
                counted.count(job.payload[0].view, 2)

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
