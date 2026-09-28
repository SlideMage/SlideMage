"""Draft image descriptions with a vision model (ALT_TEXT_NOTES.md, phase 3).

Produces **unreviewed drafts** only. Everything this writes lands as state
🔴 in the review tab and must be checked by a human before it can be marked
reviewed -- see that file's decisions log for why that is not optional:
chart values read off a scanned figure are exactly where a vision model goes
wrong, and a wrong number in a description is worse than no description.

Backends are pluggable. Ollama is the one implemented (the user's Anthropic
account has no API access), but `DraftBackend` is a plain protocol, so an
`AnthropicBackend` can be added later without touching the review tab.

The actual Ollama calls here are stdlib only -- `urllib.request` and
`base64`, no `requests`, no `Pillow` -- matching this project's own
stdlib-first policy (see requirements.txt's header) wherever a real
dependency isn't already justified; PyMuPDF is one such justified
exception (slide_snapshot.py originally, media_render.py now too), and
this file only ever reaches it indirectly, via _resolve_describable()
rendering a .pdf media file to a PNG. Image resizing is otherwise
deliberately absent: Ollama does its own preprocessing for the vision
model, and the largest raster chart in media/ is 3400x1800, which
Qwen3-VL handles at native resolution.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import alt_blocks, alt_images, media_render, tikz_render, translation_prompts
from .deck_scan import PROJECT_ROOT

DEFAULT_OLLAMA_HOST = "http://localhost:11434"

# Formats Ollama's vision path can read directly.
DRAFTABLE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _resolve_describable(resolved: Path) -> Path | None:
    """`resolved` itself if Ollama's vision path can already read it, the
    path to its rendered PNG if it's a .pdf (rendered on demand and
    cached -- see media_render.py; the *slide's* own \\includegraphics
    keeps pointing at the original .pdf regardless), or None for anything
    else (.eps -- no renderer for it in this project, 2026-08-26 direct
    instruction scoped this to .pdf only)."""
    suffix = resolved.suffix.lower()
    if suffix in DRAFTABLE_SUFFIXES:
        return resolved
    if suffix == ".pdf":
        try:
            return media_render.ensure_rendered(resolved)
        except RuntimeError:
            return None
    return None


def _resolve_for_drafting(reference: str) -> Path | None:
    """The PNG to feed the vision model for one reference -- a real image
    (resolved off disk, then through _resolve_describable() above) or a
    tikz illustration (rendered fresh via tikz_render.py, which is also
    where "not found any more" or "failed to compile" turn into None the
    same way an unresolvable/undraftable real image already does here).

    The one call site both draftable_images() and images_needing_drafts()
    now share instead of each repeating "resolve, then _resolve_describable"
    -- a tikz reference has no file at all for alt_blocks.resolve_image()
    to find, so it has to be special-cased before that call rather than
    after it.
    """
    if reference.startswith(alt_blocks.TIKZ_PREFIX):
        try:
            return tikz_render.ensure_rendered(reference)
        except RuntimeError:
            return None
    resolved = alt_blocks.resolve_image(reference)
    return _resolve_describable(resolved) if resolved is not None else None


# The schema Ollama constrains the model's output to. Structured output
# rather than prose-plus-parsing: a vision model asked for four labelled
# fields in free text will reformat them differently every few images, and
# a parser for that is a permanent source of silent corruption.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "short": {"type": "string"},
        "long": {"type": "string"},
        "takeaway": {"type": "string"},
        "role_suggestion": {"type": "string", "enum": ["informative", "decorative"]},
    },
    "required": ["short", "long", "takeaway", "role_suggestion"],
}

# Mirrors the "Writing conventions for descriptions" section of
# ALT_TEXT_NOTES.md. Keep the two in sync -- if the conventions change
# there, this prompt is the other half of the change.
SYSTEM_PROMPT = """\
You write image descriptions for university finance lecture slides, for \
students who cannot see the images. Your descriptions are read aloud by a \
screen reader or read as text in a companion transcript.

Produce four fields.

SHORT: one locating sentence. What kind of image it is, of what, over what \
range. One or two lines, no more.

LONG: the actual content, structured rather than prose-shaped. Open with one \
sentence saying what kind of chart or image it is, what variable it plots \
(with units) against what, over what range, and how many data series. Then \
give the data itself: a Markdown table for data that runs over time or \
periods, an ordered list for ranked data. For a table of periods, add a short \
column saying what the line does in each one (rising, flat, a sharp fall). A \
blind student needs the numbers, not an impression of them. Read values off \
the axes as carefully as you can, and say explicitly when a value is \
approximate. Include nothing beyond that opening sentence and the data.

Write LONG as flowing text and tables only. Do not number or label its parts, \
and do not write headings like "1." or "Structure:" -- the reader sees only \
your text, not these instructions.

TAKEAWAY: one or two sentences on why this image is on this slide -- what \
the student is supposed to see in it. Ground this in the slide's own title \
and text, not in your own opinion about the topic.

ROLE_SUGGESTION: "informative" if the image carries information a student \
needs, "decorative" if it is an illustration, icon, logo, or mood image that \
carries nothing beyond the slide text.

Rules:
- Do NOT describe visual furniture. No tick-mark spacing, no gridlines, no \
shading, no legend inventories, no "the axis is labelled X" phrasing. Axis \
variable, unit and range are content and stay; the marks used to draw the \
axis are not.
- The exception is a visual property that IS the point of the slide -- if \
the slide is about linear versus logarithmic scaling, say which scale the \
axis uses.
- Never invent numbers. If a value cannot be read reliably, say so in place \
rather than guessing a precise-looking figure.
- Do NOT interpolate, extrapolate or evenly space values. If a chart has many \
bars and you cannot measure them individually, say exactly that, give the \
range of the axis and the smallest and largest values you *can* read, and \
describe the shape of the distribution. A short honest description beats a \
long table of invented numbers: a reader cannot tell a measured value from a \
guessed one, so a plausible-looking wrong table is worse than no table.
- A run of values at regular intervals (5, 10, 15, 20...) is almost always a \
sign you are guessing rather than reading. If your table looks like that, \
replace it with a description of the range and shape.
- Write plainly, for a reader who cannot check the picture against you.
"""

USER_TEMPLATE = """\
This image appears on a lecture slide.

