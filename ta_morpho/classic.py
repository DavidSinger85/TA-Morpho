"""Classic linear measurements of a test in broad (frontal) view, as used in
the testate amoeba literature (standard L / W / pseudostome width of
Hyalospheniidae descriptions).

All measurements are taken in the frame of the oral-aboral (long) axis: the
line from the aperture midpoint (middle of the chord between the two
aperture corners) to the fundus. One rule gives the fundus, whether the
point comes from the program or from the user (:func:`axis_fundus`): the
axis runs from the aperture midpoint through a target point, and the fundus
is where that line leaves the outline. The automatic target is the middle of
the far end of the test (the stretch of outline within ``fundus_far_frac``
of the largest distance from the aperture midpoint); a fundus set by hand is
the target itself, so it replaces the point, never the method. The axis is
not forced perpendicular to the aperture: the aperture angle measures an
oblique aperture or a bent neck. The length follows the
convention of Todorov et al. 2009 (J. Eukaryot. Microbiol. 56: 279-289,
Cyphoderia): a straight overall length, and the bend is measured
separately as the aperture angle.

- length: extent of the outline along the axis (aperture to fundus, lips included).
- width: largest extent across the axis (breadth).
- aperture width: distance between the two aperture corners.
- aperture angle: angle between the aperture chord and the long axis, in
  degrees (90 = aperture square to the axis; smaller = oblique aperture, e.g.
  a bent neck).
- widest position: distance from the oral end of the outline (lips included,
  as the length) to the widest section / length.
- widest position from the aperture plane: distance from the aperture plane
  (the line between the two corners) to the widest section / distance from
  that plane to the furthest outline point along the axis (the fundus,
  unless part of the far end reaches beyond it). Equal to the above unless
  the lips protrude beyond the corners.
- neck (only when the test has one). Along the axis, the section width of a
  necked test stays nearly constant (the neck) and then rises abruptly where
  the neck meets the body; a test without a neck widens fastest right after
  the aperture and then levels off. The width profile (width / test width
  against level / length) is differentiated over +-``neck_window``; the
  neck-body junction is the level where the slope increases most, between
  ``min_neck_start`` and the widest section (levels as fractions of the
  length from the oral end of the outline; the increase is defined only from
  2 x ``neck_window`` on, so a smaller ``min_neck_start`` has no effect).
  A neck is reported only if that
  increase is at least ``min_neck_slope_jump``; neck length = aperture plane
  to the junction, neck width = narrowest section in between (sections
  within ``lip_margin`` x length of the aperture plane are ignored, they
  only clip the tip of a lip). Otherwise NaN.
- neck jump: the largest increase of that slope (the neck criterion), given
  for every test, also below ``min_neck_slope_jump``: a continuous measure of
  how distinct the neck is (gradual taper ~0.5, clear neck 1.3-2, deep
  constriction > 2).
- aperture sag: signed largest distance of the outline between the two
  aperture corners (the rim) from their chord / aperture width; + = rim
  bulging out of the test (convex, curved rim), - = sunk in, ~0 = straight.
- protrusions (:func:`protrusions`): horns and spines, the pieces cut off by
  the same opening that cuts spines in the aperture search
  (``landmark.spine_opening_frac``), with their level along the axis.
- area, perimeter, circularity, solidity (area / convex-hull area), maximum
  and minimum Feret (caliper) diameters.
Ratios follow the literature (W/L, AW/L, AW/W, NL/L, NW/W, ...).
Depth needs a lateral view and is not measured.
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy.spatial import ConvexHull

from ta_morpho.landmark import spine_radius, without_spines
from ta_morpho.rays import outline_length, polygon_area, subpixel_outline

DEFAULTS = dict(section_step_px=1.0, lip_margin=0.03, neck_window=0.08,
                min_neck_slope_jump=0.5, min_neck_start=0.08, fundus_far_frac=0.1)


def oral_axis(aperture_start, aperture_end, centroid, fundus=None):
    """Origin (aperture midpoint), unit long axis pointing into the test, and
    the unit vector across it (along the aperture when the axis is square to
    it). Without ``fundus`` the axis is perpendicular to the aperture chord;
    with it, the axis points from the aperture midpoint to the fundus.
    Raises ValueError if the two corners coincide (no axis)."""
    a, b = np.asarray(aperture_start, float), np.asarray(aperture_end, float)
    m = (a + b) / 2
    if np.hypot(*(b - a)) < 1e-9:
        raise ValueError("the two aperture corners coincide: no oral axis")
    u = (b - a) / np.hypot(*(b - a))
    n = np.array([-u[1], u[0]])
    if np.dot(np.asarray(centroid) - m, n) < 0:
        n = -n
    if fundus is not None:
        d = np.asarray(fundus, float) - m
        # a fundus on the perpendicular (the usual case) keeps it exactly
        if np.hypot(*d) > 0 and np.dot(d, n) > 0 and abs(d[0] * n[1] - d[1] * n[0]) > 1e-6 * np.hypot(*d):
            n = d / np.hypot(*d)
            u = np.array([n[1], -n[0]]) if np.dot([n[1], -n[0]], u) >= 0 else np.array([-n[1], n[0]])
    return m, n, u


def _axis_end(poly: np.ndarray, m: np.ndarray, n: np.ndarray) -> float:
    """Level (along unit ``n`` from ``m``) where the line through ``m`` along
    ``n`` leaves the outline, furthest from ``m``."""
    t, s = (poly - m) @ n, (poly - m) @ np.array([-n[1], n[0]])
    t1, s1 = np.roll(t, -1), np.roll(s, -1)
    k = np.flatnonzero((s * s1 <= 0) & (s != s1))
    f = s[k] / (s[k] - s1[k])
    return float(np.max(t[k] + f * (t1[k] - t[k])))


def far_end(poly: np.ndarray, aperture_start, aperture_end, centroid,
            far_frac: float = DEFAULTS["fundus_far_frac"]) -> tuple[float, float]:
    """Automatic target of the axis: middle of the far end of the test, the
    stretch of outline within ``far_frac`` of the largest distance from the
    aperture midpoint (mean of its points weighted by outline length, so a
    flat or round fundus gives its middle and a single far bump does not
    dominate). Not on the outline: :func:`axis_fundus` makes it the fundus."""
    m, n, _ = oral_axis(aperture_start, aperture_end, centroid)
    rel = poly - m
    dist = np.hypot(*rel.T)
    seg = np.hypot(*(np.roll(poly, -1, 0) - poly).T)     # weight: outline length per point
    far = (dist >= (1 - far_frac) * dist.max()) & (rel @ n > 0)
    if not far.any():
        return tuple(float(v) for v in m + n)
    d = (rel[far] * seg[far, None]).sum(0) / seg[far].sum()
    return tuple(float(v) for v in m + d)


def body_outline(mask: np.ndarray, spine_frac: float) -> np.ndarray | None:
    """Outline of the test without its spines and horns (:func:`ta_morpho.landmark.without_spines`,
    disk of ``spine_frac`` x the minor axis), where the automatic fundus target
    is looked for; None when nothing is cut (``spine_frac`` 0)."""
    r = spine_radius(mask, spine_frac)
    return subpixel_outline(without_spines(mask, r)) if r > 0 else None


def axis_fundus(poly: np.ndarray, aperture_start, aperture_end, centroid, point=None,
                far_frac: float = DEFAULTS["fundus_far_frac"], body: np.ndarray | None = None) -> tuple[float, float]:
    """Fundus (aboral end of the long axis): where the line from the aperture
    midpoint through ``point`` leaves the outline, furthest from the aperture.
    ``point`` is a fundus set by hand, or None for the automatic target
    (:func:`far_end`); both then follow exactly the same rule, so the hand
    replaces only the point. A point on the aperture side of the aperture
    plane gives no direction: the axis is then perpendicular to the aperture
    (the caller flags it, :func:`fundus_behind_aperture`). Idempotent: the
    fundus given back as ``point`` returns the same fundus. ``body``
    (:func:`body_outline`): the automatic target is taken on it, so a spine or
    horn on the far end does not pull the axis; the fundus stays on ``poly``."""
    if point is None:
        point = far_end(poly if body is None else body, aperture_start, aperture_end, centroid, far_frac)
    m, n, _ = oral_axis(aperture_start, aperture_end, centroid)
    d = np.asarray(point, float) - m
    if not fundus_behind_aperture(aperture_start, aperture_end, centroid, point):
        n = d / np.hypot(*d)
    return tuple(float(v) for v in m + _axis_end(poly, m, n) * n)


def fundus_behind_aperture(aperture_start, aperture_end, centroid, point) -> bool:
    """True when ``point`` is on or above the aperture plane (no axis into the test)."""
    m, n, _ = oral_axis(aperture_start, aperture_end, centroid)
    d = np.asarray(point, float) - m
    return not (np.hypot(*d) > 0 and float(d @ n) > 0)


def section_widths(poly: np.ndarray, m, n, u, step: float = 1.0):
    """Width of the outline at levels t (distance from the aperture plane
    along the axis): outermost extent of the crossings of the line t = const.
    Returns (t, width) for t from the lowest to the highest outline point."""
    t_all, s_all = (poly - m) @ n, (poly - m) @ u
    t0, t1 = np.r_[t_all, t_all[0]][:-1], np.r_[t_all[1:], t_all[0]]
    s0, s1 = s_all, np.r_[s_all[1:], s_all[0]]
    levels = np.arange(t_all.min() + step / 2, t_all.max(), step)
    widths = np.full(len(levels), np.nan)
    for i, t in enumerate(levels):
        cross = (t0 - t) * (t1 - t) <= 0
        cross &= t0 != t1
        if cross.sum() >= 2:
            f = (t - t0[cross]) / (t1[cross] - t0[cross])
            s = s0[cross] + f * (s1[cross] - s0[cross])
            widths[i] = s.max() - s.min()
    return levels, widths


def feret(poly: np.ndarray) -> tuple[float, float]:
    """Maximum and minimum caliper diameters of a polygon (via its hull)."""
    h = poly[ConvexHull(poly).vertices]
    d = np.sqrt(((h[:, None] - h[None]) ** 2).sum(-1)).max()
    widths = []
    for p, q in zip(h, np.roll(h, -1, 0), strict=True):
        e = q - p
        e = e / np.hypot(*e)
        nrm = np.array([-e[1], e[0]])
        widths.append(np.ptp((h - p) @ nrm))
    return float(d), float(min(widths))


def aperture_sag(poly: np.ndarray, aperture_start, aperture_end, fundus) -> float:
    """Curvature of the rim: signed largest distance of the outline stretch
    between the two aperture corners (the one away from the fundus) from
    their chord, divided by the chord length. + = bulging away from the
    fundus (convex rim), - = sunk towards it."""
    a, b = np.asarray(aperture_start, float), np.asarray(aperture_end, float)
    chord = b - a
    w = np.hypot(*chord)
    if w == 0:
        return np.nan
    ia, ib = (int(np.argmin(np.hypot(*(poly - p).T))) for p in (a, b))
    i, j = min(ia, ib), max(ia, ib)
    inner, outer = poly[i:j + 1], np.r_[poly[j:], poly[:i + 1]]
    k = int(np.argmin(np.hypot(*(poly - np.asarray(fundus, float)).T)))
    rim = outer if i < k < j else inner                # the stretch without the fundus
    # Measured from the rim's own ends (the outline points nearest the corners):
    # corners kept off the outline (spine bases) must not count as curvature.
    a, b = poly[ia], poly[ib]
    chord = b - a
    if np.hypot(*chord) == 0:
        return np.nan
    nrm = np.array([-chord[1], chord[0]]) / np.hypot(*chord)
    if (np.asarray(fundus, float) - a) @ nrm > 0:      # normal pointing away from the fundus
        nrm = -nrm
    d = (rim - a) @ nrm
    return float(d[np.argmax(np.abs(d))] / w)       # / the aperture width (corners as placed)


def protrusions(mask: np.ndarray, r: int, aperture_start, aperture_end, centroid, fundus,
                min_level: float = 0.1) -> list[float] | None:
    """Horns and spines: the pieces of the mask cut off by an opening with a
    disk of radius ``r`` px (:func:`ta_morpho.landmark.without_spines`, the same
    cut as the aperture search) that are longer than 2r. Returns the level of
    each one along the oral-aboral axis (its centre, from the aperture plane,
    / plane-to-fundus distance: 0 = aperture, 1 = fundus), sorted. Pieces
    reaching below ``min_level`` are the aperture end itself (lips, teeth, or a
    neck narrower than the disk) and are left out. None when r = 0 (not
    measured)."""
    if r <= 0:
        return None
    body = without_spines(mask, r)
    rest = (mask & ~body).astype(np.uint8)
    m, n, _ = oral_axis(aperture_start, aperture_end, centroid, fundus)
    t_fundus = float((np.asarray(fundus, float) - m) @ n)
    if t_fundus <= 0:
        return []
    count, lab = cv2.connectedComponents(rest)
    levels = []
    for c in range(1, count):
        ys, xs = np.nonzero(lab == c)
        if len(xs) < 3:
            continue
        (_, _), (w, h), _ = cv2.minAreaRect(np.c_[xs, ys].astype(np.float32))
        if max(w, h) <= 2 * r:
            continue
        t = (np.c_[xs, ys] - m) @ n / t_fundus
        if t.min() >= min_level:                       # not touching the aperture end
            levels.append(round(float(t.mean()), 3))
    return sorted(levels)


def classic_measurements(poly: np.ndarray, aperture_start, aperture_end, centroid,
                         px_per_um: float, cfg: dict | None = None, fundus=None) -> dict:
    """Classic measurements (µm, ratios) of one outline; see module doc.
    ``poly`` is the closed outer outline (x, y) in pixels; ``fundus`` a
    fundus set by hand, or None for the automatic one: either way it goes
    through :func:`axis_fundus` (the same rule; a fundus that already went
    through it is unchanged).

    The aperture width is the distance between the two corners, which are
    centres of edge pixels of the mask (:func:`ta_morpho.landmark.outline`),
    while lengths and widths are taken on the sub-pixel outline, about half a
    pixel further out: the aperture width can differ by up to about 1 px from
    one taken on that outline (left so: moving the corners would change the
    results)."""
    c = {**DEFAULTS, **(cfg or {})}
    ppu = px_per_um if px_per_um else np.nan
    fundus = axis_fundus(poly, aperture_start, aperture_end, centroid, fundus, c["fundus_far_frac"])
    m, n, u = oral_axis(aperture_start, aperture_end, centroid, fundus)
    chord = np.asarray(aperture_end, float) - np.asarray(aperture_start, float)
    angle = float(np.degrees(np.arccos(min(1.0, abs(chord @ n) / np.hypot(*chord)))))
    t, w = section_widths(poly, m, n, u, c["section_step_px"])
    length = float(np.ptp((poly - m) @ n))
    width = float(np.ptp((poly - m) @ u))
    ap_w = float(np.hypot(*(np.asarray(aperture_end, float) - np.asarray(aperture_start, float))))
    i_max = int(np.nanargmax(w))
    area = polygon_area(poly)
    perim = outline_length(poly)
    fmax, fmin = feret(poly)
    out = dict(
        length_um=length / ppu, width_um=width / ppu, aperture_width_um=ap_w / ppu,
        aperture_angle_deg=angle,
        widest_position=float((t[i_max] - t.min()) / length),
        widest_position_aperture=float(t[i_max] / ((poly - m) @ n).max()),
        area_um2=area / ppu ** 2, perimeter_um=perim / ppu,
        circularity=4 * np.pi * area / perim ** 2,
        solidity=area / ConvexHull(poly).volume,
        feret_max_um=fmax / ppu, feret_min_um=fmin / ppu,
    )
    # Neck: abrupt steepening of the width profile (see module doc).
    neck_len = neck_w = np.nan
    g = np.linspace(0, 1, 401)                         # level / length, from the lowest point
    wg = np.interp(t.min() + g * length, t, np.nan_to_num(w, nan=0.0)) / width
    h = max(1, int(round(c["neck_window"] * 400)))
    slope = np.full_like(g, np.nan)
    slope[h:-h] = (wg[2 * h:] - wg[:-2 * h]) / (2 * c["neck_window"])
    jump = np.full_like(g, np.nan)
    jump[2 * h:-2 * h] = slope[3 * h:-h] - slope[h:-3 * h]
    widest = (t[i_max] - t.min()) / length
    ok = (g >= c["min_neck_start"]) & (g <= widest - c["neck_window"])
    cand = np.where(ok, jump, np.nan)       # empty when the widest section is near the aperture
    out["neck_jump"] = float(np.nanmax(cand)) if np.isfinite(cand).any() else np.nan
    out["aperture_sag"] = aperture_sag(poly, aperture_start, aperture_end, fundus)
    if np.isfinite(cand).any() and np.nanmax(cand) >= c["min_neck_slope_jump"]:
        k = int(np.nanargmax(cand))
        t_j = t.min() + g[k] * length                  # junction level (pixels from aperture plane)
        inside = (t >= c["lip_margin"] * length) & (t <= t_j)
        if inside.any():
            neck_len, neck_w = t_j, float(np.nanmin(w[inside]))
    out.update(neck_length_um=neck_len / ppu, neck_width_um=neck_w / ppu)
    L, W, A, NL, NW = length, width, ap_w, neck_len, neck_w
    out.update({
        "W/L": W / L, "AW/L": A / L, "AW/W": A / W,
        "NL/L": NL / L, "NW/L": NW / L, "NL/W": NL / W, "NW/W": NW / W,
        "NL/AW": NL / A, "NW/AW": NW / A, "NW/NL": NW / NL,
    })
    return {k: float(v) for k, v in out.items()}
