"""Serialize preview raster requests through one reusable child process."""

from __future__ import annotations

import atexit
import base64
import json
import os
import subprocess
import sys
import threading

from .processes import no_console_kwargs

_lock = threading.RLock()
_process = None
REQUEST_TIMEOUT = 15.0
LAYOUT_TIMEOUT = 300.0      # reading the text and drawings of every page of a deck


def close():
    global _process
    with _lock:
        process, _process = _process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()
        finally:
            process.stdout.close()


def render(data, sizes, full_size):
    request = dict(pdf=base64.b64encode(data).decode("ascii"), sizes=sizes, full_size=full_size)
    return tuple(_ask(request, "Cannot prepare preview images", len(sizes))["images"])


def render_sequence(data):
    """Return complete-page raster evidence, never a last-page proxy."""
    from .preview_raster import SEQUENCE_DPI, SEQUENCE_SCHEMA
    import hashlib
    import math

    response = _ask(dict(op="sequence", pdf=base64.b64encode(data).decode("ascii")),
                    "Cannot prepare preview sequence", timeout=LAYOUT_TIMEOUT)
    try:
        configuration = response["configuration"]
        if (configuration.get("schema") != SEQUENCE_SCHEMA
                or configuration.get("dpi") != SEQUENCE_DPI
                or configuration.get("colorspace") != "rgb"
                or configuration.get("alpha") is not False
                or configuration.get("annots") is not True
                or not isinstance(configuration.get("renderer"), str)):
            raise ValueError("Unsupported preview sequence configuration")
        pages = response["pages"]
        if not isinstance(pages, list) or not pages or len(pages) != len(response["images"]):
            raise ValueError("Incomplete preview sequence")
        for page in pages:
            if (not isinstance(page, dict) or set(page) != {"size", "pixels", "sha256"}
                    or len(page["size"]) != 2 or len(page["pixels"]) != 2
                    or any(not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0
                           for n in page["size"])
                    or any(type(n) is not int or n <= 0 for n in page["pixels"])
                    or not isinstance(page["sha256"], str) or len(page["sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in page["sha256"])):
                raise ValueError("Invalid preview sequence page")
        evidence = dict(configuration=configuration, pages=pages)
        signature = hashlib.sha256(json.dumps(evidence, sort_keys=True,
                                  separators=(",", ":")).encode()).hexdigest()
        if response["signature"] != signature:
            raise ValueError("Invalid preview sequence signature")
        return dict(**evidence, signature=signature, images=tuple(response["images"]))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        close()
        raise RuntimeError(f"Cannot prepare preview sequence: {exc}") from exc


def read_document(path, op, start=1, count=1, dpi=110):
    """Ask the child to read a file for the chat (ops of preview_raster.document): the response with
    "count", and "texts" (str) or "images" (PNG bytes). RuntimeError when it cannot."""
    return _ask(dict(op=op, path=str(path), start=start, count=count, dpi=dpi), "Cannot read the file")


def read_layout(path) -> list[dict]:
    """Ask the child for the text lines, images, fills and figures of every page of a PDF
    (readability_pdf.read_pages): the data of readability.Page.from_dict. RuntimeError when it cannot."""
    return _ask(dict(op="layout", path=str(path)), "Cannot read the PDF", timeout=LAYOUT_TIMEOUT)["pages"]


def _ask(request, failure, expected_images=None, timeout=REQUEST_TIMEOUT):
    """Send one JSON request to the child (started or restarted as needed) and return its checked response."""
    global _process
    with _lock:
        if _process is None or _process.poll() is not None:
            close()
            frozen = getattr(sys, "frozen", False)
            command = (
                [sys.executable, "--preview-raster"]
                if frozen
                else [sys.executable, "-m", "slidemage.preview_raster"]
            )
            env = dict(os.environ)
            env["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] = "1"
            env.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            kwargs = no_console_kwargs()
            _process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                **kwargs,
            )
        expired = threading.Event()
        process = _process

        def expire():
            expired.set()
            try:
                process.kill()
            except OSError:
                pass

        # Killing the child unblocks both a full stdin pipe and a stalled read.
        # The timer captures this process, never a later replacement.
        deadline = threading.Timer(timeout, expire)
        deadline.daemon = True
        deadline.start()
        try:
            _process.stdin.write(json.dumps(request) + "\n")
            _process.stdin.flush()
            line = _process.stdout.readline()
            if expired.is_set():
                raise RuntimeError("Preview image request timed out")
            if not line:
                raise RuntimeError("Preview image process exited unexpectedly")
            response = json.loads(line)
            if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
                raise ValueError("Invalid preview image response")
            if not response["ok"]:
                raise RuntimeError(str(response.get("error", "Rasterization failed")))
            encoded = response.get("images")
            if not isinstance(encoded, list) or not all(isinstance(item, str) for item in encoded):
                raise ValueError("Invalid preview image payload")
            images = [base64.b64decode(image, validate=True) for image in encoded]
            if any(not item.startswith(b'\x89PNG\r\n\x1a\n') for item in images):
                raise ValueError("Invalid preview PNG payload")
            if expected_images is not None and len(images) != expected_images:
                raise RuntimeError("Incomplete preview image response")
            response["images"] = images
            return response
        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:  # noqa: F841 -- original error is used when not timed out
            close()
            if expired.is_set():
                exc = RuntimeError("Preview image request timed out")
            raise RuntimeError(f"{failure}: {exc}") from exc
        finally:
            deadline.cancel()


atexit.register(close)
