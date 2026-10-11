"""Segmentation of the test (shell) outline.

Classical approach, for a test standing out from a fairly uniform
background:

1. Estimate the background colour from the image border (median, CIE Lab).
2. Decide whether the background is "light" (bright-field light
   microscopy: dark test on a pale background) or "dark" (SEM, dark-field
   panels: bright test on a dark background), see :func:`detect_background`.
   A per-image override CSV can force the choice.
3. Score every pixel against the background:
   - dark background: colour distance ΔE (any difference counts);
   - light background: only pixels DARKER than the background, or of a
     different colour, count. The bright halo that bright-field optics
     draw just outside the wall is lighter than the background, so it is
     left out and the outline follows the wall itself.
4. Threshold, close small gaps in the wall, fill holes (the cytoplasm and
   the hyaline interior become part of the test), open to detach debris.
5. Keep the largest connected object.
6. Smooth the outline at a fixed physical scale (Gaussian, ``smooth_um``
   µm, needs the calibration): removes pixel-level jaggedness and edge
   noise the same way at every resolution. Skipped without calibration.

The mask covers the whole test up to the OUTER edge of the wall.

Manual correction: if ``<masks_dir>/<image stem>_mask.png`` exists (white =
test), it is used instead of the automatic mask. The automatic mask is
saved to ``results/masks/`` so it can be edited (ImageJ, GIMP...) and
copied there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import measure

from ta_morpho.calibration import REFERENCE_PX_PER_UM
from ta_morpho.image_io import read_image, write_image
from ta_morpho.tables import read_table

BACKGROUNDS = ("light", "dark")


@dataclass
class Segmentation:
    """Result of segmenting one image."""

    mask: np.ndarray              # bool, True = test
    source: str                   # "auto" or "manual"
    status: str = "ok"            # "ok", "check" or "failed"
    messages: list[str] = field(default_factory=list)
    background: str = ""          # "light", "dark" ("" for manual masks)
    background_source: str = ""   # "auto" or "override"
    smooth_px: float = 0.0        # Gaussian sigma applied to the mask (0 = none)
    unsmoothed: np.ndarray | None = None  # mask before smoothing (crop check)
    frame: tuple[int, int, int, int] = (0, 0, 0, 0)  # edge bands left out: top, bottom, left, right (px)

    @property
    def crop_check_mask(self) -> np.ndarray:
        """Mask for the straight-edge (crop) check: before smoothing, since
        smoothing can turn a nearly straight edge into a long exact run."""
        return self.mask if self.unsmoothed is None else self.unsmoothed


def to_lab(image: np.ndarray) -> np.ndarray:
    """RGB uint8 -> CIE Lab float32 (L in 0-100)."""
    return cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def estimate_background(image: np.ndarray, border: int = 10) -> np.ndarray:
    """Median Lab colour of a ``border``-pixel frame around the image."""
    lab = to_lab(image)
    frame = np.ones(lab.shape[:2], bool)
    frame[border:-border, border:-border] = False
    return np.median(lab[frame], axis=0)


def frame_line(lines: np.ndarray, start: int, width: int, border: int,
               contrast: float = 40.0, min_peak: float = 80.0, min_flat_share: float = 0.8) -> int:
    """Width of a thin frame line in ``lines`` (grey rows, from an image edge)
    from row ``start``: of the next ``width`` rows, up to the last one whose
    median grey differs by more than ``contrast`` from the ``border`` rows
    after them, provided one differs by at least ``min_peak`` (a real line)
    and those rows are a background (``min_flat_share`` of their pixels
    within ``contrast`` / 4 of their median). 0 if there is none."""
    ref_rows = lines[start + width:start + width + border].astype(np.int16)
    if not len(ref_rows):
        return 0
    ref = float(np.median(ref_rows))
    if (np.abs(ref_rows - ref) <= contrast / 4).mean() < min_flat_share:
        return 0
    diff = np.array([abs(float(np.median(r)) - ref) for r in lines[start:start + width]])
    if not len(diff) or diff.max() < min_peak:
        return 0
    return int(np.flatnonzero(diff > contrast).max()) + 1


def edge_bands(image: np.ndarray, max_frac: float = 0.25, max_std: float = 2.0,
               threshold: float = 15.0, border: int = 10,
               min_flat_share: float = 0.95, line_frac: float = 0.0) -> tuple[int, int, int, int]:
    """Widths (px) of flat bands along the image edges: top, bottom, left, right.

    A band is a run of whole rows (or columns), starting at the edge, all of
    the same flat colour (at least ``min_flat_share`` of its pixels within
    ``max_std`` grey levels of its median, so a small mark does not break
    the band) that differs from the background (ΔE > ``threshold``,
    background = median of the ``border``-pixel frame inside the bands), at
    most ``max_frac`` of the image size. Such bands come from the frame of a
    figure or a screenshot, not from the specimen: they are left out of the
    segmentation and count as the image edge. A uniform background touching
    the edge is not a band (same colour as the background). With
    ``line_frac`` > 0, a thin line (up to that fraction of the image size,
    at least 3 px) just inside each band or edge, clearly darker or lighter
    than the background after it, is added to the band (:func:`frame_line`):
    the panel's own frame line around a drawing.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    h, w = grey.shape

    def run(lines) -> int:
        # Flat lines of the same grey level as the first one.
        n, level = 0, None
        for line in lines:
            line = line.astype(np.int16)
            med = float(np.median(line))
            if (np.abs(line - med) <= max_std).mean() < min_flat_share:
                break
            if level is None:
                level = med
            elif abs(med - level) > max_std:
                break
            n += 1
        return n

    cand = [run(grey[i] for i in range(int(max_frac * h))),
            run(grey[h - 1 - i] for i in range(int(max_frac * h))),
            run(grey[:, i] for i in range(int(max_frac * w))),
            run(grey[:, w - 1 - i] for i in range(int(max_frac * w)))]
    if line_frac > 0:
        # a thin frame line just inside (the panel's own border, often not quite
        # flat: drawn or slightly tilted) is part of the frame
        cand = [n + frame_line(lines, n, max(3, round(line_frac * min(h, w))), border)
                for n, lines in zip(cand, (grey, grey[::-1], grey.T, grey.T[::-1]), strict=True)]
    t, b, l, r = cand
    inner = image[t:h - b, l:w - r]
    if min(inner.shape[:2]) <= 2 * border:
        return (0, 0, 0, 0)
    bg = estimate_background(inner, border)
    lab = to_lab(image)
    edges = [lab[:t], lab[h - b:], lab[:, :l], lab[:, w - r:]]
    return tuple(n if n and np.linalg.norm(np.median(e.reshape(-1, 3), axis=0) - bg) > threshold
                 else 0 for n, e in zip(cand, edges, strict=True))


