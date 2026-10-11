# Data dictionary

Every column of the output tables. Generated from `ta_morpho/dictionary.py` by
`python -m ta_morpho.dictionary`; do not edit by hand. Empty cells are values that
could not be measured (never estimated). Pixel coordinates are in the original
image: x to the right, y downwards, origin at the top-left pixel. Method
details: `docs/METHODS.md`.

## `summary.csv`

One row per specimen (failed ones included).

| Column | Unit | Meaning |
|---|---|---|
| `image` |  | File name of the image. |
| `genus` |  | Genus, read from the file name (first word after the bar length, if any), or set by hand (then `taxon` is in `corrections`). |
| `species` |  | Species epithet, read from the file name (lower case), or set by hand. |
| `specimen_id` |  | The rest of the file name (e.g. `01`), empty if none. |
| `status` |  | Final status after review: `ok`, `check` (look at the cell figure, reason in `messages`) or `failed` (values left empty). |
| `auto_status` |  | Status before review (the automatic result). |
| `review_note` |  | Note entered when the specimen was accepted in review; empty otherwise. |
| `corrections` |  | What was corrected by hand, separated by `; `: `scale bar`, `bar length`, `outline`, `background type`, `aperture`, `start point`, `fundus`, `holes/bumps`, `taxon`, `characters`. Empty = fully automatic result. |
| `messages` |  | Every flag of every step, `step: message`, separated by ` | `. |
| `software_version` |  | Program version, with the git commit when run from a source folder (`+changes` = files modified since that commit). |
| `bar_length_um` | µm | Length of the scale bar. |
| `bar_length_source` |  | `file name`, `override` (per-image table or Review) or `default` (`calibration.bar_length_um`); empty when px/µm was given directly. |
| `px_per_um` | px/µm | Calibration. Empty: no calibration, every µm value is empty. |
| `calibration_source` |  | `detected` (scale bar found in the image) or `manual` (px/µm given by hand: per-image table, scale drawn in Review, or `calibration.px_per_um` in the settings). |
| `calibration_uncertainty_pct` | % | Error of every length caused by 1 px of error on the bar length (areas: twice this), for a bar detected or drawn by hand. Empty when px/µm was given as a number (no bar measured). |
| `mask_source` |  | `auto` (segmentation) or `manual` (outline drawn by hand). |
| `background` |  | `light` (bright-field) or `dark` (SEM, dark-field); empty for a hand-drawn outline. |
| `background_source` |  | `auto` or `override` (chosen by hand). |
| `smooth_px` | px | Gaussian smoothing of the outline (σ) actually used, from `smooth_um`; 0 = not smoothed (no calibration, or hand-drawn outline). |
| `landmark_source` |  | Start point (ray 0): `aperture` (detected aperture corner), `aperture_corners` (closest pair of sharp corners, round tests), `fallback_max_radius` (furthest outline point), `manual` (aperture corners set by hand), `csv` (start point from `landmarks.csv`), `none` (failed). |
| `centroid_x` | px | Centroid of the mask: mean of the pixel coordinates of the (smoothed) mask; x to the right. |
| `centroid_y` | px | Centroid y (image rows, downwards). |
| `landmark_x` | px | Start landmark x (start aperture corner, by the clockwise rule). |
| `landmark_y` | px | Start landmark y. |
| `aperture_end_x` | px | The other aperture corner x; empty without an aperture. |
| `aperture_end_y` | px | The other aperture corner y. |
| `fundus_x` | px | Fundus (aboral end of the oral–aboral axis) x; empty without an aperture. |
| `fundus_y` | px | Fundus y. |
| `fundus_source` |  | `auto` or `manual`; empty without an aperture. |
| `axis` |  | Frame of length and width: `oral` (oral–aboral axis, from the aperture midpoint through the middle of the far end of the test, or through a fundus set by hand) or `principal` (long axis of the mask, when there is no aperture); empty when nothing was measured. |
| `length_um` | µm | Length along the axis (aperture to fundus, lips included). |
| `width_um` | µm | Largest extent across the axis. |
| `W/L` | ratio | Width / length. |
| `aperture_width_um` | µm | Distance between the two aperture corners. |
| `aperture_angle_deg` | degrees | Angle between the aperture (line between the corners) and the length axis: 90 = square to the axis, smaller = oblique (bent neck; Todorov et al. 2009). |
| `widest_position` | fraction | Level of the widest section from the oral end of the outline ÷ length (0 = oral end, 1 = fundus). |
| `widest_position_aperture` | fraction | Same, from the aperture plane (line between the corners) ÷ distance from that plane to the furthest outline point along the axis (the fundus, unless part of the far end reaches beyond it). |
| `neck_length_um` | µm | Aperture plane to the neck–body junction; empty when the test has no neck. |
| `neck_width_um` | µm | Narrowest section of the neck; empty without a neck. |
| `area_um2` | µm² | Area inside the outline. |
| `perimeter_um` | µm | Length of the outline (sub-pixel outline, pixel staircase smoothed). |
| `circularity` | ratio | 4π area / perimeter² (1 = circle). |
| `solidity` | ratio | Area / convex hull area (oral axis only). |
| `feret_max_um` | µm | Largest caliper diameter (oral axis only). |
| `feret_min_um` | µm | Smallest caliper diameter (oral axis only). |
| `centroid_size_um` | µm | Root of the summed squared distances of the outline-profile points from their centroid (points equally spaced within each stretch, not along the whole outline); depends on `n_points` (METHODS § 8). |
| `AW/L` | ratio | Aperture width / length. |
| `AW/W` | ratio | Aperture width / width. |
| `NL/L` | ratio | Neck length / length. |
| `NW/L` | ratio | Neck width / length. |
| `NL/W` | ratio | Neck length / width. |
| `NW/W` | ratio | Neck width / width. |
| `NL/AW` | ratio | Neck length / aperture width. |
| `NW/AW` | ratio | Neck width / aperture width. |
| `NW/NL` | ratio | Neck width / neck length. |
| `neck_jump` | slope | How distinct the neck is: the largest steepening of the width profile between the aperture and the widest section (the neck criterion, METHODS § 6), given for every test: ≤ 0.5 gradual taper or none (negative when the sides never steepen), 1.3–2 clear neck, > 2 deep constriction. Empty when the widest section is within about a quarter of the length of the aperture. |
| `aperture_sag` | ratio | Curvature of the rim: signed largest distance of the outline between the aperture corners from their chord ÷ aperture width; + = curved (convex) rim, ~0 = straight, − = sunk (METHODS § 7). |
| `n_protrusions` | count | Horns and spines: pieces cut off by the spine opening of the aperture search, longer than twice its radius, beyond 10 % of the axis (METHODS § 7). |
| `protrusion_levels` | fraction | Level of each protrusion along the oral–aboral axis (0 = aperture plane, 1 = fundus), `;`-separated; empty without an aperture. |
| `ch_<character>` |  | Diagnostic character of the specimen (`material`, `plate_shape`, `lateral_pores`, `keel`, `horns_expansions`, `neck`, `aperture_broad`, `aperture_margin`, `aperture_narrow`, `compression`, `fundus_broad`; values in docs/CHARACTERS.md): the genus's value from the monograph, or set by hand. Empty when the genus is not in the table and nothing was set. |
| `characters_by_hand` |  | The characters set by hand, `;`-separated (the others are the genus's). |
| `mean_radius_um` | µm | Mean of the ray radii (the `r…` columns). |
| `radius_cv` | ratio | Standard deviation / mean of the ray radii. |
| `h<k>` | ratio | Amplitude of harmonic k (1 to `n_harmonics`) of the radius around the centroid (fine profile) ÷ mean radius; h2 = elongation, h3 = unequal ends. |
| `symmetry_index` | ratio | Mean |r(axis + θ) − r(axis − θ)| ÷ mean radius, about the line from the centroid to the aperture midpoint (not the oral–aboral axis); 0 = mirror-symmetric. Empty without an aperture. |
| `outline_features` |  | Holes and bumps added by hand: `ok` (listed), `no features` (none added); empty when not measured (no calibration or no aperture). |
| `n_holes` | count | Holes (concave stretches) added by hand; 0 when none was added. |
| `n_bumps` | count | Bumps (convex stretches between two concave runs) added by hand; 0 when none was added. |
| `n_<kind>s_<region>` | count | Holes or bumps per region (`aperture`, `neck`, `junction` — holes only, `body`) or per side of the outline profile (`side1` = end corner to fundus, `side2` = fundus to start corner). Neck and junction empty on a test without a neck. |
| `<kind>_size_sum_<region>_um` | µm | Summed depth (holes) or height (bumps) per region. |
| `f<k>_kind` |  | Feature k (1–5, in outline order from the start landmark): `hole` or `bump`. Empty when there are fewer. |
| `f<k>_position` | fraction | Fraction of the perimeter (0–1), clockwise as displayed from the start landmark. |
| `f<k>_size_um` | µm | Depth of a hole (to its chord) or height of a bump. |
| `f<k>_width_um` | µm | Outline length across the feature. |
| `f<k>_region` |  | `aperture`, `neck`, `junction` or `body` (METHODS § 9). |
| `f<k>_axis_position` | fraction | Level along the oral–aboral axis ÷ level of the fundus (0 = aperture plane, 1 = fundus). |
| `r<angle>` | µm | Radius from the centroid to the outline at this angle, clockwise as displayed from the start landmark (r0 = start). The outermost crossing when a ray crosses the outline several times. |

## `exports/profiles_long.csv`

One row per ray of every specimen.

| Column | Unit | Meaning |
|---|---|---|
| `image` |  | File name of the image. |
| `segment` |  | Ray number (despite the name, not a stretch of the outline): 0 = ray through the start landmark, then clockwise; `angle_deg` = number × angle between rays. |
| `angle_deg` | ° | Angle clockwise (as displayed) from the start landmark. |
| `radius_px` | px | Radius from the centroid to the outline. |
| `radius_um` | µm | Same in µm; empty without calibration. |
| `radius_norm_mean` | ratio | Radius ÷ mean radius of all rays of the specimen (mean over equal angles; compare the outline profile, `d<NNN>` ÷ `mean_distance_um`, a mean over points equally spaced along the outline). |
| `radius_norm_sqrt_area` | ratio | Radius ÷ √(area inside the outline). |
| `n_crossings` | count | Times the ray crosses the outline (0 = none, radius empty). |
| `x` | px | Outline point of the ray (the crossing kept). |
| `y` | px | Same, y (image rows, downwards). |

## `exports/outline_profile.csv`

One row per specimen with an aperture: the aperture- and fundus-anchored outline profile.

| Column | Unit | Meaning |
|---|---|---|
| `image` |  | File name of the image. |
| `genus` |  | Genus, read from the file name (first word after the bar length, if any), or set by hand (then `taxon` is in `corrections`). |
| `species` |  | Species epithet, read from the file name (lower case), or set by hand. |
| `specimen_id` |  | The rest of the file name (e.g. `01`), empty if none. |
| `status` |  | Final status after review: `ok`, `check` (look at the cell figure, reason in `messages`) or `failed` (values left empty). |
| `n_aperture` | count | Points on the aperture stretch (d000 … the last aperture point). |
| `mean_distance_um` | µm | Mean of the distances below. |
| `d<NNN>` | µm | Distance from the centroid to outline-profile point NNN (0-based; point 0 = start aperture corner, then clockwise; anchors in METHODS § 8). |

## `exports/outline_features.csv`

One row per hole or bump added by hand.

| Column | Unit | Meaning |
|---|---|---|
| `image` |  | File name of the image. |
| `genus` |  | Genus, read from the file name (first word after the bar length, if any), or set by hand (then `taxon` is in `corrections`). |
| `species` |  | Species epithet, read from the file name (lower case), or set by hand. |
| `specimen_id` |  | The rest of the file name (e.g. `01`), empty if none. |
| `status` |  | Final status after review: `ok`, `check` (look at the cell figure, reason in `messages`) or `failed` (values left empty). |
| `number` |  | Number of the element within the specimen (outline order). |
| `kind` |  | `hole` or `bump`. |
| `position` | fraction | Fraction of the perimeter (0–1), clockwise as displayed from the start landmark. |
| `size_um` | µm | Depth of a hole or height of a bump. |
| `width_um` | µm | Outline length across the hole or bump. |
| `x` | px | Deepest point of a hole, top of a bump. |
| `y` | px | Same, y. |
| `profile_point` |  | Nearest outline-profile point (0-based, as `d<NNN>`). |
| `stretch` |  | Stretch of the outline profile: `aperture`, `side1`, `side2` (`body` without the fundus anchor). |
| `region` |  | `aperture`, `neck`, `junction` or `body`. |
| `axis_position` | fraction | Level along the oral–aboral axis ÷ level of the fundus. |
| `angle_deg` | ° | Ray angle, clockwise from the start landmark (as `r0 … r355`). |
| `note` |  | Note entered with the hole or bump. |

## `exports/outline_sliders.csv`

Semilandmark definition for geomorph (`outline_coordinates.tps` holds the points).

| Column | Unit | Meaning |
|---|---|---|
| `before` |  | Point before the sliding semilandmark (1-based, closed outline). |
| `slide` |  | Sliding semilandmark (1-based); the fixed anchors are not listed. |
| `after` |  | Point after it. |

