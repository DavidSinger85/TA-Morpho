"""Outline profile with equally spaced points anchored on the aperture.

The outline is walked clockwise (as displayed) from the start landmark
(aperture corner where a clockwise sweep crosses the aperture first). The
first ``n_aperture`` points are equally spaced along the aperture, from the
start corner to the other corner; the remaining points are equally spaced
around the body, from the other corner back to the start. Every specimen
therefore has the same number of points, and the aperture always occupies
the same columns (points 0 .. n_aperture - 1).

With a ``fundus`` (third anchor, as the landmark at the aboral end in
geometric morphometrics, e.g. Macumber et al. 2020), the body is split in
two equal-count sides: end corner -> fundus ("side1") and fundus -> start
corner ("side2"). The fundus is then always point n_aperture + half the body
points, so the two sides of different specimens correspond even when a test
is not symmetric.

Points 0 (start corner), n_aperture (other corner) and the fundus are
landmarks; all others are semilandmarks (see :func:`landmark_points`).

Each point is reported with its distance from the centroid (the radial
"footprint" value), its position along the outline and its coordinates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ta_morpho.rays import subpixel_outline


def _clockwise_order(poly: np.ndarray) -> np.ndarray:
    """Return the outline ordered clockwise as displayed (image y down): the
    shoelace sum is then positive."""
    x, y = poly[:, 0], poly[:, 1]
    return poly if np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) > 0 else poly[::-1]


def landmark_points(n_points: int, n_aperture: int, fundus: bool) -> list[int]:
    """Point numbers of the fixed landmarks: start corner, other corner and
    (with a fundus anchor) the fundus."""
    pts = [0, n_aperture]
    return pts + [n_aperture + (n_points - n_aperture) // 2] if fundus else pts


def anchored_profile(mask: np.ndarray, centroid, start, end, n_points: int = 250,
                     n_aperture: int = 22, px_per_um: float | None = None,
                     fundus=None) -> pd.DataFrame:
    """Equally spaced points on the outline, anchored on the aperture corners
    (and on the ``fundus`` point when given).

    Columns: point (0..n_points-1), segment ("aperture" / "body", or
    "aperture" / "side1" / "side2" with a fundus),
    position (fraction of the perimeter from the start corner), x, y,
    distance_px (from the centroid), distance_um (NaN without calibration),
    distance_norm (distance / mean distance).
    """
    if not 2 <= n_aperture < n_points - 2:
        raise ValueError("need 2 <= n_aperture < n_points - 2")
    poly = _clockwise_order(subpixel_outline(mask))
    closed = np.r_[poly, poly[:1]]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(closed, axis=0).T))]
    P = s[-1]
    tree = cKDTree(poly)
    s0 = s[tree.query(np.asarray(start, float))[1]]
    l_ap = (s[tree.query(np.asarray(end, float))[1]] - s0) % P     # start -> end, clockwise
    if l_ap > P / 2:
        raise ValueError("aperture segment longer than half the outline: check the corners")
    n_body = n_points - n_aperture
    if fundus is None:
        arc = np.r_[np.arange(n_aperture) * l_ap / n_aperture,
                    l_ap + np.arange(n_body) * (P - l_ap) / n_body]
        segment = ["aperture"] * n_aperture + ["body"] * n_body
    else:
        l_f = (s[tree.query(np.asarray(fundus, float))[1]] - s0) % P
        if not l_ap < l_f < P:
            raise ValueError("fundus not on the body outline")
        h = n_body // 2
        arc = np.r_[np.arange(n_aperture) * l_ap / n_aperture,
                    l_ap + np.arange(h) * (l_f - l_ap) / h,
                    l_f + np.arange(n_body - h) * (P - l_f) / (n_body - h)]
        segment = ["aperture"] * n_aperture + ["side1"] * h + ["side2"] * (n_body - h)
    t = np.mod(s0 + arc, P)
    x, y = np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])
    d = np.hypot(x - centroid[0], y - centroid[1])
    return pd.DataFrame({
        "point": np.arange(n_points),
        "segment": segment,
        "position": arc / P, "x": x, "y": y, "distance_px": d,
        "distance_um": d / px_per_um if px_per_um else np.nan,
        "distance_norm": d / d.mean(),
    })