def image_frame(image: np.ndarray, cfg: dict, levels: int = 2) -> tuple[int, int, int, int]:
    """Edge bands of the picture (:func:`edge_bands`), then of what is left
    inside them, up to ``levels`` nested frames (a page margin, then the
    panel's own border): their total width per edge, top, bottom, left,
    right (px). ``cfg`` is the ``segmentation`` section of config.yaml;
    ``edge_band_max_frac`` = 0 turns frames off."""
    max_frac = cfg.get("edge_band_max_frac", 0.25)
    total = np.zeros(4, int)
    if not max_frac:
        return (0, 0, 0, 0)
    h, w = image.shape[:2]
    for _ in range(levels):
        t, b, l, r = total
        f = edge_bands(np.ascontiguousarray(image[t:h - b, l:w - r]), max_frac, cfg.get("edge_band_max_std", 2.0),
                       cfg.get("delta_e_threshold", 15.0), cfg.get("border_px", 10),
                       line_frac=cfg.get("edge_line_frac", 0.015))
        if not any(f):
            break
        total += f
    return tuple(int(v) for v in total)


def border_contact(mask: np.ndarray, frame: tuple[int, int, int, int] = (0, 0, 0, 0)) -> dict[str, int]:
    """Number of mask pixels on each image edge (inside the ``frame`` bands,
    see :func:`edge_bands`): {"top": n, "bottom": n, "left": n, "right": n}."""
    t, b, l, r = frame
    h, w = mask.shape
    m = mask[t:h - b, l:w - r]
    if not m.size:
        return {"top": 0, "bottom": 0, "left": 0, "right": 0}
    return {"top": int(m[0].sum()), "bottom": int(m[-1].sum()),
            "left": int(m[:, 0].sum()), "right": int(m[:, -1].sum())}


