"""Clockwise radial profile.

Rays start at the centroid. Ray 0 points at the start landmark; ray k is
rotated clockwise (as displayed) by ``k * angle_step_deg``. Each ray is
intersected with a sub-pixel outline of the mask (the iso-line half-way
between test and background pixels, i.e. the true pixel edge).

If the outline is not star-shaped around the centroid (a ray crosses it
more than once, e.g. a curved neck), ``intersection`` decides which
crossing is used ("last" = outermost, "first" = innermost) and the
specimen is flagged "check".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage import measure

from ta_morpho.landmark import clockwise_angle


@dataclass
class Profile:
    """Radial profile of one specimen."""

    table: pd.DataFrame            # one row per angle
    status: str = "ok"             # "ok" or "check"
    messages: list[str] = field(default_factory=list)


def subpixel_outline(mask: np.ndarray) -> np.ndarray:
    """Closed outer outline of the mask as an (N, 2) array of x, y (sub-pixel).

    The mask is padded so the outline is closed even if it touches the
    border. The longest iso-contour (level 0.5) is returned.
    """
    padded = np.pad(mask.astype(float), 1)
    contours = measure.find_contours(padded, 0.5)
    if not contours:
        raise ValueError("Mask has no outline")
    rc = max(contours, key=len) - 1.0          # undo padding; (row, col)
    return rc[:, ::-1]                          # -> (x, y)


PERIMETER_SMOOTH_PX = 1.5   # removes the pixel staircase; see outline_length


def smooth_outline(poly: np.ndarray, sigma_px: float = PERIMETER_SMOOTH_PX,
                   step_px: float = 0.5) -> np.ndarray:
    """The closed outline ``poly`` resampled every ~``step_px`` along its
    length and smoothed along the outline with a Gaussian of ``sigma_px``.

    The iso-contour of a binary mask is a staircase of horizontal, vertical
    and 45° segments, so its length overestimates the true outline length
    by ~5 % whatever the resolution. A 1.5 px smoothing removes the
    staircase and keeps the length of discs, ellipses and squares within
    0.6 % of the true value; it shifts the outline by far less than a pixel,
    so it is used for lengths only.
    """
    q = np.r_[poly, poly[:1]]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    n = max(int(s[-1] / step_px), 16)
    t = np.linspace(0, s[-1], n, endpoint=False)
    r = np.c_[np.interp(t, s, q[:, 0]), np.interp(t, s, q[:, 1])]
    if sigma_px <= 0:
        return r
    sig = sigma_px / (s[-1] / n)
    return np.c_[ndi.gaussian_filter1d(r[:, 0], sig, mode="wrap"),
                 ndi.gaussian_filter1d(r[:, 1], sig, mode="wrap")]


def outline_length(poly: np.ndarray, sigma_px: float = PERIMETER_SMOOTH_PX) -> float:
    """Length (px) of the closed outline ``poly``, measured on
    :func:`smooth_outline` (no pixel-staircase bias)."""
    p = smooth_outline(poly, sigma_px)
    return float(np.sum(np.hypot(*np.diff(np.r_[p, p[:1]], axis=0).T)))


def polygon_area(poly: np.ndarray) -> float:
    """Unsigned area of a closed polygon (shoelace)."""
    x, y = poly[:, 0], poly[:, 1]
    return float(abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2)


def ray_crossings(center: tuple[float, float], angle_deg: float, poly: np.ndarray) -> np.ndarray:
    """Sorted distances from ``center`` to every crossing of the ray at
    screen angle ``angle_deg`` (0 = +x, increasing clockwise) with ``poly``.
    """
    c = np.asarray(center, float)
    d = np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])
    p, q = poly, np.roll(poly, -1, axis=0)
    e = q - p
    w = p - c
    denom = d[0] * e[:, 1] - d[1] * e[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / denom   # distance along ray
        u = (w[:, 0] * d[1] - w[:, 1] * d[0]) / denom         # position on segment
    eps = 1e-9  # a ray through a vertex hits two segments at u ~ 1 and u ~ 0
    ok = (denom != 0) & (t > eps) & (u >= -eps) & (u <= 1 + eps)
    return np.unique(np.round(t[ok], 6))  # rounding merges the vertex double hit


def radial_profile(
    mask: np.ndarray,
    centroid: tuple[float, float],
    landmark: tuple[float, float],
    angle_step_deg: float = 5.0,
    px_per_um: float | None = None,
    intersection: str = "last",
) -> Profile:
    """Radii from the centroid at fixed clockwise steps from the landmark.

    Returns a Profile whose table has, per angle: ``angle_deg`` (0 = landmark,
    clockwise), ``radius_px``, ``radius_um`` (NaN without calibration),
    ``radius_norm_mean`` (radius / mean radius), ``radius_norm_sqrt_area``
    (radius / sqrt(area)), ``n_crossings``, and the outline point ``x``, ``y``.
    """
    if angle_step_deg <= 0 or angle_step_deg > 180:
        raise ValueError(f"angle_step_deg must be in (0, 180], got {angle_step_deg}")
    if intersection not in ("first", "last"):
        raise ValueError(f"intersection must be 'first' or 'last', got {intersection!r}")
    poly = subpixel_outline(mask)
    area = polygon_area(poly)
    start = clockwise_angle(centroid, landmark)
    angles = np.arange(0.0, 360.0 - 1e-9, angle_step_deg)

    rows, multi, missing = [], [], []
    for a in angles:
        hits = ray_crossings(centroid, start + a, poly)
        if hits.size == 0:  # centroid outside the test (very concave shape)
            missing.append(a)
            r = np.nan
        else:
            r = hits[-1] if intersection == "last" else hits[0]
            if hits.size > 1:
                multi.append(a)
        rad = np.radians(start + a)
        rows.append({"angle_deg": a, "radius_px": r, "n_crossings": int(hits.size),
                     "x": centroid[0] + r * np.cos(rad),
                     "y": centroid[1] + r * np.sin(rad)})
    df = pd.DataFrame(rows)
    df["radius_um"] = df["radius_px"] / px_per_um if px_per_um else np.nan
    df["radius_norm_mean"] = df["radius_px"] / df["radius_px"].mean()
    df["radius_norm_sqrt_area"] = df["radius_px"] / np.sqrt(area)
    df = df[["angle_deg", "radius_px", "radius_um", "radius_norm_mean",
             "radius_norm_sqrt_area", "n_crossings", "x", "y"]]

    prof = Profile(df)
    if missing:
        prof.messages.append(f"{len(missing)} rays hit no outline (centroid outside test?)")
    if multi:
        prof.messages.append(f"{len(multi)} rays cross the outline more than once "
                             f"(using {intersection} crossing)")
    if px_per_um is None:
        prof.messages.append("no calibration: radius_um is empty")
    if prof.messages:
        prof.status = "check"
    return prof
