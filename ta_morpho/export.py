"""Batch run and export — the single entry point of the pipeline.

    ta-morpho [images or folders] [-o results] [--config config.yaml] [--step 5]
              [--save-masks] [--export] [--click]      (or: python -m ta_morpho ...)

Outputs in ``paths.results_dir`` (or ``-o``); each run replaces them:

- ``summary.csv``         one row per specimen: status (after review),
                          auto_status, review_note, QC messages, metadata,
                          classic measurements and ratios, shape descriptors,
                          holes/bumps, then one column per angle (radius, µm)
- ``cells/<image>.png``   one report per specimen (image + rays, classic
                          measurements and holes/bumps, profile, values,
                          QC status and messages)
- ``exports/``            the derived tables, written only with ``--export``
                          (or on demand from the desktop app):
    - ``profiles_long.csv``   all rays of all specimens, every radius measure
    - ``outline_profile.csv`` one row per specimen: distance from the centroid
                          (µm) along the outline, anchored on the aperture
                          corners and the fundus (d000... = aperture)
    - ``outline_coordinates.tps`` the same outline points as x, y coordinates
                          for geometric morphometrics (tpsDig format: pixels,
                          y up, SCALE = µm per pixel; geomorph::readland.tps)
    - ``outline_sliders.csv`` semilandmark definition for geomorph (before,
                          slide, after; 1-based point numbers; closed outline)
    - ``outline_features.csv`` one row per hole or bump added by hand
- ``.pipeline/``          hidden, technical: ``batch.log``, ``config_used.yaml``
                          (overwritten by each run) and ``records/<image>.json``,
                          the results of each image, from which the tables are
                          assembled (lets one image be re-run after a
                          correction, see :func:`rerun_images`); ``exports_stale``
                          while ``exports/`` lags behind such re-runs
- ``masks/<image>_mask.png`` only with ``--save-masks`` (for manual correction)

Failed or flagged specimens are kept as rows with their status and
messages; values that could not be measured stay empty.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ta_morpho.calibration import calibration_uncertainty_pct, load_overrides
from ta_morpho.characters import KEYS as CHARACTER_KEYS
from ta_morpho.characters import load_characters
from ta_morpho.classic import oral_axis
from ta_morpho.descriptors import N_HARMONICS
from ta_morpho.features import feature_radius_px, load_feature_corrections
from ta_morpho.image_io import IMAGE_EXTS, UnsupportedImage, list_images
from ta_morpho.landmark import click_landmarks, load_landmarks
from ta_morpho.landmark import outline as contour_of
from ta_morpho.metadata import DEFAULT_BAR_RANGE_UM, DEFAULT_SEPARATOR, parse_filename
from ta_morpho.outline_profile import landmark_points
from ta_morpho.pipeline import Specimen, analyse_image, apply_review, load_reviews, measurements
from ta_morpho.provenance import provenance, software_version
from ta_morpho.qc import draw_report
from ta_morpho.rays import subpixel_outline
from ta_morpho.segment import load_background_overrides, save_mask

log = logging.getLogger(__name__)

# The default settings, shipped inside the package (see default_config).
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.yaml")

FEATURE_KEYS = ("kind", "position", "size_um", "width_um", "region", "axis_position")
REGIONS = ("aperture", "neck", "junction", "body", "side1", "side2")
NECK = ("neck", "junction")             # regions that exist only on a test with a neck
FEATURE_SLOTS = 5                       # holes/bumps listed one by one in summary.csv (f1..f5)
FEATURE_ROW_KEYS = ("number", "kind", "position", "size_um", "width_um", "x", "y",
                    "profile_point", "stretch", "region", "axis_position", "angle_deg", "note")


def angle_column(angle: float) -> str:
    """Column name for an angle, e.g. 0 -> 'r0', 7.5 -> 'r7.5'."""
    return f"r{angle:g}"


def feature_columns(sp: Specimen) -> dict:
    """Holes/bumps summary: outline status, counts (all, then per region and
    per side of the anchored profile), summed size per region of the axis,
    and the first FEATURE_SLOTS features. Holes and bumps are those added by
    hand (none: counts 0). Neck columns are empty when the test has no neck."""
    measured = sp.features is not None
    feats = sp.features or []
    has_neck = sp.classic is not None and np.isfinite(sp.classic.get("neck_length_um", np.nan))
    located = measured and sp.outline_profile is not None
    sides = located and "side1" in set(sp.outline_profile["segment"])   # fundus anchor on
    row = {"outline_features": sp.outline_features,
           "n_holes": sum(f["kind"] == "hole" for f in feats) if measured else np.nan,
           "n_bumps": sum(f["kind"] == "bump" for f in feats) if measured else np.nan}
    for kind in ("hole", "bump"):
        of = [f for f in feats if f["kind"] == kind]
        for where in REGIONS:
            if where == "junction" and kind == "bump":      # only holes mark the junction
                continue
            key = "stretch" if where.startswith("side") else "region"
            ok = (sides if key == "stretch" else located) and (where not in NECK or has_neck)
            row[f"n_{kind}s_{where}"] = sum(f.get(key) == where for f in of) if ok else np.nan
        for where in ("neck", "junction", "body") if kind == "hole" else ("neck", "body"):
            ok = located and (where not in NECK or has_neck)
            row[f"{kind}_size_sum_{where}_um"] = (sum(f["size_um"] for f in of if f.get("region") == where)
                                                  if ok else np.nan)
    for k in range(1, FEATURE_SLOTS + 1):
        f = feats[k - 1] if k <= len(feats) else {}
        row.update({f"f{k}_{key}": f.get(key, "" if key in ("kind", "region") else np.nan)
                    for key in FEATURE_KEYS})
    return row


def corrections(sp: Specimen) -> str:
    """What was corrected by hand for this specimen ("" if nothing), from the
    source of each step: a specimen accepted without any correction keeps
    the automatic result, and its flag is a trait of the specimen."""
    out = []
    cal, seg, lm = sp.calibration, sp.segmentation, sp.landmark
    if cal is not None and cal.source == "manual":
        out.append("scale bar")                      # drawn or typed (its length included)
    elif cal is not None and cal.bar_length_source == "override":
        out.append("bar length")
    if seg is not None and seg.source == "manual":
        out.append("outline")
    if seg is not None and seg.background_source == "override":
        out.append("background type")
    if lm is not None and lm.source in ("manual", "csv"):
        out.append("aperture" if lm.source == "manual" else "start point")
    if sp.fundus_source == "manual":
        out.append("fundus")
    if sp.features:
        out.append("holes/bumps")
    if sp.taxon_by_hand:
        out.append("taxon")
    if any(src == "hand" for _, src in sp.characters.values()):
        out.append("characters")
    return "; ".join(out)


def summary_row(sp: Specimen, angles: np.ndarray, n_harmonics: int = N_HARMONICS) -> dict:
    """One wide row: QC, metadata, measurements, holes/bumps, radius (µm) per angle."""
    cal, lm, md = sp.calibration, sp.landmark, sp.metadata
    row = {
        "image": sp.path.name,
        "genus": md.genus,
        "species": md.species,
        "specimen_id": md.specimen_id,
        "status": sp.status,
        "auto_status": sp.auto_status or sp.status,
        "review_note": sp.review_note or "",
        "corrections": corrections(sp),
        "messages": " | ".join(sp.messages),
        "software_version": software_version(),
        "bar_length_um": cal.bar_length_um if cal else np.nan,
        "bar_length_source": cal.bar_length_source if cal else "",
        "px_per_um": cal.px_per_um if cal else np.nan,
        "calibration_source": cal.source if cal else "",
        "calibration_uncertainty_pct": calibration_uncertainty_pct(cal),
        "mask_source": sp.segmentation.source if sp.segmentation else "",
        "background": sp.segmentation.background if sp.segmentation else "",
        "background_source": sp.segmentation.background_source if sp.segmentation else "",
        "smooth_px": sp.segmentation.smooth_px if sp.segmentation else np.nan,
        "landmark_source": lm.source if lm else "",
        "centroid_x": sp.centroid[0] if sp.centroid else np.nan,
        "centroid_y": sp.centroid[1] if sp.centroid else np.nan,
        "landmark_x": lm.x if lm and lm.x is not None else np.nan,
        "landmark_y": lm.y if lm and lm.y is not None else np.nan,
        "aperture_end_x": lm.aperture.end[0] if lm and lm.aperture else np.nan,
        "aperture_end_y": lm.aperture.end[1] if lm and lm.aperture else np.nan,
        "fundus_x": sp.fundus[0] if sp.fundus else np.nan,
        "fundus_y": sp.fundus[1] if sp.fundus else np.nan,
        "fundus_source": sp.fundus_source,
    }
    row.update(measurements(sp, n_harmonics))
    row.update(feature_columns(sp))
    row["protrusion_levels"] = (";".join(f"{v:.2f}" for v in sp.protrusion_levels)
                                if sp.protrusion_levels is not None else "")
    row.update({f"ch_{k}": sp.characters.get(k, ("", ""))[0] for k in CHARACTER_KEYS})
    row["characters_by_hand"] = ";".join(k for k in CHARACTER_KEYS if sp.characters.get(k, ("", ""))[1] == "hand")
    radii = sp.profile.table["radius_um"].to_numpy() if sp.profile else np.full(len(angles), np.nan)
    row.update({angle_column(a): r for a, r in zip(angles, radii, strict=True)})
    return row


def outline_profile_row(sp: Specimen) -> dict | None:
    """One wide row of the aperture-anchored outline profile (µm), or None."""
    if sp.outline_profile is None:
        return None
    md, t = sp.metadata, sp.outline_profile
    return {"image": sp.path.name, "genus": md.genus, "species": md.species,
            "specimen_id": md.specimen_id, "status": sp.status,
            "n_aperture": int((t.segment == "aperture").sum()),
            "mean_distance_um": t.distance_um.mean(),
            **{f"d{i:03d}": v for i, v in zip(t.point, t.distance_um, strict=True)}}


def tps_block(sp: Specimen) -> str | None:
    """One specimen of a tpsDig file: outline points in pixels with y up
    (origin at the bottom-left of the image), IMAGE, ID and SCALE (µm / px)."""
    t = sp.outline_profile
    if t is None:
        return None
    h = sp.image.shape[0]
    lines = [f"LM={len(t)}"] + [f"{x:.3f} {h - y:.3f}" for x, y in zip(t.x, t.y, strict=True)]
    lines += [f"IMAGE={sp.path.name}", f"ID={sp.path.stem}"]
    if sp.calibration is not None:
        lines.append(f"SCALE={1 / sp.calibration.px_per_um:.8f}")
    return "\n".join(lines)


def sliders(n_points: int, landmarks: list[int]) -> pd.DataFrame:
    """geomorph slider matrix (1-based) for a closed outline: every point that
    is not a fixed landmark slides between its two neighbours."""
    rows = [((i - 1) % n_points + 1, i + 1, (i + 1) % n_points + 1)
            for i in range(n_points) if i not in landmarks]
    return pd.DataFrame(rows, columns=["before", "slide", "after"])


def feature_rows(sp: Specimen) -> list[dict]:
    """One row per outline element of a specimen: the holes and bumps added by hand."""
    md = sp.metadata
    return [{"image": sp.path.name, "genus": md.genus, "species": md.species,
             "specimen_id": md.specimen_id, "status": sp.status,
             **{k: f.get(k) for k in FEATURE_ROW_KEYS}}
            for f in sp.features or []]


def long_rows(sp: Specimen) -> pd.DataFrame:
    """All rays of one specimen with every measure, prefixed by the image name."""
    if sp.profile is None:
        return pd.DataFrame()
    t = sp.profile.table.copy()
    t.insert(0, "segment", np.arange(len(t)))
    t.insert(0, "image", sp.path.name)
    return t


PIPELINE = ".pipeline"          # hidden, technical: run log, config, records
RECORDS = PIPELINE + "/records"  # one JSON per specimen, from which the tables are built
STAGE = PIPELINE + "/staging"    # a run in progress (see run_batch)
COMPLETE = "complete"            # marker: the staged run is ready to replace the results


SUMMARY_STALE = PIPELINE + "/summary_stale"   # present while summary.csv lags behind the records


class OutputLocked(Exception):
    """An output file could not be replaced (e.g. open in Excel on Windows)."""


class SummaryStale(OutputLocked):
    """The specimen was analysed again and its record saved, but ``summary.csv``
    could not be rewritten (locked meanwhile): it is rebuilt from the records
    later (:func:`refresh_summary`)."""


def _check_replaceable(path: Path) -> None:
    """OutputLocked, before any work, when ``path`` exists and cannot be
    replaced (open in a program that locks it, e.g. Excel on Windows)."""
    if path.exists():
        try:
            with open(path, "r+b"):
                pass
        except PermissionError:
            raise OutputLocked(f"cannot write {path.name}: the file is open in another program (e.g. "
                               "Excel). Close it and try again; nothing was changed.") from None


def _replace_file(tmp: Path, dest: Path, keep: bool = False) -> None:
    """Move the finished file ``tmp`` onto ``dest`` in one step. If ``dest`` is
    locked, ``tmp`` is deleted, unless ``keep`` (a staged run, saved on retry)."""
    try:
        os.replace(tmp, dest)
    except PermissionError:
        if not keep:
            tmp.unlink(missing_ok=True)
        raise OutputLocked(f"cannot write {dest.name}: the file is open in another program (e.g. "
                           "Excel). Close it and try again; the previous file is unchanged.") from None


def _remove_table(path: Path) -> None:
    """Remove an output table that has nothing left to hold (OutputLocked if it is open elsewhere)."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        raise OutputLocked(f"cannot remove {path.name}: the file is open in another program (e.g. "
                           "Excel). Close it and try again.") from None


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    _replace_file(tmp, path)


