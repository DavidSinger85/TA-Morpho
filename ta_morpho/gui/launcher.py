"""Start the desktop interface: ``ta-morpho-gui`` or ``python -m ta_morpho.gui``.

The options are read before Qt is loaded, so ``--help`` and ``--version``
work everywhere, and a missing system library (common on bare Linux and
WSL) gives the line that installs it instead of a raw import error. A
missing Python package (e.g. numpy) is named as such, not as a Qt problem.
"""

from __future__ import annotations

import argparse
import os
import sys

QT_LIBS_HINT = ("On Debian/Ubuntu/WSL install the libraries Qt needs with:\n"
                "  sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3")
QT_MODULES = ("PySide6", "shiboken6")
PIP_NAMES = {"cv2": "opencv-python-headless", "skimage": "scikit-image", "yaml": "PyYAML", "PIL": "pillow"}
REINSTALL = 'reinstall TA-Morpho (from a source folder: pip install -e ".[gui]")'


def import_error_message(e: ImportError) -> tuple[str, bool]:
    """What to tell the user about an import error of the interface, and whether
    it is a Qt (PySide6) problem, for which a Linux system library may be missing."""
    top = (e.name or "").split(".")[0]
    if top in QT_MODULES or (not top and any(s in str(e) for s in ("Qt", "PySide", ".so", "DLL"))):
        return f"cannot load the Qt interface (PySide6): {e}", True
    if top:
        return f"a required package is missing or broken: {PIP_NAMES.get(top, top)} ({e}); {REINSTALL}", False
    return f"a required package is missing or broken ({e}); {REINSTALL}", False


def main(argv: list[str] | None = None) -> int:
    from ta_morpho import __version__
    p = argparse.ArgumentParser(prog="ta-morpho-gui",
                                description="TA-Morpho desktop interface (no arguments: open the window)")
    p.add_argument("--self-test", action="store_true",
                   help="analyse a synthetic test in a temporary folder and create the window "
                        "without showing it; prints 'self-test passed' and returns 0 if all works")
    p.add_argument("--log", metavar="FILE",
                   help="with --self-test: also write the result to FILE (the installed program "
                        "has no console on Windows)")
    p.add_argument("--version", action="version", version=f"TA-Morpho {__version__}")
    args, qt_args = p.parse_known_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ta_morpho.gui import app
    except ImportError as e:
        text, qt = import_error_message(e)
        msg = f"ta-morpho-gui: {text}"
        print(msg, file=sys.stderr)
        if qt and sys.platform.startswith("linux") and ".so" in str(e):
            print(QT_LIBS_HINT, file=sys.stderr)
        if args.self_test and args.log:
            with open(args.log, "w", encoding="utf-8") as f:
                f.write(f"self-test FAILED: {msg}\n")
        return 3
    if args.self_test:
        return app.self_test(args.log)
    return app.main([sys.argv[0], *qt_args])
