"""Holes and bumps that break the continuity of the outline (e.g. the
neck-body constriction of Apodera, bumps on the neck of Certesella), added
by hand: the user places each one (centre on the outline and a circle) and
it is measured here. There is no automatic detection.

1. The outline is resampled every ``step_um`` µm along its length.
2. Turning angle at each point over +-``turn_um`` µm (positive = convex).
3. Hole = a concave run (turning < 0); its depth is the largest distance from
   the outline to the straight chord across the run.
4. Bump = the convex stretch between two concave runs (inside a circle,
   runs at least ``flank_um`` deep); its height is the largest distance to
   the chord between the deepest points of the two runs.
5. A feature delimited by a circle (:func:`measure_stretch`, the desktop
   interface) is measured on the outline inside the circle. One given by its
   centre only (a corrections CSV without ``radius_px``) is the nearest
   concave run (hole) or convex stretch (bump) within ``match_pct`` % of the
   perimeter (:func:`measure_at`); a bump is then not wider than
   ``bump_max_um`` (and ``bump_max_frac`` of the perimeter) and does not
   contain an aperture corner (``corner_um``).
   The two ways can give different sizes for the same feature: without a
   circle a hole is the whole concave run and its depth is taken from the
   chord across it; with a circle only the outline inside the circle counts
   (rims = the most outward point on each side), so the depth and width
   depend on the circle drawn. A bump likewise starts from the neighbouring
   concave runs without a circle, from those at least ``flank_um`` deep
   inside the circle (else the circle ends) with one. The desktop interface
   always stores a circle; a centre without a circle comes only from a
   corrections CSV written by hand.

Positions are fractions of the perimeter, clockwise (as displayed) from the
start landmark, as in :mod:`ta_morpho.outline_profile`. :func:`locate` places each
feature in the frame shared with the other outputs: point and stretch of the
anchored outline profile, level along the oral-aboral axis, region (aperture,
neck, body) and ray angle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage import measure

from ta_morpho.classic import oral_axis
from ta_morpho.landmark import clockwise_angle
from ta_morpho.rays import PERIMETER_SMOOTH_PX
from ta_morpho.tables import read_table

DEFAULTS = dict(step_um=0.1, turn_um=5.0, flank_um=0.2, bump_max_um=40.0, bump_max_frac=0.15,
                corner_um=1.5, match_pct=3.0)
KINDS = ("hole", "bump")


def _runs(flag):
    """Circular runs of True, as index arrays."""
    if flag.all():
        return [np.arange(len(flag))]
    if not flag.any():
        return []
    idx = np.roll(np.arange(len(flag)), -int(np.argmin(flag)))
    f = flag[idx]
    starts = np.flatnonzero(f & ~np.r_[False, f[:-1]])
    ends = np.flatnonzero(f & ~np.r_[f[1:], False]) + 1
    return [idx[a:b] for a, b in zip(starts, ends, strict=True)]


def _chord_dist(pts, a, b):
    d = b - a
    return np.abs(d[0] * (pts[:, 1] - a[1]) - d[1] * (pts[:, 0] - a[0])) / max(np.hypot(*d), 1e-9)


def outline_points(mask, px_per_um, step_um=0.1):
    """Outer outline resampled every ``step_um`` µm, clockwise as displayed."""
    cnt = max(measure.find_contours(np.pad(mask, 1).astype(float), 0.5), key=len)[:-1, ::-1] - 1
    x, y = cnt[:, 0], cnt[:, 1]
    if np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) < 0:
        cnt = cnt[::-1]
    c = np.r_[cnt, cnt[:1]]
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(c, axis=0).T))]
    t = np.linspace(0, s[-1], max(int(s[-1] / (step_um * px_per_um)), 50), endpoint=False)
    return np.c_[np.interp(t, s, c[:, 0]), np.interp(t, s, c[:, 1])]


def step_lengths(P, px_per_um):
    """True length (µm) of each step P[j] -> P[j+1] of an ``outline_points``
    outline. The outline follows the pixel staircase, whose length is ~5 %
    too long; the steps are measured on the outline smoothed by
    ``PERIMETER_SMOOTH_PX`` (as the perimeter, :func:`ta_morpho.rays.outline_length`).
    Holes and bumps themselves are still found on P, unchanged."""
    sig = PERIMETER_SMOOTH_PX / max(np.median(np.hypot(*np.diff(P, axis=0).T)), 1e-9)
    Q = np.c_[ndi.gaussian_filter1d(P[:, 0], sig, mode="wrap"),
              ndi.gaussian_filter1d(P[:, 1], sig, mode="wrap")]
    return np.hypot(*(np.roll(Q, -1, 0) - Q).T) / px_per_um


def arc_um(steps, idx):
    """Outline length (µm) from the first to the last index of the
    consecutive (circular) index run ``idx``."""
    return float(steps[np.asarray(idx)[:-1]].sum())


def concave_runs(P, px_per_um, c, steps=None):
    """Concave runs of the outline P (turning angle over +-turn_um < 0), each
    with its deepest point: dicts with kind "hole", i, size_um, width_um."""
    k = int(round(c["turn_um"] / c["step_um"]))
    v1, v2 = P - np.roll(P, k, 0), np.roll(P, -k, 0) - P
    turn = np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(1))
    if np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1]) < 0:
        turn = -turn
    conc = []
    for m in _runs(turn < 0):
        dd = _chord_dist(P[m], P[m[0]], P[m[-1]]) / px_per_um
        i = int(m[np.argmax(dd)])
        reach = max(np.hypot(*(P[m[0]] - P[i])), np.hypot(*(P[m[-1]] - P[i]))) / px_per_um
        width = len(m) * c["step_um"] if steps is None else arc_um(steps, m)
        conc.append(dict(kind="hole", i=i, size_um=float(dd.max()), width_um=width,
                         radius_um=float(reach)))
    conc.sort(key=lambda h: h["i"])
    return conc


def candidates(mask, px_per_um, corners=(), cfg=None):
    """Every hole and bump of one outline, without any size threshold:
    (points, list of dicts with kind, i (index in points), size_um,
    width_um, radius_um). Each concave run is a hole; each convex stretch
    between two neighbouring concave runs is a bump, unless wider than
    ``bump_max_um`` / ``bump_max_frac`` of the perimeter or containing an
    aperture corner."""
    c = {**DEFAULTS, **(cfg or {})}
    ppu = px_per_um
    P = outline_points(mask, ppu, c["step_um"])
    n = len(P)
    steps = step_lengths(P, ppu)
    conc = concave_runs(P, ppu, c, steps)
    feats = list(conc)
    max_w = min(c["bump_max_um"], c["bump_max_frac"] * n * c["step_um"])
    for h1, h2 in (zip(conc, conc[1:] + conc[:1], strict=True) if len(conc) >= 2 else []):
        i1, i2 = h1["i"], h2["i"]
        seg = np.arange(i1, i2 + (n if i2 <= i1 else 0)) % n
        w = len(seg) * c["step_um"]
        if w > max_w:
            continue
        if any(np.hypot(*(P[seg] - np.asarray(cc, float)).T).min() / ppu < c["corner_um"] for cc in corners):
            continue
        dd = _chord_dist(P[seg], P[i1], P[i2]) / ppu
        top = int(seg[np.argmax(dd)])
        reach = max(np.hypot(*(P[i1] - P[top])), np.hypot(*(P[i2] - P[top]))) / ppu
        feats.append(dict(kind="bump", i=top, size_um=float(dd.max()), width_um=arc_um(steps, seg),
                          radius_um=float(reach)))
    return P, feats


def measure_at(mask, px_per_um, landmark, point, kind, corners=(), cfg=None):
    """Measure a hole or bump the user pointed at (centre only, no circle):
    the nearest of the :func:`candidates` of that kind. Returns a feature
    dict (kind, position, size_um, width_um, x, y) or None if no concave run
    (hole) or convex stretch between two concave runs (bump) lies within
    ``match_pct`` % of the perimeter of ``point``."""
    c = {**DEFAULTS, **(cfg or {})}
    P, feats = candidates(mask, px_per_um, corners, c)
    n = len(P)
    tol = c["match_pct"] / 100 * n * c["step_um"] * px_per_um
    cand = [f for f in feats if f["kind"] == kind]
    if not cand:
        return None
    d = [np.hypot(*(P[f["i"]] - np.asarray(point, float))) for f in cand]
    k = int(np.argmin(d))
    if d[k] > tol:
        return None
    f = cand[k]
    k0 = cKDTree(P).query(landmark)[1]
    x, y = P[f["i"]]
    return dict(kind=kind, position=((f["i"] - k0) % n) / n, size_um=f["size_um"],
                width_um=f["width_um"], x=float(x), y=float(y))


def manual_features(corrections, mask, px_per_um, landmark, corners=(), cfg=None):
    """Measure the holes and bumps added by the user on one outline.

    ``corrections``: rows with ``kind`` ("hole" or "bump"), ``x``, ``y``,
    optional ``radius_px`` and ``note``. With a radius, the stretch delimited
    by the user (:func:`measure_stretch`); without one, the feature found near
    (x, y) (:func:`measure_at`).

    Returns (features with their ``note``, numbered clockwise from the start
    landmark; outline status "ok" or "no features"; messages for additions
    that can no longer be measured).
    """
    c = {**DEFAULTS, **(cfg or {})}
    feats, messages = [], []
    for row in corrections:
        kind = row.get("kind")
        if kind not in KINDS:
            raise ValueError(f"hole/bump kind must be one of {KINDS}, got {kind!r}")
        x, y, note = float(row["x"]), float(row["y"]), row.get("note") or ""
        r = row.get("radius_px")
        r = float(r) if r not in (None, "") and np.isfinite(float(r)) else None
        f = (measure_stretch(mask, px_per_um, landmark, (x, y), r, kind, c) if r
             else measure_at(mask, px_per_um, landmark, (x, y), kind, corners, c))
        if f is None:
            messages.append(f"the {kind} added at ({x:.0f}, {y:.0f}) can no longer be measured")
        else:
            feats.append({**f, "note": note or "added by the user"})
    feats.sort(key=lambda f: f["position"])
    for i, f in enumerate(feats, 1):
        f["number"] = i
    return feats, ("ok" if feats else "no features"), messages


def feature_radius_px(f, px_per_um):
    """Extent of a feature (centre to its farther end point), in px: the
    user's circle, else half the width."""
    return float(f["radius_px"]) if f.get("radius_px") else f["width_um"] / 2 * px_per_um


