"""Managing the local Ollama model store from Settings: delete, update
(pull), and relink a custom model to its refreshed base (moved here from
alt_draft.py in the 2026-10-09 AI provider layer, unchanged: these are
Ollama-only administration calls, not chat, so they have no cloud
counterpart and stay out of ChatProvider)."""
from __future__ import annotations

import ast
import http.client
import json
import math
import re
import urllib.error
import urllib.request
from typing import Callable, Optional

from .. import app_settings

# What a call to the server can raise besides a refusal: no connection, a timeout (OSError), a cut-off or
# malformed reply (HTTPException), a reply that is not UTF-8 text or JSON (ValueError).
_CALL_ERRORS = (OSError, http.client.HTTPException, ValueError)


def _open(host: str, path: str, payload: dict, timeout: float, method: str = "POST"):
    """The open response of `method path` on the server at `host` with a JSON body (a context manager)."""
    request = urllib.request.Request(
        f"{host.rstrip('/')}{path}", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method=method)
    return urllib.request.urlopen(request, timeout=timeout)


def _failure(exc: Exception) -> str:
    """The text to show for a failed call: the server's own message when it sent one."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8"))
            if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"]:
                return body["error"]
        except _CALL_ERRORS:
            pass
    return str(exc) or type(exc).__name__


def _simple_call(host: str, path: str, payload: dict, timeout: float, method: str = "POST") -> tuple[bool, str]:
    """Run a call whose answer does not matter: (True, "") or (False, why) -- never raises."""
    try:
        with _open(host, path, payload, timeout, method) as response:
            response.read()
        return True, ""
    except _CALL_ERRORS as exc:
        return False, _failure(exc)


def delete_model(model: str, host: Optional[str] = None) -> tuple[bool, str]:
    """Deletes `model` from the local Ollama server via its own
    DELETE /api/delete -- this removes the model's actual files from
    disk (Ollama's own model store, typically several GB each), not just
    something this app was tracking; there is nothing else to clean up on
    this side. Returns (True, "") on success, (False, error message)
    otherwise -- never raises.

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
    return _simple_call(host or app_settings.get_ollama_host(), "/api/delete", {"model": model}, 30, "DELETE")


# Custom models built with `ollama create <name> -f <modelfile>` -- FROM some
# pulled base model plus PARAMETER num_ctx/temperature overrides -- have no
# registry entry of their own, so pulling them fails ("pull model manifest:
# file does not exist"). Ollama records the base they were built from in
# /api/show's details.parent_model, so update_model() below finds the base
# there (v5.35.3, direct report: four custom models failed to update; this
# replaces a hand-kept name -> base table that listed only some of them,
# partly under misspelt names). parent_model is not proof of a custom model
# on its own: some registry models carry one too (gemma4:latest names its
# upstream build), so it is only consulted after the registry has said the
# model does not exist.
_NOT_IN_REGISTRY_RE = re.compile(r"does not exist|not found|manifest unknown", re.IGNORECASE)
_WEIGHTS_BLOB_RE = re.compile(r"^FROM\s+.*?(sha256[-:][0-9a-f]{64})", re.MULTILINE)


def parent_model(model: str, host: Optional[str] = None) -> str | None:
    """The model `model` was built from (/api/show details.parent_model),
    or None if Ollama records none or can't be reached."""
    show = _get_model_show(model, host=host)
    details = show.get("details") if show is not None else None
    parent = details.get("parent_model") if isinstance(details, dict) else None
    return parent if isinstance(parent, str) and parent.strip() else None


def _weights_blob(model: str, host: Optional[str] = None) -> str | None:
    """The digest of `model`'s weights -- the blob its Modelfile's first
    FROM line points to -- or None if unknown."""
    m = _WEIGHTS_BLOB_RE.search(get_modelfile(model, host=host) or "")
    return m.group(1).replace(":", "-") if m else None


def pull_model(model: str, host: Optional[str] = None,
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
        with _open(host or app_settings.get_ollama_host(), "/api/pull", {"model": model, "stream": True}, 1800) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if "error" in event:
                    return False, str(event["error"])
                status = event.get("status", "")
                if on_progress and status:
                    total, completed = event.get("total"), event.get("completed")
                    if (isinstance(total, (int, float)) and isinstance(completed, (int, float))
                            and total and completed):
                        on_progress(f"{model}: {status} ({completed / total * 100:.0f}%)")
                    else:
                        on_progress(f"{model}: {status}")
        return True, ""
    except _CALL_ERRORS as exc:
        return False, _failure(exc)


def _get_model_show(model: str, host: Optional[str] = None) -> dict | None:
    """Returns Ollama's structured `/api/show` response, or None if the
    model doesn't exist, the server isn't reachable, or it returns invalid
    JSON. Keeping this response lets callers preserve model configuration
    through APIs that no longer accept a Modelfile string."""
    try:
        with _open(host or app_settings.get_ollama_host(), "/api/show", {"model": model}, 30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except _CALL_ERRORS:
        return None


def get_modelfile(model: str, host: Optional[str] = None) -> str | None:
    """Returns `model`'s current Modelfile text via POST /api/show, or None
    if the model doesn't exist or the server isn't reachable. Kept for
    callers that still need the display/export form; model relinking uses
    `/api/show`'s structured fields instead of sending this text back to
    `/api/create`."""
    data = _get_model_show(model, host=host)
    modelfile = data.get("modelfile") if data is not None else None
    return modelfile if isinstance(modelfile, str) else None


_FLOAT_PARAMETER_RE = re.compile(
    r"[+-]?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|"
    r"\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+)\Z"
)


def _parse_parameter_value(value: str) -> bool | int | float | str:
    """Convert one formatted `/api/show` parameter value into JSON's
    corresponding scalar type without treating zero or false as absent."""
    lowered = value.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if _FLOAT_PARAMETER_RE.fullmatch(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"non-finite numeric value {value!r}")
        return number
    if lowered in {"nan", "+nan", "-nan", "inf", "+inf", "-inf",
                   "infinity", "+infinity", "-infinity"}:
        raise ValueError(f"non-finite numeric value {value!r}")
    return value


def _parse_show_parameters(parameters: object) -> dict[str, bool | int | float | str | list[str]]:
    """Parse Ollama's formatted `parameters` text into the `/api/create`
    JSON map. `stop` is the one repeatable parameter and becomes a list;
    malformed or ambiguous lines fail instead of silently dropping a
    setting while relinking a model."""
    if parameters is None or parameters == "":
        return {}
    if not isinstance(parameters, str):
        raise ValueError("Ollama returned model parameters in an unsupported format")

    parsed: dict[str, bool | int | float | str | list[str]] = {}
    for line_number, line in enumerate(parameters.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", parts[0]):
            raise ValueError(f"unsupported parameter syntax on line {line_number}")
        name, serialized_value = parts
        is_quoted = serialized_value.startswith('"')
        if is_quoted:
            try:
                raw_value = ast.literal_eval(serialized_value)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"invalid parameter line {line_number}: {exc}") from exc
            if not isinstance(raw_value, str):
                raise ValueError(f"unsupported parameter value on line {line_number}")
        else:
            if any(character.isspace() for character in serialized_value):
                raise ValueError(f"unsupported parameter syntax on line {line_number}")
            raw_value = serialized_value
        if name == "stop":
            parsed.setdefault(name, []).append(raw_value)
        elif name in parsed:
            raise ValueError(f"repeated non-stop parameter {name!r} on line {line_number}")
        else:
            try:
                parsed[name] = raw_value if is_quoted else _parse_parameter_value(raw_value)
            except ValueError as exc:
                raise ValueError(f"invalid parameter {name!r} on line {line_number}: {exc}") from exc
    return parsed


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


def relink_derived_model(model: str, base: str, host: Optional[str] = None) -> tuple[bool, str]:
    """Re-creates custom `model` (built from `base`) against `base`'s
    current weights. Reads Ollama's structured `/api/show` response and
    sends the supported `/api/create` fields, replacing only `from` while
    preserving the model's template, prompts, license, parameters, and
    messages. Returns (True, "") on success, (False, error) otherwise,
    same contract as delete_model()."""
    host = host or app_settings.get_ollama_host()
    show = _get_model_show(model, host=host)
    if show is None:
        return False, f"Could not read {model}'s current model configuration"

    try:
        payload: dict[str, object] = {
            "model": model,
            "from": base,
            "parameters": _parse_show_parameters(show.get("parameters")),
            "stream": False,
        }
        for field_name in (
            "template", "system", "license", "renderer", "parser",
            "messages", "requires",
        ):
            if field_name not in show or show[field_name] is None:
                continue
            value = show[field_name]
            if field_name in {"template", "system", "renderer", "parser", "requires"}:
                if not isinstance(value, str):
                    raise ValueError(f"Ollama returned {field_name} in an unsupported format")
            elif field_name == "license":
                if not isinstance(value, (str, list)) or (
                    isinstance(value, list) and not all(isinstance(item, str) for item in value)
                ):
                    raise ValueError("Ollama returned license in an unsupported format")
            elif field_name == "messages":
                if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                    raise ValueError("Ollama returned messages in an unsupported format")
            payload[field_name] = value
    except ValueError as exc:
        return False, f"Could not preserve {model}'s current configuration: {exc}"

    return _simple_call(host, "/api/create", payload, 120)


def update_model(model: str, host: Optional[str] = None,
                  on_progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """"Update" for the Settings dialog's "Update selected…" button: pulls
    `model` itself; if the registry has no such model, it is a custom model
    (see _NOT_IN_REGISTRY_RE above), so its base (parent_model()) is pulled
    instead and `model` relinked to those refreshed weights
    (relink_derived_model() above) -- unless it already uses them, which
    needs no relink. `host=None` is passed straight through; each helper
    resolves it itself."""
    ok, error = pull_model(model, host=host, on_progress=on_progress)
    if ok or not _NOT_IN_REGISTRY_RE.search(error):
        return ok, error
    base = parent_model(model, host=host)
    if base is None or base == model:
        return False, f"{error} (a custom model, but Ollama does not record the model it was built from)"
    if on_progress:
        on_progress(f"{model}: a custom model built from {base}; updating {base}")
    ok, base_error = pull_model(base, host=host, on_progress=on_progress)
    if not ok:
        return False, f"Pulling base {base} failed: {base_error}"
    current = _weights_blob(model, host=host)
    if current is not None and current == _weights_blob(base, host=host):
        if on_progress:
            on_progress(f"{model}: already uses the current {base}")
        return True, ""
    if on_progress:
        on_progress(f"{model}: relinking to updated {base}")
    return relink_derived_model(model, base, host=host)