def background_distance(image: np.ndarray, background_lab: np.ndarray) -> np.ndarray:
    """Per-pixel colour distance ΔE (CIE76) to the background colour."""
    return np.linalg.norm(to_lab(image) - background_lab, axis=2)


def darker_or_coloured(image: np.ndarray, background_lab: np.ndarray) -> np.ndarray:
    """Per-pixel score for a light background: how much darker than the
    background (ΔL*), or how different in colour (Δa*b*), whichever is
    larger. Pixels lighter than the background (halo) score only by colour.
    """
    lab = to_lab(image)
    darker = background_lab[0] - lab[..., 0]
    chroma = np.hypot(lab[..., 1] - background_lab[1], lab[..., 2] - background_lab[2])
    return np.maximum(darker, chroma)


def detect_background(image: np.ndarray, background_lab: np.ndarray,
                      object_mask: np.ndarray, band_px: int = 10,
                      threshold: float = 15.0, min_balance: float = 0.3) -> tuple[str, float]:
    """Is the test wall darker than the background ("light" background) or
    brighter ("dark" background)?

    Looks only at a band of ``band_px`` pixels inside the edge of a first
    rough mask, i.e. at the wall (a transparent interior would look like
    the background). Among band pixels whose lightness L* differs from the
    background by more than ``threshold``, balance = (share darker) - (share
    lighter), from -1 (all lighter) to +1 (all darker). Returns the decision
    and the balance. Below ``min_balance`` in absolute value the decision
    is unreliable and "dark" (any colour difference counts, the general
    rule) is returned; the caller flags the image.
    """
    if not object_mask.any():
        return "dark", 0.0
    band = object_mask & (ndi.distance_transform_edt(object_mask) <= band_px)
    dl = background_lab[0] - to_lab(image)[..., 0][band]
    darker, lighter = int((dl > threshold).sum()), int((dl < -threshold).sum())
    balance = (darker - lighter) / max(1, darker + lighter)
    return ("light" if balance >= min_balance else "dark"), balance


def load_background_overrides(path: str | Path | None) -> dict[str, str]:
    """Per-image background type from a CSV (columns image, background),
    as {image stem: "light" | "dark"}. Missing file -> empty.
    Raises ValueError on an unknown background value.
    """
    if path is None or not Path(path).exists():
        return {}
    df = read_table(path, ["image", "background"], text=True, filled=("image", "background"))
    out = {}
    for img, bg in zip(df["image"], df["background"], strict=True):
        bg = bg.strip().lower()
        if bg not in BACKGROUNDS:
            raise ValueError(f"{Path(path).name}: background '{bg}' for {img} "
                             f"is not one of {BACKGROUNDS}")
        out[Path(img.strip()).stem] = bg
    return out


