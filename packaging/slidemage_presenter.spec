# Build SlideMage Presenter (docs/plans/presenter-app.md, step 3) as a folder, for whichever OS this actually runs
# on -- PyInstaller never cross-compiles. From the repo root, with pyinstaller installed (pip install -e ".[build]"):
#     pyinstaller --noconfirm packaging/slidemage_presenter.spec
# Output: dist/SlideMagePresenter/ with SlideMagePresenter(.exe) and _internal/ (on macOS also
# SlideMage Presenter.app, see step 4). It is a separate spec, not an option of slidemage.spec: the Presenter's entry
# point (presenter_app.py) imports only the presentation modules and the kit, so PyInstaller leaves the compiler, the
# workspace, QtWebEngine and the rest out by itself, and this spec bundles only the data the Presenter reads
# (some fonts, its icon, the licences). `excludes` is the safety net, and tests/test_presenter_imports.py keeps the
# import graph small.
# A folder build only, no one-file exe and no splash screen: a one-file exe unpacks itself on every start, which is
# exactly the slow start the Presenter is meant to avoid, and a folder starts fast enough to need no splash.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"
FONTS = ASSETS / "fonts"

# Fonts: ui/kit/fonts.py loads every *.ttf it finds in FONT_DIR, which must resolve in the frozen build to
# slidemage/assets/fonts. SlideMage ships all 37 files (12 MB); the Presenter's own windows use only Roboto in
# weights 400-700 (kit_qss, the presentation UI), Roboto Mono and Material Icons, so it ships the variable fonts
# (they give every weight and the italics), the static Regular/Medium/Bold for the weights that must not be
# synthesised (fonts.py), and the licences, not Condensed, Thin, Light, Black or the static italics (about 9 MB).
FONT_FILES = {"Roboto[ital,wdth,wght].ttf", "Roboto-Regular.ttf", "Roboto-Medium.ttf", "Roboto-Bold.ttf",
              "RobotoMono[wght].ttf", "RobotoMono-Regular.ttf", "RobotoMono-Medium.ttf", "RobotoMono-Bold.ttf",
              "MaterialIcons-Regular.ttf"}
FONT_DATAS = [(str(path), "slidemage/assets/fonts") for path in sorted(FONTS.iterdir())
              if path.name in FONT_FILES or path.name.startswith("LICENSE")]

# The icon: the SVG for the window icon (needs QtSvg), the .ico for Windows' own use is embedded by EXE(icon=...).
ICON_DATAS = [(str(ASSETS / "presenter-icon.svg"), "slidemage/assets"),
              (str(ASSETS / "presenter-icon-256.png"), "slidemage/assets")]

if sys.platform == "win32":
    icon = str(ASSETS / "presenter-icon.ico")
elif sys.platform == "darwin":
    icon = str(ASSETS / "presenter-icon.icns")
else:
    icon = None      # Linux takes the icon from the .desktop file (presenter-icon-256.png / .svg)

EXCLUDES = [
    # Qt modules the Presenter never uses
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    # third-party packages of SlideMage itself
    "lxml", "pptx", "odf", "segno", "winpty", "ptyprocess",
    # standard library the Presenter does not need
    "tkinter", "unittest", "pydoc",
    # PyMuPDF imports Pillow only to convert a pixmap on request; ssl (and with it libssl) is only reached from
    # urllib/http, which the Presenter does not use; _hashlib (and libcrypto, 5 MB) because hashlib falls back to
    # Python's own sha/md5 code without it
    "PIL", "ssl", "_ssl", "_hashlib",
    # SlideMage's heavy parts
    "slidemage.compiler", "slidemage.ui.app", "slidemage.ui.workspace", "slidemage.ui.dialogs", "slidemage.ai",
    "slidemage.plugins",
]

a = Analysis(
    [str(ROOT / "packaging" / "launch_presenter.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        *FONT_DATAS,
        *ICON_DATAS,
        # The licences, as in slidemage.spec (app_info.license_text), for everyone who gets the folder.
        (str(ROOT / "LICENSE"), "slidemage/legal"),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "slidemage/legal"),
        (str(ROOT / "LICENSES"), "slidemage/legal/LICENSES"),
    ],
    # The SVG icon needs QtSvg: without it QIcon draws it empty. presenter_app.py imports it, this is for certainty.
    hiddenimports=["PySide6.QtSvg"],
    excludes=EXCLUDES,
)

# Qt files the Presenter does not need, dropped after the analysis (paths are the in-bundle destinations).
_DROP_PLUGIN_DIRS = ("generic", "networkinformation", "platforminputcontexts", "platformthemes", "tls",
                     "position", "sensors", "multimedia", "sqldrivers", "designer", "qmltooling", "bearer",
                     "renderers", "scenegraph", "geometryloaders", "sceneparsers", "texttospeech", "canbus",
                     "printsupport", "qmllint", "assetimporters", "egldeviceintegrations", "xcbglintegrations")
_KEEP_IMAGEFORMATS = ("qjpeg", "qsvg", "qico", "qgif", "qwebp", "qicns")     # PNG is built into QtGui
_DROP_FILES = ("qtdbus.pyd", "opengl32sw.dll", "d3dcompiler_47.dll", "dxcompiler.dll", "dxil.dll", "qdirect2d.dll", "qminimal.dll")
# Qt libraries that Qt's own plugins or PySide6's hooks pull in although no module of the Presenter uses them
_DROP_QT_LIBRARIES = ("qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6virtualkeyboard", "qt6opengl", "qt6dbus")


def _unneeded(dest):
    path = dest.replace("\\", "/")
    parts = path.split("/")
    name = parts[-1].lower()
    if name in _DROP_FILES or name.endswith(".qm"):
        return True
    if "plugins" not in parts and name.removeprefix("lib").startswith(_DROP_QT_LIBRARIES):
        return True
    if "translations" in parts or "qml" in parts:
        return True
    if "plugins" in parts:
        folder = parts[parts.index("plugins") + 1]
        if folder in _DROP_PLUGIN_DIRS:
            return True
        if folder == "imageformats" and not any(name.startswith(prefix) or name.startswith("lib" + prefix)
                                                for prefix in _KEEP_IMAGEFORMATS):
            return True
    return False


a.binaries = [entry for entry in a.binaries if not _unneeded(entry[0])]
a.datas = [entry for entry in a.datas if not _unneeded(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SlideMagePresenter",
    console=False,
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="SlideMagePresenter",
)
