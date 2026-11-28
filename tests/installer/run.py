# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test packaging/install-slidemage.sh in clean Linux containers (Docker; not part of the pytest run).

    python tests/installer/run.py --zip PATH/SlideMage-linux-folder.zip     a build of this checkout (--from-zip)
    python tests/installer/run.py --release                                 the latest release from GitHub
    options: --image ubuntu-24.04 --image fedora (default: both), --keep (leave the containers)

For each image (tests/installer/Dockerfile.<image>: a user with passwordless sudo, nothing else) it runs check.sh in
a fresh container: install, the compile self-test, ldd, the window under Xvfb, a second run, uninstall. The package
downloads are cached in a Docker volume per image (slidemage-installer-cache-<image>), so a second run is quick.
Prints each check and a table of the recorded numbers; exits 1 when a check failed. README.md here has the details.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IMAGES = ("ubuntu-24.04", "fedora")
CACHE = {"ubuntu-24.04": "/var/cache/apt/archives", "fedora": "/var/cache/libdnf5"}


def docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], **kwargs)


def build_image(image: str) -> str:
    tag = f"slidemage-installer-test:{image}"
    docker("build", "-q", "-t", tag, "-f", str(HERE / f"Dockerfile.{image}"), str(HERE), check=True,
           stdout=subprocess.DEVNULL)
    return tag


def run_image(image: str, inputs: Path, mode: str, keep: bool) -> tuple[list[str], dict[str, str], float]:
    tag = build_image(image)
    started = time.monotonic()
    args = ["run", "--shm-size=1g", "-v", f"{inputs}:/in:ro", "-v", f"slidemage-installer-cache-{image}:{CACHE[image]}"]
    if not keep:
        args.append("--rm")
    # The cache volume belongs to root; the test user's sudo writes to it.
    process = docker(*args, tag, "bash", "/in/check.sh", mode, capture_output=True, text=True, encoding="utf-8",
                     errors="replace")
    output = process.stdout + process.stderr
    (inputs / f"output-{image}.log").write_text(output, encoding="utf-8")
    checks = [line for line in output.splitlines() if line.startswith("CHECK ")]
    results = {}
    for line in output.splitlines():
        if line.startswith("RESULT "):
            _, key, *value = line.split(" ", 2)
            results[key] = value[0] if value else ""
    if not checks:
        checks = [f"CHECK container FAILED exit {process.returncode}: {output[-2000:]}"]
    return checks, results, time.monotonic() - started


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", type=Path, help="SlideMage-linux-folder.zip to install with --from-zip")
    source.add_argument("--release", action="store_true", help="install the latest GitHub release")
    parser.add_argument("--image", action="append", choices=IMAGES, help="default: all")
    parser.add_argument("--keep", action="store_true", help="keep the containers for a look inside")
    options = parser.parse_args(argv)
    if shutil.which("docker") is None:
        print("docker is not on PATH")
        return 2

    inputs = Path(tempfile.mkdtemp(prefix="slidemage-installer-test-"))
    shutil.copy(ROOT / "packaging" / "install-slidemage.sh", inputs)
    shutil.copy(HERE / "check.sh", inputs)
    if options.zip:
        shutil.copy(options.zip, inputs / "SlideMage-linux-folder.zip")
        signature = options.zip.with_name(options.zip.name + ".sig")
        if signature.is_file():
            shutil.copy(signature, inputs / "SlideMage-linux-folder.zip.sig")
    failed = False
    table = []
    for image in options.image or IMAGES:
        print(f"== {image}", flush=True)
        checks, results, seconds = run_image(image, inputs, "zip" if options.zip else "release", options.keep)
        for line in checks:
            print("  " + line.removeprefix("CHECK "))
        failed |= any(" FAILED" in line for line in checks)
        table.append((image, f"{seconds:.0f}s", results.get("download", "?"), results.get("ldd_missing", "").strip()))
    print("\nimage, total time, download, libraries ldd did not find (optional Qt plugins included):")
    for row in table:
        print("  " + " | ".join(row))
    print(f"\nFull output per image: {inputs}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
