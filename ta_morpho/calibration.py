"""Scale bar detection and px/µm calibration.

Scale bars differ between microscopes (black, white or coloured; thick or
thin; with or without a text label touching them). Detection therefore
works on a "feature image" in which bar pixels are high, one per bar mode:

- ``dark``  : 255 - grey      (black bar on light background)
- ``light`` : grey            (white bar on dark background)
- ``color`` : HSV saturation  (red / yellow / green ... bar)

Each feature image is thresholded, cleaned with a horizontal opening (which
removes text glyphs such as the "µ" descender touching the bar), and the
connected components are filtered by shape. Bars are assumed horizontal.

Per-image overrides (config ``calibration.overrides_csv``) cover images
without a bar or with a bar of a different physical length.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from ta_morpho.tables import read_table
from skimage import measure


BAR_MODES = ("dark", "light", "color")
DARK_VALUE = 64      # below this brightness (HSV value, 0-255) a pixel has no colour for the "color" mode

# px/µm used to convert the µm settings (morphology, crop check, snapping...)
# of an image without calibration; its µm results stay empty (config
# calibration.uncalibrated_px_per_um overrides it).
REFERENCE_PX_PER_UM = 7.0


class ScaleBarNotFound(RuntimeError):
    """Raised when no scale bar can be detected; the image must be flagged."""


@dataclass
class ScaleBar:
    """Detected scale bar geometry, in pixel coordinates (x right, y down)."""

    x0: float          # left end (sub-pixel)
    x1: float          # right end (sub-pixel)
    y_top: int         # bounding box, inclusive
    y_bottom: int
    length_px: float   # x1 - x0
    thickness_px: int
    n_candidates: int  # distinct bar-shaped objects that passed the filters


@dataclass
class Calibration:
    """Pixel-to-micrometre calibration for one image."""

    px_per_um: float
    bar_length_um: float | None
    source: str                   # "detected" or "manual"
    status: str = "ok"            # "ok" or "ambiguous" (needs visual check)
    bar: ScaleBar | None = None
    line: tuple[float, float, float, float] | None = None  # bar drawn by hand (x0, y0, x1, y1)
    bar_length_source: str = ""   # where bar_length_um came from: "file name", "override", "default"


def bar_length_px(cal: Calibration | None) -> float | None:
    """Length (px) of the scale bar the calibration was measured on (detected
    or drawn by hand); None when px/µm was typed in directly."""
    if cal is None:
        return None
    if cal.line is not None:
        x0, y0, x1, y1 = cal.line
        return float(np.hypot(x1 - x0, y1 - y0))
    return float(cal.bar.length_px) if cal.bar is not None else None


def calibration_uncertainty_pct(cal: Calibration | None, error_px: float = 1.0) -> float:
    """Relative error (%) of every length in µm caused by an error of
    ``error_px`` on the bar length (areas: twice this). NaN without a bar."""
    n = bar_length_px(cal)
    return 100.0 * error_px / n if n else float("nan")


def feature_image(image: np.ndarray, mode: str) -> np.ndarray:
    """Return a uint8 image in which pixels of a ``mode`` bar are high."""
    rgb = image if image.ndim == 3 else np.dstack([image] * 3)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if mode == "dark":
        return 255 - gray
    if mode == "light":
        return gray
    if mode == "color":
        # Saturation means nothing for near-black pixels (RGB 0,0,1 is "fully saturated"): a black bar
        # would also be found as a coloured one, in pieces, and win on contrast over the dark bar.
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        return np.where(hsv[:, :, 2] >= DARK_VALUE, hsv[:, :, 1], 0).astype(np.uint8)
    raise ValueError(f"mode must be one of {BAR_MODES}, got {mode!r}")


def bar_mask(feature: np.ndarray, threshold: int, min_bar_length_frac: float) -> np.ndarray:
    """Binary mask of long horizontal runs where ``feature > threshold``.

    A horizontal opening with a kernel of ``min_bar_length_frac * width``
    pixels removes anything that is not a long horizontal run (text,
    debris, specimen outline).
    """
    k = max(3, int(round(min_bar_length_frac * feature.shape[1])))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))
    mask = (feature > threshold).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel) > 0


def _subpixel_ends(
    feature: np.ndarray, y_top: int, y_bottom: int, x0: int, x1: int
) -> tuple[float, float, float]:
    """Refine bar ends to sub-pixel precision.

    Averages the core rows of the bar into a 1-D profile and finds, on each
    side, where it crosses half-way between the bar level and the
    background level (linear interpolation). Also returns the contrast
    (bar level - background level), used to rank duplicate detections.

    Known bias: on a blurred bar the length comes out slightly short, because
    the background level is read within ``max(3, thickness)`` px of the ends,
    where the blur tail still lifts it, so both crossings move inwards. On a
    synthetic 200 px x 8 px bar: 0 % sharp or with a Gaussian blur of
    sigma 1 px, -0.4 % at sigma 2 px, -2 % at sigma 3 px (all µm values then
    come out about as much too large). Sharp bars, the usual case, are exact.
    """
    t = y_bottom - y_top + 1
    core = slice(y_top + t // 4, y_bottom - t // 4 + 1)
    pad = max(3, t)
    lo, hi = max(0, x0 - pad), min(feature.shape[1], x1 + pad + 1)
    prof = feature[core, lo:hi].astype(float).mean(axis=0)
    bar_level = np.median(prof[x0 - lo + 1 : x1 - lo])
    bg_level = np.median(np.r_[prof[: x0 - lo], prof[x1 - lo + 1 :]])
    half = (bar_level + bg_level) / 2.0

    def crossing(i_out: int, i_in: int) -> float:
        # Walk from outside towards inside until the profile rises above half.
        step = 1 if i_in > i_out else -1
        i = i_out
        while i != i_in and prof[i + step] <= half:
            i += step
        a, b = prof[i], prof[i + step]
        frac = 0.0 if a == b else (half - a) / (b - a)
        return lo + i + step * frac

    left = crossing(0, x0 - lo + 1)
    right = crossing(len(prof) - 1, x1 - lo - 1)
    return float(left), float(right), float(bar_level - bg_level)


def _isolation(feature: np.ndarray, threshold: int, y0: int, y1: int, x0: int, x1: int) -> float:
    """Fraction of background pixels in the cleaner of the two bands just
    above and just below the bar (y0..y1, x0..x1 inclusive).

    A real scale bar lies on plain background on at least one side (the
    label is usually on the other); streaks inside a specimen do not.
    """
    band = max(3, (y1 - y0 + 1) // 2)
    gap = 2
    above = feature[max(0, y0 - gap - band): max(0, y0 - gap), x0:x1 + 1]
    below = feature[y1 + 1 + gap: y1 + 1 + gap + band, x0:x1 + 1]
    fracs = [float((b <= threshold).mean()) for b in (above, below) if b.size]
    return max(fracs, default=0.0)


def _component_share(raw: np.ndarray, labels: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> float:
    """Share of the candidate's connected shape (before the horizontal
    opening) that lies inside the candidate box (y0..y1, x0..x1 inclusive).

    A bar is its own shape (a label touching it adds a little); the
    horizontal stroke of a letter such as "4" is a small part of the letter.
    """
    box = labels[y0:y1 + 1, x0:x1 + 1]
    ids, counts = np.unique(box[raw[y0:y1 + 1, x0:x1 + 1]], return_counts=True)
    if not len(ids):
        return 0.0
    i = ids[counts.argmax()]
    return float(counts.max() / (labels == i).sum())


def _overlaps(a: tuple, b: tuple) -> bool:
    """True if two (y0, y1, x0, x1) inclusive boxes intersect."""
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


def _is_label_box(box: ScaleBar, bar: ScaleBar) -> bool:
    """True if ``box`` is a label background with ``bar`` drawn on/next to it:
    ``bar`` is shorter, lies horizontally within ``box`` (± its thickness)
    and touches it vertically (gap <= the thicker of the two + 3 px).
    """
    tol = max(box.thickness_px, bar.thickness_px)
    inside = bar.x0 >= box.x0 - tol and bar.x1 <= box.x1 + tol and bar.length_px < box.length_px
    gap = max(bar.y_top - box.y_bottom, box.y_top - bar.y_bottom, 0)
    return inside and gap <= tol + 3


def find_bar_candidates(
    image: np.ndarray,
    modes: tuple[str, ...] = BAR_MODES,
    thresholds: dict[str, int] | None = None,
    min_bar_length_frac: float = 0.05,
    min_aspect_ratio: float = 3.0,
    min_extent: float = 0.85,
    min_isolation: float = 0.9,
    min_contrast: float = 80.0,
    min_component_share: float = 0.5,
) -> list[ScaleBar]:
    """All distinct bar-shaped objects, longest first.

    Candidates must not touch the image border, must be at least
    ``min_aspect_ratio`` times longer than thick and fill at least
    ``min_extent`` of their bounding box. They must also lie on plain
    background on at least one side (``min_isolation``, see
    :func:`_isolation`) and differ from the background beyond their ends by
    at least ``min_contrast`` grey levels, and make up at least
    ``min_component_share`` of their connected shape (rejects strokes of
    letters, see :func:`_component_share`). The same bar found by several
    modes is kept once (the mode with the highest contrast), and a label
    box with a bar drawn on it is dropped in favour of the bar.
    """
    thresholds = {"dark": 175, "light": 200, "color": 100, **(thresholds or {})}
    h, w = image.shape[:2]
    found = []  # (box, contrast, ScaleBar)
    for mode in modes:
        feat = feature_image(image, mode)
        mask = bar_mask(feat, thresholds[mode], min_bar_length_frac)
        raw = feat > thresholds[mode]
        raw_labels = None  # labelled only if a candidate reaches the shape test
        for r in measure.regionprops(measure.label(mask)):
            y0, x0, y1, x1 = r.bbox  # y1, x1 exclusive
            if y0 == 0 or x0 == 0 or y1 == h or x1 == w:
                continue
            length, thick = x1 - x0, y1 - y0
            if length / thick < min_aspect_ratio or r.extent < min_extent:
                continue
            if _isolation(feat, thresholds[mode], y0, y1 - 1, x0, x1 - 1) < min_isolation:
                continue
            sx0, sx1, contrast = _subpixel_ends(feat, y0, y1 - 1, x0, x1 - 1)
            if contrast < min_contrast:
                continue
            if raw_labels is None:
                raw_labels = measure.label(raw)
            if _component_share(raw, raw_labels, y0, y1 - 1, x0, x1 - 1) < min_component_share:
                continue
            bar = ScaleBar(sx0, sx1, int(y0), int(y1 - 1), sx1 - sx0, int(thick), 0)
            found.append(((y0, y1 - 1, x0, x1 - 1), contrast, bar))

    distinct: list[tuple] = []
    for box, contrast, bar in sorted(found, key=lambda f: -f[1]):
        if not any(_overlaps(box, d[0]) for d in distinct):
            distinct.append((box, contrast, bar))
    bars = [b for b in (d[2] for d in distinct) if not any(_is_label_box(b, o) for o in
                                                            (d[2] for d in distinct) if o is not b)]
    bars.sort(key=lambda b: -b.length_px)
    for b in bars:
        b.n_candidates = len(bars)
    return bars


def detect_scale_bar(image: np.ndarray, **kwargs) -> ScaleBar:
    """Return the longest bar candidate (see :func:`find_bar_candidates`).

    Raises ScaleBarNotFound if there is none.
    """
    bars = find_bar_candidates(image, **kwargs)
    if not bars:
        raise ScaleBarNotFound("No scale-bar-shaped object found")
    return bars[0]


def load_overrides(path: str | Path | None) -> pd.DataFrame:
    """Read per-image calibration overrides, indexed by image file name.

    Columns: ``image`` (file name), and optionally ``px_per_um`` (skip
    detection) and/or ``bar_length_um`` (bar of a non-default length), and
    ``bar_x0, bar_y0, bar_x1, bar_y1`` (the bar line drawn by hand, from
    which px_per_um was computed; shown in the cell figure).
    Empty cells mean "use the default". Missing file -> empty table.
    """
    cols = ["px_per_um", "bar_length_um", "bar_x0", "bar_y0", "bar_x1", "bar_y1"]
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=cols, index=pd.Index([], name="image"))
    df = read_table(path, ["image"], numbers=tuple(cols), positive=("px_per_um", "bar_length_um"))
    return df.set_index("image").reindex(columns=cols)


def calibrate(image: np.ndarray, cfg: dict, override: dict | None = None) -> Calibration:
    """Return the px/µm calibration for an image.

    ``cfg`` is the ``calibration`` section of config.yaml; ``override`` is
    this image's row of the overrides CSV (if any). Precedence:
    per-image px_per_um > global px_per_um > detection, where detection
    divides the bar length by the per-image or default bar_length_um.

    The result has status "ambiguous" when several distinct bar-shaped
    objects were found: the longest is used, but the QC image must be
    checked. Raises ScaleBarNotFound if detection finds nothing.
    """
    override = {k: v for k, v in (override or {}).items() if pd.notna(v)}
    ppu = override.get("px_per_um") or cfg.get("px_per_um")
    bar_um = float(override.get("bar_length_um") or cfg["bar_length_um"])
    if ppu:
        ppu = float(ppu)
        keys = ("bar_x0", "bar_y0", "bar_x1", "bar_y1")
        line = tuple(float(override[k]) for k in keys) if all(k in override for k in keys) else None
        given_um = float(override["bar_length_um"]) if "bar_length_um" in override else None
        return Calibration(ppu, given_um if line else None, "manual", line=line)

    bar = detect_scale_bar(
        image,
        modes=tuple(cfg.get("bar_modes", BAR_MODES)),
        thresholds=cfg.get("thresholds"),
        min_bar_length_frac=cfg.get("min_bar_length_frac", 0.05),
        min_aspect_ratio=cfg.get("min_aspect_ratio", 3.0),
        min_extent=cfg.get("min_extent", 0.85),
        min_isolation=cfg.get("min_isolation", 0.9),
        min_contrast=cfg.get("min_contrast", 80.0),
        min_component_share=cfg.get("min_component_share", 0.5),
    )
    ppu = bar.length_px / bar_um
    status = "ok" if bar.n_candidates == 1 else "ambiguous"
    return Calibration(ppu, bar_um, "detected", status, bar)
