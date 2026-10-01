"""Single per-image store for everything the accessibility system knows
about an image: `media/alt-text.json`. Replaces two former stores --
alt_manifest.py's `media/alt-text.csv` (role/status/short_alt only) and the
per-slide `%%ALT` comment block alt_blocks.py used to read/write at the
bottom of every slide file (long/takeaway/review state) -- with one.

The original split existed because a CSV cell can't hold a 400-word
description with an embedded Markdown table. JSON has no such limit, and an
image used on more than one slide was always describing the same picture
twice over -- migrated 2026-08-14, checked directly first: of the images
used on more than one slide, only two had any drafted text at all, and in
both cases only one of the two slides had it. There was nothing to actually
merge.

Two things stay genuinely per-slide, because they are contextual in a way
the image itself is not:

- **takeaway** -- why *this* image is on *this* slide. `takeaway_default`
  lives on the image; a slide's own `SlideUse.takeaway` is empty unless it
  was deliberately overridden, in which case it lives independently from
  then on (Save promotes the very first takeaway entered for an image to
  become its default automatically; after that, "Set as default" is an
  explicit action).
- **reviewed** -- confirming an image's role/short/long happens once
  (`ImageEntry.status`), but confirming that a given slide's *use* of it
  (its context, its takeaway) is right is a separate, per-slide check
  (`SlideUse.reviewed`). A slide is only fully done when both are true.

On-disk shape (sorted by image path, and by slide_id within `used_on`, so
diffs stay readable):

    {
      "media/chart-index-scale-illusion-linear.png": {
        "role": "informative",
        "status": "reviewed",
        "short": "Line chart of the S&P 500 index level, 1975-2025.",
        "long": "A line chart titled \\"S&P 500\\"...",
        "source": "Source: Own illustration of Yahoo Finance data.",
        "takeaway_default": "On a linear vertical axis...",
        "drafted_by": "qwen3-vl:32b",
        "used_on": {
          "3px": {"takeaway": "", "reviewed": "2026-08-20", "hash": "3f9c21ea77b0"}
        }
      }
    }

`used_on`'s *keys* (which slides reference this image) are a derived cache,
rebuilt additively on every `sync_store()` scan -- like the old CSV's
`sync_manifest()`, a slide reference disappearing is reported for a human to
confirm, never silently deleted. Each key's *values* (takeaway override,
reviewed date, hash) are real authored data, preserved across scans.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import alt_blocks
from .deck_scan import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / "media" / "alt-text.json"
FORMAT_VERSION = 2

ROLE_DECORATIVE = "decorative"
ROLE_INFORMATIVE = "informative"

STATUS_AUTO = "auto"
STATUS_REVIEWED = "reviewed"

# Same scan targets/guesses as the old alt_manifest.py. The three scheme_*
# dirs moved under schemes/ 2026-09-18 (were project-root siblings of
# media/ before that).
IMAGE_DIRS = ("media", "schemes/scheme_uni_graz", "schemes/scheme_uni_ibk", "schemes/scheme_mci")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".eps")
_DECORATIVE_PREFIXES = ("midjourney-", "icon-", "chapter-logo-", "logo-", "logo_")
_DECORATIVE_DIRS = ("schemes/scheme_uni_graz", "schemes/scheme_uni_ibk", "schemes/scheme_mci")

# Review states for one slide's *use* of one image, worst first -- same
# four-state shape the old per-slide %%ALT block state machine used, now
# computed per (image, slide) pair instead of once per slide file.
STATE_NONE = "none"          # image has no content at all yet
STATE_DRAFT = "draft"        # image has content, this slide's use unreviewed
STATE_STALE = "stale"        # was reviewed, but the image or this slide changed since
STATE_REVIEWED = "reviewed"  # reviewed and still current

STATE_LABELS = {
    STATE_NONE: "No description",
    STATE_DRAFT: "Draft, unreviewed",
    STATE_STALE: "Needs re-check",
    STATE_REVIEWED: "Reviewed",
}

# Same reasoning as alt_blocks._image_hash: hashing every referenced image
# on every rescan is expensive, so cache by (path, size, mtime).
_image_hash_cache: dict[tuple[str, int, int], str] = {}


@dataclass
class SlideUse:
    """One slide's use of one image -- the per-slide half of the record."""

    takeaway: str = ""   # "" = follows the image's takeaway_default
    reviewed: str = ""   # ISO date; "" = never reviewed
    stored_hash: str = ""  # slide-context hash as of `reviewed`
    # German counterpart to `takeaway` (2026-08-24) -- "" follows
    # takeaway_default_de the same way `takeaway` follows takeaway_default.
    # One `reviewed` stamp covers both languages: reviewing a slide's
    # takeaway means looking at both language versions in one sitting, so
    # there is deliberately no separate reviewed_de/stored_hash_de.
    takeaway_de: str = ""

    @property
    def has_override(self) -> bool:
        return bool(self.takeaway)

    @property
    def has_override_de(self) -> bool:
        return bool(self.takeaway_de)