def locate(features, profile, aperture_start, aperture_end, centroid, fundus, landmark,
           px_per_um, neck_level_px=np.nan):
    """Add the position of each feature (in place) in the frame shared with
    the other outputs:

    - ``angle_deg``: clockwise from the start landmark, seen from the
      centroid (the frame of the radial profile, r0 ... r355);
    - ``axis_position``: level along the oral-aboral axis from the aperture
      plane, divided by the level of the fundus (0 = aperture plane,
      1 = fundus; < 0 on lips that protrude beyond the corners);
    - ``profile_point`` and ``stretch``: nearest point of the anchored outline
      ``profile`` (:func:`ta_morpho.outline_profile.anchored_profile`) and its
      segment (aperture / side1 / side2, or body); empty without a profile;
    - ``region``: "aperture" on the aperture stretch; when the test has a
      neck (``neck_level_px``: level of the neck-body junction), "junction"
      for a hole whose deepest point is within its own radius (centre to its
      farther end) of the junction level (the neck-body constriction), else
      "neck" or "body" by the level of its point (deepest point / top;
      the circle centre for a stretch delimited by hand); "body"
      without a neck.
    """
    m, n, _ = oral_axis(aperture_start, aperture_end, centroid, fundus)
    level_f = float((np.asarray(fundus, float) - m) @ n)
    a0 = clockwise_angle(centroid, landmark)
    pts = None if profile is None else profile[["x", "y"]].to_numpy()
    for f in features:
        p = np.array([f["x"], f["y"]], float)
        level = float((p - m) @ n)
        f["angle_deg"] = (clockwise_angle(centroid, p) - a0) % 360
        # a fundus on or above the aperture plane (dragged there by hand) gives no axis
        f["axis_position"] = level / level_f if level_f > 1.0 else np.nan
        if pts is None:
            f["profile_point"], f["stretch"], f["region"] = np.nan, "", ""
            continue
        k = int(np.argmin(np.hypot(*(pts - p).T)))
        f["profile_point"], f["stretch"] = int(profile["point"].iloc[k]), profile["segment"].iloc[k]
        if f["stretch"] == "aperture":
            f["region"] = "aperture"
        elif not np.isfinite(neck_level_px):
            f["region"] = "body"
        elif f["kind"] == "hole" and abs(level - neck_level_px) <= feature_radius_px(f, px_per_um):
            f["region"] = "junction"
        else:
            f["region"] = "neck" if level <= neck_level_px else "body"
    return features


