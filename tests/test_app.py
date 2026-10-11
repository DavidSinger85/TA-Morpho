"""The desktop app, offscreen (no display needed): the installers' self-test,
a project with every kind of correction and its Undo, and the window going
through a whole project. Skipped when Qt cannot be loaded, except when
TA_MORPHO_REQUIRE_QT is set (as in the automatic checks): then it fails."""

import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

if os.environ.get("TA_MORPHO_REQUIRE_QT"):
    import PySide6.QtWidgets  # noqa: F401  (an error, not a skip: the window must be tested)
else:
    pytest.importorskip("PySide6.QtWidgets", reason="Qt cannot load (missing system libraries)",
                        exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ta_morpho.gui import launcher  # noqa: E402
from ta_morpho.gui.app import MainWindow  # noqa: E402
from ta_morpho.gui.project import Project  # noqa: E402

PICTURES = Path(__file__).resolve().parents[1] / "data" / "validation" / "images" / "Replicate_1"
APODERA = "Apodera_vas_P00205_100um.png"                # bar of 100 µm
PADAUNGIELLA = "Padaungiella_lageniformis_TB161E_20um.png"   # bar of 20 µm


def wait(condition, timeout_s=120):
    loop_ms, waited = 100, 0
    while not condition() and waited < timeout_s * 1000:
        loop = QEventLoop()
        QTimer.singleShot(loop_ms, loop.quit)
        loop.exec()
        waited += loop_ms
    assert condition()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """Offscreen, a real dialog would wait forever: record them instead, and
    fail the test if an error or a warning was shown. A test that expects a
    warning patches QMessageBox.warning itself."""
    errors, warnings = [], []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    yield
    assert not errors, "error dialog shown:\n" + "\n".join(errors)
    assert not warnings, "unexpected warning shown:\n" + "\n".join(warnings)


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    for name in (APODERA, PADAUNGIELLA):
        shutil.copyfile(PICTURES / name, folder / name)
    return folder


def row(project: Project, image: str) -> pd.Series:
    return project.summary().set_index("image").loc[image]


def test_self_test_of_the_installers(tmp_path):
    log = tmp_path / "self_test.log"
    assert launcher.main(["--self-test", "--log", str(log)]) == 0
    assert "self-test passed" in log.read_text(encoding="utf-8")


def test_a_failing_self_test_is_reported_not_raised(tmp_path, monkeypatch):
    """On the installers a raised error would open a dialog that waits for a click."""
    def broken(self, *a, **k):
        raise RuntimeError("cannot analyse")
    monkeypatch.setattr(Project, "run", broken)
    log = tmp_path / "self_test.log"
    assert launcher.main(["--self-test", "--log", str(log)]) == 1
    assert "RuntimeError: cannot analyse" in log.read_text(encoding="utf-8")


def test_corrections_and_undo(images, tmp_path):
    p = Project(tmp_path / "out", images)
    df = p.run().set_index("image")
    assert set(df.status) <= {"ok", "check"}
    r = df.loc[APODERA]

    # Aperture corners by hand, then Accept, then Undo of the acceptance only.
    p.set_aperture(APODERA, (r.landmark_x + 3, r.landmark_y), (r.aperture_end_x - 3, r.aperture_end_y))
    assert row(p, APODERA).landmark_source == "manual"
    p.accept(APODERA, "looks right")
    assert row(p, APODERA).review_note == "looks right"
    p.undo(APODERA)
    assert pd.isna(row(p, APODERA).review_note) and row(p, APODERA).landmark_source == "manual"

    # A bump added by hand: measured, resized, removed.
    outline = np.asarray(p.overlay(PADAUNGIELLA)["outline"])
    x, y = outline[len(outline) // 4]
    p.add_feature(PADAUNGIELLA, "bump", x, y, radius_px=40)
    f = p.overlay(PADAUNGIELLA)["features"][0]
    assert f["kind"] == "bump" and f["radius_px"] == pytest.approx(40)
    p.edit_feature(PADAUNGIELLA, f, (f["x"], f["y"]), 45.0)
    assert p.overlay(PADAUNGIELLA)["features"][0]["radius_px"] == pytest.approx(45)
    p.remove_feature(PADAUNGIELLA, f["x"], f["y"])
    assert not p.overlay(PADAUNGIELLA).get("features")

    # Characters: the genus's values, one set by hand (kept by Back to automatic), Undo.
    assert row(p, APODERA).ch_neck == "distinct" and row(p, APODERA).ch_material == "kleptosomic"
    p.set_characters(APODERA, {"keel": "hollow"})
    r = row(p, APODERA)
    assert r.ch_keel == "hollow" and r.characters_by_hand == "keel" and "characters" in r.corrections
    p.undo(APODERA)
    assert row(p, APODERA).ch_keel == "variable"
    p.set_characters(APODERA, {"genus": "Nebela"})
    assert row(p, APODERA).genus == "Nebela" and row(p, APODERA).ch_neck == "none or short"
    p.undo(APODERA)

    # Outline drawn by hand, then back to automatic.
    p.set_mask(PADAUNGIELLA, p.current_mask(PADAUNGIELLA))
    assert row(p, PADAUNGIELLA).mask_source == "manual"
    p.reset_corrections(PADAUNGIELLA)
    assert row(p, PADAUNGIELLA).mask_source == "auto"

    # The extra tables, and a project opened again.
    out = p.export()
    assert (out / "outline_coordinates.tps").exists() and (out / "profiles_long.csv").exists()
    assert Project.open(tmp_path / "out").has_results()


def test_a_refused_correction_changes_nothing(images, tmp_path):
    """The image folder moved: a correction is refused and nothing is saved, so trying
    again (folder back) makes it once, not twice."""
    p = Project(tmp_path / "out", images)
    p.run()
    r = p.summary().set_index("image").loc[PADAUNGIELLA]
    images.rename(tmp_path / "moved")
    with pytest.raises(ValueError, match="not found"):
        p.add_feature(PADAUNGIELLA, "bump", r.fundus_x, r.fundus_y)
    assert p.corrections(PADAUNGIELLA)["features"] == [] and not p.can_undo(PADAUNGIELLA)
    (tmp_path / "moved").rename(images)
    p.set_fundus(PADAUNGIELLA, (r.fundus_x, r.fundus_y))
    assert len(p.history[PADAUNGIELLA]) == 1


def test_summary_open_in_another_program(images, tmp_path, monkeypatch):
    """summary.csv locked (as by Excel on Windows): a finished run is kept aside and
    saved once the file is free, without analysing again; a correction is saved and
    the table catches up."""
    import ta_morpho.export
    from ta_morpho.export import OutputLocked, SummaryStale
    p = Project(tmp_path / "out", images)
    p.run()
    real, locked = os.replace, [True]

    def replace(src_path, dst):
        if locked[0] and Path(dst).name == "summary.csv" and "staging" not in Path(dst).parts:
            raise PermissionError(13, "Permission denied")
        return real(src_path, dst)
    monkeypatch.setattr(ta_morpho.export.os, "replace", replace)
    with pytest.raises(OutputLocked, match="retry"):
        p.run()
    assert p.finished_run_pending() and not p.save_finished_run()
    locked[0] = False
    assert p.save_finished_run()
    locked[0] = True
    with pytest.raises(SummaryStale):
        p.accept(APODERA, "looks right")
    assert row(p, APODERA).review_note == "looks right"           # shown from the records
    locked[0] = False
    Project.open(tmp_path / "out")
    assert pd.read_csv(tmp_path / "out" / "summary.csv").set_index("image").loc[APODERA, "review_note"] \
        == "looks right"


def test_settings_a_run_cannot_use(images, tmp_path):
    p = Project(tmp_path / "out", images)
    p.settings["rays"]["angle_step_deg"] = 0
    with pytest.raises(ValueError, match="change them in Settings"):
        p.run()
    assert not (tmp_path / "out" / "summary.csv").exists()


def test_command_line_inputs_are_checked(tmp_path):
    """A table saved by a spreadsheet with ';' or decimal commas, an image listed
    twice, a negative calibration: refused with the file named. 'cf' written apart
    from the species is kept with it."""
    from ta_morpho.calibration import load_overrides
    from ta_morpho.landmark import load_landmarks
    from ta_morpho.metadata import parse_filename
    t = tmp_path / "table.csv"
    for content, expected, loader in (
            ("image;x;y\na.png;10;20\n", "';' between the columns", load_landmarks),
            ("image,x,y\na.png,\"12,5\",20\n", "decimal mark", load_landmarks),
            ("image,x,y\na.png,1,2\na.png,3,4\n", "listed more than once", load_landmarks),
            ("image,px_per_um\na.png,-3.5\n", "above 0", load_overrides)):
        t.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match=expected):
            loader(t)
    md = parse_filename("Nebela_cf_collaris_20um_01")
    assert (md.genus, md.species, md.specimen_id) == ("Nebela", "cf.collaris", "01")


def test_files_it_cannot_read_are_refused(images, tmp_path):
    p = Project(tmp_path / "out", images)
    p.run()
    p.cell_csv(APODERA).write_text("type,view\nbackground,dark\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown row type"):
        p.corrections(APODERA)
    odd = tmp_path / "not_a_project"
    odd.mkdir()
    (odd / "summary.csv").write_text("image\nx.png\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Project.open(odd)


def test_damaged_project_file_is_refused(images, tmp_path):
    """A project.yaml cut short is refused with the file named, not replaced by the
    default settings (the user's settings would be lost at the next save)."""
    p = Project(tmp_path / "out", images)
    p.save()
    f = tmp_path / "out" / ".pipeline" / "project.yaml"
    assert f.exists() and not list(f.parent.glob("*.tmp"))     # written in one step
    f.write_text("settings: {rays: {angle_st", encoding="utf-8")
    with pytest.raises(ValueError, match="project.yaml"):
        Project.open(tmp_path / "out")


def test_correction_file_saved_by_excel_or_locked(images, tmp_path, monkeypatch):
    """A correction file saved in the Windows encoding, or open in a program that
    locks it: a plain message naming the file, and nothing changed."""
    import ta_morpho.gui.project
    p = Project(tmp_path / "out", images)
    f = p.cell_csv(APODERA)
    f.parent.mkdir(parents=True)
    f.write_bytes("type,note\nreview,vérifié\n".encode("cp1252"))
    with pytest.raises(ValueError, match="UTF-8"):
        p.corrections(APODERA)
    f.write_text("type,note\nreview,vérifié\n", encoding="utf-8")
    real = os.replace

    def locked(src, dst):
        if Path(dst) == f:
            raise PermissionError(13, "Permission denied")
        return real(src, dst)
    monkeypatch.setattr(ta_morpho.gui.project.os, "replace", locked)
    with pytest.raises(ValueError, match=f"{f.name}.*close it"):
        p.accept(APODERA, "looks right")
    monkeypatch.setattr(ta_morpho.gui.project.os, "replace", real)
    assert f.read_text(encoding="utf-8") == "type,note\nreview,vérifié\n"


def test_window_through_a_project(app, images, tmp_path):
    from PySide6.QtGui import QTextDocument
    from PySide6.QtTest import QTest
    win = MainWindow()
    win.resize(1200, 900)
    win.show()
    assert not win.tabs.isTabEnabled(1)                      # nothing before the folders
    win.folders.set_input(images)
    win.folders.set_output(tmp_path / "out")
    assert win.tabs.isTabEnabled(2) and not win.tabs.isTabEnabled(3)

    # Settings: an edited value is saved in the project and shown in bold.
    _, w = win.settings.widgets[("rays", "angle_step_deg")]
    w.setValue(10)
    assert win.project.settings["rays"]["angle_step_deg"] == 10
    assert win.settings.labels[("rays", "angle_step_deg")].font().bold()

    win.run.start()
    wait(lambda: win.run.worker is None)
    assert win.tabs.isTabEnabled(3) and win.tabs.isTabEnabled(4)
    assert win.review.list.count() == 2

    # The editor shows the picture with the measured length and width lines.
    win.tabs.setCurrentIndex(3)
    win.review.views.setCurrentIndex(1)
    item = win.review.list.findItems(Path(APODERA).stem, Qt.MatchStartsWith)[0]
    win.review.list.setCurrentItem(item)
    canvas = win.review.correct.canvas
    wait(lambda: canvas.isVisible())
    assert canvas.outline is not None and canvas.axes is not None and canvas.length_line.isVisible()

    # Real mouse clicks on the picture with the "Aperture corners" tool set both corners by hand.
    corners = win.project.overlay(APODERA)["aperture"]
    win.review.correct.b_ap.click()
    for x, y in corners:
        QTest.mouseClick(canvas.viewport(), Qt.LeftButton, Qt.NoModifier, canvas.mapFromScene(x, y))
    wait(lambda: win.review.worker is None)
    assert win.review.row()["landmark_source"] == "manual"

    # A note is shown as typed ("<" is not taken for formatting).
    win.review.note.setText("L<100 µm")
    win.review.accept()
    wait(lambda: win.review.worker is None)
    doc = QTextDocument()
    doc.setHtml(win.review.messages.text())
    assert "L<100 µm" in doc.toPlainText()

    # The Characters tab: the genus's values, one set by hand from its list (bold).
    win.review.views.setCurrentIndex(2)
    chars = win.review.chars
    assert chars.genus.currentText() == "Apodera" and chars.boxes["neck"].currentText() == "(distinct, genus)"
    chars.character_changed("keel", chars.boxes["keel"].findData("hollow"))
    wait(lambda: win.review.worker is None)
    assert win.review.row()["ch_keel"] == "hollow"
    assert chars.boxes["keel"].currentText() == "hollow" and chars.boxes["keel"].font().bold()

    win.results.load()
    assert win.results.files.count() >= 3
    win.close()
