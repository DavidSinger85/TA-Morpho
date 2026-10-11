"""The results folder stays consistent when things go wrong: a picture that
cannot be read, a run stopped or cut short, two pictures with the same name,
every picture failing, and "Erase and run again" with its backups."""

import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest
import yaml

from ta_morpho.export import COMPLETE, DEFAULT_CONFIG, STAGE, main, recover, run_batch
from ta_morpho.image_io import list_images, write_image


def oval(path: Path) -> None:
    img = np.full((400, 400, 3), 245, np.uint8)
    cv2.ellipse(img, (200, 190), (80, 120), 0, 0, 360, (150, 160, 170), -1)
    img[370:378, 20:220] = 0                                     # 200 px bar
    write_image(path, img)


def config(tmp: Path, step: int = 30) -> dict:
    c = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for key in c["paths"]:
        if key.endswith("_csv"):
            c["paths"][key] = None
    c["paths"]["results_dir"] = str(tmp / "results")
    c["calibration"]["overrides_csv"] = None
    c["segmentation"].update(masks_dir=str(tmp / "masks"), background_overrides_csv=None)
    c["rays"]["angle_step_deg"] = step
    return c


@pytest.fixture
def raw(tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    for name in ("Testus_ovalis_25um_01.png", "Testus_ovalis_25um_02.png"):
        oval(folder / name)
    return folder


def test_a_picture_that_cannot_be_read_fails_alone(raw, tmp_path):
    (raw / "broken.png").write_bytes(b"not a picture")
    df = run_batch(list_images([], raw), config(tmp_path)).set_index("image")
    assert df.loc["broken.png", "status"] == "failed" and "Cannot read image" in df.loc["broken.png", "messages"]
    assert (df.drop("broken.png")["status"] != "failed").all()


def test_a_stopped_run_keeps_the_previous_results(raw, tmp_path):
    run_batch(list_images([], raw), config(tmp_path))
    first = (tmp_path / "results" / "summary.csv").read_bytes()
    stopped = run_batch(list_images([], raw), config(tmp_path, step=45), should_stop=lambda: True)
    assert stopped.attrs.get("cancelled")
    assert (tmp_path / "results" / "summary.csv").read_bytes() == first
    assert not (tmp_path / "results" / STAGE).exists()


def test_a_run_cut_short_is_finished_or_dropped(raw, tmp_path):
    """A crash during a run leaves a staged run: if it was complete it is saved when
    the folder is used again; if not, it is dropped and the previous results stay."""
    results = tmp_path / "results"
    run_batch(list_images([], raw), config(tmp_path))
    first = (results / "summary.csv").read_bytes()
    (results / STAGE).mkdir(parents=True)                       # a run that crashed half-way
    (results / STAGE / "summary.csv").write_text("image,status\nhalf.png,ok\n")
    recover(results)
    assert not (results / STAGE).exists()
    assert (results / "summary.csv").read_bytes() == first
    # a complete run whose saving was cut short: saved by recover()
    staged = results / STAGE
    run_batch(list_images([], raw), {**config(tmp_path), "paths": {**config(tmp_path)["paths"],
                                                                   "results_dir": str(staged)}})
    (staged / COMPLETE).write_text(json.dumps({"remove": [], "save_masks": False}))
    (staged / "summary.csv").write_text("image,status\nfrom_the_staged_run.png,ok\n")
    recover(results)
    assert pd.read_csv(results / "summary.csv")["image"].tolist() == ["from_the_staged_run.png"]


def test_two_pictures_with_the_same_name_are_refused(raw, tmp_path):
    oval(raw / "Testus_ovalis_25um_01.tif")                     # same name as the .png
    df = run_batch(list_images([], raw), config(tmp_path)).set_index("image")
    for name in ("Testus_ovalis_25um_01.png", "Testus_ovalis_25um_01.tif"):
        assert df.loc[name, "status"] == "failed" and "duplicate name" in df.loc[name, "messages"]
    assert df.loc["Testus_ovalis_25um_02.png", "status"] != "failed"


def test_command_line_exit_codes(raw, tmp_path):
    """0 when pictures were analysed, 1 when every picture failed, 2 when nothing could run."""
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config(tmp_path)), encoding="utf-8")
    cfg = ["--config", str(tmp_path / "config.yaml")]
    assert main([str(raw), "-o", str(tmp_path / "a"), *cfg]) == 0
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.png").write_bytes(b"not a picture")
    assert main([str(bad), "-o", str(tmp_path / "b"), *cfg]) == 1
    assert main([str(tmp_path / "missing"), "-o", str(tmp_path / "c"), *cfg]) == 2


def test_erase_keeps_a_backup_of_the_corrections(raw, tmp_path):
    from ta_morpho.gui.project import KEEP_BACKUPS, Project
    p = Project(tmp_path / "out", raw)
    p.settings["rays"]["angle_step_deg"] = 30
    p.run()
    for i in range(KEEP_BACKUPS + 1):
        p.accept("Testus_ovalis_25um_01.png", f"checked {i}")
        made = p.reset_all()
        assert (made / "cells" / "Testus_ovalis_25um_01.csv").exists()
    backups = sorted((tmp_path / "out" / ".pipeline" / "backups").iterdir())
    assert len(backups) == KEEP_BACKUPS                          # only the newest few are kept
    assert "checked" in (backups[-1] / "cells" / "Testus_ovalis_25um_01.csv").read_text()
    assert not p.cell_csv("Testus_ovalis_25um_01.png").exists() and p.reset_all() is None   # nothing to back up
