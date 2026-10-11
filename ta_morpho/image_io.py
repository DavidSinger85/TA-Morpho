"""Finding, reading and writing images, with any file name.

OpenCV's ``imread`` / ``imwrite`` take the path as a narrow string and fail
on Windows when it contains characters outside the system code page (e.g.
``F:\\Données\\Nebela_é.png``): ``imread`` then returns None as if the file
were not an image. Here Python opens the file and OpenCV only decodes or
encodes the bytes, which works with every path on every system.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class UnsupportedImage(ValueError):
    """An image file of a kind the analysis does not read (reported without a traceback)."""


def list_images(inputs: list[Path], default_dir: str | Path) -> list[Path]:
    """Expand image files and folders (sorted); ``default_dir`` if none given.
    A file given twice (or given and also in a folder given) is listed once."""
    paths, seen = [], set()
    for inp in inputs or [Path(default_dir)]:
        found = sorted(f for f in inp.iterdir() if f.suffix.lower() in IMAGE_EXTS) if inp.is_dir() else [inp]
        for f in found:
            if f.resolve() not in seen:
                seen.add(f.resolve())
                paths.append(f)
    return paths


def load_image(path: str | Path) -> np.ndarray:
    """Read an image (PNG/JPG/TIFF) as an RGB uint8 array.

    An 8-bit image is read as it is. A 16-bit image is brought to 8 bits from
    the range its data really use (a camera's 12-bit values stored in a
    16-bit file fill 0-4095: divided by 16, not by 256, which would leave only
    16 grey levels). Raises FileNotFoundError if the file cannot be read,
    UnsupportedImage for floating-point images.
    """
    bgr = read_image(path, cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH)
    if bgr is None:
        raise FileNotFoundError(f"Cannot read image: {path} (missing, not an image, or a kind of "
                                "image that cannot be decoded, e.g. a floating-point TIFF: save it "
                                "as an 8-bit or 16-bit PNG or TIFF)")
    if bgr.dtype == np.uint16:
        bgr = to_8bit(bgr)
    elif bgr.dtype != np.uint8:
        raise UnsupportedImage(f"{bgr.dtype} pixel values (a floating-point image) are not supported: "
                               "save it as an 8-bit or 16-bit image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def to_8bit(img: np.ndarray) -> np.ndarray:
    """16-bit pixel values to 8 bits, keeping the image's own scale: divided by
    2**(bits - 8), where ``bits`` is the smallest bit depth that holds the
    largest value (at least 8)."""
    bits = max(8, int(img.max()).bit_length())
    return (img >> (bits - 8)).astype(np.uint8)


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """Decode an image file as OpenCV would (BGR, or grey with
    ``cv2.IMREAD_GRAYSCALE``). None if the file is missing or not an image."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def write_image(path: str | Path, image: np.ndarray) -> None:
    """Encode an image (BGR or grey) in the format given by the file extension
    and write it. Raises ValueError if it cannot be encoded, OSError if the file
    cannot be written (unlike ``cv2.imwrite``, which fails silently)."""
    path = Path(path)
    ok, buf = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"cannot encode an image as {path.suffix}: {path.name}")
    path.write_bytes(buf.tobytes())
