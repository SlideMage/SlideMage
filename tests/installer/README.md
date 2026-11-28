# Installer tests (Docker)

Tests `packaging/install-slidemage.sh` in clean Linux containers. Not part of the pytest run: it needs Docker, a
Linux build of SlideMage and several minutes per image (the first run downloads the TeX packages; they are cached in
a Docker volume per image, `slidemage-installer-cache-<image>`).

```bash
python tests/installer/run.py --zip path/to/SlideMage-linux-folder.zip    # a build of this checkout
python tests/installer/run.py --release                                    # the latest GitHub release
python tests/installer/run.py --zip ... --image fedora --keep              # one image, keep the container
```

A Linux build of a checkout, from Windows too (Docker with Linux containers), the way release.yml builds it:
an `ubuntu:24.04` container with `python3 python3-venv python3-dev binutils git` and every library of the script's
`APT_LIBRARIES`, then `pip install -e ".[build]"`, `SLIDEMAGE_BUILD=folder pyinstaller --noconfirm
packaging/slidemage.spec` and `shutil.make_archive('SlideMage-linux-folder', 'zip', 'dist', 'SlideMage-folder')`.
Build it on Ubuntu 24.04 or older: the build needs the build machine's glibc. Without those libraries PySide6 cannot
start during the build, PyInstaller's Qt hook then bundles no Qt plugin, and the window does not open
("Could not find the Qt platform plugin xcb"); `find dist -name libqxcb.so` must find it.

## Images

`Dockerfile.<image>`: a user `tester` with passwordless sudo and nothing else (no curl, no unzip, no TeX).

- `ubuntu-24.04`: the oldest supported system (glibc 2.39, the release runner's).
- `fedora`: `fedora:latest`, dnf.

## What check.sh checks, per image

1. `install-slidemage.sh --yes --from-zip ...` (`--unsigned` unless a `.sig` lies beside the zip; `--release` downloads
   and checks the real signature) exits 0, which includes `SlideMage --self-test` and
   `SlideMage --self-test --compile` (a deck per layout and template with a citation; the PDF's fonts are checked).
2. `ldd` on every shared object of the app: the libraries Qt's window and QtWebEngine need are all found. Optional
   Qt plugins that lack a library (other platform themes, multimedia back ends, ...) are listed, not failed.
3. The menu entry passes `desktop-file-validate`; the window runs for 20 s under Xvfb with no missing library or
   platform plugin in its output (`QTWEBENGINE_DISABLE_SANDBOX=1`: Chromium's sandbox needs privileges a container
   lacks). The test tools are installed only after the installer ran, so they cannot stand in for a library it
   forgot.
4. A second run finds nothing to install and leaves a working installation.
5. `--uninstall` leaves nothing of SlideMage in `~/.local`.

`run.py` prints each check, and per image the time, the download size and the libraries `ldd` did not find; the
full output of each container is in the folder it names.

What containers cannot show: the menu entry and the window on a real desktop. Check that once by hand on a Linux
desktop after a change to the script. The Windows setup (`packaging/slidemage.iss`) is smoke-tested by release.yml
(install without the TeX and Perl tasks, self-test, uninstall); its MiKTeX and Perl steps need a clean Windows (a
VM: Windows Sandbox has no winget).
