"""Desktop interface: choose the folders, adjust the settings, run the
analysis, review every specimen and accept the flags checked by eye.

    python -m ta_morpho.gui

Everything is done through :class:`ta_morpho.gui.project.Project`, i.e. with the
same pipeline and files as the command line (``python -m ta_morpho``).
"""

from __future__ import annotations

import copy
import functools
import html
import sys
import threading
import traceback
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QThread, QUrl, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QCursor, QDesktopServices, QIcon, QKeySequence, QPainter,
                           QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsSimpleTextItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QToolButton, QToolTip, QVBoxLayout,
    QWidget,
)

from ta_morpho.characters import CHARACTERS, KEYS, VALUES, defaults, find_genus, genera, help_text
from ta_morpho.classic import DEFAULTS as CLASSIC_DEFAULTS, axis_fundus, body_outline, oral_axis, section_widths
from ta_morpho.export import EXPORTS, OutputLocked
from ta_morpho.gui.paths import display_path, is_wsl, to_local_path, windows_drives
from ta_morpho.gui.project import Project, default_settings
from ta_morpho.gui.settings import CHOICES, SECTION_LABELS, Setting, all_settings, get_value, parse_value, set_value
from ta_morpho.gui.settings import limits as setting_limits
from ta_morpho.gui.settings import problems as setting_problems
from ta_morpho.image_io import list_images
from ta_morpho.qc import BAR, CENTROID, FEATURE, LANDMARK, LENGTH, OUTLINE, STATUS, WIDTH

APP_NAME = "TA-Morpho"
TAGLINE = "Shape measurement of testate amoeba tests"
# Petrol-teal accent, matching the mask-editing overlay and the app icon.
ACCENT = "#0a7d78"
ACCENT_DARK = "#065a56"
ACCENT_LIGHT = "#13a39c"
STATUS_LABEL = {"ok": "OK", "check": "To check", "failed": "Failed"}
OUTPUT_FILES = [
    ("cells/", "One figure per specimen (as shown in Review)"),
    ("summary.csv", "One row per specimen: status, all measurements, holes/bumps, ray lengths"),
    ("exports/profiles_long.csv", "Every ray of every specimen"),
    ("exports/outline_profile.csv", "Distance from the centroid at the outline points"),
    ("exports/outline_coordinates.tps", "Outline points for geometric morphometrics (tpsDig / geomorph)"),
    ("exports/outline_sliders.csv", "Semilandmark definition for geomorph"),
    ("exports/outline_features.csv", "One row per hole or bump added by hand"),
    (".pipeline/batch.log", "Log of the analysis"),
    (".pipeline/config_used.yaml", "Exact settings of the last run"),
]


def asset(name: str) -> Path:
    """An image shipped with the program, found both when run from the source
    and from a PyInstaller build (datas are unpacked under ``sys._MEIPASS``)."""
    bases = [Path(getattr(sys, "_MEIPASS", "")) / "ta_morpho" / "gui" / "assets",
             Path(__file__).resolve().parent / "assets"]
    for base in bases:
        if (base / name).exists():
            return base / name
    return bases[-1] / name


def app_icon() -> QIcon:
    """The program's testate-amoeba icon."""
    return QIcon(str(asset("icon.png")))


# A light, palette-aware theme: a petrol-teal accent on buttons, tabs and the
# progress bar; cards for the setting groups. Neutral surfaces come from the
# system palette, so it still looks right in a dark theme.
STYLESHEET = f"""
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    padding: 9px 20px; margin-right: 2px; border: none;
    border-bottom: 3px solid transparent; color: palette(text);
}}
QTabBar::tab:hover {{ color: {ACCENT}; }}
QTabBar::tab:selected {{
    color: {ACCENT}; font-weight: 600; border-bottom: 3px solid {ACCENT};
}}
QTabBar::tab:disabled {{ color: palette(mid); }}
QPushButton {{
    padding: 6px 14px; border: 1px solid palette(mid); border-radius: 6px;
    background: palette(button);
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: palette(midlight); }}
QPushButton:checked {{
    background: {ACCENT}; color: white; border-color: {ACCENT};
}}
QPushButton:disabled {{ color: palette(mid); border-color: palette(midlight); }}
QPushButton[accent="true"] {{
    background: {ACCENT}; color: white; border: 1px solid {ACCENT_DARK};
}}
QPushButton[accent="true"]:hover {{ background: {ACCENT_LIGHT}; }}
QPushButton[accent="true"]:pressed {{ background: {ACCENT_DARK}; }}
QPushButton[accent="true"]:disabled {{ background: palette(midlight); color: palette(mid);
                                       border-color: palette(midlight); }}
QGroupBox {{
    border: 1px solid palette(midlight); border-radius: 8px;
    margin-top: 12px; padding: 10px 6px 4px 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {ACCENT}; font-weight: 600;
}}
QProgressBar {{ border: 1px solid palette(midlight); border-radius: 6px; height: 16px;
                text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QToolButton#help {{
    border: none; border-radius: 9px; background: {ACCENT};
    color: white; font-weight: 700; font-size: 12px;
}}
QToolButton#help:hover {{ background: {ACCENT_LIGHT}; }}
QFrame#Header {{ background: {ACCENT}; }}
QLabel#HeaderTitle {{ color: white; font-size: 18px; font-weight: 700; }}
QLabel#HeaderTag {{ color: rgba(255,255,255,0.85); font-size: 12px; }}
"""


def accent(button: QPushButton) -> QPushButton:
    """Mark a button as the teal primary action (styled by the stylesheet)."""
    button.setProperty("accent", True)
    return button


def help_bubble(text: str) -> QToolButton:
    """A small round “?” that shows a paragraph of guidance on hover or click.
    Use it next to a heading or a control to explain a step in plain words."""
    b = QToolButton()
    b.setObjectName("help")
    b.setText("?")
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(18, 18)
    b.setToolTip(text)                      # hover
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(lambda: QToolTip.showText(QCursor.pos(), text, b))   # click
    return b


def setting_help_html(st: Setting) -> str:
    """Help shown in a setting's “?” bubble: a plain explanation first, then the
    precise note from config.yaml and the default, in grey."""
    parts = []
    if st.plain:
        parts.append(f"<p style='margin:0'>{html.escape(st.plain)}</p>")
    if st.help:
        parts.append(f"<p style='margin:8px 0 0 0; color:gray'>{html.escape(st.help)}</p>")
    default = "automatic" if st.default is None else st.default
    parts.append(f"<p style='margin:8px 0 0 0; color:gray'>Default: {html.escape(str(default))}</p>")
    return "".join(parts)


