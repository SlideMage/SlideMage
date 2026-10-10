"""Image descriptions, review side: what the Images page works out and stores, without any widget.

Each slide that shows an image is a SlideView (its scan row, the worst review state across its
images, the hash of its text). Filtering, ordering, finding and counting them, saving the
edited form of a slide's images, and replacing an image with another file are all here; the
drafting and translating models are alt_draft's, the store itself is alt_images'."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import alt_blocks, alt_images
from .deck_editor import parse_slide_calls
from .deck_scan import PROJECT_ROOT, Deck

# (label, states shown; None shows every slide)
FILTERS = [
    ("Needs attention", (alt_images.STATE_NONE, alt_images.STATE_DRAFT, alt_images.STATE_STALE)),
    ("All slides with images", None),
    ("No description", (alt_images.STATE_NONE,)),
    ("Draft, unreviewed", (alt_images.STATE_DRAFT,)),
    ("Needs re-check", (alt_images.STATE_STALE,)),
    ("Reviewed", (alt_images.STATE_REVIEWED,)),
]
FILTER_ALL = 1   # index of "All slides with images"

# Worst first, as alt_images.STATE_LABELS is ordered.
_STATE_RANK = {alt_images.STATE_NONE: 0, alt_images.STATE_DRAFT: 1,
               alt_images.STATE_STALE: 2, alt_images.STATE_REVIEWED: 3}

# What a form holds per image; `role` is the image's, the takeaways are as this slide shows them.
FIELDS = ("role", "short", "long", "source", "takeaway", "short_de", "long_de", "source_de", "takeaway_de")


@dataclass
class SlideView:
    row: alt_blocks.SlideRow
    state: str
    slide_hash: str


def image_state(entries: dict[str, alt_images.ImageEntry], reference: str, slide_id: str, slide_hash: str) -> str:
    """State of one slide's use of one image; an image without an entry has no description."""
    entry = alt_images.lookup(entries, reference)
    return alt_images.STATE_NONE if entry is None else alt_images.slide_use_state(entry, slide_id, slide_hash)


def slide_state(row: alt_blocks.SlideRow, entries: dict[str, alt_images.ImageEntry], slide_hash: str) -> str:
    """The worst state across the images a slide shows."""
    states = [image_state(entries, reference, row.slide_id, slide_hash) for reference in row.images]
    return min(states, key=_STATE_RANK.__getitem__, default=alt_images.STATE_REVIEWED)


def scan_views(entries: dict[str, alt_images.ImageEntry]) -> list[SlideView]:
    """Every slide that shows at least one image."""
    views = []
    for row in alt_blocks.scan_slides_raw():
        slide_hash = alt_images.slide_context_hash(row.path)
        views.append(SlideView(row, slide_state(row, entries, slide_hash), slide_hash))
    return views


def sort_order(deck: Deck) -> dict[str, int]:
    """Slide id -> position in `deck`."""
    return {call.id: position for position, call in enumerate(parse_slide_calls(deck))}


def visible_views(views: list[SlideView], states: tuple[str, ...] | None, *,
                  pin: Path | None = None, order: dict[str, int] | None = None) -> list[SlideView]:
    """The views in `states` (None: all), plus the one at `pin` even if its state is not among them,
    ordered by `order` (slide id -> position; slides missing from it keep their order, at the end)."""
    shown = views if states is None else [view for view in views if view.state in states]
    if pin is not None and not any(view.row.path == pin for view in shown):
        shown = [view for view in views if view.row.path == pin] + shown
    if order:
        shown = sorted(shown, key=lambda view: order.get(view.row.slide_id, len(order)))
    return shown


def state_counts(views: list[SlideView]) -> dict[str, int]:
    counts = dict.fromkeys(_STATE_RANK, 0)
    for view in views:
        counts[view.state] += 1
    return counts


def summary_text(views: list[SlideView]) -> str:
    counts = state_counts(views)
    return (f"{counts[alt_images.STATE_REVIEWED]} reviewed · {counts[alt_images.STATE_STALE]} need re-check · "
            f"{counts[alt_images.STATE_DRAFT]} draft · {counts[alt_images.STATE_NONE]} undescribed")


def find_slide(views: list[SlideView], text: str) -> SlideView | None:
    """The view for a bare slide id or an "id-slug" (a slide file's stem)."""
    candidate_id = text.split("-", 1)[0].strip().lower()
    by_id = next((view for view in views if view.row.slide_id.lower() == candidate_id), None)
    return by_id or next((view for view in views if view.row.path.name.lower().startswith(text.lower())), None)


def needs_long_description(role: str, long: str) -> bool:
    """An informative image cannot be reviewed without a long description."""
    return role == alt_images.ROLE_INFORMATIVE and not long


# -- saving a slide's form ---------------------------------------------------------------------------


@dataclass
class FormEdit:
    """One image's form: `values` as typed and `baseline` as it was shown (both keyed by FIELDS),
    `baseline_en_hash` the English text it was shown with, and `provenance` the exact source hash
    and German values of a translation applied to it (None when there is none)."""

    reference: str
    values: dict[str, str]
    baseline: dict[str, str]
    baseline_en_hash: str
    provenance: dict | None = None


def form_baseline(entry: alt_images.ImageEntry, slide_id: str) -> dict[str, str]:
    return {"role": entry.role, "short": entry.short, "long": entry.long, "source": entry.source,
            "takeaway": entry.takeaway_for(slide_id), "short_de": entry.short_de, "long_de": entry.long_de,
            "source_de": entry.source_de, "takeaway_de": entry.takeaway_for_de(slide_id)}


