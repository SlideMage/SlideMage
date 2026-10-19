
## Also bundled

| Component | Licence | Notes |
|---|---|---|
| Roboto, Roboto Mono, Roboto Condensed (fonts) | SIL Open Font License 1.1 | `slidemage/assets/fonts/`, texts next to the files |
| Material Icons (font) | Apache-2.0 | `slidemage/assets/fonts/` |
| Gotham beamer theme (`latex/`) | LPPL-1.3c, © Romain Noël | unchanged from release v1.2.5.a (https://gitlab.com/RomainNOEL/beamertheme-gotham) |
| Qt WebEngine (Chromium; the Claude Code terminal) | LGPL-3.0 with Chromium's own third-party licences | part of PySide6_WebEngine; the licence list is in the Qt documentation (https://doc.qt.io/qt-6/qtwebengine-attribution.html) |
| The Python runtime | PSF-2.0 | https://www.python.org/ |

## Source code and replacing Qt

- **Source.** The software is GPL-3.0-or-later. The complete corresponding source of each release (this repository
  at the release tag, with the build script `packaging/slidemage.spec`) is attached to the release on GitHub as
  `SlideMage-<version>-source.tar.gz`, and is in the public repository.
- **PyMuPDF (AGPL-3.0)** is used unmodified through its Python interface. SlideMage is licensed GPL-3.0-or-later,
  which section 13 of the GPL permits to combine with AGPL-3.0 software.
- **Qt for Python (LGPL-3.0).** The Windows and Linux executables are single files that unpack the Qt libraries
  when they start. Qt is used unmodified. To run SlideMage with another build of Qt for Python, rebuild it from
  the source archive with `pip install -e ".[build]"` and `pyinstaller packaging/slidemage.spec`, or run it from source
  with your own PySide6.
