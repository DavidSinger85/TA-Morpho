# Parameters

Every setting of `ta_morpho/config.yaml` with its default value. Generated from its
comments by `python -m ta_morpho.dictionary`; do not edit by hand. A run records the
values it used in `.pipeline/config_used.yaml` of its results folder.

## Scale bar (`calibration`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `bar_length_um` | `25.0` | µm | Default physical length of the scale bar, used only when neither the file name nor calibration_overrides.csv gives one (picture flagged "check"). |
| `bar_length_range_um` | `[5, 500]` | µm | Plausible bar lengths (µm). A bare leading number in the file name ("20 Nebela collaris") is read as the bar length only inside this range (so a date or counter such as "003_..." is not); a length with a unit ("3um") outside it is used but flagged "check". |
| `px_per_um` | `null` | px/µm | If set (a number), no scale bar is searched: this value is used for every picture that has no px_per_um of its own in overrides_csv. |
| `uncalibrated_px_per_um` | `7.0` | px/µm | Settings given in µm (&lt;name>_um: morphology, wall band, snapping, cut contact) are converted to pixels with each picture's calibration, but never below &lt;name>_min_px (on low-resolution pictures a finer setting would go below the pixel noise). A picture without calibration uses this resolution instead (its µm results stay empty). |
| `bar_modes` | `[dark, light, color]` |  | Kinds of bar to look for: dark (black), light (white), color (any saturated colour, e.g. red/yellow). |
| `thresholds.dark` | `175` |  | Threshold on each mode's feature image (0-255, bar pixels are above): dark  -> 255 - grey  (175 means grey &lt; 80) light -> grey color -> HSV saturation |
| `thresholds.light` | `200` |  | 〃 (same note as above) |
| `thresholds.color` | `100` |  | 〃 (same note as above) |
| `min_bar_length_frac` | `0.05` | fraction | Width of the horizontal opening kernel, as a fraction of picture width. Removes text glyphs (e.g. the "µ" descender) touching the bar. The bar must be longer than this. |
| `min_aspect_ratio` | `3.0` |  | Shape filters for candidate bars. length / thickness; 3 accepts short thick bars of small pictures (e.g. 48 x 15 px), letters are rejected by min_component_share. |
| `min_extent` | `0.85` |  | area / bounding-box area (rectangularity) |
| `min_isolation` | `0.9` |  | Background check: a bar must lie on plain background on at least one side (fraction of background pixels in the band above or below) ... |
| `min_contrast` | `80` |  | ... and differ from the background beyond its ends by this much (0-255). |
| `min_component_share` | `0.5` |  | Share of its connected shape (before the opening) that the bar must make up: a bar is its own shape (a touching label adds a little); the bar of a letter such as "4" is a small part of the letter. |