@functools.cache
def status_icon(status: str) -> QIcon:
    """A small coloured disc for a status (drawn once per status), also drawn
    at 2x and 3x so that it stays sharp on high-resolution screens."""
    icon = QIcon()
    for k in (1, 2, 3):
        pm = QPixmap(14 * k, 14 * k)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(k, k)
        p.setBrush(QColor(STATUS.get(status, ("#999999",))[0]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()
        pm.setDevicePixelRatio(k)              # the same 14 px disc on screen, k times sharper
        icon.addPixmap(pm)
    return icon


def heading(text: str, sub: str = "", help: str = "") -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 8)
    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(8)
    t = QLabel(text)
    t.setStyleSheet("font-size: 17px; font-weight: 600;")
    title_row.addWidget(t)
    if help:
        title_row.addWidget(help_bubble(help))
    title_row.addStretch()
    v.addLayout(title_row)
    if sub:
        s = QLabel(sub)
        s.setWordWrap(True)
        s.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(s)
    return w


def primary(button: QPushButton) -> QPushButton:
    button.setDefault(True)
    button.setMinimumHeight(34)
    accent(button)
    return button


def choose_folder(parent: QWidget, title: str, current: str) -> Path | None:
    """Folder dialog. Under WSL the Qt dialog is used, opening on the Windows
    drives (/mnt/c, /mnt/d, ...) with the drives in its side panel."""
    start = to_local_path(current) if current else None
    if not is_wsl():
        d = QFileDialog.getExistingDirectory(parent, title, str(start) if start else "")
        return Path(d) if d else None
    drives = windows_drives()
    dlg = QFileDialog(parent, title)
    dlg.setFileMode(QFileDialog.Directory)
    dlg.setOption(QFileDialog.ShowDirsOnly, True)
    dlg.setOption(QFileDialog.DontUseNativeDialog, True)
    dlg.setSidebarUrls([QUrl.fromLocalFile(str(d)) for d in drives] + [QUrl.fromLocalFile(str(Path.home()))])
    dlg.setDirectory(str(start if start and start.is_dir() else drives[0].parent if drives else Path.home()))
    return Path(dlg.selectedFiles()[0]) if dlg.exec() else None


def _quietly(fn) -> None:
    """Run ``fn()`` ignoring errors: for optional background work (a preload),
    which is done again, and reports its errors, when it is really needed."""
    try:
        fn()
    except Exception:  # done again when needed
        pass


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class Worker(QThread):
    """Runs ``fn(worker)`` in the background; ``fn`` may call ``report`` and
    ``stop_requested``."""

    progress = Signal(int, int, str, str)
    done = Signal(object)
    failed = Signal(str)
    refused = Signal(str)        # something the user can fix (invalid file, file locked…): plain message

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn, self._stop = fn, False
        self.finished.connect(self.deleteLater)      # freed once the thread has ended

    def report(self, i, n, image, status):
        self.progress.emit(i, n, image, status)

    def stop(self):
        self._stop = True

    def stop_requested(self) -> bool:
        return self._stop

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except (ValueError, RuntimeError, OutputLocked) as e:
            self.refused.emit(str(e)[:1].upper() + str(e)[1:].rstrip(".") + ".")
        except Exception as e:  # shown to the user, never silent
            self.failed.emit(f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")


class ImageView(QGraphicsView):
    """Image that fits the view; mouse wheel zooms, double-click fits again."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFrameShape(QFrame.NoFrame)
        self.fitted = True

    def set_image(self, path: Path | None, keep_view: bool = False):
        """Show an image, fitted to the view; ``keep_view`` keeps the zoom and
        position (the same image shown again, e.g. after a correction)."""
        keep = keep_view and not self.fitted and not self.item.pixmap().isNull()
        if keep:
            t, h, v = self.transform(), self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        pm = QPixmap(str(path)) if path and Path(path).exists() else QPixmap()
        self.item.setPixmap(pm)
        self.scene().setSceneRect(self.item.boundingRect())
        if keep and not pm.isNull():
            self.setTransform(t)
            self.horizontalScrollBar().setValue(h)
            self.verticalScrollBar().setValue(v)
        else:
            self.fit()

    def fit(self):
        self.fitted = True
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fitted:
            self.fit()

    def wheelEvent(self, e):
        self.fitted = False
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mouseDoubleClickEvent(self, e):
        self.fit()


# ----------------------------------------------------------------------------- pages
class FoldersPage(QWidget):
    changed = Signal()
    next_requested = Signal()

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.addWidget(heading(
            "1. Choose your folders",
            "The images are only read, never modified. Results and your corrections "
            "are saved in the output folder: choose an existing output folder to "
            "continue a previous analysis.",
            help="Pick two different folders.\n\n"
                 "• Images — the folder holding your microscope pictures (PNG, JPG or TIFF). "
                 "They are only read, never changed.\n"
                 "• Output — where TA-Morpho writes the results (summary.csv, the figures and "
                 "your corrections).\n\n"
                 "To continue earlier work, choose that same output folder again: the previous "
                 "analysis and your corrections are reopened.\n\n"
                 "Under Windows you can also paste a path like F:\\data straight into the box."))
        form = QFormLayout()
        self.input = QLineEdit(placeholderText="Folder with the images (PNG, JPG, TIFF): browse, or paste its path")
        self.input.editingFinished.connect(lambda: self.typed(self.input, self.set_input, must_exist=True))
        b_in = QPushButton("Browse…")
        b_in.clicked.connect(self.choose_input)
        self.input_info = QLabel()
        form.addRow("Images", self._row(self.input, b_in))
        form.addRow("", self.input_info)
        self.output = QLineEdit(placeholderText="Folder for the results: browse, or paste its path")
        self.output.editingFinished.connect(lambda: self.typed(self.output, self.set_output, must_exist=False))
        b_out = QPushButton("Browse…")
        b_out.clicked.connect(self.choose_output)
        self.output_info = QLabel()
        self.output_info.setWordWrap(True)
        form.addRow("Output", self._row(self.output, b_out))
        form.addRow("", self.output_info)
        v.addLayout(form)
        v.addStretch()
        self.next = primary(QPushButton("Next: settings →"))
        self.next.clicked.connect(self.next_requested)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(self.next)
        v.addLayout(h)
        self.refresh()

    @staticmethod
    def _row(edit, button):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        h.addWidget(button)
        return w

    def choose_input(self):
        d = choose_folder(self, "Folder with the images", self.input.text())
        if d:
            self.set_input(d)

    def choose_output(self):
        d = choose_folder(self, "Output folder", self.output.text())
        if d:
            self.set_output(d)

    def typed(self, edit: QLineEdit, setter, must_exist: bool):
        """A path typed or pasted in a folder field (Windows paths accepted)."""
        path = to_local_path(edit.text())
        current = self.win.pending_input if setter == self.set_input else (
            self.win.project.output_dir if self.win.project else None)
        if path is None or (current is not None and path == current):
            self.refresh()
            return
        ok = path.is_dir() if must_exist else (path.is_dir() or path.parent.is_dir())
        if not ok:
            QMessageBox.warning(self, APP_NAME, f"Folder not found:\n{edit.text()}")
            self.refresh()
            return
        setter(path)

    def set_input(self, path: Path):
        path = path.resolve()
        p = self.win.project
        if p is not None and path == p.output_dir.resolve():
            QMessageBox.warning(self, APP_NAME, "Please choose different folders for the images and the results.")
            return
        self.win.pending_input = path
        if p is not None:
            p.input_dir = path
            p.save()
        self.refresh()
        self.changed.emit()

    def set_output(self, path: Path):
        path = path.resolve()
        if self.win.pending_input and path == self.win.pending_input.resolve():
            QMessageBox.warning(self, APP_NAME, "Please choose different folders for the images and the results.")
            return
        if self.win.project is not None and path == self.win.project.output_dir.resolve():
            self.refresh()                      # the same folder again: keep the open project
            return
        c = self.win.review.correct
        if c.tool == "mask" and c.canvas.painted and QMessageBox.question(
                self, APP_NAME, f"The outline drawn on {Path(c.image).stem} is not applied yet.\n\n"
                                "Open another output folder without applying it?") != QMessageBox.Yes:
            self.refresh()
            return
        other = Project.foreign_files(path)
        if other and QMessageBox.question(
                self, APP_NAME,
                f"This folder already holds files that are not part of a TA-Morpho analysis (e.g. "
                f"{', '.join(other[:3])}).\n\nThe program writes only its own files (summary.csv, cells, "
                "exports, .pipeline) and never removes yours, but a new, empty folder is clearer.\n\n"
                "Use this folder anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = Project.open(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, APP_NAME, f"Could not open this output folder:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        other = p.locked_by()
        if other and QMessageBox.question(
                self, APP_NAME,
                f"This analysis seems to be open in another TA-Morpho window ({other}).\n\n"
                "Two windows on one analysis can lose results: close the other one first. If it was "
                "closed by a crash, it is safe to continue.\n\nOpen it here anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            p.lock()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not open this output folder:\n{e}")
            return
        if p.input_dir is None and self.win.pending_input is not None:
            p.input_dir = self.win.pending_input
        elif p.input_dir is not None:
            self.win.pending_input = p.input_dir
        if p.input_dir is not None:
            p.save()
        self.win.set_project(p)
        self.refresh()
        self.changed.emit()

    def refresh(self):
        p, inp = self.win.project, self.win.pending_input
        self.input.setText(display_path(inp))
        if inp is None:
            self.input_info.setText("")
        elif not inp.is_dir():
            self.input_info.setText("⚠ Folder not found (moved, renamed, or drive not connected): choose it again")
        else:
            n = len(list_images([inp], inp))
            self.input_info.setText(f"{n} image{'s' if n != 1 else ''} found" if n else
                                    "⚠ No PNG, JPG or TIFF image in this folder")
        self.output.setText(display_path(p.output_dir) if p else "")
        if p is None:
            self.output_info.setText("")
        elif p.has_results():
            self.output_info.setText(f"Existing analysis found ({len(p.summary())} specimens): "
                                     "it will be opened, with your corrections.")
        else:
            self.output_info.setText("New analysis.")
        self.next.setEnabled(p is not None and p.input_dir is not None)


class SettingsPage(QWidget):
    changed = Signal()
    next_requested = Signal()
    FLOAT_KEYS = {("rays", "angle_step_deg")}   # int in config.yaml, fractions allowed

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self.widgets: dict[tuple[str, str], tuple[Setting, QWidget]] = {}
        self.labels: dict[tuple[str, str], QLabel] = {}
        basic, advanced = all_settings(default_settings())
        v = QVBoxLayout(self)
        v.addWidget(heading(
            "2. Settings", "The defaults suit most images. Click the “?” next to a setting "
                           "for a plain explanation. Changes apply to the next run.",
            help="The defaults work for most images — you can usually skip this page.\n\n"
                 "• Hover over any setting’s name to read what it does; a bold name means you "
                 "changed it from its default.\n"
                 "• The most useful one is the ray step (default 5°): smaller means more rays "
                 "around the test.\n"
                 "• “Show advanced settings” reveals the calibration, segmentation and feature "
                 "options — only needed for tricky images.\n"
                 "• “Reset to defaults” puts everything back.\n\n"
                 "Changes are saved at once and applied the next time you run the analysis."))
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 12, 0)
        g = QGroupBox("Main settings")
        f = QFormLayout(g)
        for st in basic:
            f.addRow(self._label(st), self._editor(st))
        cv.addWidget(g)
        self.show_adv = QCheckBox("Show advanced settings")
        cv.addWidget(self.show_adv)
        self.adv = QWidget()
        av = QVBoxLayout(self.adv)
        av.setContentsMargins(0, 0, 0, 0)
        for section in dict.fromkeys(st.section for st in advanced):
            box = QGroupBox(SECTION_LABELS.get(section, section))
            bf = QFormLayout(box)
            for st in (s for s in advanced if s.section == section):
                bf.addRow(self._label(st), self._editor(st))
            av.addWidget(box)
        self.adv.setVisible(False)
        self.show_adv.toggled.connect(self.adv.setVisible)
        cv.addWidget(self.adv)
        cv.addStretch()
        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        v.addWidget(scroll, 1)
        h = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self.reset)
        h.addWidget(reset)
        h.addStretch()
        nxt = primary(QPushButton("Next: run →"))
        nxt.clicked.connect(self.next_requested)
        h.addWidget(nxt)
        v.addLayout(h)

    def _label(self, st: Setting) -> QWidget:
        """The setting's name followed by a “?” bubble with a plain explanation."""
        lab = QLabel(st.label)
        lab.setToolTip(st.help)
        self.labels[(st.section, st.key)] = lab
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(lab)
        h.addWidget(help_bubble(setting_help_html(st)))
        h.addStretch()
        return row

    def _mark(self, section: str, key: str, value) -> None:
        """Bold label (and its default in the tooltip) when a setting differs
        from the default."""
        st, _ = self.widgets[(section, key)]
        lab = self.labels[(section, key)]
        modified = value != st.default
        f = lab.font()
        f.setBold(modified)
        lab.setFont(f)
        default = "automatic" if st.default is None else st.default
        lab.setToolTip(st.help + (f"\n\nModified (default: {default})" if modified else ""))

    def _editor(self, st: Setting) -> QWidget:
        kind = "float" if (st.section, st.key) in self.FLOAT_KEYS else st.kind
        lo, hi, closed = setting_limits(st.section, st.key)
        if (st.section, st.key) in CHOICES:      # a fixed list of words: chosen, not typed
            w = QComboBox()
            w.addItems(CHOICES[(st.section, st.key)])
            w.currentTextChanged.connect(lambda val, st=st: self._set(st, val))
        elif kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda val, st=st: self._set(st, bool(val)))
        elif kind == "int":
            w = QSpinBox(maximum=int(hi), minimum=int(lo) + (0 if closed else 1))
            w.valueChanged.connect(lambda val, st=st: self._set(st, int(val)))
        elif kind == "float":
            frac = repr(float(st.default)).split(".")[1].rstrip("0")
            decimals = min(4, max(1, len(frac)))
            w = QDoubleSpinBox(maximum=hi, minimum=lo + (0 if closed else 10 ** -decimals), decimals=decimals,
                               singleStep=0.1 if st.default >= 1 else 10 ** -decimals)
            w.valueChanged.connect(lambda val, st=st: self._set(st, float(val)))
        else:
            w = QLineEdit()
            if kind == "optional_float":
                w.setPlaceholderText("automatic")
            elif kind == "list":
                w.setPlaceholderText("values separated by commas")
            w.editingFinished.connect(lambda st=st, w=w: self._set_text(st, w))
        w.setToolTip(st.help)
        w.setMaximumWidth(260)
        self.widgets[(st.section, st.key)] = (st, w)
        return w

    def _set(self, st: Setting, value):
        p = self.win.project
        if p is None or self._loading:
            return
        set_value(p.settings, st.section, st.key, value)
        p.save()
        self._mark(st.section, st.key, value)
        self.changed.emit()

    def _set_text(self, st: Setting, w: QLineEdit):
        p = self.win.project
        if p is None or self._loading:
            return
        try:
            value = parse_value(st, w.text())
            trial = copy.deepcopy(p.settings)
            set_value(trial, st.section, st.key, value)
            new = [m for m in setting_problems(trial) if m not in setting_problems(p.settings)]
            if new:
                raise ValueError("\n".join(new))
        except ValueError as e:
            detail = "" if str(e).startswith(("could not convert", "invalid literal")) else f"\n\n{e}"
            QMessageBox.warning(self, APP_NAME, f"“{w.text()}” is not a valid value for “{st.label}”.{detail}")
            self.load()
            return
        self._set(st, value)

    _loading = False

    def load(self):
        """Show the settings of the current project."""
        p = self.win.project
        settings = p.settings if p else default_settings()
        self._loading = True
        for (section, key), (st, w) in self.widgets.items():
            val = get_value(settings, section, key, st.default)
            if isinstance(w, QComboBox):
                w.setCurrentText(str(val))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(val)
            else:
                w.setText("" if val is None else ", ".join(map(str, val)) if isinstance(val, list) else str(val))
            self._mark(section, key, val)
        self._loading = False

    def reset(self):
        p = self.win.project
        if p is None:
            return
        p.settings = default_settings()
        p.save()
        self.load()
        self.changed.emit()


class RunPage(QWidget):
    finished = Signal()

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win, self.worker = win, None
        self.erased, self.backup = False, None   # last start: "Erase and run again", its backup
        v = QVBoxLayout(self)
        v.addWidget(heading(
            "3. Run the analysis",
            help="Press “Run analysis” to process every image in the folder.\n\n"
                 "• Each image appears in the list with a coloured dot: green = OK, "
                 "orange = to check, red = failed.\n"
                 "• You can press “Stop” at any time: the run is cancelled and the previous "
                 "results are kept as they were (a results folder never mixes two runs). After "
                 "“Erase and run again” there are no previous results left to keep.\n"
                 "• “Run again” re-processes everything — your hand corrections are kept and "
                 "re-applied.\n"
                 "• “Erase and run again” starts from zero: it removes all results and your "
                 "corrections and analyses every image automatically. If you have "
                 "corrections, a backup is saved first (only the few most recent are kept), "
                 "in case you need it.\n\n"
                 "When it finishes, go to “Review” to look at each specimen."))
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {STATUS['check'][0]}; font-weight: 600;")
        v.addWidget(self.warn)
        h = QHBoxLayout()
        self.run_b = primary(QPushButton("Run analysis"))
        self.run_b.setToolTip("Analyse the images; your hand corrections are kept and re-applied")
        self.run_b.clicked.connect(lambda: self.start(clean=False))
        self.reset_b = QPushButton("Erase and run again…")
        self.reset_b.setToolTip("Remove all results and every hand correction, then analyse every "
                                "image from zero (a backup of your corrections is kept first)")
        self.reset_b.clicked.connect(lambda: self.start(clean=True))
        self.reset_b.setVisible(False)
        self.stop_b = QPushButton("Stop")
        self.stop_b.clicked.connect(self.stop)
        self.stop_b.setEnabled(False)
        h.addWidget(self.run_b)
        h.addWidget(self.reset_b)
        h.addWidget(self.stop_b)
        h.addStretch()
        v.addLayout(h)
        self.bar = QProgressBar()
        v.addWidget(self.bar)
        self.log = QListWidget()
        v.addWidget(self.log, 1)
        self.result = QLabel()
        v.addWidget(self.result)
        h2 = QHBoxLayout()
        h2.addStretch()
        self.review_b = primary(QPushButton("Review the results →"))
        self.review_b.clicked.connect(self.finished)
        self.review_b.setVisible(False)
        h2.addWidget(self.review_b)
        v.addLayout(h2)

    def refresh(self):
        p = self.win.project
        if p is None:
            return
        n = len(p.images())
        where = (f"{n} image{'s' if n != 1 else ''} in {display_path(p.input_dir)}"
                 if p.input_dir is not None and p.input_dir.is_dir() else
                 f"⚠ Image folder not found: {display_path(p.input_dir)} (choose it again in Folders)")
        self.info.setText(f"{where}\nResults in {display_path(p.output_dir)}")
        self.run_b.setText("Run again" if p.has_results() else "Run analysis")
        self.warn.setText("A finished analysis is waiting to be saved: close summary.csv in the other "
                          "program, then open this output folder again (or run again)."
                          if p.finished_run_pending() else
                          "The settings or the image folder changed since the last run: run the analysis "
                          "again to apply them." if p.has_results() and p.settings_changed() else "")
        self.run_b.setEnabled(n > 0 and self.worker is None)
        self.reset_b.setVisible(p.has_results())
        self.reset_b.setEnabled(p.has_results() and n > 0 and self.worker is None)
        if self.worker is None and p.has_results():
            c = p.summary()["status"].value_counts().to_dict()
            self.result.setText("Current results: " + ", ".join(
                f"{c.get(s, 0)} {STATUS_LABEL[s].lower()}" for s in ("ok", "check", "failed")))
            self.review_b.setVisible(True)

    def start(self, clean: bool = False):
        p = self.win.project
        try:
            p.check_settings()                   # before anything is erased
        except ValueError as e:
            QMessageBox.warning(self, APP_NAME, "The analysis did not run: " + str(e))
            return
        if clean:
            n = sum(1 for img in p.images()
                    if p.cell_csv(img.name).exists() or p.mask_path(img.name).exists())
            detail = (f"\n\n{n} specimen{'s' if n != 1 else ''} "
                      f"ha{'ve' if n != 1 else 's'} corrections that will be removed. "
                      "A copy of them is saved first (only the few most recent backups "
                      "are kept, in .pipeline/backups), so nothing is lost."
                      if n else "\n\nThere are no hand corrections to lose.")
            if QMessageBox.question(
                    self, APP_NAME,
                    "Erase everything and run from zero?\n\n"
                    "This removes all results and every correction you made by hand "
                    "(outlines, aperture / fundus / scale, holes and bumps added by "
                    "hand and accepted specimens), then analyses "
                    "every image automatically."
                    + detail,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        elif p.has_results() and QMessageBox.question(
                self, APP_NAME, "Run the analysis again? The results will be replaced; your "
                                "corrections are kept and applied.") != QMessageBox.Yes:
            return
        self.log.clear()
        self.result.setText("")
        self.review_b.setVisible(False)
        self.bar.setValue(0)
        self.erased = clean                      # the previous results are gone: say so if stopped
        self.backup = None

        def job(w):
            if clean:
                self.backup = p.reset_all()
            return p.run(progress=w.report, should_stop=w.stop_requested)

        self.win.end_preload()
        self.worker = Worker(job, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.refused.connect(self.on_refused)
        self.run_b.setEnabled(False)
        self.reset_b.setEnabled(False)
        self.stop_b.setEnabled(True)
        self.win.set_busy(True)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.stop_b.setEnabled(False)
            self.result.setText("Stopping after the current image…")

    def on_progress(self, i, n, image, status):
        self.bar.setMaximum(n)
        self.bar.setValue(i)
        item = QListWidgetItem(status_icon(status), f"{image} — {STATUS_LABEL.get(status, status)}")
        self.log.addItem(item)
        self.log.scrollToBottom()

    def on_done(self, df):
        self._end()
        if df.attrs.get("cancelled"):
            if not self.erased:
                self.result.setText("Stopped: the run was cancelled; the previous results are kept.")
                return
            self.result.setText(
                "Stopped: the run was cancelled. The previous results and corrections had already been "
                "erased" + (" (a copy of the corrections is in .pipeline/backups)" if self.backup else "")
                + ": run the analysis again to get results.")
            self.win.results_changed()
            return
        counts = df["status"].value_counts().to_dict() if len(df) else {}
        self.result.setText("Done: " + ", ".join(f"{counts.get(s, 0)} {STATUS_LABEL[s].lower()}"
                                                  for s in ("ok", "check", "failed")))
        self.review_b.setVisible(True)
        self.win.results_changed()

    def on_failed(self, msg):
        self._end()
        QMessageBox.critical(self, APP_NAME, "The analysis stopped with an error:\n\n" + msg)

    def on_refused(self, msg):
        """A file the analysis cannot use (e.g. a correction file edited by
        hand): the run did not start; say which file and why. A finished run
        that could not be saved (summary.csv open elsewhere) is kept aside:
        saved on "Retry", or when the analysis is opened again."""
        self._end()
        p = self.win.project
        if p is None or not p.finished_run_pending():
            QMessageBox.warning(self, APP_NAME, "The analysis did not run:\n\n" + msg)
            return
        while QMessageBox.warning(
                self, APP_NAME, msg + "\n\nUntil then, the previous results are shown.",
                QMessageBox.Retry | QMessageBox.Cancel, QMessageBox.Retry) == QMessageBox.Retry:
            if p.save_finished_run():
                self.on_done(p.summary())
                return
            msg = "summary.csv is still open in another program: close it, then retry."
        self.refresh()

    def _end(self):
        self.worker = None
        self.stop_b.setEnabled(False)
        self.win.set_busy(False)
        self.refresh()


class Canvas(ImageView):
    """The original image with the current detection drawn on top, and the
    mouse tools of the correction panel: ``"point"`` (one click, snapped to
    the outline) and ``"line"`` (press, drag, release). Without a tool, the
    aperture corners and the fundus can be dragged along the outline
    (signal ``moved``: "start", "end" or "fundus", x, y)."""

    clicked = Signal(float, float)
    dragged = Signal(float, float, float, float)
    moved = Signal(str, float, float)
    feature_clicked = Signal(int)    # index in the overlay's feature list
    feature_changed = Signal(int, float, float, float)   # index, new centre x, y, radius (px)

    def __init__(self):
        super().__init__()
        self.mode = None
        self.outline = None          # (N, 2) array of outline points (px)
        self.overlay_items, self.temp_items = [], []
        self.handles: dict[str, QGraphicsEllipseItem] = {}   # draggable markers
        self.ap_line = None
        self.moving = None           # name of the marker being dragged
        self.locked = False          # True while a correction is applied: zoom and pan only
        self.free_points = False     # point clicks may land off the outline (aperture corners)
        self.centroid, self.fundus_auto = None, False
        self.far_frac = CLASSIC_DEFAULTS["fundus_far_frac"]   # setting of the last run, set on load
        self.spine_frac = 0.06       # landmark spine_opening_frac of the last run, set on load
        self.shape = None            # image size (h, w) of the overlay
        self._body = (None, None)    # (key, outline without spines): see body()
        self.axes = None            # length and width lines as measured by the analysis
        self.outline_item = None
        self.feature_items: list[dict] = []       # circle, dot, handle, label of each feature
        self.features: list[dict] = []
        self.feat_drag = None                      # (index, "dot" | "handle", press x, y)
        self.paint_item = None                     # translucent layer of the mask being edited
        self.paint_pm = None
        self.painted = False                       # the mask being edited was changed (not applied)
        self.brush_add, self.brush_r = True, 10.0
        self.last_paint = None
        self.brush_mark = QGraphicsEllipseItem()
        self.brush_mark.setPen(self._pen("#ffffff", 1.5, Qt.DashLine))
        self.brush_mark.setZValue(30)
        self.brush_mark.setVisible(False)
        self.scene().addItem(self.brush_mark)
        self.length_line = self.width_line = None
        self.line_start = None
        self.setMouseTracking(True)
        self.cursor_mark = self._marker(0, 0, "#ffffff", 7, filled=False, z=20)
        # Markers keep their screen size (ItemIgnoresTransformations); partial repaints
        # can leave traces of them when they move, so always repaint the whole view.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.cursor_mark.setVisible(False)

    # drawing helpers (pens and markers keep their screen size at any zoom)
    def _pen(self, colour, width=2.0, style=Qt.SolidLine):
        pen = QPen(QColor(colour), width, style)
        pen.setCosmetic(True)
        return pen

    def _marker(self, x, y, colour, r=6, filled=True, z=10):
        item = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        item.setPos(x, y)
        item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        item.setPen(self._pen("#ffffff" if filled else colour, 1.5 if filled else 2.5))
        item.setBrush(QBrush(QColor(colour)) if filled else Qt.NoBrush)
        item.setZValue(z)
        self.scene().addItem(item)
        return item

    def _line(self, x0, y0, x1, y1, colour, width=2.5, style=Qt.SolidLine, z=5):
        item = QGraphicsLineItem(x0, y0, x1, y1)
        item.setPen(self._pen(colour, width, style))
        item.setZValue(z)
        self.scene().addItem(item)
        return item

    def set_overlay(self, ov: dict):
        for it in self.overlay_items:
            self.scene().removeItem(it)
        self.overlay_items = []
        self.clear_temp()
        out = ov.get("outline")
        self.outline = np.asarray(out, float) if out else None
        self.outline_item = None
        self.axes = ov.get("axes")
        self.shape = ov.get("shape")
        if self.outline is not None and len(self.outline) > 2:
            path = QPainterPath(QPointF(*self.outline[0]))
            for x, y in self.outline[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            item = QGraphicsPathItem(path)
            item.setPen(self._pen(OUTLINE, 1.5))
            item.setZValue(4)
            self.scene().addItem(item)
            self.overlay_items.append(item)
            self.outline_item = item
        if "bar" in ov:
            self.overlay_items.append(self._line(*ov["bar"], BAR, 3))
        self.handles, self.ap_line = {}, None
        self.length_line = self.width_line = None
        self.centroid = ov.get("centroid")
        self.fundus_auto = ov.get("fundus_source", "auto") == "auto"
        if "aperture" in ov and self.outline is not None and self.centroid is not None:
            self.length_line = self._line(0, 0, 0, 0, LENGTH, 2, z=6)
            self.width_line = self._line(0, 0, 0, 0, WIDTH, 2, z=6)
            self.overlay_items += [self.length_line, self.width_line]
        if "aperture" in ov:
            (sx, sy), (ex, ey) = ov["aperture"]
            self.ap_line = self._line(sx, sy, ex, ey, LANDMARK, 2, Qt.DashLine)
            self.handles["start"] = self._marker(sx, sy, LANDMARK, 8)
            self.handles["end"] = self._marker(ex, ey, LANDMARK, 8, filled=False)
            self.overlay_items += [self.ap_line, self.handles["start"], self.handles["end"]]
        if "fundus" in ov:
            self.handles["fundus"] = self._marker(*ov["fundus"], LENGTH, 8)
            self.overlay_items.append(self.handles["fundus"])
        for name, item in self.handles.items():
            item.setToolTip({"start": "Start corner of the aperture: drag along the outline to move it",
                             "end": "Second corner of the aperture: drag along the outline to move it",
                             "fundus": "Fundus: drag along the outline to move it"}[name])
        if "centroid" in ov:
            self.overlay_items.append(self._marker(*ov["centroid"], CENTROID, 5))
        self.features = ov.get("features") or []
        self.feature_items = []
        for f in self.features:
            parts = self._draw_feature(f)
            self.feature_items.append(parts)
            # removed with the rest of the overlay at the next redraw
            self.overlay_items += [it for key, it in parts.items() if key != "f"]
        self.update_axes()

    def _draw_feature(self, f: dict) -> dict:
        """One hole/bump: its circle (real size: the outline inside it is the
        feature), a centre dot on the outline (drag to move along the outline,
        click for options) and a square handle on the circle (drag to resize)."""
        colour = FEATURE[f["kind"]]
        r = float(f.get("radius_px") or 13)
        circle = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        circle.setPos(f["x"], f["y"])
        circle.setPen(self._pen(colour, 2.5, Qt.DashLine))
        circle.setZValue(11)
        self.scene().addItem(circle)
        name = f"{f['kind'][0].upper()}{f['number']}"
        tip = (f"{f['kind'].capitalize()} {name}"
               + (f": {'depth' if f['kind'] == 'hole' else 'height'} {f['size_um']:.1f} µm, "
                  f"width {f['width_um']:.1f} µm" if f.get("size_um") is not None else ""))
        items = {"circle": circle, "f": f}
        dot = self._marker(f["x"], f["y"], colour, 6, z=13)
        dot.setToolTip(tip + ". Drag along the outline to move it; click for options.")
        handle = QGraphicsRectItem(-5, -5, 10, 10)
        handle.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        handle.setPos(f["x"] + r, f["y"])
        handle.setPen(self._pen("#ffffff", 1.5))
        handle.setBrush(QBrush(QColor(colour)))
        handle.setZValue(13)
        handle.setToolTip("Drag to make the circle larger or smaller: the outline inside it is the "
                          + f["kind"])
        self.scene().addItem(handle)
        label = QGraphicsSimpleTextItem(name + (f" · {f['size_um']:.1f} µm" if f.get("size_um") is not None else ""))
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        label.setBrush(QBrush(QColor(colour)))
        label.setPos(f["x"] + r * 0.72, f["y"] - r * 0.72)
        label.setZValue(13)
        self.scene().addItem(label)
        items.update(dot=dot, handle=handle, label=label)
        return items

    def _feature_part_at(self, e):
        """(index, "dot" | "handle") of the feature part under the mouse, or None;
        a handle wins over a dot under it."""
        hits = []
        for it in self.items(e.position().toPoint()):
            while it is not None:
                for i, parts in enumerate(self.feature_items):
                    for part in ("handle", "dot"):
                        if parts.get(part) is it:
                            hits.append((i, part))
                it = it.parentItem()
        hits.sort(key=lambda h: h[1] != "handle")
        return hits[0] if hits else None

    def _set_feature_geometry(self, i, x, y, r):
        parts = self.feature_items[i]
        parts["circle"].setPos(x, y)
        parts["circle"].setRect(-r, -r, 2 * r, 2 * r)
        parts["dot"].setPos(x, y)
        parts["handle"].setPos(x + r, y)
        parts["label"].setPos(x + r * 0.72, y - r * 0.72)

    # ----- outline editing (mode "paint") -----------------------------------
    PAINT_RGBA = (0, 200, 170, 110)            # translucent teal = test

    def start_paint(self, mask: np.ndarray):
        """Show ``mask`` as a translucent layer that the brush / eraser modify."""
        from PySide6.QtGui import QImage
        h, w = mask.shape
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[mask] = self.PAINT_RGBA
        img = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        self.paint_pm = QPixmap.fromImage(img)
        self.paint_item = QGraphicsPixmapItem(self.paint_pm)
        self.paint_item.setZValue(3)
        self.scene().addItem(self.paint_item)
        self.painted = False
        for it in self.overlay_items:              # keep only the outline for reference
            it.setVisible(it is self.outline_item)
        self.set_mode("paint")

    def stop_paint(self):
        if self.paint_item is not None:
            self.scene().removeItem(self.paint_item)
        self.paint_item = self.paint_pm = self.last_paint = None
        self.painted = False
        self.brush_mark.setVisible(False)
        for it in self.overlay_items:
            it.setVisible(True)
        self.update_axes()
        self.set_mode(None)

    def paint_mask(self) -> np.ndarray:
        """The edited mask (True = test)."""
        img = self.paint_pm.toImage().convertToFormat(self.paint_pm.toImage().Format.Format_RGBA8888)
        w, h = img.width(), img.height()
        arr = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine())
        return arr[:, : 4 * w].reshape(h, w, 4)[..., 3] > 0

    def _paint(self, x, y):
        """One brush step (a round line from the previous point)."""
        p = QPainter(self.paint_pm)
        p.setRenderHint(QPainter.Antialiasing, False)
        if self.brush_add:
            p.setCompositionMode(QPainter.CompositionMode_Source)
            colour = QColor(*self.PAINT_RGBA)
        else:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            colour = QColor(0, 0, 0, 0)
        pen = QPen(colour, 2 * self.brush_r, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        a = self.last_paint or (x, y)
        p.drawLine(QPointF(*a), QPointF(x, y))
        p.end()
        self.paint_item.setPixmap(self.paint_pm)
        self.last_paint = (x, y)
        self.painted = True

    def _show_brush(self, x, y):
        r = self.brush_r
        self.brush_mark.setRect(x - r, y - r, 2 * r, 2 * r)
        self.brush_mark.setVisible(True)

    def body(self) -> np.ndarray | None:
        """The outline without spines, target of the automatic fundus (the same as
        the analysis). Slow on a large picture (about a second at 4000 x 3000 px), so
        computed only when a drag needs it, and kept while the outline is the same."""
        if self.outline is None or len(self.outline) <= 2 or not self.shape:
            return None
        key = (tuple(self.shape[:2]), self.spine_frac, self.outline.tobytes())
        if self._body[0] != key:
            filled = np.zeros(self.shape[:2], np.uint8)
            cv2.fillPoly(filled, [np.round(self.outline).astype(np.int32)], 1)
            self._body = (key, body_outline(filled > 0, self.spine_frac))
        return self._body[1]

    def min_corner_gap(self) -> float:
        """Closest allowed distance between the two aperture corners (px): 2 % of
        the perimeter, well below any real aperture."""
        if self.outline is None:
            return 3.0
        closed = np.r_[self.outline, self.outline[:1]]
        return max(3.0, 0.02 * float(np.hypot(*np.diff(closed, axis=0).T).sum()))

    def corners_too_close(self) -> bool:
        a, b = self.handles["start"].pos(), self.handles["end"].pos()
        return np.hypot(a.x() - b.x(), a.y() - b.y()) < self.min_corner_gap()

    def update_axes(self):
        """Length (yellow) and width (cyan) lines along the oral-aboral axis, as
        in the cell figure: the lines measured by the analysis; while an aperture
        corner or the fundus is dragged, recomputed live (same functions as the
        analysis, on the displayed outline), an automatic fundus following the
        corners."""
        if self.length_line is None or "start" not in self.handles:
            return
        if self.moving is None and self.axes:
            self.length_line.setLine(*self.axes[0])
            self.width_line.setLine(*self.axes[1])
            self.length_line.setVisible(True)
            self.width_line.setVisible(True)
            return
        a, b = self.handles["start"].pos(), self.handles["end"].pos()
        start, end = (a.x(), a.y()), (b.x(), b.y())
        too_close = self.corners_too_close()
        self.length_line.setVisible(not too_close)
        self.width_line.setVisible(not too_close)
        if too_close:
            return
        poly = self.outline
        # same rule as the analysis: a fundus set by hand is only the point the axis goes through
        point = None
        if "fundus" in self.handles and not (self.fundus_auto and self.moving != "fundus"):
            f = self.handles["fundus"].pos()
            point = (f.x(), f.y())
        fundus = axis_fundus(poly, start, end, self.centroid, point, self.far_frac,
                             self.body() if point is None else None)
        m, n, u = oral_axis(start, end, self.centroid, fundus)
        t, s = (poly - m) @ n, (poly - m) @ u
        at = lambda tt, ss: m + tt * n + ss * u  # noqa: E731
        p, q = at(t.min(), 0), at(t.max(), 0)
        self.length_line.setLine(p[0], p[1], q[0], q[1])
        levels, widths = section_widths(poly, m, n, u, step=max(1.0, np.ptp(t) / 300))
        if np.isfinite(widths).any():
            tw = levels[int(np.nanargmax(widths))]
            p, q = at(tw, s.min()), at(tw, s.max())
            self.width_line.setLine(p[0], p[1], q[0], q[1])
        if self.fundus_auto and "fundus" in self.handles and self.moving != "fundus":
            self.handles["fundus"].setPos(*fundus)

    def clear_temp(self):
        for it in self.temp_items:
            self.scene().removeItem(it)
        self.temp_items = []
        self.line_start = None

    def add_temp_marker(self, x, y, colour):
        self.temp_items.append(self._marker(x, y, colour, 7, z=15))

    def set_mode(self, mode):
        self.mode = mode
        self.clear_temp()
        self.cursor_mark.setVisible(False)
        self.setDragMode(QGraphicsView.ScrollHandDrag if mode is None else QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.OpenHandCursor if mode is None else Qt.CrossCursor)

    def snap(self, x, y):
        """Nearest outline point (the pipeline snaps again to the exact outline)."""
        if self.outline is None:
            return x, y
        k = int(np.argmin(np.hypot(self.outline[:, 0] - x, self.outline[:, 1] - y)))
        return float(self.outline[k, 0]), float(self.outline[k, 1])

    MAGNET_SCREEN_PX = 12

    def magnet(self, x, y):
        """An aperture corner: onto the outline when dropped within a few screen
        pixels of it, else where it is (the opening at the bases of spines or
        teeth may lie off the outline)."""
        sx, sy = self.snap(x, y)
        reach = self.MAGNET_SCREEN_PX / max(self.transform().m11(), 1e-6)
        return (sx, sy) if np.hypot(sx - x, sy - y) <= reach else (float(x), float(y))

    def _scene_xy(self, e):
        p = self.mapToScene(e.position().toPoint())
        return p.x(), p.y()

    def _handle_at(self, e) -> str | None:
        item = self.itemAt(e.position().toPoint())
        return next((n for n, it in self.handles.items() if it is item), None)

    def mousePressEvent(self, e):
        if self.locked:                              # a correction is being applied: look, do not touch
            super().mousePressEvent(e)
            return
        if self.mode is None and e.button() == Qt.LeftButton and self.outline is not None:
            name = self._handle_at(e)
            if name is not None:                     # start dragging a marker
                self.moving = name
                self.setDragMode(QGraphicsView.NoDrag)
                return
            part = self._feature_part_at(e)
            if part is not None:                     # move / resize a feature, or click it
                p = e.position()
                self.feat_drag = (*part, p.x(), p.y())
                self.setDragMode(QGraphicsView.NoDrag)
                return
        if self.mode == "paint" and e.button() == Qt.LeftButton and self.paint_pm is not None:
            self.last_paint = None
            self._paint(*self._scene_xy(e))
            return
        if self.mode is None or e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        x, y = self._scene_xy(e)
        if self.mode == "point":
            self.clicked.emit(*(self.magnet(x, y) if self.free_points else self.snap(x, y)))
        elif self.mode == "line":
            self.line_start = (x, y)
            self.temp_items.append(self._line(x, y, x, y, BAR, 3, z=15))

    def mouseMoveEvent(self, e):
        if self.locked:
            super().mouseMoveEvent(e)
            return
        if self.mode == "paint" and self.paint_pm is not None:
            x, y = self._scene_xy(e)
            self._show_brush(x, y)
            if e.buttons() & Qt.LeftButton:
                self._paint(x, y)
            return
        if self.feat_drag is not None:
            i, part = self.feat_drag[:2]
            if part == "handle":
                c = self.feature_items[i]["circle"].pos()
                x, y = self._scene_xy(e)
                r = max(3.0, float(np.hypot(x - c.x(), y - c.y())))
                self._set_feature_geometry(i, c.x(), c.y(), r)
            else:
                r = self.feature_items[i]["circle"].rect().width() / 2
                self._set_feature_geometry(i, *self.snap(*self._scene_xy(e)), r)
            return
        if self.moving is not None:
            x, y = (self.magnet if self.moving in ("start", "end") else self.snap)(*self._scene_xy(e))
            self.handles[self.moving].setPos(x, y)
            if self.ap_line is not None and self.moving in ("start", "end"):
                a, b = self.handles["start"].pos(), self.handles["end"].pos()
                self.ap_line.setLine(a.x(), a.y(), b.x(), b.y())
                self.update_axes()
            elif self.moving == "fundus":           # the length axis ends at the fundus
                self.update_axes()
            return
        if self.mode is None:
            part = self._feature_part_at(e)
            cursor = (Qt.SizeHorCursor if part and part[1] == "handle" else
                      Qt.PointingHandCursor if part or self._handle_at(e) is not None else Qt.OpenHandCursor)
            self.viewport().setCursor(cursor)
        if self.mode == "point" and self.outline is not None:
            self.cursor_mark.setPos(*(self.magnet if self.free_points else self.snap)(*self._scene_xy(e)))
            self.cursor_mark.setVisible(True)
        elif self.mode == "line" and self.line_start is not None:
            x, y = self._straighten(*self._scene_xy(e))
            self.temp_items[-1].setLine(*self.line_start, x, y)
        super().mouseMoveEvent(e)

    def _straighten(self, x, y):
        """Scale bars are horizontal: a nearly horizontal line (< 5°) is made exactly horizontal."""
        x0, y0 = self.line_start
        return (x, y0) if abs(y - y0) < abs(x - x0) * np.tan(np.radians(5)) else (x, y)

    def mouseReleaseEvent(self, e):
        if self.locked:
            super().mouseReleaseEvent(e)
            return
        if self.mode == "paint":
            self.last_paint = None
            return
        if self.feat_drag is not None:
            i, part, px, py = self.feat_drag
            self.feat_drag = None
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            p = e.position()
            if np.hypot(p.x() - px, p.y() - py) < 3:            # a click: options menu
                self.feature_clicked.emit(i)
                return
            parts = self.feature_items[i]
            c = parts["circle"].pos()
            self.feature_changed.emit(i, c.x(), c.y(), parts["circle"].rect().width() / 2)
            return
        if self.moving is not None:
            name, self.moving = self.moving, None
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            pos = self.handles[name].pos()
            self.moved.emit(name, pos.x(), pos.y())
            return
        if self.mode == "line" and self.line_start is not None and e.button() == Qt.LeftButton:
            x, y = self._straighten(*self._scene_xy(e))
            x0, y0 = self.line_start
            self.line_start = None
            if np.hypot(x - x0, y - y0) > 3:
                self.dragged.emit(x0, y0, x, y)
            else:
                self.clear_temp()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.mode is None:
            super().mouseDoubleClickEvent(e)


UNDO_TIP = ("Undo the last change to this specimen, whatever it was: a correction on the image, "
            "a character, or Accept (the Undo buttons of both tabs share one list). The list is "
            "lost when the program is closed, another output folder is opened or everything is erased.")


class CorrectPanel(QWidget):
    """Corrections drawn on the original image: aperture corners, fundus,
    scale bar; Undo and Back to automatic. Each correction re-analyses the
    image (through ReviewPage._update)."""

    TOOLS = {
        "aperture": "Click the first aperture corner (Esc: cancel). Near the outline it snaps onto it; "
                    "further away it stays where you click (e.g. at the base of a spine). "
                    "To adjust only one corner, drag its blue dot instead.",
        "aperture2": "Now click the second aperture corner",
        "fundus": "Click the fundus (aboral end) on the outline",
        "scale": "Drag along the scale bar, from one end to the other",
        "add_hole": "Click the centre of the hole on the outline (then adjust its circle)",
        "add_bump": "Click the centre of the bump on the outline (then adjust its circle)",
    }

    def __init__(self, review: ReviewPage):
        super().__init__()
        self.review, self.image, self.tool, self.first = review, None, None, None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.b_ap = QPushButton("Aperture corners")
        self.b_ap.setToolTip("Set both aperture corners by clicking on the outline (any order)")
        self.b_fu = QPushButton("Fundus")
        self.b_fu.setToolTip("Set the fundus (aboral end of the test) by clicking on the outline")
        self.b_sc = QPushButton("Scale bar")
        self.b_sc.setToolTip("Draw a line along the scale bar and type its length in µm")
        self.b_hole = QPushButton("Add hole")
        self.b_hole.setToolTip("Add a hole (concave stretch of the outline)")
        self.b_bump = QPushButton("Add bump")
        self.b_bump.setToolTip("Add a bump (convex stretch between two concave ones)")
        self.b_undo = QPushButton("Undo")
        self.b_undo.setToolTip(UNDO_TIP)
        self.b_reset = QPushButton("Back to automatic")
        self.b_reset.setToolTip("Remove all corrections drawn on this image")
        for b in (self.b_ap, self.b_fu, self.b_sc, self.b_hole, self.b_bump):
            b.setCheckable(True)
        self.b_hole.clicked.connect(lambda: self.start("add_hole"))
        self.b_bump.clicked.connect(lambda: self.start("add_bump"))
        self.b_ap.clicked.connect(lambda: self.start("aperture"))
        self.b_fu.clicked.connect(lambda: self.start("fundus"))
        self.b_sc.clicked.connect(lambda: self.start("scale"))
        self.b_undo.clicked.connect(lambda: self.apply(lambda p, img: p.undo(img)))
        self.b_reset.clicked.connect(lambda: self.apply(lambda p, img: p.reset_corrections(img)))
        for b in (self.b_ap, self.b_fu, self.b_sc):
            bar.addWidget(b)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        bar.addWidget(sep)
        bar.addWidget(self.b_hole)
        bar.addWidget(self.b_bump)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        bar.addWidget(sep2)
        self.b_mask = QPushButton("Edit outline")
        self.b_mask.setToolTip("Correct the outline with a brush (add to the test) and an eraser "
                               "(remove debris, halo)")
        self.b_mask.setCheckable(True)
        self.b_mask.clicked.connect(self.toggle_mask_edit)
        bar.addWidget(self.b_mask)
        bar.addStretch()
        bar.addWidget(self.b_undo)
        bar.addWidget(self.b_reset)
        v.addLayout(bar)
        # bar shown while the outline is edited
        self.mask_bar = QWidget()
        mb = QHBoxLayout(self.mask_bar)
        mb.setContentsMargins(0, 0, 0, 0)
        self.r_brush = QPushButton("Brush (add)")
        self.r_eraser = QPushButton("Eraser (remove)")
        for b in (self.r_brush, self.r_eraser):
            b.setCheckable(True)
            b.setAutoExclusive(True)
        self.r_brush.setChecked(True)
        self.r_brush.toggled.connect(lambda on: setattr(self.canvas, "brush_add", on))
        self.brush_size = QSpinBox(minimum=1, maximum=500, value=10, suffix=" px")
        self.brush_size.setToolTip("Brush radius (pixels of the image)")
        self.brush_size.valueChanged.connect(lambda v: setattr(self.canvas, "brush_r", float(v)))
        self.size_um = QLabel()
        self.brush_size.valueChanged.connect(self._show_size)
        self.b_apply = primary(QPushButton("Apply outline"))
        self.b_apply.clicked.connect(self.apply_mask)
        self.b_cancel = QPushButton("Cancel")
        self.b_cancel.clicked.connect(self.cancel)
        for w in (self.r_brush, self.r_eraser, QLabel("Size"), self.brush_size, self.size_um):
            mb.addWidget(w)
        mb.addStretch()
        mb.addWidget(self.b_cancel)
        mb.addWidget(self.b_apply)
        self.mask_bar.setVisible(False)
        v.addWidget(self.mask_bar)
        self.hint = QLabel()
        self.hint.setStyleSheet(f"color: {LANDMARK}; font-weight: 600;")
        v.addWidget(self.hint)
        self.canvas = Canvas()
        self.canvas.clicked.connect(self.on_click)
        self.canvas.dragged.connect(self.on_drag)
        self.canvas.moved.connect(self.on_moved)
        self.canvas.feature_clicked.connect(self.on_feature)
        self.canvas.feature_changed.connect(self.on_feature_changed)
        v.addWidget(self.canvas, 1)
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        v.addWidget(self.legend)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.cancel)

    @property
    def project(self):
        return self.review.win.project

    def load(self, image: str | None):
        same = image is not None and image == self.image      # reloaded after a correction: keep the zoom
        if same and self.tool == "mask":      # back from another tab while the outline is edited: keep it
            self.update_buttons()
            return
        if not same:
            self.cancel()
        self.image = image
        self.ov = {}
        if image is None:                     # empty list (e.g. a filter with no match): nothing to edit
            self.canvas.set_image(None)
            self.canvas.set_overlay({})
            self.hint.setText("")
            self.update_buttons()
            return
        path = self.project.image_path(image)
        self.canvas.set_image(path, keep_view=same)
        self.hint.setText("" if path.is_file() else f"Image not found: {display_path(path)} "
                                                    "(choose the image folder again in Folders)")
        self.ov = ov = self.project.overlay(image)
        used = self.project.last_run_config()          # the settings the results were made with
        self.canvas.far_frac = float((used.get("classic") or {}).get(
            "fundus_far_frac", CLASSIC_DEFAULTS["fundus_far_frac"]))
        self.canvas.spine_frac = float((used.get("landmark") or {}).get("spine_opening_frac", 0.06))
        self.canvas.set_overlay(ov)
        corr = self.project.corrections(image)
        lm, sc = corr["landmarks"], corr["scale"]
        n_added = len(corr["features"])
        manual = [name for name, on in (("outline", corr.get("mask", False)),
                                        ("aperture corners", "end_x" in lm), ("fundus", "fundus_x" in lm),
                                        ("scale bar", bool(sc)),
                                        (f"holes/bumps added: {n_added}", n_added)) if on]
        self.legend.setText(
            "<b>Drag a blue dot (aperture corner) or the yellow dot (fundus) to move it along the "
            "outline</b>; length (yellow line) and width (cyan line) follow. <b>Holes (pink) and bumps "
            "(green) are added by hand (Add hole / Add bump): the outline inside the circle is the "
            "feature. Drag the centre dot along the outline, drag the square to resize, click the dot "
            "for options.</b> Outline (magenta), aperture corners (blue: start filled, second hollow), "
            "fundus (yellow dot), centroid (red), scale bar (thick cyan). Mouse wheel: zoom · drag the "
            "image: move."
            + (f"<br><b>Set by hand on this image:</b> {', '.join(manual)}" if manual else ""))
        self.update_buttons()

    ov: dict = {}           # overlay of the image shown (read once in load)

    def update_buttons(self):
        # Nothing can be changed while a correction is applied (files rewritten in the background:
        # do not read them either), nor when the image file cannot be found (it could not be
        # re-analysed; the hint above the image says so).
        missing = self.image is not None and not self.project.image_path(self.image).is_file()
        self.canvas.locked = self.review.worker is not None or missing or self.image is None
        if self.canvas.locked:
            for b in (self.b_ap, self.b_fu, self.b_sc, self.b_hole, self.b_bump, self.b_mask,
                      self.b_undo, self.b_reset):
                b.setEnabled(False)
            return
        has_outline = self.canvas.outline is not None
        self.b_ap.setEnabled(has_outline)
        self.b_fu.setEnabled(has_outline and "aperture" in self.ov)
        self.b_sc.setEnabled(self.image is not None)
        self.b_hole.setEnabled(has_outline and "features" in self.ov)
        self.b_bump.setEnabled(has_outline and "features" in self.ov)
        self.b_undo.setEnabled(self.image is not None and self.project.can_undo(self.image))
        corr = self.project.corrections(self.image) if self.image else {"landmarks": {}, "scale": {}, "features": []}
        self.b_reset.setEnabled(bool(corr["landmarks"] or corr["scale"] or corr["features"] or corr.get("mask")))
        editing = self.tool == "mask"
        for b in (self.b_ap, self.b_fu, self.b_sc, self.b_hole, self.b_bump, self.b_undo, self.b_reset):
            b.setEnabled(b.isEnabled() and not editing)
        self.b_mask.setEnabled(self.image is not None and "shape" in self.ov)
        self.b_mask.setChecked(editing)
        for b, name in ((self.b_ap, "aperture"), (self.b_fu, "fundus"), (self.b_sc, "scale"),
                        (self.b_hole, "add_hole"), (self.b_bump, "add_bump")):
            b.setChecked(self.tool is not None and self.tool.startswith(name))

    def _show_size(self, v=None):
        ppu = self.ov.get("px_per_um")
        self.size_um.setText(f"≈ {self.brush_size.value() / ppu:.1f} µm" if ppu else "")

    def toggle_mask_edit(self):
        if self.tool == "mask":
            return self.cancel()
        mask = self.project.current_mask(self.image) if self.image else None
        if mask is None:                 # no outline found: paint one from scratch
            shape = self.ov.get("shape")
            if not shape:
                self.b_mask.setChecked(False)
                QMessageBox.warning(self, APP_NAME, "This image could not be read.")
                return
            mask = np.zeros(shape, bool)
        self.cancel()
        self.tool = "mask"
        h, w = mask.shape
        self.brush_size.setValue(max(2, int(round(max(h, w) / 100))))
        self.canvas.brush_r = float(self.brush_size.value())
        self.canvas.brush_add = self.r_brush.isChecked()
        self._show_size()
        self.canvas.start_paint(mask)
        self.mask_bar.setVisible(True)
        self.hint.setText("Paint the test with the brush, remove debris or halo with the eraser, then "
                          "Apply outline (Esc: cancel). Only the largest piece is kept; holes are filled.")
        self.update_buttons()

    def apply_mask(self):
        mask = self.canvas.paint_mask()
        self.canvas.stop_paint()
        self.mask_bar.setVisible(False)
        self.apply(lambda p, img: p.set_mask(img, mask), image=self.image)   # the image painted on

    def leave_edit(self, image: str | None, can_stay: bool) -> bool:
        """Another specimen is about to be shown while the outline of this one is
        being edited: ask what to do with the changes not yet applied. True to go
        on (applied or discarded), False to stay ("Cancel", offered if ``can_stay``)."""
        if self.tool != "mask" or image == self.image:
            return True
        if not self.canvas.painted:
            self.cancel()
            return True
        buttons = QMessageBox.Apply | QMessageBox.Discard
        if can_stay:
            buttons |= QMessageBox.Cancel
        answer = QMessageBox.question(
            self, APP_NAME, f"The outline drawn on {Path(self.image).stem} is not applied yet.\n\n"
                            "Apply it (the specimen is analysed again), or discard it?",
            buttons, QMessageBox.Apply)
        if answer == QMessageBox.Apply:
            self.apply_mask()
            return True
        if answer == QMessageBox.Discard:
            self.cancel()
            return True
        return False

    def start(self, tool):
        if self.tool == "mask":
            self.cancel()
        if self.tool and self.tool.startswith(tool):        # second press: cancel
            return self.cancel()
        self.tool, self.first = tool, None
        self.canvas.free_points = tool == "aperture"
        self.canvas.set_mode("line" if tool == "scale" else "point")
        self.hint.setText(self.TOOLS[tool])
        self.update_buttons()

    def cancel(self):
        if self.tool == "mask":
            self.canvas.stop_paint()
            self.mask_bar.setVisible(False)
        self.tool, self.first = None, None
        self.canvas.set_mode(None)
        self.hint.setText("")
        self.update_buttons()

    def on_click(self, x, y):
        if self.tool == "aperture":
            self.first, self.tool = (x, y), "aperture2"
            self.canvas.add_temp_marker(x, y, LANDMARK)
            self.hint.setText(self.TOOLS["aperture2"])
        elif self.tool == "aperture2":
            first = self.first
            if np.hypot(first[0] - x, first[1] - y) < self.canvas.min_corner_gap():
                self.hint.setText("Too close to the first corner: click the other side of the aperture")
                return
            self.canvas.add_temp_marker(x, y, LANDMARK)
            self.apply(lambda p, img: p.set_aperture(img, first, (x, y)))
        elif self.tool == "fundus":
            self.canvas.add_temp_marker(x, y, LENGTH)
            self.apply(lambda p, img: p.set_fundus(img, (x, y)))
        elif self.tool in ("add_hole", "add_bump"):
            kind = self.tool[4:]
            self.canvas.add_temp_marker(x, y, FEATURE[kind])
            self.apply(lambda p, img: p.add_feature(img, kind, x, y))

    def on_feature(self, index: int):
        """Menu for a clicked hole/bump: remove it."""
        f = self.canvas.features[index]
        x, y, what = f["x"], f["y"], f["kind"]
        menu = QMenu(self)
        menu.addAction(f"Remove this {what}", lambda: self.apply(lambda p, img: p.remove_feature(img, x, y)))
        self.popup(menu)

    def popup(self, menu: QMenu) -> None:
        """Show a menu at the mouse (separate method so that tests can choose an item)."""
        menu.exec(QCursor.pos())

    def on_feature_changed(self, index: int, x: float, y: float, radius: float):
        """A hole/bump moved (centre) or resized (circle): measured again on the
        outline inside the new circle."""
        f = dict(self.canvas.features[index])
        self.apply(lambda p, img: p.edit_feature(img, f, (x, y), radius))

    def on_moved(self, name, x, y):
        """A marker dragged to a new outline position: only that point changes."""
        ov = self.ov
        if name == "fundus":
            old = ov.get("fundus")
            if old and np.hypot(old[0] - x, old[1] - y) < 1:
                return
            self.apply(lambda p, img: p.set_fundus(img, (x, y)))
            return
        start, end = ov["aperture"]
        old, other = (start, end) if name == "start" else (end, start)
        if np.hypot(old[0] - x, old[1] - y) < 1:               # click without moving
            return
        if self.canvas.corners_too_close():
            QMessageBox.warning(self, APP_NAME, "The two aperture corners are too close to each "
                                                "other. Place each one on its side of the aperture.")
            self.load(self.image)                             # put the dot back
            return
        self.apply(lambda p, img: p.set_aperture(img, (x, y), tuple(other)))

    def on_drag(self, x0, y0, x1, y1):
        default = self.ov.get("bar_length_um") or self.project.settings["calibration"]["bar_length_um"]
        um, ok = QInputDialog.getDouble(self, APP_NAME, "Length of this scale bar (µm):",
                                        float(default), 0.001, 1e6, 3)
        if not ok:
            self.canvas.clear_temp()
            return
        self.apply(lambda p, img: p.set_scale(img, (x0, y0), (x1, y1), um))

    def apply(self, fn, image: str | None = None):
        project = self.project
        self.tool = None
        self.canvas.set_mode(None)
        self.hint.setText("")
        self.review._update(lambda img: fn(project, img), "Re-analysing this image…", image)
        self.update_buttons()


def _text(v) -> str:
    """A summary.csv cell as text ("" for an empty cell)."""
    return v.strip() if isinstance(v, str) else ""


class CharactersPanel(QWidget):
    """Genus, species and diagnostic characters of the specimen shown
    (ta_morpho.characters): the genus's values from the monograph, any of which can
    be set by hand. Each change is a correction (recorded, Undo)."""

    def __init__(self, review: ReviewPage):
        super().__init__()
        self.review, self.image, self.genus_now = review, None, ""
        # The content scrolls, so that the panel follows the window when it is made smaller
        # (a tab's minimum size is that of its largest page: without this, the whole window).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        v = QVBoxLayout(content)
        top = QFormLayout()
        self.genus = QComboBox()
        self.genus.setEditable(True)
        self.genus.setInsertPolicy(QComboBox.NoInsert)  # a typed name does not join the list of genera
        self.genus.addItems(genera())
        self.genus.setToolTip("The genera of the reference table (Kosakyan et al. 2025); another name can be "
                              "typed. Empty = the genus read from the file name.")
        self.genus.lineEdit().editingFinished.connect(self.genus_changed)
        self.genus.activated.connect(lambda _: self.genus_changed())
        self.species = QLineEdit()
        self.species.editingFinished.connect(self.species_changed)
        top.addRow("Genus", self.genus)
        top.addRow("Species", self.species)
        v.addLayout(top)
        self.source = QLabel()
        self.source.setWordWrap(True)
        self.source.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(self.source)
        form = QFormLayout()
        self.boxes: dict[str, QComboBox] = {}
        for key, label, _ in CHARACTERS:
            box = QComboBox()
            box.activated.connect(lambda i, k=key: self.character_changed(k, i))
            self.boxes[key] = box
            form.addRow(label, box)
        v.addLayout(form)
        self.measured = QLabel()
        self.measured.setWordWrap(True)
        v.addWidget(self.measured)
        bar = QHBoxLayout()
        self.b_undo = QPushButton("Undo")
        self.b_undo.setToolTip(UNDO_TIP)
        self.b_undo.clicked.connect(lambda: self.apply(lambda p, img: p.undo(img)))
        self.b_genus = QPushButton("Back to the genus values")
        self.b_genus.setToolTip("Remove the characters set by hand (the genus and species set by hand stay)")
        self.b_genus.clicked.connect(lambda: self.apply(
            lambda p, img: p.set_characters(img, {k: "" for k in KEYS})))
        bar.addStretch()
        bar.addWidget(self.b_undo)
        bar.addWidget(self.b_genus)
        v.addLayout(bar)
        v.addStretch()

    @property
    def project(self):
        return self.review.win.project

    def load(self, r, busy: bool = False):
        """Show the specimen of summary row ``r`` (None: nothing). While a
        correction is applied (``busy``) everything is disabled and no file is
        read; the panel is loaded again when it ends."""
        for w in (self.genus, self.species, *self.boxes.values(), self.b_undo, self.b_genus):
            w.setEnabled(r is not None and not busy)
        if busy:
            return
        self.image = None if r is None else r["image"]
        if r is None:
            return
        by_hand = self.project.corrections(self.image)["characters"]
        self.genus_now = _text(r.get("genus"))
        for w in (self.genus, self.species):            # filling them in is not a change by the user
            w.blockSignals(True)
        self.genus.setCurrentText(self.genus_now)
        self.species.setText(_text(r.get("species")))
        self.species.setModified(False)
        for w in (self.genus, self.species):
            w.blockSignals(False)
        for w, key in ((self.genus, "genus"), (self.species, "species")):
            f = w.font()
            f.setBold(key in by_hand)
            w.setFont(f)
        table = find_genus(self.genus_now)
        self.source.setText(
            f"Values of <i>{html.escape(table)}</i> from Kosakyan et al. (2025); change one to set it by hand "
            "for this specimen (shown in bold). Nothing here is detected on the picture." if table else
            f"<i>{html.escape(self.genus_now or 'No genus')}</i> is not in the reference table: no values "
            "to start from. "
            "Choose a genus, or set the characters by hand.")
        default = defaults(self.genus_now)
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.clear()
            box.addItem(f"({default[key]}, genus)" if key in default else "(not stated)", "")
            for value in VALUES[key]:
                box.addItem(value, value)
            hand = by_hand.get(key, "")
            box.setCurrentIndex(box.findData(hand) if hand else 0)
            f = box.font()
            f.setBold(bool(hand))
            box.setFont(f)
            box.setToolTip(help_text(self.genus_now, key))
            box.blockSignals(False)
        self.measured.setText(
            "<b>Measured on the outline</b> (METHODS § 7): neck distinctness (neck_jump) "
            f"{_num(r.get('neck_jump'))} · rim curvature (aperture_sag) {_num(r.get('aperture_sag'))} · "
            f"horns and spines {_num(r.get('n_protrusions'), 0)}")
        self.b_undo.setEnabled(not busy and self.project.can_undo(self.image))
        self.b_genus.setEnabled(not busy and any(k in by_hand for k in KEYS))

    def character_changed(self, key: str, index: int):
        self.apply(lambda p, img: p.set_characters(img, {key: self.boxes[key].itemData(index)}))

    def genus_changed(self):
        text = self.genus.currentText().strip()
        if self.image is None or text == self.genus_now:
            return
        self.apply(lambda p, img: p.set_characters(img, {"genus": find_genus(text) or text}))

    def species_changed(self):
        text = self.species.text().strip().lower()
        if self.image is None or not self.species.isModified():
            return
        self.species.setModified(False)
        self.apply(lambda p, img: p.set_characters(img, {"species": text}))

    def apply(self, fn):
        if self.image is None or self.review.worker is not None:
            return
        project = self.project
        self.review._update(lambda img: fn(project, img), "Updating this specimen…")


def _num(v, digits: int = 2) -> str:
    """A number of summary.csv as text ("–" when empty)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return "–" if np.isnan(v) else f"{v:.{digits}f}"


class ReviewPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win, self.worker, self.df = win, None, None
        v = QVBoxLayout(self)
        v.addWidget(heading(
            "4. Review each specimen",
            "Check the figures. A specimen “to check” whose flag is a real feature "
            "(checked by eye) can be accepted: its status becomes OK and the "
            "automatic messages are kept in the results.",
            help="Go through the specimens on the left (filter them by status at the top).\n\n"
                 "• “Result figure” shows the measured test; “Correct on the image” lets you fix "
                 "it by hand (aperture, fundus, scale bar, holes/bumps, or the outline with a "
                 "brush).\n"
                 "• “Characters” shows the genus, the species and the genus’s diagnostic characters "
                 "(from the reference table); any of them can be set by hand for this specimen.\n"
                 "• Undo (in both tabs) takes back the last change to this specimen, whatever it was. "
                 "The Undo list is lost when the program is closed.\n"
                 "• If a specimen is flagged “to check” but looks correct to your eye, write an "
                 "optional note and press “Accept after visual check” — it becomes OK and the "
                 "original message is kept.\n"
                 "• Every correction re-analyses just that one image.\n\n"
                 "On the image: mouse wheel zooms, drag moves, double-click fits to the window."))
        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.filter = QComboBox()
        self.filter.addItems(["All specimens", "To check", "Failed", "OK"])
        self.filter.currentIndexChanged.connect(lambda _: self.fill_list(keep_row=False))
        lv.addWidget(self.filter)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.show_current)
        lv.addWidget(self.list, 1)
        self.counts = QLabel()
        lv.addWidget(self.counts)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.view = ImageView()
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        fig = QWidget()
        fv = QVBoxLayout(fig)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.addWidget(self.view, 1)
        hint = QLabel("Mouse wheel: zoom · drag: move · double-click: fit")
        hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        fv.addWidget(hint)
        self.correct = CorrectPanel(self)
        self.chars = CharactersPanel(self)
        self.views = QTabWidget()
        self.views.addTab(fig, "Result figure")
        self.views.addTab(self.correct, "Correct on the image")
        self.views.addTab(self.chars, "Characters")
        # while a correction rewrites the files, the panels are only disabled (show_current reloads
        # them when it ends)
        self.views.currentChanged.connect(lambda i: self.show_current() if i in (1, 2) else None)
        rv.addWidget(self.views, 1)
        self.status = QLabel()
        self.status.setStyleSheet("font-weight: 600; font-size: 14px;")
        rv.addWidget(self.status)
        self.messages = QLabel()
        self.messages.setWordWrap(True)
        self.messages.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rv.addWidget(self.messages)
        h = QHBoxLayout()
        self.note = QLineEdit(placeholderText="Note (optional), e.g. “neck seen by eye, correct”")
        self.accept_b = QPushButton("Accept after visual check")
        self.accept_b.clicked.connect(self.accept)
        self.undo_b = QPushButton("Undo acceptance")
        self.undo_b.clicked.connect(self.unaccept)
        h.addWidget(self.note, 1)
        h.addWidget(self.accept_b)
        h.addWidget(self.undo_b)
        rv.addLayout(h)
        nav = QHBoxLayout()
        self.prev_b, self.next_b = QPushButton("← Previous"), QPushButton("Next →")
        self.prev_b.clicked.connect(lambda: self.step(-1))
        self.next_b.clicked.connect(lambda: self.step(1))
        nav.addWidget(self.prev_b)
        nav.addStretch()
        nav.addWidget(self.next_b)
        rv.addLayout(nav)
        split.addWidget(right)
        split.setStretchFactor(1, 4)
        split.setSizes([260, 1000])
        v.addWidget(split, 1)

    def load(self):
        p = self.win.project
        self.df = p.summary() if p and p.has_results() else None
        self.fill_list()

    def fill_list(self, keep_row: bool = True):
        """Fill the list (filter applied), keeping the specimen shown; if it left
        the list (e.g. accepted while only those to check are listed), the one now
        at its place (``keep_row``) or the first."""
        current, at = self.current_image(), self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        if self.df is None or not len(self.df):
            self.list.blockSignals(False)
            self.counts.setText("No results yet.")
            self.show_current()
            return
        want = {1: "check", 2: "failed", 3: "ok"}.get(self.filter.currentIndex())
        df, rows = self.df, []
        none = [None] * len(df)                  # only the columns shown (iterrows is slow on 200 columns)
        for image, status, genus, species in zip(df["image"], df["status"], df.get("genus", none),
                                                 df.get("species", none), strict=True):
            if want and status != want:
                continue
            taxon = " ".join(str(x) for x in (genus, species) if isinstance(x, str))
            item = QListWidgetItem(status_icon(status), Path(image).stem)
            item.setData(Qt.UserRole, image)
            item.setToolTip(f"{image}\n{taxon or 'taxon not read from the file name'}\n"
                            f"{STATUS_LABEL.get(status, status)}")
            self.list.addItem(item)
            rows.append(image)
        c = df["status"].value_counts().to_dict()
        self.counts.setText(" · ".join(f"{c.get(s, 0)} {STATUS_LABEL[s].lower()}" for s in ("ok", "check", "failed")))
        self.list.setCurrentRow(rows.index(current) if current in rows else
                                -1 if not rows else min(max(at, 0), len(rows) - 1) if keep_row else 0)
        self.list.blockSignals(False)
        self.show_current()                      # once (signals were off while the row was set)

    def current_image(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def row(self):
        img = self.current_image()
        if img is None or self.df is None:
            return None
        return self.df[self.df["image"] == img].iloc[0]

    def _row_of(self, image: str | None) -> int:
        """Row of ``image`` in the list, -1 if not listed."""
        return next((i for i in range(self.list.count())
                     if self.list.item(i).data(Qt.UserRole) == image), -1)

    def show_current(self, *_):
        edited = self.correct.image
        back = self._row_of(edited)
        if not self.correct.leave_edit(self.current_image(), can_stay=back >= 0):
            self.list.blockSignals(True)                # "Cancel": stay on the specimen being edited
            self.list.setCurrentRow(back)
            self.list.blockSignals(False)
        r = self.row()
        busy = self.worker is not None
        if r is None or (self.views.currentIndex() == 1 and not busy):
            self.correct.load(None if r is None else r["image"])
        elif busy:
            self.correct.update_buttons()
        if r is None or self.views.currentIndex() == 2:
            self.chars.load(r, busy)
        if r is None:
            self.view.set_image(None)
            self.status.setText("")
            self.messages.setText("")
            for w in (self.accept_b, self.undo_b, self.note):
                w.setVisible(False)
            self.prev_b.setEnabled(False)
            self.next_b.setEnabled(False)
            return
        row = self.list.currentRow()                     # no wrap: Previous / Next stop at the ends
        self.prev_b.setEnabled(row > 0)
        self.next_b.setEnabled(row < self.list.count() - 1)
        self.view.set_image(self.win.project.cell_figure(r["image"]))
        reviewed = isinstance(r.get("review_note"), str) and r["review_note"] != "" or (
            r["status"] == "ok" and r.get("auto_status") == "check")
        colour = STATUS.get(r["status"], ("#999",))[0]
        label = STATUS_LABEL.get(r["status"], r["status"]) + (" (accepted after visual check)" if reviewed else "")
        self.status.setText(f"<span style='color:{colour}'>●</span> {label}")
        msgs = r.get("messages")
        msgs = msgs if isinstance(msgs, str) and msgs else "No issues detected."
        note = r.get("review_note")
        # rich text: the messages and the note are escaped (a note "L<100" would lose its end)
        text = "<br>".join("• " + html.escape(m) for m in msgs.split(" | "))
        if isinstance(note, str) and note:
            text = f"<b>Your note:</b> {html.escape(note)}<br>" + text
        self.messages.setText(text)
        can_accept = r["status"] == "check" and not reviewed
        self.accept_b.setVisible(can_accept)
        self.note.setVisible(can_accept)
        self.undo_b.setVisible(reviewed)
        for w in (self.accept_b, self.undo_b, self.note):
            w.setEnabled(not busy)

    def step(self, d):
        i = self.list.currentRow() + d
        if 0 <= i < self.list.count():                   # stops at the first and the last
            self.list.setCurrentRow(i)

    def _update(self, fn, message, image: str | None = None):
        """Apply one change to a specimen (default: the one shown) in the background.
        Only one at a time: a change asked for while another is applied is ignored (the
        controls are disabled meanwhile; this guard covers any path that slips through)."""
        if self.worker is not None:
            return
        image = image or self.current_image()
        if image is None:
            return
        self.win.end_preload()
        self.worker = Worker(lambda w: fn(image), self)
        self.worker.done.connect(self._updated)
        self.worker.failed.connect(lambda msg: (self._updated(None),
                                                QMessageBox.critical(self, APP_NAME, msg)))
        self.worker.refused.connect(lambda msg: (self._updated(None),
                                                 QMessageBox.warning(self, APP_NAME, msg)))
        self.status.setText(message)
        self.win.set_busy(True)
        self.show_current()
        self.worker.start()

    def _updated(self, df):
        """The change ended: ``df`` is the new summary, None when it was refused or
        failed (then the note typed for Accept is kept, to try again)."""
        self.worker = None
        self.win.set_busy(False)
        if df is not None:
            self.note.clear()
        self.load()
        self.win.results_changed(reload_review=False)

    def accept(self):
        note = self.note.text().strip() or "accepted after visual check"
        self._update(lambda img: self.win.project.accept(img, note), "Updating this specimen…")

    def unaccept(self):
        self._update(lambda img: self.win.project.unaccept(img), "Updating this specimen…")


class ResultsPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.addWidget(heading(
            "5. Results", "summary.csv holds everything. The extra tables for "
                          "stats and geometric morphometrics are written to exports/ "
                          "only when you ask. Double-click a file to open it.",
            help="Everything is in your output folder.\n\n"
                 "• summary.csv is the one table that matters: one row per specimen, with the "
                 "status and all the measurements.\n"
                 "• “Export the extra tables” writes the long ray profiles, the outline files for "
                 "geometric morphometrics (tpsDig / geomorph) and the holes/bumps into an exports/ "
                 "sub-folder — only when you ask.\n"
                 "• Double-click any file in the list to open it.\n"
                 "• “Open the output folder” opens it in your file explorer."))
        b = primary(QPushButton("Open the output folder"))
        b.clicked.connect(lambda: self.open(""))
        self.export_b = QPushButton("Export the extra tables")
        self.export_b.setToolTip("Write the long profiles, the outline/geomorph files and the holes/bumps "
                                 "to exports/ (from the results already computed)")
        self.export_b.clicked.connect(self.export)
        h = QHBoxLayout()
        h.addWidget(b)
        h.addWidget(self.export_b)
        h.addStretch()
        v.addLayout(h)
        self.files = QListWidget()
        self.files.itemDoubleClicked.connect(
            lambda it: self.open(it.data(Qt.UserRole)))
        v.addWidget(self.files, 1)

    def open(self, name: str):
        """Open a file or folder of the output folder ("" = the folder itself),
        the extra tables brought up to date first (corrections only mark them
        out of date, to stay fast)."""
        p = self.win.project
        if (name == "" or name.startswith(EXPORTS)) and p.exports_stale():
            self.win._refresh_exports()
        open_path(p.output_dir / name)

    def export(self):
        p = self.win.project
        if p is None or not p.has_results():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)            # a few seconds on a large project
        try:
            out = p.export()
        except (OSError, OutputLocked) as e:
            QMessageBox.warning(self, APP_NAME, f"The extra tables could not be written:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.load()
        QMessageBox.information(self, "Export", f"The extra tables are in\n{display_path(out)}")

    def load(self):
        self.files.clear()
        p = self.win.project
        if p is None:
            return
        self.export_b.setEnabled(p.has_results())
        for name, desc in OUTPUT_FILES:
            if (p.output_dir / name.rstrip("/")).exists():
                it = QListWidgetItem(f"{name}    —    {desc}")
                it.setData(Qt.UserRole, name.rstrip("/"))
                self.files.addItem(it)


# ----------------------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self.pending_input: Path | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1300, 860)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.folders = FoldersPage(self)
        self.settings = SettingsPage(self)
        self.run = RunPage(self)
        self.review = ReviewPage(self)
        self.results = ResultsPage(self)
        for page, name in ((self.folders, "1  Folders"), (self.settings, "2  Settings"),
                           (self.run, "3  Run"), (self.review, "4  Review"), (self.results, "5  Results")):
            wrap = QWidget()
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(24, 18, 24, 18)
            lay.addWidget(page)
            self.tabs.addTab(wrap, name)
        self.setCentralWidget(self._with_header(self.tabs))
        self.folders.changed.connect(self.update_tabs)
        self.folders.next_requested.connect(lambda: self.tabs.setCurrentIndex(1))
        self.settings.changed.connect(self.run.refresh)
        self.settings.next_requested.connect(lambda: self.tabs.setCurrentIndex(2))
        self.run.finished.connect(lambda: self.tabs.setCurrentIndex(3))
        self.tabs.currentChanged.connect(self.on_tab)
        quit_action = QAction("Quit", self, shortcut="Ctrl+Q", triggered=self.close)
        self.addAction(quit_action)
        self.busy = False
        self.preloading: threading.Thread | None = None
        self.update_tabs()

    def _with_header(self, tabs: QWidget) -> QWidget:
        """A thin teal header (icon, name, tagline, a help “?”) above the tabs."""
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(20, 10, 16, 10)
        h.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(36, 36))
        h.addWidget(logo)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("HeaderTitle")
        tag = QLabel(TAGLINE)
        tag.setObjectName("HeaderTag")
        text.addWidget(title)
        text.addWidget(tag)
        h.addLayout(text)
        h.addStretch()
        tip = help_bubble(
            "TA-Morpho measures the shape of testate amoeba tests.\n\n"
            "Work through the tabs in order:\n"
            "1. Folders — your images and an output folder\n"
            "2. Settings — usually leave the defaults\n"
            "3. Run — process every image\n"
            "4. Review — check and correct each specimen\n"
            "5. Results — open summary.csv and export extra tables\n\n"
            "Each tab has its own “?” with more detail.")
        h.addWidget(tip, 0, Qt.AlignTop)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(header)
        v.addWidget(tabs, 1)
        return box

    def set_project(self, project: Project):
        self.end_preload()                           # the preload of the project left behind
        if self.project is not None and self.project is not project:
            self.review.correct.cancel()             # an outline being edited belongs to the old one
            self._refresh_exports()                  # the project left behind
            self._unlock()
        self.project = project
        if project.has_results():                    # first correction as fast as the next ones
            self.preloading = threading.Thread(target=_quietly, args=(project.preload,), daemon=True)
            self.preloading.start()
        self.settings.load()
        self.update_tabs()
        self.results_changed()

    def end_preload(self):
        """Wait for the preload of the results, before anything writes them
        (on Windows a file being read cannot be replaced)."""
        if self.preloading is not None:
            self.preloading.join()
            self.preloading = None

    def results_changed(self, reload_review: bool = True):
        if reload_review:
            self.review.load()
        self.results.load()
        self.run.refresh()
        self.update_tabs()

    def update_tabs(self):
        p = self.project
        ready = p is not None and p.input_dir is not None
        for i, enabled in ((1, ready), (2, ready), (3, ready and p.has_results()),
                           (4, ready and p.has_results())):
            self.tabs.setTabEnabled(i, enabled and (not self.busy or i == self.tabs.currentIndex()))
        self.statusBar().showMessage(f"Output folder: {display_path(p.output_dir)}" if p
                                     else "Choose the folders to start")

    def set_busy(self, busy: bool):
        self.busy = busy
        self.tabs.setTabEnabled(0, not busy or self.tabs.currentIndex() == 0)
        self.update_tabs()

    def on_tab(self, i):
        if i == 2:
            self.run.refresh()

    def closeEvent(self, e):
        c = self.review.correct
        if c.tool == "mask" and c.canvas.painted and QMessageBox.question(
                self, APP_NAME, f"The outline drawn on {Path(c.image).stem} is not applied yet.\n\n"
                                "Quit without applying it?") != QMessageBox.Yes:
            e.ignore()
            return
        if self.run.worker is not None and QMessageBox.question(
                self, APP_NAME, "An analysis is running. Stop it and quit?") != QMessageBox.Yes:
            e.ignore()
            return
        if self.run.worker is not None:
            self.run.worker.stop()
            self.run.worker.wait()
        if self.review.worker is not None:             # a correction being applied: let it finish
            self.review.worker.wait()
        self._refresh_exports()
        self._unlock()
        e.accept()

    def _unlock(self):
        try:
            if self.project is not None:
                self.project.unlock()
        except OSError:                              # a lock left behind is only a question later
            pass

    def _refresh_exports(self):
        """Bring the open project's summary.csv and extra tables up to date
        (a correction that met a locked summary.csv, corrections only mark the
        tables out of date). A failure never prevents quitting or changing
        folders: the project is marked, and it is done again when reopened."""
        if self.project is None:
            return
        try:
            self.project.refresh_summary()
        except Exception:                            # still locked: done when reopened
            pass
        if not self.project.exports_stale():
            return
        self.statusBar().showMessage("Updating the extra tables in exports/…")
        QApplication.setOverrideCursor(Qt.WaitCursor)            # a few seconds on a large project
        QApplication.processEvents()
        try:
            self.project.refresh_exports()
        except Exception as err:  # shown, never silent
            QMessageBox.warning(self, APP_NAME, "The extra tables in exports/ could not be "
                                                f"updated; they will be when the project is opened.\n\n{err}")
        finally:
            QApplication.restoreOverrideCursor()
            self.update_tabs()


def self_test(log: Path | None = None) -> int:
    """Check that the program works end to end (used on the installers): a
    synthetic test with a scale bar is analysed in a temporary folder, and the
    window is created. Prints the result, and writes it to ``log`` if given
    (a windowed program has no console); returns 0 when everything works, 1
    otherwise. Never raises: an error is reported, not shown in a dialog that
    would wait for a click."""
    lines = []

    def say(text: str) -> None:
        print(text)
        lines.append(text)

    try:
        code = _self_test(say)
    except Exception:  # reported, never a blocking dialog
        say("self-test FAILED with an error:\n" + traceback.format_exc())
        code = 1
    if log is not None:
        try:
            Path(log).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"cannot write {log}: {e}", file=sys.stderr)
            code = code or 1
    return code


def _self_test(say) -> int:
    import tempfile

    from ta_morpho import __version__
    from ta_morpho.image_io import write_image
    from ta_morpho.provenance import provenance

    say(f"TA-Morpho {__version__}, Python {sys.version.split()[0]}, {sys.platform}")
    packages = provenance()["packages"]          # recorded with every run (config_used.yaml)
    say("package versions recorded: " + (", ".join(f"{k} {v}" for k, v in packages.items()) or "none"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        raw = tmp / "images"
        raw.mkdir()
        img = np.full((400, 400, 3), 250, np.uint8)
        cv2.ellipse(img, (200, 210), (90, 140), 0, 0, 360, (150, 170, 190), -1)
        img[60:80, 170:230] = 250                                   # aperture: flat top
        img[375:383, 20:220] = 0                                    # 200 px = 25 µm
        write_image(raw / "Testus_selftest_25um_01.png", img)
        project = Project(tmp / "out", raw)
        df = project.run()
        exports = project.export()
        row = df.iloc[0]
        ok = (len(df) == 1 and row["status"] != "failed" and row["px_per_um"] == 8.0
              and (tmp / "out" / "summary.csv").exists()
              and project.cell_figure(row["image"]).exists()
              and (exports / "outline_coordinates.tps").exists())
        app = QApplication.instance() or QApplication([])
        app.setStyleSheet(STYLESHEET)
        win = MainWindow()
        win.close()
        say(f"self-test {'passed' if ok else 'FAILED'}: status {row['status']}, "
            f"length {row['length_um']:.1f} µm")
        return 0 if ok else 1


def show_error(exc_type, exc, tb) -> None:
    """Exception hook: an unexpected error raised on the window's own thread
    (a click, a page change) is shown in a message box, never lost."""
    traceback.print_exception(exc_type, exc, tb)
    parent = QApplication.activeWindow()
    if issubclass(exc_type, (ValueError, OutputLocked)):
        QMessageBox.warning(parent, APP_NAME, str(exc))
        return
    box = QMessageBox(QMessageBox.Critical, APP_NAME, f"Unexpected error: {exc_type.__name__}: {exc}",
                      parent=parent)
    box.setDetailedText("".join(traceback.format_exception(exc_type, exc, tb)))
    box.exec()


def main(argv=None) -> int:
    """Open the window (started by :mod:`ta_morpho.gui.launcher`)."""
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(STYLESHEET)
    sys.excepthook = show_error
    win = MainWindow()
    win.show()
    return app.exec()
