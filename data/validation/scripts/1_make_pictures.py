"""Replicates 2 and 3 of the validation: turned and resized copies of the pictures in
images/Replicate_1 (the pictures as published).

Each picture is resized by a factor between 0.7 and 1.6 and turned by an angle at least 10° away
from upright, with a mirror flip on half of them; factors, angles and flips are drawn at random
(fixed seed: 2 for Replicate_2, 3 for Replicate_3) and differ between replicates, so a picture is
measured in a new orientation and size each time.

The scale bar is not turned: it is cut out of the resized picture, its place filled with the
background colour, and pasted back level on a strip added at the bottom of the turned picture.
It is resized with the picture, so its length in µm (the "_20um" part of the file name) is
unchanged and the names stay the same; only the number of pixels per µm changes. Pictures without
a bar (drawings) are resized and turned only.

Writes images/Replicate_2/ and images/Replicate_3/, and data/transforms.csv (one row per replicate
and picture: factor, angle, flip, bar length in px before and after). Then checks each new picture
with the app's bar detection: detected length = factor × original length (± 1.5 px).

    python data/validation/scripts/1_make_pictures.py      (from the repository, with ta_morpho installed)
"""
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

from ta_morpho.calibration import ScaleBarNotFound, detect_scale_bar
from ta_morpho.image_io import read_image, write_image

VALIDATION = Path(__file__).resolve().parents[1]
IMAGES = VALIDATION / "images"
REPLICATES = {2: 2, 3: 3}  # replicate: random seed
SCALE_RANGE = (0.7, 1.6)   # smaller would leave bars of 1 px; larger gives very big files
MIN_TILT = 10              # degrees away from upright (0°)


def draw(rng: np.random.Generator) -> tuple[float, int, bool]:
    """Resize factor (log-uniform, rounded to 0.05, not 0.95-1.05), angle (whole degrees,
    counter-clockwise), mirror flip."""
    while True:
        s = round(float(np.exp(rng.uniform(*np.log(SCALE_RANGE)))) * 20) / 20
        if abs(s - 1) > 0.05:
            break
    angle = int(rng.integers(MIN_TILT, 360 - MIN_TILT + 1))
    return s, angle, bool(rng.integers(2))


def background(img: np.ndarray) -> tuple[int, ...]:
    """Median colour of the picture's border pixels."""
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    return tuple(int(v) for v in np.median(border, axis=0))


def resize(img: np.ndarray, s: float) -> np.ndarray:
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=s, fy=s, interpolation=interp)


def turn(img: np.ndarray, angle: int, fill: tuple[int, ...]) -> np.ndarray:
    """Turn by ``angle`` degrees counter-clockwise on a canvas large enough for every pixel."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    c, s = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(np.ceil(w * c + h * s)), int(np.ceil(w * s + h * c))
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=fill)


def make_copy(img: np.ndarray, s: float, angle: int, flip: bool) -> tuple[np.ndarray, float | None]:
    """The transformed picture and the bar length in px it should have (None without a bar)."""
    fill = background(img)
    try:
        bar = detect_scale_bar(img)
    except ScaleBarNotFound:
        bar = None
    big = resize(img, s)
    patch = None
    if bar is not None:
        def box(pad_x: float, pad_y: float) -> tuple[slice, slice]:
            y0 = max(0, int(np.floor((bar.y_top - pad_y) * s)))
            y1 = min(big.shape[0], int(np.ceil((bar.y_bottom + 1 + pad_y) * s)))
            x0 = max(0, int(np.floor((bar.x0 - pad_x) * s)))
            x1 = min(big.shape[1], int(np.ceil((bar.x1 + pad_x) * s)))
            return slice(y0, y1), slice(x0, x1)
        # tight above and below (a label often touches the bar), wider for erasing
        patch = big[box(4, 2)].copy()
        big[box(max(4, 2 * bar.thickness_px), max(4, 2 * bar.thickness_px))] = fill
    if flip:
        big = big[:, ::-1]
    out = turn(np.ascontiguousarray(big), angle, fill)
    if patch is None:
        return out, None
    margin = max(10, patch.shape[0])
    strip = np.full((patch.shape[0] + 2 * margin, out.shape[1], 3), fill, np.uint8)
    px = max(0, out.shape[1] - patch.shape[1] - margin)
    strip[margin:margin + patch.shape[0], px:px + patch.shape[1]] = patch[:, :strip.shape[1] - px]
    return np.vstack([out, strip]), bar.length_px * s


def make_replicate(k: int, rows: list[dict]) -> int:
    """Replicate_1 -> Replicate_<k> with seed REPLICATES[k]; appends to ``rows``; returns the failed
    bar checks."""
    out = IMAGES / f"Replicate_{k}"
    out.mkdir(exist_ok=True)
    rng = np.random.default_rng(REPLICATES[k])
    bad = 0
    for p in sorted((IMAGES / "Replicate_1").glob("*.png")):
        img = read_image(p)
        s, angle, flip = draw(rng)
        new, expected = make_copy(img, s, angle, flip)
        write_image(out / p.name, new)
        found = ""
        if expected is not None:
            try:
                found = round(detect_scale_bar(new).length_px, 1)
            except ScaleBarNotFound:
                found = "not found"
            if found == "not found" or abs(found - expected) > 1.5:
                bad += 1
        rows.append({"replicate": k, "image": p.name, "scale": s, "angle_ccw_deg": angle, "mirrored": flip,
                     "bar_px_original": "" if expected is None else round(expected / s, 1),
                     "bar_px_expected": "" if expected is None else round(expected, 1),
                     "bar_px_detected": found, "size_px": f"{new.shape[1]}x{new.shape[0]}"})
        print(f"replicate {k}  {p.name:45s} x{s:<5} {angle:3d}° {'mirror' if flip else '':6s} "
              f"bar {rows[-1]['bar_px_expected']} -> {found}")
    return bad


def main() -> int:
    rows: list[dict] = []
    bad = sum(make_replicate(k, rows) for k in REPLICATES)
    with open(VALIDATION / "data" / "transforms.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} pictures written; bar check failed on {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
