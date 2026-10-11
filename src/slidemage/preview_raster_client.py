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
        deadline = threading.Timer(REQUEST_TIMEOUT, expire)
        deadline.daemon = True
        deadline.start()
        try:
            _process.stdin.write(
                json.dumps(
                    dict(
                        pdf=base64.b64encode(data).decode("ascii"),
                        sizes=sizes,
                        full_size=full_size,
                    )
                )
                + "\n"
            )
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
            images = tuple(base64.b64decode(image, validate=True) for image in encoded)
            if len(images) != len(sizes):
                raise RuntimeError("Incomplete preview image response")
            if any(not item.startswith(b'\x89PNG\r\n\x1a\n') for item in images):
                raise ValueError("Invalid preview PNG payload")
            return images
        except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:  # noqa: F841 -- original error is used when not timed out
            close()
            if expired.is_set():
                exc = RuntimeError("Preview image request timed out")
            raise RuntimeError(f"Cannot prepare preview images: {exc}") from exc
        finally:
            deadline.cancel()


atexit.register(close)