def _disk(r: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def keep_largest(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """The largest connected object of ``mask``, holes filled, and the sizes
    (px) of all objects, largest first."""
    lab = measure.label(mask)
    if lab.max() == 0:
        return np.zeros(mask.shape, bool), []
    sizes = np.bincount(lab.ravel())[1:]
    largest = np.argmax(sizes) + 1
    return ndi.binary_fill_holes(lab == largest), sorted(sizes.tolist(), reverse=True)


def clean_mask(raw: np.ndarray, close_radius: int, open_radius: int,
               sizes: list | None = None) -> np.ndarray:
    """Close gaps, fill holes, open, keep the largest object, fill again.
    ``sizes``, if given, receives the sizes of all objects (largest first)."""
    m = raw.astype(np.uint8)
    if close_radius > 0:
        # Pad so closing does not glue the object to the image border.
        r = close_radius
        m = np.pad(m, r)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, _disk(r))[r:-r, r:-r]
    m = ndi.binary_fill_holes(m).astype(np.uint8)
    if open_radius > 0:
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _disk(open_radius))
    out, found = keep_largest(m)
    if sizes is not None:
        sizes[:] = found
    return out


def close_wall_ring(raw: np.ndarray, mask: np.ndarray, radii_px: list[int], min_gain: float = 1.25,
                    min_support: float = 0.85, max_straight_px: int | None = None) -> tuple[np.ndarray | None, int]:
    """The whole test when only its contents were found: a pale, thin wall.

    On a transparent shell (hyaline wall, DIC, faint drawing line) the wall is
    a thin line close to the background colour, broken in places, and the
    cytoplasm is the largest object: the mask follows the cytoplasm. The wall
    pixels (``raw``: different from the background) are closed with a disk of
    each radius of ``radii_px`` (bridging gaps of the broken line), holes are
    filled, and the object around ``mask`` is opened again with the same disk.
    A candidate is kept only if it is at least ``min_gain`` times the area of
    ``mask``, does not touch the image border, and its outline lies on wall
    pixels (within 2 px) for at least ``min_support`` of its length: it then
    follows a wall that is really there, not a gap bridged across the
    background. A candidate with a straight edge longer than
    ``max_straight_px`` (and longer than any in ``mask``) follows a picture
    frame, not a wall, and is refused. The largest candidate is returned
    (None if none), with its radius. A test whose mask already follows its
    wall is not changed (no larger object around it is supported by wall
    pixels).
    """
    if not mask.any():
        return None, 0
    near = cv2.dilate(raw.astype(np.uint8), _disk(2)) > 0
    straight0 = longest_straight_edge(mask) if max_straight_px else 0
    best, best_r = None, 0
    for rp in radii_px:
        big = np.pad(raw.astype(np.uint8), rp)
        big = cv2.morphologyEx(big, cv2.MORPH_CLOSE, _disk(rp))[rp:-rp, rp:-rp]
        lab = measure.label(ndi.binary_fill_holes(big))
        hits = np.bincount(lab[mask].ravel(), minlength=lab.max() + 1)
        hits[0] = 0
        if hits.max() == 0:
            continue
        comp = cv2.morphologyEx((lab == hits.argmax()).astype(np.uint8), cv2.MORPH_OPEN, _disk(rp)) > 0
        cand = ndi.binary_fill_holes(comp | mask)
        if cand.sum() < min_gain * mask.sum() or cand[0].any() or cand[-1].any() or cand[:, 0].any() \
                or cand[:, -1].any():
            continue
        if max_straight_px and longest_straight_edge(cand) > max(max_straight_px, straight0):
            continue
        edge = cand ^ (cv2.erode(cand.astype(np.uint8), _disk(1)) > 0)
        if near[edge].mean() >= min_support and (best is None or cand.sum() > best.sum()):
            best, best_r = cand, rp
    return best, best_r


def smooth_mask(mask: np.ndarray, sigma_px: float) -> np.ndarray:
    """Smooth a mask outline: Gaussian blur of sigma ``sigma_px``, threshold
    at 0.5 (keeps the area nearly unchanged), keep the largest object and
    fill holes. Details narrower than about one sigma are rounded off.
    """
    if sigma_px <= 0 or not mask.any():
        return mask
    m = ndi.gaussian_filter(mask.astype(np.float32), sigma_px) > 0.5
    lab = measure.label(m)
    if lab.max() == 0:
        return mask
    largest = np.argmax(np.bincount(lab.ravel())[1:]) + 1
    return ndi.binary_fill_holes(lab == largest)