## Outline (segmentation) (`segmentation`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `border_px` | `10` | px | Width of the picture frame used to estimate the background colour (px: a property of the picture, not of the specimen). |
| `delta_e_threshold` | `15.0` |  | A pixel is "test" if its colour differs from the background by more than this (CIE76 ΔE; ~2 = just noticeable, 10 = clearly different). 15 ignores the faint glow along edges in SEM pictures. |
| `background_band_um` | `1.4` | µm | Background type, detected per picture: "light" (dark test on a pale background, bright-field light microscopy) or "dark" (bright test on a dark background, SEM / dark-field). On a light background only pixels darker than the background (or of another colour) count as test, which leaves out the bright halo outside the wall. Decided on a band this wide (µm, at least _min_px) inside the edge of a first rough mask (the wall): balance = share of band pixels darker than the background minus share lighter (by more than delta_e_threshold in L*), -1 to +1. \|balance\| below min_background_balance -> type uncertain: the general "dark" rule is used and the picture flagged. |
| `background_band_min_px` | `10` | px | 〃 (same note as above) |
| `min_background_balance` | `0.3` |  | 〃 (same note as above) |
| `close_radius_um` | `0.4` | µm | Morphology (radius in µm, at least _min_px): closing bridges gaps in a faint wall, opening detaches small debris touching the test. |
| `close_radius_min_px` | `3` | px | 〃 (same note as above) |
| `open_radius_um` | `0.4` | µm | 〃 (same note as above) |
| `open_radius_min_px` | `3` | px | 〃 (same note as above) |
| `smooth_um` | `1.0` | µm | Final outline smoothing (Gaussian sigma, µm; 0 = off). Same physical scale at every resolution; removes pixel jaggedness and edge noise, rounds off details narrower than ~this, keeps the aperture corners. Needs the calibration. The crop (straight-edge) check uses the mask before smoothing. |
| `min_area_frac` | `0.02` | fraction | Plausibility checks (fraction of the picture area); outside -> "check". |
| `max_area_frac` | `0.9` | fraction | 〃 (same note as above) |
| `max_second_object_frac` | `0.3` | fraction | Only the largest object is measured. Another object larger than this fraction of it (a second test, a large piece of debris) -> "check". |
| `max_straight_edge_px` | `60` | px | Longest allowed perfectly vertical/horizontal outline stretch (px; a pixel-grid test: at low resolution curved edges give longer exact runs, so a µm threshold over-flags); longer -> "check" (test probably cut by a picture crop). Flat apertures seen exactly edge-on are ~40-50 px in typical figures, hence 60. |
| `edge_band_max_frac` | `0.25` | fraction | Flat bands along the picture edges (frame of a figure or screenshot): whole rows/columns of one colour (grey std &lt;= edge_band_max_std) that differ from the background, up to this fraction of the picture size, are left out and count as the picture edge (a figure panel cut out with a margin of the page or plate around it). |
| `edge_band_max_std` | `2.0` |  | 〃 (same note as above) |
| `edge_line_frac` | `0.015` | fraction | A thin frame line just inside a band or the picture edge (the panel's own border around a drawing, often not flat: drawn or slightly tilted), up to this fraction of the picture size (at least 3 px), is part of the frame when it is clearly darker or lighter than the background after it. 0 = off. |
| `wall_ring_radii_um` | `[1.0, 2.0, 4.0]` | µm | Pale, thin wall (hyaline shells, DIC, faint drawings): when the mask follows the contents, the broken wall line is closed with disks of these radii (µm; at least 3 px) and the whole test kept if it is at least wall_ring_min_gain x larger and its outline lies on wall pixels for at least wall_ring_min_support of its length. [] turns it off. |
| `wall_ring_min_gain` | `1.25` |  | 〃 (same note as above) |
| `wall_ring_min_support` | `0.85` |  | 〃 (same note as above) |
| `wall_ring_delta_e` | `12.0` |  | Second pass for fainter walls: around the result of the first pass, the wall pixels at this lower ΔE are closed the same way, and kept on the same conditions (growth at least wall_ring_min_gain, support, no picture frame). |

## Aperture and start point (`landmark`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `snap_tolerance_um` | `2.0` | µm | Start point precedence: landmarks.csv (image,x,y) > automatic aperture corner > fallback. CSV points are snapped to the nearest outline pixel; if further than this (µm, at least _min_px) the picture is flagged "check". |
| `snap_tolerance_min_px` | `15` | px | 〃 (same note as above) |
| `min_elongation` | `1.05` |  | Aperture detection (elongated tests with the aperture seen in profile): major/minor axis; rounder -> no aperture (ovoid tests still have one) |
| `end_frac` | `0.15` | fraction | length fraction used to compare end widths |
| `max_width_ratio` | `0.97` |  | narrow/wide end width must be below this |
| `corner_region_frac` | `0.25` | fraction | search corners in this fraction near the aperture end |
| `corner_scale_frac` | `0.0125` | fraction | outline span (fraction of perimeter) for corner angle |
| `min_corner_turn_deg` | `22` | ° | both corners must turn at least this much |
| `corner_strong_frac` | `0.8` | fraction | Which corner on each side: of the corners turning at least this fraction of the sharpest one, the one nearest the end (the rim, not a sharper bump or debris further up the side); 1 = the sharpest corner. |
| `corner_min_lateral_frac` | `0.3` | fraction | A corner lies at least this fraction of the narrow end's half-width out from its middle (not the tip of a domed or pointed rim); 0 = off. |
| `spine_opening_frac` | `0.06` | fraction | Spines and teeth: corners are searched on the outline with everything narrower than a disk of this radius (x the test's minor axis) cut off, so they lie at the spine bases, then put back on the sharpest point of the real outline nearby. 0 = off. |
| `corner_pair_fallback` | `true` |  | When the rule above finds no aperture (round test, ends of almost equal width, no clear corners): the aperture is taken as the pair of sharp corners (each turning at least min_corner_turn_deg) at most corner_pair_max_arc_frac of the perimeter apart along the outline, the pair whose weaker corner is the sharpest (e.g. the collar of Nebela flabellulum). Flagged "check". corner_pair_fallback: false turns this off. |
| `corner_pair_max_arc_frac` | `0.25` | fraction | 〃 (same note as above) |
| `fallback` | `max_radius` |  | No aperture found (e.g. round Centropyxis): "max_radius" = start at the outline point furthest from the centroid (flagged "check"), or "flag". |
| `cut_contact_um` | `1.4` | µm | Test cut by the picture border: from this length of outline (µm, at least _min_px) on one picture edge, no automatic aperture (it may be outside the picture); the landmark fails until the aperture corners are set by hand. |
| `cut_contact_min_px` | `10` | px | 〃 (same note as above) |

## Radial profile (`rays`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `angle_step_deg` | `5` | ° | Angle between rays, clockwise from the start landmark (ray 0). |
| `intersection` | `last` |  | If a ray crosses the outline several times (non star-shaped outline): "last" = outermost crossing, "first" = innermost. Picture flagged "check". |

## File names (`metadata`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `separator` | `'[_\s]+'` |  | File names: "Genus_species_&lt;bar>um_&lt;id>.ext" or "&lt;bar> Genus species.ext". Parts are split on this regular expression (underscores and/or spaces). Bar length from the name is used unless calibration_overrides.csv gives one; missing parts -> status "check". |

## Outline profile (`outline_profile`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `n_points` | `250` |  | Outline profile: points equally spaced along the outline, anchored on the aperture corners (ta_morpho/outline_profile.py). 250 points; the aperture gets 22 points, the body the rest. |
| `n_aperture` | `22` |  | 〃 (same note as above) |
| `fundus_anchor` | `true` |  | Third anchor at the fundus (aboral end of the oral-aboral axis): the body is split in two sides of equal point count (114 + 114), so left and right sides of different specimens correspond (landmarks: points 0, 22, 136). |

## Classic measurements (`classic`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `lip_margin` | `0.03` |  | Classic measurements in broad view (ta_morpho/classic.py), along the oral-aboral axis: from the aperture midpoint through the middle of the far end of the test, or through a fundus set by hand (same rule; no snap to the perpendicular of the aperture, the aperture angle gives the tilt). ignore sections this close (x length) to the aperture plane |
| `neck_window` | `0.08` |  | +- window (x length) for the width-profile slope |
| `min_neck_slope_jump` | `0.5` |  | steepening of the width profile that marks a neck-body junction |
| `min_neck_start` | `0.08` |  | junction not closer than this (x length) to the oral end; no effect below 2 x neck_window (searched from there) |
| `section_step_px` | `1.0` | px | spacing of the width sections (px: sampling of the pixel outline) |
| `fundus_far_frac` | `0.1` | fraction | far end of the test (the axis goes through its middle) = outline within this fraction of the largest distance from the aperture midpoint |

## Holes and bumps added by hand (`features`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `turn_um` | `5.0` | µm | Measurement of the holes and bumps added by hand (ta_morpho/features.py). curvature measured over +- this distance along the outline; also the default circle radius of a new hole/bump |
| `flank_um` | `0.2` | µm | bump in a circle: measured from the concave stretches at least this deep on each side |
| `step_um` | `0.1` | µm | outline resampling step |
| `match_pct` | `3.0` | % | A hole/bump added in a CSV with its centre only (no radius_px) is the nearest concave stretch (hole) or convex stretch between two concave ones (bump) within match_pct % of the perimeter; such a bump is not wider than bump_max_um (and bump_max_frac x perimeter) and is not within corner_um of an aperture corner. |
| `bump_max_um` | `40.0` | µm | 〃 (same note as above) |
| `bump_max_frac` | `0.15` | fraction | 〃 (same note as above) |
| `corner_um` | `1.5` | µm | 〃 (same note as above) |

## Shape descriptors (`descriptors`)

| Setting | Value | Unit | What it does and why |
|---|---|---|---|
| `n_harmonics` | `5` |  | Shape descriptors (ta_morpho/descriptors.py): harmonics h1..h&lt;n> and the symmetry index use a fine radial profile, independent of rays.angle_step_deg. |
| `fine_step_deg` | `1.0` | ° | 〃 (same note as above) |

