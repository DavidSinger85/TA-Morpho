"""Start landmark on the outline.

The landmark is the homologous start point of the radial profile. Sources,
in order of precedence:

1. The landmarks file (config ``paths.landmarks_csv``; columns ``image, x,
   y``), filled by hand, by clicking (``--click``) or by the desktop
   interface. The point is snapped to the nearest outline pixel.
   With the optional columns ``end_x, end_y`` the two points are the two
   aperture corners, set by hand (e.g. in the desktop interface) when the
   automatic detection fails: they replace the detected aperture, in either
   order (the start corner is chosen by the clockwise rule below). A corner
   further than the snap tolerance from the outline (bases of spines) is kept
   where it was placed, with a message; the status is not changed (placed by
   hand on purpose, it needs no second check). Optional
   ``fundus_x, fundus_y`` replace the automatic fundus (see ta_morpho/pipeline.py).
2. Automatic aperture detection (:func:`detect_aperture`; for round tests
   :func:`detect_aperture_corner_pair`, flagged "check"). The start is the
   aperture corner from which a clockwise sweep (as displayed, seen from the
   centroid) crosses the aperture first — i.e. the right-hand corner when
   the aperture points down. This does not depend on how the cell lies.
   A test cut by the image border (``cut``) gets no automatic aperture:
   the aperture may be outside the image, and the narrower end of a cut
   test is not reliably the aperture. It must be set by hand.
3. Fallback when no aperture is found (e.g. round Centropyxis):
   ``max_radius`` = outline point furthest from the centroid, or ``flag``
   = no landmark, image flagged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from ta_morpho.calibration import REFERENCE_PX_PER_UM
from ta_morpho.centroid import mask_centroid
from ta_morpho.segment import setting_px
from ta_morpho.tables import read_table

log = logging.getLogger(__name__)


@dataclass
class Aperture:
    """Aperture corners, detected or set by hand (pixel coordinates x, y).
    Detected and snapped corners are centres of edge pixels of the mask, not
    points of the sub-pixel outline (see :func:`ta_morpho.classic.classic_measurements`)."""

    start: tuple[float, float]    # corner where the clockwise sweep begins
    end: tuple[float, float]      # other corner
    midpoint: tuple[float, float]
    corner_turns: tuple[float, float]  # outline turning angle at each corner (deg; NaN if set by hand)


@dataclass
class Landmark:
    """Start landmark for one specimen."""

    x: float | None
    y: float | None
    source: str  # "manual", "csv", "aperture", "aperture_corners", "fallback_max_radius", "none"
    status: str = "ok"            # "ok", "check" or "failed"
    messages: list[str] = field(default_factory=list)
    aperture: Aperture | None = None


def outline(mask: np.ndarray) -> np.ndarray:
    """Outer contour of the largest object, as an (N, 2) float array of x, y.

    Points follow the boundary pixel by pixel.
    """
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("Mask has no outline")
    return max(contours, key=len)[:, 0, :].astype(float)


def turning_angles(contour: np.ndarray, k: int) -> np.ndarray:
    """Signed turning angle (deg) at each contour point, using neighbours ±k.

    Positive = convex corner, negative = concave, whatever the contour
    orientation. 0 on a straight line, close to 90 at a right-angle corner.
    """
    v_in = contour - np.roll(contour, k, axis=0)
    v_out = np.roll(contour, -k, axis=0) - contour
    cross = v_in[:, 0] * v_out[:, 1] - v_in[:, 1] * v_out[:, 0]
    dot = (v_in * v_out).sum(axis=1)
    ang = np.degrees(np.arctan2(cross, dot))
    # Shoelace signed area: sign gives the traversal direction.
    x, y = contour[:, 0], contour[:, 1]
    orientation = np.sign(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    return ang * orientation


def clockwise_angle(center: tuple[float, float], point: tuple[float, float]) -> float:
    """Screen angle (deg, 0-360) of ``point`` seen from ``center``.

    Image y points down, so atan2(dy, dx) increases clockwise as displayed.
    """
    return float(np.degrees(np.arctan2(point[1] - center[1], point[0] - center[0])) % 360)


def order_corners(center, a, b):
    """Return (start, end): start is the corner from which a clockwise sweep
    reaches the other corner in less than 180°, i.e. crosses the aperture first.
    """
    sweep = (clockwise_angle(center, b) - clockwise_angle(center, a)) % 360
    return (a, b) if sweep < 180 else (b, a)


def detect_aperture(mask: np.ndarray, cfg: dict) -> tuple[Aperture | None, str]:
    """Find the aperture corners of an elongated test.

    1. Principal axis of the mask; tests rounder than ``min_elongation``
       have no detectable aperture end.
    2. The aperture end is the narrower end (width measured over the last
       ``end_frac`` of the length); the ends must differ
       (width ratio < ``max_width_ratio``).
    3. On that end (last ``corner_region_frac`` of the length), one convex
       corner on each side of the axis: of the corners turning at least
       ``corner_strong_frac`` x the sharpest one on that side, the one nearest
       the end, and at least ``corner_min_lateral_frac`` x the half-width of
       the narrow end out from its middle (not the tip of a domed rim). Both must turn by
       at least ``min_corner_turn_deg`` (outline turning angle measured over
       ``corner_scale_frac`` of the perimeter). ``corner_strong_frac`` 1 and
       ``corner_min_lateral_frac`` 0 = the sharpest corner on each side.

    Returns (Aperture, "") or (None, reason).
    """
    cx, cy = mask_centroid(mask)
    c = np.array([cx, cy])
    ys, xs = np.nonzero(mask)
    pts = np.c_[xs, ys] - c
    evals, evecs = np.linalg.eigh(np.cov(pts.T))
    elong = float(np.sqrt(evals[1] / evals[0]))
    if elong < cfg.get("min_elongation", 1.05):
        return None, f"test too round (elongation {elong:.2f})"
    axis = evecs[:, 1]
    perp = np.array([-axis[1], axis[0]])

    cnt = outline(mask)
    t, s = (cnt - c) @ axis, (cnt - c) @ perp
    t0, t1 = t.min(), t.max()
    length = t1 - t0

    def width(sel):
        return float(s[sel].max() - s[sel].min()) if sel.any() else 0.0

    end_frac = cfg.get("end_frac", 0.15)
    w_lo, w_hi = width(t < t0 + end_frac * length), width(t > t1 - end_frac * length)
    if w_lo <= w_hi:
        ratio, near_end = w_lo / w_hi, (t < t0 + cfg.get("corner_region_frac", 0.25) * length)
        tip = t < t0 + end_frac * length
    else:
        ratio, near_end = w_hi / w_lo, (t > t1 - cfg.get("corner_region_frac", 0.25) * length)
        tip = t > t1 - end_frac * length
    if ratio >= cfg.get("max_width_ratio", 0.97):
        return None, f"both ends have similar width (ratio {ratio:.2f})"

    perim = cv2.arcLength(cnt.astype(np.float32).reshape(-1, 1, 2), True)
    k = max(3, int(round(cfg.get("corner_scale_frac", 0.0125) * perim)))
    turn = turning_angles(cnt, k)
    min_turn = cfg.get("min_corner_turn_deg", 22.0)
    toward_end = -t if w_lo <= w_hi else t
    peaks = set(corner_peaks(turn, k, min_turn))
    mid_s, half_w = (s[tip].max() + s[tip].min()) / 2, (s[tip].max() - s[tip].min()) / 2   # the narrow end
    corners = []
    for side in (s > 0, s < 0):
        sel = np.flatnonzero(near_end & side)
        if sel.size == 0:
            return None, "no outline on one side of the aperture end"
        # Of the strong corners on this side, the one nearest the end: the rim, not a
        # sharper bump or piece of debris further up the side. A corner lies out on its
        # side, not at the tip in the middle of a domed or pointed rim.
        strong = cfg.get("corner_strong_frac", 0.8) * turn[sel].max()
        out = sel[np.abs(s[sel] - mid_s) >= cfg.get("corner_min_lateral_frac", 0.3) * half_w]
        sel = out if out.size else sel
        cand = [j for j in sel if j in peaks and turn[j] >= strong]
        i = max(cand, key=lambda j: toward_end[j]) if cand else sel[np.argmax(turn[sel])]
        corners.append((tuple(cnt[i]), float(turn[i])))
    (a, ta), (b, tb) = corners
    start, end = order_corners((cx, cy), a, b)
    turns = (ta, tb) if start == a else (tb, ta)
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    if min(ta, tb) < min_turn:
        return None, f"aperture corners not sharp enough ({ta:.0f}°, {tb:.0f}° < {min_turn}°)"
    return Aperture(start, end, mid, turns), ""


def corner_peaks(turn: np.ndarray, k: int, min_turn: float) -> list[int]:
    """Indices of local maxima of ``turn`` >= ``min_turn``, at least 2k apart
    along the contour, sharpest first."""
    n = len(turn)
    peaks: list[int] = []
    for i in np.argsort(-turn):
        if turn[i] < min_turn:
            break
        if all(min(abs(i - j), n - abs(i - j)) > 2 * k for j in peaks):
            peaks.append(int(i))
    return peaks


def detect_aperture_corner_pair(mask: np.ndarray, cfg: dict) -> tuple[Aperture | None, str]:
    """Aperture of a test too round for :func:`detect_aperture` (e.g. a collar
    on a broad Nebela): the two sharpest convex corners that are close along
    the outline (shorter arc <= ``corner_pair_max_arc_frac`` of the
    perimeter), both turning at least ``min_corner_turn_deg``.

    Returns (Aperture, "") or (None, reason).
    """
    cnt = outline(mask)
    n = len(cnt)
    perim = cv2.arcLength(cnt.astype(np.float32).reshape(-1, 1, 2), True)
    k = max(3, int(round(cfg.get("corner_scale_frac", 0.0125) * perim)))
    turn = turning_angles(cnt, k)
    peaks = corner_peaks(turn, k, cfg.get("min_corner_turn_deg", 22.0))
    max_arc = cfg.get("corner_pair_max_arc_frac", 0.25) * n
    best = None
    for a_i, i in enumerate(peaks):
        for j in peaks[a_i + 1:]:
            if min(abs(i - j), n - abs(i - j)) <= max_arc:
                score = min(turn[i], turn[j])
                if best is None or score > best[0]:
                    best = (score, i, j)
    if best is None:
        return None, "no pair of sharp corners close together"
    _, i, j = best
    c = mask_centroid(mask)
    start, end = order_corners(c, tuple(cnt[i]), tuple(cnt[j]))
    turns = (float(turn[i]), float(turn[j])) if start == tuple(cnt[i]) else (float(turn[j]), float(turn[i]))
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    return Aperture(start, end, mid, turns), ""


def spine_radius(mask: np.ndarray, frac: float) -> int:
    """Radius (px) of the disk that cuts spines off: ``frac`` x the minor axis
    of the mask (0 = no cutting)."""
    if frac <= 0:
        return 0
    ys, xs = np.nonzero(mask)
    return max(1, int(round(frac * 4 * np.sqrt(np.linalg.eigvalsh(np.cov(np.c_[xs, ys].T))[0]))))


def without_spines(mask: np.ndarray, r: int) -> np.ndarray:
    """The mask opened by a disk of radius ``r`` px: spines, teeth and thin
    debris narrower than the disk are cut off (r = 0: unchanged). Corners
    found on it lie at the bases of the spines."""
    if r <= 0:
        return mask
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(opened)
    if n < 2:
        return mask
    return lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def on_outline(ap: Aperture, mask: np.ndarray, r: int, cfg: dict) -> Aperture:
    """Aperture found on a spine-free mask, its corners put back on the real
    outline: the sharpest convex point within ``r`` px (along the outline) of
    the nearest outline point. The opening rounds corners off; this restores
    them (a spine is longer than ``r``, so its tip is not reached)."""
    cnt = outline(mask)
    n = len(cnt)
    perim = cv2.arcLength(cnt.astype(np.float32).reshape(-1, 1, 2), True)
    turn = turning_angles(cnt, max(3, int(round(cfg.get("corner_scale_frac", 0.0125) * perim))))
    out = []
    for p in (ap.start, ap.end):
        i = int(np.argmin(np.hypot(cnt[:, 0] - p[0], cnt[:, 1] - p[1])))
        win = np.arange(i - r, i + r + 1) % n
        j = int(win[np.argmax(turn[win])])
        if turn[j] < cfg.get("min_corner_turn_deg", 22.0):
            j = i                   # no corner nearby (a spine base): the nearest point
        out.append(((float(cnt[j, 0]), float(cnt[j, 1])), float(turn[j])))
    (a, ta), (b, tb) = out
    start, end = order_corners(mask_centroid(mask), a, b)
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    return Aperture(start, end, mid, (ta, tb) if start == a else (tb, ta))


def snap_to_outline(point: tuple[float, float], contour: np.ndarray) -> tuple[tuple[float, float], float]:
    """Nearest outline point to ``point`` and its distance in px."""
    d = np.hypot(contour[:, 0] - point[0], contour[:, 1] - point[1])
    i = int(np.argmin(d))
    return (float(contour[i, 0]), float(contour[i, 1])), float(d[i])


LANDMARK_COLUMNS = ["x", "y", "end_x", "end_y", "fundus_x", "fundus_y"]


def load_landmarks(path: str | Path | None) -> pd.DataFrame:
    """Read the landmarks CSV indexed by image; empty if absent. Columns
    ``x, y`` (start point, or first aperture corner), optional ``end_x, end_y``
    (second aperture corner) and ``fundus_x, fundus_y``; empty cells = automatic."""
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=LANDMARK_COLUMNS, index=pd.Index([], name="image"))
    df = read_table(path, ["image"], numbers=tuple(LANDMARK_COLUMNS)).set_index("image")
    return df.reindex(columns=LANDMARK_COLUMNS).astype(float).dropna(how="all")


def find_landmark(mask: np.ndarray, cfg: dict, csv_point: tuple[float, float] | None = None,
                  csv_end: tuple[float, float] | None = None,
                  contact: dict[str, int] | None = None,
                  scale: float = REFERENCE_PX_PER_UM) -> Landmark:
    """Start landmark for one specimen (see module docstring for precedence).

    ``cfg`` is the ``landmark`` section of config.yaml. The aperture is
    detected whenever possible (also stored when a CSV point is used).
    ``csv_point`` and ``csv_end`` together are two aperture corners set by hand.
    ``contact`` = mask pixels on each image edge (``segment.border_contact``):
    from ``cut_contact_um`` on one edge the test is cut and, without a point
    set by hand, the landmark fails. ``scale`` (px/µm) converts the µm settings
    (see :func:`ta_morpho.segment.setting_px`).
    """
    contour = outline(mask)
    tol = setting_px(cfg, "snap_tolerance", 2.0, 15, scale)

    if csv_point is not None and csv_end is not None:
        # Corners set by hand stay where they were placed: on a spined or toothed
        # aperture the opening is at the bases of the spines, which may lie off the
        # outline. Points within the snap tolerance go onto the outline; the start
        # landmark of the rays is the outline point nearest the start corner.
        (a, da), (b, db) = snap_to_outline(csv_point, contour), snap_to_outline(csv_end, contour)
        a = a if da <= tol else (float(csv_point[0]), float(csv_point[1]))
        b = b if db <= tol else (float(csv_end[0]), float(csv_end[1]))
        if np.hypot(a[0] - b[0], a[1] - b[1]) < 1.0:
            return Landmark(None, None, "none", "failed",
                            ["the two aperture corners set by hand are less than 1 px apart (after snapping "
                             "to the outline): place them on either side of the aperture"])
        start, end = order_corners(mask_centroid(mask), a, b)
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        ap = Aperture(start, end, mid, (np.nan, np.nan))
        lm = Landmark(*snap_to_outline(start, contour)[0], "manual", aperture=ap)
        if max(da, db) > tol:
            lm.messages.append(f"an aperture corner set by hand is {max(da, db):.0f} px off the outline: "
                               "kept where it was placed")
        return lm

    r = spine_radius(mask, cfg.get("spine_opening_frac", 0.06))
    ap, reason = detect_aperture(without_spines(mask, r), cfg)
    if ap is not None and r:
        ap = on_outline(ap, mask, r, cfg)
    elif r:
        ap, reason = detect_aperture(mask, cfg)   # the opening rounded the corners off
    if ap is not None and np.hypot(ap.start[0] - ap.end[0], ap.start[1] - ap.end[1]) < 1.0:
        ap, reason = None, "the two aperture corners found coincide"
    min_cut = setting_px(cfg, "cut_contact", 1.4, 10, scale)
    cut = [side for side, n in (contact or {}).items() if n >= min_cut]
    if cut:
        ap = None
    if csv_point is not None:
        (x, y), d = snap_to_outline(csv_point, contour)
        lm = Landmark(x, y, "csv", aperture=ap)
        if d > tol:
            lm.status = "check"
            lm.messages.append(f"CSV point is {d:.0f} px from the outline (> {tol:.0f} px)")
        return lm

    if cut:
        return Landmark(None, None, "none", "failed",
                        [f"test cut by the image border ({', '.join(cut)}): the aperture may be "
                         "outside the image; set the aperture corners by hand or use an "
                         "uncropped image"])
    if ap is not None:
        return Landmark(*ap.start, "aperture", aperture=ap)
    if cfg.get("corner_pair_fallback", True):
        ap2, reason2 = detect_aperture_corner_pair(mask, cfg)
        if ap2 is not None:
            return Landmark(*ap2.start, "aperture_corners", "check",
                            [f"{reason}; aperture taken as the closest pair of sharp corners "
                             f"({ap2.corner_turns[0]:.0f}°, {ap2.corner_turns[1]:.0f}°)"],
                            aperture=ap2)
        reason += f"; {reason2}"

    fallback = cfg.get("fallback", "max_radius")
    msg = f"no aperture: {reason}"
    if fallback == "max_radius":
        cx, cy = mask_centroid(mask)
        i = int(np.argmax(np.hypot(contour[:, 0] - cx, contour[:, 1] - cy)))
        lm = Landmark(float(contour[i, 0]), float(contour[i, 1]),
                      "fallback_max_radius", "check")
        lm.messages.append(msg + "; start = outline point furthest from centroid")
        return lm
    return Landmark(None, None, "none", "failed", [msg + "; add it to landmarks.csv"])


def click_landmarks(paths: list[Path], csv_path: Path) -> None:
    """Show each image and record one click per image into ``csv_path``.

    Left-click sets the point; close the window (or press Enter) to accept.
    Existing rows for other images are kept; rows for clicked images are
    replaced (aperture corners or fundus set before are cleared).
    """
    import matplotlib.pyplot as plt
    from ta_morpho.image_io import load_image

    df = load_landmarks(csv_path)
    for path in paths:
        img = load_image(path)
        fig, ax = plt.subplots(figsize=(10, 7))
        ax.imshow(img)
        ax.set_title(f"{path.name}: click the start landmark, then Enter")
        pts = plt.ginput(n=1, timeout=0)
        plt.close(fig)
        if pts:
            df.loc[path.name, LANDMARK_COLUMNS] = np.nan
            df.loc[path.name, ["x", "y"]] = pts[0]
            log.info("%s: landmark (%.1f, %.1f)", path.name, *pts[0])
        else:
            log.warning("%s: no click recorded", path.name)
    df.reset_index().to_csv(csv_path, index=False)
    log.info("Wrote %s", csv_path)
