"""What produced a set of results: program version, git commit and the
versions of the packages that compute the numbers (written to
``config_used.yaml`` and, as ``software_version``, to ``summary.csv``)."""

from __future__ import annotations

import platform
import subprocess
from functools import lru_cache
from importlib import metadata
from pathlib import Path

from ta_morpho import __version__

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("numpy", "scipy", "scikit-image", "opencv-python-headless", "opencv-python",
            "pandas", "matplotlib", "PyYAML", "PySide6")


@lru_cache(maxsize=1)
def git_commit() -> str:
    """Short commit of the source folder, with "+changes" when files were
    modified since; "" when the program does not run from its own git
    checkout (e.g. installed). Read once per session."""
    if not (ROOT / ".git").exists():
        return ""
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True,  # noqa: E731
                                        text=True, timeout=5)
        head = run("rev-parse", "--short", "HEAD")
        if head.returncode:
            return ""
        dirty = run("status", "--porcelain", "--untracked-files=no").stdout.strip()
        return head.stdout.strip() + ("+changes" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def software_version() -> str:
    """``1.0.0`` or ``1.0.0 (git edcc7d7)``: one value per run, for summary.csv."""
    commit = git_commit()
    return f"{__version__} (git {commit})" if commit else __version__


def provenance() -> dict:
    """Version, commit, Python and package versions (installed ones only)."""
    packages = {}
    for name in PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return {"ta_morpho": __version__, "git_commit": git_commit() or None,
            "python": platform.python_version(), "packages": packages}