@dataclass
class ImageEntry:
    """Everything known about one image, shared across every slide using it."""

    image: str  # forward-slash path relative to the project root
    role: str = ROLE_INFORMATIVE
    status: str = STATUS_AUTO
    short: str = ""
    long: str = ""
    takeaway_default: str = ""
    # Free-text citation ("Source: ...", "Image source: ...") -- who this
    # image is from, not what it shows (that's short/long). Independent of
    # role: a decorative Midjourney illustration still needs attribution
    # even though it carries no alt text, confirmed directly against a real
    # slide (dh6-Private-Equity-Categorization) that already hand-authors
    # exactly that combination. Auto-pulled into a compiled slide's own
    # footnote wherever this image is used -- see ALT_TEXT_NOTES.md.
    source: str = ""
    # Which vision model produced the current short/long, when one did.
    # Cleared on human review -- once checked, the text is yours.
    drafted_by: str = ""
    # A stored per-image correction from prompt-tuning ("the y-axis maximum
    # is 6800, not 250"), reused by a later redraft instead of the user
    # rediscovering it. Same purpose alt_blocks.AltImage.hint served.
    hint: str = ""
    used_on: dict[str, SlideUse] = field(default_factory=dict)

    # German counterparts (2026-08-24), produced by translating the
    # already-finalized English text (alt_draft.translate_to_german())
    # rather than an independent vision-model draft, per direct
    # instruction -- see LANGUAGE_NOTES.md. `source_de` is a genuine
    # default+override, the same shape takeaway_default/SlideUse.takeaway
    # already use: "" means "same citation in both languages" (most
    # citations are proper nouns/publication names that don't translate),
    # a non-empty value is an explicit German-specific override.
    short_de: str = ""
    long_de: str = ""
    source_de: str = ""
    takeaway_default_de: str = ""
    status_de: str = STATUS_AUTO
    # sha256 (12 hex chars, same truncation as every other hash in this
    # module) of the EN short+long+takeaway_default text as of the last
    # translation -- see en_text_hash()/translation_state() below. A
    # later edit to the English text changes this hash, so a stale German
    # copy is visibly flagged instead of silently drifting out of sync.
    translated_from_hash: str = ""

    @property
    def is_decorative(self) -> bool:
        return self.role == ROLE_DECORATIVE

    @property
    def is_tikz(self) -> bool:
        """Whether this entry describes a hand-drawn tikz illustration
        (image == "tikz:ID", alt_blocks.TIKZ_PREFIX) rather than a real
        media/ file. No separate `kind` field: the prefix is already a
        stable, self-describing key, and every existing on-disk row (all of
        which are real paths) reads as False here for free, with no
        migration or FORMAT_VERSION bump needed."""
        return self.image.startswith(alt_blocks.TIKZ_PREFIX)

    @property
    def has_content(self) -> bool:
        """Whether someone has said anything deliberate about this image.

        Marking it decorative counts, same as the old AltImage.has_content:
        a real decision, not an absence of one.
        """
        return bool(self.short or self.long or self.is_decorative)

    @property
    def has_content_de(self) -> bool:
        """German counterpart to has_content -- decorative still counts
        (role has no language of its own), an untranslated informative
        image does not."""
        return bool(self.short_de or self.long_de or self.is_decorative)

    def takeaway_for(self, slide_id: str) -> str:
        """The effective takeaway text a slide shows: its own override, or
        this image's current default."""
        use = self.used_on.get(slide_id)
        if use and use.has_override:
            return use.takeaway
        return self.takeaway_default

    def takeaway_for_de(self, slide_id: str) -> str:
        use = self.used_on.get(slide_id)
        if use and use.has_override_de:
            return use.takeaway_de
        return self.takeaway_default_de

    def source_for_de(self) -> str:
        """source_de if set, else the English source -- the default+
        override fallback described on source_de above."""
        return self.source_de or self.source

    def is_override_for(self, slide_id: str) -> bool:
        use = self.used_on.get(slide_id)
        return bool(use and use.has_override)


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------

