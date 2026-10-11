"""Private persistent process for preview PDF rasterization.

MuPDF objects stay in this process and never cross a GUI/worker thread boundary.
Requests and results are newline-delimited JSON on private pipes, with PNG bytes
encoded as base64. No GUI or project writes happen here.
"""

from __future__ import annotations

import base64
from contextlib import redirect_stdout
import json
import os
import sys


def raster(data, sizes, full_size):
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if not doc.page_count:
            return []
        page = doc[-1]
        images = {}
        for width, height in sizes:
            size = (width, height)
            if size in images:
                continue
            if (
                height is None
                and width == full_size[0]
                and tuple(full_size) in images
                and abs(
                    page.rect.width / page.rect.height - full_size[0] / full_size[1]
                )
                < 0.0001
            ):
                images[size] = images[tuple(full_size)]
                continue
            zoom = width / page.rect.width
            matrix = pymupdf.Matrix(
                zoom, height / page.rect.height if height is not None else zoom
            )
            images[size] = page.get_pixmap(matrix=matrix).tobytes("png")
        return [images[tuple(size)] for size in sizes]


def _pipe_stream(number, mode):
    """Restore redirected pipes in a Windows windowed executable/pythonw."""
    try:
        descriptor = os.dup(number)
    except OSError:
        if os.name != "nt":
            raise
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        handle = kernel.GetStdHandle(wintypes.DWORD(-10 if number == 0 else -11))
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            raise OSError("Preview image process has no redirected pipe")
        flags = os.O_RDONLY if number == 0 else os.O_WRONLY
        descriptor = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
    return os.fdopen(descriptor, mode, encoding="utf-8")


def serve():
    # PyInstaller's Windows windowed bootloader can leave these as None even
    # though this private child has redirected OS handles supplied by Popen.
    incoming = sys.stdin if sys.stdin is not None else _pipe_stream(0, "r")
    outgoing = sys.stdout if sys.stdout is not None else _pipe_stream(1, "w")
    errors = sys.stderr if sys.stderr is not None else open(os.devnull, "w")
    for line in incoming:
        try:
            request = json.loads(line)
            with redirect_stdout(errors):
                images = raster(
                    base64.b64decode(request["pdf"]),
                    request["sizes"],
                    request["full_size"],
                )
            response = dict(
                ok=True,
                images=[base64.b64encode(image).decode("ascii") for image in images],
            )
        except Exception as exc:
            response = dict(ok=False, error=str(exc) or type(exc).__name__)
        outgoing.write(json.dumps(response) + "\n")
        outgoing.flush()


if __name__ == "__main__":
    serve()