Slide title: {title}
Slide ID: {slide_id}
Image file: {image}
{source}
Slide text:
{body}
{hint}
Describe the image."""


@dataclass
class SlideContext:
    """What the model is told about the slide an image sits on."""

    slide_id: str
    title: str
    body: str
    source: str
    image: str
    # A stored per-image correction; see AltImage.hint.
    hint: str = ""


@dataclass
class DraftResult:
    short: str = ""
    long: str = ""
    takeaway: str = ""
    role_suggestion: str = ""
    model: str = ""
    elapsed_s: float = 0.0
    error: str | None = None
    # True when a value table was removed as interpolated rather than
    # measured -- see detect_value_ramp().
    suspected_fabrication: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.long)


# --------------------------------------------------------------------------
# Slide context extraction
# --------------------------------------------------------------------------

_FRAME_BEGIN_RE = re.compile(r"\\begin\{\w*frame\}(?:\[[^\]]*\])?\{.*?\}", re.DOTALL)
_FRAME_END_RE = re.compile(r"\\end\{\w*frame\}")
_ITEM_RE = re.compile(r"\\item\s*")
_ENV_RE = re.compile(r"\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?(?:\{[^}]*\})?")
_MACRO_ARG_RE = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
_MACRO_BARE_RE = re.compile(r"\\[a-zA-Z]+\*?")

# Layout noise, stripped *before* macro flattening. Slides in this project
# are heavily hand-positioned, and without this the "slide text" handed to
# the model is mostly tikz: node options, paper-relative coordinates, struts,
# and the image's own filename repeated back as if it were prose. All of it
# is confidently meaningless to a description, and some of it is actively
# misleading (a model shown "9.58pt" will occasionally describe a measurement).
_GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")
_TIKZ_OPTS_RE = re.compile(r"\[[^\[\]]*=[^\[\]]*\]")          # [anchor=north west, ...]
_OVERLAY_RE = re.compile(r"<\d+[-–]?\d*>")                     # \item<2->, \node<4->
_COORD_RE = re.compile(
    r"\((?:[^()]*(?:pt|cm|mm|current page|\$|\+\+)[^()]*)\)"    # ($(current page)+(4pt,-2pt)$)
)
_DIMENSION_RE = re.compile(
    r"(?<![\w.])[-+]?\d*\.?\d+\s*(?:pt|cm|mm|em|ex|in|bp|sp)\b"
)
_TIKZ_STYLE_RE = re.compile(r"\[[A-Za-z]\w*\]")                # [zEightBoxColor]
_NODE_NAME_RE = re.compile(r"\((?:[A-Za-z]\w*)\)")             # (leftchart)
_MATH_RESIDUE_RE = re.compile(r"\$[^$A-Za-z]*\$")              # ($ +(,-)$)

# Lines that survive stripping but carry no words -- stray semicolons,
# leftover "to" from \vbox to 0pt, lone punctuation.
_NOISE_LINE_RE = re.compile(r"^(?:to|[\s;,.:*+\-−–—()\[\]<>/\\|]*)$")

# A line whose every alphabetic token is a tikz path keyword is drawing
# instructions, not slide text. Requiring *all* tokens to match keeps real
# prose safe -- a sentence about, say, the north-east corner of a market
# still contains ordinary words alongside "north" and "east".
_TIKZ_WORDS = {
    "at", "to", "node", "draw", "fill", "path", "rectangle", "circle",
    "ellipse", "arc", "grid", "cycle", "foreach", "anchor", "inner", "outer",
    "sep", "north", "south", "east", "west", "center", "midway", "above",
    "below", "left", "right", "opacity", "overlay", "remember", "picture",
    "current", "page", "and", "of", "shift", "xshift", "yshift",
}


def _is_layout_line(line: str) -> bool:
    tokens = re.findall(r"[A-Za-z]{2,}", line)
    return bool(tokens) and all(t.lower() in _TIKZ_WORDS for t in tokens)


def _flatten_latex(text: str) -> str:
    """Reduce slide body LaTeX to something a language model reads sensibly.

    Not a LaTeX parser and doesn't need to be -- this is context for a
    description, not a rendering. Keeps the argument of single-argument
    macros (so \\textbf{crucial} stays "crucial") and drops the rest.
    """
    text = _GRAPHICS_RE.sub(" ", text)
    text = _OVERLAY_RE.sub(" ", text)
    text = _COORD_RE.sub(" ", text)
    text = _TIKZ_OPTS_RE.sub(" ", text)
    text = _TIKZ_STYLE_RE.sub(" ", text)
    text = _NODE_NAME_RE.sub(" ", text)
    text = _MATH_RESIDUE_RE.sub(" ", text)
    text = _DIMENSION_RE.sub(" ", text)

    text = _ITEM_RE.sub("- ", text)
    text = _ENV_RE.sub("", text)
    for _ in range(3):  # nested macros, e.g. \\textbf{\\emph{x}}
        text = _MACRO_ARG_RE.sub(r"\1", text)
    text = _MACRO_BARE_RE.sub("", text)
    text = text.replace("~", " ").replace("\\\\", "\n")
    text = re.sub(r"[{}]", "", text)
    text = text.replace("``", '"').replace("''", '"')

    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(
        line for line in lines
        if line and not _NOISE_LINE_RE.match(line) and not _is_layout_line(line)
    )


def build_context(slide_path: Path, reference: str) -> SlideContext:
    """Assemble what the model is told about one image's slide.

    `\\note{}` content is deliberately **excluded**. Instructor notes often
    state the slide's point in one line -- exactly the takeaway we want --
    but they are instructor-only material that must never reach a student
    transcript. Keeping them out of the drafting input entirely is a much
    stronger guarantee than instructing the model not to repeat them.
    """
    source_text = slide_path.read_text(encoding="utf-8")
    stripped = alt_blocks.COMMENT_RE.sub("", source_text)

    slide_id, title = alt_blocks._slide_title(source_text, slide_path)

    body, sources = alt_blocks.extract_macro_calls(stripped, "source")
    body, _notes = alt_blocks.extract_macro_calls(body, "note")  # discarded, see docstring
    source_line = _flatten_latex(" ".join(sources)) if sources else ""

    # Brace-matched, same reason as alt_blocks._slide_title: a non-greedy
    # frame-open regex ends mid-title whenever the title carries a
    # `\footnote{...\fullcite{key}...}`, and the title's tail (", 430-431.")
    # then becomes the first line of what we hand the model as slide text.
    begin = alt_blocks.FRAME_OPEN_RE.search(body)
    end = _FRAME_END_RE.search(body)
    if begin and end:
        _title, after_title = alt_blocks.braced_argument(body, begin.end() - 1)
        if after_title < end.start():
            body = body[after_title:end.start()]
    body = _flatten_latex(body)

    entries = alt_images.load_store()
    entry = alt_images.lookup(entries, reference)

    return SlideContext(
        slide_id=slide_id,
        title=title,
        body=body or "(no body text)",
        source=source_line,
        image=reference,
        hint=entry.hint if entry else "",
    )


def build_prompt(context: SlideContext) -> str:
    source = f"Source line on the slide: {context.source}\n" if context.source else ""
    hint = (f"\nImportant correction about this specific image, from someone "
            f"who has looked at it: {context.hint}\n") if context.hint else ""
    return USER_TEMPLATE.format(
        title=context.title,
        slide_id=context.slide_id,
        image=context.image,
        source=source,
        body=context.body,
        hint=hint,
    )


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

class DraftBackend(Protocol):
    label: str

    def draft(self, image_path: Path, context: SlideContext) -> DraftResult: ...


# See the num_predict field comment on OllamaBackend below for what this is
# for. 4x the default budget -- large enough to finish the dense charts that
# actually need it, without becoming the new default cost for every image.
NUM_PREDICT_RETRY = 8192


@dataclass
class _Attempt:
    """One raw call to Ollama, before DraftResult's higher-level shaping."""

    elapsed_s: float
    error: str | None = None
    fields: dict | None = None
    content: str = ""
    thinking: str = ""
    done_reason: str = ""


