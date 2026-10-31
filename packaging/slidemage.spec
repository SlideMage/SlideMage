# Build SlideMage as a one-file executable and as a folder, for whichever OS this actually
# runs on -- PyInstaller never cross-compiles. From the repo root, with
# pyinstaller installed (pip install -e ".[build]"):
#     pyinstaller packaging/slidemage.spec
# Output lands in dist/SlideMage(.exe) and dist/SlideMage-folder/. The exe finds its project via
# --project, $SLIDEMAGE_PROJECT, an upward search from the cwd, the
# last project opened, or a folder picker.
import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"


def _load_selftest():
    # The list of bundled standard-library modules lives in the plugin host's self-test (plugins/selftest.py),
    # which imports only the standard library, so it is loaded by path here rather than through the package.
    path = ROOT / "src" / "slidemage" / "plugins" / "selftest.py"
    spec = importlib.util.spec_from_file_location("slidemage_selftest_list", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_selftest = _load_selftest()


def _load_plugin_api():
    # plugin_api imports only the standard library until a plugin asks for a re-export, so it loads by path too.
    path = ROOT / "src" / "slidemage" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("slidemage_plugin_api_list", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # its dataclasses look their module up
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


# The SlideMage modules plugin_api loads by name, which PyInstaller cannot follow.
PLUGIN_API_MODULES = list(_load_plugin_api()._RUNTIME_MODULES)

# The whole assets/ folder is data: the fonts (assets/fonts), the Claude Code terminal's page and scripts
# (assets/terminal, loaded by QtWebEngine from a file), the frame thumbnails (assets/frames) and the icons.
# The release history is also data, stored beside version.py.
# Everything else the app needs is code: PyInstaller follows the imports. Not QtWebEngine's helper process and
# resources, which the PySide6 hooks of PyInstaller add as soon as QtWebEngineWidgets is imported
# (ui/workspace/terminal/web.py).
# ptyprocess (pywinpty on Windows) is imported inside a function and found that way.
# Plugins (plugins plan 2.2, PLUGIN_HOST_PLAN step 5) may import any standard-library module and PySide6's
# modules, and PyInstaller bundles only what SlideMage itself imports: so the whole standard library except
# selftest.EXCLUDED is a hidden import here, and so are the PySide6 modules a plugin's widgets come from.
# `slidemage --self-test --plugins` checks that each one imports in the build (slidemage/plugins/selftest.py).
STDLIB_MODULES = _selftest.bundled_stdlib_modules()   # for this platform: find_spec drops the others


def _stdlib_hidden_imports(names):
    hidden = []
    for name in names:
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.submodule_search_locations is not None:
            hidden += collect_submodules(name)   # a package: its submodules too
        else:
            hidden.append(name)
    return hidden


PYSIDE6_MODULES = [f"PySide6.{name}" for name in ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg")]
HIDDEN_IMPORTS = list(dict.fromkeys([
    *_stdlib_hidden_imports(STDLIB_MODULES),
    *PYSIDE6_MODULES,
    *PLUGIN_API_MODULES,
]))
# The same list for the frozen self-test, which cannot ask find_spec what was bundled (slidemage/plugins/selftest.py).
STDLIB_LIST_FILE = ROOT / "build" / _selftest.STDLIB_LIST_NAME
STDLIB_LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
STDLIB_LIST_FILE.write_text("\n".join(STDLIB_MODULES) + "\n", encoding="utf-8")
# pywinpty's helpers, which conpty.dll and winpty.dll start at run time, so PyInstaller does not see them: without
# OpenConsole.exe a program in the Claude Code terminal got a console closed at once and ended before printing
# anything, exit code -1073741510 (0xC000013A), up to v8.58.0.
WINPTY_HELPERS = collect_data_files("winpty", includes=["*.exe"]) if sys.platform == "win32" else []

# Bundled so a project created via "Open Project..."'s "not a project
# yet -- create one?" offer (project.py's init_project()) can be seeded
# with real, working demo content even when SlideMage was only ever
# downloaded as this one exe, never cloned from the repo. Also the source of
# the manual updates (bundled_copies.py).
#
# The example project is filtered file by file (v5.20.1): bundling the whole
# folder also shipped a developer's slides/.backups (the slide editor's undo
# history), their .slidemage/app_settings.json and compile output -- and the
# backups reached users' projects through the manual's copy.
_EXAMPLE_SKIP_DIRS = {".build", ".previews", ".backups", "pdf", "__pycache__"}
_EXAMPLE_SKIP_FILES = {
    ".slidemage/app_settings.json", ".slidemage/project.json",
    ".slidemage/compile_passes.json", ".slidemage/bundled_copies.json",
}


def _example_datas():
    example = ROOT / "example"
    datas = []
    for path in sorted(example.rglob("*")):
        rel = path.relative_to(example)
        if (not path.is_file() or _EXAMPLE_SKIP_DIRS.intersection(rel.parts)
                or rel.as_posix() in _EXAMPLE_SKIP_FILES
                or (rel.parts[0] == "decks" and path.name.endswith((".pdf", ".synctex.gz")))):
            continue
        datas.append((str(path), str(Path("slidemage_template/example") / rel.parent)))
    return datas


TEMPLATE_DATAS = [
    *_example_datas(),
    (str(ROOT / "latex"), "slidemage_template/latex"),
]

# PyInstaller only actually embeds this on Windows (.ico) and macOS
# (.icns) -- ignored on Linux, where a windowmanager/taskbar icon instead
# comes from a .desktop file's own Icon= line, conventionally an SVG/PNG,
# not the Windows .ico this project ships for that platform's build.
if sys.platform == "win32":
    icon = str(ASSETS / "icon.ico")
elif sys.platform == "darwin":
    icon = None  # no .icns shipped
else:
    icon = str(ASSETS / "icon.svg")

a = Analysis(
    [str(ROOT / "packaging" / "launch_slidemage.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ASSETS), "slidemage/assets"),
        (str(ROOT / "src" / "slidemage" / "CHANGELOG.md"), "slidemage"),
        # The licences, for the About sheet (app_info.license_text) and for everyone who gets the executable.
        (str(ROOT / "LICENSE"), "slidemage/legal"),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "slidemage/legal"),
        (str(ROOT / "LICENSES"), "slidemage/legal/LICENSES"),
        (str(STDLIB_LIST_FILE), "slidemage/plugins"),
        *TEMPLATE_DATAS,
        *WINPTY_HELPERS,
    ],
    hiddenimports=HIDDEN_IMPORTS,
)
pyz = PYZ(a.pure)

# Windows only: a splash screen (splash.png) shown by the bootloader while
# the one-file build unpacks itself, several seconds before any Python code
# runs -- without it, double-clicking the exe looks like nothing happened.
# slidemage/splash.py closes it. Not on macOS (unsupported by PyInstaller)
# or Linux (would need Tk on the build runner; untested).
splash_parts = []
if sys.platform == "win32":
    splash = Splash(
        str(ASSETS / "splash.png"),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=None,
        always_on_top=True,
    )
    splash_parts = [splash, splash.binaries]

# SLIDEMAGE_BUILD=folder or =onefile builds just that one (the release builds the folder first and publishes
# it before the single file); unset, both.
BUILD = os.environ.get("SLIDEMAGE_BUILD", "")

# The same program as a folder (dist/SlideMage-folder/: SlideMage[.exe] and _internal/). It does not unpack itself
# at every start, so it starts in about a quarter of the time (v8.33.0); the release publishes both and an
# installation updates itself with the build it is (updater.install_flavour()).
if BUILD != "onefile":
    folder_exe = EXE(
        pyz,
        a.scripts,
        *([splash] if splash_parts else []),
        [],
        exclude_binaries=True,
        name="SlideMage",
        console=False,
        icon=icon,
    )
    folder = COLLECT(
        folder_exe,
        a.binaries,
        a.datas,
        *([splash.binaries] if splash_parts else []),
        name="SlideMage-folder",
    )

if BUILD != "folder":
    exe = EXE(
        pyz,
        a.scripts,
        *splash_parts,
        a.binaries,
        a.datas,
        [],
        name="SlideMage",
        console=False,
        icon=icon,
    )