def _write_text(text: str, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _replace_file(tmp, path)


def _json_default(o):
    if hasattr(o, "item"):          # numpy scalars
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def load_tables(config: dict) -> dict:
    """The per-image correction tables named in ``config`` (landmarks,
    calibration overrides, reviews, holes/bumps, characters). Raises ValueError on an
    invalid table."""
    return dict(landmarks=load_landmarks(config["paths"].get("landmarks_csv")),
                overrides=load_overrides(config["calibration"].get("overrides_csv")),
                reviews=load_reviews(config["paths"].get("review_csv")),
                features=load_feature_corrections(config["paths"].get("feature_corrections_csv")),
                characters=load_characters(config["paths"].get("characters_csv")))


def process_image(path: Path, config: dict, tables: dict, save_masks: bool = False) -> dict:
    """Analyse one image, draw its cell figure and return its record: every
    row it contributes to the batch files. Errors are recorded, not raised."""
    results = Path(config["paths"]["results_dir"])
    angles = np.arange(0.0, 360.0 - 1e-9, float(config["rays"]["angle_step_deg"]))
    try:
        sp = analyse_image(path, config, tables["landmarks"], tables["overrides"], tables["features"],
                           tables["characters"].get(path.name))
        apply_review(sp, reviews=tables["reviews"])
        return _finish(sp, path, results, angles, config, save_masks)
    except Exception as e:  # unreadable file, figure error, unexpected error: flag, go on
        _remove_outputs(results, path)
        return failed_record(path, config, e)


class RefusedImage(Exception):
    """An image the batch does not analyse, for a reason the user can fix."""


def failed_record(path: Path, config: dict, e: Exception) -> dict:
    """Record of an image that could not be analysed: status "failed" with
    the reason; logged (with the traceback for unexpected errors)."""
    angles = np.arange(0.0, 360.0 - 1e-9, float(config["rays"]["angle_step_deg"]))
    plain = isinstance(e, (FileNotFoundError, RefusedImage, UnsupportedImage))
    log.error("%s: FAILED %s%s", path.name, e, "" if plain else "\n" + traceback.format_exc())
    sp = Specimen(path, np.zeros((1, 1, 3), np.uint8))
    sp.metadata = parse_filename(path.stem, config.get("metadata", {}).get("separator", DEFAULT_SEPARATOR),
                                 tuple(config["calibration"].get("bar_length_range_um", DEFAULT_BAR_RANGE_UM)))
    sp.flag("failed", "error", str(e) if isinstance(e, (RefusedImage, UnsupportedImage))
            else f"{type(e).__name__}: {e}")
    return dict(image=path.name, summary=summary_row(sp, angles, _n_harmonics(config)), overlay={}, rays=[],
                outline=None, tps=None, features=[], features_measured=False)


def _n_harmonics(config: dict) -> int:
    return int((config.get("descriptors") or {}).get("n_harmonics", N_HARMONICS))


def duplicate_stems(paths: list[Path]) -> dict[str, str]:
    """Images whose names differ only by the extension (``x.png``, ``x.tif``):
    they would share one figure, one corrections file and one hand mask, so
    neither is analysed. The same name in two folders is refused the same way;
    the same file given twice is not a duplicate. {file name: reason}."""
    by_stem: dict[str, dict[Path, Path]] = {}
    for p in paths:
        by_stem.setdefault(p.stem, {}).setdefault(p.resolve(), p)
    out = {}
    for group in by_stem.values():
        files = list(group.values())
        if len(files) < 2:
            continue
        names = [p.name for p in files]
        if len(set(names)) == len(names):
            reason = f"duplicate name: {' and '.join(names)} differ only by the extension; rename one"
        else:
            reason = (f"duplicate name: {' and '.join(str(p) for p in files)} have the same file name "
                      "(images from different folders); rename one")
        out.update({n: reason for n in names})
    return out


def write_config_used(folder: Path, config: dict) -> None:
    """Reproducibility: the exact parameters of the run whose results are in
    ``folder`` (written with them, so it always matches them)."""
    (folder / PIPELINE).mkdir(parents=True, exist_ok=True)
    _write_text(f"# Run of {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                + yaml.safe_dump({"software": provenance()}, sort_keys=False, allow_unicode=True)
                + yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                folder / PIPELINE / "config_used.yaml")


def _rmtree(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d)


def _remove_outputs(results: Path, path: Path) -> None:
    """Remove the figure and saved masks of an image (before recording it as
    failed, so they cannot contradict the failed row). Hand corrections
    (``cells/<stem>.csv``, ``cells/<stem>_mask.png``) are kept."""
    (results / "cells" / f"{path.stem}.png").unlink(missing_ok=True)
    (results / "masks" / f"{path.stem}_mask.png").unlink(missing_ok=True)
    mask = results / RECORDS / f"{path.name}.mask.png"
    if mask.exists():
        _write_in_records(results, lambda: mask.unlink(missing_ok=True))


def _commit(results: Path) -> None:
    """Replace the previous results by the completed staging folder
    (:func:`run_batch`). Each step can be repeated, so an interrupted commit
    is finished by :func:`recover`. ``summary.csv`` goes first: if it is
    locked, nothing has changed yet. The figures (and, for a run that saved
    them, the masks) of images no longer analysed or failed are removed;
    hand corrections (``cells/<stem>.csv``, ``cells/<stem>_mask.png``) are
    never touched. ``config_used.yaml`` goes last."""
    stage = results / STAGE
    run = json.loads((stage / COMPLETE).read_text(encoding="utf-8"))
    if (stage / "summary.csv").exists():
        _replace_file(stage / "summary.csv", results / "summary.csv", keep=True)
    for name in run["remove"]:
        (results / "cells" / f"{Path(name).stem}.png").unlink(missing_ok=True)
        if run["save_masks"]:
            (results / "masks" / f"{Path(name).stem}_mask.png").unlink(missing_ok=True)
    if (stage / RECORDS).is_dir():
        old = results / PIPELINE / "records.old"
        _rmtree(old)
        if (results / RECORDS).is_dir():
            (results / RECORDS).replace(old)
        (stage / RECORDS).replace(results / RECORDS)
        _rmtree(old)
    for sub in ("cells", "masks"):
        if (stage / sub).is_dir():
            (results / sub).mkdir(exist_ok=True)
            for f in (stage / sub).iterdir():
                f.replace(results / sub / f.name)
    used = stage / PIPELINE / "config_used.yaml"
    if used.exists():
        used.replace(results / PIPELINE / "config_used.yaml")
    if (results / EXPORTS).is_dir():     # rewritten by run_batch, or later (refresh_exports)
        (results / STALE).touch()
    _rmtree(stage)


def recover(results: Path) -> None:
    """Bring a results folder back to a consistent state after a run or
    commit that was interrupted (crash, power cut, file locked): a completed
    run is committed, an incomplete one is dropped, and records moved aside
    are put back."""
    results = Path(results)
    stage = results / STAGE
    if (stage / COMPLETE).exists():
        try:
            _commit(results)
        except OutputLocked as e:
            log.warning("%s", e)
            return
    elif stage.exists():
        _rmtree(stage)
    old = results / PIPELINE / "records.old"
    if old.is_dir():
        if (results / RECORDS).is_dir():
            _rmtree(old)
        else:
            old.replace(results / RECORDS)


def _finish(sp: Specimen, path: Path, results: Path, angles, config: dict, save_masks) -> dict:
    """Figure, mask and record of an analysed specimen."""
    record_mask = results / RECORDS / f"{path.name}.mask.png"
    (results / RECORDS).mkdir(parents=True, exist_ok=True)
    if sp.segmentation is not None and sp.segmentation.mask.any():   # starting point of mask editing
        _write_in_records(results, lambda: save_mask(sp.segmentation.mask, record_mask))
    elif record_mask.exists():
        _write_in_records(results, lambda: record_mask.unlink(missing_ok=True))
    (results / "cells").mkdir(parents=True, exist_ok=True)
    try:
        draw_report(sp, results / "cells" / f"{path.stem}.png")
    except Exception as e:  # the measurements stand without their figure: keep them, say so
        log.error("%s: cell figure not drawn\n%s", path.name, traceback.format_exc())
        (results / "cells" / f"{path.stem}.png").unlink(missing_ok=True)
        sp.flag("check", "figure", f"the cell figure could not be drawn ({type(e).__name__}: {e}); "
                                   "the measurements are not affected")
    if save_masks and sp.segmentation is not None and sp.segmentation.mask.any():
        (results / "masks").mkdir(exist_ok=True)
        save_mask(sp.segmentation.mask, results / "masks" / f"{path.stem}_mask.png")
    level = {"ok": logging.INFO, "check": logging.WARNING}.get(sp.status, logging.ERROR)
    reviewed = f" (reviewed: {sp.review_note})" if sp.review_note else ""
    log.log(level, "%s: %s%s %s", path.name, sp.status.upper(), reviewed, " | ".join(sp.messages))
    return dict(image=path.name, summary=summary_row(sp, angles, _n_harmonics(config)), overlay=overlay(sp),
                rays=long_rows(sp).to_dict("records"), outline=outline_profile_row(sp),
                tps=tps_block(sp), features=feature_rows(sp), features_measured=sp.features is not None)


def overlay(sp: Specimen, max_points: int = 1500) -> dict:
    """Geometry shown under the correction tools of the interface: outline
    (pixel contour, thinned), centroid, aperture corners, fundus, the length
    and width lines as measured (as in the cell figure), scale bar,
    holes/bumps."""
    out = {"shape": list(sp.image.shape[:2])}
    seg = sp.segmentation
    if seg is not None and seg.mask.any():
        c = contour_of(seg.mask)
        out["outline"] = c[:: max(1, len(c) // max_points)].round(1).tolist()
    if sp.centroid is not None:
        out["centroid"] = list(sp.centroid)
    ap = sp.landmark.aperture if sp.landmark else None
    if ap is not None:
        out["aperture"] = [list(ap.start), list(ap.end)]
    if sp.fundus is not None:
        out["fundus"] = list(sp.fundus)
        out["fundus_source"] = sp.fundus_source
    if sp.classic is not None and ap is not None:
        poly = subpixel_outline(seg.mask)
        m, n, u = oral_axis(ap.start, ap.end, sp.centroid, sp.fundus)
        t, s = (poly - m) @ n, (poly - m) @ u
        at = lambda tt, ss: (m + tt * n + ss * u).tolist()  # noqa: E731
        tw = t.min() + sp.classic["widest_position"] * np.ptp(t)
        out["axes"] = [at(t.min(), 0) + at(t.max(), 0), at(tw, s.min()) + at(tw, s.max())]
    if sp.features is not None:              # measured: the image is calibrated
        ppu = sp.calibration.px_per_um
        out["features"] = [{**{k: f.get(k) for k in ("kind", "number", "x", "y", "size_um", "width_um",
                                                     "region", "note")},
                            # circle shown in the interface: the user's radius (half the
                            # width for one added in a CSV without a circle)
                            "radius_px": feature_radius_px(f, ppu)}
                           for f in sp.features]
    cal = sp.calibration
    if cal is not None:
        out["px_per_um"] = cal.px_per_um
        out["bar_length_um"] = cal.bar_length_um
        if cal.line is not None:
            out["bar"] = list(cal.line)
        elif cal.bar is not None:
            b = cal.bar
            y = (b.y_top + b.y_bottom) / 2
            out["bar"] = [b.x0, y, b.x0 + b.length_px, y]
    return out


def _record_path(results: Path, image: str) -> Path:
    return results / RECORDS / f"{image}.json"


# The summary rows of the records, kept in memory per records folder, so that
# re-running one image after a correction does not read every record again
# (slow on network and WSL drives, where even reading the date of each file
# is). They stay valid while the folder's modification time is unchanged:
# records are written by replacing the file, which changes it, and the writes
# made here update the copy in memory (see _write_in_records).
_SUMMARIES: dict[str, list] = {}       # folder -> [folder stamp, {file name: light record}]


def _stamp(folder: Path) -> tuple | None:
    try:
        st = folder.stat()
    except FileNotFoundError:
        return None
    return st.st_ino, st.st_mtime_ns


def _light(record: dict) -> dict:
    """What the summary needs of a record: image, batch order, summary row."""
    return {"image": record.get("image"), "order": record["order"], "summary": record["summary"]}


def _write_in_records(results: Path, write) -> list | None:
    """Run ``write()``, which writes (or removes) one file in the records
    folder, keeping the summaries in memory valid if they were (else they are
    dropped, and read again when needed). Returns the entry to update, or None."""
    folder = results / RECORDS
    key = os.path.abspath(folder)
    cached = _SUMMARIES.get(key)
    valid = cached is not None and cached[0] == _stamp(folder)
    write()
    if not valid:
        _SUMMARIES.pop(key, None)
        return None
    cached[0] = _stamp(folder)
    return cached


def save_record(results: Path, record: dict, order: int) -> None:
    path = _record_path(results, record["image"])
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {**record, "order": order}

    def write():               # replace the file: a reader never sees half of it
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record, default=_json_default), encoding="utf-8")
        os.replace(tmp, path)

    cached = _write_in_records(results, write)
    if cached is not None:
        cached[1][path.name] = _light(record)


def load_records(results: Path) -> list[dict]:
    """All specimen records of a results folder, in batch order."""
    files = (results / RECORDS).glob("*.json") if (results / RECORDS).is_dir() else []
    return sorted((json.loads(f.read_text(encoding="utf-8")) for f in files), key=lambda r: r["order"])


def load_summaries(results: Path) -> list[dict]:
    """Image, batch order and summary row of every record of a results folder,
    in batch order. Read from disk only when the records changed outside this
    program (see ``_SUMMARIES``); the rows are shared: do not modify them."""
    folder = results / RECORDS
    key = os.path.abspath(folder)
    stamp = _stamp(folder)              # before reading: a change meanwhile is read next time
    if stamp is None:
        _SUMMARIES.pop(key, None)
        return []
    cached = _SUMMARIES.get(key)
    if cached is None or cached[0] != stamp:
        cached = [stamp, {f.name: _light(json.loads(f.read_text(encoding="utf-8")))
                          for f in folder.glob("*.json")}]
        _SUMMARIES[key] = cached
    return sorted(list(cached[1].values()), key=lambda r: r["order"])   # list(): one step


EXPORTS = "exports"   # derived tables, written on demand into the results folder
STALE = PIPELINE + "/exports_stale"    # present while exports/ lags behind re-run images


def exports_stale(results: Path) -> bool:
    """True when images were re-run since ``exports/`` was last written."""
    return (Path(results) / STALE).exists()


def refresh_exports(results: Path, config: dict) -> bool:
    """Rewrite ``exports/`` if re-runs left it out of date (see
    :func:`rerun_images`); returns True if it was rewritten."""
    results = Path(results)
    recover(results)
    if not exports_stale(results):
        return False
    if (results / EXPORTS).is_dir():
        export_derived(results, config)
    (results / STALE).unlink(missing_ok=True)
    return True


def assemble(results: Path) -> pd.DataFrame:
    """Write ``summary.csv`` from the specimen records; returns the summary.

    The derived tables (profiles, outline/GM) are written by
    :func:`export_derived`: on demand, and at the end of a run when they
    already exist (see :func:`run_batch`, :func:`rerun_images`)."""
    df = pd.DataFrame([r["summary"] for r in load_summaries(results)])
    _write_csv(df, results / "summary.csv")
    (results / SUMMARY_STALE).unlink(missing_ok=True)
    return df


def summary_stale(results: Path) -> bool:
    """True when ``summary.csv`` lags behind the records (see :class:`SummaryStale`)."""
    return (Path(results) / SUMMARY_STALE).exists()


def refresh_summary(results: Path) -> bool:
    """Rewrite ``summary.csv`` if a correction could not (see
    :class:`SummaryStale`); True if it was rewritten. Raises OutputLocked if
    it is still locked."""
    if not summary_stale(results):
        return False
    assemble(Path(results))
    return True


def export_derived(results: Path, config: dict) -> Path:
    """(Re)write the derived tables into ``results/exports/`` from the specimen
    records: the long ray profiles, the outline profile and its geomorph files
    (tps, sliders) and the holes/bumps. A table with nothing to write is
    removed, so no file is left from an earlier run. Returns the exports
    folder. ``summary.csv`` itself is always in the results root."""
    records = load_records(results)
    out = results / EXPORTS
    out.mkdir(parents=True, exist_ok=True)
    rays = [row for r in records for row in r["rays"]]
    if rays:
        _write_csv(pd.DataFrame(rays), out / "profiles_long.csv")
    else:
        _remove_table(out / "profiles_long.csv")
    outlines = [r for r in records if r["outline"] is not None]
    if outlines:
        _write_csv(pd.DataFrame([r["outline"] for r in outlines]), out / "outline_profile.csv")
        _write_text("\n".join(r["tps"] for r in outlines) + "\n", out / "outline_coordinates.tps")
        op = config["outline_profile"]
        _write_csv(sliders(op["n_points"], landmark_points(op["n_points"], op["n_aperture"],
                                                           op.get("fundus_anchor", True))),
                   out / "outline_sliders.csv")
    else:
        for name in ("outline_profile.csv", "outline_coordinates.tps", "outline_sliders.csv"):
            _remove_table(out / name)
    feat_cols = ["image", "genus", "species", "specimen_id", "status", *FEATURE_ROW_KEYS]
    if any(r["features_measured"] for r in records):  # header even when there is no feature
        _write_csv(pd.DataFrame([f for r in records for f in r["features"]], columns=feat_cols),
                   out / "outline_features.csv")
    else:
        _remove_table(out / "outline_features.csv")
    (results / STALE).unlink(missing_ok=True)
    return out


def run_batch(paths: list[Path], config: dict, save_masks: bool = False,
              export: bool = False, progress=None, should_stop=None) -> pd.DataFrame:
    """Process ``paths`` and write the outputs listed in the module docstring.

    Returns the summary table. Any error on one image is logged and recorded
    as status "failed"; the batch continues. ``progress(i, n, image, status)``
    is called after each image. ``export`` also writes the derived tables
    into ``results/exports/`` (rewritten anyway when it already exists, so a
    run never leaves an out-of-date export).

    A run is all or nothing: the images are analysed into a hidden staging
    folder, with its own summary and settings, which replaces the previous
    results only when the run completes (:func:`_commit`; hand corrections in
    ``cells/`` are never touched). When ``should_stop()`` returns True the run
    is cancelled and the previous results are kept as they were, so a results
    folder never mixes two runs (two sets of settings). Raises OutputLocked
    when ``summary.csv`` cannot be replaced: the previous results stay in
    place and the finished run is kept aside, saved by :func:`recover` (when
    the folder is opened again, or on "retry") without analysing again.
    ValueError when there is no image.
    """
    if not paths:
        raise ValueError("no images to analyse")
    results = Path(config["paths"]["results_dir"])
    results.mkdir(parents=True, exist_ok=True)
    recover(results)
    stage = results / STAGE
    _rmtree(stage)
    staged = {**config, "paths": {**config["paths"], "results_dir": str(stage)}}
    tables = load_tables(config)
    dupes = duplicate_stems(paths)
    for i, path in enumerate(paths):
        if should_stop is not None and should_stop():
            log.warning("Stopped by the user after %d of %d images: run cancelled, "
                        "previous results kept", i, len(paths))
            _rmtree(stage)
            df = pd.read_csv(results / "summary.csv") if (results / "summary.csv").exists() \
                else pd.DataFrame()
            df.attrs["cancelled"] = True
            return df
        if path.name in dupes:
            record = failed_record(path, staged, RefusedImage(dupes[path.name]))
        else:
            record = process_image(path, staged, tables, save_masks)
        save_record(stage, record, i)
        if progress is not None:
            progress(i + 1, len(paths), path.name, record["summary"]["status"])
    df = assemble(stage)
    write_config_used(stage, config)
    names = {p.name for p in paths}
    old = {r["image"] for r in load_summaries(results)}
    failed = {r["image"] for r in load_summaries(stage) if r["summary"]["status"] == "failed"}
    remove = sorted((old - names) | failed)     # figures of images gone or failed
    _write_text(json.dumps({"remove": remove, "save_masks": save_masks}), stage / COMPLETE)
    try:
        _commit(results)
    except OutputLocked:     # the finished run is kept aside: recover() saves it once the file is free
        raise OutputLocked("the analysis finished, but its results could not be saved: summary.csv is "
                           "open in another program (e.g. Excel). Close it, then retry: the results are "
                           "saved without analysing again.") from None
    if export or (results / EXPORTS).is_dir():
        export_derived(results, config)
    if len(df):
        log.info("%d images: %s. Results in %s", len(df), df["status"].value_counts().to_dict(), results)
    return df


def rerun_images(paths: list[Path], config: dict) -> pd.DataFrame:
    """Analyse again some images of an existing results folder (after a
    correction) and rewrite ``summary.csv``. ``config`` must be the one of
    the original run, so that all records stay comparable.

    Fast enough for one correction at a time: the other records are not read
    again (see :func:`load_summaries`). An existing ``exports/`` is not
    rewritten (that reads every record) but marked out of date, until
    :func:`refresh_exports`, :func:`export_derived` or the next run.

    Raises RuntimeError, before changing anything, when records are missing
    for images listed in ``summary.csv`` (rewriting it would drop their rows),
    and OutputLocked, before changing anything, when ``summary.csv`` cannot be
    replaced; SummaryStale when it became locked during the work (the records
    are saved, ``summary.csv`` is rebuilt later)."""
    results = Path(config["paths"]["results_dir"])
    recover(results)
    _check_replaceable(results / "summary.csv")
    order = {r["image"]: r["order"] for r in load_summaries(results)}
    if (results / "summary.csv").exists():
        listed = set(pd.read_csv(results / "summary.csv", usecols=["image"], dtype=str)["image"])
        lost = sorted(listed - set(order))
        if lost:
            raise RuntimeError(f"{len(lost)} specimen records are missing from {RECORDS} (e.g. {lost[0]}); "
                               "summary.csv was not changed: run the whole analysis again")
    if (results / EXPORTS).is_dir():
        (results / STALE).parent.mkdir(parents=True, exist_ok=True)
        (results / STALE).touch()
    tables = load_tables(config)
    new_order = max(order.values(), default=-1) + 1      # images not in the results yet: after the others
    for path in paths:
        twins = [p for p in path.parent.glob(f"{path.stem}.*") if p.suffix.lower() in IMAGE_EXTS]
        if len(twins) > 1:
            record = failed_record(path, config, RefusedImage(duplicate_stems(twins)[path.name]))
            _remove_outputs(results, path)
        else:
            record = process_image(path, config, tables)
        if path.name not in order:                       # each its own place, in the order given
            order[path.name] = new_order
            new_order += 1
        save_record(results, record, order[path.name])
    try:
        return assemble(results)
    except OutputLocked:
        (results / SUMMARY_STALE).touch()
        raise SummaryStale("the specimen was analysed again and the change is saved, but summary.csv "
                           "is open in another program (e.g. Excel) and could not be updated: close it; "
                           "it is updated at the next change or when the analysis is opened again.") from None


PATH_KEYS = [("paths", "raw_dir"), ("paths", "landmarks_csv"), ("paths", "review_csv"),
             ("paths", "feature_corrections_csv"), ("paths", "characters_csv"), ("paths", "results_dir"),
             ("calibration", "overrides_csv"), ("segmentation", "masks_dir"),
             ("segmentation", "background_overrides_csv")]


def resolve_paths(config: dict, base: Path) -> dict:
    """Relative file locations of a config file are read from ``base`` (the
    config file's folder; the current folder for the built-in settings), so a
    run does not depend on where the program is installed."""
    for section, key in PATH_KEYS:
        value = config.get(section, {}).get(key)
        if value and not Path(value).is_absolute():
            config[section][key] = str(base / value)
    return config


def merge_settings(base: dict, over: dict, where: str = "") -> tuple[dict, list[str]]:
    """``over`` laid over ``base`` (a copy): a setting of ``over`` wins, the
    others come from ``base``. Returns the merged settings and the settings of
    ``base`` that ``over`` leaves out ("section" or "section.key"). Raises
    UsageError where ``over`` gives a value for a whole section."""
    out, taken = dict(base), []
    for key, value in base.items():
        name = f"{where}{key}"
        if key not in over:
            taken.append(name)
        elif isinstance(value, dict):
            if not isinstance(over[key], dict):
                raise UsageError(f"'{name}' must be a section of settings (key: value lines), not "
                                 f"{over[key]!r}")
            out[key], sub = merge_settings(value, over[key], f"{name}.")
            taken += sub
    out.update({k: v for k, v in over.items() if k not in base})
    for key in over.keys() & base.keys():
        if not isinstance(base[key], dict):
            out[key] = over[key]
    return out, taken


def unknown_settings(base: dict, over: dict, where: str = "") -> list[str]:
    """Settings of ``over`` that ``base`` does not have (a typo would otherwise be
    ignored without a word), each with the nearest real name when there is one."""
    out = []
    for key, value in over.items():
        name = f"{where}{key}"
        if key not in base:
            near = difflib.get_close_matches(str(key), [str(k) for k in base], n=1)
            out.append(name + (f" (did you mean {where}{near[0]}?)" if near else ""))
        elif isinstance(value, dict) and isinstance(base[key], dict):
            out += unknown_settings(base[key], value, f"{name}.")
    return out


def default_config() -> Path:
    """``config.yaml`` in the current folder, else the built-in settings."""
    here = Path("config.yaml")
    return here if here.exists() else DEFAULT_CONFIG


class UsageError(Exception):
    """A problem with the command line or its files, reported without a traceback."""


def main(argv: list[str] | None = None) -> int:
    """Command line entry point (see module docstring). Returns the exit code:
    0 = every image analysed (some may be flagged "check"), 1 = every image
    failed, 2 = nothing could be run or written (missing settings, input or
    images, invalid correction file, results file locked)."""
    from ta_morpho import __version__
    p = argparse.ArgumentParser(prog="ta-morpho", description="Shape measurement of testate amoeba tests")
    p.add_argument("inputs", nargs="*", type=Path,
                   help="images or folders (default: paths.raw_dir from config)")
    p.add_argument("--config", type=Path, default=None,
                   help="settings file (default: config.yaml in the current folder, else the "
                        "built-in settings); relative paths inside it are read from its folder "
                        "(from the current folder for the built-in settings)")
    p.add_argument("-o", "--output", type=Path,
                   help="results folder (default: paths.results_dir from config); its results "
                        "are replaced by each run, hand corrections in cells/ are kept")
    p.add_argument("--step", type=float, help="override rays.angle_step_deg")
    p.add_argument("--save-masks", action="store_true",
                   help="also write masks to <results>/masks/ (to correct by hand)")
    p.add_argument("--export", action="store_true",
                   help="also write the derived tables (profiles, outline/GM, holes/bumps) to <results>/exports/")
    p.add_argument("--click", action="store_true",
                   help="click start landmarks into landmarks.csv before running")
    p.add_argument("--version", action="version", version=f"TA-Morpho {__version__}")
    args = p.parse_args(argv)
    try:
        return _run(args)
    except (UsageError, OutputLocked) as e:
        print(f"ta-morpho: error: {e}", file=sys.stderr)
        return 2


def _run(args) -> int:
    cfg_path = args.config or default_config()
    if not cfg_path.is_file():
        raise UsageError(f"settings file not found: {cfg_path}")
    try:
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise UsageError(f"cannot read the settings file {cfg_path}: {e}") from None
    if not isinstance(config, dict):
        raise UsageError(f"the settings file {cfg_path} holds no settings (key: value lines)")
    builtin = cfg_path.resolve() == DEFAULT_CONFIG
    config = resolve_paths(config, Path.cwd() if builtin else cfg_path.resolve().parent)
    taken = []
    if not builtin:                             # what the file leaves out: the built-in settings
        defaults = resolve_paths(yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")), Path.cwd())
        unknown = unknown_settings(defaults, config)
        if unknown:
            raise UsageError(f"unknown settings in {cfg_path}: {'; '.join(unknown)}. Correct the names "
                             "(docs/PARAMETERS.md lists every setting)")
        config, taken = merge_settings(defaults, config)
    if args.output:
        config["paths"]["results_dir"] = str(args.output)
    if args.step:
        config["rays"]["angle_step_deg"] = args.step
    from ta_morpho.gui.settings import problems     # the limits the desktop program uses (no Qt needed)
    bad = problems(config)
    if bad:
        raise UsageError("some settings cannot be used:\n  " + "\n  ".join(bad))
    missing = [str(i) for i in args.inputs if not i.exists()]
    if missing:
        raise UsageError("input not found: " + ", ".join(missing))
    if not args.inputs and not Path(config["paths"]["raw_dir"]).is_dir():
        raise UsageError(f"image folder not found: {config['paths']['raw_dir']} "
                         "(give images or folders, or set paths.raw_dir)")
    paths = list_images(args.inputs, config["paths"]["raw_dir"])
    if not paths:
        where = ", ".join(map(str, args.inputs)) or config["paths"]["raw_dir"]
        raise UsageError(f"no images (.png, .jpg, .tif) found in {where}")
    try:
        load_tables(config)                     # an invalid correction file stops before any work
        load_background_overrides(config["segmentation"].get("background_overrides_csv"))
    except ValueError as e:
        raise UsageError(str(e)) from None

    results = Path(config["paths"]["results_dir"])
    pipeline = results / PIPELINE
    pipeline.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(pipeline / "batch.log", mode="w", encoding="utf-8")])
    if builtin:
        log.info("using the built-in settings (%s)", DEFAULT_CONFIG)
    elif taken:
        log.info("settings from %s; not in it, taken from the built-in settings: %s", cfg_path, ", ".join(taken))
    if args.click:
        click_landmarks(paths, Path(config["paths"]["landmarks_csv"]))
    df = run_batch(paths, config, save_masks=args.save_masks, export=args.export)
    if len(df) and (df["status"] == "failed").all():
        log.error("every image failed: see the messages column of %s", results / "summary.csv")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
