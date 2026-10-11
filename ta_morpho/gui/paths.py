"""Folder paths typed or pasted by the user, or saved in a project, and the
drives to offer in the folder dialog. Under WSL (Linux inside Windows) the
Windows drives are mounted as /mnt/c, /mnt/d, ...; a Windows path such as
``F:\\data`` is converted to ``/mnt/f/data``, and back under Windows.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

_DRIVE = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")
_MNT = re.compile(r"^/mnt/([a-zA-Z])(?:/(.*))?$")


def is_wsl() -> bool:
    return "microsoft" in platform.release().lower()


def to_local_path(text: str, wsl: bool | None = None, windows: bool | None = None) -> Path | None:
    """Path from what the user typed or pasted, or what a project saved
    (quotes and spaces removed). Under WSL, Windows paths (``F:\\a\\b``,
    ``F:/a/b``) become ``/mnt/f/a/b``; under Windows, ``/mnt/f/a/b`` becomes
    ``F:/a/b`` (a project made under WSL). None for an empty text."""
    t = str(text).strip().strip('"').strip("'").strip()
    if not t:
        return None
    wsl = is_wsl() if wsl is None else wsl
    windows = os.name == "nt" if windows is None else windows
    m = _DRIVE.match(t)
    if wsl and m:
        rest = (m.group(2) or "").replace("\\", "/").strip("/")
        return Path(f"/mnt/{m.group(1).lower()}") / rest if rest else Path(f"/mnt/{m.group(1).lower()}")
    m = _MNT.match(t)
    if windows and m:
        return Path(f"{m.group(1).upper()}:/" + (m.group(2) or ""))
    return Path(t).expanduser()


def display_path(path: Path | str | None, wsl: bool | None = None) -> str:
    """How to show a path to the user: under WSL, /mnt/f/a/b as F:\\a\\b."""
    if path is None:
        return ""
    s = str(path)
    wsl = is_wsl() if wsl is None else wsl
    m = re.match(r"^/mnt/([a-z])(?:/(.*))?$", s)
    if wsl and m:
        return f"{m.group(1).upper()}:\\" + (m.group(2) or "").replace("/", "\\")
    return s


def windows_drives(mnt: Path = Path("/mnt")) -> list[Path]:
    """Mounted Windows drives under WSL (/mnt/c, /mnt/d, ...)."""
    if not mnt.is_dir():
        return []
    return sorted(p for p in mnt.iterdir() if len(p.name) == 1 and p.name.isalpha() and p.is_dir())