def _entry_to_dict(entry: ImageEntry) -> dict:
    d = {
        "role": entry.role,
        "status": entry.status,
        "short": entry.short,
        "long": entry.long,
        "source": entry.source,
        "takeaway_default": entry.takeaway_default,
    }
    if entry.drafted_by:
        d["drafted_by"] = entry.drafted_by
    if entry.hint:
        d["hint"] = entry.hint
    # German fields (2026-08-24) written only when there's something to
    # write -- same optional-key pattern as drafted_by/hint above, so an
    # untranslated entry (the vast majority, at first) doesn't bloat every
    # row in the store with five empty keys.
    if entry.short_de:
        d["short_de"] = entry.short_de
    if entry.long_de:
        d["long_de"] = entry.long_de
    if entry.source_de:
        d["source_de"] = entry.source_de
    if entry.takeaway_default_de:
        d["takeaway_default_de"] = entry.takeaway_default_de
    if entry.status_de != STATUS_AUTO:
        d["status_de"] = entry.status_de
    if entry.translated_from_hash:
        d["translated_from_hash"] = entry.translated_from_hash
    d["used_on"] = {
        slide_id: {
            k: v for k, v in (
                ("takeaway", use.takeaway),
                ("reviewed", use.reviewed),
                ("hash", use.stored_hash),
                ("takeaway_de", use.takeaway_de),
            ) if v
        }
        for slide_id, use in sorted(entry.used_on.items())
    }
    return d


def _entry_from_dict(image: str, d: dict) -> ImageEntry:
    used_on = {
        slide_id: SlideUse(
            takeaway=(u.get("takeaway") or ""),
            reviewed=(u.get("reviewed") or ""),
            stored_hash=(u.get("hash") or ""),
            takeaway_de=(u.get("takeaway_de") or ""),
        )
        for slide_id, u in (d.get("used_on") or {}).items()
    }
    return ImageEntry(
        image=image,
        role=(d.get("role") or ROLE_INFORMATIVE),
        status=(d.get("status") or STATUS_AUTO),
        short=(d.get("short") or ""),
        long=(d.get("long") or ""),
        source=(d.get("source") or ""),
        takeaway_default=(d.get("takeaway_default") or ""),
        drafted_by=(d.get("drafted_by") or ""),
        hint=(d.get("hint") or ""),
        short_de=(d.get("short_de") or ""),
        long_de=(d.get("long_de") or ""),
        source_de=(d.get("source_de") or ""),
        takeaway_default_de=(d.get("takeaway_default_de") or ""),
        status_de=(d.get("status_de") or STATUS_AUTO),
        translated_from_hash=(d.get("translated_from_hash") or ""),
        used_on=used_on,
    )