@dataclass
class OllamaBackend:
    """Local Ollama. No API key, no per-image cost, nothing leaves the machine."""

    model: str
    host: str = DEFAULT_OLLAMA_HOST
    # 16k rather than the model's native 256k: one image plus a few hundred
    # words of slide context never approaches that, and the KV cache for a
    # 256k window is what pushes a 21 GB model past a 24 GB card into system
    # RAM. Keeping the window small is what keeps the whole model resident.
    num_ctx: int = 16384
    # Thinking improves value-reading off charts but multiplies wall-clock
    # time across a 200-image batch. Off by default; the bake-off measures
    # whether it earns its cost on this content.
    think: bool = False
    temperature: float = 0.2
    # A hard ceiling on generated tokens. Without it a model can run away on a
    # single image: qwen3-vl:32b hit the 600 s timeout on a 450x181, 16 KB map
    # during the bake-off, having succeeded on the *same* image in 69 s
    # minutes earlier -- so it is a generation runaway, not image size. Most
    # images finish comfortably inside this, and across a 146-image overnight
    # run one runaway costs ten minutes -- but a handful of dense charts
    # (a return-triangle table, many close bars) make the model reason for
    # longer than this before ever writing the answer, hitting the cap with
    # zero content and all of it sitting unfinished in `thinking`. That specific
    # signature gets one retry at NUM_PREDICT_RETRY rather than a permanently
    # higher ceiling, so the common case keeps this budget's speed.
    num_predict: int = 2048
    timeout: float = 600.0
    # The NUM_PREDICT_RETRY retry needs its own, longer ceiling: measured
    # back-to-back on the same real image, one run finished the 8192-budget
    # retry in 422s and another exceeded 600s on it alone (GPU contention,
    # presumably) -- close enough to the base timeout that reusing `timeout`
    # would make the retry itself unreliable on an already-rare path.
    retry_timeout: float = 1200.0
    # Overridable so the review tab can offer a "tune the prompt and try
    # again" loop on a single image without touching the default everyone
    # else's batch uses.
    system_prompt: str = SYSTEM_PROMPT

    @property
    def label(self) -> str:
        return f"{self.model}{' +think' if self.think else ''}"

    def _attempt(self, image_path: Path, context: SlideContext,
                 num_predict: int, timeout: float) -> "_Attempt":
        payload = {
            "model": self.model,
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature,
                        "num_predict": num_predict},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": build_prompt(context),
                    "images": [
                        base64.b64encode(image_path.read_bytes()).decode("ascii")
                    ],
                },
            ],
        }
        # `think` is sent ONLY when enabled -- never as an explicit false.
        # On qwen3-vl:32b, `format` + `think: false` makes the model put its
        # JSON answer in the response's `thinking` field and return an empty
        # `content`, so every image fails with "non-JSON output: ''". Omitting
        # the key entirely produces correct, well-formed output. (It does not
        # even suppress thinking on that model -- `think: false` still
        # returned 1000 characters of it, literal <think> tag included; it
        # only breaks the channel separation.) Measured 2026-08-14 across the
        # whole five-slide bake-off, where it failed all six images on the one
        # model this was meant to run.
        if self.think:
            payload["think"] = True

        started = time.monotonic()
        try:
            request = urllib.request.Request(
                f"{self.host.rstrip('/')}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return _Attempt(elapsed_s=time.monotonic() - started,
                            error=f"Ollama unreachable: {exc}")
        except (TimeoutError, OSError) as exc:
            return _Attempt(elapsed_s=time.monotonic() - started,
                            error=f"Ollama request failed: {exc}")

        elapsed = time.monotonic() - started
        message = body.get("message") or {}
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""
        fields = _parse_response_json(content)
        if fields is None:
            # Belt and braces for the misrouting described above: if `content`
            # didn't parse, the schema-shaped answer may be sitting in
            # `thinking` instead. Cheap to check, and it turns a hard failure
            # into a usable draft on any model with the same quirk.
            fields = _parse_response_json(thinking)
        return _Attempt(elapsed_s=elapsed, fields=fields, content=content,
                        thinking=thinking, done_reason=body.get("done_reason") or "")

    def draft(self, image_path: Path, context: SlideContext) -> DraftResult:
        attempt = self._attempt(image_path, context, self.num_predict, self.timeout)
        if attempt.error:
            return DraftResult(model=self.label, error=attempt.error,
                               elapsed_s=attempt.elapsed_s)

        if (attempt.fields is None and attempt.done_reason == "length"
                and attempt.thinking and not attempt.content):
            # The model hadn't reached its answer yet -- all of it is still
            # sitting unfinished in `thinking` when the token cap cut it off.
            # Measured on chart-eurostoxx-return-triangle.png: at num_predict
            # 2048, done_reason "length", 6646 chars of thinking and zero
            # content; retried at 8192 it finished naturally (done_reason
            # "stop") with a valid answer. One retry at a much larger budget
            # recovers these without raising the ceiling for every image.
            retry = self._attempt(image_path, context, NUM_PREDICT_RETRY,
                                  self.retry_timeout)
            retry.elapsed_s += attempt.elapsed_s
            if retry.error:
                return DraftResult(model=self.label, error=retry.error,
                                   elapsed_s=retry.elapsed_s)
            attempt = retry

        if attempt.fields is None:
            shown = attempt.content or attempt.thinking
            if not shown:
                message = "Model returned an empty response"
            elif self.system_prompt is not SYSTEM_PROMPT:
                # Measured on both qwen3-vl:32b and gemma4:12b: appending even
                # one sentence to the system prompt makes the model abandon
                # the JSON schema and answer in prose. The per-image hint goes
                # in the *user* message and does not have this effect.
                message = (
                    "The model ignored the required JSON output format and "
                    "answered in prose. This is usually caused by editing the "
                    "system prompt -- both local models drop out of structured "
                    "output when it changes. Use the hint field instead, or "
                    "reset the prompt. Raw output: " + repr(shown[:160]))
            else:
                message = f"Model returned non-JSON output: {shown[:200]!r}"
            return DraftResult(model=self.label, elapsed_s=attempt.elapsed_s, error=message)

        fields = attempt.fields
        long_text = (fields.get("long") or "").strip()
        ramp = detect_value_ramp(long_text)
        if ramp:
            long_text = _strip_ramp_table(long_text)

        return DraftResult(
            short=(fields.get("short") or "").strip(),
            long=long_text,
            takeaway=(fields.get("takeaway") or "").strip(),
            role_suggestion=(fields.get("role_suggestion") or "").strip(),
            model=self.label,
            elapsed_s=attempt.elapsed_s,
            suspected_fabrication=ramp,
        )


