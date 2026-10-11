"""TA-Morpho on the three replicates of the validation pictures -> data/app_results.csv.

Runs the app with its default settings (the package's config.yaml) and no hand correction, no
correction table and no calibration table: every scale comes from the picture and its file name,
as in the golden test (tests/test_validation_pictures.py). The full results of each replicate are
written to a temporary folder; data/app_results.csv keeps one row per replicate and picture with the
columns the analysis uses, and results/manuscript/Figure_1_app_output.png is the app's figure of one
specimen (EXAMPLE, replicate 1).

    python data/validation/scripts/2_run_app.py      (from the repository, with ta_morpho installed)
"""
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import yaml

from ta_morpho.export import DEFAULT_CONFIG, run_batch
from ta_morpho.image_io import list_images

VALIDATION = Path(__file__).resolve().parents[1]
EXAMPLE = "Padaungiella_lageniformis_TB161E_20um.png"     # CC BY 4.0 (SOURCES.md)
FIGURE = VALIDATION / "results" / "manuscript" / "Figure_1_app_output.png"
COLUMNS = ["image", "specimen_id", "software_version", "status", "messages", "bar_length_um", "px_per_um",
           "length_um", "width_um", "aperture_width_um", "W/L", "AW/L"]


def run(folder: Path, out: Path):
    config = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for key in config["paths"]:
        if key.endswith("_csv"):
            config["paths"][key] = None
    config["paths"]["results_dir"] = str(out)
    config["calibration"]["overrides_csv"] = None
    config["segmentation"].update(masks_dir=str(out / "masks"), background_overrides_csv=None)
    return run_batch(list_images([], folder), config)


def main() -> None:
    tables = []
    with tempfile.TemporaryDirectory() as tmp:
        for folder in sorted((VALIDATION / "images").glob("Replicate_*")):
            k = int(folder.name.split("_")[1])
            df = run(folder, Path(tmp) / folder.name)[COLUMNS]
            df.insert(0, "replicate", k)
            tables.append(df)
            if k == 1:
                FIGURE.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(tmp) / folder.name / "cells" / EXAMPLE, FIGURE)
    out = pd.concat(tables, ignore_index=True)
    target = VALIDATION / "data" / "app_results.csv"
    out.to_csv(target, index=False, float_format="%.6g")
    print(f"{len(out)} rows written to {target}; figure {FIGURE}")


if __name__ == "__main__":
    main()