def load_store() -> dict[str, ImageEntry]:
    """Read the store, keyed by root-relative image path. {} if absent."""
    if not STORE_PATH.is_file():
        return {}
    raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    images = raw.get("images", raw)  # tolerate a bare {image: {...}} shape too
    return {image: _entry_from_dict(image, d) for image, d in images.items()}


@dataclass
class SlideNotes:
    """Free-text notes about a slide's *transcript entry* as a whole --
    not about any one image. Currently just a summary blurb, shown at the
    top of that slide's section (before its body text) so a reader gets
    oriented before the bullet points. Keyed by the same bare slide id
    used everywhere else (alt_blocks.scan_slides_raw()'s SlideRow.slide_id,
    slide_snapshot.bare_id()) -- unlike ImageEntry, this has nothing to do
    with any particular image, so it lives in its own top-level "slides"
    section of the same JSON file rather than inside `used_on`.
    """

    summary: str = ""


def _read_raw() -> dict:
    if not STORE_PATH.is_file():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_slide_notes() -> dict[str, SlideNotes]:
    raw = _read_raw()
    slides = raw.get("slides", {})
    return {
        slide_id: SlideNotes(summary=(d.get("summary") or ""))
        for slide_id, d in slides.items()
    }


# Every image used to have its own slide file to write to, so two writers
# could only ever collide on the one slide a background batch happened to
# be touching at the exact moment of a manual save -- closed by comparing a
# whole-file digest. Now every write (a batch draft, a review-tab save)
# goes through this one shared JSON file instead, which reopens the same
# class of lost-update race across *any* two images, not just a shared one.
# A single process-wide lock around the whole load-mutate-save round trip
# closes it outright: the batch thread and the GUI thread are the only two
# writers that ever exist, both in this one process, never across
# processes -- a Lock is sufficient, no file locking needed.
_store_lock = threading.Lock()


def update_store(mutate) -> bool:
    """Atomically load, let `mutate(entries) -> bool` change it in place,
    and save only if it returned True. Single-entry edits use this path;
    sync_store() takes the same lock around its full scan and bulk update."""
    with _store_lock:
        entries = load_store()
        changed = mutate(entries)
        if changed:
            save_store(entries)
        return changed


def delete_entry(image: str) -> bool:
    """Drops `image`'s whole entry (role/short/long/takeaway_default/
    used_on -- everything) from the store, atomically. For the Images tab's
    "Replace image…" flow (2026-09-18): once every slide that used to
    reference `image` has been repointed at a new file, its old description
    describes a picture nothing shows any more -- this is what "yes, delete
    it" in that flow's confirmation actually does. Returns False (no-op) if
    `image` wasn't in the store to begin with."""
    def mutate(entries: dict[str, ImageEntry]) -> bool:
        return entries.pop(image, None) is not None
    return update_store(mutate)


def update_slide_notes(mutate) -> bool:
    """Same atomic load-mutate-save contract as update_store(), for the
    "slides" section instead of "images" -- same shared file, same lock,
    so a slide-notes save and an image save can never interleave and lose
    each other's change."""
    with _store_lock:
        notes = load_slide_notes()
        changed = mutate(notes)
        if changed:
            _save_slide_notes(notes)
        return changed