_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# A fabricated table is a *worse* outcome than no table: a reader cannot tell
# a measured value from a guessed one. See RAMP_WARNING for the failure this
# detects.
RAMP_WARNING = (
    "> ⚠ **The value table this model produced was removed automatically.** "
    "Its numbers rose in near-equal steps, which is the signature of a model "
    "interpolating between axis endpoints rather than measuring each bar. The "
    "labels and ordering above may still be correct; the values were not "
    "trustworthy. Read the figures off the image yourself."
)


def detect_value_ramp(text: str) -> bool:
    """True when a Markdown table's numbers look interpolated, not measured.

    Measured on this project's own images: asked for the 54 country values on
    slide 4r7's scanned bar charts, qwen3-vl:32b returned the country ordering
    *exactly right* and then every value as a clean arithmetic ramp -- 5, 10,
    15, 20 ... 135, against an actual range of about 3% to 19%. Strengthening
    the prompt against it did not help (a second run produced 17, 20, 22, 25
    ... 120), so this is a capability limit on faint multi-bar scans rather
    than a wording problem, and it needs catching in code.

    Deliberately conservative -- at least 8 rows, strictly increasing, and
    step sizes far more uniform than real data. Real ranked financial data is
    almost never this even across that many points, and the cost of a false
    positive is a warning rather than a deletion of the description.
    """
    values: list[float] = []
    for row in _TABLE_ROW_RE.findall(text):
        cells = [c.strip() for c in row.split("|")]
        numbers = [float(n) for cell in cells
                   for n in _NUMBER_RE.findall(cell.replace("~", ""))]
        if numbers:
            values.append(numbers[-1])

    if len(values) < 8:
        return False
    steps = [b - a for a, b in zip(values, values[1:])]
    if not all(step > 0 for step in steps):
        return False
    mean = sum(steps) / len(steps)
    if mean <= 0:
        return False
    spread = (sum((s - mean) ** 2 for s in steps) / len(steps)) ** 0.5
    return (spread / mean) < 0.35


