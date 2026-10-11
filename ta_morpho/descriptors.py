"""Shape descriptors per specimen, from the mask, landmark and profile.

Lengths are in µm when the image is calibrated, else NaN (ratios are
always given). Mean radius and CV use the exported rays (as in summary.csv);
harmonics and symmetry use a fine profile (``fine_step_deg``, 1° by
default), so they do not depend on the export angle step.
"""

from __future__ import annotations

import numpy as np

from ta_morpho.landmark import clockwise_angle
from ta_morpho.rays import outline_length, polygon_area, radial_profile, subpixel_outline

N_HARMONICS = 5


def harmonic_amplitudes(radii: np.ndarray, n: int = N_HARMONICS) -> np.ndarray:
    """Amplitudes of harmonics 1..n of an evenly sampled closed profile,
    relative to the mean radius (2 = elongation, 3 = pear shape / unequal ends).
    """
    f = np.fft.rfft(radii) / len(radii)
    return 2 * np.abs(f[1:n + 1]) / radii.mean()


def symmetry_index(fine_angles: np.ndarray, fine_r: np.ndarray, axis_deg: float) -> float:
    """Mean |r(axis + θ) - r(axis - θ)| over θ in 0-180°, relative to the
    mean radius. 0 = perfect mirror symmetry about the axis.
    """
    th = np.arange(0, 181)
    r = lambda a: np.interp(a % 360, fine_angles, fine_r, period=360)  # noqa: E731
    return float(np.mean(np.abs(r(axis_deg + th) - r(axis_deg - th))) / fine_r.mean())


def shape_descriptors(sp, cfg: dict | None = None, intersection: str = "last") -> dict:
    """Descriptors for a :class:`ta_morpho.pipeline.Specimen` with a profile.

    Keys: length, width (extent along / across the principal axis),
    aspect_ratio, area, perimeter, circularity (4πA/P²), aperture_width,
    mean_radius, radius_cv, h1..h<n> (harmonic amplitudes / mean radius,
    n = ``n_harmonics``), symmetry_index (about the centroid -> aperture-
    midpoint axis; NaN if no aperture). Lengths in µm (suffix _um). ``cfg``
    = the ``descriptors`` section of config.yaml (``n_harmonics``,
    ``fine_step_deg``, which must divide 360). ``intersection`` = the
    outline crossing used by the rays (config ``rays.intersection``), the
    same for the fine profile.

    A ray of the fine profile that meets no outline (centroid outside the
    test, a very concave shape: then a whole sector of rays is missing, not
    one) leaves all the harmonics and the symmetry index empty (NaN), and the
    image is flagged by the rays step. They are not interpolated across the
    gap: that would invent the outline there. Mean radius and CV use the
    rays that were found.
    """
    cfg = cfg or {}
    step = float(cfg.get("fine_step_deg", 1.0))
    if step <= 0 or abs(360 / step - round(360 / step)) > 1e-9:
        raise ValueError(f"descriptors.fine_step_deg must divide 360, got {step}")
    mask, c = sp.segmentation.mask, np.asarray(sp.centroid)
    ppu = sp.calibration.px_per_um if sp.calibration else np.nan
    poly = subpixel_outline(mask)
    area = polygon_area(poly)
    perim = outline_length(poly)

    ys, xs = np.nonzero(mask)
    _, evecs = np.linalg.eigh(np.cov(np.c_[xs, ys].T))
    along, across = (poly - c) @ evecs[:, 1], (poly - c) @ evecs[:, 0]
    length, width = np.ptp(along), np.ptp(across)

    lm = (sp.landmark.x, sp.landmark.y)
    fine = radial_profile(mask, sp.centroid, lm, step, intersection=intersection).table
    r = fine["radius_px"].to_numpy()
    r_export = sp.profile.table["radius_px"].to_numpy()  # same rays as summary.csv
    ap = sp.landmark.aperture
    out = {
        "length_um": length / ppu,
        "width_um": width / ppu,
        "aspect_ratio": length / width,
        "area_um2": area / ppu ** 2,
        "perimeter_um": perim / ppu,
        "circularity": 4 * np.pi * area / perim ** 2,
        "aperture_width_um": (np.hypot(ap.start[0] - ap.end[0], ap.start[1] - ap.end[1]) / ppu
                              if ap else np.nan),
        "mean_radius_um": np.nanmean(r_export) / ppu,
        "radius_cv": np.nanstd(r_export) / np.nanmean(r_export),
    }
    for i, a in enumerate(harmonic_amplitudes(r, int(cfg.get("n_harmonics", N_HARMONICS))), start=1):
        out[f"h{i}"] = float(a)
    if ap is not None:
        axis = (clockwise_angle(sp.centroid, ap.midpoint) - clockwise_angle(sp.centroid, lm)) % 360
        out["symmetry_index"] = symmetry_index(fine["angle_deg"].to_numpy(), r, axis)
    else:
        out["symmetry_index"] = np.nan
    return {k: float(v) for k, v in out.items()}