def _atomic_write_text(path: Path, text: str) -> None:
    """Write complete UTF-8 content beside its target, then replace it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _save_slide_notes(notes: dict[str, SlideNotes]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = _read_raw()
    raw["version"] = FORMAT_VERSION
    # Empty summaries aren't worth a row -- keeps the file from
    # accumulating dead entries for a slide someone typed into and then
    # cleared.
    raw["slides"] = {
        slide_id: {"summary": n.summary}
        for slide_id, n in sorted(notes.items()) if n.summary
    }
    # No _write_compile_csv() call here, unlike save_store() -- the
    # compile-time CSV mirror only ever holds image role/short_alt columns
    # (Slidemaster_alt.lua doesn't know slide summaries exist), so a
    # slides-only change has nothing in it worth regenerating.
    _atomic_write_text(
        STORE_PATH,
        json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
    )


def save_store(entries: dict[str, ImageEntry]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # save_store() only ever receives the "images" half (that's the shape
    # every existing caller works with) -- reading the file's current
    # "slides" section first and carrying it forward unchanged is what
    # stops an image save from silently wiping out slide summaries saved
    # through update_slide_notes(), and vice versa.
    existing_slides = _read_raw().get("slides", {})
    payload = {
        "version": FORMAT_VERSION,
        "images": {
            image: _entry_to_dict(entries[image]) for image in sorted(entries)
        },
        "slides": existing_slides,
    }
    _atomic_write_text(
        STORE_PATH,
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
    )
    _write_compile_csv(entries)


# `media/alt-text.csv` used to be the store itself (alt_manifest.py); it is
# now a generated compile-time projection of it, in the same "derived,
# gitignored, regenerated on demand" category as transcripts/. Kept because
# Slidemaster_alt.lua reads it directly at compile time with a hand-rolled
# CSV parser, and LuaTeX has no JSON library to switch it to one -- rewriting
# the compile-time side was a much larger change than just keeping the one
# file format it already reads working. Same header/column shape the old
# store wrote, so nothing on the Lua side needed to change at all.
_COMPILE_CSV_PATH = PROJECT_ROOT / "media" / "alt-text.csv"


def _write_compile_csv(entries: dict[str, ImageEntry]) -> None:
    import csv as _csv

    def _clean(text: str) -> str:
        # Slidemaster_alt.lua reads one CSV row per handle:lines() call; an
        # embedded newline would split one logical row across two lines
        # its parser never rejoins. `short`/`short_de` are meant to be one
        # sentence anyway (see alt_draft.py's SYSTEM_PROMPT) -- this is
        # just the defensive backstop. `source`/`source_de` are free text
        # a human typed into the Images tab and could in principle contain
        # a pasted newline, so they get the same guard.
        return text.replace("\n", " ").replace("\r", " ")

    with _COMPILE_CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle)
        # Widened 2026-08-24 (was image,role,status,short_alt,source) to
        # carry both languages in one file rather than a second CSV/second
        # Lua load() call -- Slidemaster_alt.lua picks the *_en/*_de pair
        # to actually use per-image based on the compiling deck's own
        # \SMDeckLanguage. `role` stays a single shared column: it's
        # language-independent (decorative/informative is a property of
        # the picture, not of which language is being read).
        writer.writerow([
            "image", "role",
            "status_en", "short_alt_en", "source_en",
            "status_de", "short_alt_de", "source_de",
        ])
        for image in sorted(entries):
            entry = entries[image]
            writer.writerow([
                entry.image, entry.role,
                entry.status, _clean(entry.short), _clean(entry.source),
                entry.status_de, _clean(entry.short_de), _clean(entry.source_for_de()),
            ])


# --------------------------------------------------------------------------
# Scanning / sync
# --------------------------------------------------------------------------

def _guess_role(image: str) -> str:
    directory, _, name = image.rpartition("/")
    if directory in _DECORATIVE_DIRS:
        return ROLE_DECORATIVE
    lowered = name.lower()
    if any(lowered.startswith(p) for p in _DECORATIVE_PREFIXES):
        return ROLE_DECORATIVE
    return ROLE_INFORMATIVE


def scan_images() -> list[str]:
    """Every includable image in the project, as root-relative posix paths."""
    found: list[str] = []
    for dirname in IMAGE_DIRS:
        directory = PROJECT_ROOT / dirname
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                found.append(path.relative_to(PROJECT_ROOT).as_posix())
    return found


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)          # new image rows
    missing: list[str] = field(default_factory=list)        # in store, not on disk
    new_uses: list[tuple[str, str]] = field(default_factory=list)  # (image, slide_id)
    stale_uses: list[tuple[str, str]] = field(default_factory=list)  # (image, slide_id) no longer referenced

    @property
    def changed(self) -> bool:
        return bool(self.added or self.new_uses)


def sync_store() -> SyncReport:
    """Add-only sync, serialized with every other store writer.

    Holding the shared lock across scanning prevents an older snapshot from
    replacing image drafts or slide notes saved while the scan runs.
    """
    with _store_lock:
        return _sync_store_locked()


def _sync_store_locked() -> SyncReport:
    entries = load_store()
    report = SyncReport()

    on_disk = scan_images()
    for image in on_disk:
        if image not in entries:
            entries[image] = ImageEntry(image=image, role=_guess_role(image))
            report.added.append(image)

    rows = alt_blocks.scan_slides_raw()

    # Tikz illustrations have no file for scan_images() to find -- their own
    # \begin{tikzillustration}{ID} call, already surfaced in row.images by
    # alt_blocks.referenced_images() as a synthetic "tikz:ID" reference, is
    # the only place they exist at all. Discovered here from the same slide
    # scan sync_store() already runs below, rather than a second walk over
    # every slide file, since referenced_images() has already done the
    # parsing work once per slide by the time rows exists.
    tikz_keys: set[str] = {
        reference
        for row in rows
        for reference in row.images
        if reference.startswith(alt_blocks.TIKZ_PREFIX)
    }
    for key in sorted(tikz_keys):
        if key not in entries:
            entries[key] = ImageEntry(image=key, role=ROLE_INFORMATIVE)
            report.added.append(key)

    on_disk_set = set(on_disk) | tikz_keys
    report.missing = [image for image in sorted(entries) if image not in on_disk_set]

    referenced: dict[str, set[str]] = {}
    for row in rows:
        for reference in row.images:
            entry = lookup(entries, reference)
            if entry is None:
                continue
            referenced.setdefault(entry.image, set()).add(row.slide_id)

    for image, slide_ids in referenced.items():
        entry = entries[image]
        for slide_id in sorted(slide_ids):
            if slide_id not in entry.used_on:
                entry.used_on[slide_id] = SlideUse()
                report.new_uses.append((image, slide_id))
        for slide_id in sorted(entry.used_on):
            if slide_id not in slide_ids:
                report.stale_uses.append((image, slide_id))

    if report.changed:
        save_store(entries)
    return report


def lookup(entries: dict[str, ImageEntry], reference: str) -> ImageEntry | None:
    """Resolve a filename as written in a `.tex` file against the store --
    identical matching rules to the old alt_manifest.lookup()."""
    reference = reference.strip().replace("\\", "/")
    # A tikz reference is exact by construction -- both the reference
    # (alt_blocks.referenced_images()) and the store key
    # (ImageEntry.image, written by sync_store() above) are the same
    # "tikz:ID" string, no filename/stem fuzzy-matching involved, since
    # there is no filename at all to be fuzzy about.
    if reference.startswith(alt_blocks.TIKZ_PREFIX):
        return entries.get(reference)
    name = reference.rsplit("/", 1)[-1]

    by_name: dict[str, ImageEntry] = {}
    by_stem: dict[str, ImageEntry] = {}
    for entry in entries.values():
        entry_name = entry.image.rsplit("/", 1)[-1]
        by_name.setdefault(entry_name, entry)
        by_stem.setdefault(entry_name.rsplit(".", 1)[0], entry)

    if name in by_name:
        return by_name[name]
    return by_stem.get(name.rsplit(".", 1)[0] if "." in name else name)


# --------------------------------------------------------------------------
# Staleness
# --------------------------------------------------------------------------

def _image_hash(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _image_hash_cache.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _image_hash_cache[key] = digest
    return digest


def content_hash(image_path: Path) -> str:
    """The image's own bytes only -- what invalidates an ImageEntry's
    reviewed status. No slide text involved: the description belongs to
    the picture, not to any one slide that happens to show it."""
    return _image_hash(image_path)[:12]


def tikz_source_hash(source: str) -> str:
    """content_hash()'s counterpart for a tikz illustration, which has no
    file/bytes to hash -- its own tikz source (already comment-stripped by
    alt_blocks.referenced_tikz_illustrations()) stands in for "the picture's
    own bytes" instead. `source` is the illustration's own [options] and
    body concatenated (tikz_render.py's own call site) -- both matter: a
    style defined only in the options block (box/.style={...}) and never
    touched again still changes what the picture looks like if edited, even
    with the body itself untouched. Whitespace-normalized the same way
    slide_context_hash() is (a version-note-driven reformat of surrounding
    slide code shouldn't ever touch this hash, but a real edit to the
    drawing itself always does): used by tikz_render.py to name/invalidate
    its rendered-PNG cache, not currently wired into image_state()'s own
    reviewed/stale logic -- see that function's own docstring: today's
    staleness is driven by slide_context_hash() and a human-set `status`,
    the same as a real image's is, not by re-hashing the picture itself on
    every scan."""
    normalized = "\n".join(line.strip() for line in source.splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def slide_context_hash(slide_path: Path) -> str:
    """What invalidates a *SlideUse*'s reviewed status: this slide's own
    text (title, body -- whatever informs whether its takeaway still makes
    sense), comments and layout whitespace excluded for the same reason
    alt_blocks.compute_hash() excluded them -- these files accumulate
    version notes on every edit, and a flag that resets on every one of
    those gets ignored within a week. No %%ALT block to exclude any more:
    nothing describing an image lives in the slide file at all now.
    """
    text = slide_path.read_text(encoding="utf-8")
    stripped = alt_blocks.COMMENT_RE.sub("", text)
    normalized = "\n".join(
        line.strip() for line in stripped.splitlines() if line.strip()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def en_text_hash(entry: ImageEntry) -> str:
    """sha256 (12 hex chars, same truncation as content_hash()/
    slide_context_hash()) of the EN short+long+takeaway_default text --
    what ImageEntry.translated_from_hash is compared against to tell
    whether a German translation is still current."""
    combined = f"{entry.short}\n{entry.long}\n{entry.takeaway_default}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]


def translation_state(entry: ImageEntry) -> str:
    """Reuses image_state()'s STATE_NONE/STATE_STALE/STATE_REVIEWED
    vocabulary for the same shape of problem (draft/stale/current), keyed
    off translated_from_hash instead of a human-review timestamp:
    STATE_NONE (no German text at all yet), STATE_STALE (German text
    exists but the English text has changed since it was translated), or
    STATE_REVIEWED (German text exists and matches the English text it
    was translated from -- "reviewed" here means "in sync with English",
    not necessarily human-proofread)."""
    if not entry.has_content_de:
        return STATE_NONE
    if entry.translated_from_hash != en_text_hash(entry):
        return STATE_STALE
    return STATE_REVIEWED


def image_state(entry: ImageEntry) -> str:
    """Draft/reviewed state of the image's own content (role/short/long),
    independent of any one slide's use of it."""
    if not entry.has_content:
        return STATE_NONE
    if entry.status == STATUS_REVIEWED:
        return STATE_REVIEWED
    return STATE_DRAFT


def slide_use_state(entry: ImageEntry, slide_id: str, slide_hash: str) -> str:
    """State of one slide's use of one image -- the finer-grained
    replacement for the old single per-slide %%ALT block state.

    Reviewed here means both halves are current: the image's own content
    is reviewed, *and* this slide's own use of it (context, takeaway) was
    confirmed since this slide's text last changed.
    """
    if not entry.has_content:
        return STATE_NONE
    use = entry.used_on.get(slide_id)
    if entry.status != STATUS_REVIEWED:
        return STATE_DRAFT
    if use is None or not use.reviewed:
        return STATE_DRAFT
    if use.stored_hash != slide_hash:
        return STATE_STALE
    return STATE_REVIEWED
