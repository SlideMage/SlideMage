"""Serialize preview raster requests through one reusable child process.

The module-level functions use one shared child (the Preview's and the chat's). A `RasterClient` of
its own is a second child with a lock of its own: background rendering (background_renders.py) uses
one so that it never makes a foreground raster wait.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import subprocess
import sys
import threading

from .processes import no_console_kwargs

REQUEST_TIMEOUT = 15.0
LAYOUT_TIMEOUT = 300.0      # reading the text and drawings of every page of a deck


class RasterClient:
    """One raster child process and the lock that serializes requests to it."""

    subprocess = subprocess     # the module, patched by tests through the instance
    REQUEST_TIMEOUT = REQUEST_TIMEOUT

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process = None
        atexit.register(self.close)

    def close(self) -> None:
        with self._lock:
            process, self._process = self._process, None
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

    def render(self, data, sizes, full_size):
        request = dict(pdf=base64.b64encode(data).decode("ascii"), sizes=sizes, full_size=full_size)
        return tuple(self.ask(request, "Cannot prepare preview images", len(sizes))["images"])

    def read_document(self, path, op, start=1, count=1, dpi=110, width=None):
        """Ask the child to read a file for the chat (ops of preview_raster.document): the response with
        "count", and "texts" (str) or "images" (PNG bytes). `width` (op "pdf_images" only) sets the pixel
        width of every page instead of `dpi`. RuntimeError when it cannot."""
        request = dict(op=op, path=str(path), start=start, count=count, dpi=dpi)
        if width is not None:
            request["width"] = width
        return self.ask(request, "Cannot read the file")

    def read_layout(self, path) -> list[dict]:
        """Ask the child for the text lines, images, fills and figures of every page of a PDF
        (readability_pdf.read_pages): the data of readability.Page.from_dict. RuntimeError when it cannot."""
        return self.ask(dict(op="layout", path=str(path)), "Cannot read the PDF", timeout=LAYOUT_TIMEOUT)["pages"]

    def ask(self, request, failure, expected_images=None, timeout=None):
        """Send one JSON request to the child (started or restarted as needed) and return its checked response."""
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self.close()
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
                self._process = subprocess.Popen(
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
            process = self._process

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
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                line = process.stdout.readline()
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
                self.close()
                if expired.is_set():
                    exc = RuntimeError("Preview image request timed out")
                raise RuntimeError(f"{failure}: {exc}") from exc
            finally:
                deadline.cancel()


_shared = RasterClient()


def close():
    _shared.close()


def render(data, sizes, full_size):
    return _shared.render(data, sizes, full_size)


def read_document(path, op, start=1, count=1, dpi=110, width=None):
    return _shared.read_document(path, op, start, count, dpi, width)


def read_layout(path) -> list[dict]:
    return _shared.read_layout(path)


def _ask(request, failure, expected_images=None, timeout=None):
    return _shared.ask(request, failure, expected_images, timeout)
