"""Per-specimen report: one PNG with everything computed for a cell.

Top left: the image with outline, rays (numbered), centroid (red), start
landmark (blue), other aperture corner (hollow blue) and detected scale bar.
Top right: the cell with the classic measurements (length, width, aperture,
neck-body junction) and the holes / bumps added by hand circled and numbered.
Bottom: the radial profile; the QC status, measurements and messages.

Colours: categorical slot 1 (blue) for the profile, reserved status colours
for the badge (always with icon + label), neutral ink for all text.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

from ta_morpho.characters import KEYS, LABELS  # noqa: E402
from ta_morpho.classic import oral_axis  # noqa: E402
from ta_morpho.landmark import clockwise_angle, outline  # noqa: E402
from ta_morpho.pipeline import measurements  # noqa: E402
from ta_morpho.rays import subpixel_outline  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3de"
SERIES = ["#2a78d6", "#eb6834"]
APERTURE_FILL = "#ebeae4"
STATUS = {"ok": ("#0ca30c", "✔ OK"), "check": ("#fab219", "⚠ CHECK"),
          "failed": ("#d03b3b", "✖ FAILED")}
# Overlay marks on the photo (high contrast on bright-field images).
RAY, CENTROID, LANDMARK, OUTLINE, BAR = "#ffd400", "#e60000", "#0aa0e6", "#ff00ff", "#00c8ff"
LENGTH, WIDTH, NECK = "#ffd400", "#00c8ff", "#ffffff"
FEATURE = {"hole": "#d6246e", "bump": "#1baf7a"}   # as in the desktop interface

YLABELS = {"radius_um": "Ray length (µm)", "radius_px": "Ray length (px)"}


def style_axes(ax: plt.Axes) -> None:
    """Recessive grid and axes, neutral text."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(INK)
    ax.yaxis.label.set_color(INK)
    ax.title.set_color(INK)


