"""Data dictionary: every column of every output table, with its unit and
meaning, and the table of settings. ``python -m ta_morpho.dictionary`` writes them
to ``docs/DATA_DICTIONARY.md`` and ``docs/PARAMETERS.md``.

A column name in <angle brackets> stands for a family of columns, matched by
the regular expression given with it.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Column:
    name: str
    unit: str
    meaning: str
    pattern: str = ""            # regular expression for a family of columns

    def matches(self, column: str) -> bool:
        return re.fullmatch(self.pattern or re.escape(self.name), column) is not None


STATUS = "`ok`, `check` (look at the cell figure, reason in `messages`) or `failed` (values left empty)"
ID = [
    Column("image", "", "File name of the image."),
    Column("genus", "", "Genus, read from the file name (first word after the bar length, if any), or set "
                        "by hand (then `taxon` is in `corrections`)."),
    Column("species", "", "Species epithet, read from the file name (lower case), or set by hand."),
    Column("specimen_id", "", "The rest of the file name (e.g. `01`), empty if none."),
    Column("status", "", f"Final status after review: {STATUS}."),
]
POSITION = ("Fraction of the perimeter (0–1), clockwise as displayed from the start landmark.")

SUMMARY = ID + [
    Column("auto_status", "", "Status before review (the automatic result)."),
    Column("review_note", "", "Note entered when the specimen was accepted in review; empty otherwise."),
    Column("corrections", "", "What was corrected by hand, separated by `; `: `scale bar`, `bar length`, "
                              "`outline`, `background type`, `aperture`, `start point`, `fundus`, "
                              "`holes/bumps`, `taxon`, `characters`. Empty = fully automatic result."),
    Column("messages", "", "Every flag of every step, `step: message`, separated by ` | `."),
    Column("software_version", "", "Program version, with the git commit when run from a source folder "
                                   "(`+changes` = files modified since that commit)."),
    Column("bar_length_um", "µm", "Length of the scale bar."),
    Column("bar_length_source", "", "`file name`, `override` (per-image table or Review) or `default` "
                                    "(`calibration.bar_length_um`); empty when px/µm was given directly."),
    Column("px_per_um", "px/µm", "Calibration. Empty: no calibration, every µm value is empty."),
    Column("calibration_source", "", "`detected` (scale bar found in the image) or `manual` (px/µm given "
                                     "by hand: per-image table, scale drawn in Review, or "
                                     "`calibration.px_per_um` in the settings)."),
    Column("calibration_uncertainty_pct", "%", "Error of every length caused by 1 px of error on the bar "
                                               "length (areas: twice this), for a bar detected or drawn by "
                                               "hand. Empty when px/µm was given as a number (no bar measured)."),
    Column("mask_source", "", "`auto` (segmentation) or `manual` (outline drawn by hand)."),
    Column("background", "", "`light` (bright-field) or `dark` (SEM, dark-field); empty for a hand-drawn outline."),
    Column("background_source", "", "`auto` or `override` (chosen by hand)."),
    Column("smooth_px", "px", "Gaussian smoothing of the outline (σ) actually used, from `smooth_um`; "
                              "0 = not smoothed (no calibration, or hand-drawn outline)."),
    Column("landmark_source", "", "Start point (ray 0): `aperture` (detected aperture corner), "
                                  "`aperture_corners` (closest pair of sharp corners, round tests), "
                                  "`fallback_max_radius` (furthest outline point), `manual` (aperture "
                                  "corners set by hand), `csv` (start point from `landmarks.csv`), "
                                  "`none` (failed)."),
    Column("centroid_x", "px", "Centroid of the mask: mean of the pixel coordinates of the (smoothed) "
                               "mask; x to the right."),
    Column("centroid_y", "px", "Centroid y (image rows, downwards)."),
    Column("landmark_x", "px", "Start landmark x (start aperture corner, by the clockwise rule)."),
    Column("landmark_y", "px", "Start landmark y."),
    Column("aperture_end_x", "px", "The other aperture corner x; empty without an aperture."),
    Column("aperture_end_y", "px", "The other aperture corner y."),
    Column("fundus_x", "px", "Fundus (aboral end of the oral–aboral axis) x; empty without an aperture."),
    Column("fundus_y", "px", "Fundus y."),
    Column("fundus_source", "", "`auto` or `manual`; empty without an aperture."),
    Column("axis", "", "Frame of length and width: `oral` (oral–aboral axis, from the aperture "
                       "midpoint through the middle of the far end of the test, or through a fundus set by "
                       "hand) or "
                       "`principal` (long axis of the mask, when there is no aperture); empty when nothing "
                       "was measured."),
    Column("length_um", "µm", "Length along the axis (aperture to fundus, lips included)."),
    Column("width_um", "µm", "Largest extent across the axis."),
    Column("W/L", "ratio", "Width / length."),
    Column("aperture_width_um", "µm", "Distance between the two aperture corners."),
    Column("aperture_angle_deg", "degrees", "Angle between the aperture (line between the corners) and the "
                                            "length axis: 90 = square to the axis, smaller = oblique "
                                            "(bent neck; Todorov et al. 2009)."),
    Column("widest_position", "fraction", "Level of the widest section from the oral end of the "
                                          "outline ÷ length (0 = oral end, 1 = fundus)."),
    Column("widest_position_aperture", "fraction", "Same, from the aperture plane (line between the "
                                                   "corners) ÷ distance from that plane to the furthest "
                                                   "outline point along the axis (the fundus, unless part "
                                                   "of the far end reaches beyond it)."),
    Column("neck_length_um", "µm", "Aperture plane to the neck–body junction; empty when the test has no neck."),
    Column("neck_width_um", "µm", "Narrowest section of the neck; empty without a neck."),
    Column("area_um2", "µm²", "Area inside the outline."),
    Column("perimeter_um", "µm", "Length of the outline (sub-pixel outline, pixel staircase smoothed)."),
    Column("circularity", "ratio", "4π area / perimeter² (1 = circle)."),
    Column("solidity", "ratio", "Area / convex hull area (oral axis only)."),
    Column("feret_max_um", "µm", "Largest caliper diameter (oral axis only)."),
    Column("feret_min_um", "µm", "Smallest caliper diameter (oral axis only)."),
    Column("centroid_size_um", "µm", "Root of the summed squared distances of the outline-profile points "
                                     "from their centroid (points equally spaced within each stretch, not "
                                     "along the whole outline); depends on `n_points` (METHODS § 8)."),
    *[Column(r, "ratio", f"{a} / {b}.") for r, a, b in (
        ("AW/L", "Aperture width", "length"), ("AW/W", "Aperture width", "width"),
        ("NL/L", "Neck length", "length"), ("NW/L", "Neck width", "length"),
        ("NL/W", "Neck length", "width"), ("NW/W", "Neck width", "width"),
        ("NL/AW", "Neck length", "aperture width"), ("NW/AW", "Neck width", "aperture width"),
        ("NW/NL", "Neck width", "neck length"))],
    Column("neck_jump", "slope", "How distinct the neck is: the largest steepening of the width profile "
                                "between the aperture and the widest section (the neck criterion, "
                                "METHODS § 6), given for every test: ≤ 0.5 gradual taper or none (negative "
                                "when the sides never steepen), 1.3–2 clear neck, > 2 deep constriction. "
                                "Empty when the widest section is within about a quarter of the length "
                                "of the aperture."),
    Column("aperture_sag", "ratio", "Curvature of the rim: signed largest distance of the outline between "
                                    "the aperture corners from their chord ÷ aperture width; + = curved "
                                    "(convex) rim, ~0 = straight, − = sunk (METHODS § 7)."),
    Column("n_protrusions", "count", "Horns and spines: pieces cut off by the spine opening of the aperture "
                                     "search, longer than twice its radius, beyond 10 % of the axis "
                                     "(METHODS § 7)."),
    Column("protrusion_levels", "fraction", "Level of each protrusion along the oral–aboral axis (0 = aperture "
                                            "plane, 1 = fundus), `;`-separated; empty without an aperture."),
    Column("ch_<character>", "", "Diagnostic character of the specimen (`material`, `plate_shape`, "
                                 "`lateral_pores`, `keel`, `horns_expansions`, `neck`, `aperture_broad`, "
                                 "`aperture_margin`, `aperture_narrow`, `compression`, `fundus_broad`; values "
                                 "in docs/CHARACTERS.md): the genus's value from the monograph, or set by hand. "
                                 "Empty when the genus is not in the table and nothing was set.",
           r"ch_(material|plate_shape|lateral_pores|keel|horns_expansions|neck|aperture_broad|"
           r"aperture_margin|aperture_narrow|compression|fundus_broad)"),
    Column("characters_by_hand", "", "The characters set by hand, `;`-separated (the others are the genus's)."),
    Column("mean_radius_um", "µm", "Mean of the ray radii (the `r…` columns)."),
    Column("radius_cv", "ratio", "Standard deviation / mean of the ray radii."),
    Column("h<k>", "ratio", "Amplitude of harmonic k (1 to `n_harmonics`) of the radius around the centroid "
                            "(fine profile) ÷ mean radius; h2 = elongation, h3 = unequal ends.", r"h\d+"),
    Column("symmetry_index", "ratio", "Mean |r(axis + θ) − r(axis − θ)| ÷ mean radius, about the line from "
                                      "the centroid to the aperture midpoint (not the oral–aboral axis); "
                                      "0 = mirror-symmetric. Empty without an aperture."),
    Column("outline_features", "", "Holes and bumps added by hand: `ok` (listed), `no features` (none "
                                   "added); empty when not measured (no calibration or no aperture)."),
    Column("n_holes", "count", "Holes (concave stretches) added by hand; 0 when none was added."),
    Column("n_bumps", "count", "Bumps (convex stretches between two concave runs) added by hand; 0 when "
                               "none was added."),
    Column("n_<kind>s_<region>", "count", "Holes or bumps per region (`aperture`, `neck`, `junction` — holes "
                                          "only, `body`) or per side of the outline profile (`side1` = end "
                                          "corner to fundus, `side2` = fundus to start corner). Neck and "
                                          "junction empty on a test without a neck.",
           r"n_(holes|bumps)_(aperture|neck|junction|body|side1|side2)"),
    Column("<kind>_size_sum_<region>_um", "µm", "Summed depth (holes) or height (bumps) per region.",
           r"(hole|bump)_size_sum_(neck|junction|body)_um"),
    Column("f<k>_kind", "", "Feature k (1–5, in outline order from the start landmark): `hole` or `bump`. "
                            "Empty when there are fewer.", r"f\d+_kind"),
    Column("f<k>_position", "fraction", POSITION, r"f\d+_position"),
    Column("f<k>_size_um", "µm", "Depth of a hole (to its chord) or height of a bump.", r"f\d+_size_um"),
    Column("f<k>_width_um", "µm", "Outline length across the feature.", r"f\d+_width_um"),
    Column("f<k>_region", "", "`aperture`, `neck`, `junction` or `body` (METHODS § 9).", r"f\d+_region"),
    Column("f<k>_axis_position", "fraction", "Level along the oral–aboral axis ÷ level of the fundus "
                                             "(0 = aperture plane, 1 = fundus).", r"f\d+_axis_position"),
    Column("r<angle>", "µm", "Radius from the centroid to the outline at this angle, clockwise as displayed "
                             "from the start landmark (r0 = start). The outermost crossing when a ray "
                             "crosses the outline several times.", r"r\d+(\.\d+)?"),
]

PROFILES_LONG = [
    Column("image", "", "File name of the image."),
    Column("segment", "", "Ray number (despite the name, not a stretch of the outline): 0 = ray through "
                          "the start landmark, then clockwise; `angle_deg` = number × angle between rays."),
    Column("angle_deg", "°", "Angle clockwise (as displayed) from the start landmark."),
    Column("radius_px", "px", "Radius from the centroid to the outline."),
    Column("radius_um", "µm", "Same in µm; empty without calibration."),
    Column("radius_norm_mean", "ratio", "Radius ÷ mean radius of all rays of the specimen (mean over "
                                        "equal angles; compare the outline profile, `d<NNN>` ÷ "
                                        "`mean_distance_um`, a mean over points equally spaced along "
                                        "the outline)."),
    Column("radius_norm_sqrt_area", "ratio", "Radius ÷ √(area inside the outline)."),
    Column("n_crossings", "count", "Times the ray crosses the outline (0 = none, radius empty)."),
    Column("x", "px", "Outline point of the ray (the crossing kept)."),
    Column("y", "px", "Same, y (image rows, downwards)."),
]

OUTLINE_PROFILE = ID + [
    Column("n_aperture", "count", "Points on the aperture stretch (d000 … the last aperture point)."),
    Column("mean_distance_um", "µm", "Mean of the distances below."),
    Column("d<NNN>", "µm", "Distance from the centroid to outline-profile point NNN (0-based; point 0 = start "
                           "aperture corner, then clockwise; anchors in METHODS § 8).", r"d\d{3}"),
]

OUTLINE_SLIDERS = [
    Column("before", "", "Point before the sliding semilandmark (1-based, closed outline)."),
    Column("slide", "", "Sliding semilandmark (1-based); the fixed anchors are not listed."),
    Column("after", "", "Point after it."),
]

OUTLINE_FEATURES = ID + [
    Column("number", "", "Number of the element within the specimen (outline order)."),
    Column("kind", "", "`hole` or `bump`."),
    Column("position", "fraction", POSITION),
    Column("size_um", "µm", "Depth of a hole or height of a bump."),
    Column("width_um", "µm", "Outline length across the hole or bump."),
    Column("x", "px", "Deepest point of a hole, top of a bump."),
    Column("y", "px", "Same, y."),
    Column("profile_point", "", "Nearest outline-profile point (0-based, as `d<NNN>`)."),
    Column("stretch", "", "Stretch of the outline profile: `aperture`, `side1`, `side2` (`body` without "
                          "the fundus anchor)."),
    Column("region", "", "`aperture`, `neck`, `junction` or `body`."),
    Column("axis_position", "fraction", "Level along the oral–aboral axis ÷ level of the fundus."),
    Column("angle_deg", "°", "Ray angle, clockwise from the start landmark (as `r0 … r355`)."),
    Column("note", "", "Note entered with the hole or bump."),
]

TABLES = {
    "summary.csv": (SUMMARY, "One row per specimen (failed ones included)."),
    "exports/profiles_long.csv": (PROFILES_LONG, "One row per ray of every specimen."),
    "exports/outline_profile.csv": (OUTLINE_PROFILE, "One row per specimen with an aperture: the "
                                                     "aperture- and fundus-anchored outline profile."),
    "exports/outline_features.csv": (OUTLINE_FEATURES, "One row per hole or bump added by hand."),
    "exports/outline_sliders.csv": (OUTLINE_SLIDERS, "Semilandmark definition for geomorph "
                                                     "(`outline_coordinates.tps` holds the points)."),
}


def undocumented(table: str, columns) -> list[str]:
    """Columns of an output table that no entry of the dictionary describes."""
    entries = TABLES[table][0]
    return [c for c in columns if not any(e.matches(c) for e in entries)]


def markdown() -> str:
    """The data dictionary as a Markdown document."""
    out = ["# Data dictionary", "",
           "Every column of the output tables. Generated from `ta_morpho/dictionary.py` by",
           "`python -m ta_morpho.dictionary`; do not edit by hand. Empty cells are values that",
           "could not be measured (never estimated). Pixel coordinates are in the original",
           "image: x to the right, y downwards, origin at the top-left pixel. Method",
           "details: `docs/METHODS.md`.", ""]
    for table, (entries, what) in TABLES.items():
        out += [f"## `{table}`", "", what, "", "| Column | Unit | Meaning |", "|---|---|---|"]
        out += [f"| `{e.name}` | {e.unit} | {e.meaning} |" for e in entries]
        out.append("")
    return "\n".join(out)


# ----- settings ----------------------------------------------------------------
UNITS = (("px_per_um", "px/µm"), ("_um2", "µm²"), ("_um", "µm"), ("_px", "px"), ("_deg", "°"),
         ("_pct", "%"), ("_frac", "fraction"))


def _unit(key: str) -> str:
    return next((u for suffix, u in UNITS if key.endswith(suffix)), "")


def parameters_markdown(config_text: str) -> str:
    """The settings of a config.yaml as a Markdown table per section: value,
    unit and the comment written above it in the file (what it does, why this
    value). File locations are left out."""
    import yaml

    from ta_morpho.gui.settings import HIDDEN, SECTION_LABELS, parse_help
    helps, config = parse_help(config_text), yaml.safe_load(config_text)
    out = ["# Parameters", "",
           "Every setting of `ta_morpho/config.yaml` with its default value. Generated from its",
           "comments by `python -m ta_morpho.dictionary`; do not edit by hand. A run records the",
           "values it used in `.pipeline/config_used.yaml` of its results folder.", ""]
    for section, values in config.items():
        if section == "paths" or not isinstance(values, dict):
            continue
        out += [f"## {SECTION_LABELS.get(section, section)} (`{section}`)", "",
                "| Setting | Value | Unit | What it does and why |", "|---|---|---|---|"]
        flat = {}
        for key, value in values.items():
            if isinstance(value, dict):
                flat.update({f"{key}.{k}": v for k, v in value.items()})
            else:
                flat[key] = value
        previous = None
        for key, value in flat.items():
            if (section, key) in HIDDEN or key.endswith("_csv") or key.endswith("_dir"):
                continue
            shown = yaml.safe_dump(value, default_flow_style=True).strip().removesuffix("...").strip()
            text = helps.get((section, key), "").replace("|", "\\|").replace("<", "&lt;")
            text, previous = ("〃 (same note as above)" if text and text == previous else text), text
            out.append(f"| `{key}` | `{shown}` | {_unit(key.split('.')[-1])} | {text} |")
        out.append("")
    return "\n".join(out)


def write_docs(docs: Path) -> None:
    """Write ``DATA_DICTIONARY.md`` and ``PARAMETERS.md`` into the folder ``docs``."""
    from ta_morpho.export import DEFAULT_CONFIG
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "DATA_DICTIONARY.md").write_text(markdown() + "\n", encoding="utf-8")
    (docs / "PARAMETERS.md").write_text(parameters_markdown(DEFAULT_CONFIG.read_text(encoding="utf-8")) + "\n",
                                        encoding="utf-8")


if __name__ == "__main__":
    write_docs(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs"))
