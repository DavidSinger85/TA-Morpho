"""Tests on drawn shapes whose true sizes in µm are known.

Each image is drawn at a chosen resolution (px/µm) with a 25 µm scale bar
named in the file name, then run through the command line exactly as a user
would (``ta-morpho <folder> -o <results>``). The values in summary.csv are
compared with the geometry of the drawing, not with earlier outputs: scale
bar, outline, aperture, rays and classic measurements.
"""

from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest
import yaml

from ta_morpho.export import DEFAULT_CONFIG, angle_column, main
from ta_morpho.image_io import write_image

FILL = (150, 160, 170)
BG = 245
BAR_UM = 25


def blank(ppu: float, w_um: float = 300, h_um: float = 225, bar: bool = True) -> np.ndarray:
    """Light background with a dark 25 µm scale bar in the lower left corner."""
    s = lambda v: int(round(v * ppu))  # noqa: E731
    img = np.full((s(h_um), s(w_um), 3), BG, np.uint8)
    if bar:
        img[s(h_um - 15):s(h_um - 15) + max(3, s(0.75)), s(15):s(15) + s(BAR_UM)] = 0
    return img


def disc(ppu: float, r_um: float = 60, bar: bool = True) -> np.ndarray:
    img = blank(ppu, bar=bar)
    cv2.circle(img, (img.shape[1] // 2, img.shape[0] // 2 - 5), int(round(r_um * ppu)), FILL, -1, cv2.LINE_AA)
    return img


def ellipse(ppu: float, a_um: float = 80, b_um: float = 45) -> np.ndarray:
    img = blank(ppu)
    cv2.ellipse(img, (img.shape[1] // 2, img.shape[0] // 2 - 5),
                (int(round(a_um * ppu)), int(round(b_um * ppu))), 0, 0, 360, FILL, -1, cv2.LINE_AA)
    return img


def flask(ppu: float, bar: bool = True) -> np.ndarray:
    """Round body (r = 50 µm) with a neck pointing left: 30 µm long beyond the
    body, 20 µm wide at the open aperture, widening to 30 µm into the body.
    Length 130 µm along the oral axis, width 100 µm."""
    s = lambda v: int(round(v * ppu))  # noqa: E731
    img = blank(ppu, bar=bar)
    cx, cy, r = s(175), s(105), s(50)
    cv2.circle(img, (cx, cy), r, FILL, -1, cv2.LINE_AA)
    x0 = cx - r - s(30)
    pts = np.array([[x0, cy - s(10)], [cx - s(40), cy - s(15)], [cx, cy - s(15)],
                    [cx, cy + s(15)], [cx - s(40), cy + s(15)], [x0, cy + s(10)]])
    cv2.fillPoly(img, [pts], FILL, cv2.LINE_AA)
    return img


def ramanujan(a: float, b: float) -> float:
    """Perimeter of an ellipse of semi-axes a and b."""
    h = ((a - b) / (a + b)) ** 2
    return np.pi * (a + b) * (1 + 3 * h / (10 + np.sqrt(4 - 3 * h)))


def run(tmp: Path, images: dict[str, np.ndarray], export: bool = False, features: str | None = None,
        **calibration) -> pd.DataFrame:
    """Write the images and a settings file (no correction tables, apart from
    ``features``: the text of a holes/bumps table), run the command line (with
    ``--export``: the extra tables too) and return summary.csv indexed by image."""
    raw = tmp / "raw"
    raw.mkdir()
    for name, img in images.items():
        write_image(raw / name, img)
    config = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for key in config["paths"]:
        if key.endswith("_csv"):
            config["paths"][key] = None
    if features is not None:
        (tmp / "features.csv").write_text(features, encoding="utf-8")
        config["paths"]["feature_corrections_csv"] = str(tmp / "features.csv")
    config["calibration"].update(overrides_csv=None, **calibration)
    config["segmentation"].update(masks_dir=str(tmp / "masks"), background_overrides_csv=None)
    (tmp / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    args = [str(raw), "-o", str(tmp / "results"), "--config", str(tmp / "config.yaml")]
    assert main(args + ["--export"] * export) == 0
    return pd.read_csv(tmp / "results" / "summary.csv").set_index("image")


def radii(row: pd.Series) -> np.ndarray:
    return np.array([row[angle_column(a)] for a in range(0, 360, 5)], float)


@pytest.fixture(scope="module")
def summary(tmp_path_factory):
    return run(tmp_path_factory.mktemp("shapes"), {
        "Testus_discus_25um_01.png": disc(4.0),
        "Testus_ellipticus_25um_01.png": ellipse(4.0),
        "Testus_lagena_25um_01.png": flask(4.0),
        "Testus_lagena_25um_02.png": flask(8.0),
    })


def test_scale_bar_read_from_the_drawing(summary):
    assert (summary["bar_length_um"] == BAR_UM).all()
    assert (summary["bar_length_source"] == "file name").all()
    assert summary.loc["Testus_discus_25um_01.png", "px_per_um"] == pytest.approx(4.0, rel=0.01)
    assert summary.loc["Testus_lagena_25um_02.png", "px_per_um"] == pytest.approx(8.0, rel=0.01)


def test_disc(summary):
    row = summary.loc["Testus_discus_25um_01.png"]
    r = 60
    assert np.allclose(radii(row), r, atol=0.5)                    # every ray
    assert row["length_um"] == pytest.approx(2 * r, abs=1)
    assert row["width_um"] == pytest.approx(2 * r, abs=1)
    assert row["area_um2"] == pytest.approx(np.pi * r ** 2, rel=0.01)
    assert row["perimeter_um"] == pytest.approx(2 * np.pi * r, rel=0.015)
    assert row["circularity"] > 0.98 and row["radius_cv"] < 0.01
    assert row["axis"] == "principal"                              # no aperture on a disc
    assert row["landmark_source"] == "fallback_max_radius"


def test_ellipse(summary):
    row = summary.loc["Testus_ellipticus_25um_01.png"]
    a, b = 80, 45
    assert row["length_um"] == pytest.approx(2 * a, abs=1)
    assert row["width_um"] == pytest.approx(2 * b, abs=1)
    assert row["area_um2"] == pytest.approx(np.pi * a * b, rel=0.01)
    assert row["perimeter_um"] == pytest.approx(ramanujan(a, b), rel=0.015)
    r = radii(row)
    assert r.max() == pytest.approx(a, abs=0.5) and r.min() == pytest.approx(b, abs=0.5)
    # Ray 0 starts at the furthest point (an end of the major axis); 90° later
    # (clockwise) the ray meets the minor axis.
    assert r[0] == pytest.approx(a, abs=0.5) and r[90 // 5] == pytest.approx(b, abs=0.5)


@pytest.mark.parametrize("image", ["Testus_lagena_25um_01.png", "Testus_lagena_25um_02.png"])
def test_flask(summary, image):
    row = summary.loc[image]
    assert row["status"] == "ok", row["messages"]
    assert row["axis"] == "oral" and row["landmark_source"] == "aperture"
    assert row["length_um"] == pytest.approx(130, abs=1.5)
    assert row["width_um"] == pytest.approx(100, abs=1.5)
    assert row["aperture_width_um"] == pytest.approx(20, abs=1.5)
    assert row["neck_length_um"] == pytest.approx(30, abs=2.5)
    assert 19 < row["neck_width_um"] < 24                         # narrow part of the neck
    # Clockwise rule: with the aperture pointing left, the start is the lower corner.
    assert row["landmark_y"] > row["centroid_y"] and row["aperture_end_y"] < row["centroid_y"]
    assert row["landmark_x"] < row["centroid_x"] - 70 * row["px_per_um"]


def test_flask_values_do_not_depend_on_resolution(summary):
    lo, hi = summary.loc["Testus_lagena_25um_01.png"], summary.loc["Testus_lagena_25um_02.png"]
    for key in ("length_um", "width_um", "area_um2", "perimeter_um", "mean_radius_um"):
        assert hi[key] == pytest.approx(lo[key], rel=0.02), key
    assert np.allclose(radii(hi), radii(lo), atol=1.0)


def test_hole_of_known_depth(tmp_path):
    """A semicircular bite of radius 6 µm in the top of the flask's body (r = 50 µm),
    marked as a hole: its depth below the line joining its rims is the bite radius
    less the bulge of the body between the rims, 6 - (50 - √(50² - 6²)) ≈ 5.6 µm."""
    ppu = 4.0
    img = flask(ppu)
    cx, cy, r = int(round(175 * ppu)), int(round(105 * ppu)), int(round(50 * ppu))
    cv2.circle(img, (cx, cy - r), int(round(6 * ppu)), (BG, BG, BG), -1, cv2.LINE_AA)
    table = f"image,action,kind,x,y,radius_px\nTestus_lagena_25um_01.png,add,hole,{cx},{cy - r},{12 * ppu}\n"
    row = run(tmp_path, {"Testus_lagena_25um_01.png": img}, features=table).iloc[0]
    assert row["n_holes"] == 1 and row["n_bumps"] == 0 and row["f1_kind"] == "hole"
    assert row["f1_size_um"] == pytest.approx(6 - (50 - np.sqrt(50 ** 2 - 6 ** 2)), abs=0.6)
    assert row["f1_region"] == "body"


def test_without_scale_bar_um_values_stay_empty(tmp_path):
    df = run(tmp_path, {"Testus_discus_01.png": disc(4.0, bar=False)})
    row = df.iloc[0]
    assert row["status"] == "check"
    assert np.isnan(row["px_per_um"]) and np.isnan(row["area_um2"]) and np.isnan(radii(row)).all()
    assert "calibration" in row["messages"]


def test_px_per_um_given_in_settings(tmp_path):
    # No bar drawn; the resolution is given in the settings instead.
    df = run(tmp_path, {"Testus_discus_01.png": disc(4.0, bar=False)}, px_per_um=4.0)
    row = df.iloc[0]
    assert row["px_per_um"] == 4.0
    assert np.allclose(radii(row), 60, atol=0.5)


def test_accented_folder_and_file_names(tmp_path):
    # Windows: OpenCV cannot open such paths itself (see ta_morpho/image_io.py).
    folder = tmp_path / "Données_été"
    folder.mkdir()
    df = run(folder, {"Nebela_collaris_25um_échantillon_01.png": flask(4.0)}, export=True)
    row = df.loc["Nebela_collaris_25um_échantillon_01.png"]
    assert row["status"] == "ok" and row["length_um"] == pytest.approx(130, abs=1.5)
    assert (folder / "results" / "cells" / "Nebela_collaris_25um_échantillon_01.png").exists()
    assert (folder / "results" / "exports" / "outline_coordinates.tps").exists()


def test_settings_file_with_only_some_settings(tmp_path):
    """A settings file needs only the settings it changes: the others are the
    built-in ones (the rays here are every 30°)."""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_image(raw / "Testus_lagena_25um_01.png", flask(4.0))
    (tmp_path / "mine.yaml").write_text("rays:\n  angle_step_deg: 30\n", encoding="utf-8")
    assert main([str(raw), "-o", str(tmp_path / "results"), "--config", str(tmp_path / "mine.yaml")]) == 0
    row = pd.read_csv(tmp_path / "results" / "summary.csv").iloc[0]
    assert row["status"] == "ok" and row["length_um"] == pytest.approx(130, abs=1.5)
    assert angle_column(30) in row.index and angle_column(5) not in row.index
    (tmp_path / "flat.yaml").write_text("rays: 30\n", encoding="utf-8")
    assert main([str(raw), "-o", str(tmp_path / "r2"), "--config", str(tmp_path / "flat.yaml")]) == 2


def test_ratios_without_calibration(tmp_path):
    """No scale bar: the µm values stay empty, but the aperture, the neck and
    the ratios are still measured."""
    df = run(tmp_path, {"Testus_lagena_01.png": flask(4.0, bar=False)})
    row = df.iloc[0]
    assert np.isnan(row["length_um"]) and row["axis"] == "oral"
    assert row["W/L"] == pytest.approx(100 / 130, abs=0.02)
    assert row["NL/L"] == pytest.approx(30 / 130, abs=0.03)
