"""Entry point of the packaged desktop program (see packaging/ta_morpho.spec)."""

import multiprocessing
import sys

from ta_morpho.gui.launcher import main

if __name__ == "__main__":
    multiprocessing.freeze_support()   # needed by frozen programs on Windows
    sys.exit(main())