def plot_profile(
    table: pd.DataFrame,
    ax: plt.Axes,
    measure: str = "radius_um",
    aperture_end_deg: float | None = None,
    title: str | None = None,
) -> plt.Axes:
    """Radial profile: x = segment (ray number, 0 = start landmark, with the
    clockwise angle underneath), y = ray length.

    ``aperture_end_deg`` (angle of the second aperture corner) shades the
    rays crossing the aperture. Ray 0 is repeated at the end (hollow
    marker) to show the profile is closed.
    """
    style_axes(ax)
    y = table[measure].to_numpy()
    n = len(y)
    step = 360 / n
    seg = np.arange(n)

    if aperture_end_deg is not None:
        ax.axvspan(0, aperture_end_deg / step, color=APERTURE_FILL, lw=0, zorder=0)
        ax.text(aperture_end_deg / step / 2, 0.02, "aperture", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=8, color=INK_2)
    mean = np.nanmean(y)
    ax.axhline(mean, color=INK_2, lw=0.8, ls=(0, (4, 3)), zorder=1)
    # Label the mean where the profile is furthest from it, to avoid the line.
    xi = int(np.nanargmax(np.abs(y - mean)))
    ax.text(xi, mean, f" mean {mean:.1f} ", va="bottom" if y[xi] < mean else "top",
            ha="center", fontsize=8, color=INK_2)

    ax.plot(np.r_[seg, n], np.r_[y, y[0]], color=SERIES[0], lw=2, zorder=3)
    ax.plot(seg, y, "o", ms=5, color=SERIES[0], zorder=4)
    ax.plot([n], [y[0]], "o", ms=5, mfc=SURFACE, mec=SERIES[0], mew=1.5, zorder=4)

    ticks = np.arange(0, n + 1, max(1, n // 12))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t}\n{t * step:g}°" for t in ticks])
    ax.set_xlim(-0.8, n + 0.8)
    ax.set_xlabel("Segment (ray number; angle clockwise from start landmark)", fontsize=9)
    ax.set_ylabel(YLABELS.get(measure, measure), fontsize=9)
    if title:
        ax.set_title(title, loc="left", fontsize=11)
    return ax


def _draw_specimen(ax: plt.Axes, sp) -> None:
    """Photo with every geometric result that exists for this specimen."""
    ax.imshow(sp.image)
    ax.axis("off")
    cal = sp.calibration
    if cal is not None and cal.bar is not None:
        b = cal.bar
        ax.add_patch(Rectangle((b.x0, b.y_top - 3), b.length_px, b.thickness_px + 6,
                               fill=False, ec=BAR, lw=1.5))
        ax.text((b.x0 + b.x1) / 2, b.y_bottom + 8, f"{b.length_px:.1f} px = {_um(cal.bar_length_um)}",
                ha="center", va="top", fontsize=8, color=INK,
                bbox=dict(boxstyle="round,pad=0.2", fc="#ffffffd9", ec="none"))
    if cal is not None and cal.line is not None:          # bar drawn by hand
        x0, y0, x1, y1 = cal.line
        ax.plot([x0, x1], [y0, y1], color=BAR, lw=2.5, solid_capstyle="butt")
        length = np.hypot(x1 - x0, y1 - y0)
        ax.text((x0 + x1) / 2, max(y0, y1) + 8, f"set by hand: {length:.1f} px = {_um(cal.bar_length_um)}",
                ha="center", va="top", fontsize=8, color=INK,
                bbox=dict(boxstyle="round,pad=0.2", fc="#ffffffd9", ec="none"))
    seg = sp.segmentation
    if seg is None or not seg.mask.any():
        return
    cnt = outline(seg.mask)
    ax.plot(np.r_[cnt[:, 0], cnt[:1, 0]], np.r_[cnt[:, 1], cnt[:1, 1]], color=OUTLINE, lw=1)
    c = sp.centroid
    if sp.profile is not None:
        t = sp.profile.table
        every = max(1, len(t) // 12)
        # Thinner, see-through rays when there are many, so the shell stays visible.
        thin = len(t) > 36
        for i, r in t.iterrows():
            if np.isnan(r.x):
                continue
            ax.plot([c[0], r.x], [c[1], r.y], color=RAY,
                    lw=2.4 if i == 0 else (0.6 if thin else 1),
                    alpha=1 if i == 0 or not thin else 0.75)
            if i % every == 0:
                dx, dy = r.x - c[0], r.y - c[1]
                k = 1 + 0.06 * max(sp.image.shape[:2]) / np.hypot(dx, dy)
                ax.text(c[0] + k * dx, c[1] + k * dy, str(i), ha="center", va="center",
                        fontsize=8, color=INK,
                        bbox=dict(boxstyle="round,pad=0.15", fc="#ffffffd9", ec="none"))
    lm = sp.landmark
    if lm is not None and lm.aperture is not None:
        ax.plot(*lm.aperture.end, "o", ms=9, mfc="none", mec=LANDMARK, mew=2)
    if lm is not None and lm.x is not None:
        ax.plot(lm.x, lm.y, "o", ms=11, color=LANDMARK, mec="white", mew=1)
    if c is not None:
        ax.plot(*c, "o", ms=11, color=CENTROID, mec="white", mew=1)
    h, w = sp.image.shape[:2]
    pad = 0.07 * max(h, w)
    ax.set_xlim(-pad, w + pad)
    ax.set_ylim(h + pad, -pad)


def _draw_classic(ax: plt.Axes, sp) -> None:
    """The cell alone, with the classic measurements along the oral-aboral
    axis and the holes (H) / bumps (B) added by hand, numbered clockwise
    from the start landmark."""
    ax.axis("off")
    seg = sp.segmentation
    if seg is None or not seg.mask.any():
        return
    ax.imshow(sp.image)
    poly = subpixel_outline(seg.mask)
    ax.plot(np.r_[poly[:, 0], poly[0, 0]], np.r_[poly[:, 1], poly[0, 1]], color=OUTLINE, lw=0.8)
    ys, xs = np.nonzero(seg.mask)
    pad = 0.08 * max(np.ptp(xs), np.ptp(ys))
    ax.set_xlim(xs.min() - pad, xs.max() + pad)
    ax.set_ylim(ys.max() + pad, ys.min() - pad)
    c, ap = sp.classic, sp.landmark.aperture if sp.landmark else None
    if c is None or ap is None:
        ax.text(0.5, 0.02, "no aperture: classic measurements not taken", transform=ax.transAxes,
                ha="center", va="bottom", fontsize=9, color=INK,
                bbox=dict(boxstyle="round,pad=0.3", fc="#ffffffd9", ec="none"))
        return
    m, n, u = oral_axis(ap.start, ap.end, sp.centroid, sp.fundus)
    t, s = (poly - m) @ n, (poly - m) @ u
    at = lambda tt, ss: m + tt * n + ss * u  # noqa: E731
    seg_line = lambda p, q, **kw: ax.plot([p[0], q[0]], [p[1], q[1]], **kw)  # noqa: E731
    length = np.ptp(t)
    seg_line(at(t.min(), 0), at(t.max(), 0), color=LENGTH, lw=2)
    tw = t.min() + c["widest_position"] * length
    seg_line(at(tw, s.min()), at(tw, s.max()), color=WIDTH, lw=2)
    seg_line(ap.start, ap.end, color=LANDMARK, lw=3)
    handles = ["length (yellow)", "width (cyan)", "aperture (blue)"]
    if sp.fundus is not None:
        ax.plot(*sp.fundus, "o", ms=8, color=LENGTH, mec=INK, mew=1, zorder=5)
        handles.append("fundus (yellow dot" + (", set by hand)" if sp.fundus_source == "manual" else ")"))
    if not np.isnan(c["NL/L"]):                    # ratio: drawn also without a calibration
        tn = c["NL/L"] * length
        s_n = _crossings(t, s, tn)
        seg_line(at(tn, s_n.min()), at(tn, s_n.max()), color=NECK, lw=1.8, ls=(0, (4, 3)))
        handles.append("neck–body junction (white dashed)")
    feats = sp.features or []
    r = 0.035 * length
    for f in feats:
        ax.add_patch(plt.Circle((f["x"], f["y"]), r, fill=False, ec=FEATURE[f["kind"]], lw=2, ls=(0, (3, 2))))
    # One label per group of neighbouring features, placed outward from the centroid.
    for group in _neighbour_groups(feats, 2.5 * r):
        xy = np.mean([(f["x"], f["y"]) for f in group], axis=0)
        out = xy - np.asarray(sp.centroid)
        xy = xy + out / np.hypot(*out) * 2.2 * r
        ax.text(*xy, " ".join(f"{f['kind'][0].upper()}{f['number']}" for f in group),
                ha="center", va="center", fontsize=8, color=INK, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.15", fc="#ffffffd9", ec="none"))
    if feats:
        handles.append("holes H (pink), bumps B (green), added by hand")
    ax.text(0, 1.01, " · ".join(handles), transform=ax.transAxes, ha="left", va="bottom",
            fontsize=8, color=INK_2)


def _crossings(t: np.ndarray, s: np.ndarray, level: float) -> np.ndarray:
    """Positions s where the closed outline (t, s) crosses t = level."""
    t1, s1 = np.roll(t, -1), np.roll(s, -1)
    k = ((t - level) * (t1 - level) <= 0) & (t != t1)
    return s[k] + (level - t[k]) / (t1[k] - t[k]) * (s1[k] - s[k])


def _neighbour_groups(feats: list[dict], dist: float) -> list[list[dict]]:
    """Consecutive features (in outline order) closer than ``dist`` px."""
    groups = []
    for f in feats:
        if groups and np.hypot(f["x"] - groups[-1][-1]["x"], f["y"] - groups[-1][-1]["y"]) < dist:
            groups[-1].append(f)
        else:
            groups.append([f])
    if len(groups) > 1 and np.hypot(groups[0][0]["x"] - groups[-1][-1]["x"],
                                    groups[0][0]["y"] - groups[-1][-1]["y"]) < dist:
        groups[0] = groups.pop() + groups[0]
    return groups


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _um(v) -> str:
    """A bar length, or "? µm" when none was given (a calibration line without length)."""
    return "? µm" if v is None else f"{v:g} µm"


def _fmt(v, unit="", digits=1) -> str:
    return "–" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{digits}f}{unit}"


def _info_lines(sp) -> list[tuple[str, str]]:
    """(label, value) rows of the measurements in the info panel: the classic
    measurements of the literature only (the shape statistics are in summary.csv)."""
    cal = sp.calibration
    rows = [
        ("Calibration", f"{cal.px_per_um:.3f} px/µm" if cal else "none"),
        ("Scale bar", ("–" if cal is None else
                       f"{_um(cal.bar_length_um)}, set by hand" if cal.line else
                       "manual px/µm" if cal.source == "manual" else
                       f"{_um(cal.bar_length_um)}, detected")),
    ]
    m = measurements(sp)
    if m["axis"]:
        axis = "" if m["axis"] == "oral" else " (principal axis)"
        neck = (f"{_fmt(m['neck_length_um'])} × {_fmt(m['neck_width_um'])} µm"
                if not np.isnan(m["neck_length_um"]) else
                # no calibration: the neck is found but has no µm length; show it as ratios
                f"NL/L {_fmt(m['NL/L'], digits=2)}, NW/W {_fmt(m['NW/W'], digits=2)} (no µm)"
                if not np.isnan(m["NL/L"]) else "none" if sp.classic else "–")
        fs = sp.features
        feats = ("–" if fs is None else "none" if not fs else
                 _count(sum(f["kind"] == "hole" for f in fs), "hole") + ", "
                 + _count(sum(f["kind"] == "bump" for f in fs), "bump"))
        rows += [
            ("L × W" + axis, f"{_fmt(m['length_um'])} × {_fmt(m['width_um'])} µm"),
            ("Aperture width", _fmt(m["aperture_width_um"], " µm")),
            ("Neck length × width", neck),
            ("Area", _fmt(m["area_um2"], " µm²", 0)),
            ("Perimeter", _fmt(m["perimeter_um"], " µm")),
            ("Holes / bumps", feats),
        ]
    return rows


def _character_lines(sp) -> list[tuple[str, str]]:
    """(label, value) rows of the diagnostic characters (ta_morpho.characters): the
    genus's values, and those set by hand marked as such."""
    if not sp.characters:
        genus = sp.metadata.genus if sp.metadata else None
        return [(f"{genus} not in the reference table" if genus else "no genus (set it in Review)", "")]
    return [(LABELS[k], v + (" (by hand)" if src == "hand" else ""))
            for k in KEYS if k in sp.characters for v, src in [sp.characters[k]]]


ROW_H = 0.055  # height of one info row (axes fraction)


def _draw_info(ax: plt.Axes, sp) -> None:
    """Status badge, measurement table and QC messages."""
    ax.axis("off")
    colour, label = STATUS[sp.status]
    if sp.review_note:
        label += " (reviewed)"
    ax.add_patch(FancyBboxPatch((0, 0.9), 0.022, 0.07, boxstyle="round,pad=0.004",
                                fc=colour, ec="none", transform=ax.transAxes))
    ax.text(0.04, 0.935, label, transform=ax.transAxes, fontsize=11, color=INK,
            va="center", fontweight="bold")
    columns = (("Measurements", _info_lines(sp)), ("Characters", _character_lines(sp)))
    for col, (title, chunk) in enumerate(columns):
        x = 0.56 * col
        ax.text(x, 0.83, title, transform=ax.transAxes, fontsize=8.5, color=INK, va="top", fontweight="bold")
        for j, (k, v) in enumerate(chunk, start=1):
            y = 0.83 - j * ROW_H
            ax.text(x, y, k, transform=ax.transAxes, fontsize=8.5, color=INK_2, va="top")
            ax.text(x + 0.2, y, v, transform=ax.transAxes, fontsize=8.5, color=INK, va="top")
    n = max(len(chunk) for _, chunk in columns) + 1
    msgs = sp.messages or ["no issues"]
    if sp.review_note:
        msgs = [f"review: {sp.review_note}"] + [f"note: {m}" for m in sp.messages]
    text = "\n".join(textwrap.fill("• " + m, 110, subsequent_indent="  ") for m in msgs[:6])
    ax.text(0, 0.83 - n * ROW_H - 0.02, text, transform=ax.transAxes, fontsize=8,
            color=INK_2, va="top")


def draw_report(sp, out_path: str | Path) -> None:
    """Write the single per-specimen PNG (see module docstring).

    Works for partial results: whatever was computed is shown, and the
    profile panel says why it is missing. Ray lengths in µm, in pixels when
    the image is not calibrated.
    """
    fig = plt.figure(figsize=(17, 12.5), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1], hspace=0.22, wspace=0.08)
    ax_img = fig.add_subplot(gs[0, 0])
    ax_img.set_facecolor(SURFACE)
    _draw_specimen(ax_img, sp)
    ax_img.set_anchor("N")  # both images start at the top
    md = sp.metadata
    taxon = f"{md.genus} {md.species}" if md is not None and md.genus else "taxon unknown"
    fig.suptitle(f"{taxon} — {sp.path.name}", x=0.125, y=0.95, ha="left", fontsize=14, color=INK)
    ax_img.set_title("Radial rays", loc="left", fontsize=11, color=INK, pad=16)

    ax_cl = fig.add_subplot(gs[0, 1])
    ax_cl.set_facecolor(SURFACE)
    _draw_classic(ax_cl, sp)
    ax_cl.set_anchor("N")
    ax_cl.set_title("Classic measurements, holes and bumps", loc="left", fontsize=11, color=INK, pad=16)

    ax_prof = fig.add_subplot(gs[1, 0])
    if sp.profile is not None:
        t = sp.profile.table
        measure = "radius_px" if t["radius_um"].isna().all() else "radius_um"
        ap = sp.landmark.aperture
        end = None
        if ap is not None and (sp.landmark.source.startswith("aperture") or sp.landmark.source == "manual"):
            lm = (sp.landmark.x, sp.landmark.y)
            end = (clockwise_angle(sp.centroid, ap.end) - clockwise_angle(sp.centroid, lm)) % 360
        plot_profile(t, ax_prof, measure, end, title="Radial profile")
    else:
        ax_prof.axis("off")
        ax_prof.text(0.5, 0.5, "No profile (see messages)", ha="center", va="center",
                     color=INK_2, fontsize=10, transform=ax_prof.transAxes)
    _draw_info(fig.add_subplot(gs[1, 1]), sp)
    fig.savefig(out_path, dpi=130, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
