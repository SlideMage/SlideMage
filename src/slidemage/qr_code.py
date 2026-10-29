# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""QR codes for slides (2026-10-25, direct instruction): a link, an email, a contact, a
calendar event or a map location as a QR code file, and the \\SMQRCode call that puts it on a
slide (SlideMage_base.tex). Used by the Source view's "Insert QR" dialog
(ui/dialogs/qr_code.py) and the agent's make_qr_code tool.

* What a phone reads: `payload()` turns the fields of a kind into the text the code holds --
  the URL itself, a mailto: link, a vCard 3.0, an iCalendar VEVENT, or a map link (Google Maps,
  a geo: URI or OpenStreetMap). segno (BSD licence, pure Python) makes the code and its PNG;
  the vector files are drawn here, as filled rectangles (`_save_vector`).
* Files: PDF (the project's default, vector), PNG, SVG and EPS. LuaLaTeX includes PDF and PNG;
  SVG and EPS are for a copy saved outside the project. Dark modules on a white quiet zone,
  whatever the slide's background: a scanner needs the light border.
* How large: `recommended_height()` -- a phone reads a module (one dot) from about 500 times its
  size away. On the screen a module is (slide height / modules), so the code's share of the
  slide height follows from the room's farthest-viewer-to-screen-height ratio alone. A rule of
  thumb, on the safe side; sizes of 0.6 and more are meant (a code may have a slide of its own).
* A click does what a scan does (2026-10-29): the call ends in [link] (`link_target`) for a link, an email
  and a map location, and \\SMQRCode makes the code a link to it.
* What the project keeps: the file in media/, its alt text in media/alt-text.json, and in
  media/qr-codes.json the kind and fields it was made from, so the dialog can open it again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import pymupdf as fitz
import segno
from segno import helpers

from . import alt_images, slide_import
from .fileio import read_json, write_json
from .project import ProjectContext

KIND_URL = "url"
KIND_EMAIL = "email"
KIND_CONTACT = "contact"
KIND_EVENT = "event"
KIND_LOCATION = "location"
KINDS = (KIND_URL, KIND_EMAIL, KIND_CONTACT, KIND_EVENT, KIND_LOCATION)
KIND_LABELS = {KIND_URL: "URL", KIND_EMAIL: "Email", KIND_CONTACT: "Contact (vCard)",
               KIND_EVENT: "Calendar event", KIND_LOCATION: "Map location"}

# The fields of each kind, in the dialog's order; the first is required (for an event also "start").
FIELDS = {
    KIND_URL: ("url",),
    KIND_EMAIL: ("to", "subject", "body"),
    KIND_CONTACT: ("name", "organization", "title", "email", "phone", "website",
                   "street", "postcode", "city", "country"),
    KIND_EVENT: ("title", "start", "end", "all_day", "location", "description", "url"),
    KIND_LOCATION: ("place", "label", "map_link"),
}
REQUIRED = {KIND_URL: ("url",), KIND_EMAIL: ("to",), KIND_CONTACT: ("name",),
            KIND_EVENT: ("title", "start"), KIND_LOCATION: ("place",)}

LINK_GOOGLE = "google"
LINK_GEO = "geo"
LINK_OSM = "osm"
LINK_STYLES = {LINK_GOOGLE: "Google Maps link (every phone)", LINK_GEO: "geo: URI (Android map apps, smaller code)",
               LINK_OSM: "OpenStreetMap link"}

FORMATS = ("pdf", "png", "svg", "eps")
PROJECT_FORMATS = ("pdf", "png")          # what LuaLaTeX includes
ERROR_LEVELS = ("L", "M", "Q", "H")
DEFAULT_BORDER = 4                        # the quiet zone the standard asks for, in modules
PNG_WIDTH = 1000                          # pixels a PNG is at least wide

CAPTION_NONE = "none"                     # the default (2026-10-26, direct request)
CAPTION_CONTENT = "content"               # the URL, address, name, ... (default_caption())
CAPTION_CUSTOM = "custom"

# Where the call goes: at the cursor (""), or in a corner of the content area through \cornerfigure.
CORNERS = {"": "Where the cursor is", "ne": "Top right corner", "se": "Bottom right corner",
           "sw": "Bottom left corner", "nw": "Top left corner"}

DEFAULT_HEIGHT = 0.6                      # of \textheight
MIN_HEIGHT = 0.2
MAX_HEIGHT = 0.95
# Farthest viewer distance / projected screen height. A rule of thumb: the farthest seat of a
# room is about this many screen heights away.
ROOMS = (("Seminar room", 4.0), ("Lecture hall", 8.0))
READ_DISTANCE = 500                       # a module reads from this many times its size away

_STORE = "qr-codes.json"


@dataclass
class QRSpec:
    """What a code holds and how it is drawn."""

    kind: str = KIND_URL
    fields: dict[str, str] = field(default_factory=dict)
    error: str = "M"
    border: int = DEFAULT_BORDER

    def value(self, name: str) -> str:
        return str(self.fields.get(name, "") or "").strip()


# -- what the code holds ------------------------------------------------------------------

def default_error(kind: str) -> str:
    """M for a link, L for the long kinds (a vCard or an event): larger dots matter more on a
    projected slide than recovery from damage, which a code drawn on a slide hardly ever gets."""
    return "L" if kind in (KIND_CONTACT, KIND_EVENT) else "M"


def normalize_url(text: str) -> str:
    """`text` as a full link: "uni-graz.at/x" gets https://. ValueError when it cannot be one."""
    url = text.strip()
    if not url:
        raise ValueError("Enter the link.")
    if any(char.isspace() for char in url):
        raise ValueError("A link must not contain spaces.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() in ("http", "https") and not parts.hostname:
        raise ValueError("Enter a full link, like https://example.org/page.")
    return url


def _check_email(address: str) -> str:
    address = address.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        raise ValueError(f"'{address}' is not an email address.")
    return address


def _name_parts(name: str) -> str:
    """A vCard N value ("Family;Given") from "Given Family" or "Family, Given"."""
    if "," in name:
        family, given = (part.strip() for part in name.split(",", 1))
    else:
        words = name.split()
        family, given = words[-1], " ".join(words[:-1])
    return f"{family};{given}"


def display_name(name: str) -> str:
    """"Given Family" from "Family, Given" (and unchanged when there is no comma)."""
    family, _, given = name.strip().partition(",")
    return f"{given.strip()} {family.strip()}".strip() if given else name.strip()


def _ical_text(text: str) -> str:
    """RFC 5545 TEXT: backslash, semicolon, comma and line ends escaped."""
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def parse_when(text: str, all_day: bool) -> datetime | date:
    """'2026-12-14 10:00' (also 'T' between, or seconds), or '2026-12-14' for an all-day event."""
    text = text.strip()
    try:
        if all_day:
            return date.fromisoformat(text[:10])
        return datetime.fromisoformat(text.replace(" ", "T", 1))
    except ValueError:
        raise ValueError(f"'{text}' is not a date{'' if all_day else ' and time'} like "
                         f"{'2026-12-14' if all_day else '2026-12-14 10:00'}.") from None


def _ical_when(value: datetime | date) -> str:
    if isinstance(value, datetime):
        # A time without a zone is local time; as UTC it lands right wherever the phone is.
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return value.strftime("%Y%m%d")


def _event(spec: QRSpec) -> str:
    all_day = spec.value("all_day").lower() in ("1", "true", "yes")
    start = parse_when(spec.value("start"), all_day)
    if spec.value("end"):
        end = parse_when(spec.value("end"), all_day)
    else:
        end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
    if all_day and spec.value("end"):
        end = end + timedelta(days=1)     # DTEND of an all-day event is the day after the last
    if end <= start:
        raise ValueError("The event ends before it starts.")
    kind = ";VALUE=DATE" if all_day else ""
    lines = ["BEGIN:VEVENT", f"SUMMARY:{_ical_text(spec.value('title'))}",
             f"DTSTART{kind}:{_ical_when(start)}", f"DTEND{kind}:{_ical_when(end)}"]
    for name, key in (("location", "LOCATION"), ("description", "DESCRIPTION")):
        if spec.value(name):
            lines.append(f"{key}:{_ical_text(spec.value(name))}")
    if spec.value("url"):
        lines.append(f"URL:{normalize_url(spec.value('url'))}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


# Coordinates in text or in a map link: "47.0777, 15.4495", Google's "@47.07,15.44,17z" and
# "query=47.07,15.44", Apple's "ll=" / "q=", OpenStreetMap's "mlat=..&mlon=" and "#map=17/47.07/15.44".
_COORDS_RES = (
    re.compile(r"mlat=(-?\d+(?:\.\d+)?)&mlon=(-?\d+(?:\.\d+)?)"),
    re.compile(r"#map=\d+/(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)"),
    re.compile(r"[@=](-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"),
    re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$"),
)


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """(latitude, longitude) from `text` or a map link; None when it holds none (an address)."""
    for pattern in _COORDS_RES:
        match = pattern.search(text.strip())
        if match:
            lat, lng = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None


def _degrees(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _location(spec: QRSpec) -> str:
    place, style = spec.value("place"), spec.value("map_link") or LINK_GOOGLE
    coords = parse_coordinates(place)
    lat, lng = (_degrees(c) for c in coords) if coords else ("", "")
    where = f"{lat},{lng}" if coords else place
    if style == LINK_GEO:
        return f"geo:{where}" if coords else f"geo:0,0?q={quote(place)}"
    if style == LINK_OSM:
        if coords:
            return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}"
        return f"https://www.openstreetmap.org/search?query={quote(place)}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(where, safe=',')}"


def payload(spec: QRSpec) -> str:
    """The text the code holds. ValueError, saying what to enter, when a field is missing or wrong."""
    if spec.kind not in KINDS:
        raise ValueError(f"Unknown QR code kind '{spec.kind}'. Kinds: {', '.join(KINDS)}.")
    for name in REQUIRED[spec.kind]:
        if not spec.value(name):
            raise ValueError(f"Enter the {name.replace('_', ' ')}.")
    if spec.kind == KIND_URL:
        return normalize_url(spec.value("url"))
    if spec.kind == KIND_EMAIL:
        return helpers.make_make_email_data(_check_email(spec.value("to")), subject=spec.value("subject") or None,
                                            body=spec.value("body") or None)
    if spec.kind == KIND_CONTACT:
        name = spec.value("name")
        email = _check_email(spec.value("email")) if spec.value("email") else None
        website = normalize_url(spec.value("website")) if spec.value("website") else None
        optional = {key: spec.value(name) or None for key, name in (
            ("org", "organization"), ("title", "title"), ("phone", "phone"), ("street", "street"),
            ("zipcode", "postcode"), ("city", "city"), ("country", "country"))}
        return helpers.make_vcard_data(_name_parts(name), display_name(name), email=email, url=website, **optional)
    if spec.kind == KIND_EVENT:
        return _event(spec)
    return _location(spec)


def make(spec: QRSpec) -> segno.QRCode:
    """The code; ValueError for missing or wrong fields, or more data than a QR code holds."""
    data = payload(spec)
    try:
        return segno.make(data, error=spec.error.lower(), micro=False, boost_error=False)
    except segno.DataOverflowError:
        raise ValueError("This is more than a QR code can hold. Leave out some of the text.") from None


def modules(code: segno.QRCode, border: int = DEFAULT_BORDER) -> int:
    """Modules across, quiet zone included: what the image's height is made of."""
    return code.symbol_size(border=border)[0]


def recommended_height(total_modules: int, ratio: float) -> float:
    """The code's share of \\textheight so the farthest viewer can scan it (see the module doc);
    at least MIN_HEIGHT. May be above 1: then the code is too dense for that room."""
    return max(MIN_HEIGHT, total_modules * ratio / READ_DISTANCE)


def size_advice(code: segno.QRCode, border: int = DEFAULT_BORDER) -> list[tuple[str, float]]:
    """(room, recommended height) for each of ROOMS."""
    total = modules(code, border)
    return [(room, recommended_height(total, ratio)) for room, ratio in ROOMS]


def size_note(code: segno.QRCode, border: int = DEFAULT_BORDER) -> str:
    """One line for the dialog and the agent: the grid and the recommended heights."""
    rooms = []
    for room, height in size_advice(code, border):
        rooms.append(f"{room} ≥ {height:.2f}" if height <= MAX_HEIGHT else f"{room}: too dense even at full height")
    text = f"{code.symbol_size(border=0)[0]}×{code.symbol_size(border=0)[0]} modules. Recommended height " \
           f"(share of the text height): {'; '.join(rooms)}."
    if size_advice(code, border)[-1][1] > MAX_HEIGHT:
        text += " Fewer fields or a shorter link make the code coarser."
    return text


# -- captions and alt text ----------------------------------------------------------------------

def default_caption(spec: QRSpec) -> str:
    """Plain text under the code: the link, the address, the name, title and date, the place."""
    if spec.kind == KIND_URL:
        return normalize_url(spec.value("url"))
    if spec.kind == KIND_EMAIL:
        return spec.value("to")
    if spec.kind == KIND_CONTACT:
        return display_name(spec.value("name"))
    if spec.kind == KIND_EVENT:
        return f"{spec.value('title')}, {spec.value('start').replace('T', ' ')}"
    return spec.value("label") or spec.value("place")


def alt_text(spec: QRSpec) -> str:
    """The short description screen readers get."""
    if spec.kind == KIND_URL:
        return f"QR code linking to {normalize_url(spec.value('url'))}"
    if spec.kind == KIND_EMAIL:
        return f"QR code: write an email to {spec.value('to')}"
    if spec.kind == KIND_CONTACT:
        return f"QR code: add contact {display_name(spec.value('name'))}"
    if spec.kind == KIND_EVENT:
        return f"QR code: calendar event '{spec.value('title')}', {spec.value('start').replace('T', ' ')}"
    return f"QR code: map location {spec.value('label') or spec.value('place')}"


def caption_latex(spec: QRSpec, mode: str, custom: str = "") -> str:
    """The caption argument of \\SMQRCode: a link as \\url (breaks at its slashes), other text escaped."""
    if mode == CAPTION_NONE:
        return ""
    if mode == CAPTION_CUSTOM:
        return slide_import.escape_latex(custom.strip())
    text = default_caption(spec)
    if spec.kind == KIND_URL:
        # Same protection as latex_edit.format_hyperlink: \url reads its argument as a macro argument here.
        encoded = quote(text, safe=":/?#[]@!$&'()*+,;=%-._~")
        for char in "%#":
            encoded = encoded.replace(char, "\\" + char)
        return f"\\url{{{encoded}}}"
    return slide_import.escape_latex(text)


def link_target(spec: QRSpec) -> str:
    """The address a click on the code opens (2026-10-29, direct instruction: the same as a scan): the link,
    the mailto: link, the map link or geo: URI; "" for a contact or an event, which no link opens."""
    return payload(spec) if spec.kind in (KIND_URL, KIND_EMAIL, KIND_LOCATION) else ""


def link_latex(link: str) -> str:
    """`link` as the [link] argument of \\SMQRCode: percent-encoded where TeX or the optional argument would
    misread it (spaces, brackets, ~), and % and # escaped as in caption_latex."""
    encoded = quote(link, safe=":/?#@!$&'()*+,;=%-._").replace("~", "%7E")     # quote() keeps ~ always
    for char in "%#":
        encoded = encoded.replace(char, "\\" + char)
    return encoded


def snippet(image: str, height: float, caption: str, link: str = "") -> str:
    """The \\SMQRCode call: `image` root-relative, `height` a share of \\textheight, `link` (link_target) the
    address the code links to, written as the trailing [link] argument; "" for none."""
    return f"\\SMQRCode[{height:.2f}\\textheight]{{{image}}}{{{caption}}}" + (f"[{link_latex(link)}]" if link else "")


def place(call: str, corner: str = "") -> str:
    """`call` as it is, or in \\cornerfigure[corner=...] (SlideMage_base.tex) for one of CORNERS."""
    if corner not in CORNERS:
        raise ValueError(f"The corner is one of {', '.join(c for c in CORNERS if c)}.")
    return f"\\cornerfigure[corner={corner}]{{{call}}}" if corner else call


# -- files --------------------------------------------------------------------------------------

MODULE_PT = 4                             # a module's size in a PDF or EPS at natural size (a 33-module code: 4.7 cm)


def _runs(code: segno.QRCode, border: int) -> list[tuple[int, int, int]]:
    """(x, y, length) of each horizontal run of dark modules, in modules from the top left, quiet zone included."""
    runs = []
    for y, row in enumerate(code.matrix):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                runs.append((start + border, y + border, x - start))
            else:
                x += 1
    return runs


def _save_vector(code: segno.QRCode, path: Path, fmt: str, border: int) -> None:
    """PDF, SVG or EPS as filled rectangles, one per run of dark modules, on a white square.

    Not segno's own vector output (2026-10-26, found in a deck preview): it draws each run as a stroked line
    and leaves the line width unset, and a PDF placed with \\includegraphics takes the width of the page
    around it -- the slide's thin lines, so every row came out as a hairline with gaps between them. A fill
    has no line width to inherit."""
    total, runs = modules(code, border), _runs(code, border)
    if fmt == "pdf":
        doc = fitz.open()
        page = doc.new_page(width=total * MODULE_PT, height=total * MODULE_PT)
        shape = page.new_shape()
        shape.draw_rect(page.rect)
        shape.finish(color=None, fill=(1, 1, 1), width=0)
        for x, y, length in runs:
            shape.draw_rect(fitz.Rect(x, y, x + length, y + 1) * MODULE_PT)
        shape.finish(color=None, fill=(0, 0, 0), width=0)          # one path, one fill: no seams between runs
        shape.commit()
        doc.save(str(path), garbage=3, deflate=True)
        doc.close()
    elif fmt == "svg":
        rows = "".join(f"M{x} {y}h{length}v1h-{length}z" for x, y, length in runs)
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
                        f'width="{total * MODULE_PT}pt" height="{total * MODULE_PT}pt" shape-rendering="crispEdges">'
                        f'<rect width="{total}" height="{total}" fill="#fff"/><path fill="#000" d="{rows}"/></svg>\n',
                        encoding="utf-8")
    else:
        size, unit = total * MODULE_PT, MODULE_PT
        fills = "\n".join(f"{x * unit} {(total - y - 1) * unit} {length * unit} {unit} rectfill" for x, y, length in runs)
        path.write_text(f"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 {size} {size}\n%%EndComments\n"
                        f"1 setgray 0 0 {size} {size} rectfill\n0 setgray\n{fills}\nshowpage\n%%EOF\n",
                        encoding="ascii")


def save(code: segno.QRCode, path: Path, fmt: str | None = None, border: int = DEFAULT_BORDER) -> Path:
    """Write the code as PDF, PNG, SVG or EPS (from `fmt`, else the suffix)."""
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt not in FORMATS:
        raise ValueError(f"QR codes are saved as {', '.join(FORMATS)}, not '{fmt}'.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "png":
        code.save(str(path), kind="png", border=border, dark="#000", light="#fff",
                  scale=max(1, -(-PNG_WIDTH // modules(code, border))))
    else:
        _save_vector(code, path, fmt, border)
    return path


def slug(text: str) -> str:
    """A file name part from a caption, a host or a name: lowercase ASCII, dashes."""
    text = re.sub(r"^[a-z]+://(www\.)?", "", text.strip().lower())
    text = text.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-")


def suggest_name(spec: QRSpec, caption: str = "") -> str:
    """'qr-<slug>' from the custom caption, else the kind's own text."""
    try:
        base = caption.strip() or default_caption(spec)
    except ValueError:
        base = ""
    name = slug(base) or spec.kind
    return name if name == "qr" or name.startswith("qr-") else f"qr-{name}"     # "QR 1" -> qr-1


def free_path(folder: Path, name: str, fmt: str) -> Path:
    """folder/name.fmt, or name-2, name-3, ... when taken: an existing file is never overwritten."""
    stem = slug(name.removesuffix(f".{fmt}")) or "qr"
    stem = stem if stem == "qr" or stem.startswith("qr-") else f"qr-{stem}"
    path, number = folder / f"{stem}.{fmt}", 2
    while path.exists():
        path, number = folder / f"{stem}-{number}.{fmt}", number + 1
    return path


# -- what the project keeps ------------------------------------------------------------------

def _store_path(ctx: ProjectContext) -> Path:
    return ctx.media_dir / _STORE


def load_spec(ctx: ProjectContext, image: str) -> tuple[QRSpec, dict] | None:
    """The spec a project file was made from and its other settings (caption mode/text, height)."""
    entry = read_json(_store_path(ctx)).get(image)
    if not isinstance(entry, dict) or entry.get("kind") not in KINDS:
        return None
    spec = QRSpec(entry["kind"], {k: str(v) for k, v in (entry.get("fields") or {}).items()},
                  entry.get("error", "M"), int(entry.get("border", DEFAULT_BORDER)))
    return spec, {k: entry[k] for k in ("caption_mode", "caption") if k in entry}


def _record(ctx: ProjectContext, image: str, spec: QRSpec, caption_mode: str, caption: str) -> None:
    store = read_json(_store_path(ctx))
    store[image] = {"kind": spec.kind, "fields": {k: v for k, v in spec.fields.items() if str(v).strip()},
                    "error": spec.error, "border": spec.border, "caption_mode": caption_mode,
                    **({"caption": caption} if caption_mode == CAPTION_CUSTOM else {})}
    write_json(_store_path(ctx), store)

    def describe(entries: dict[str, alt_images.ImageEntry]) -> bool:
        entry = entries.setdefault(image, alt_images.ImageEntry(image=image))
        entry.role, entry.short, entry.status = alt_images.ROLE_INFORMATIVE, alt_text(spec), alt_images.STATUS_REVIEWED
        return True
    alt_images.update_store(ctx, describe)


@dataclass
class Created:
    image: str                # root-relative, forward slashes
    path: Path
    snippet: str
    note: str                 # size_note()


def create(ctx: ProjectContext, spec: QRSpec, *, height: float = DEFAULT_HEIGHT, fmt: str = "pdf",
           caption_mode: str = CAPTION_NONE, caption: str = "", name: str = "",
           replace: str = "", corner: str = "") -> Created:
    """Make the code, write it to media/ (a new name, or the file `replace` names), record its spec
    and alt text, and return the \\SMQRCode call, in \\cornerfigure for a `corner` (place()). ValueError for
    anything the user must change."""
    place("", corner)                       # an unknown corner is refused before anything is written
    if fmt not in PROJECT_FORMATS:
        raise ValueError(f"A QR code in the project is {' or '.join(PROJECT_FORMATS)}: LuaLaTeX includes those.")
    if spec.error not in ERROR_LEVELS:
        raise ValueError(f"The error correction level is one of {', '.join(ERROR_LEVELS)}.")
    code = make(spec)
    if caption_mode == CAPTION_CUSTOM and not caption.strip():
        raise ValueError("Enter the caption text, or choose no caption.")
    if replace:
        path = ctx.root / replace
        if path.parent.resolve() != ctx.media_dir.resolve() or path.suffix.lower() != f".{fmt}":
            raise ValueError(f"{replace} is not a .{fmt} file in media/.")
    else:
        path = free_path(ctx.media_dir, name or suggest_name(spec, caption if caption_mode == CAPTION_CUSTOM else ""), fmt)
    save(code, path, fmt, spec.border)
    image = path.relative_to(ctx.root).as_posix()
    _record(ctx, image, spec, caption_mode, caption)
    height = min(MAX_HEIGHT, max(0.05, height))
    call = place(snippet(image, height, caption_latex(spec, caption_mode, caption), link_target(spec)), corner)
    return Created(image, path, call, size_note(code, spec.border))
