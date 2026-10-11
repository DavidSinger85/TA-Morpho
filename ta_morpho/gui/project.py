"""A project for the graphical interface: an input folder of images and an
output folder holding the settings, the user's corrections and the results.

Layout of the output folder::

    summary.csv                the results, one row per specimen
    cells/
        <stem>.png             one report figure per specimen
        <stem>.csv             that specimen's corrections (typed rows: landmark,
                               scale, feature, review, character), if any
        <stem>_mask.png        its outline corrected by hand, if any
    exports/                   the derived tables, written on demand (see export()); a
                               correction marks them out of date (refresh_exports())
    .pipeline/                 hidden, technical
        project.yaml           input folder and settings (all of config.yaml but the paths)
        config_used.yaml, batch.log
        inputs/                the corrections gathered into the CSVs the pipeline reads
        records/               one record per specimen, the source of the tables

Everything the user touches is in one place per specimen (``cells/``); the
consolidated correction files the pipeline consumes are rebuilt in
``.pipeline/inputs/`` before each run (only the corrected images' rows before
a re-run after a correction). The image folder is never modified.
Everything here is independent of Qt, so it can be tested and used from scripts.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import os
import shutil
import socket
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import yaml
from scipy import ndimage as ndi
from skimage import measure

from ta_morpho.export import (COMPLETE, DEFAULT_CONFIG, EXPORTS, PIPELINE, RECORDS, STAGE, OutputLocked, SummaryStale,
                        export_derived, exports_stale, load_summaries, recover, refresh_exports, refresh_summary,
                        rerun_images, run_batch, summary_stale)
from ta_morpho.features import KINDS
from ta_morpho.gui.paths import to_local_path
from ta_morpho.gui.settings import problems as setting_problems
from ta_morpho.image_io import list_images, read_image, write_image
from ta_morpho.characters import TAXON
from ta_morpho.characters import VALUES as CHARACTER_VALUES
from ta_morpho.landmark import LANDMARK_COLUMNS

CELLS = "cells"
INPUTS = PIPELINE + "/inputs"
PROJECT_FILE = PIPELINE + "/project.yaml"
EXPORT_FILES = ("profiles_long.csv", "outline_profile.csv", "outline_coordinates.tps", "outline_sliders.csv",
                "outline_features.csv")          # the tables export_derived writes into exports/
KEEP_BACKUPS = 3        # "Erase and run again" keeps only this many correction backups

# The pieces of one specimen's correction file. x/y are shared by the landmark
# (aperture start) and the feature (hole/bump centre) rows.
SCALE_COLUMNS = ["px_per_um", "bar_length_um", "bar_x0", "bar_y0", "bar_x1", "bar_y1"]
FEATURE_STR = ["action", "kind", "note"]
FEATURE_NUM = ["x", "y", "radius_px"]
FEATURE_COLUMNS = ["action", "kind", "x", "y", "radius_px", "note"]
CORR_COLUMNS = ["type"] + LANDMARK_COLUMNS + SCALE_COLUMNS + ["action", "kind", "radius_px", "name", "value", "note"]
# The consolidated correction files the pipeline reads (in .pipeline/inputs/).
INPUT_FILES = {"landmarks.csv": ["image", *LANDMARK_COLUMNS],
               "calibration_overrides.csv": ["image", *SCALE_COLUMNS],
               "qc_review.csv": ["image", "note"],
               "feature_corrections.csv": ["image", *FEATURE_COLUMNS],
               "characters.csv": ["image", "name", "value"]}


def default_settings() -> dict:
    """All settings of the default config.yaml except the file locations."""
    return _strip_paths(yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")))


def _strip_paths(cfg: dict) -> dict:
    """Settings without the file locations (which belong to the project) and
    without the software versions recorded in config_used.yaml."""
    out = copy.deepcopy(cfg)
    out.pop("paths", None)
    out.pop("software", None)
    out.get("calibration", {}).pop("overrides_csv", None)
    for k in ("masks_dir", "background_overrides_csv"):
        out.get("segmentation", {}).pop(k, None)
    return out


class Project:
    """Input folder, output folder, settings and corrections of one analysis."""

    def __init__(self, output_dir: str | Path, input_dir: str | Path | None = None,
                 settings: dict | None = None):
        self.output_dir = Path(output_dir)
        self.input_dir = Path(input_dir) if input_dir else None
        self.settings = _strip_paths(settings) if settings else default_settings()
        self.history: dict[str, list[dict]] = {}     # undo stack of corrections, per image

    # ----- files --------------------------------------------------------------
    @property
    def pipeline_dir(self) -> Path:
        return self.output_dir / PIPELINE

    @property
    def inputs_dir(self) -> Path:
        return self.output_dir / INPUTS

    @property
    def cells_dir(self) -> Path:
        return self.output_dir / CELLS

    def cell_csv(self, image: str) -> Path:
        """This specimen's correction file (next to its figure)."""
        return self.cells_dir / f"{Path(image).stem}.csv"

    def mask_path(self, image: str) -> Path:
        """Hand-corrected mask of an image (read by the segmentation step)."""
        return self.cells_dir / f"{Path(image).stem}_mask.png"

    @classmethod
    def open(cls, output_dir: str | Path) -> Project:
        """Reopen a project from its output folder (new project if none there).
        The saved image folder is converted between Windows and WSL paths, so
        a project opened on the other side still finds its images. Raises
        ValueError for a folder holding results that are not a project."""
        output_dir = Path(output_dir)
        f = output_dir / PROJECT_FILE
        if not f.exists():
            if (output_dir / "summary.csv").exists():
                raise ValueError(f"{output_dir} holds results that are not a TA-Morpho project "
                                 "(no .pipeline/project.yaml): choose another output folder")
            return cls(output_dir)
        d = _read_project_file(f)
        settings = default_settings()
        _merge(settings, d.get("settings") or {})      # new defaults fill in missing keys
        inp = d.get("input_dir")
        project = cls(output_dir, to_local_path(inp) if inp else None, settings)
        recover(output_dir)                            # a run or commit cut short
        try:
            refresh_summary(output_dir)                # a correction met a locked summary.csv
            project.refresh_exports()                  # corrections made when it was last open
        except OutputLocked as e:                      # still open in another program: later
            logging.getLogger(__name__).warning("%s", e)
        return project

    # One window per analysis: a correction in one window would otherwise remove a run going on
    # in another. The lock says who has the analysis open; a lock left by a crash is overridden
    # after a question.
    @property
    def lock_file(self) -> Path:
        return self.pipeline_dir / "lock"

    def locked_by(self) -> str | None:
        """Who else has this analysis open ("computer, since time"), or None."""
        try:
            d = json.loads(self.lock_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if d.get("host") == socket.gethostname() and d.get("pid") == os.getpid():
            return None                                  # this program itself
        return f"{d.get('host', '?')}, since {d.get('time', '?')}"

    def lock(self) -> None:
        """Mark this analysis as open in this program."""
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(json.dumps({"host": socket.gethostname(), "pid": os.getpid(),
                                              "time": datetime.now().strftime("%Y-%m-%d %H:%M")}),
                                  encoding="utf-8")

    def unlock(self) -> None:
        """Release the lock, if it is this program's."""
        if self.lock_file.exists() and self.locked_by() is None:
            self.lock_file.unlink(missing_ok=True)

    @staticmethod
    def foreign_files(output_dir: str | Path) -> list[str]:
        """Names in a folder that is not yet a project and that the program did not
        write (to warn before using it as the output folder); [] for a project or a
        missing or empty folder."""
        d = Path(output_dir)
        if not d.is_dir() or (d / PROJECT_FILE).exists():
            return []
        return sorted(f.name for f in d.iterdir() if f.name not in ("summary.csv", CELLS, EXPORTS, PIPELINE))

    def finished_run_pending(self) -> bool:
        """True when a finished run could not be saved (results file locked) and waits."""
        return (self.output_dir / STAGE / COMPLETE).exists()

    def save_finished_run(self) -> bool:
        """Save a finished run that could not be saved (see :func:`ta_morpho.export.run_batch`),
        without analysing again; True when saved, False while the file is still locked."""
        recover(self.output_dir)
        return not self.finished_run_pending()

    def save(self) -> None:
        """Write the image folder and the settings (.pipeline/project.yaml) in one
        step: a crash or a full disk never leaves a half-written file."""
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        f = self.output_dir / PROJECT_FILE
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(yaml.safe_dump(
            {"input_dir": str(self.input_dir) if self.input_dir else None, "settings": self.settings},
            sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, f)

    def config(self, settings: dict | None = None) -> dict:
        """The full pipeline configuration: settings (default: the current
        ones) + this project's paths.
        The correction tables live in ``.pipeline/inputs/`` (rebuilt before each
        run from the per-specimen files); masks live next to the figures."""
        cfg = copy.deepcopy(self.settings if settings is None else settings)
        i = self.inputs_dir
        cfg["paths"] = {"raw_dir": str(self.input_dir), "results_dir": str(self.output_dir),
                        "landmarks_csv": str(i / "landmarks.csv"), "review_csv": str(i / "qc_review.csv"),
                        "feature_corrections_csv": str(i / "feature_corrections.csv"),
                        "characters_csv": str(i / "characters.csv")}
        cfg.setdefault("calibration", {})["overrides_csv"] = str(i / "calibration_overrides.csv")
        cfg.setdefault("segmentation", {})["masks_dir"] = str(self.cells_dir)
        return cfg

    def images(self) -> list[Path]:
        if self.input_dir is None or not self.input_dir.is_dir():
            return []
        return list_images([self.input_dir], self.input_dir)

    # ----- runs ---------------------------------------------------------------
    def config_used(self) -> dict | None:
        """Configuration of the last run (None if never run)."""
        f = self.pipeline_dir / "config_used.yaml"
        return yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None

    def last_run_config(self) -> dict:
        """Settings of the last run with *this* project's paths (current
        settings if never run). The paths saved in config_used.yaml are not
        used: the folder may have been moved, copied, or opened from another
        computer (e.g. /mnt/f/... under WSL and F:\\... under Windows), and
        corrections must go to the project that is open, never to the old one."""
        used = self.config_used()
        return self.config(_strip_paths(used) if used else None)

    def has_results(self) -> bool:
        return (self.output_dir / "summary.csv").exists()

    def settings_changed(self) -> bool:
        """True when the settings or the input folder differ from the last run."""
        used = self.config_used()
        if used is None:
            return False
        raw = used.get("paths", {}).get("raw_dir")
        return _strip_paths(used) != self.settings or (to_local_path(raw) if raw else None) != self.input_dir

    def _input_rows(self, image: str) -> dict[str, list[dict]]:
        """This specimen's rows in each consolidated correction file."""
        c = self._corr(image)
        rows: dict[str, list[dict]] = {f: [] for f in INPUT_FILES}
        if c["landmarks"]:
            rows["landmarks.csv"].append({"image": image, **c["landmarks"]})
        if c["scale"]:
            rows["calibration_overrides.csv"].append({"image": image, **c["scale"]})
        if c.get("review") is not None:
            rows["qc_review.csv"].append({"image": image, "note": c["review"]})
        rows["feature_corrections.csv"] += [{"image": image, **feat} for feat in c["features"]]
        rows["characters.csv"] += [{"image": image, "name": k, "value": v} for k, v in c["characters"].items()]
        return rows

    def _materialize_inputs(self, changed: list[str] | None = None) -> None:
        """Gather every specimen's correction file into the consolidated CSVs
        the pipeline reads (hidden in ``.pipeline/inputs/``). Masks stay in
        ``cells/``; this never touches them.

        ``changed``: only these images' corrections changed since the last
        time; their rows are replaced and the others kept as they are (reading
        every correction file is slow on network and WSL drives). The files
        are the same as a full rebuild, which is done when one is missing."""
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        i = self.inputs_dir
        order = [img.name for img in self.images()]
        old = {}
        if changed is not None:
            try:
                old = {f: pd.read_csv(i / f, dtype=str, keep_default_na=False) for f in INPUT_FILES}
            except (FileNotFoundError, pd.errors.EmptyDataError):
                changed = None
            if changed is not None and any(list(old[f].columns) != cols for f, cols in INPUT_FILES.items()):
                changed = None                       # other columns: rebuild everything
        names = order if changed is None else [n for n in order if n in set(changed)]
        new: dict[str, list[dict]] = {f: [] for f in INPUT_FILES}
        for name in names:
            for f, rows in self._input_rows(name).items():
                new[f] += rows
        rank = {name: k for k, name in enumerate(order)}
        for f, cols in INPUT_FILES.items():
            df = pd.DataFrame(new[f], columns=cols)
            if changed is not None:
                # The new rows as text, as a full rebuild writes them, among the
                # kept rows (images still in the folder) in the order of the images.
                df = pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype=str, keep_default_na=False)
                kept = old[f][old[f]["image"].isin(rank) & ~old[f]["image"].isin(changed)]
                df = pd.concat([kept, df], ignore_index=True)
                df = df.sort_values("image", key=lambda s: s.map(rank), kind="stable")
            _atomic_csv(df, i / f)

    def run(self, progress=None, should_stop=None) -> pd.DataFrame:
        """Analyse every image of the input folder (see :func:`ta_morpho.export.run_batch`).
        Raises ValueError when the folder holds no image."""
        images = self.images()
        if not images:
            raise ValueError(f"no images found in {self.input_dir}: choose the image folder (Folders)")
        self.check_settings()
        self.save()
        self.cells_dir.mkdir(parents=True, exist_ok=True)
        self._materialize_inputs()
        cfg = self.config()
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        with _log_to(self.pipeline_dir / "batch.log", mode="w"):
            return run_batch(images, cfg, progress=progress, should_stop=should_stop)

    def check_settings(self) -> None:
        """ValueError listing the settings a run cannot use (see :func:`ta_morpho.gui.settings.problems`)."""
        bad = setting_problems(self.settings)
        if bad:
            raise ValueError("some settings cannot be used; change them in Settings:\n\n• " + "\n• ".join(bad))

    def rerun(self, images: list[str]) -> pd.DataFrame:
        """Analyse some images again with the settings of the last run (after
        a correction), so that all specimens stay comparable."""
        cfg = self.last_run_config()
        raw = Path(cfg["paths"]["raw_dir"])
        missing = [name for name in images if not (raw / name).is_file()]
        if missing:     # never replace a good result by a "cannot read the image" failure
            raise ValueError(f"image {missing[0]} not found in {raw}: choose the image folder "
                             "again (Folders) and retry")
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        self._materialize_inputs(changed=images)
        with _log_to(self.pipeline_dir / "batch.log", mode="a"):
            return rerun_images([raw / name for name in images], cfg)

    def has_corrections(self) -> bool:
        """True if any specimen has a hand correction (a cells/<stem>.csv or a
        hand-drawn mask) in this output folder."""
        return any(self._correction_files())

    def _correction_files(self) -> list[Path]:
        """Every correction file on disk (``cells/*.csv``, ``cells/*_mask.png``),
        also of images no longer in the input folder (renamed, moved)."""
        if not self.cells_dir.is_dir():
            return []
        return [f for f in self.cells_dir.iterdir()
                if f.suffix == ".csv" or f.name.endswith("_mask.png")]

    def reset_all(self, backup: bool = True) -> Path | None:
        """Erase every result *and* every hand correction in the output folder,
        for a clean automatic re-run from zero. Only the project settings and
        the input folder (``.pipeline/project.yaml``) are kept.

        A backup is made only when there are actual hand corrections to lose
        (not for regenerable results alone), so a second erase of an already
        clean folder cannot overwrite an earlier real backup with an empty one.
        Only the :data:`KEEP_BACKUPS` most recent backups are kept, in
        ``.pipeline/backups/<timestamp>/``, so they never pile up. Returns the
        backup path, or None when none was made."""
        made = None
        if backup and self.has_corrections():
            backups = self.pipeline_dir / "backups"
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            made, i = backups / stamp, 1
            while made.exists():                       # keep names unique and readable
                made, i = backups / f"{stamp}_{i}", i + 1
            made.mkdir(parents=True, exist_ok=True)
            (made / CELLS).mkdir()
            for f in self._correction_files():         # the corrections, not the figures
                shutil.copy2(f, made / CELLS / f.name)
            if (self.output_dir / "summary.csv").exists():
                shutil.copy2(self.output_dir / "summary.csv", made / "summary.csv")
            for old in sorted(d for d in backups.iterdir() if d.is_dir())[:-KEEP_BACKUPS]:
                _rmtree_quiet(old)                     # drop all but the newest few
        # Only what the program writes goes: summary.csv, the figures and corrections in cells/
        # (<stem>.png, <stem>.csv, <stem>_mask.png), the tables in exports/, and .pipeline/ except the
        # project file and the backups. Anything else (the images, the user's own files, also inside
        # cells/ or exports/) stays. A file that cannot be removed (open in another program) stops
        # the erase with a message, before the run: old corrections must not come back in it.
        if self.output_dir.is_dir():
            _remove(self.output_dir / "summary.csv")
            for folder, keep in ((self.cells_dir, lambda f: not f.name.endswith((".png", ".csv"))),
                                 (self.output_dir / EXPORTS, lambda f: f.name not in EXPORT_FILES)):
                if folder.is_dir():
                    for f in folder.iterdir():
                        if f.is_file() and not keep(f):
                            _remove(f)
                    if not any(folder.iterdir()):
                        folder.rmdir()
            if self.pipeline_dir.is_dir():
                for child in self.pipeline_dir.iterdir():
                    if child.name not in ("project.yaml", "backups"):
                        _remove(child)
        self.history.clear()
        return made

    def export(self) -> Path:
        """Write the derived tables (profiles, outline/GM, holes/bumps) into
        ``exports/`` from the cached records. Returns the exports folder."""
        return export_derived(self.output_dir, self.last_run_config())

    def exports_stale(self) -> bool:
        """True when corrections were made since ``exports/`` was written."""
        return exports_stale(self.output_dir)

    def refresh_exports(self) -> bool:
        """Bring ``exports/`` up to date after corrections (a correction only
        marks it out of date, to stay fast); True if it was rewritten. Done
        when the project is opened or closed and before its files are opened."""
        return self.exports_stale() and refresh_exports(self.output_dir, self.last_run_config())

    def refresh_summary(self) -> bool:
        """Rewrite summary.csv if a correction met it locked (see
        :class:`ta_morpho.export.SummaryStale`); True if rewritten. OutputLocked if still locked."""
        return refresh_summary(self.output_dir)

    def preload(self) -> None:
        """Read the results of every specimen into memory (see
        :func:`ta_morpho.export.load_summaries`) so that the first correction is
        as fast as the next ones. Safe in a background thread: a change made
        meanwhile is seen and read again."""
        load_summaries(self.output_dir)

    def summary(self) -> pd.DataFrame:
        """The results table: summary.csv, or, while it lags behind (it could not be
        rewritten after a correction), the same table built from the records."""
        if summary_stale(self.output_dir):
            df = pd.DataFrame([r["summary"] for r in load_summaries(self.output_dir)])
            return pd.read_csv(io.StringIO(df.to_csv(index=False)), keep_default_na=True)  # as read from disk
        f = self.output_dir / "summary.csv"
        return pd.read_csv(f, keep_default_na=True) if f.exists() else pd.DataFrame()

    def cell_figure(self, image: str) -> Path:
        return self.output_dir / CELLS / f"{Path(image).stem}.png"

    def image_path(self, image: str) -> Path:
        return Path(self.last_run_config()["paths"]["raw_dir"]) / image

    def overlay(self, image: str) -> dict:
        """Geometry of the last analysis of an image (outline, centroid,
        aperture corners, fundus, scale bar), for the correction tools."""
        f = self.output_dir / RECORDS / f"{image}.json"
        return json.loads(f.read_text(encoding="utf-8")).get("overlay", {}) if f.exists() else {}

    # ----- corrections --------------------------------------------------------
    # Each specimen's corrections live in one typed-row CSV, cells/<stem>.csv.
    def _corr(self, image: str) -> dict:
        """This specimen's corrections: {"landmarks": {...}, "scale": {...},
        "features": [...], "characters": {name: value}} plus "review" when set.
        Empty if none. Raises ValueError on a row it cannot read."""
        out: dict = {"landmarks": {}, "scale": {}, "features": [], "characters": {}}
        f = self.cell_csv(image)
        try:
            df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8")
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return out
        except UnicodeDecodeError:
            raise ValueError(f"cannot read the corrections in {f.name}: it is not saved as UTF-8 text "
                             "(e.g. saved by Excel as \"CSV\" instead of \"CSV UTF-8\"). Save it again "
                             "as CSV UTF-8, or undo the change") from None
        except pd.errors.ParserError as e:
            raise ValueError(f"cannot read the corrections in {f.name}: {e}") from None
        except OSError as e:
            raise ValueError(f"cannot read the corrections in {f.name} ({e.strerror or e}): close it "
                             "in any other program and try again") from None
        if "type" not in df.columns:
            raise ValueError(f"cannot read the corrections in {f.name}: no 'type' column "
                             "(saved with ';' separators, e.g. by Excel? Save it as a "
                             "comma-separated CSV, or undo the change)")

        def num(vals, keys, line):
            out = {}
            for k in keys:
                if k in vals:
                    try:
                        out[k] = float(vals[k])
                    except ValueError:
                        raise ValueError(
                            f"cannot read the corrections in {f.name}, line {line}: "
                            f"{k} = '{vals[k]}' is not a number (use a decimal point, "
                            "e.g. 12.5, not 12,5)") from None
            return out

        for line, row in enumerate(df.to_dict("records"), start=2):
            kind = row.get("type", "")
            vals = {k: v for k, v in row.items() if k != "type" and v != ""}
            if kind == "landmark":
                out["landmarks"] = num(vals, LANDMARK_COLUMNS, line)
            elif kind == "scale":
                out["scale"] = num(vals, SCALE_COLUMNS, line)
            elif kind == "feature":
                if vals.get("action") != "add" or vals.get("kind") not in KINDS:
                    raise ValueError(f"cannot read the corrections in {f.name}, line {line}: a hole/bump "
                                     "row needs action 'add' and kind 'hole' or 'bump'")
                feat = {k: vals[k] for k in FEATURE_STR if k in vals}
                feat.update(num(vals, FEATURE_NUM, line))
                out["features"].append(feat)
            elif kind == "review":
                out["review"] = vals.get("note", "")
            elif kind == "character":
                name = vals.get("name", "")
                if name not in CHARACTER_VALUES and name not in TAXON or not vals.get("value"):
                    raise ValueError(f"cannot read the corrections in {f.name}, line {line}: a character "
                                     "row needs a known name and a value")
                out["characters"][name] = vals["value"]
            else:
                raise ValueError(f"cannot read the corrections in {f.name}, line {line}: "
                                 f"unknown row type '{kind}'")
        return out

    def _write_corr(self, image: str, corr: dict) -> None:
        """Replace this specimen's correction file (removed when empty)."""
        rows: list[dict] = []
        if corr.get("landmarks"):
            rows.append({"type": "landmark", **corr["landmarks"]})
        if corr.get("scale"):
            rows.append({"type": "scale", **corr["scale"]})
        for feat in corr.get("features") or []:
            rows.append({"type": "feature", **feat})
        if corr.get("review") is not None:
            rows.append({"type": "review", "note": corr["review"]})
        for name, value in (corr.get("characters") or {}).items():
            rows.append({"type": "character", "name": name, "value": value})
        f = self.cell_csv(image)
        try:
            if not rows:
                f.unlink(missing_ok=True)
                return
            f.parent.mkdir(parents=True, exist_ok=True)
            _atomic_csv(pd.DataFrame(rows).reindex(columns=CORR_COLUMNS), f)
        except PermissionError as e:          # open in a program that locks it (Excel on Windows)
            raise ValueError(f"cannot save the corrections in {f.name} ({e.strerror or e}): close it in "
                             "any other program and try again; nothing was changed") from None

    def _feature_rows(self, image: str) -> list[dict]:
        return self._corr(image)["features"]

    def corrections(self, image: str) -> dict:
        """This image's current corrections: {"landmarks": {...}, "scale": {...},
        "features": [...], "characters": {...}}, plus "mask": True when the
        outline was edited by hand."""
        c = self._corr(image)
        out = {"landmarks": c["landmarks"], "scale": c["scale"], "features": c["features"],
               "characters": c["characters"]}
        if self.mask_path(image).exists():
            out["mask"] = True
        return out

    def accept(self, image: str, note: str = "") -> pd.DataFrame:
        """Accept a flagged specimen after a visual check and update the
        results; the automatic status and messages are kept. Can be undone."""
        return self._apply(image, lambda corr: corr.update(review=note))

    def unaccept(self, image: str) -> pd.DataFrame:
        """Withdraw the acceptance of a specimen. Can be undone."""
        return self._apply(image, lambda corr: corr.pop("review", None))

    def set_characters(self, image: str, values: dict[str, str]) -> pd.DataFrame:
        """Genus, species or characters set by hand ({name: value}; "" = back to
        the file name / the genus's value). Can be undone."""
        unknown = [k for k in values if k not in CHARACTER_VALUES and k not in TAXON]
        bad = [f"{k} = {v}" for k, v in values.items() if k in CHARACTER_VALUES and v
               and v not in CHARACTER_VALUES[k]]
        if unknown or bad:
            raise ValueError(f"unknown character or value: {', '.join(unknown + bad)}")

        def edit(corr):
            for k, v in values.items():
                v = str(v).strip()
                if v:
                    corr["characters"][k] = v
                else:
                    corr["characters"].pop(k, None)
        return self._apply(image, edit)

    # Every correction: written to cells/<stem>.csv (and the hand mask), kept
    # for Undo, and the image re-analysed at once. If the re-analysis is refused
    # or fails (image folder moved, results file open in another program), the
    # files are put back as they were: a correction is either fully made or not
    # at all, so that trying again never doubles it.
    def _snapshot(self, image: str) -> dict:
        f = self.mask_path(image)
        return {"corr": copy.deepcopy(self._corr(image)),
                "mask_png": f.read_bytes() if f.exists() else None}

    def _restore(self, image: str, snapshot: dict) -> None:
        """Put this image's correction files back as in ``snapshot``."""
        self._write_corr(image, snapshot["corr"])
        f = self.mask_path(image)
        if snapshot.get("mask_png") is None:
            f.unlink(missing_ok=True)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(snapshot["mask_png"])

    def _check_image(self, image: str) -> None:
        """ValueError if the image cannot be re-analysed (checked before any file is written)."""
        raw = Path(self.last_run_config()["paths"]["raw_dir"])
        if not (raw / image).is_file():
            raise ValueError(f"image {image} not found in {raw}: choose the image folder again "
                             "(Folders) and retry")

    def _apply(self, image: str, edit, mask: np.ndarray | None | bool = False) -> pd.DataFrame:
        """Change this image's corrections with ``edit(corr)`` (and ``mask``:
        array = new hand-corrected mask, None = remove it, False = unchanged),
        re-analyse, and keep the previous state for Undo. On failure the files
        are put back and nothing is added to the Undo history."""
        self._check_image(image)
        before = self._snapshot(image)
        corr = copy.deepcopy(before["corr"])
        edit(corr)
        try:
            self._write_corr(image, corr)
            if mask is None:
                self.mask_path(image).unlink(missing_ok=True)
            elif mask is not False:
                self.mask_path(image).parent.mkdir(parents=True, exist_ok=True)
                _atomic_png(mask, self.mask_path(image))
            df = self.rerun([image])
        except SummaryStale:            # made and recorded; only summary.csv lags (rebuilt later)
            self.history.setdefault(image, []).append(before)
            raise
        except BaseException:
            self._restore(image, before)
            raise
        self.history.setdefault(image, []).append(before)
        return df

    def _change(self, image: str, landmarks: dict | None = None, scale: dict | None = None,
                features: list[dict] | None = None, mask: np.ndarray | None | bool = False) -> pd.DataFrame:
        """Apply corrections (``None`` leaves a part unchanged, a value replaces
        it; ``mask``: array = new hand-corrected mask, None = remove it, False =
        unchanged), remember the previous state for Undo, and re-analyse."""
        def edit(corr):
            for key, value in (("landmarks", landmarks), ("scale", scale), ("features", features)):
                if value is not None:
                    corr[key] = value
        return self._apply(image, edit, mask)

    # Outline drawn by hand ------------------------------------------------------
    def current_mask(self, image: str) -> np.ndarray | None:
        """The mask used in the last analysis (hand-corrected or automatic);
        None when there is none (e.g. the analysis failed)."""
        for f in (self.mask_path(image), self.output_dir / RECORDS / f"{image}.mask.png"):
            if f.exists():
                m = read_image(f, cv2.IMREAD_GRAYSCALE)
                if m is not None:
                    return m > 127
        return None

    def set_mask(self, image: str, mask: np.ndarray) -> pd.DataFrame:
        """Save an outline corrected by hand (True = test) and re-analyse. The
        mask is cleaned as the automatic one: largest object only, holes
        filled. ValueError if nothing is left."""
        m = np.asarray(mask, bool)
        if not m.any():
            raise ValueError("the outline is empty: paint the test with the brush")
        lab = measure.label(m)
        m = ndi.binary_fill_holes(lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1)
        return self._change(image, mask=m)

    def set_aperture(self, image: str, corner1, corner2) -> pd.DataFrame:
        """The two aperture corners clicked by the user (any order)."""
        if np.hypot(corner1[0] - corner2[0], corner1[1] - corner2[1]) < 3:
            raise ValueError("the two aperture corners are at the same place")
        lm = {k: v for k, v in self._corr(image)["landmarks"].items() if k.startswith("fundus")}
        lm.update(x=float(corner1[0]), y=float(corner1[1]), end_x=float(corner2[0]), end_y=float(corner2[1]))
        return self._change(image, landmarks=lm)

    def set_fundus(self, image: str, point) -> pd.DataFrame:
        lm = dict(self._corr(image)["landmarks"])
        lm.update(fundus_x=float(point[0]), fundus_y=float(point[1]))
        return self._change(image, landmarks=lm)

    def set_scale(self, image: str, p0, p1, length_um: float) -> pd.DataFrame:
        """Scale from a line drawn along the scale bar and its length in µm."""
        length_px = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        if length_px <= 0 or length_um <= 0:
            raise ValueError("the scale bar line and its length must be longer than 0")
        return self._change(image, scale=dict(
            px_per_um=length_px / length_um, bar_length_um=float(length_um),
            bar_x0=float(p0[0]), bar_y0=float(p0[1]), bar_x1=float(p1[0]), bar_y1=float(p1[1])))

    # Holes and bumps, added by hand. Each one is stored with its image
    # coordinates (see ta_morpho.features.manual_features).
    def _feature(self, image: str, x, y):
        """The hole/bump nearest to (x, y), in the last analysis."""
        feats = self.overlay(image).get("features") or []
        if not feats:
            raise ValueError("this image has no hole or bump added by hand")
        return min(feats, key=lambda f: np.hypot(f["x"] - x, f["y"] - y))

    @staticmethod
    def _nearest_row(rows: list[dict], f: dict) -> dict:
        same = [r for r in rows if r["kind"] == f["kind"]]
        return min(same, key=lambda r: np.hypot(float(r["x"]) - f["x"], float(r["y"]) - f["y"]))

    def remove_feature(self, image: str, x, y) -> pd.DataFrame:
        """Remove the hole/bump nearest to (x, y)."""
        f = self._feature(image, x, y)
        rows = self._feature_rows(image)
        drop = self._nearest_row(rows, f)
        return self._change(image, features=[r for r in rows if r is not drop])

    def _check_added(self, image: str, rows: list[dict], kind: str) -> None:
        """After a change adding a hole/bump: if it could not be measured,
        undo the change and raise ValueError."""
        measured = [f for f in self.overlay(image).get("features") or [] if f["kind"] == kind]
        wanted = sum(r["kind"] == kind for r in rows)
        if len(measured) < wanted:
            self.undo(image)
            way = "inward (into the shell)" if kind == "hole" else "outward"
            raise ValueError(f"no {kind} can be measured there: inside the circle, the outline does "
                             f"not go {way} beyond the line joining the two ends of the circle. "
                             f"Try another place or a smaller circle")

    def default_radius(self, image: str) -> float:
        """Circle radius (px) for a new hole/bump: the curvature scale
        (features.turn_um), i.e. 5 µm by default."""
        ov = self.overlay(image)
        return float(self.settings["features"]["turn_um"]) * float(ov.get("px_per_um") or 1.0)

    def add_feature(self, image: str, kind: str, x, y, note: str = "",
                    radius_px: float | None = None) -> pd.DataFrame:
        """Add a hole or bump by hand: centre (x, y) on the outline and a circle of ``radius_px`` (default
        :meth:`default_radius`) delimiting it; measured on the outline inside
        the circle. If it cannot be measured there (wrong kind for the place),
        the change is undone and ValueError raised."""
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        r = float(radius_px) if radius_px else self.default_radius(image)
        rows = self._feature_rows(image) + [{"action": "add", "kind": kind, "x": float(x), "y": float(y),
                                             "radius_px": r, "note": note or "added by the user"}]
        df = self._change(image, features=rows)
        self._check_added(image, rows, kind)
        return df

    def edit_feature(self, image: str, feature: dict, center, radius_px: float) -> pd.DataFrame:
        """Move a hole/bump (centre on the outline) and/or change its circle."""
        rows = self._feature_rows(image)
        kind = feature["kind"]
        old = self._nearest_row(rows, feature)
        note = old.get("note") or "added by the user"
        rows = [r for r in rows if r is not old]
        rows.append({"action": "add", "kind": kind, "x": float(center[0]), "y": float(center[1]),
                     "radius_px": float(radius_px), "note": note})
        df = self._change(image, features=rows)
        self._check_added(image, rows, kind)
        return df

    def reset_corrections(self, image: str) -> pd.DataFrame:
        """Back to automatic: remove every correction drawn on this image
        (outline, aperture, fundus, scale, holes and bumps). A manual QC
        acceptance and the genus, species and characters set by hand, if any,
        are kept (Characters tab: "Back to the genus values")."""
        return self._change(image, landmarks={}, scale={}, features=[], mask=None)

    def can_undo(self, image: str) -> bool:
        return bool(self.history.get(image))

    def undo(self, image: str) -> pd.DataFrame:
        """Restore this image's corrections as they were before the last change
        (a drawing or an acceptance). If the re-analysis fails, nothing changes
        and the step stays in the Undo history."""
        self._check_image(image)
        now = self._snapshot(image)
        try:
            self._restore(image, self.history[image][-1])
            df = self.rerun([image])
        except SummaryStale:
            self.history[image].pop()
            raise
        except BaseException:
            self._restore(image, now)
            raise
        self.history[image].pop()
        return df


def _rmtree_quiet(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _remove(path: Path) -> None:
    """Delete a file or folder; ValueError with a plain message if it cannot be."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError as e:
        raise ValueError(f"could not remove {path.name} ({e.strerror or e}): close it in any other program "
                         "and try again. The erase stopped there and nothing was analysed (your "
                         "corrections were backed up first, in .pipeline/backups).") from None


def _atomic_csv(df: pd.DataFrame, path: Path) -> None:
    """Write a CSV so that a reader never sees a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    df.to_csv(tmp, index=False)
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)         # no half-way file left behind
        raise


def _atomic_png(mask: np.ndarray, path: Path) -> None:
    """Write a mask (255 = test) so that a reader never sees a half-written file."""
    tmp = path.with_name(path.name + ".tmp.png")
    write_image(tmp, np.asarray(mask, np.uint8) * 255)
    os.replace(tmp, path)


def _read_project_file(f: Path) -> dict:
    """The saved project (``.pipeline/project.yaml``). A file that cannot be read
    is refused with a ValueError naming it, never replaced by the default
    settings (the user's settings would be lost at the next save)."""
    try:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("settings") or {}, dict):
        raise ValueError(f"cannot read the project file {f}: it is damaged (e.g. the computer stopped "
                         "while it was saved). Your results and corrections are not affected. Repair it "
                         "in a text editor or put back a copy, then open the folder again (the settings "
                         "of the last run are in .pipeline/config_used.yaml).")
    return d


def _merge(base: dict, new: dict) -> None:
    """Recursively copy the values of ``new`` into ``base``; keys that ``base``
    does not have are ignored."""
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        elif k in base:
            base[k] = v


class _log_to:
    """Context manager: also send the pipeline log to a file."""

    def __init__(self, path: Path, mode: str):
        self.handler = logging.FileHandler(path, mode=mode, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    def __enter__(self):
        root = logging.getLogger()
        self.level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(self.handler)

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self.handler)
        root.setLevel(self.level)
        self.handler.close()
