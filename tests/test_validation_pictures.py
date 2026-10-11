"""Golden test: the validation pictures (data/validation/images/Replicate_1) give the recorded results.

The pictures are analysed with the default settings (each scale comes from the
bar in the picture and its length in the file name), exactly as a user would
run them, and the main results are compared
with tests/data/expected_validation.csv: the status, the aperture corners and
fundus (pixels), how they were found, the classic measurements (µm and ratios),
the shape descriptors and four rays of the radial profile. A difference
means the program now measures these pictures differently. If the change is
intended, record the new values with

    python -m tests.test_validation_pictures --update

which lists the pictures and columns that changed and keeps that run in
``validation_update/`` (current folder): check its cell figures
(``validation_update/cells/``) before committing the new values.
"""

import shutil
import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from ta_morpho.export import DEFAULT_CONFIG, run_batch
from ta_morpho.image_io import list_images

ROOT = Path(__file__).resolve().parents[1]
PICTURES = ROOT / "data" / "validation" / "images" / "Replicate_1"    # the pictures as published
EXPECTED = Path(__file__).resolve().parent / "data" / "expected_validation.csv"
POINTS = ["landmark_x", "landmark_y", "aperture_end_x", "aperture_end_y", "fundus_x", "fundus_y"]
KINDS = ["landmark_source", "axis", "background"]          # how the points and the outline were found
SIZES = ["px_per_um", "length_um", "width_um", "aperture_width_um", "neck_length_um", "neck_width_um",
         "area_um2", "perimeter_um", "feret_max_um", "mean_radius_um", "r0", "r90", "r180", "r270"]
RATIOS = ["W/L", "AW/L", "circularity", "solidity", "neck_jump", "radius_cv", "symmetry_index",
          "h1", "h2", "h3", "h4", "h5"]
ANGLES = ["aperture_angle_deg"]
COLUMNS = ["image", "status", *KINDS, *POINTS, *SIZES, *RATIOS, *ANGLES]


def analyse(out: Path) -> pd.DataFrame:
    """Run the validation pictures (default settings) into ``out``."""
    config = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for key in config["paths"]:
        if key.endswith("_csv"):
            config["paths"][key] = None
    config["paths"]["results_dir"] = str(out)
    config["calibration"]["overrides_csv"] = None       # every scale comes from the picture and its name
    config["segmentation"].update(masks_dir=str(out / "masks"), background_overrides_csv=None)
    df = run_batch(list_images([], PICTURES), config)
    return df[COLUMNS].set_index("image").sort_index()


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return analyse(tmp_path_factory.mktemp("validation"))


@pytest.fixture(scope="module")
def expected():
    return pd.read_csv(EXPECTED).set_index("image").sort_index()


def test_same_pictures(results, expected):
    assert list(results.index) == list(expected.index)


def test_status(results, expected):
    assert results["status"].to_dict() == expected["status"].to_dict()


@pytest.mark.parametrize("column", KINDS)
def test_how_points_and_outline_were_found(results, expected, column):
    assert results[column].fillna("").to_dict() == expected[column].fillna("").to_dict()


@pytest.mark.parametrize("column", POINTS)
def test_aperture_and_fundus_positions(results, expected, column):
    """Within 1 pixel of the recorded point."""
    np.testing.assert_allclose(results[column], expected[column], atol=1.0, equal_nan=True, err_msg=column)


@pytest.mark.parametrize("column", SIZES)
def test_sizes(results, expected, column):
    """Within 0.5 % (empty for the drawings, which have no scale)."""
    np.testing.assert_allclose(results[column], expected[column], rtol=0.005, equal_nan=True, err_msg=column)


@pytest.mark.parametrize("column", RATIOS)
def test_ratios(results, expected, column):
    """Ratios and shape descriptors (no unit): within 0.005."""
    np.testing.assert_allclose(results[column], expected[column], atol=0.005, equal_nan=True, err_msg=column)


@pytest.mark.parametrize("column", ANGLES)
def test_angles(results, expected, column):
    np.testing.assert_allclose(results[column], expected[column], atol=0.5, equal_nan=True, err_msg=column)


def changes(old: pd.DataFrame, new: pd.DataFrame) -> list[str]:
    """Lines describing what differs between two recorded tables (as read back from CSV)."""
    lines = [f"  new picture: {i}" for i in new.index.difference(old.index)]
    lines += [f"  picture gone: {i}" for i in old.index.difference(new.index)]
    lines += [f"  new column: {c}" for c in new.columns.difference(old.columns)]
    lines += [f"  column gone: {c}" for c in old.columns.difference(new.columns)]
    columns = [c for c in new.columns if c in old.columns]
    for image in new.index.intersection(old.index):
        diff = [f"{c} {old.at[image, c]} -> {new.at[image, c]}" for c in columns
                if not (pd.isna(old.at[image, c]) and pd.isna(new.at[image, c]))
                and old.at[image, c] != new.at[image, c]]
        if diff:
            lines.append(f"  {image}: " + "; ".join(diff))
    return lines


def update(out: Path) -> None:
    """Analyse the pictures into ``out`` (kept, for checking the cell figures), record the
    results in EXPECTED and print what changed."""
    if out.exists() and any(out.iterdir()) and not (out / "summary.csv").exists():
        sys.exit(f"{out} exists and is not a previous validation run: move it away first")
    shutil.rmtree(out, ignore_errors=True)        # a fresh run: no hand correction from a previous one
    text = analyse(out).round(4).to_csv(lineterminator="\n")      # same file on every system
    new = pd.read_csv(StringIO(text)).set_index("image")
    old = pd.read_csv(EXPECTED).set_index("image") if EXPECTED.exists() else None
    EXPECTED.parent.mkdir(exist_ok=True)
    EXPECTED.write_text(text, encoding="utf-8", newline="")
    print(f"{len(new)} pictures recorded in {EXPECTED}: {new['status'].value_counts().to_dict()}")
    if old is None:
        print("no previous file to compare with")
    else:
        lines = changes(old, new)
        print("\n".join(["changes from the previous file:", *lines]) if lines
              else "no change from the previous file")
    print(f"check the cell figures in {(out / 'cells').resolve()} before committing")


if __name__ == "__main__":
    if "--update" not in sys.argv:
        sys.exit("usage: python -m tests.test_validation_pictures --update   (records the current results)")
    update(Path("validation_update"))