def _promote_takeaway(typed: str, default: str) -> tuple[str, str]:
    """(new default, new slide override) for a typed takeaway: it equals the default (follow it),
    becomes the default if there is none yet, or is an override of this slide."""
    if typed == default:
        return default, ""
    if not default and typed:
        return typed, ""
    return default, typed


def apply_form_edit(entry: alt_images.ImageEntry, slide_id: str, edit: FormEdit) -> alt_images.SlideUse:
    """Copy into `entry` only the fields changed in the form: the store can change while the form is
    open (draft and translation workers write each image as they finish), and every untouched value
    stays at its newest persisted value. Returns this slide's use of the image."""
    changed = {key for key in FIELDS if edit.values[key] != edit.baseline[key]}
    values = edit.values
    for key in ("role", "short", "long", "source", "short_de", "long_de", "source_de"):
        if key in changed:
            setattr(entry, key, values[key])
    use = entry.used_on.setdefault(slide_id, alt_images.SlideUse())
    if "takeaway" in changed:
        entry.takeaway_default, use.takeaway = _promote_takeaway(values["takeaway"], entry.takeaway_default)
    if "takeaway_de" in changed:
        entry.takeaway_default_de, use.takeaway_de = _promote_takeaway(
            values["takeaway_de"], entry.takeaway_default_de)

    provenance = edit.provenance or {}
    fields = provenance.get("fields", {})
    provenance_matches = (
        bool(provenance)
        and fields.get("short_de") == entry.short_de
        and fields.get("long_de") == entry.long_de
        and fields.get("takeaway_de") == entry.takeaway_for_de(slide_id)
        and provenance.get("source_hash") == alt_images.en_text_hash(entry)
    )
    if provenance_matches:
        entry.translated_from_hash = str(provenance["source_hash"])
    elif changed & {"short_de", "long_de", "takeaway_de"}:
        if not entry.short_de and not entry.long_de:
            entry.translated_from_hash = ""
        elif alt_images.en_text_hash(entry) == edit.baseline_en_hash:
            # A manual German edit is in sync only while the latest English text still matches
            # the form's original source.
            entry.translated_from_hash = alt_images.en_text_hash(entry)
        else:
            # The German was edited against an older form, but the live English text has since
            # changed (possibly alongside a worker translation); an empty source hash keeps the
            # pair visibly stale instead of blessing the edited German against the newer English.
            entry.translated_from_hash = ""
    return use


def save_slide_forms(slide_id: str, slide_path: Path, edits: list[FormEdit], *, reviewed: bool) -> None:
    """Store the forms of one slide's images, then stamp its use of each as alt_images.stamp_review()
    does. The slide hash is taken now, not at scan time: the slide may have been edited since, and a
    stale hash would mark it reviewed against text nobody looked at."""
    slide_hash = alt_images.slide_context_hash(slide_path)

    def mutate(entries: dict[str, alt_images.ImageEntry]) -> bool:
        for edit in edits:
            entry = entries.setdefault(edit.reference, alt_images.ImageEntry(image=edit.reference))
            use = apply_form_edit(entry, slide_id, edit)
            alt_images.stamp_review(entry, use, reviewed, slide_hash)
        return True

    alt_images.update_store(mutate)


def source_hash(short: str, long: str, takeaway: str) -> str:
    """The English text hash a translation of exactly this text is made from."""
    return alt_images.en_text_hash(alt_images.ImageEntry(image="", short=short, long=long, takeaway_default=takeaway))


# -- replacing an image ------------------------------------------------------------------------------


def copy_into_media(source: Path, name: str) -> Path:
    """Copy `source` to media/`name`; OSError if that fails."""
    destination = PROJECT_ROOT / "media" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(destination))
    return destination


def repoint_slides(entry: alt_images.ImageEntry, entries: dict[str, alt_images.ImageEntry],
                   targets: dict[str, Path], rows: dict[str, alt_blocks.SlideRow],
                   old_reference: str, new_reference: str) -> tuple[list[str], list[str]]:
    """Point the slide files in `targets` (slide id -> file) from `entry`'s image to `new_reference`.
    Returns (ids changed, failure messages). A slide may spell the old reference differently
    (extension or not) from `old_reference`, so it is looked up among the slide's own images."""
    changed, failures = [], []
    for slide_id, path in targets.items():
        raw = old_reference
        row = rows.get(slide_id)
        if row is not None:
            raw = next((ref for ref in row.images
                        if (found := alt_images.lookup(entries, ref)) is not None and found.image == entry.image),
                       old_reference)
        try:
            text = path.read_text(encoding="utf-8")
            new_text, count = alt_blocks.replace_image_reference(text, raw, new_reference)
            if count == 0:
                failures.append(f"{slide_id}: reference not found in {path.name} as written")
                continue
            path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            failures.append(f"{slide_id}: {exc}")
            continue
        changed.append(slide_id)
    return changed, failures


def is_unused_after(entry: alt_images.ImageEntry, changed: list[str]) -> bool:
    """Whether no slide uses the image any more once the slides in `changed` point elsewhere."""
    return not set(entry.used_on) - set(changed)


def has_text(entry: alt_images.ImageEntry) -> bool:
    """Whether the entry holds any text worth asking about before it is deleted."""
    return bool(entry.short or entry.long or entry.takeaway_default or entry.source)
