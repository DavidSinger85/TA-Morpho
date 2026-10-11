# PyInstaller recipe for the desktop program (Windows, macOS, Linux).
#
#   pyinstaller --noconfirm packaging/ta_morpho.spec      (from the repository root)
#
# Result: dist/TA-Morpho/ (a folder with the program and everything it
# needs; no Python required), and on macOS dist/TA-Morpho.app.
# Check it with:  dist/TA-Morpho/TA-Morpho --self-test
# The installers are built by .github/workflows/release.yml.
import re
import sys
from importlib import metadata
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from ta_morpho.provenance import PACKAGES  # noqa: E402  (the packages whose versions are recorded)


def installed(pkg):
    try:
        metadata.version(pkg)
        return True
    except metadata.PackageNotFoundError:          # e.g. only one of the two OpenCV builds is installed
        return False


# Package metadata, so that the installed program records the versions it computes with
# (ta_morpho/provenance.py: config_used.yaml); without it the bundle knows none of them.
METADATA = [m for pkg in PACKAGES if installed(pkg) for m in copy_metadata(pkg)]
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "ta_morpho" / "__init__.py").read_text(encoding="utf-8"))[1]
NAME = "TA-Morpho"
ASSETS = ROOT / "ta_morpho" / "gui" / "assets"
ICON_WIN = str(ASSETS / "icon.ico")
ICON_MAC = str(ASSETS / "icon.icns")

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "ta_morpho" / "config.yaml"), "ta_morpho"),  # default settings (ta_morpho/export.py DEFAULT_CONFIG)
           (str(ROOT / "ta_morpho" / "genus_characters.csv"), "ta_morpho"),  # genus characters (ta_morpho/characters.py)
           (str(ASSETS / "icon.png"), "ta_morpho/gui/assets"),   # window / taskbar icon (ta_morpho/gui/app.py)
           (str(ASSETS / "icon.ico"), "ta_morpho/gui/assets"), *METADATA],
    hiddenimports=["ta_morpho.gui.app", "skimage.measure", "skimage.morphology",
                   "scipy.spatial", "scipy.interpolate", "scipy.ndimage"],
    excludes=["tkinter", "pytest", "IPython", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,                                      # a window program, no terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=ICON_WIN,                                      # Windows .exe icon
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, strip=False, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=ICON_MAC,                                  # macOS .app icon
        bundle_identifier="org.ta-morpho.app",
        info_plist={"NSHighResolutionCapable": True,
                    "CFBundleShortVersionString": VERSION,
                    # the oldest macOS the bundled libraries run on: the numpy and scipy wheels
                    # (and OpenCV on Intel) installed by release.yml are built for macOS 14
                    "LSMinimumSystemVersion": "14.0"},
    )