def segment_test(
    image: np.ndarray,
    cfg: dict,
    exclude: np.ndarray | None = None,
    background: str | None = None,
    px_per_um: float | None = None,
    scale: float | None = None,
) -> Segmentation:
    """Automatic binary mask of the test.

    ``cfg`` is the ``segmentation`` section of config.yaml. ``exclude`` is
    an optional bool mask of pixels that can never be test (e.g. the scale
    bar). ``background`` forces "light" or "dark"; None = detect it (an
    uncertain detection flags "check"). ``px_per_um`` converts the
    ``smooth_um`` setting to pixels; without it the mask is not smoothed
    (``smooth_px`` stays 0). The other µm settings are converted with
    ``scale`` (default: ``px_per_um``, else :data:`REFERENCE_PX_PER_UM`).
    The result is flagged "failed" if nothing is found, and "check" if the
    object touches the image border (test probably cut off), its area is
    outside the configured range, or its outline has a long perfectly
    straight stretch (see :func:`longest_straight_edge`). The picture's
    frame (:func:`image_frame`) is left out first and counts as the image
    edge.
    """
    frame = image_frame(image, cfg)
    if any(frame):
        t, b, l, r = frame
        h, w = image.shape[:2]
        inner = (slice(t, h - b), slice(l, w - r))
        seg = segment_test(np.ascontiguousarray(image[inner]), {**cfg, "edge_band_max_frac": 0},
                           None if exclude is None else exclude[inner], background, px_per_um, scale)

        def pad(m):
            if m is None:
                return None
            full = np.zeros((h, w), bool)
            full[inner] = m
            return full

        seg.mask, seg.unsmoothed, seg.frame = pad(seg.mask), pad(seg.unsmoothed), frame
        return seg
    bg = estimate_background(image, cfg.get("border_px", 10))
    thr = cfg.get("delta_e_threshold", 15.0)
    scale = scale or px_per_um or REFERENCE_PX_PER_UM
    close_r = radius_px(cfg, "close_radius", 0.4, 3, scale)
    open_r = radius_px(cfg, "open_radius", 0.4, 3, scale)
    keep = np.ones(image.shape[:2], bool) if exclude is None else ~exclude
    raw = (background_distance(image, bg) > thr) & keep
    sizes: list = []
    mask = clean_mask(raw, close_r, open_r, sizes)
    source, note = "override", None
    if background is None:
        source = "auto"
        min_b = cfg.get("min_background_balance", 0.3)
        background, balance = detect_background(
            image, bg, mask, radius_px(cfg, "background_band", 1.4, 10, scale), thr, min_b)
        if abs(balance) < min_b and mask.any():
            note = (f"wall neither clearly darker nor lighter than the background "
                    f"(balance {balance:+.2f}); background type uncertain, "
                    "used 'dark' (any difference)")
    if background == "light":
        raw = (darker_or_coloured(image, bg) > thr) & keep
        mask = clean_mask(raw, close_r, open_r, sizes)
    ring_note = None
    radii = [max(3, int(round(um * scale))) for um in cfg.get("wall_ring_radii_um", [1.0, 2.0, 4.0])]
    if radii:
        score = darker_or_coloured(image, bg) if background == "light" else background_distance(image, bg)
        # the wall at the usual threshold, then a fainter wall around that result: each pass must
        # enlarge the outline by wall_ring_min_gain (a lobe of debris or a letter does not)
        first, passes = mask, []
        for ring_thr in [thr] + [t for t in [cfg.get("wall_ring_delta_e")] if t and t < thr]:
            ring, r_used = close_wall_ring((score > ring_thr) & keep, mask, radii, cfg.get("wall_ring_min_gain", 1.25),
                                           cfg.get("wall_ring_min_support", 0.85), cfg.get("max_straight_edge_px"))
            if ring is not None:
                mask = ring
                passes.append(f"gaps up to {2 * r_used} px bridged" + ("" if ring_thr == thr else
                                                                     f", wall ΔE > {ring_thr:g}"))
        if passes:
            ring_note = (f"pale wall: outline closed along the wall ({'; '.join(passes)}); "
                         f"the first mask ({100 * first.sum() / mask.sum():.0f} % of it) followed the contents")
    smooth_um = cfg.get("smooth_um", 1.0) or 0.0
    sigma, unsmoothed = 0.0, None
    if smooth_um > 0 and px_per_um:
        sigma, unsmoothed = smooth_um * px_per_um, mask
        mask = smooth_mask(mask, sigma)
    seg = Segmentation(mask, "auto", background=background, background_source=source,
                       smooth_px=sigma, unsmoothed=unsmoothed)
    if note:
        seg.status = "check"
        seg.messages.append(note)
    if ring_note:
        seg.messages.append(ring_note)
    max_second = cfg.get("max_second_object_frac", 0.3)
    if len(sizes) > 1 and sizes[1] > max_second * sizes[0]:
        seg.status = "check"
        seg.messages.append(f"another object in the image ({100 * sizes[1] / sizes[0]:.0f} % of "
                            "the test's size) was left out: check that the right one was measured")
    _quality_flags(seg, cfg)
    return seg


