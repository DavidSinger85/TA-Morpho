"""Run all steps on one image: calibration, segmentation, centroid,
landmark, radial profile, descriptors, then the footprint (classic
measurements, outline profile anchored on the aperture, holes/bumps).
Failures are recorded, never filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ta_morpho.calibration import REFERENCE_PX_PER_UM, Calibration, ScaleBarNotFound, calibrate
from ta_morpho.centroid import mask_centroid
from ta_morpho.characters import TAXON, resolve
from ta_morpho.classic import axis_fundus, body_outline, classic_measurements, fundus_behind_aperture, protrusions
from ta_morpho.descriptors import N_HARMONICS, shape_descriptors
from ta_morpho.features import locate, manual_features
from ta_morpho.image_io import load_image
from ta_morpho.landmark import Landmark, find_landmark, spine_radius
from ta_morpho.metadata import DEFAULT_BAR_RANGE_UM, DEFAULT_SEPARATOR, FileMetadata, parse_filename
from ta_morpho.outline_profile import anchored_profile
from ta_morpho.rays import Profile, radial_profile, subpixel_outline
from ta_morpho.segment import Segmentation, border_contact, excuse_flat_aperture, segment
from ta_morpho.tables import read_table


# Measurement columns of summary.csv, in order (after the QC and metadata
# columns, before the radii): MEASURE_KEYS, the harmonics h1..h<n>, then
# symmetry_index. Length and width are along the oral-aboral axis ("axis" =
# oral); without an aperture, along the principal axis ("principal").
MEASURE_KEYS = ("length_um", "width_um", "W/L", "aperture_width_um", "aperture_angle_deg", "widest_position",
                "widest_position_aperture", "neck_length_um", "neck_width_um", "area_um2",
                "perimeter_um", "circularity",
                "solidity", "feret_max_um", "feret_min_um", "centroid_size_um",
                "AW/L", "AW/W", "NL/L", "NW/L", "NL/W", "NW/W", "NL/AW", "NW/AW", "NW/NL",
                "neck_jump", "aperture_sag", "n_protrusions",
                "mean_radius_um", "radius_cv")


def measure_columns(n_harmonics: int = N_HARMONICS) -> list[str]:
    """Measurement columns of summary.csv, in order (see MEASURE_KEYS)."""
    return [*MEASURE_KEYS, *(f"h{i}" for i in range(1, n_harmonics + 1)), "symmetry_index"]


@dataclass
class Specimen:
    """Everything computed for one image. Fields stay None after a failure."""

    path: Path
    image: np.ndarray
    calibration: Calibration | None = None
    segmentation: Segmentation | None = None
    centroid: tuple[float, float] | None = None
    landmark: Landmark | None = None
    profile: Profile | None = None
    metadata: FileMetadata | None = None
    descriptors: dict | None = None
    classic: dict | None = None              # oral-axis measurements (needs the aperture)
    outline_profile: pd.DataFrame | None = None  # equally spaced points, aperture-anchored
    fundus: tuple[float, float] | None = None  # aboral end of the oral-aboral axis (px)
    manual_fundus: tuple[float, float] | None = None  # set by hand (landmarks.csv)
    fundus_source: str = ""                  # "auto" or "manual"
    features: list[dict] | None = None       # holes / bumps added by hand, measured
    outline_features: str = ""               # "ok", "no features", "" (not measured)
    protrusion_levels: list[float] | None = None  # horns/spines (ta_morpho.classic.protrusions); None = not measured
    characters: dict = field(default_factory=dict)  # {key: (value, "genus" | "hand")} (ta_morpho.characters)
    taxon_by_hand: bool = False              # genus / species set by hand, not read from the file name
    status: str = "ok"                       # worst of the step statuses
    messages: list[str] = field(default_factory=list)
    auto_status: str | None = None           # status before manual review
    review_note: str | None = None           # set when listed in qc_review.csv

    def flag(self, status: str, step: str, message: str) -> None:
        """Record a problem; status only gets worse (ok < check < failed)."""
        order = ["ok", "check", "failed"]
        if order.index(status) > order.index(self.status):
            self.status = status
        self.messages.append(f"{step}: {message}")


def _row(df: pd.DataFrame, key: str) -> dict | None:
    return df.loc[key].to_dict() if key in df.index else None


def analyse_image(path: Path, config: dict, landmarks: pd.DataFrame,
                  overrides: pd.DataFrame, feature_corrections: dict | None = None,
                  characters: dict[str, str] | None = None) -> Specimen:
    """Run all steps on one image. ``landmarks`` and ``overrides`` are the
    tables from :func:`ta_morpho.landmark.load_landmarks` and
    :func:`ta_morpho.calibration.load_overrides`; ``feature_corrections`` the hole/
    bump corrections from :func:`ta_morpho.features.load_feature_corrections`;
    ``characters`` this image's rows of :func:`ta_morpho.characters.load_characters`
    (genus, species and characters set by hand).
    """
    sp = Specimen(path, load_image(path))
    cal_cfg = config["calibration"]
    sp.metadata = md = parse_filename(
        path.stem, config.get("metadata", {}).get("separator", DEFAULT_SEPARATOR),
        tuple(cal_cfg.get("bar_length_range_um", DEFAULT_BAR_RANGE_UM)))
    by_hand = dict(characters or {})
    taxon = {k: by_hand.pop(k) for k in TAXON if by_hand.get(k)}
    if taxon:                                  # genus / species set by hand win over the file name
        md.genus, md.species = taxon.get("genus", md.genus), taxon.get("species", md.species)
        md.messages = [m for m in md.messages if not m.startswith("file name does not start")]
        sp.taxon_by_hand = True
    sp.characters = resolve(md.genus, by_hand)

    # Bar length: overrides CSV > file name > config default.
    override = {k: v for k, v in (_row(overrides, path.name) or {}).items() if pd.notna(v)}
    if "bar_length_um" in override:
        bar_source = "override"
    elif md.bar_length_um is not None:
        override["bar_length_um"] = md.bar_length_um
        bar_source = "file name"
    else:
        bar_source = "default"
    no_bar_needed = bar_source == "override" or override.get("px_per_um") or cal_cfg.get("px_per_um")
    for m in md.messages:
        if m.startswith("no bar length"):
            if no_bar_needed:
                continue                       # the override gives the calibration
            m += (f"; default bar length {cal_cfg['bar_length_um']:g} µm used: rename the file "
                  "(e.g. '_25um'), or draw the scale (desktop: Scale bar) or give it in the "
                  "calibration table (command line)")
        sp.flag("check", "file name", m)
    try:
        sp.calibration = calibrate(sp.image, cal_cfg, override)
        sp.calibration.bar_length_source = bar_source if sp.calibration.bar_length_um else ""
        if sp.calibration.status != "ok":
            sp.flag("check", "calibration", f"{sp.calibration.bar.n_candidates} bar candidates")
    except ScaleBarNotFound as e:
        sp.flag("check", "calibration", f"{e}; µm values left empty")
    bar = sp.calibration.bar if sp.calibration else None

    # px/µm used to convert the µm settings: the calibration, else a reference.
    scale = sp.calibration.px_per_um if sp.calibration else \
        cal_cfg.get("uncalibrated_px_per_um") or REFERENCE_PX_PER_UM     # empty setting: the reference
    try:
        sp.segmentation = segment(sp.image, path.stem, config["segmentation"], bar,
                                  sp.calibration.px_per_um if sp.calibration else None, scale)
    except ValueError as e:
        sp.flag("failed", "segmentation", str(e))
        return sp
    seg = sp.segmentation
    if seg.source == "auto" and config["segmentation"].get("smooth_um") and not seg.smooth_px:
        sp.flag("check", "segmentation", "no calibration: mask not smoothed")
    if seg.status == "failed":
        for m in seg.messages:
            sp.flag("failed", "segmentation", m)
        return sp

    sp.centroid = mask_centroid(seg.mask)
    pt = _row(landmarks, path.name) or {}
    xy = lambda kx, ky: (pt[kx], pt[ky]) if pd.notna(pt.get(kx)) and pd.notna(pt.get(ky)) else None  # noqa: E731
    sp.landmark = find_landmark(seg.mask, config["landmark"], xy("x", "y"), xy("end_x", "end_y"),
                                border_contact(seg.mask, seg.frame), scale)
    sp.manual_fundus = xy("fundus_x", "fundus_y")
    ap = sp.landmark.aperture
    if ap is not None:
        excuse_flat_aperture(seg, config["segmentation"], (ap.start, ap.end))
    for m in seg.messages:
        sp.flag(seg.status, "segmentation", m)
    for m in sp.landmark.messages:
        sp.flag(sp.landmark.status, "landmark", m)
    if sp.landmark.x is None:
        return sp

    rcfg = config["rays"]
    sp.profile = radial_profile(
        seg.mask, sp.centroid, (sp.landmark.x, sp.landmark.y),
        angle_step_deg=rcfg["angle_step_deg"],
        px_per_um=sp.calibration.px_per_um if sp.calibration else None,
        intersection=rcfg.get("intersection", "last"),
    )
    for m in sp.profile.messages:
        sp.flag(sp.profile.status, "rays", m)
    sp.descriptors = shape_descriptors(sp, config.get("descriptors"), rcfg.get("intersection", "last"))
    measure_footprint(sp, config, (feature_corrections or {}).get(path.name, []))
    return sp


def measure_footprint(sp: Specimen, config: dict, feature_corrections: list[dict] = ()) -> None:
    """Classic measurements, aperture-anchored outline profile and holes/bumps
    (config sections ``classic``, ``outline_profile``, ``features``).

    All three are taken from the aperture, so a specimen without one (round
    test, fallback start point) keeps them empty and is flagged.
    """
    ap = sp.landmark.aperture
    if ap is None:
        sp.flag("check", "footprint", "no aperture: classic measurements (length and width "
                "along the principal axis instead), outline profile and holes/bumps not measured")
        if sp.manual_fundus is not None:
            sp.flag("check", "footprint", "fundus set by hand not used: it needs the aperture")
        return
    mask, ppu = sp.segmentation.mask, sp.calibration.px_per_um if sp.calibration else None
    poly = subpixel_outline(mask)
    ccfg = config.get("classic") or {}
    # One rule for both sources (ta_morpho.classic.axis_fundus): the hand gives the
    # point the axis goes through, never a different method.
    sp.fundus_source = "manual" if sp.manual_fundus is not None else "auto"
    if sp.manual_fundus is not None and fundus_behind_aperture(ap.start, ap.end, sp.centroid,
                                                               sp.manual_fundus):
        sp.flag("check", "footprint", "fundus set by hand on the aperture side: axis taken "
                "perpendicular to the aperture")
    spine_frac = (config.get("landmark") or {}).get("spine_opening_frac", 0.06)
    sp.fundus = axis_fundus(poly, ap.start, ap.end, sp.centroid, sp.manual_fundus,
                            ccfg.get("fundus_far_frac", 0.1), body_outline(mask, spine_frac))
    sp.classic = classic_measurements(poly, ap.start, ap.end, sp.centroid, ppu, ccfg, sp.fundus)
    r = spine_radius(mask, spine_frac)
    sp.protrusion_levels = protrusions(mask, r, ap.start, ap.end, sp.centroid, sp.fundus)
    sp.classic["n_protrusions"] = (float(len(sp.protrusion_levels)) if sp.protrusion_levels is not None
                                   else np.nan)      # no spine opening set: not measured
    op = config["outline_profile"]
    try:
        sp.outline_profile = anchored_profile(
            mask, sp.centroid, ap.start, ap.end, op["n_points"], op["n_aperture"], ppu,
            sp.fundus if op.get("fundus_anchor", True) else None)
    except ValueError as e:
        sp.flag("check", "outline profile", str(e))
    if ppu is None:
        sp.flag("check", "holes/bumps", "no calibration: not measured")
        return
    lm = (sp.landmark.x, sp.landmark.y)
    neck_px = sp.classic["neck_length_um"] * ppu
    # Holes and bumps: those added by hand (ta_morpho.features).
    sp.features, sp.outline_features, msgs = manual_features(
        feature_corrections, mask, ppu, lm, [ap.start, ap.end], config.get("features"))
    for m in msgs:
        sp.flag("check", "holes/bumps", m)
    locate(sp.features, sp.outline_profile, ap.start, ap.end, sp.centroid, sp.fundus, lm, ppu, neck_px)


def measurements(sp: Specimen, n_harmonics: int = N_HARMONICS) -> dict:
    """Measurement values of one specimen (keys of :func:`measure_columns`,
    plus ``axis``); classic (oral-axis) values when the aperture is known,
    else the principal-axis descriptors; NaN when nothing was measured."""
    d = sp.descriptors or {}
    out = {k: np.nan for k in measure_columns(n_harmonics)}
    out.update({k: v for k, v in d.items() if k in out})
    if sp.classic is not None:
        out.update(sp.classic)
    t = sp.outline_profile
    if t is not None and sp.calibration is not None:
        # Geometric-morphometric size: root of the summed squared distances of the
        # outline points from their centroid (scales with sqrt(number of points)).
        out["centroid_size_um"] = float(np.sqrt(((t.x - t.x.mean()) ** 2 + (t.y - t.y.mean()) ** 2).sum())
                                        / sp.calibration.px_per_um)
    # The axis is the oral one whenever the classic measurements were taken (also
    # without a calibration: the ratios stay); the principal axis only without.
    if sp.classic is not None:
        axis = "oral"
    elif d:
        out["W/L"] = 1 / d["aspect_ratio"]     # pixel ratio: also without a calibration
        axis = "principal"
    else:
        axis = ""
    return {"axis": axis, **out}


def load_reviews(path: str | Path | None) -> pd.DataFrame:
    """Read the manual QC review list (columns ``image, note``), indexed by
    image; empty if the file is absent."""
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=["note"], index=pd.Index([], name="image"))
    return read_table(path, ["image", "note"], text=True).set_index("image")[["note"]]


def apply_review(sp: Specimen, reviews: pd.DataFrame) -> None:
    """Mark a specimen checked by a person as accepted.

    A "check" becomes "ok"; the automatic status and all QC messages are
    kept (``auto_status``, ``messages``) so nothing is hidden from the CSV.
    A "failed" specimen stays failed: there is nothing to accept.
    """
    sp.auto_status = sp.status
    if sp.path.name not in reviews.index:
        return
    sp.review_note = reviews.loc[sp.path.name, "note"] or "accepted after visual check"
    if sp.status == "check":
        sp.status = "ok"

