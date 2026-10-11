"""Which settings the interface shows, with labels and help texts.

Each setting shows a plain explanation (PLAIN) followed by its comment in
config.yaml, so the interface and the file never disagree. A few settings
are "basic" (shown first, with friendly labels); all other scalar settings
are "advanced". File locations are not settings: they belong to the project
(input/output folders).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from ta_morpho.export import DEFAULT_CONFIG

SECTION_LABELS = {
    "calibration": "Scale bar",
    "segmentation": "Outline (segmentation)",
    "landmark": "Aperture and start point",
    "rays": "Radial profile",
    "metadata": "File names",
    "outline_profile": "Outline profile",
    "classic": "Classic measurements",
    "features": "Holes and bumps added by hand",
    "descriptors": "Shape descriptors",
}

# (section, key, label) of the settings shown first.
BASIC = [
    ("rays", "angle_step_deg", "Angle between rays (°)"),
    ("calibration", "bar_length_um", "Scale bar length if not in the file name (µm)"),
    ("segmentation", "delta_e_threshold", "Outline contrast threshold (ΔE)"),
    ("segmentation", "smooth_um", "Outline smoothing (µm)"),
    ("outline_profile", "n_points", "Number of outline points"),
]

# Plain-language labels of the advanced settings (help texts come from config.yaml).
LABELS = {
    ("calibration", "px_per_um"): "Fixed calibration for all images (px/µm)",
    ("calibration", "bar_length_range_um"): "Plausible scale bar lengths (µm, min and max)",
    ("calibration", "bar_modes"): "Kinds of scale bar to look for",
    ("calibration", "thresholds.dark"): "Dark bar: threshold (0–255)",
    ("calibration", "thresholds.light"): "Light bar: threshold (0–255)",
    ("calibration", "thresholds.color"): "Coloured bar: saturation threshold (0–255)",
    ("calibration", "min_bar_length_frac"): "Shortest bar (fraction of image width)",
    ("calibration", "min_aspect_ratio"): "Bar: minimum length / thickness",
    ("calibration", "min_extent"): "Bar: minimum rectangularity",
    ("calibration", "min_isolation"): "Bar: plain background around it (fraction)",
    ("calibration", "min_contrast"): "Bar: minimum contrast with background",
    ("calibration", "min_component_share"): "Bar: not part of a letter (share of its shape)",
    ("segmentation", "border_px"): "Image border used for the background (px)",
    ("segmentation", "background_band_um"): "Band used to detect the background type (µm)",
    ("segmentation", "min_background_balance"): "Certainty needed for the background type",
    ("segmentation", "close_radius_um"): "Gap closing in the wall (µm)",
    ("segmentation", "open_radius_um"): "Debris removal (µm)",
    ("segmentation", "min_area_frac"): "Smallest test (fraction of image area)",
    ("segmentation", "max_area_frac"): "Largest test (fraction of image area)",
    ("segmentation", "max_second_object_frac"): "Second object that triggers a check (fraction of the test)",
    ("segmentation", "max_straight_edge_px"): "Longest straight edge before “cropped?” (px)",
    ("segmentation", "edge_band_max_frac"): "Flat band at the image edge: widest (fraction of size)",
    ("segmentation", "edge_band_max_std"): "Flat band at the image edge: colour variation allowed",
    ("segmentation", "edge_line_frac"): "Frame: thin frame line up to (fraction)",
    ("segmentation", "wall_ring_radii_um"): "Pale wall: gap sizes bridged along the wall (µm)",
    ("segmentation", "wall_ring_min_gain"): "Pale wall: minimum growth of the outline",
    ("segmentation", "wall_ring_min_support"): "Pale wall: share of the outline on wall pixels",
    ("segmentation", "wall_ring_delta_e"): "Pale wall: colour difference of a fainter wall (second pass)",
    ("landmark", "snap_tolerance_um"): "Max distance of a given start point to the outline (µm)",
    ("landmark", "min_elongation"): "Minimum elongation to find the aperture by the long axis",
    ("landmark", "end_frac"): "Length fraction used to compare the two ends",
    ("landmark", "max_width_ratio"): "Aperture end: max width ratio narrow / wide end",
    ("landmark", "corner_region_frac"): "Corner search zone near the aperture (fraction)",
    ("landmark", "corner_scale_frac"): "Outline span to measure corner angles (fraction)",
    ("landmark", "min_corner_turn_deg"): "Minimum corner angle (°)",
    ("landmark", "corner_strong_frac"): "Corner choice: strong corners from (x sharpest)",
    ("landmark", "corner_min_lateral_frac"): "Corner choice: min distance from the end's middle (fraction)",
    ("landmark", "spine_opening_frac"): "Spines: cut off thinner than (x test width)",
    ("landmark", "corner_pair_fallback"): "Round tests: aperture from the sharpest corner pair",
    ("landmark", "corner_pair_max_arc_frac"): "Round tests: max distance between the corners (fraction)",
    ("landmark", "fallback"): "No aperture found: start point rule",
    ("landmark", "cut_contact_um"): "Test cut by the border: contact from (µm)",
    ("rays", "intersection"): "Ray crossing the outline several times: use",
    ("metadata", "separator"): "File-name separator (regular expression)",
    ("outline_profile", "n_aperture"): "Outline points across the aperture",
    ("outline_profile", "fundus_anchor"): "Anchor the outline points on the fundus",
    ("classic", "lip_margin"): "Ignored zone next to the aperture (fraction of length)",
    ("classic", "neck_window"): "Neck detection window (fraction of length)",
    ("classic", "min_neck_slope_jump"): "Neck: minimum widening at the junction",
    ("classic", "min_neck_start"): "Neck: minimum distance from the oral end (fraction)",
    ("features", "turn_um"): "Curvature scale and default circle radius (µm)",
    ("features", "flank_um"): "Bump: minimum depth of the dip on each side (µm)",
    ("features", "bump_max_um"): "Added without a circle: maximum bump width (µm)",
    ("calibration", "uncalibrated_px_per_um"): "Resolution assumed for settings when there is no scale (px/µm)",
    ("classic", "section_step_px"): "Spacing of the width sections (px)",
    ("classic", "fundus_far_frac"): "Length axis: share of the largest distance counted as the far end",
    ("features", "step_um"): "Outline resampling step (µm)",
    ("features", "bump_max_frac"): "Added without a circle: maximum bump width (share of the perimeter)",
    ("features", "corner_um"): "Added without a circle: bump this close to an aperture corner = the corner (µm)",
    ("features", "match_pct"): "Added without a circle: search distance (% of perimeter)",
    ("descriptors", "n_harmonics"): "Number of harmonics (h1…)",
    ("segmentation", "close_radius_min_px"): "Gap closing: at least (px)",
    ("segmentation", "open_radius_min_px"): "Debris removal: at least (px)",
    ("segmentation", "background_band_min_px"): "Background-type band: at least (px)",
    ("landmark", "snap_tolerance_min_px"): "Start point distance: at least (px)",
    ("landmark", "cut_contact_min_px"): "Cut by the border: at least (px)",
    ("descriptors", "fine_step_deg"): "Fine profile for harmonics and symmetry (°)",
}

HIDDEN = {("calibration", "overrides_csv"), ("segmentation", "masks_dir"),
          ("segmentation", "background_overrides_csv")}

# Plain-language explanations, shown first in the "?" bubble of each setting
# (the precise, technical note from config.yaml follows, in grey). Written for
# someone who is not a programmer: what it does and when you would change it.
PLAIN = {
    # Basic settings
    ("rays", "angle_step_deg"):
        "The spacing between the measuring rays around the test. 5° gives 72 "
        "rays; a smaller angle means more rays and finer detail. Must divide "
        "360.",
    ("calibration", "bar_length_um"):
        "The real length of the scale bar, in micrometres. Used only when the "
        "length is not given in the image's file name or by a scale drawn by hand.",
    ("segmentation", "delta_e_threshold"):
        "How different from the background a pixel must be to count as part of "
        "the test. Lower catches faint edges but also more noise; higher is "
        "stricter and ignores a faint halo.",
    ("segmentation", "smooth_um"):
        "How much the outline is smoothed, in micrometres. Higher gives a "
        "cleaner outline but rounds off fine detail; 0 turns smoothing off.",
    ("outline_profile", "n_points"):
        "How many equally spaced points describe the outline in the geometric-"
        "morphometrics export. More points = finer shape but larger files.",
    # Scale bar
    ("calibration", "px_per_um"):
        "Pixels per micrometre. Leave empty to read the scale bar on each "
        "image; set a number only if your images have no bar but you know the "
        "calibration — it is then used for every image.",
    ("calibration", "bar_length_range_um"):
        "The shortest and longest scale bar you expect, in micrometres. A number "
        "at the start of a file name (\"20 Nebela collaris\") counts as the bar "
        "length only inside this range, so a date or a counter (\"003_...\") is "
        "not mistaken for one.",
    ("calibration", "bar_modes"):
        "What the scale bar looks like: dark (black), light (white) or colour. "
        "Keep all three unless the program keeps picking the wrong object.",
    ("calibration", "thresholds.dark"):
        "How dark a pixel must be to belong to a black scale bar. Higher = "
        "stricter (only very dark pixels count).",
    ("calibration", "thresholds.light"):
        "How bright a pixel must be to belong to a white scale bar. Higher = "
        "stricter (only very bright pixels count).",
    ("calibration", "thresholds.color"):
        "How vivid a colour must be to belong to a coloured scale bar. Higher "
        "= only strongly coloured bars count.",
    ("calibration", "min_bar_length_frac"):
        "Ignore any candidate bar shorter than this fraction of the image "
        "width. Raise it if small marks are mistaken for the bar.",
    ("calibration", "min_aspect_ratio"):
        "A scale bar is long and thin: how many times longer than thick it "
        "must be. Lower it only for short, stubby bars.",
    ("calibration", "min_extent"):
        "How rectangular the bar must be (1 = a perfect rectangle). Lower it "
        "if your bar has ticks, serifs or rounded ends.",
    ("calibration", "min_isolation"):
        "A scale bar should sit on empty background: how clean the strip just "
        "above or below it must be. Lower it if the bar is near other marks.",
    ("calibration", "min_contrast"):
        "How strongly the bar must stand out from the background (0–255). "
        "Lower it for faint bars.",
    ("calibration", "min_component_share"):
        "Rejects strokes of letters (the bar of a \"4\" in a label): a scale "
        "bar must make up at least this share of the shape it belongs to. "
        "Lower it only if a label drawn on the bar hides it.",
    # Outline (segmentation)
    ("segmentation", "border_px"):
        "Width of the frame around the image used to sample the background "
        "colour. Increase it if that frame contains part of the specimen.",
    ("segmentation", "background_band_um"):
        "Width of the strip just inside the test edge used to decide whether "
        "the background is light or dark. Rarely needs changing.",
    ("segmentation", "min_background_balance"):
        "How clear the light-or-dark background decision must be before it is "
        "trusted. Below this, the image is flagged for you to check.",
    ("segmentation", "close_radius_um"):
        "Bridges small gaps in a faint test wall so the outline closes up. "
        "Increase it if the outline breaks; too high merges nearby debris.",
    ("segmentation", "open_radius_um"):
        "Removes small specks stuck to the test. Increase it to shed debris; "
        "too high eats into real detail.",
    ("segmentation", "min_area_frac"):
        "Ignore detected shapes smaller than this fraction of the image — "
        "usually dirt. Raise it if small debris is kept as a test.",
    ("segmentation", "max_area_frac"):
        "Ignore shapes larger than this fraction of the image. Lower it if the "
        "background is grabbed instead of the test.",
    ("segmentation", "max_second_object_frac"):
        "Only the largest object in the image is measured. If another object is "
        "at least this big compared with it (0.3 = 30 %), for example a second "
        "test or a large piece of debris, the image is marked for checking.",
    ("segmentation", "max_straight_edge_px"):
        "A long, perfectly straight edge usually means the test was cut off by "
        "the image border. Anything longer than this flags the image to check.",
    ("segmentation", "edge_band_max_frac"):
        "A plain coloured band along an image edge (frame of a figure or a "
        "screenshot) is left out and counts as the edge of the image. Bands "
        "wider than this fraction of the image are not removed (0 = never).",
    ("segmentation", "edge_band_max_std"):
        "How uniform a row or column must be to count as such a band (grey "
        "levels). Raise it slightly for JPEG images.",
    ("segmentation", "edge_line_frac"):
        "A thin line along the frame or image edge (the panel's own border around a "
        "drawing), up to this fraction of the image size, clearly darker or lighter "
        "than the background inside it, is left out with the frame. 0 = off.",
    ("segmentation", "wall_ring_radii_um"):
        "On a pale, transparent shell the outline may follow the cell contents "
        "instead of the faint wall. The broken wall line is then closed with "
        "these gap sizes, and the whole shell is kept if the result really lies "
        "on the wall. Empty list = never.",
    ("segmentation", "wall_ring_min_gain"):
        "The whole-shell outline replaces the first one only if it is at least "
        "this many times larger.",
    ("segmentation", "wall_ring_min_support"):
        "Share of the new outline that must lie on visible wall pixels, so that "
        "it follows a real wall and not a gap bridged across the background.",
    ("segmentation", "wall_ring_delta_e"):
        "A second, fainter look for the wall, around the result of the first: "
        "wall pixels need only this colour difference from the background "
        "(lower than the main one). Same conditions apply. Empty = no second pass.",
    # Aperture and start point
    ("landmark", "snap_tolerance_um"):
        "If you supply a start point (by CSV or click), it snaps to the "
        "nearest outline point; if it lands further than this, the image is "
        "flagged.",
    ("landmark", "min_elongation"):
        "How stretched a test must be before the aperture is looked for along "
        "its long axis. Rounder tests use the fallback rule instead.",
    ("landmark", "end_frac"):
        "How much of each end (as a fraction of the length) is measured when "
        "deciding which end is the aperture — the narrower one.",
    ("landmark", "max_width_ratio"):
        "The aperture end must be narrower than the other end by at least this "
        "much. Lower = requires a more obvious taper.",
    ("landmark", "corner_region_frac"):
        "How large a zone near the aperture end is searched for the two "
        "aperture corners.",
    ("landmark", "corner_scale_frac"):
        "Over how much of the outline a corner's sharpness is measured. "
        "Smaller reacts to finer, more local corners.",
    ("landmark", "min_corner_turn_deg"):
        "How sharp the two aperture corners must be, in degrees. Lower it to "
        "accept gentler corners.",
    ("landmark", "corner_strong_frac"):
        "On each side of the aperture, the corner nearest the end is taken among the "
        "corners at least this sharp compared with the sharpest one, so that a bump or "
        "piece of debris further up the side is not taken. 1 = always the sharpest corner.",
    ("landmark", "corner_min_lateral_frac"):
        "An aperture corner must lie at least this far out from the middle of the narrow "
        "end (fraction of its half-width), so the tip of a domed or pointed rim is not "
        "taken as a corner. "
        "0 = off.",
    ("landmark", "spine_opening_frac"):
        "Spines and teeth narrower than a disk of this radius (fraction of the test's "
        "width) are ignored when the corners are searched, so the aperture is placed at "
        "the spine bases. 0 = off. Raise it if spines are still taken as corners; lower "
        "it if a short collar is cut off.",
    ("landmark", "corner_pair_fallback"):
        "For round tests with no clear aperture, use the sharpest pair of "
        "nearby corners (e.g. a collar) as the aperture. These are flagged.",
    ("landmark", "corner_pair_max_arc_frac"):
        "For that round-test fallback, how far apart along the outline the two "
        "corners are allowed to be.",
    ("landmark", "fallback"):
        "What to do when no aperture is found: “max_radius” starts at the "
        "outline point furthest from the centre (flagged); “flag” only marks "
        "the image.",
    ("landmark", "cut_contact_um"):
        "If the test touches the image edge along at least this length, "
        "it is cut off: the aperture may be outside the picture, so it is not "
        "detected automatically. Set the two aperture corners by hand.",
    # Radial profile
    ("rays", "intersection"):
        "If a ray crosses a wavy outline more than once, take the outermost "
        "crossing (“last”) or the innermost (“first”). The image is flagged.",
    # File names
    ("metadata", "separator"):
        "How file names are split into parts (genus, species, scale, id). The "
        "default splits on spaces and underscores; change it only if your "
        "names use another separator.",
    # Outline profile
    ("outline_profile", "n_aperture"):
        "Of the outline points, how many are placed across the aperture; the "
        "rest are spread around the body.",
    ("outline_profile", "fundus_anchor"):
        "Also pin the outline points at the fundus (the end opposite the "
        "aperture) so the left and right sides match between specimens. "
        "Recommended on.",
    # Classic measurements
    ("classic", "lip_margin"):
        "A strip next to the aperture opening that is skipped when measuring "
        "widths, so the lip does not distort them.",
    ("classic", "neck_window"):
        "How wide a window along the length is used to spot where a neck "
        "widens into the body.",
    ("classic", "min_neck_slope_jump"):
        "How sharply the test must widen to count as a neck-to-body junction. "
        "Higher = only obvious necks are detected.",
    ("classic", "min_neck_start"):
        "A neck junction must be at least this far from the oral end of the test "
        "(as a fraction of the length). The junction is only searched from twice "
        "the neck detection window on (0.16 with the default window), so a smaller "
        "value has no effect.",
    # Holes and bumps (added by hand)
    ("features", "turn_um"):
        "Holes and bumps are added by hand (tab Correct on the image: Add hole "
        "/ Add bump). This is the radius of the circle of a new one, and the "
        "stretch of outline over which curvature is measured to find the dips "
        "on each side of a bump.",
    ("features", "flank_um"):
        "When a bump is measured inside its circle, the dips on each side "
        "must be at least this deep to serve as its base; otherwise the ends "
        "of the circle are used.",
    ("features", "step_um"):
        "Distance between the points along the outline where an added hole "
        "or bump is measured. Smaller is finer but slower.",
    ("features", "match_pct"):
        "Only for a hole/bump written in a corrections CSV with its centre "
        "but no circle: the nearest hole or bump within this share of the "
        "outline length is measured.",
    ("features", "bump_max_um"):
        "Only for a bump added without a circle (CSV): anything wider than "
        "this is part of the body, not a bump.",
    ("features", "bump_max_frac"):
        "Only for a bump added without a circle (CSV): it cannot be wider "
        "than this share of the whole outline.",
    ("features", "corner_um"):
        "Only for a bump added without a circle (CSV): a bump this close to "
        "an aperture corner is the corner itself.",
    ("calibration", "uncalibrated_px_per_um"):
        "Settings in micrometres need the image scale. For an image without "
        "a scale they are converted with this resolution instead; its results "
        "in micrometres stay empty.",
    ("classic", "section_step_px"):
        "Spacing, in pixels, of the cross-sections used to measure widths "
        "along the test. Rarely needs changing.",
    ("classic", "fundus_far_frac"):
        "The length axis runs from the middle of the aperture to the middle of "
        "the far end of the test: the part of the outline within this share of "
        "the largest distance from the aperture, spines and horns left out. A "
        "fundus set by hand takes the place of that middle point; the rule is "
        "the same. The aperture angle gives the tilt of the aperture to that "
        "axis (as in Todorov et al. 2009).",
    ("descriptors", "n_harmonics"):
        "How many harmonics of the outline are given (h1, h2, …): h2 measures "
        "elongation, h3 pear shape.",
    ("segmentation", "close_radius_min_px"):
        "On low-resolution images the setting in micrometres would be only one "
        "or two pixels, finer than the image noise: it is never taken below "
        "this many pixels.",
    ("segmentation", "open_radius_min_px"):
        "On low-resolution images the setting in micrometres would be only one "
        "or two pixels, finer than the image noise: it is never taken below "
        "this many pixels.",
    ("segmentation", "background_band_min_px"):
        "On low-resolution images the setting in micrometres would be only one "
        "or two pixels, finer than the image noise: it is never taken below "
        "this many pixels.",
    ("landmark", "snap_tolerance_min_px"):
        "On low-resolution images the setting in micrometres would be only one "
        "or two pixels, finer than the image noise: it is never taken below "
        "this many pixels.",
    ("landmark", "cut_contact_min_px"):
        "On low-resolution images the setting in micrometres would be only one "
        "or two pixels, finer than the image noise: it is never taken below "
        "this many pixels.",
    ("descriptors", "fine_step_deg"):
        "Angle between the fine rays used for the harmonics and the symmetry "
        "index, independent of the angle between the exported rays. Must "
        "divide 360.",
}


# What a setting accepts. A value outside makes the run stop or every image fail, so the
# Settings page offers only these (lists to choose from, spin box limits) and a run checks
# them first (problems()). Numbers: (lowest, highest, lowest itself allowed). Settings not
# listed take any number from 0; the ones whose name ends in _frac, 0 to 1.
CHOICES = {("rays", "intersection"): ("last", "first"),
           ("landmark", "fallback"): ("max_radius", "flag")}
LIST_CHOICES = {("calibration", "bar_modes"): ("dark", "light", "color")}
LIMITS = {
    ("rays", "angle_step_deg"): (0, 90, False),
    ("descriptors", "fine_step_deg"): (0, 90, False),          # and must divide 360
    ("descriptors", "n_harmonics"): (1, 50, True),
    ("outline_profile", "n_points"): (8, 10_000, True),
    ("outline_profile", "n_aperture"): (2, 10_000, True),       # and below n_points - 2
    ("calibration", "bar_length_um"): (0, 1e6, False),
    ("calibration", "px_per_um"): (0, 1e6, False),
    ("calibration", "uncalibrated_px_per_um"): (0, 1e6, False),
    ("calibration", "thresholds.dark"): (0, 255, True),
    ("calibration", "thresholds.light"): (0, 255, True),
    ("calibration", "thresholds.color"): (0, 255, True),
    ("calibration", "min_contrast"): (0, 255, True),
    ("calibration", "min_extent"): (0, 1, True),
    ("calibration", "min_isolation"): (0, 1, True),
    ("calibration", "min_component_share"): (0, 1, True),
    ("segmentation", "min_background_balance"): (0, 1, True),
    ("segmentation", "wall_ring_min_support"): (0, 1, True),
    ("classic", "lip_margin"): (0, 1, True),
    ("classic", "neck_window"): (0, 1, False),
    ("classic", "section_step_px"): (0, 1e6, False),
    ("features", "step_um"): (0, 1e6, False),
    ("features", "turn_um"): (0, 1e6, False),
}


def limits(section: str, key: str) -> tuple[float, float, bool]:
    """(lowest, highest, lowest itself allowed) of a number setting."""
    if (section, key) in LIMITS:
        return LIMITS[(section, key)]
    return (0, 1, True) if key.endswith("_frac") else (0, 1e6, True)


def problems(settings: dict) -> list[str]:
    """Plain messages for every setting a run cannot use ([] when all are fine)."""
    out = []
    basic, advanced = all_settings(settings)
    for st in basic + advanced:
        v, name = st.default, f"“{st.label}” ({st.section}.{st.key})"
        if (st.section, st.key) in CHOICES and v not in CHOICES[(st.section, st.key)]:
            out.append(f"{name} must be one of {', '.join(CHOICES[(st.section, st.key)])}, not “{v}”")
        elif (st.section, st.key) in LIST_CHOICES:
            bad = [m for m in v or [] if m not in LIST_CHOICES[(st.section, st.key)]]
            if bad or not v:
                out.append(f"{name}: choose among {', '.join(LIST_CHOICES[(st.section, st.key)])}"
                           + (f", not “{bad[0]}”" if bad else ""))
        elif isinstance(v, (bool, str)) or v is None:
            continue
        elif isinstance(v, (int, float)):
            lo, hi, closed = limits(st.section, st.key)
            if not math.isfinite(v) or v > hi or v < lo or (v == lo and not closed):
                out.append(f"{name} must be {'at least' if closed else 'more than'} {lo:g} "
                           f"and at most {hi:g}, not {v:g}")
        elif isinstance(v, list) and any(not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
                                         for x in v):
            out.append(f"{name}: positive numbers only")
    get = lambda s, k: get_value(settings, s, k)   # noqa: E731
    # Both ray spacings must close the circle: otherwise the last ray falls short of
    # 360° and the ray labels (r0, r5…) no longer match between the two sides.
    for (section, key), label in ((("rays", "angle_step_deg"), BASIC[0][2]),
                                  (("descriptors", "fine_step_deg"), LABELS[("descriptors", "fine_step_deg")])):
        step = get(section, key)
        if isinstance(step, (int, float)) and not isinstance(step, bool) and math.isfinite(step) and step > 0 \
                and abs(360 / step - round(360 / step)) > 1e-9:
            out.append(f"“{label}” must divide 360 (e.g. 0.5, 1, 2, 5), not {step:g}")
    n, na = get("outline_profile", "n_points"), get("outline_profile", "n_aperture")
    if isinstance(n, int) and isinstance(na, int) and not 2 <= na < n - 2:
        out.append(f"“{LABELS[('outline_profile', 'n_aperture')]}” must be below the number of outline "
                   f"points minus 2 ({n - 3} at most), not {na}")
    rng = get("calibration", "bar_length_range_um")
    if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, (int, float)) for x in rng)
            and 0 < rng[0] < rng[1]):
        out.append(f"“{LABELS[('calibration', 'bar_length_range_um')]}”: two numbers, the smaller first "
                   "(e.g. 5, 500)")
    sep = get("metadata", "separator")
    try:
        if not sep or re.compile(sep).match(""):     # empty, or would split between every letter
            raise re.error("empty match")
    except (re.error, TypeError):
        out.append(f"“{LABELS[('metadata', 'separator')]}” is not a usable regular expression: “{sep}” "
                   "(default: [_\\s]+, underscores and spaces)")
    return out


@dataclass
class Setting:
    section: str
    key: str
    label: str
    help: str
    default: object
    plain: str = ""

    @property
    def kind(self) -> str:
        """bool, int, float, optional_float, list or str."""
        d = self.default
        if isinstance(d, bool):
            return "bool"
        if isinstance(d, int):
            return "int"
        if isinstance(d, float):
            return "float"
        if d is None:
            return "optional_float"
        if isinstance(d, list):
            return "list"
        return "str"


def parse_help(text: str) -> dict[tuple[str, str], str]:
    """Comments of a config.yaml written as in this project: the comment lines
    just above a key, plus its inline comment, keyed by (section, key); nested
    keys as (section, "parent.key"). A key
    with no comment of its own gets the comment block of its group (the keys
    that follow one block without a blank line)."""
    helps, pending, block, section, parent = {}, [], "", None, None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            pending, block = [], ""
            continue
        if s.startswith("#"):
            pending.append(s.lstrip("#").strip())
            continue
        m = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if not m:
            pending = []
            continue
        indent, key, rest = m.groups()
        inline = rest.split(" #", 1)[1].strip() if " #" in rest else ""
        if not indent:
            section, block = key, ""
        else:
            if pending:
                block = " ".join(pending)
            own = " ".join(pending + ([inline] if inline else [])).strip()
            if len(indent) <= 2:
                parent = key
                helps[(section, key)] = own or block
            else:                                   # nested key, e.g. thresholds.dark
                helps[(section, f"{parent}.{key}")] = own or helps.get((section, parent), "")
        pending = []
    return helps


def _humanise(key: str) -> str:
    words = key.replace("_um", " (µm)").replace("_px", " (px)").replace("_deg", " (°)").replace("_", " ")
    return words[0].upper() + words[1:]


def all_settings(defaults: dict, config_text: str | None = None) -> tuple[list[Setting], list[Setting]]:
    """(basic, advanced) settings described from the default configuration."""
    text = config_text if config_text is not None else Path(DEFAULT_CONFIG).read_text(encoding="utf-8")
    helps = parse_help(text)
    basic_labels = {(s, k): label for s, k, label in BASIC}
    labels = {**LABELS, **basic_labels}
    basic, advanced = [], []
    for section, values in defaults.items():
        if not isinstance(values, dict):
            continue
        flat = {}
        for key, value in values.items():
            if isinstance(value, dict):                     # one level of nesting
                flat.update({f"{key}.{k}": v for k, v in value.items()})
            else:
                flat[key] = value
        for key, value in flat.items():
            if (section, key) in HIDDEN:
                continue
            st = Setting(section, key, labels.get((section, key), _humanise(key)),
                         helps.get((section, key), ""), value,
                         plain=PLAIN.get((section, key), ""))
            (basic if (section, key) in basic_labels else advanced).append(st)
    order = {(s, k): i for i, (s, k, _) in enumerate(BASIC)}
    basic.sort(key=lambda st: order[(st.section, st.key)])
    return basic, advanced


def get_value(settings: dict, section: str, key: str, default=None):
    """Value of a setting; ``key`` may be nested ("thresholds.dark")."""
    node = settings.get(section, {})
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_value(settings: dict, section: str, key: str, value) -> None:
    node = settings.setdefault(section, {})
    *parents, last = key.split(".")
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value


def parse_value(setting: Setting, text: str):
    """Convert the text typed for a list / optional setting to its value."""
    if setting.kind == "optional_float":
        return float(text) if text.strip() else None
    if setting.kind == "list":
        items = [t.strip() for t in text.split(",") if t.strip()]
        sample = setting.default[0] if setting.default else ""
        if isinstance(sample, bool):
            return [t.lower() in ("1", "true", "yes") for t in items]
        if isinstance(sample, int):
            return [int(t) for t in items]
        if isinstance(sample, float):
            return [float(t) for t in items]
        return items
    return text