def longest_straight_edge(mask: np.ndarray, ignore_segment=None) -> int:
    """Length (px) of the longest perfectly vertical or horizontal run of
    the mask's outer contour.

    Natural outlines are curved; a long axis-aligned run usually means the
    test was cut by an image crop or edited background. ``ignore_segment``
    = ((x, y), (x, y)): runs lying along that segment (both ends within 10%
    of its length, min 3 px) are skipped, e.g. a flat aperture between its
    two corners.
    """
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    best = 0
    for c in contours:
        pts = c[:, 0, :]
        nxt = np.roll(pts, -1, axis=0)
        # CHAIN_APPROX_SIMPLE stores each H/V/diagonal run as its 2 end points.
        seg = np.abs(nxt - pts)
        for i in np.flatnonzero((seg[:, 0] == 0) | (seg[:, 1] == 0)):
            if ignore_segment is not None and _on_segment(pts[i], nxt[i], *ignore_segment):
                continue
            best = max(best, int(seg[i].max()))
    return best


def _on_segment(p, q, a, b) -> bool:
    """True if points p and q both lie within tolerance of segment a-b."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    L = np.hypot(*ab)
    tol = max(3.0, 0.1 * L)

    def dist(x):
        t = np.clip(np.dot(np.asarray(x, float) - a, ab) / (L * L), 0, 1) if L else 0.0
        return np.hypot(*(np.asarray(x, float) - (a + t * ab)))

    return dist(p) <= tol and dist(q) <= tol


STRAIGHT_MSG = "straight outline segment of"


def setting_px(cfg: dict, name: str, default_um: float, default_min_px: float, scale: float) -> float:
    """Setting ``<name>_um`` in pixels at ``scale`` px/µm, but never below
    ``<name>_min_px``: the same physical size at every resolution, without
    going finer than the pixel noise allows on low-resolution images."""
    return max(float(cfg.get(f"{name}_min_px", default_min_px)),
               float(cfg.get(f"{name}_um", default_um)) * scale)


def radius_px(cfg: dict, name: str, default_um: float, default_min_px: int, scale: float) -> int:
    """:func:`setting_px` as a whole number of pixels (halves round up)."""
    return int(np.floor(setting_px(cfg, name, default_um, default_min_px, scale) + 0.5))


def _quality_flags(seg: Segmentation, cfg: dict) -> None:
    """Set ``seg.status``/``messages`` from simple plausibility checks."""
    m = seg.mask
    if not m.any():
        seg.status = "failed"
        seg.messages.append("no object found")
        return
    frac = m.mean()
    lo, hi = cfg.get("min_area_frac", 0.02), cfg.get("max_area_frac", 0.9)
    if not lo <= frac <= hi:
        seg.messages.append(f"area fraction {frac:.3f} outside [{lo}, {hi}]")
    if any(border_contact(m, seg.frame).values()):
        seg.messages.append("object touches image border")
    run, max_run = longest_straight_edge(seg.crop_check_mask), cfg.get("max_straight_edge_px", 60)
    if run > max_run:
        seg.messages.append(f"{STRAIGHT_MSG} {run} px (image cropped?)")
    if seg.messages:
        seg.status = "check"


def excuse_flat_aperture(seg: Segmentation, cfg: dict, corners) -> None:
    """Re-check the straight-edge flag ignoring the aperture (``corners`` =
    its two corner points): a flat aperture seen edge-on is not a crop.
    Updates ``seg.messages`` and ``seg.status`` in place.
    """
    if not any(m.startswith(STRAIGHT_MSG) for m in seg.messages):
        return
    if longest_straight_edge(seg.crop_check_mask, corners) <= cfg.get("max_straight_edge_px", 60):
        seg.messages = [m for m in seg.messages if not m.startswith(STRAIGHT_MSG)]
        if seg.status == "check" and not seg.messages:
            seg.status = "ok"


def scale_bar_exclusion(shape: tuple[int, int], bar, margin: int | None = None) -> np.ndarray:
    """Bool mask of the scale bar box, grown by ``margin`` (default: its thickness)."""
    ex = np.zeros(shape[:2], bool)
    if bar is None:
        return ex
    m = bar.thickness_px if margin is None else margin
    y0, y1 = max(0, bar.y_top - m), bar.y_bottom + m + 1
    x0, x1 = max(0, int(bar.x0) - m), int(np.ceil(bar.x1)) + m + 1
    ex[y0:y1, x0:x1] = True
    return ex


def load_manual_mask(path: str | Path, shape: tuple[int, int]) -> np.ndarray | None:
    """Read a hand-corrected mask (non-zero = test), or None if absent.

    Raises ValueError if its size does not match the image.
    """
    path = Path(path)
    if not path.exists():
        return None
    m = read_image(path, cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise ValueError(f"Cannot read mask {path}")
    if m.shape != tuple(shape[:2]):
        raise ValueError(f"Mask {path.name} is {m.shape}, image is {shape[:2]}")
    return m > 127


def segment(image: np.ndarray, stem: str, cfg: dict, bar=None,
            px_per_um: float | None = None, scale: float | None = None) -> Segmentation:
    """Manual mask if one exists for ``stem`` (used as drawn, not smoothed),
    else automatic segmentation (background type from
    ``background_overrides_csv`` if listed there)."""
    manual = load_manual_mask(Path(cfg["masks_dir"]) / f"{stem}_mask.png", image.shape)
    if manual is not None:
        cleaned, sizes = keep_largest(manual)
        seg = Segmentation(cleaned, "manual", frame=image_frame(image, cfg))
        changes = []
        if len(sizes) > 1:
            changes.append(f"{len(sizes)} separate parts, the largest kept")
        if sizes and int(cleaned.sum()) > sizes[0]:
            changes.append("holes filled")
        if changes:
            seg.messages.append("hand mask cleaned: " + ", ".join(changes))
        _quality_flags(seg, cfg)
        return seg
    forced = load_background_overrides(cfg.get("background_overrides_csv")).get(stem)
    return segment_test(image, cfg, scale_bar_exclusion(image.shape, bar), forced, px_per_um, scale)


def save_mask(mask: np.ndarray, path: str | Path) -> None:
    """Write a mask as an 8-bit PNG (255 = test)."""
    write_image(path, mask.astype(np.uint8) * 255)