def load_feature_corrections(path) -> dict[str, list[dict]]:
    """Read the hole/bump CSV (columns image, action = "add", kind = "hole" |
    "bump", x, y, radius_px (optional), note): {image: [rows]}; empty if the
    file is absent. Raises ValueError on another action or kind."""
    if path is None or not Path(path).exists():
        return {}
    df = read_table(path, ["image", "action", "kind", "x", "y"], numbers=("x", "y", "radius_px"),
                    positive=("radius_px",), unique=None, filled=("image", "x", "y"))
    out: dict[str, list[dict]] = {}
    for row in df.to_dict("records"):
        if row.get("action") != "add" or row.get("kind") not in KINDS:
            raise ValueError(f"{Path(path).name}, {row.get('image')}: a hole/bump row needs action 'add' "
                             f"and kind 'hole' or 'bump' (got {row.get('action')!r}, {row.get('kind')!r})")
        out.setdefault(row["image"], []).append(row)
    return out


def measure_stretch(mask, px_per_um, landmark, center, radius_px, kind, cfg=None):
    """Measure a hole or bump delimited by the user: the outline stretch
    around ``center`` (snapped to the outline) that lies within ``radius_px``.

    - Same geometry as :func:`candidates`, within the circle. Bump: on
      each side of the centre, the deepest point (furthest inward) of the
      stretch; the height is how far the outline between these two points
      goes outward beyond the line joining them (as a bump between two
      concave runs is measured from their deepest points). Hole: on
      each side, the highest point (rim); the depth is how far the outline
      between the rims goes inward. width_um = outline length between the two
      points. Inward / outward are judged from the line joining the two ends
      of the stretch (where the circle crosses the outline).
    - None when the outline does not go that way at all (wrong kind for the
      place, e.g. a hole on a convex stretch).
    - position = the centre, as a fraction of the perimeter clockwise from
      ``landmark``.

    Returns a feature dict as :func:`measure_at`, with ``radius_px``, or
    None when the stretch is too short or of the other kind.
    """
    c = {**DEFAULTS, **(cfg or {})}
    P = outline_points(mask, px_per_um, c["step_um"])
    n = len(P)
    k = int(cKDTree(P).query(np.asarray(center, float))[1])
    d = np.hypot(*(P - P[k]).T)
    # contiguous stretch around k within the radius (walk both ways along the outline)
    lo = 0
    while lo < n // 2 and d[(k - lo - 1) % n] <= radius_px:
        lo += 1
    hi = 0
    while hi < n // 2 and d[(k + hi + 1) % n] <= radius_px:
        hi += 1
    idx = np.arange(k - lo, k + hi + 1) % n
    if len(idx) < 5:
        return None
    def signed_in(pts, a, b):
        """Distance (µm) of pts on the inner side of the line a-b (negative: outer
        side). P runs clockwise as displayed (y down): inside is where
        cross(b - a, p - a) > 0."""
        d = b - a
        return (d[0] * (pts[:, 1] - a[1]) - d[1] * (pts[:, 0] - a[0])) / max(np.hypot(*d), 1e-9) / px_per_um

    sign = 1.0 if kind == "hole" else -1.0          # hole: inward is "down"; bump: outward is "up"
    centre = lo                                     # position of k inside idx
    if kind == "hole":
        # rims: on each side, the most outward point (judged from the line between the circle ends)
        ref = signed_in(P[idx], P[idx[0]], P[idx[-1]])
        i1 = int(np.argmin(ref[:centre + 1]))
        i2 = centre + int(np.argmin(ref[centre:]))
    else:
        # as candidates(): from the deepest points of the flanking hollows, i.e. on each
        # side the nearest concave run (>= flank_um deep) inside the circle; else the circle end
        pos = {int(j): q for q, j in enumerate(idx)}
        flanks = [pos[h["i"]] for h in concave_runs(P, px_per_um, c)
                  if h["size_um"] >= c["flank_um"] and h["i"] in pos]
        i1 = max([q for q in flanks if q < centre], default=0)
        i2 = min([q for q in flanks if q > centre], default=len(idx) - 1)
    if i2 - i1 < 2:
        return None
    seg = idx[i1:i2 + 1]
    dd = sign * signed_in(P[seg], P[idx[i1]], P[idx[i2]])
    if dd.max() <= 0.05:                            # < 0.05 µm: nothing of that kind here
        return None
    k0 = cKDTree(P).query(landmark)[1]
    return dict(kind=kind, position=((k - k0) % n) / n, size_um=float(dd.max()),
                width_um=arc_um(step_lengths(P, px_per_um), seg),
                x=float(P[k, 0]), y=float(P[k, 1]), radius_px=float(radius_px))
