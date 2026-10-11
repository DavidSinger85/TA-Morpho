# Methods

How each step of TA-Morpho works and why its settings have their values. All
settings are in [`ta_morpho/config.yaml`](../ta_morpho/config.yaml), listed with their
values in [`PARAMETERS.md`](PARAMETERS.md); every output column is described in
[`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).

The method is deterministic (no machine-learning model): the same picture and
the same settings always give the same results. Coordinates are in pixels of
the original picture, x to the right and y downwards; "clockwise" is as
displayed. Lengths in the settings are given in µm and converted with each
picture's calibration, with a floor in pixels so that on low-resolution
pictures they never fall below the pixel noise; a picture without calibration
uses 7 px/µm for these conversions (`uncalibrated_px_per_um`), and its µm
results stay empty.

## 1. Calibration

- **Scale bar.** The bar is searched for in the picture: dark, light or
  coloured; elongated (length / thickness ≥ 3, which accepts the short thick
  bars of small figure panels); rectangular (≥ 85 % of its bounding box); on
  plain background; with text glyphs touching it removed by a horizontal
  opening. A candidate must also make up at least half of its connected shape:
  a bar does (a touching label adds a little), the horizontal stroke of a
  letter such as "4" does not. Only horizontal bars are detected. When several
  bar-shaped objects are found, the longest is used and the specimen is
  flagged `check` ("N bar candidates").
- **Bar length** (µm) is read from the file name (`20 Nebela collaris.png`,
  `Nebela_collaris_20um_01.png`). A bare leading number counts as the bar
  length only between 5 and 500 µm, so a counter such as `003_` is not taken; a
  length with a unit outside that range is used but flagged. No length in the
  name: the default 25 µm is used and the specimen flagged. The label written
  on the bar is not read.
- **Calibration table** (command line, `calibration.overrides_csv`; columns
  `image`, `px_per_um`, `bar_length_um`): per picture, the resolution (for
  pictures whose bar is elsewhere, e.g. on the figure plate) or the bar length.
  In the desktop program, a scale drawn by hand along the bar is kept in the
  picture's correction file (`cells/<picture>.csv`) with its line, and used
  the same way (`calibration_source` = `manual`).
- **Uncertainty.** ± 1 px on the bar length gives the percentage in
  `calibration_uncertainty_pct`; every length in µm carries it (areas twice).
- **No bar found:** status `check` and every µm value left empty. Ratios and
  pixel values are still given.

## 2. Outline of the test

- **Background and test.** The background colour is estimated from a 10 px
  frame around the picture. A pixel belongs to the test when its colour differs
  from the background by more than ΔE = 15 (CIE76), which ignores the faint
  glow along edges in SEM pictures.
- **Background type,** per picture, from a band inside the edge of a first
  mask: a wall darker than the background means a light background
  (bright-field microscopy), otherwise a dark one (SEM, dark-field). On a light
  background only darker or differently coloured pixels count as test, which
  leaves out the bright halo outside the wall. When the band is neither clearly
  darker nor clearly lighter, the general rule is used and the picture flagged.
  On the command line the type can be set per picture
  (`segmentation.background_overrides_csv`; columns `image`, `background` =
  `light` or `dark`; `background_source` = `override`).
- **Figure frames.** Flat bands along the picture edges (the margin of a page
  or plate around a panel cut out of a figure, the frame of a screenshot: whole
  rows or columns of one colour, up to 25 % of the picture) are left out and
  count as the picture edge, so they are neither glued to the test nor taken
  for it. Two nested frames are both left out, and a thin frame line just
  inside them (a drawing's own border) too.
- **Clean-up.** Closing and opening with a disk of 0.4 µm (at least 3 px)
  bridge small gaps in the wall and detach small debris; holes are filled and
  the largest object is kept. Another object larger than 30 % of it is
  flagged.
- **Pale, thin walls** (hyaline tests, DIC, faint drawings). The wall is then
  a thin, broken line barely different from the background, and the largest
  object is the cell contents. The wall pixels are closed with disks of 1, 2
  and 4 µm and the test inside them filled; the result is kept only when it is
  at least 1.25 times the first mask, lies on wall pixels along at least 85 %
  of its outline (so it follows a wall that is really there) and has no long
  straight edge (a picture frame). A second pass does the same around this
  result with fainter wall pixels (ΔE > 12). The change is noted in the
  messages.
- **Smoothing.** The outline is smoothed with a Gaussian of σ = 1 µm (the
  same physical scale at every resolution): it removes the pixel staircase and
  annotation residue and keeps the aperture corners.
- **Outline drawn by hand** (desktop program, or a mask file): used as drawn,
  without smoothing (`mask_source` = `manual`); only its largest part is kept,
  with holes filled.
- **Checks** (status `check`): implausible area (below 2 % or above 90 % of
  the picture); test touching the picture edge; a perfectly straight outline
  stretch longer than 60 px (the test is probably cut by the crop; a flat
  aperture between the two corners is excused).

## 3. Centroid

The mean of the pixel coordinates of the final outline's area. The rays and
the symmetry index start from it.

## 4. Aperture and start point

- **Which end.** On an elongated test (major / minor axis ≥ 1.05), the
  aperture is at the narrower end of the long axis (end width ratio < 0.97).
  These limits also accept ovoid tests, whose ends differ only a little.
- **Corners.** On each side of the axis near that end, the aperture corner is
  the outline turn nearest the end among those at least 0.8 times as sharp as
  the sharpest one on that side (and turning ≥ 22°): the rim, not a sharper
  bump or piece of debris further up the side. A corner must lie at least
  0.3 times the end's half-width out from its middle, so the tip of a domed or
  pointed rim is not taken.
- **Spines and teeth.** Everything narrower than a disk of radius 0.06 × the
  minor axis is cut off before the corners are searched, so the end is chosen
  without the spines and the corners lie at the spine bases (the aperture is
  the opening at the bases). Each corner is then put back on the sharpest point
  of the real outline within that radius.
- **Round tests.** When the test is not elongated enough, the aperture is the
  closest pair of sharp corners (e.g. a collar); flagged `check`.
- **Start point** (ray 0, point 0 of the outline profile): the aperture corner
  from which a clockwise sweep crosses the aperture first.
- **Test cut by the picture edge:** no automatic aperture (it may lie outside
  the picture); the corners must be set by hand.
- **No aperture found:** the start is the outline
  point furthest from the centroid, the length and width are taken along the
  principal axis, and the specimen is flagged `check`. The other classic
  measurements, the outline profile and the holes and bumps are not measured.
- **Set by hand** (desktop program, or `landmarks.csv`): the two aperture
  corners (any order; the start follows the clockwise rule) and the fundus
  (the end of the test opposite the aperture, § 6).
  Corners placed near the outline go onto it; corners placed further off stay
  where they are (e.g. at the base of a spine). Recorded as `landmark_source`
  = `manual`.

## 5. Radial profile

Rays from the centroid every 5° (72 rays), clockwise from the start point,
give the distance to the outline in µm (`r0` … `r355` in `summary.csv`), and
in the extra tables also in pixels, ÷ the mean ray length and ÷ √area. When a
ray crosses the outline several times (an outline that is not star-shaped
around the centroid, e.g. horns curving over the body), the outermost crossing
is used, the number of crossings is given per ray (`n_crossings`) and the
specimen is flagged. Finer detail of the outline is given by the outline
profile (§ 8), not by more rays.

## 6. Oral–aboral axis and classic measurements

**Axis.** All classic measurements are taken along the line from the aperture
midpoint (the middle of the line between the two corners) through the middle
of the far end of the test. The far end is the stretch of outline within 10 %
of the largest distance from the aperture midpoint; its points are averaged,
weighted by outline length, so a flat or round fundus gives its middle and a
single far bump does not dominate. The far end is searched on the outline
without its spines and horns (the same cut as in § 4), so a spine at the
fundus does not pull the axis to its side. The **fundus** is where the axis
leaves the real outline.

On a symmetric test this axis is perpendicular to the aperture, as in the
literature (e.g. Kosakyan et al. 2025); on a curved body or a
bent neck it reaches the far end instead of a flank. As for *Cyphoderia*
(Todorov et al. 2009), the length is a straight overall length, and the tilt
of the aperture is given separately as the **aperture angle**
(`aperture_angle_deg`, between the aperture line and the axis; 90° = square).

A fundus set by hand is the point the axis goes through, in place of the
middle of the far end: the same rule and the same code follow. A hand point
on the aperture side of the aperture gives no direction; the axis is then
perpendicular to the aperture and the specimen flagged.

**Measurements.**
- **Length:** aperture to fundus, lips included. **Width:** largest extent
  across the axis. **Aperture width:** corner to corner.
- **Widest position:** distance from the oral end of the outline to the widest
  section ÷ length (0 = oral end, 1 = fundus); the same from the aperture
  line (`widest_position_aperture`), which differs only when the lips protrude
  beyond the corners.
- **Neck,** only when the test has one. Along the axis, the section width of a
  necked test stays nearly constant and then rises abruptly where the neck
  meets the body. The width profile (section width ÷ test width, against level
  ÷ length; both dimensionless, so the rule does not depend on size or
  resolution) is differentiated over ± 8 % of the length; the neck–body
  junction is the level where the slope increases most, by at least 0.5,
  searched from 16 % of the length (from the oral end; twice the slope window)
  to 8 % before the widest section. Neck length = aperture line
  to junction; neck width = narrowest section in between (sections within 3 %
  of the length of the aperture line are ignored: they only clip a lip).
  Without a calibration the neck is still found and given as ratios.
- **Size and shape:** area, perimeter, circularity (4πA/P²), solidity (area ÷
  convex hull area), Feret maximum and minimum, centroid size (§ 8), and the
  ratios W/L, AW/L, AW/W, NL/L, NW/L, NL/W, NW/W, NL/AW, NW/AW, NW/NL.
- Depth, and therefore volume, is not measured (it needs a lateral view).

## 7. Genus characters

The diagnostic characters of the hyalospheniid genera (Kosakyan et al. 2025;
[`CHARACTERS.md`](CHARACTERS.md), reference table
[`genus_characters.csv`](../ta_morpho/genus_characters.csv)) are recorded for every
specimen in two ways.

**Described** (material, plate shape, lateral pores, keel, horns and
expansions, neck, aperture in broad and narrow view, aperture margin,
compression, fundus; columns `ch_…`): when the genus, read from the file name or
set by hand, is in the table, the specimen starts with its genus's values; any
of them can be set by hand for the specimen (desktop program: Review >
Characters; command line: `characters.csv`). The program does not detect them:
a value is the genus's or the user's (`characters_by_hand` lists the latter),
and a genus not in the table gives no values.

**Measured** on the outline, as numbers for every specimen, without labels:

- `neck_jump`: the neck criterion of § 6 as a number, also below the 0.5
  threshold: a gradual taper scores low, a distinct neck high.
- `aperture_sag`: curvature of the rim, the largest signed distance of the
  outline between the two corners from the line joining them, ÷ aperture
  width: positive for a convex rim, about 0 for a straight one, negative for a
  sunken one.
- `n_protrusions` and `protrusion_levels`: horns and spines, the pieces cut off
  by the opening of § 4 when they are longer than twice its radius, with the
  level of each along the axis (0 = aperture line, 1 = fundus). Pieces
  reaching below 0.1 belong to the aperture end itself (lips, teeth, a narrow
  neck) and are left out.

## 8. Shape descriptors, outline profile and geometric morphometrics

**Shape descriptors.** Mean ray length and its coefficient of variation (from
the rays of § 5); harmonic amplitudes h1–h5 of the radius ÷ mean radius
(h2 = elongation, h3 = unequal ends) and the symmetry index (mean
|r(axis + θ) − r(axis − θ)| ÷ mean radius, about the line from the centroid to
the aperture midpoint; 0 = symmetric), both from a 1° profile so that they do
not depend on the ray step.

**Outline profile.** 250 points on the outline, on three anchors:
- point 0: start aperture corner; points 0–21 across the aperture;
- point 22: the other aperture corner; points 22–135 on the first side;
- point 136: the fundus (§ 6); points 136–249 on the second side;
- equally spaced within each stretch.

Every specimen has the same number of points and the anchors are always the
same point numbers, so profiles can be compared column by column, and the
sides of different specimens correspond even when a test is not symmetric.
`outline_profile.csv` gives the distance of each point from the centroid.

**Geometric morphometrics.** The same 250 points are written as coordinates in
tpsDig format (`outline_coordinates.tps`; pixels, y up, `SCALE` = µm per pixel)
with a slider definition for geomorph (`outline_sliders.csv`, Adams &
Otárola-Castillo 2013): points 1, 23 and 137 (counted from 1) are fixed
landmarks, all others semilandmarks sliding on the closed outline, a scheme
like that of Macumber et al. (2020). Centroid size (square root of the summed
squared distances of the points from their centroid) is in `summary.csv`; it
depends on the number of points. Because the points are equally spaced within
each stretch, the aperture weighs a little more than its share of the
perimeter.

## 9. Holes and bumps

Outline features such as a neck–body constriction or bumps on the neck are
**added by hand** (desktop program, or `feature_corrections.csv`); they are
not detected automatically. Without them `n_holes` and `n_bumps` are 0.

- A feature is a centre on the outline and a circle (default radius 5 µm). It
  is measured on the outline inside the circle: a hole's depth from the line
  joining its two rims (on each side of the centre, the most outward point); a
  bump's height from the line joining the deepest points of the concave
  stretches flanking it (else the circle's ends); width = outline length
  between these two points. A hole where the outline does not go inward, or a
  bump where it does not go outward, is refused.
- A row of `feature_corrections.csv` without a circle gives the centre only:
  the nearest concave stretch (hole) or convex stretch between two concave ones
  (bump) within 3 % of the perimeter is measured.
- Each feature is placed in the frame of the other outputs: position along the
  perimeter (clockwise from the start point), ray angle, nearest point of the
  outline profile and its stretch (aperture, side 1, side 2; clockwise as
  displayed, not a biological left and right), level along the axis
  (0 = aperture line, 1 = fundus) and region (aperture, neck, neck–body
  junction, body).
- Per specimen: counts per region and per stretch, summed depth or height per
  region, and the first five features one by one (`f1` … `f5`).

## 10. Status and corrections

Each specimen gets a status: `ok`, `check` (look at the cell figure; the
reasons are in `messages`) or `failed` (values left empty). A specimen
flagged `check` whose figure is right can be accepted after a visual check,
with a note: its status becomes `ok`, and its automatic status and messages
stay in `summary.csv`. Every correction made by hand is recorded by the step it
changed (`calibration_source`, `bar_length_source`, `mask_source`,
`background_source`, `landmark_source`, `fundus_source`, and
`characters_by_hand` for the characters) and listed together in the
`corrections` column; a specimen with an empty `corrections` has a fully
automatic result. All values are per specimen: statistics across specimens are
left to the analysis of `summary.csv` (e.g. in R).

## Known limitations

- **Tested scope:** hyalospheniids in broad view with a terminal aperture.
  On other groups the outline is usually found, but the aperture and the axis
  often are not; the method was not tested on them. The aperture is always
  searched on the outline: tests seen from below, with the aperture inside the
  outline, are not measured correctly.
- **One test per picture, on a uniform background:** the background colour is
  taken from the picture frame. Debris touching the test is part of the
  outline unless the opening detaches it; remove it with the eraser in Review.
- **Ends of almost equal width:** on such tests the narrower end may not be
  the aperture; the aperture is then taken as the closest pair of sharp
  corners and the specimen flagged `check`.
- **Drawn lines** in a drawing can be taken for a scale bar: a drawing
  without a scale should have empty µm values; check the calibration of
  drawings in their cell figures.
- On a light background, pixels of another colour count as test even when
  lighter than the background, so a coloured fringe (chromatic aberration) can
  enlarge the outline slightly.
- A long, perfectly straight outline stretch (e.g. a regular drawn neck) is
  flagged as a possible crop.
- Mirror images are not equivalent: the start corner and the direction of the
  profiles follow the clockwise rule as displayed, so a test photographed from
  the other side gives its profile in reverse order.
- Only horizontal scale bars are detected; strong shadows or DIC relief are
  not handled specially; depth and volume are not measured.

## References

- Adams D.C., Otárola-Castillo E. (2013) geomorph: an R package for the
  collection and analysis of geometric morphometric shape data. *Methods in
  Ecology and Evolution* 4: 393–399.
- Kosakyan A., Meisterfeld R., Lara E., Duckert C., Mitchell E.A.D. (2025) A
  taxonomic monograph of hyalospheniid testate amoebae (Amoebozoa:
  Arcellinida: Hyalospheniformes). Mémoires de la Société neuchâteloise des
  sciences naturelles, tome XIV. Alphil-Presses universitaires suisses, Neuchâtel.
  https://doi.org/10.33055/alphil.00614
- Macumber A.L., Roe H.M., Prentice S.V., Sayer C.D., Bennion H., Salgado J.
  (2020) Freshwater testate amoebae (Arcellinida) response to eutrophication as
  revealed by test size and shape indices. *Frontiers in Ecology and
  Evolution* 8: 568904.
- Todorov M., Golemansky V., Mitchell E.A.D., Heger T.J. (2009) Morphology,
  biometry, and taxonomy of freshwater and marine interstitial *Cyphoderia*
  (Cercozoa: Euglyphida). *Journal of Eukaryotic Microbiology* 56: 279–289.