def _strip_ramp_table(text: str) -> str:
    """Remove the table rows, keep the surrounding prose, add the warning."""
    kept = [line for line in text.splitlines()
            if not _TABLE_ROW_RE.match(line)]
    body = "\n".join(kept).strip()
    return f"{body}\n\n{RAMP_WARNING}" if body else RAMP_WARNING


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _parse_response_json(text: str) -> dict | None:
    """Parse a model's structured reply, tolerating a wrapping <think> block.

    Returns None rather than raising, so the caller can try another field.
    """
    text = _THINK_TAG_RE.sub("", text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap the object in prose despite `format`; take the
        # outermost brace-delimited span and try that.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def list_vision_models(host: str = DEFAULT_OLLAMA_HOST) -> list[str]:
    """Vision-capable models Ollama currently has, newest-installed first."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    models = [
        entry for entry in data.get("models", [])
        if "vision" in (entry.get("capabilities") or [])
    ]
    models.sort(key=lambda e: e.get("modified_at", ""), reverse=True)
    return [entry["name"] for entry in models]


def list_all_models(host: str = DEFAULT_OLLAMA_HOST) -> list[str]:
    """Every model Ollama currently has, newest-installed first -- for
    translation's own model picker (2026-08-25): unlike drafting, which
    needs a vision-capable model, translation is text-only and works with
    any installed model, general-purpose chat model or a model
    specifically fine-tuned for machine translation alike (e.g.
    sun_leaf/HY-MT, this project's current default -- confirmed directly
    to follow both a plain "translate this" prompt and the structured
    short_de/long_de/takeaway_de JSON format OllamaTranslationBackend
    actually sends, despite being untagged for "tools"/structured output
    in Ollama's own capability list)."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    models = sorted(data.get("models", []), key=lambda e: e.get("modified_at", ""), reverse=True)
    return [entry["name"] for entry in models]


@dataclass
class InstalledModel:
    name: str
    size_bytes: int
    modified_at: str


def list_installed_models_detailed(host: str = DEFAULT_OLLAMA_HOST) -> list[InstalledModel]:
    """Every model Ollama currently has, with its on-disk size -- for the
    Settings dialog's own "Ollama models" tab (2026-08-25), where knowing
    how much space each one takes matters more than for the plain
    name-only pickers (list_vision_models()/list_all_models() above)."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    models = sorted(data.get("models", []), key=lambda e: e.get("modified_at", ""), reverse=True)
    return [
        InstalledModel(
            name=entry["name"],
            size_bytes=entry.get("size", 0),
            modified_at=entry.get("modified_at", ""),
        )
        for entry in models
    ]


def delete_model(model: str, host: str = DEFAULT_OLLAMA_HOST) -> tuple[bool, str]:
    """Deletes `model` from the local Ollama server via its own
    DELETE /api/delete -- this removes the model's actual files from
    disk (Ollama's own model store, typically several GB each), not just
    something this app was tracking; there is nothing else to clean up on
    this side. Returns (True, "") on success, (False, error message)
    otherwise -- never raises, same contract as the list_*() functions
    above.

    Safe to call on a model that shares underlying blob files with another
    installed model (e.g. one created from it via `ollama create`) --
    confirmed by research, not assumed, 2026-08-25: this is the exact same
    endpoint the `ollama rm` CLI itself calls, and Ollama's own
    content-addressable blob store does reference counting server-side --
    a model's manifest is removed, and a blob is only actually deleted
    once no other remaining manifest references it. Nothing on this
    client side touches blob files directly, so there is no way for this
    function to bypass that. The real, well-documented danger case is
    someone manually deleting files under Ollama's own blobs/ directory,
    which is not what this does."""
    try:
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/delete",
            data=json.dumps({"model": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        return True, ""
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error") or str(exc)
        except (json.JSONDecodeError, OSError):
            message = str(exc)
        return False, message
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


# Custom models this machine builds via `ollama create <name> -f
# <modelfile>` -- FROM some pulled base model plus PARAMETER num_ctx/
# temperature overrides (see d:\dokumente\ai\modelfile_*.txt). Once created,
# Ollama's own /api/show only ever returns the resolved *local blob path*
# for a model's FROM line, never the original base tag it was built from --
# confirmed directly, 2026-09-18 -- so there is no way to rediscover this
# relationship from the Ollama server itself. This mapping is this app's own
# record of it, kept by hand; update_model() below uses it so "Update
# selected…" pulls and relinks to the real underlying base model instead of
# trying (and failing) to pull a tag that was never in any registry.
# Extend this whenever a new custom model is created this way.
DERIVED_MODEL_BASES: dict[str, str] = {
    "Claude_Gemma4_32k:latest": "gemma4",
    "gemma4:64k": "gemma4",
    "gemma4_12b_32k:latest": "gemma4:12b",
    "gemma4:_26b_32k": "gemma4:26b",
    "Claude-qwen3-coder-next:64k": "qwen3-coder-next",
    "qwen3-coder-next:32k": "qwen3-coder-next",
    "qwen3-coder-next:128k": "qwen3-coder-next",
    "qwen3.6:64k": "qwen3.6",
    "qwen3.6:jbef": "qwen3.6:35b",
}


def pull_model(model: str, host: str = DEFAULT_OLLAMA_HOST,
                on_progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Re-downloads `model` from the Ollama registry via POST /api/pull
    (stream=True) -- an already-up-to-date model just returns "success"
    quickly rather than wasting bandwidth, same as the `ollama pull` CLI.
    Calls on_progress(line) for each streamed NDJSON status update (layer
    download percentage, "verifying sha256 digest", etc.) so a caller can
    show live progress instead of a frozen UI for what can be a many-GB,
    many-minute download. Returns (True, "") on success, (False, error)
    otherwise -- never raises, same contract as delete_model() above."""
    try:
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/pull",
            data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1800) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in event:
                    return False, event["error"]
                status = event.get("status", "")
                if on_progress and status:
                    total = event.get("total")
                    completed = event.get("completed")
                    if total and completed:
                        on_progress(f"{model}: {status} ({completed / total * 100:.0f}%)")
                    else:
                        on_progress(f"{model}: {status}")
        return True, ""
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error") or str(exc)
        except (json.JSONDecodeError, OSError):
            message = str(exc)
        return False, message
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def get_modelfile(model: str, host: str = DEFAULT_OLLAMA_HOST) -> str | None:
    """Returns `model`'s current Modelfile text via POST /api/show, or None
    if the model doesn't exist or the server isn't reachable. Used by
    relink_derived_model() below to preserve a custom model's own
    PARAMETER/SYSTEM lines exactly as they currently are -- only its FROM
    line needs to change, to point at a freshly-pulled base instead of a
    now-stale local blob."""
    try:
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/show",
            data=json.dumps({"model": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("modelfile")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _strip_modelfile_comments(modelfile: str) -> list[str]:
    """Drops Ollama's own auto-generated leading "#" comment lines and
    blank separator lines from a `ollama show --modelfile`-style Modelfile
    -- but only outside a multi-line triple-quoted field (SYSTEM/TEMPLATE/
    LICENSE all use this). Blank lines and stray "#" characters *inside*
    one of those are real content (confirmed directly, 2026-09-18: the
    qwen3.6:jbef custom model's inherited LICENSE field is the Apache 2.0
    text, which has blank lines throughout) and must survive untouched, or
    the model re-created from this would silently carry a mangled
    SYSTEM/LICENSE/etc. compared to the one it's replacing."""
    kept: list[str] = []
    in_block = False
    for line in modelfile.splitlines():
        if not in_block and (not line.strip() or line.lstrip().startswith("#")):
            continue
        kept.append(line)
        if line.count('"""') % 2 == 1:
            in_block = not in_block
    return kept


def relink_derived_model(model: str, base: str, host: str = DEFAULT_OLLAMA_HOST) -> tuple[bool, str]:
    """Re-creates `model` (one of DERIVED_MODEL_BASES) against `base`'s
    current weights: reads model's own live Modelfile, drops Ollama's
    auto-generated "#" comment lines and its literal (now-stale) "FROM
    <local-blob-path>" line, replaces that with "FROM <base>", and POSTs
    the result to /api/create. Every PARAMETER/SYSTEM/etc. line is kept
    exactly as the model currently has it -- this only changes which
    weights the tag points at, never its configuration. Returns (True, "")
    on success, (False, error) otherwise, same contract as delete_model()."""
    modelfile = get_modelfile(model, host=host)
    if modelfile is None:
        return False, f"Could not read {model}'s current Modelfile"
    kept_lines = _strip_modelfile_comments(modelfile)
    new_lines: list[str] = []
    replaced = False
    for line in kept_lines:
        if not replaced and line.startswith("FROM "):
            new_lines.append(f"FROM {base}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        return False, f"{model}'s Modelfile has no FROM line"
    try:
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/create",
            data=json.dumps({
                "model": model,
                "modelfile": "\n".join(new_lines),
                "stream": False,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
        return True, ""
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error") or str(exc)
        except (json.JSONDecodeError, OSError):
            message = str(exc)
        return False, message
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def update_model(model: str, host: str = DEFAULT_OLLAMA_HOST,
                  on_progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """"Update" for the Settings dialog's "Update selected…" button: pulls
    `model` itself if it's a plain/base model, or -- if it's one of this
    project's own custom models (DERIVED_MODEL_BASES) -- pulls its base
    instead and relinks `model` to those refreshed weights
    (relink_derived_model() above), since a custom model has no registry
    entry of its own to pull directly."""
    base = DERIVED_MODEL_BASES.get(model)
    if base is None:
        return pull_model(model, host=host, on_progress=on_progress)
    ok, error = pull_model(base, host=host, on_progress=on_progress)
    if not ok:
        return False, f"Pulling base {base} failed: {error}"
    if on_progress:
        on_progress(f"{model}: relinking to updated {base}")
    return relink_derived_model(model, base, host=host)


# --------------------------------------------------------------------------
# Drafting: per image, not per slide
# --------------------------------------------------------------------------
#
# An image used on several slides only needs describing once (checked
# directly against the real repo 2026-08-14: of the images used on more
# than one slide, only two had any drafted text at all, and in both cases
# only one of the two slides had it -- see alt_images.py's own docstring).
# The queue below is keyed by unique image, not by (slide, image) pair, so
# a shared image is drafted once regardless of how many slides show it.

@dataclass
class ImageJob:
    """One image queued for drafting, plus which slide's context to use."""

    image: str
    resolved: Path
    slide_id: str
    slide_path: Path


def draftable_images(row: alt_blocks.SlideRow,
                     entries: dict[str, "alt_images.ImageEntry"]) -> list[tuple[str, Path]]:
    """(reference, resolved path) for one slide's images worth sending to a
    model. Skips decorative ones (nothing to describe) and any format
    neither Ollama's vision path nor _resolve_describable()'s .pdf
    rendering can turn into something it can read. Used by the bake-off,
    which stays per-slide since it's explicitly comparing models on chosen
    slides, not running the real batch."""
    out: list[tuple[str, Path]] = []
    for reference in row.images:
        entry = alt_images.lookup(entries, reference)
        if entry is not None and entry.is_decorative:
            continue
        describable = _resolve_for_drafting(reference)
        if describable is None:
            continue
        out.append((reference, describable))
    return out


def apply_one_draft(image: str, result: DraftResult, model_label: str) -> bool:
    """Write one image's draft into the shared store as unreviewed. True if
    written.

    Goes through alt_images.update_store() for the whole load-check-save
    round trip, so a concurrent write (the review tab's own save, running on
    the GUI thread while this runs on the batch's background thread) can
    never interleave with it and silently lose either side's change.

    Refuses to overwrite a *reviewed* entry -- the state is re-checked here,
    against a freshly reloaded store, not against whatever the queue looked
    like when the batch started: this is what makes marking an image
    reviewed *during* a running batch (hours long, unattended) safe.
    `role_suggestion` is recorded nowhere -- a model must not silently mark
    an image decorative, because that removes it from both the PDF and the
    transcript with no visible trace. It is surfaced in the review tab for a
    human to act on instead.
    """
    if not result.ok:
        return False

    def mutate(entries: dict[str, "alt_images.ImageEntry"]) -> bool:
        entry = entries.get(image)
        if entry is None or entry.status == alt_images.STATUS_REVIEWED:
            return False
        entry.short = result.short
        entry.long = result.long
        if result.takeaway:
            entry.takeaway_default = result.takeaway
        entry.drafted_by = model_label
        return True

    return alt_images.update_store(mutate)


def images_needing_drafts(
    *,
    redraft: bool = False,
    redraft_unless_model: str = "",
    slide_ids: list[str] | None = None,
) -> list[ImageJob]:
    """The batch queue, derived from the store and the slide files rather
    than kept anywhere of its own.

    That is what makes the batch resumable across sessions for free: stop
    it, close the app, come back tomorrow, and the queue recomputes to
    exactly what is still outstanding. There is no job state to persist or
    corrupt.

    `redraft_unless_model` is the model-switch case: include images whose
    existing draft came from a *different* model, leaving alone the ones
    the current model already did.

    An undescribed image can have `has_content` true for a reason other
    than real text -- a role toggle alone counts, same as the old
    AltImage.has_content did -- so this splits on whether there is any
    actual short/long text, not just on `has_content`:

    - No description text (role-only, or genuinely empty) -- nothing to
      lose, so always draftable.
    - Real description text with a *recorded* different model -- the
      intended case; offered under `redraft_unless_model`.
    - Real description text with *no* recorded model -- unknown provenance,
      possibly hand-written. Protected the same as "same model": excluded
      unless the caller passes the blanket `redraft=True`.
    """
    wanted = {sid.lower() for sid in slide_ids} if slide_ids else None
    entries = alt_images.load_store()
    rows = alt_blocks.scan_slides_raw()
    row_by_id = {row.slide_id: row for row in rows}

    queue: list[ImageJob] = []
    for image in sorted(entries):
        entry = entries[image]
        if entry.status == alt_images.STATUS_REVIEWED or entry.is_decorative:
            continue
        describable = _resolve_for_drafting(image)
        if describable is None:
            continue
        if not entry.used_on:
            continue  # nothing currently references it

        candidates = sorted(sid for sid in entry.used_on if sid in row_by_id)
        if wanted is not None:
            candidates = [sid for sid in candidates if sid.lower() in wanted]
        if not candidates:
            continue

        has_description = bool(entry.short or entry.long)
        if has_description:
            if redraft_unless_model:
                if not entry.drafted_by or entry.drafted_by == redraft_unless_model:
                    continue
            elif not redraft:
                continue
        # else: no description text yet -- draftable regardless of
        # redraft/redraft_unless_model.

        slide_id = candidates[0]
        queue.append(ImageJob(image=image, resolved=describable,
                              slide_id=slide_id, slide_path=row_by_id[slide_id].path))
    return queue


@dataclass
class BatchSummary:
    attempted: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0
    fabrications: int = 0
    # Skipped because the image was reviewed (or vanished from the store)
    # after the queue was built -- i.e. the user reviewed it by hand while
    # the batch was running.
    skipped_changed: int = 0
    seconds: float = 0.0
    stopped_early: bool = False
    errors: list[str] = field(default_factory=list)


def run_batch(
    queue: list[ImageJob],
    backend: DraftBackend,
    *,
    on_progress=None,
    on_slide_done=None,
    should_stop=None,
) -> BatchSummary:
    """Draft every image in `queue`, writing each one as it completes.

    Written per image rather than at the end on purpose: a run over 100+
    images takes hours, and anything that dies, is stopped, or loses power
    partway should leave every image it finished already on disk.
    """
    summary = BatchSummary()
    started = time.monotonic()

    for index, job in enumerate(queue, start=1):
        if should_stop is not None and should_stop():
            summary.stopped_early = True
            break
        if on_progress is not None:
            on_progress(index, len(queue), job)

        summary.attempted += 1
        try:
            context = build_context(job.slide_path, job.image)
            result = backend.draft(job.resolved, context)
        except Exception as exc:                     # never kill the batch
            summary.failed += 1
            summary.errors.append(f"{job.image}: {exc}")
            continue

        if not result.ok:
            summary.errors.append(f"{job.image}: {result.error}")
        elif result.suspected_fabrication:
            summary.fabrications += 1
            summary.errors.append(
                f"{job.image}: value table removed — the numbers looked "
                f"interpolated, not measured")

        written = apply_one_draft(job.image, result, backend.label)
        if written:
            summary.written += 1
        elif result.ok:
            # The draft itself succeeded; it just wasn't applied -- the only
            # way that happens is the entry became reviewed (or disappeared)
            # since the queue was built.
            summary.skipped += 1
            summary.skipped_changed += 1
            summary.errors.append(
                f"{job.image}: skipped - you reviewed it while the batch "
                f"was running, so the draft was not written over it")
        else:
            summary.skipped += 1

        # Report per image, not just at the end: a run over 100+ images
        # takes hours, and the review list has to become usable as it goes.
        if on_slide_done is not None:
            on_slide_done(job.image, written)

    summary.seconds = time.monotonic() - started
    return summary


# --------------------------------------------------------------------------
# German translation (2026-08-24)
# --------------------------------------------------------------------------
# Per the confirmed multi-language design (LANGUAGE_NOTES.md): German alt
# text is produced by translating the *finalized* English short/long/
# takeaway_default text, not by an independent vision-model draft against
# the image -- cheaper, and keeps the two languages semantically aligned.
# This reuses the DraftBackend-style pluggable-seam pattern above (a plain
# Protocol + one Ollama implementation), but the backend here is
# text-only: no image, no vision model needed -- so any installed Ollama
# model works (list_all_models(), not list_vision_models()), general
# chat model or a model fine-tuned specifically for machine translation
# alike.
#
# Default model, changeable via the Images tab's own "Translation model:"
# picker (2026-08-25, direct instruction): sun_leaf/HY-MT (Tencent
# Hunyuan-MT, 7B) -- a dedicated MT model, not a general instruction-
# following LLM (Ollama reports its own capabilities as ["completion"]
# only, no "tools"). Both translation-model combos (qt_transcript_tab.py's
# own, and qt_duplicate_slide_dialog.py's auto-translate option) now
# remember the user's last pick in app_settings.json's "translation_model"
# key -- this constant is still needed underneath that as the very first
# preselection on a fresh install (nothing remembered yet), and as the
# fallback if the remembered model is no longer installed here.
DEFAULT_TRANSLATION_MODEL = "sun_leaf/HY-MT:7b"

# Three separate, simple per-field calls -- NOT one combined call asking
# for short/long/takeaway together as structured JSON (tried first,
# reverted 2026-08-25 after direct testing against the real store, not
# just a short hand-written example: a dedicated MT model like HY-MT is
# fine-tuned on plain "translate this text" pairs, not on multi-paragraph
# instructions or multi-field JSON output. Ollama's own `format` option
# grammar-constrains token generation regardless of the model, so it
# *can* force syntactically valid JSON -- but the combined approach was
# empirically unreliable on real (longer) description text: the exact
# same "long" field that translated perfectly as a single plain-text call
# came back as three empty strings under the JSON-schema version on a
# same-settings re-run. The per-field approach below was verified
# directly against real store content, including a real Markdown table
# (numbers and structure preserved exactly, only prose/headers
# translated, even correctly localizing "0.2" to "0,2"), and is also a
# safe default for a general-purpose LLM (any model capable of following
# instructions can certainly follow "translate this text").
#
# The actual prompt text sent is resolved per (model, source_lang,
# target_lang) via translation_prompts.get_effective_prompt() (2026-08-25,
# direct instruction: a user-editable *default* prompt, not just per-model
# overrides -- see that module's own docstring for the two-level
# fallback: an exact model+pair match, else the user's own configured
# default, else a hardcoded last-resort for a fresh install). Nothing in
# this module hardcodes prompt wording any more.


@dataclass
class TranslationResult:
    short_de: str = ""
    long_de: str = ""
    takeaway_de: str = ""
    model: str = ""
    elapsed_s: float = 0.0
    error: str | None = None
    # alt_images.en_text_hash() of the entry's EN text at the moment this
    # translation was requested -- "" for a backend that hasn't been ported
    # to set it, which apply_one_translation() then treats as "no staleness
    # check possible, apply anyway" rather than refusing every result
    # outright (2026-09-28, porting SlideMage upstream commit 34cdbd7).
    source_hash: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.long_de)


class TranslationBackend(Protocol):
    label: str

    def translate(self, entry: "alt_images.ImageEntry") -> TranslationResult: ...


@dataclass
class OllamaTranslationBackend:
    """Text-only sibling of OllamaBackend above -- no image, no vision
    model required (a smaller/cheaper text model, or one fine-tuned
    specifically for translation, is a perfectly reasonable choice here).
    Issues up to three separate calls per image (short/long/takeaway),
    each a single "translate this text" turn -- see the module-level
    comment above for why this is simpler than, and more reliable than,
    one combined structured-output call.

    Every call's prompt comes from
    translation_prompts.get_effective_prompt(model, source_lang,
    target_lang) (2026-08-25, direct instruction -- see that module and
    the Settings dialog): an exact model+pair match if the user
    configured one, else their own general default prompt, else a
    hardcoded last-resort for a fresh install. Always sent as a single
    combined message (no separate system-role turn) -- some models tested
    here respond far more reliably to one self-contained instruction+text
    block than to a system/user split."""

    model: str
    host: str = DEFAULT_OLLAMA_HOST
    num_ctx: int = 8192
    think: bool = False
    temperature: float = 0.2
    num_predict: int = 2048
    timeout: float = 300.0
    source_lang: str = "en"
    target_lang: str = "de"

    @property
    def label(self) -> str:
        return f"{self.model}{' +think' if self.think else ''}"

    def _translate_one(self, text: str) -> tuple[str, Optional[str]]:
        """(translated text, error) for one field's own text -- "" (no
        error) straight through for empty input, since there is nothing
        to send the model and an empty field should just stay empty."""
        if not text.strip():
            return "", None

        config = translation_prompts.get_effective_prompt(
            self.model, self.source_lang, self.target_lang)
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature,
                        "num_predict": self.num_predict},
            "messages": [{"role": "user", "content": config.build_message(text)}],
        }
        # Same reasoning as OllamaBackend._attempt above: never send `think`
        # as an explicit false.
        if self.think:
            payload["think"] = True
        try:
            request = urllib.request.Request(
                f"{self.host.rstrip('/')}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            return "", f"Ollama unreachable: {exc}"
        except (TimeoutError, OSError) as exc:
            return "", f"Ollama request failed: {exc}"

        message = body.get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            thinking = (message.get("thinking") or "").strip()
            content = _THINK_TAG_RE.sub("", thinking).strip()
        if not content:
            return "", "Model returned an empty response"
        return content, None

    def translate_text(self, text: str) -> tuple[str, Optional[str]]:
        """Public entry point for translating an arbitrary block of text --
        not tied to alt_images.ImageEntry's short/long/takeaway shape.
        Thin wrapper around _translate_one(), which already does exactly
        this; used by qt_duplicate_slide_dialog.py's own "auto-translate
        the slide body" option (2026-08-25) to translate a whole slide's
        raw LaTeX body as one block. Experimental in that use -- a
        dedicated MT model has no notion of LaTeX syntax, so a command's
        argument text can come back altered along with the prose around
        it; reviewing the result before saving is the caller's job, not
        this method's."""
        return self._translate_one(text)

    def translate(self, entry: "alt_images.ImageEntry") -> TranslationResult:
        started = time.monotonic()
        # Captured from the exact entry snapshot handed to this call, before
        # any of the (potentially slow) network round-trips below -- so a
        # later apply_one_translation() can tell whether the store's EN text
        # is still the same text this translation was actually produced
        # from (2026-09-28, porting SlideMage upstream commit 34cdbd7).
        source_hash = alt_images.en_text_hash(entry)
        short_de, short_err = self._translate_one(entry.short)
        long_de, long_err = self._translate_one(entry.long)
        takeaway_de, takeaway_err = self._translate_one(entry.takeaway_default)
        elapsed = time.monotonic() - started

        # TranslationResult.ok only actually gates on long_de being
        # non-empty -- images_needing_translation() is what keeps an
        # image with no real EN `long` text (nothing to translate at all)
        # out of the queue in the first place, so that case shouldn't
        # reach here. error is purely informational: report every field
        # that genuinely failed, not just long's.
        errors = [e for e in (short_err, long_err, takeaway_err) if e]
        return TranslationResult(
            short_de=short_de, long_de=long_de, takeaway_de=takeaway_de,
            model=self.label, elapsed_s=elapsed,
            error="; ".join(errors) if errors else None,
            source_hash=source_hash,
        )


def apply_one_translation(image: str, result: TranslationResult, model_label: str) -> bool:
    """Write one image's German translation into the shared store. True if
    written. Mirrors apply_one_draft()'s update_store()-based atomicity,
    but refuses only when the *English* text has moved on since `result`
    was produced (translated_from_hash mismatch) rather than checking a
    reviewed flag -- there is no separate "German reviewed" gate to
    respect here, translation_state() derives staleness purely from the
    hash."""
    if not result.ok:
        return False

    def mutate(entries: dict[str, "alt_images.ImageEntry"]) -> bool:
        entry = entries.get(image)
        if entry is None:
            return False
        current_hash = alt_images.en_text_hash(entry)
        # The queue this came from was built against some earlier snapshot
        # of the store; re-check freshness now, the same "never trust the
        # queue's own age" caution apply_one_draft() already applies to its
        # reviewed-status check. Unlike that computation above suggests on
        # its own, computing current_hash was never enough by itself --
        # this refuses the write outright (rather than only stamping
        # translated_from_hash with whatever current_hash turns out to be)
        # when the EN text result was actually translated from no longer
        # matches what's in the store right now, e.g. someone edited the
        # EN short/long/takeaway text in the time between this translation
        # being queued and it finishing (2026-09-28, porting SlideMage
        # upstream commit 34cdbd7). A blank result.source_hash (a backend
        # that predates this field) skips the check rather than refusing
        # every result unconditionally.
        if result.source_hash and result.source_hash != current_hash:
            return False
        entry.short_de = result.short_de
        entry.long_de = result.long_de
        if result.takeaway_de:
            entry.takeaway_default_de = result.takeaway_de
        entry.translated_from_hash = current_hash
        return True

    return alt_images.update_store(mutate)


def images_needing_translation() -> list[str]:
    """Every image reference (store key) whose German text is missing or
    stale relative to its current English text -- the translation
    counterpart to images_needing_drafts(). Derived fresh from the store
    every call, same resumable-with-no-persisted-state design.

    Deliberately checks `entry.short or entry.long`, not `entry.has_content`
    -- has_content also counts a decorative image with no text at all
    (role alone is "content" for the drafting/review-state machinery,
    which cares whether a role *decision* was made), but a decorative
    image with empty short/long has nothing to translate, and was
    confirmed directly to reach the backend as a real (if harmless)
    failure -- an empty request that can never produce a non-empty
    long_de, so TranslationResult.ok is false and it shows up as a
    spurious "failed" line in every batch summary."""
    entries = alt_images.load_store()
    return [
        image for image, entry in sorted(entries.items())
        if (entry.short or entry.long)
        and alt_images.translation_state(entry) != alt_images.STATE_REVIEWED
    ]


@dataclass
class TranslationBatchSummary:
    attempted: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0
    seconds: float = 0.0
    stopped_early: bool = False
    errors: list[str] = field(default_factory=list)


def run_translation_batch(
    queue: list[str],
    backend: TranslationBackend,
    *,
    on_progress=None,
    on_image_done=None,
    should_stop=None,
) -> TranslationBatchSummary:
    """Translate every image in `queue`, writing each one as it completes
    -- same per-image-write, same should_stop cooperative-cancel shape as
    run_batch() above, for the same reason (a run over the whole store can
    take a while, and a stop/crash partway through should keep whatever
    finished)."""
    summary = TranslationBatchSummary()
    started = time.monotonic()
    entries = alt_images.load_store()

    for index, image in enumerate(queue, start=1):
        if should_stop is not None and should_stop():
            summary.stopped_early = True
            break
        if on_progress is not None:
            on_progress(index, len(queue), image)

        entry = entries.get(image)
        if entry is None:
            summary.skipped += 1
            continue

        summary.attempted += 1
        try:
            result = backend.translate(entry)
        except Exception as exc:                      # never kill the batch
            summary.failed += 1
            summary.errors.append(f"{image}: {exc}")
            continue

        if not result.ok:
            summary.errors.append(f"{image}: {result.error}")

        written = apply_one_translation(image, result, backend.label)
        if written:
            summary.written += 1
        else:
            summary.skipped += 1

        if on_image_done is not None:
            on_image_done(image, written)

    summary.seconds = time.monotonic() - started
    return summary


# --------------------------------------------------------------------------
# Bake-off
# --------------------------------------------------------------------------

@dataclass
class BakeOffRow:
    slide_id: str
    title: str
    reference: str
    results: dict[str, DraftResult] = field(default_factory=dict)


def bake_off(slide_ids: list[str], backends: list[DraftBackend],
             on_progress=None) -> list[BakeOffRow]:
    """Run several backends over the same images so they can be compared.

    Deliberately a separate entry point from the batch pass: the model is
    chosen once, on evidence, by reading its output next to the actual
    chart -- not by benchmark scores from elsewhere on the internet, which
    say nothing about *these* images.
    """
    entries = alt_images.load_store()
    wanted = {sid.lower() for sid in slide_ids}

    targets: list[tuple[BakeOffRow, Path, SlideContext]] = []
    for row in alt_blocks.scan_slides_raw():
        if row.slide_id.lower() not in wanted:
            continue
        for reference, resolved in draftable_images(row, entries):
            targets.append((
                BakeOffRow(slide_id=row.slide_id, title=row.title,
                           reference=reference),
                resolved,
                build_context(row.path, reference),
            ))

    # Model outer, image inner -- deliberately. The other nesting reads more
    # naturally but makes Ollama evict and reload the model between every
    # single image: six images across three models would be 18 loads of a
    # 21 GB model rather than 3, and the reload dominates the actual work.
    total = len(backends) * len(targets)
    done = 0
    for backend in backends:
        for row, resolved, context in targets:
            done += 1
            if on_progress is not None:
                on_progress(done, total, backend.label, row.reference)
            row.results[backend.label] = backend.draft(resolved, context)

    return [row for row, _resolved, _context in targets]


def render_bake_off(rows: list[BakeOffRow]) -> str:
    """Markdown comparison, one section per image, one block per model."""
    out: list[str] = ["# Vision-model bake-off", ""]
    out.append("Each image below is described by every model tested. Read each "
               "description **against the actual image** — the thing that "
               "matters is whether the numbers are right, not whether the prose "
               "reads well.")
    out.append("")

    for row in rows:
        out.append(f"## {row.slide_id} — {row.title}")
        out.append("")
        out.append(f"`{row.reference}`")
        out.append("")
        for label, result in row.results.items():
            out.append(f"### {label}")
            out.append("")
            if not result.ok:
                out.append(f"**FAILED** after {result.elapsed_s:.1f}s: "
                           f"{result.error}")
                out.append("")
                continue
            out.append(f"*{result.elapsed_s:.1f}s · suggested role: "
                       f"{result.role_suggestion or 'n/a'}*")
            out.append("")
            out.append(f"**Short.** {result.short}")
            out.append("")
            out.append("**Long.**")
            out.append("")
            out.append(result.long)
            out.append("")
            out.append(f"**Takeaway.** {result.takeaway}")
            out.append("")
        out.append("---")
        out.append("")

    timings: dict[str, list[float]] = {}
    for row in rows:
        for label, result in row.results.items():
            timings.setdefault(label, []).append(result.elapsed_s)
    if timings:
        out.append("## Timing")
        out.append("")
        out.append("| Model | Images | Mean s | Est. for 200 images |")
        out.append("|---|---:|---:|---|")
        for label, values in timings.items():
            mean = sum(values) / len(values)
            hours = mean * 200 / 3600
            out.append(f"| {label} | {len(values)} | {mean:.1f} | {hours:.1f} h |")
        out.append("")
    return "\n".join(out)


def write_bake_off(rows: list[BakeOffRow], destination: Path | None = None) -> Path:
    target = destination or (PROJECT_ROOT / "alt-text-bakeoff.md")
    target.write_text(render_bake_off(rows), encoding="utf-8")
    return target
